"""Per-level DJPower histogram shared by the bests and target headers.

A bar is the DJPower accumulated by the best 100 records in one level bucket, expressed as a
share of the maximum 10000. The optional capacity ghost behind it is the most that bucket could
contribute to a 70-basic + 30-new list, computed from every chart in the song database.
"""
from __future__ import annotations

import os
from decimal import Decimal

from PIL import Image, ImageDraw, ImageFont

from .. import api_handler, models, util

FONT_PATH = os.path.join(os.path.dirname(__file__), "fonts")

# Level buckets in increasing difficulty order. The official level scales overlap: diff_coeff()
# gives SC 2/4/6/8 the same coefficient as non-SC 12/13/14/15, so those pairs share one bucket
# (SC 12/14 are their own buckets and are not folded into 13/15).
LEVEL_BUCKET_ORDER = (
    "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "SC1",
    "12/SC2", "SC3", "13/SC4", "SC5", "14/SC6", "SC7", "15/SC8",
    "SC9", "SC10", "SC11", "SC12", "SC13", "SC14", "SC15",
)
LEVEL_BUCKET_MERGED = {
    (False, 12): "12/SC2", (False, 13): "13/SC4",
    (False, 14): "14/SC6", (False, 15): "15/SC8",
    (True, 2): "12/SC2", (True, 4): "13/SC4",
    (True, 6): "14/SC6", (True, 8): "15/SC8",
}

LEVEL_BAR_FONT_SIZE = 20
LEVEL_BAR_FILL_RATIO = 0.62
LEVEL_BAR_BASIC_COLOR = "#D2D2D2"
LEVEL_BAR_NEW_COLOR = "#F0BE40"
LEVEL_BAR_LABEL_COLOR = "#E4E4E4"
LEVEL_BAR_ZERO_LABEL_COLOR = "#7A7A7A"
LEVEL_BAR_BASELINE_COLOR = "#5A5A5A"
LEVEL_BAR_GRID_COLOR = "#444444"
LEVEL_BAR_TOP_COLOR = "#8A8A8A"
LEVEL_BAR_CAPACITY_ALPHA = 20
LEVEL_BAR_CAPACITY_TOP_ALPHA = 95
# Slot counts of the best-100 list, matching data_converter.BEST_BASIC/NEW_LIMIT.
LEVEL_BAR_BASIC_SLOTS = 70
LEVEL_BAR_NEW_SLOTS = 30


def level_bucket_for(pattern: str, level: int) -> str:
    """The histogram bucket a chart of this pattern/level belongs to."""
    merged = LEVEL_BUCKET_MERGED.get((pattern == "SC", level))
    if merged is not None:
        return merged
    return f"SC{level}" if pattern == "SC" else str(level)


def level_bucket(song: models.DMSong) -> str:
    """The histogram bucket a best-100 entry belongs to."""
    return level_bucket_for(song.pattern, song.level)


def level_djpower_totals(data: models.DMBests) -> dict[str, tuple[Decimal, Decimal]]:
    """Raw djpower per level bucket, split into (basic-70, new-30) so mixed buckets can be stacked."""
    totals = {bucket: [Decimal(0), Decimal(0)] for bucket in LEVEL_BUCKET_ORDER}
    for column, songs in ((0, data.basic), (1, data.new)):
        for song in songs:
            values = totals.get(level_bucket(song))
            if values is not None:
                values[column] += song.djpower
    return {bucket: (values[0], values[1]) for bucket, values in totals.items()}


def level_capacity_totals(song_db: models.DMSongDB, bmode: int) -> dict[str, Decimal]:
    """Highest raw djpower each bucket could contribute to one 70-basic + 30-new best list.

    Every chart of a given pattern/level has the same theoretical djpower, so a bucket's
    maximum is simply its best 70 basic charts plus its best 30 new charts. That is the most
    this difficulty could contribute if the whole best 100 were drawn from it.
    """
    basic: dict[str, list[Decimal]] = {bucket: [] for bucket in LEVEL_BUCKET_ORDER}
    new: dict[str, list[Decimal]] = {bucket: [] for bucket in LEVEL_BUCKET_ORDER}

    for entry in song_db.root:
        bmode_data = getattr(entry.patterns, f"BMode_{bmode}")
        for diff_name in ("NM", "HD", "MX", "SC"):
            diff = getattr(bmode_data, diff_name)
            if diff is None:
                continue
            bucket = level_bucket_for("SC" if diff_name == "SC" else "NM", diff.level)
            if bucket not in basic:
                continue
            max_djpower = util.djpower_pp(util.diff_coeff(diff.level, diff_name == "SC"))
            (new if entry.is_new else basic)[bucket].append(max_djpower)

    capacities = {}
    for bucket in LEVEL_BUCKET_ORDER:
        basic_top = sorted(basic[bucket], reverse=True)[:LEVEL_BAR_BASIC_SLOTS]
        new_top = sorted(new[bucket], reverse=True)[:LEVEL_BAR_NEW_SLOTS]
        capacities[bucket] = sum(basic_top, Decimal(0)) + sum(new_top, Decimal(0))
    return capacities


def draw_level_distribution(bg: Image.Image, data: models.DMBests, box: tuple[int, int, int, int],
                            label_y: int, song_db: models.DMSongDB | None = None) -> None:
    """Draw the level histogram into a header's grey strip.

    `box` is (x0, y0, x1, y1); its height is the 100% reference. Every bar is the accumulated
    djpower of the best 100 records in one level bucket. Buckets that receive both basic-70 and
    new-30 records are stacked: the basic part in light grey, the new part in gold. With a song
    database, a faint ghost bar behind each column shows the most the difficulty could
    contribute to a best-100 list (its best 70 basic charts plus its best 30 new charts).
    """
    x0, y0, x1, y1 = box
    height = y1 - y0
    conv_const, _ = api_handler.get_convert_constant(data.bmode)
    totals = level_djpower_totals(data)
    capacities = level_capacity_totals(song_db, data.bmode) if song_db is not None else None

    draw = ImageDraw.Draw(bg)
    slot_width = (x1 - x0) / len(LEVEL_BUCKET_ORDER)
    bar_width = max(2, int(slot_width * LEVEL_BAR_FILL_RATIO))
    font = ImageFont.truetype(os.path.join(FONT_PATH, "Respect_bd.ttf"), LEVEL_BAR_FONT_SIZE)

    # The 100% guide is the plot's top edge; the fainter 25/50/75 guides sit between it and the
    # baseline, so the topmost line can never be mistaken for anything but 100%.
    for fraction in (0.25, 0.5, 0.75):
        guide_y = round(y1 - height * fraction)
        draw.line((x0, guide_y, x1, guide_y), fill=LEVEL_BAR_GRID_COLOR, width=1)
    draw.line((x0, y0, x1, y0), fill=LEVEL_BAR_TOP_COLOR, width=1)
    draw.line((x0, y1 + 2, x1, y1 + 2), fill=LEVEL_BAR_BASELINE_COLOR, width=2)

    def value_px(value: Decimal) -> int:
        share = min(value * conv_const / Decimal(10000), Decimal(1))
        return int(round(float(share) * height))

    columns = []
    for idx, bucket in enumerate(LEVEL_BUCKET_ORDER):
        center = x0 + (idx + 0.5) * slot_width
        left = int(round(center - bar_width / 2))
        columns.append((bucket, center, left, left + bar_width - 1))

    # Capacity first, as a translucent layer so the stripes and guides stay visible through it.
    if capacities is not None:
        layer = Image.new("RGBA", (x1 - x0, height))
        layer_draw = ImageDraw.Draw(layer)
        for bucket, _, left, right in columns:
            capacity_px = value_px(capacities[bucket])
            if capacity_px <= 0:
                continue
            capacity_top = (y1 - capacity_px) - y0
            local_left, local_right = left - x0, right - x0
            layer_draw.rectangle((local_left, capacity_top, local_right, height - 1),
                                 fill=(255, 255, 255, LEVEL_BAR_CAPACITY_ALPHA))
            layer_draw.line((local_left, capacity_top, local_right, capacity_top),
                            fill=(255, 255, 255, LEVEL_BAR_CAPACITY_TOP_ALPHA), width=1)
        bg.alpha_composite(layer, (x0, y0))
        layer.close()

    for bucket, center, left, right in columns:
        basic_power, new_power = totals[bucket]
        total_px = value_px(basic_power + new_power)
        if basic_power + new_power > 0:
            total_px = max(total_px, 2)

        # Basic-70 rests on the baseline; new-30 stacks on top of it inside a mixed bucket.
        if new_power > 0 and basic_power > 0:
            new_px = min(max(1, value_px(new_power)), total_px - 1)
            basic_px = total_px - new_px
        elif new_power > 0:
            new_px, basic_px = total_px, 0
        else:
            new_px, basic_px = 0, total_px

        if basic_px > 0:
            draw.rectangle((left, y1 - basic_px, right, y1 - 1), fill=LEVEL_BAR_BASIC_COLOR)
        if new_px > 0:
            draw.rectangle((left, y1 - total_px, right, y1 - basic_px - 1), fill=LEVEL_BAR_NEW_COLOR)

        label_color = LEVEL_BAR_LABEL_COLOR if basic_power + new_power > 0 else LEVEL_BAR_ZERO_LABEL_COLOR
        draw.text((center, label_y), bucket, font=font, fill=label_color, anchor="mt")
