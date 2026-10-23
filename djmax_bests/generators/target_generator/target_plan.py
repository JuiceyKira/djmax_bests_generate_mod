"""Plan a target DJPower: work out which records to play so a button's total reaches a goal.

The model follows how the game computes a button's total DJPower:

    total = floor((sum of the best 70 "basic" + best 30 "new" record djpower) * convert_constant, 4)

with `convert_constant = 10000 / maxpower` and one record per (songid, pattern), so a chart only
matters while it is inside its bucket's top 70 / 30.

Given a target total, an accuracy the player expects to reach, and an optional difficulty cap,
this module projects the *final* top 70 + 30: which cards stay untouched, which ones only get a
better score, and which ones newly make the list. Those two task kinds are told apart by the
*list*, not by whether a record exists:

    'improve'  the record already sat in its bucket's top 70 / 30
    'new'      the chart was outside the list and now makes the cut -- record or not

Charts are chosen cheapest-difficulty-first -- many easy charts rather than a few hard ones --
and the fill stops as soon as the goal is covered, so the result lands close to the target
instead of overshooting with the hardest available charts.

The gap between the current total and the target is shared by the two buckets, and that split is
searched rather than fixed: a split is accepted once both buckets end up with a similar *task
difficulty mean*, so a bucket sitting on cheap unfilled slots ("new" often has fewer than 30
records) takes pressure off the other one instead of one bucket carrying everything.

Difficulty axis (ordering only, never displayed unless the chart really has a floor):

    real floor when the chart has one (floorName, kept as level*10 + tier: 8.2 -> 82)
    otherwise the official design equivalence, extended below the floor scale

The design equivalence maps a chart onto the SC level with the same diff_coeff, whose floor is
that level .1: a non-SC level L carries the same diff_coeff as SC level 2L-22, so

    non-SC Lv12 -> SC2 -> 2.1     Lv13 -> 4.1     Lv14 -> 6.1     Lv15 -> 8.1
    SC n        -> n.1

The same rule keeps counting below the game's own floor scale, which bottoms out at 1.1: Lv11
lands on 0.1 and every level below that turns negative (Lv1 -> -19.9). That matters because a
single clamped value would make every chart of level <= 11 equally "easy", which distorts both
the cheapest-first ordering and the mean the two buckets are balanced on. The mapping depends
only on the level and pattern type, so one level has the same floor in every button mode.

DJPower gains come in three flavours, and they are not interchangeable:

    already inside the bucket's top K   -> potential - current value (nothing is displaced)
    has a record below the cutoff       -> max(0, potential - cutoff)
    never played                        -> potential - cutoff (cutoff is 0 while slots are empty)
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass, field
from decimal import ROUND_FLOOR, Decimal

import pandas as pd

from ... import api_handler, models, util
from ...analyzer import data_analyzer
from . import accuracy_table

BEST_BASIC_LIMIT = 70
BEST_NEW_LIMIT = 30
TOTAL_LIMIT = Decimal("10000.0000")
MIN_RECORD_SCORE = Decimal("90")

#: ordering key of a chart with no tasks at all; a real key is never 0 for a level-based floor
NO_DIFFICULTY = 0
#: the lowest floor the game's own scale uses (1.1) -- the design mapping keeps counting below it
FLOOR_SCALE_BOTTOM = 11


# --------------------------------------------------------------------------------------
# difficulty axis
# --------------------------------------------------------------------------------------
def design_floor_units(level: int, is_sc: bool) -> int:
    """Official-design floor of a chart without a real floorName, in floor*10 units.

    A chart maps onto the SC level with the same diff_coeff, whose floor is that level .1, and
    the rule keeps counting below the bottom of the game's scale (Lv11 -> 0.1, Lv1 -> -19.9).
    """
    if is_sc:
        return level * 10 + 1
    return (2 * level - 22) * 10 + 1


def difficulty_key(level: int, is_sc: bool, floor_units: int | None) -> int:
    """Ordering key: the real floor when the chart has one, the design equivalence otherwise."""
    if floor_units is not None:
        return int(floor_units)
    return design_floor_units(level, is_sc)


def format_difficulty(key: int) -> str:
    """Human-readable difficulty key ('4.1', '-1.9', '0.1')."""
    sign = "-" if key < 0 else ""
    value = abs(key)
    return f"{sign}{value // 10}.{value % 10}"


def format_mean_difficulty(value: Decimal | None) -> str:
    """Human-readable mean difficulty key ('4.15', '-2.30', or '-' when there are no tasks)."""
    if value is None:
        return "-"
    return f"{value / 10:.2f}"


def _q(value: Decimal) -> Decimal:
    """Round a derived number for display: record sums are exact, deficits are divisions."""
    return value.quantize(Decimal("0.0001"))


# --------------------------------------------------------------------------------------
# per-chart data
# --------------------------------------------------------------------------------------
@dataclass
class Pattern:
    """One chart of one button, the player's record on it, and the planned value on top."""
    songid: int
    title: str
    pattern: str
    level: int
    dlc_code: str
    is_new: bool
    is_sc: bool
    max_djpower: Decimal
    difficulty: int
    coeff: int = 0                          # diff_coeff, the design difficulty of the chart
    floor: Decimal | None = None            # the real floorName, None when the chart has none
    floor_estimated: bool = False           # difficulty comes from the estimate, not a real floor
    record_djpower: Decimal | None = None   # the player's current record, None when unplayed
    record_score: Decimal | None = None
    record_max_combo: bool = False
    in_current_top: bool = False            # does the record already sit in its bucket's top 70/30?
    planned_djpower: Decimal | None = None  # set while filling; None means "keep the record"

    @property
    def played(self) -> bool:
        return self.record_djpower is not None

    @property
    def value(self) -> Decimal | None:
        """The DJPower this chart contributes after the plan (None: not in any list)."""
        return self.planned_djpower if self.planned_djpower is not None else self.record_djpower

    @property
    def task(self) -> str:
        """'' (untouched) | 'improve' (already listed, score raised) | 'new' (enters the list).

        The distinction is about the *list*, not about whether a record exists: a chart that
        was already inside its bucket's top 70/30 and only gets a better score is 'improve',
        while one that was outside it and now makes the cut is 'new' -- even if the player had
        already played it before.
        """
        if self.planned_djpower is None:
            return ""
        if self.record_djpower is not None and self.planned_djpower <= self.record_djpower:
            return ""
        return "improve" if self.in_current_top else "new"

    def potential(self, ratio: Decimal) -> Decimal:
        """DJPower this chart is worth at the planned accuracy, floored like the game does."""
        return (ratio * self.max_djpower).quantize(Decimal("0.0001"), rounding=ROUND_FLOOR)


@dataclass
class PlanEntry:
    """One card of the projected top 100."""
    pattern: Pattern
    djpower: Decimal
    score: Decimal
    task: str

    @property
    def is_task(self) -> bool:
        return self.task != ""

    def to_song(self) -> models.DMSong:
        return models.DMSong(
            songid=self.pattern.songid,
            title=self.pattern.title,
            pattern=self.pattern.pattern,
            level=self.pattern.level,
            score=self.score,
            max_combo=self.pattern.record_max_combo if self.task == "" else False,
            djpower=self.djpower,
            dlc_code=self.pattern.dlc_code,
        )


@dataclass
class BucketPlan:
    name: str
    limit: int
    current_sum: Decimal
    required_sum: Decimal
    deficit: Decimal
    capacity: Decimal
    achieved_sum: Decimal
    entries: list[PlanEntry] = field(default_factory=list)

    @property
    def tasks(self) -> list[PlanEntry]:
        return [entry for entry in self.entries if entry.is_task]

    @property
    def improved(self) -> list[PlanEntry]:
        """Cards that were already listed and only got a better score."""
        return [entry for entry in self.entries if entry.task == "improve"]

    @property
    def added(self) -> list[PlanEntry]:
        """Cards that were outside the list and now make the cut (record or not)."""
        return [entry for entry in self.entries if entry.task == "new"]

    @property
    def task_difficulties(self) -> list[int]:
        return [entry.pattern.difficulty for entry in self.tasks]

    @property
    def task_mean_difficulty(self) -> Decimal | None:
        """Mean difficulty key of this bucket's tasks (None when it has none)."""
        keys = self.task_difficulties
        if not keys:
            return None
        return Decimal(sum(keys)) / Decimal(len(keys))

    @property
    def task_max_difficulty(self) -> int:
        return max(self.task_difficulties, default=NO_DIFFICULTY)


@dataclass
class TargetPlan:
    username: str
    bmode: int
    accuracy: Decimal
    target_total: Decimal
    floor_cap: Decimal | None
    convert_constant: Decimal
    maxpower: Decimal
    ratio: Decimal
    basic: BucketPlan
    new: BucketPlan
    achieved_total: Decimal
    ceiling: Decimal                  # ceiling at this accuracy, no difficulty cap
    ceiling_capped: Decimal           # ceiling actually available to this plan
    min_accuracy: Decimal | None
    reachable: bool
    #: minimum accuracy ignoring the difficulty cap (equals `min_accuracy` when there is no cap)
    min_accuracy_uncapped: Decimal | None = None
    basic_share: Decimal | None = None    # share of the gap the basic bucket was given
    balance_rounds: int = 0               # splits tried while balancing (0 = balancing off)
    notes: list[str] = field(default_factory=list)

    @property
    def entries(self) -> list[PlanEntry]:
        return self.basic.entries + self.new.entries

    @property
    def tasks(self) -> list[PlanEntry]:
        return self.basic.tasks + self.new.tasks

    @property
    def task_count(self) -> int:
        return len(self.tasks)

    @property
    def improved_count(self) -> int:
        return len(self.basic.improved) + len(self.new.improved)

    @property
    def added_count(self) -> int:
        return len(self.basic.added) + len(self.new.added)

    @property
    def max_task_difficulty(self) -> int:
        return max((entry.pattern.difficulty for entry in self.tasks), default=NO_DIFFICULTY)

    @property
    def current_total(self) -> Decimal:
        """The total the button has right now, before anything is played."""
        return total_from_raw(self.basic.current_sum + self.new.current_sum, self.convert_constant)

    def to_dmbests(self) -> models.DMBests:
        """The projected top 100 in the shape the bests renderer already understands."""
        return models.DMBests(
            username=self.username,
            bmode=self.bmode,
            basic=[entry.to_song() for entry in self.basic.entries],
            new=[entry.to_song() for entry in self.new.entries],
        )

    def summary(self) -> dict:
        """Everything worth keeping for logs/UI, including data that is not drawn on the card."""
        return {
            "username": self.username,
            "bmode": self.bmode,
            "target_total": self.target_total,
            "accuracy": self.accuracy,
            "floor_cap": self.floor_cap,
            "reachable": self.reachable,
            "achieved_total": self.achieved_total,
            "current_total": self.current_total,
            "ceiling": self.ceiling,
            "ceiling_capped": self.ceiling_capped,
            "min_accuracy": self.min_accuracy,
            "min_accuracy_uncapped": self.min_accuracy_uncapped,
            "tasks": self.task_count,
            "raised": self.improved_count,
            "entered": self.added_count,
            "max_task_difficulty": format_difficulty(self.max_task_difficulty),
            "basic_share": self.basic_share,
            "balance_rounds": self.balance_rounds,
            "basic": {
                "cards": len(self.basic.entries), "tasks": len(self.basic.tasks),
                "current_sum": self.basic.current_sum, "achieved_sum": self.basic.achieved_sum,
                "required_sum": _q(self.basic.required_sum), "deficit": _q(self.basic.deficit),
                "capacity": _q(self.basic.capacity),
                "task_mean_difficulty": format_mean_difficulty(self.basic.task_mean_difficulty),
                "task_max_difficulty": format_difficulty(self.basic.task_max_difficulty),
            },
            "new": {
                "cards": len(self.new.entries), "tasks": len(self.new.tasks),
                "current_sum": self.new.current_sum, "achieved_sum": self.new.achieved_sum,
                "required_sum": _q(self.new.required_sum), "deficit": _q(self.new.deficit),
                "capacity": _q(self.new.capacity),
                "task_mean_difficulty": format_mean_difficulty(self.new.task_mean_difficulty),
                "task_max_difficulty": format_difficulty(self.new.task_max_difficulty),
            },
            "notes": list(self.notes),
        }

    def describe(self) -> str:
        lines = [
            f"{self.bmode}B  target {self.target_total} @ {self.accuracy}%"
            + (f"  (floor <= {self.floor_cap})" if self.floor_cap is not None else ""),
            f"  achieved total {self.achieved_total}"
            f"  ({'reached' if self.reachable else 'BEST EFFORT, target not reachable'})",
            f"  ceiling at this accuracy: {self.ceiling}"
            + (f", {self.ceiling_capped} under the difficulty cap"
               if self.floor_cap is not None else ""),
            f"  tasks: {self.task_count} ({self.improved_count} raised in place,"
            f" {self.added_count} entering the list),"
            f" hardest {format_difficulty(self.max_task_difficulty)}",
            f"  basic: {len(self.basic.entries)} cards / {len(self.basic.tasks)} tasks,"
            f" sum {self.basic.current_sum} -> {self.basic.achieved_sum}"
            f" (deficit {_q(self.basic.deficit)} of capacity {_q(self.basic.capacity)}),"
            f" task difficulty mean {format_mean_difficulty(self.basic.task_mean_difficulty)}"
            f" / max {format_difficulty(self.basic.task_max_difficulty)}",
            f"  new:   {len(self.new.entries)} cards / {len(self.new.tasks)} tasks,"
            f" sum {self.new.current_sum} -> {self.new.achieved_sum}"
            f" (deficit {_q(self.new.deficit)} of capacity {_q(self.new.capacity)}),"
            f" task difficulty mean {format_mean_difficulty(self.new.task_mean_difficulty)}"
            f" / max {format_difficulty(self.new.task_max_difficulty)}",
        ]
        if self.min_accuracy is not None:
            lines.append(f"  minimum accuracy for this target: {self.min_accuracy}%")
        lines.extend(f"  note: {note}" for note in self.notes)
        return "\n".join(lines)


# --------------------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------------------
def total_from_raw(raw: Decimal, convert_constant: Decimal) -> Decimal:
    """The game's total DJPower conversion, shared by every total this module reports."""
    total = util.cut_digits(raw * convert_constant, 4)
    return TOTAL_LIMIT if total > TOTAL_LIMIT else total


def _top_sum(values: list[Decimal], limit: int) -> Decimal:
    """Sum of the best `limit` values: a bucket only counts its top 70 / 30."""
    if len(values) <= limit:
        return sum(values, Decimal(0))
    return sum(values[-limit:], Decimal(0))


def _load_patterns(analyzer: data_analyzer.RecordAnalyzer) -> list[Pattern]:
    """Every chart of one button, with the player's record attached when there is one."""
    df = analyzer.data
    floor_units_column = pd.to_numeric(df["floor_name"], errors="coerce") * 10

    patterns: list[Pattern] = []
    for row, floor_units in zip(df.itertuples(), floor_units_column):
        score = None if pd.isna(row.score) else Decimal(str(row.score))
        has_record = score is not None and score >= MIN_RECORD_SCORE
        floor_value = None
        key = None
        if not pd.isna(floor_units):
            key = int(round(float(floor_units)))
            floor_value = (Decimal(key) / 10).quantize(Decimal("0.1"))
        patterns.append(Pattern(
            songid=int(row.songid),
            title=str(row.title),
            pattern=str(row.pattern),
            level=int(row.level),
            dlc_code=str(row.dlc_code),
            is_new=bool(row.is_new),
            is_sc=bool(row.is_sc),
            max_djpower=Decimal(str(row.max_djpower)),
            difficulty=difficulty_key(int(row.level), bool(row.is_sc), key),
            coeff=util.diff_coeff(int(row.level), bool(row.is_sc)),
            floor=floor_value,
            record_djpower=Decimal(str(row.djpower)) if has_record else None,
            record_score=score if has_record else None,
            record_max_combo=bool(row.max_combo) if has_record else False,
        ))

    for pattern in patterns:
        if pattern.floor is None:
            pattern.floor_estimated = True
    return patterns


def _record_sum(patterns: list[Pattern], limit: int) -> Decimal:
    """What the bucket contributes today: only its best `limit` records count."""
    values = sorted(p.record_djpower for p in patterns if p.played)
    return _top_sum(values, limit)


def _mark_current_top(patterns: list[Pattern], limit: int) -> None:
    """Flag the records that already occupy this bucket's top `limit` today.

    Those are the "improve" cards of the plan; everything outside that set becomes a "new"
    card when it makes the projected list, whether or not it has a record.
    """
    ranked = sorted((p for p in patterns if p.played),
                    key=lambda p: (-p.record_djpower, p.songid, p.pattern))[:limit]
    for pattern in ranked:
        pattern.in_current_top = True


def _bucket_ceiling(patterns: list[Pattern], limit: int, ratio: Decimal,
                    cap_units: int | None) -> Decimal:
    """Best achievable bucket sum at `ratio`: play everything allowed, keep whatever is better."""
    values: list[Decimal] = []
    for pattern in patterns:
        best = pattern.record_djpower
        if cap_units is None or pattern.difficulty <= cap_units:
            potential = pattern.potential(ratio)
            if best is None or potential > best:
                best = potential
        if best is not None:
            values.append(best)
    values.sort()
    return _top_sum(values, limit)


def _fill_bucket(patterns: list[Pattern], limit: int, ratio: Decimal, cap_units: int | None,
                 deficit: Decimal) -> tuple[Decimal, int]:
    """Cheapest-difficulty-first fill; sets `planned_djpower` on whatever has to be played.

    Returns (remaining deficit, charts played).
    """
    live: list[Decimal] = sorted(p.record_djpower for p in patterns if p.played)
    remaining = deficit
    played = 0

    candidates = [
        pattern for pattern in patterns
        if (cap_units is None or pattern.difficulty <= cap_units)
        and not (pattern.played and pattern.potential(ratio) <= pattern.record_djpower)
    ]
    candidates.sort(key=lambda p: (p.difficulty, -p.potential(ratio)))

    for pattern in candidates:
        if remaining <= 0:
            break
        potential = pattern.potential(ratio)
        old = pattern.record_djpower
        before = _top_sum(live, limit)
        if old is not None:
            live.pop(bisect.bisect_left(live, old))
        bisect.insort(live, potential)
        gain = _top_sum(live, limit) - before
        if gain <= 0:                           # below the cutoff: playing it changes nothing
            live.pop(bisect.bisect_left(live, potential))
            if old is not None:
                bisect.insort(live, old)
            continue
        pattern.planned_djpower = potential
        remaining -= gain
        played += 1
    return max(remaining, Decimal(0)), played


def _project(patterns: list[Pattern], limit: int, accuracy: Decimal) -> tuple[list[PlanEntry], Decimal]:
    """The bucket's final top `limit` cards and their raw sum."""
    ranked = sorted(
        (p for p in patterns if p.value is not None),
        key=lambda p: (-p.value, p.songid, p.pattern),
    )[:limit]

    entries = [
        PlanEntry(
            pattern=pattern,
            djpower=pattern.value,
            score=accuracy if pattern.task else (pattern.record_score or accuracy),
            task=pattern.task,
        )
        for pattern in ranked
    ]
    return entries, sum((entry.djpower for entry in entries), Decimal(0))


def _min_accuracy(patterns: list[Pattern], cap_units: int | None, target_total: Decimal,
                  convert_constant: Decimal) -> Decimal | None:
    """Smallest accuracy (0.01 steps) whose ceiling already covers the target."""
    basic = [p for p in patterns if not p.is_new]
    new = [p for p in patterns if p.is_new]

    def ceiling(accuracy: float) -> Decimal:
        ratio = accuracy_table.ratio_at(accuracy)
        raw = (_bucket_ceiling(basic, BEST_BASIC_LIMIT, ratio, cap_units)
               + _bucket_ceiling(new, BEST_NEW_LIMIT, ratio, cap_units))
        return total_from_raw(raw, convert_constant)

    if ceiling(100.0) < target_total:
        return None
    if ceiling(90.0) >= target_total:
        return Decimal("90.00")
    low, high = 90.0, 100.0
    for _ in range(20):
        mid = round((low + high) / 2, 2)
        if mid <= low or mid >= high:
            break
        if ceiling(mid) >= target_total:
            high = mid
        else:
            low = mid
    return Decimal(f"{high:.2f}")


# --------------------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------------------
#: bucket task difficulty means closer than this count as balanced (0.1 floor units)
BALANCE_TOLERANCE = Decimal(1)
#: share of the gap the basic bucket gets when balancing is disabled (70 of 100 slots)
DEFAULT_BASIC_SHARE = Decimal("0.7")


@dataclass
class _Attempt:
    """One complete plan at one basic/new split of the gap."""
    share_basic: Decimal | None
    deficit_basic: Decimal
    deficit_new: Decimal
    left_basic: Decimal
    left_new: Decimal
    basic_entries: list[PlanEntry]
    new_entries: list[PlanEntry]
    basic_sum: Decimal
    new_sum: Decimal
    notes: list[str] = field(default_factory=list)

    @staticmethod
    def _mean(entries: list[PlanEntry]) -> Decimal | None:
        keys = [entry.pattern.difficulty for entry in entries if entry.is_task]
        if not keys:
            return None
        return Decimal(sum(keys)) / Decimal(len(keys))

    @property
    def mean_basic(self) -> Decimal | None:
        return self._mean(self.basic_entries)

    @property
    def mean_new(self) -> Decimal | None:
        return self._mean(self.new_entries)

    def signal(self) -> int:
        """+1 when basic is the harder bucket, -1 when new is, 0 when balanced."""
        basic, new = self.mean_basic, self.mean_new
        if basic is None and new is None:
            return 0
        if new is None:
            return 1
        if basic is None:
            return -1
        if basic - new > BALANCE_TOLERANCE:
            return 1
        if new - basic > BALANCE_TOLERANCE:
            return -1
        return 0

    def score(self) -> float:
        """How far apart the two buckets' task difficulties are (used to pick the best split)."""
        basic, new = self.mean_basic, self.mean_new
        if basic is None and new is None:
            return 0.0
        if basic is None or new is None:
            return float("inf")
        return abs(float(basic - new))


def build_plan(bmode: int, target_total: float | Decimal, accuracy: float | Decimal,
               floor_cap: float | Decimal | None = None, *,
               username: str = "Max DJPower",
               analyzer: data_analyzer.RecordAnalyzer | None = None,
               balance: bool = True, balance_rounds: int = 7) -> TargetPlan:
    """Project the top 100 of one button at `target_total`, playing at `accuracy`.

    The gap between the current total and the target is shared by the two buckets. With
    `balance` (the default) the split is searched instead of fixed at 70/30: each candidate
    split is planned completely, and the search keeps the one whose two buckets end up with
    the closest *task difficulty means*, so the bucket with spare cheap capacity takes the
    pressure off the other one. `balance_rounds` caps how many splits are tried.
    """
    if analyzer is None:
        analyzer = data_analyzer.AnalyzeUtil().spawn_analyzer(bmode)

    accuracy = Decimal(str(accuracy)).quantize(Decimal("0.01"))
    target_total = Decimal(str(target_total)).quantize(Decimal("0.0001"))
    floor_cap = None if floor_cap is None else Decimal(str(floor_cap))
    cap_units = None if floor_cap is None else int(round(float(floor_cap) * 10))

    accuracy_table.build_if_missing()
    ratio = accuracy_table.ratio_at(accuracy)
    convert_constant, maxpower = api_handler.get_convert_constant(bmode)

    patterns = _load_patterns(analyzer)
    basic_patterns = [p for p in patterns if not p.is_new]
    new_patterns = [p for p in patterns if p.is_new]
    _mark_current_top(basic_patterns, BEST_BASIC_LIMIT)
    _mark_current_top(new_patterns, BEST_NEW_LIMIT)
    basic_current = _record_sum(basic_patterns, BEST_BASIC_LIMIT)
    new_current = _record_sum(new_patterns, BEST_NEW_LIMIT)

    # ceilings: what playing everything allowed would be worth
    basic_top = _bucket_ceiling(basic_patterns, BEST_BASIC_LIMIT, ratio, cap_units)
    new_top = _bucket_ceiling(new_patterns, BEST_NEW_LIMIT, ratio, cap_units)
    ceiling_capped = total_from_raw(basic_top + new_top, convert_constant)
    if cap_units is None:
        ceiling = ceiling_capped
        basic_top_free, new_top_free = basic_top, new_top
    else:
        basic_top_free = _bucket_ceiling(basic_patterns, BEST_BASIC_LIMIT, ratio, None)
        new_top_free = _bucket_ceiling(new_patterns, BEST_NEW_LIMIT, ratio, None)
        ceiling = total_from_raw(basic_top_free + new_top_free, convert_constant)

    capacity_basic = max(basic_top - basic_current, Decimal(0))
    capacity_new = max(new_top - new_current, Decimal(0))

    notes: list[str] = []
    rounds = 0
    need_raw = target_total / convert_constant
    current_raw = basic_current + new_current
    needed_raw = max(need_raw - current_raw, Decimal(0))

    def attempt(deficit_basic: Decimal, deficit_new: Decimal,
                share_basic: Decimal | None = None) -> _Attempt:
        """Fill both buckets at one split and project the resulting top 70 / 30."""
        for pattern in patterns:
            pattern.planned_djpower = None

        attempt_notes: list[str] = []
        # the "new" pool is the thin one, so its shortfall moves to basic first, and anything
        # basic cannot swallow moves back to new
        if deficit_new > capacity_new:
            deficit_basic += deficit_new - capacity_new
            deficit_new = capacity_new
        if deficit_basic > capacity_basic:
            spare = min(capacity_new - deficit_new, deficit_basic - capacity_basic)
            deficit_basic -= spare
            deficit_new += spare

        left_basic, _ = _fill_bucket(basic_patterns, BEST_BASIC_LIMIT, ratio, cap_units,
                                     deficit_basic)
        left_new, _ = _fill_bucket(new_patterns, BEST_NEW_LIMIT, ratio, cap_units, deficit_new)
        basic_entries, basic_sum = _project(basic_patterns, BEST_BASIC_LIMIT, accuracy)
        new_entries, new_sum = _project(new_patterns, BEST_NEW_LIMIT, accuracy)
        if left_basic > 0 or left_new > 0:
            attempt_notes.append(f"filled every useful chart, still "
                                 f"{_q(left_basic + left_new)} raw short")
        return _Attempt(share_basic, deficit_basic, deficit_new, left_basic, left_new,
                        basic_entries, new_entries, basic_sum, new_sum, attempt_notes)

    if ceiling_capped < target_total:
        # cannot be reached as configured: project the best state we can get to instead
        if ceiling >= target_total:
            notes.append(f"the difficulty cap is what blocks this: without it the ceiling is "
                         f"{ceiling}")
        else:
            notes.append(f"unreachable at {accuracy}%: the ceiling is {ceiling}, "
                         f"{target_total - ceiling} short of the target")
        result = attempt(capacity_basic, capacity_new)
        reachable = False
    elif needed_raw <= 0:
        # the current total already covers the target: nothing to play
        notes.append(f"target already reached ({_q(current_raw)} raw vs {_q(need_raw)} needed)")
        result = attempt(Decimal(0), Decimal(0))
        reachable = True
    else:
        if balance:
            # Bisect the basic/new split. Giving a bucket more of the gap pushes its cutoff up,
            # so its task difficulty only grows -- which is what makes the search monotone.
            low, high = 0.0, 1.0
            best_share, best_score = DEFAULT_BASIC_SHARE, None
            for _ in range(max(1, balance_rounds)):
                middle = (low + high) / 2
                share = Decimal(str(round(middle, 4)))
                candidate = attempt(needed_raw * share, needed_raw * (1 - share), share)
                rounds += 1
                score = candidate.score()
                if best_score is None or score < best_score:
                    best_share, best_score = share, score
                signal = candidate.signal()
                if signal == 0 or high - low < 0.02:
                    break
                if signal > 0:      # basic is harder: hand more of the gap to new
                    high = middle
                else:               # new is harder: hand more of it to basic
                    low = middle
            result = attempt(needed_raw * best_share, needed_raw * (1 - best_share), best_share)
            notes.append(f"split {best_share:.2f} / {1 - float(best_share):.2f} after {rounds} "
                         f"round(s): basic task difficulty "
                         f"{format_mean_difficulty(result.mean_basic)} vs new "
                         f"{format_mean_difficulty(result.mean_new)}")
        else:
            share = DEFAULT_BASIC_SHARE
            result = attempt(needed_raw * share, needed_raw * (1 - share), share)
        reachable = result.left_basic <= 0 and result.left_new <= 0
        if not reachable and not result.notes:
            notes.append("the available charts cannot cover the target under this difficulty cap")

    notes.extend(result.notes)
    deficit_basic, deficit_new = result.deficit_basic, result.deficit_new
    achieved_total = total_from_raw(result.basic_sum + result.new_sum, convert_constant)

    min_accuracy = _min_accuracy(patterns, cap_units, target_total, convert_constant)
    min_accuracy_uncapped = min_accuracy if cap_units is None else _min_accuracy(
        patterns, None, target_total, convert_constant)

    return TargetPlan(
        username=username,
        bmode=bmode,
        accuracy=accuracy,
        target_total=target_total,
        floor_cap=floor_cap,
        convert_constant=convert_constant,
        maxpower=maxpower,
        ratio=ratio,
        basic=BucketPlan("basic", BEST_BASIC_LIMIT, basic_current,
                         basic_current + deficit_basic, deficit_basic, capacity_basic,
                         result.basic_sum, result.basic_entries),
        new=BucketPlan("new", BEST_NEW_LIMIT, new_current,
                       new_current + deficit_new, deficit_new, capacity_new,
                       result.new_sum, result.new_entries),
        achieved_total=achieved_total,
        ceiling=ceiling,
        ceiling_capped=ceiling_capped,
        min_accuracy=min_accuracy,
        min_accuracy_uncapped=min_accuracy_uncapped,
        reachable=reachable,
        notes=notes,
        basic_share=result.share_basic,
        balance_rounds=rounds,
    )
