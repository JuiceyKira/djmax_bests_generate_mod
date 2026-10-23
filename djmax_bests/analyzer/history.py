"""The play-history layer: an append-only log of play events, each carrying the mode's
total djpower as it stood after that play (the stamped column), accumulated by diffing
consecutive snapshots of the raw record store.

V-ARCHIVE keeps only each chart's current best record, so a superseded score is gone from the
API the moment it is beaten. This module accumulates what can still be accumulated:

  - the first time a record state is seen (fresh store, or the primary account switched), every
    current best becomes an event, stamped with its own `updatedAt` — the archive's play
    timestamp — so the history starts with real depth;
  - every later refresh diffs the new state against the last snapshot; a chart whose score rose
    or that appeared contributes exactly one event (again at its `updatedAt`).

Policies (agreed 2026-10-07, stamped design 2026-10-11):
  - events fire on score/max-combo changes, reclassifications (is_new) and djpower recomputes.
    A recompute or reclassification is not a play, but it changes the total and is recorded:
    its row borrows the record's unchanged updatedAt for `datetime` and carries the discovery
    moment in `observed_at`, so the intervening history is never rewritten;
  - event time is the record's own `updatedAt`, never the observation time;
  - the event schema carries only what the log is for — chart keys, the replay state
    (score/max_combo/djpower/is_new), the row-displayed values (title/level/max_djpower) and
    the stamped columns (total_djpower/maxpower); per-record attributes like floor name live
    in the store, and the snapshots keep the full raw states for anything else;
  - the stamped `total_djpower` is the modecard formula (top-70 basic + top-30 new raw djpower
    summed, times the convert constant, cut to 4 digits, capped at 10000) over the replay state
    as of that event, frozen at write time — the convert constant in effect when the row was
    written is stored alongside as `maxpower`, so the log is self-describing: verify and region
    re-stamps re-derive the constant from the stored value and reproduce every total bit-exactly;
  - snapshots of the raw layer are kept in records/history/snapshots/ (gzip, written only when
    the content hash changes, pruned to the newest SNAPSHOTS_TO_KEEP) so a corrupted event log
    can be re-derived from them;
  - every event-log rewrite is also backed up as a dated copy in records/history/backups/
    (newest LOG_BACKUPS_TO_KEEP kept): restoring the newest healthy backup and replaying the
    kept snapshots over it recovers everything the two retention windows overlap on;
  - events are keyed per account; a snapshot belonging to another account never diffs against
    the current one, so switching the primary account never fakes events (the new account is
    seeded instead, and re-seeding an account is absorbed by the dedup key).

Deleting records/history/ loses every superseded score permanently — the API cannot replay
them. The finer the refresh cadence, the finer the history: plays between two refreshes
survive only as their final best.

Read side: the stamped column IS the totals curve — reads are pure column selections plus
per-button shifts; the replay engine (`_walk_mode`) runs only on the write path, over
absorption regions after out-of-order insertions, and inside `verify_history`. The event log
is reconciled with the current store (the store's bests are appended as transient events when
the log does not hold them yet — a refresh that died between the raw write and the history
write self-heals on the next refresh's snapshot diff, and until then reads still see the
store). `load_play_events` returns the bare log; every other reader reconciles. `replay_view`
is the chart's shared read: one reconciled pass serving both the recent-plays rows and the
totals selection, so a generation reads the log once, not twice.
"""
import gzip
import hashlib
import heapq
import json
import os
import shutil
from datetime import datetime, timezone
from decimal import Decimal

import pandas as pd

from .. import api_handler, util
from . import data_fetcher

HISTORY_PATH = os.path.join(api_handler.RECORDS_PATH, 'history')
EVENTS_PATH = os.path.join(HISTORY_PATH, 'play_events.parquet')
SNAPSHOTS_PATH = os.path.join(HISTORY_PATH, 'snapshots')
BACKUPS_PATH = os.path.join(HISTORY_PATH, 'backups')

# Retention caps. Lossless corruption recovery needs the kept snapshots to reach back past the
# oldest kept log backup — the two windows must overlap in time.
SNAPSHOTS_TO_KEEP = 30
LOG_BACKUPS_TO_KEEP = 5

# The stamped columns are stored physically as int64 values scaled by 10^4 and carried
# in memory as Decimals of scale 4; the conversion happens only at the I/O boundary
# (_load_events_df / _write_events). maxpower keeps the raw official value the row was
# stamped with; the convert constant is re-derived from it (10000 / maxpower).
EVENT_COLUMNS = ['username', 'songid', 'title', 'button', 'pattern', 'level',
                 'is_new', 'datetime', 'observed_at', 'score', 'max_combo',
                 'djpower', 'max_djpower', 'total_djpower', 'maxpower']
_DECIMAL_COLS = ['total_djpower', 'maxpower']
_DECIMAL_QUANT = Decimal('0.0001')
_SCALE = Decimal(10000)

# One play per chart per moment: the dedup key that keeps re-observations and re-seeds from
# growing the log.
DEDUP_KEYS = ['username', 'songid', 'button', 'pattern', 'datetime', 'score', 'max_combo']

CHART_KEYS = ['songid', 'button', 'pattern']

# The canonical row order. username breaks the tie between cross-account rows of the same
# chart at the same moment, so the stored order is stable across account switches (without
# it, every switch flips the concat order and re-sorts those ties).
_SORT_KEYS = ['datetime', 'username'] + CHART_KEYS

_INT_COLS = ['songid', 'button', 'level']
_FLOAT_COLS = ['score', 'djpower', 'max_djpower']
_STR_COLS = ['username', 'title', 'pattern']
_BOOL_COLS = ['is_new', 'max_combo']
_TS_COLS = ['datetime', 'observed_at']


# ======================================================================
# Write side: diff consecutive snapshots into stamped play events
# ======================================================================

def update_history(username: str, texts: dict) -> int:
    """Fold a freshly observed {bmode: raw response text} state into the history.

    Called by data_fetcher right after the raw layer was updated (refresh or ensure fetch).
    Returns the number of genuinely new events appended; a no-op when nothing changed since
    the last snapshot. New rows are stamped in the same pass (their mode's total after the
    event, frozen with today's maxpower); out-of-order insertions additionally re-stamp the
    absorption region between the insertion point and the event that supersedes the inserted
    value. A rewritten log lands a dated backup; a written snapshot triggers pruning to the
    retention caps.
    """
    observed_at = datetime.now(timezone.utc)
    last = _load_last_snapshot()

    if last is None or str(last.get('username', '')).casefold() != username.casefold():
        if last is not None:
            print(f'play history: primary account changed from {last["username"]!r} to '
                  f'{username!r}; seeding a fresh event stream')
        new_rows = [_event_row(username, row) for row in _flatten(texts).values()]
        kind = 'seeded'
    else:
        old = _flatten(last['texts'])
        new = _flatten(texts)
        new_rows = []
        for key, row in new.items():
            prev = old.get(key)
            if (prev is None or row['score'] > prev['score'] or row['max_combo'] != prev['max_combo']
                    or row['is_new'] != prev['is_new'] or row['djpower'] != prev['djpower']):
                new_rows.append(_event_row(username, row))
        for key in old.keys() - new.keys():
            print(f'play history warning: {key} vanished from the archive records; '
                  'not treated as a play')
        kind = 'diffed'

    maxpower = {b: api_handler.get_convert_constant(b)[1].quantize(_DECIMAL_QUANT)
                for b in {int(row['button']) for row in new_rows}}
    for row in new_rows:
        row['maxpower'] = maxpower[int(row['button'])]
        row['total_djpower'] = None
        row['observed_at'] = observed_at

    # the stamping walk evolves ONE account's state: rows of other primary accounts are
    # immutable archive and must neither enter the pool nor be touched on write
    log = _load_events_df()
    me = log['username'].str.casefold() == username.casefold()
    log_me, log_other = log[me], log[~me]
    new_df = _normalize(pd.DataFrame(new_rows, columns=EVENT_COLUMNS))
    new_df = _drop_known_keys(new_df, log_me)            # classify: copies die, adjustments re-dated
    new_df = _drop_redundant_adjustments(new_df, log_me)  # state-based idempotency for re-fires
    new_df = new_df.drop(columns='is_adjustment')
    added = len(new_df)
    if added:
        stamped = _merge_and_stamp(log_me, new_df)
        combined = pd.concat([log_other, stamped], ignore_index=True)
        combined = (combined.sort_values(_SORT_KEYS, kind='stable')
                    .reset_index(drop=True))
        _write_events(combined)
        _backup_events_log()
        print(f'play history: {kind} {added} event(s)')

    changed = _save_snapshot(username, texts, observed_at, last)
    if changed:
        _prune_snapshots()
    if not added and changed:
        print('play history: no new events, snapshot updated (records changed without a score change)')
    return added


def _flatten(texts: dict) -> dict[tuple, dict]:
    """{(songid, button, pattern): one record row} parsed from raw response texts."""
    rows = {}
    for key, text in texts.items():
        button = int(key)
        payload = json.loads(text)
        for entry in payload.get('records', []):
            # same field mapping as data_fetcher.build_recorddf: API names -> SongRecords fields
            record_info = {'songid': entry.get('title'),
                           'title': entry.get('name'),
                           'pattern': entry.get('pattern'),
                           'level': entry.get('level'),
                           'dlc_code': entry.get('dlcCode'),
                           'button': button,
                           'floor_name': entry.get('floorName'),
                           'is_new': entry.get('newTab'),
                           'score': entry.get('score'),
                           'max_combo': entry.get('maxCombo'),
                           'djpower': entry.get('djpower'),
                           'max_djpower': entry.get('maxDjpower'),
                           'rating': entry.get('rating'),
                           'datetime': entry.get('updatedAt')}
            record = data_fetcher.SongRecords.model_validate(record_info).model_dump()
            row = {'songid': record['songid'], 'title': record['title'],
                   'button': button, 'pattern': record['pattern'], 'level': record['level'],
                   'is_new': record['is_new'],
                   'score': float(record['score']), 'max_combo': record['max_combo'],
                   'djpower': float(record['djpower']),
                   'max_djpower': float(record['max_djpower']),
                   'datetime': record['datetime']}
            rows[(row['songid'], button, row['pattern'])] = row
    return rows


def _event_row(username: str, row: dict) -> dict:
    return {'username': username, **row}


def _load_last_snapshot() -> dict | None:
    """The newest snapshot ({'username', 'observed_at', 'hash', 'texts'}); None when there is
    none. Snapshots are named <observed_at>_<hash8>, so filename order is age order."""
    if not os.path.isdir(SNAPSHOTS_PATH):
        return None
    for name in sorted(os.listdir(SNAPSHOTS_PATH), reverse=True):
        if not name.endswith('.json.gz'):
            continue
        try:
            with gzip.open(os.path.join(SNAPSHOTS_PATH, name), 'rt', encoding='utf-8') as f:
                snapshot = json.load(f)
        except (OSError, ValueError):
            continue
        if isinstance(snapshot, dict) and isinstance(snapshot.get('texts'), dict):
            return snapshot
    return None


def _snapshot_hash(texts: dict) -> str:
    canonical = json.dumps(texts, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def _save_snapshot(username: str, texts: dict, observed_at: datetime, last: dict | None) -> bool:
    """Archive the raw state; False when it is identical to the newest snapshot."""
    digest = _snapshot_hash(texts)
    if last is not None and last.get('hash') == digest:
        return False
    os.makedirs(SNAPSHOTS_PATH, exist_ok=True)
    stamp = observed_at.astimezone(timezone.utc).strftime('%Y%m%d_%H%M%S')
    path = os.path.join(SNAPSHOTS_PATH, f'snapshot_{stamp}_{digest[:8]}.json.gz')
    payload = {'username': username, 'observed_at': observed_at.isoformat(),
               'hash': digest, 'texts': texts}
    tmp = path + '.tmp'
    with gzip.open(tmp, 'wt', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False)
    os.replace(tmp, path)
    return True


def _prune_snapshots() -> None:
    """Keep only the newest SNAPSHOTS_TO_KEEP snapshots — filename order is age order, so the
    diff baseline _load_last_snapshot reads is always inside the kept window."""
    try:
        names = sorted(name for name in os.listdir(SNAPSHOTS_PATH) if name.endswith('.json.gz'))
    except OSError:
        return
    for name in names[:-SNAPSHOTS_TO_KEEP]:
        try:
            os.remove(os.path.join(SNAPSHOTS_PATH, name))
        except OSError:
            pass


def _load_events_df() -> pd.DataFrame:
    """The stored event log as a normalized frame (stamped columns as Decimals).

    Raises on a log the stamped schema cannot serve — an un-stamped legacy file (delete it;
    the next refresh reseeds) or a stamped file with gaps in the stamped columns (corruption:
    restore a backup). An empty log is fine and reads as an empty typed frame."""
    if not os.path.exists(EVENTS_PATH):
        return _normalize(pd.DataFrame(columns=EVENT_COLUMNS))
    try:
        df = pd.read_parquet(EVENTS_PATH)
    except (OSError, ValueError):
        return _normalize(pd.DataFrame(columns=EVENT_COLUMNS))
    if 'total_djpower' not in df.columns or 'maxpower' not in df.columns:
        raise RuntimeError(
            f'{EVENTS_PATH} is an un-stamped event log. Delete it and refresh to reseed '
            f'(superseded intermediate scores will be lost), or convert it with the '
            f'conversion script.')
    if len(df) and df['total_djpower'].isna().any():
        raise RuntimeError(f'{EVENTS_PATH} has rows without a stamped total — restore a '
                           f'backup from {BACKUPS_PATH} or delete the log and reseed.')
    df = df.reindex(columns=EVENT_COLUMNS)
    for col in _DECIMAL_COLS:
        df[col] = df[col].map(_as_decimal_scale4)
    return _normalize(df)


def _as_decimal_scale4(v):
    """Physical int64 (value x 10^4) -> logical Decimal of scale 4; None passes through."""
    if pd.isna(v):
        return None
    return (Decimal(int(v)) / _SCALE).quantize(_DECIMAL_QUANT)


def _as_decimal(v):
    """Tolerant logical-value coercion: Decimal passes through, None/NaN -> None."""
    if pd.isna(v):
        return None
    if isinstance(v, Decimal):
        return v
    return Decimal(str(v))


def _to_physical(df: pd.DataFrame) -> pd.DataFrame:
    """Logical Decimal stamped columns -> physical int64 (value x 10^4) for parquet."""
    df = df.copy()
    for col in _DECIMAL_COLS:
        df[col] = df[col].map(
            lambda v: None if pd.isna(v) else int(v.quantize(_DECIMAL_QUANT) * _SCALE))
    return df


def _write_events(combined: pd.DataFrame) -> None:
    os.makedirs(HISTORY_PATH, exist_ok=True)
    tmp = EVENTS_PATH + '.tmp'
    _to_physical(combined).to_parquet(tmp, index=False)
    os.replace(tmp, EVENTS_PATH)


def _drop_known_keys(new_df: pd.DataFrame, log: pd.DataFrame) -> pd.DataFrame:
    """Classify the batch rows against the log by dedup key.

    A key the log does not hold is a new play (or a backfilled superseded record) and passes
    through. A key the log holds is a re-observation of an already-recorded play: with
    identical djpower and is_new it is a re-fired copy from a crash between the log write and
    the snapshot write and dies here; with differing values it is an official adjustment of
    that play — kept, flagged (`is_adjustment`), and re-dated to the discovery moment
    (datetime = observed_at), so the region re-stamp never rewrites the intervening history
    with post-adjustment values."""
    if log.empty or new_df.empty:
        return new_df.assign(is_adjustment=False)
    known = log[DEDUP_KEYS + ['djpower', 'is_new']].drop_duplicates(subset=DEDUP_KEYS)
    known = known.rename(columns={'djpower': 'log_djpower', 'is_new': 'log_is_new'})
    known['_in_log'] = True
    merged = new_df.merge(known, on=DEDUP_KEYS, how='left')
    in_log = merged['_in_log'].fillna(False).astype(bool)
    adjusted = in_log & ((merged['djpower'] != merged['log_djpower'])
                         | (merged['is_new'] != merged['log_is_new']))
    merged.loc[adjusted, 'datetime'] = merged.loc[adjusted, 'observed_at']
    merged['is_adjustment'] = adjusted
    return merged[~(in_log & ~adjusted)].drop(columns=['_in_log', 'log_djpower', 'log_is_new'])


def _drop_redundant_adjustments(new_df: pd.DataFrame, log: pd.DataFrame) -> pd.DataFrame:
    """Adjustment rows are idempotent by state, not by datetime — their datetime is the
    discovery moment and differs on every re-fire. If the chart's latest logged row already
    carries the same djpower and is_new, the adjustment is on record and the re-fired copy
    dies here."""
    if log.empty or new_df.empty or not new_df['is_adjustment'].any():
        return new_df
    latest = {}
    for r in log.itertuples():
        latest[(int(r.songid), int(r.button), str(r.pattern))] = (r.djpower, r.is_new)

    def redundant(row):
        if not row.is_adjustment:
            return False
        cur = latest.get((int(row.songid), int(row.button), str(row.pattern)))
        return (cur is not None and cur[0] == row.djpower and cur[1] == row.is_new)

    return new_df[~new_df.apply(redundant, axis=1)]


def _absorption_stamp_set(combined: pd.DataFrame, new_pos: set) -> set:
    """Positions that must (re)carry a stamped total: every new row, plus every row between a
    new row and the next later event of the same chart (the absorption point) — the replay
    state of ALL rows in that position range differs from what the recorded stamps were
    computed against, whichever chart they belong to. The state carries each chart's LATEST
    values, so the next own event overwrites the inserted row's contribution completely and
    rows after it are unaffected; a new row with no later own event keeps needing re-stamps
    all the way to the end."""
    stamp = set(new_pos)
    last_pos = int(combined.index[-1]) if len(combined) else -1
    for _, own_rows in combined.groupby(CHART_KEYS, sort=False).indices.items():
        new_own = sorted(p for p in own_rows if p in new_pos)
        if not new_own:
            continue
        for i_pos in new_own:
            absorber = next((p for p in own_rows if p > i_pos), None)
            for p in range(i_pos, absorber if absorber is not None else last_pos + 1):
                stamp.add(p)
    return stamp


def _merge_and_stamp(log: pd.DataFrame, new_df: pd.DataFrame) -> pd.DataFrame:
    """Merge the batch into the log, sort into replay order, and (re)stamp every row of the
    absorption stamp set through the replay walk — one pass per affected mode, the state
    evolving from empty exactly as a from-scratch replay would."""
    combined = pd.concat([log, new_df.assign(_new=True)], ignore_index=True)
    combined = _normalize(combined)
    combined = (combined.sort_values(_SORT_KEYS, kind='stable')
                .drop_duplicates(subset=DEDUP_KEYS, keep='first')
                .reset_index(drop=True))
    new_pos = set(combined.index[combined['_new'].fillna(False)])
    stamp = _absorption_stamp_set(combined, new_pos)
    combined['total_djpower'] = combined['total_djpower'].map(_as_decimal)
    for button in sorted(int(b) for b in combined.loc[sorted(stamp), 'button'].unique()):
        mode = combined[combined['button'] == button]
        for event, total in _walk_mode(mode, _row_convert, stamp=stamp):
            combined.at[event.Index, 'total_djpower'] = total
    return combined.drop(columns='_new')


def _row_convert(event) -> Decimal:
    """The convert constant a row was (or is being) stamped with, re-derived from its own
    stored maxpower — the one conversion serving batch stamping, region re-stamps and verify."""
    return _convert_from_maxpower(event.maxpower)


def _backup_events_log() -> None:
    """Copy the just-rewritten event log to a dated backup; keep the newest LOG_BACKUPS_TO_KEEP.
    The content hash in the name keeps same-second rewrites from overwriting each other. A
    failed backup only warns — the log itself is already safely written."""
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
    try:
        with open(EVENTS_PATH, 'rb') as f:
            digest = hashlib.sha256(f.read()).hexdigest()[:8]
        os.makedirs(BACKUPS_PATH, exist_ok=True)
        path = os.path.join(BACKUPS_PATH, f'play_events_{stamp}_{digest}.parquet')
        shutil.copyfile(EVENTS_PATH, path + '.tmp')
        os.replace(path + '.tmp', path)
    except OSError as exc:
        print(f'play history warning: event log backup failed: {exc}')
        return
    names = sorted(name for name in os.listdir(BACKUPS_PATH)
                   if name.startswith('play_events_') and name.endswith('.parquet'))
    for name in names[:-LOG_BACKUPS_TO_KEEP]:
        try:
            os.remove(os.path.join(BACKUPS_PATH, name))
        except OSError:
            pass


# ======================================================================
# Read side: the stamped column IS the totals curve
# ======================================================================

def load_play_events(username: str | None = None) -> pd.DataFrame:
    """The bare event log (no store reconciliation), oldest first; optionally one account."""
    events = _load_events_df()
    if username is not None:
        events = events[events['username'].str.casefold() == username.casefold()]
    return events.sort_values(_SORT_KEYS, kind='stable').reset_index(drop=True)


def _store_overlay(username: str) -> pd.DataFrame:
    """The current store's bests as event rows — the reconciliation tail of the log. Rows the
    log already holds die in the dedup; the rest get their maxpower (today's) and a placeholder
    total that _events_with_overlay fills through a transient continuation walk."""
    empty = _normalize(pd.DataFrame(columns=EVENT_COLUMNS))
    try:
        meta = data_fetcher.read_db_meta()
        if str(meta.get('username') or '').casefold() != username.casefold():
            return empty
        rows = _flatten(data_fetcher.read_full_varecord())
    except (OSError, ValueError, TypeError, KeyError):
        return empty
    if not rows:
        return empty
    events = [_event_row(username, row) for row in rows.values()]
    overlay = _normalize(pd.DataFrame(events, columns=EVENT_COLUMNS))
    for b in overlay['button'].unique():
        overlay.loc[overlay['button'] == b, 'maxpower'] = _today_maxpower(int(b))
    overlay['total_djpower'] = None
    return overlay


def _today_maxpower(button: int) -> Decimal:
    return api_handler.get_convert_constant(button)[1].quantize(_DECIMAL_QUANT)


def _events_with_overlay(username: str) -> pd.DataFrame:
    """The event log plus the store's bests it does not hold yet, oldest first. Overlay rows
    that survive the dedup are stamped through a transient continuation walk, so reads see
    the store even before the next refresh's snapshot diff heals the log."""
    events = load_play_events(username)
    overlay = _store_overlay(username)
    if overlay.empty:
        return events
    overlay = overlay.assign(_overlay=True)
    combined = pd.concat([events, overlay], ignore_index=True)
    combined = _normalize(combined)
    combined = (combined.sort_values(_SORT_KEYS, kind='stable')
                .drop_duplicates(subset=DEDUP_KEYS, keep='first')
                .reset_index(drop=True))
    overlay_pos = set(combined.index[combined['_overlay'].fillna(False)])
    combined = combined.drop(columns='_overlay')
    if overlay_pos:
        for button in sorted(int(b) for b in combined.loc[sorted(overlay_pos), 'button'].unique()):
            mode = combined[combined['button'] == button]
            for event, total in _walk_mode(mode, _row_convert, stamp=overlay_pos):
                combined.at[event.Index, 'total_djpower'] = total
    return combined


def _with_deltas(events: pd.DataFrame) -> pd.DataFrame:
    """Add each event's previous best (prev_*) and the deltas against it, per chart."""
    events = events.copy()
    if events.empty:
        for col in ('prev_score', 'prev_djpower', 'prev_max_combo', 'delta_score', 'delta_djpower'):
            events[col] = pd.Series(dtype='float64')
        return events
    asc = events.sort_values(_SORT_KEYS, kind='stable')
    grouped = asc.groupby(CHART_KEYS, sort=False)
    asc = asc.assign(
        prev_score=grouped['score'].shift(1),
        prev_djpower=grouped['djpower'].shift(1),
        prev_max_combo=grouped['max_combo'].shift(1),
    )
    asc['delta_score'] = asc['score'] - asc['prev_score']
    asc['delta_djpower'] = asc['djpower'] - asc['prev_djpower']
    return asc


def _with_adjustment_flag(events: pd.DataFrame) -> pd.DataFrame:
    """Flag the official adjustment rows: a row whose score and max_combo match the chart's
    previous row's exactly. The diff never fires for same-score-same-combo plays, so such a
    row can only be a recompute or a reclassification."""
    events = events.copy()
    prev = events.groupby(CHART_KEYS, sort=False)['score'].shift(1)
    prev_combo = events.groupby(CHART_KEYS, sort=False)['max_combo'].shift(1)
    events['is_adjustment'] = (
        prev.notna() & (prev == events['score'])
        & prev_combo.notna() & (prev_combo == events['max_combo']))
    return events


def replay_view(username: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(events, totals) from one reconciled pass — the history chart's shared read.

    `events` is the reconciled stream with the chart's row columns (the per-chart
    prev_*/delta_* pairs, the previous row's stamp for the era-boundary gain decomposition,
    newest first and uncapped); `totals` is the per-mode totals selection. One log read, both
    views — the stamped column is the totals curve, so nothing here replays anything."""
    events = _events_with_overlay(username)
    events = _with_deltas(events)
    events = _with_adjustment_flag(events)
    grouped = events.groupby('button', sort=False)
    events['prev_total_djpower'] = grouped['total_djpower'].shift(1)
    events['prev_maxpower'] = grouped['maxpower'].shift(1)
    events = _with_row_gains(events)
    events = (events.sort_values(_SORT_KEYS, ascending=False, kind='stable')
              .reset_index(drop=True))
    return events, events[['datetime', 'button', 'total_djpower']].reset_index(drop=True)


def _with_row_gains(frame: pd.DataFrame) -> pd.DataFrame:
    """The play-component gain a row shows: within a constant era it is the exact total
    difference (bit-identical to a from-scratch replay); at an era boundary (the previous
    row carries a different maxpower) the official step is excluded by exact algebra over
    the stored columns. A mode's first event counts from zero."""
    frame = frame.copy()
    gains = []
    for row in frame.itertuples():
        prev_total, prev_mp = row.prev_total_djpower, row.prev_maxpower
        if _as_decimal(prev_total) is None:
            gains.append(row.total_djpower)
        elif _as_decimal(prev_mp) == _as_decimal(row.maxpower):
            gains.append(row.total_djpower - _as_decimal(prev_total))
        else:
            raw = row.total_djpower * row.maxpower / _SCALE
            prev_raw = _as_decimal(prev_total) * _as_decimal(prev_mp) / _SCALE
            gains.append(util.cut_digits(
                (raw - prev_raw) * _convert_from_maxpower(row.maxpower), 4))
    frame['total_gain'] = gains
    return frame


def chart_progression(username: str, songid: int, button: int, pattern: str) -> pd.DataFrame:
    """One chart's full play history, newest first, with replay_view's full row columns: the
    per-chart prev_*/delta_* pairs plus total_gain (the per-chart walk rides the shared
    replay, so its rows carry exactly what the history chart's rows carry)."""
    events, _totals = replay_view(username)
    rows = events[(events['songid'] == songid)
                  & (events['button'] == button)
                  & (events['pattern'].str.upper() == str(pattern).upper())]
    return rows.reset_index(drop=True)


# ======================================================================
# The replay walk: the one state machine behind stamping and verification
# ======================================================================

def _top_sums(state: dict) -> tuple[float, float]:
    """The modecard raw sums over `state`: top-70 basic + top-30 new djpower, each summed in
    descending order — the addition order sum(nlargest(...)) had, so the Decimal multiply in
    _total_from sees bit-identical floats."""
    basic_heap: list[float] = []
    new_heap: list[float] = []
    for p, is_new in state.values():
        if is_new:
            if len(new_heap) < 30:
                heapq.heappush(new_heap, p)
            elif p > new_heap[0]:
                heapq.heapreplace(new_heap, p)
        else:
            if len(basic_heap) < 70:
                heapq.heappush(basic_heap, p)
            elif p > basic_heap[0]:
                heapq.heapreplace(basic_heap, p)
    return sum(sorted(basic_heap, reverse=True)), sum(sorted(new_heap, reverse=True))


def _total_from(raw: tuple[float, float], convert: Decimal) -> Decimal:
    total = util.cut_digits(Decimal(raw[0] + raw[1]) * convert, 4)
    if total > Decimal('10000.0000'):
        total = Decimal('10000.0000')
    return total


def _convert_from_maxpower(maxpower: Decimal) -> Decimal:
    return Decimal("10000.0000") / maxpower


def _walk_mode(mode_events: pd.DataFrame, convert_for, stamp: set | None = None):
    """Evolve one mode's replay state from empty through `mode_events` in replay order,
    yielding (event, total_djpower) for every event — or, when `stamp` is a set of frame
    positions, only for those rows (the write path: the state evolves through every row, the
    expensive top-sum pass runs only where a total will be stored). `convert_for(event)`
    supplies the row's own constant; the raw sums are cached and invalidated whenever the
    state changes, so a non-improving event re-derives its total from the cache instead of
    re-scanning the pool."""
    state: dict[tuple, tuple[float, bool]] = {}
    raw: tuple[float, float] | None = None
    for event in mode_events.sort_values(_SORT_KEYS, kind='stable').itertuples():
        key = (event.songid, event.pattern)
        old = state.get(key)
        if old is None or event.djpower != old[0]:
            state[key] = (event.djpower, event.is_new)
            raw = None
        elif event.is_new != old[1]:
            # reclassification: the chart moves between pools, the routing changes
            state[key] = (old[0], event.is_new)
            raw = None
        if stamp is not None and event.Index not in stamp:
            continue
        if raw is None:
            raw = _top_sums(state)
        yield event, _total_from(raw, convert_for(event))


def snapshot_view(username: str, texts: dict) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series]:
    """(events, totals, gains) as the single snapshot `texts` would seed them — the in-memory
    view behind inspect_history. No event log is read or written, and the events hold only
    the current bests: a single snapshot cannot know superseded scores. The rows carry
    today's maxpower and their replayed totals; `gains` comes from the same walk."""
    events = pd.DataFrame(
        [_event_row(username, row) for row in _flatten(texts).values()],
        columns=EVENT_COLUMNS)
    events = _normalize(events)
    for b in events['button'].unique():
        events.loc[events['button'] == b, 'maxpower'] = _today_maxpower(int(b))
    events = events.sort_values(_SORT_KEYS, kind='stable').reset_index(drop=True)
    events = _with_adjustment_flag(events)
    totals_rows = []
    gains = pd.Series(Decimal(0), index=events.index, dtype=object)
    for button in sorted(int(b) for b in events['button'].unique()):
        previous = Decimal(0)
        for event, total in _walk_mode(events[events['button'] == button], _row_convert):
            totals_rows.append({'datetime': event.datetime, 'button': button,
                                'total_djpower': total})
            gains[event.Index] = total - previous
            previous = total
            events.at[event.Index, 'total_djpower'] = total
    totals = pd.DataFrame(totals_rows, columns=['datetime', 'button', 'total_djpower'])
    return events.reset_index(drop=True), totals, gains


def verify_history() -> bool:
    """Re-replay the whole log from an empty state (each row scored with its own stored
    maxpower) and compare against the stamped column bit-for-bit — the guardian of the
    frozen values and the acceptance test of every stamping path. Per account: each primary
    account's rows evolve their own pool, so the log holding several accounts replays and
    verifies one account at a time. Passes silently; the first mismatch is reported with
    its row. Note verify validates the column against the log's own event sequence: a log
    missing events replays self-consistently — event completeness is the snapshot diff's
    job, not this one."""
    events = _load_events_df()
    if events.empty:
        print('verify: the log is empty, nothing to check')
        return True
    ok = True
    for _, account in events.groupby(events['username'].str.casefold(), sort=False):
        name = account['username'].iloc[0]
        for button in sorted(int(b) for b in account['button'].unique()):
            mode = account[account['button'] == button]
            for event, total in _walk_mode(mode, _row_convert):
                if total != event.total_djpower:
                    ok = False
                    print(f'verify: mismatch at {name} {event.datetime} {event.songid} '
                          f'{int(event.button)}b {event.pattern}: stamped '
                          f'{event.total_djpower}, replayed {total}')
    print('verify: OK' if ok else 'verify: FAILED')
    return ok


# ======================================================================
# Helpers
# ======================================================================

def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    """Pin the event schema's dtypes (parquet round-trips and empty frames included). Columns
    that are absent are left absent — legacy in-memory views may legitimately omit the
    stamped columns."""
    df = df.copy()
    for col in _INT_COLS:
        if col in df:
            df[col] = pd.to_numeric(df[col], errors='coerce').astype('int64')
    for col in _FLOAT_COLS:
        if col in df:
            df[col] = pd.to_numeric(df[col], errors='coerce').astype('float64')
    for col in _STR_COLS:
        if col in df:
            df[col] = df[col].astype(str)
    for col in _BOOL_COLS:
        if col in df:
            df[col] = df[col].astype(bool)
    for col in _DECIMAL_COLS:
        if col in df:
            df[col] = df[col].map(_as_decimal)
    for col in _TS_COLS:
        if col in df:
            df[col] = pd.to_datetime(df[col], utc=True, errors='coerce')
    return df
