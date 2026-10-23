import os, asyncio
from decimal import Decimal
from random import random
from PIL import Image, ImageDraw, ImageFont
from math import ceil

from ... import models, constants, api_handler, util


ASSET_PATH = os.path.join(os.path.dirname(__file__), "assets")
FONT_PATH = os.path.join(os.path.dirname(__file__), "..", "fonts")
EMBLEM_PATH = os.path.join(ASSET_PATH, "emblems")
EMBLEM_BG_PATH = os.path.join(ASSET_PATH, "emblem_bg")
DIFF_STAR_PATH = os.path.join(ASSET_PATH, "diff_stars")

# Level buckets of the header histogram, in increasing difficulty order. The official level
# scales overlap: diff_coeff() gives SC 2/4/6/8 the same coefficient as non-SC 12/13/14/15, so
# those pairs share one bucket (SC 12/14 are their own buckets and are not folded into 13/15).
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

# Geometry of the histogram: the dark grey strip between the "BASIC 70" bar (ends at 769) and
# the orange summary bar (starts at 2310), spanning the same height as those header bars. The
# 100% guide is therefore the strip's top edge, and 25/50/75 divide it evenly. The level labels
# sit in the small gap between the plot and the card grid.
LEVEL_BAR_BOX = (778, 533, 2302, 632)
LEVEL_BAR_LABEL_Y = 637
LEVEL_BAR_FONT_SIZE = 20
LEVEL_BAR_FILL_RATIO = 0.62
LEVEL_BAR_BASIC_COLOR = "#D2D2D2"
LEVEL_BAR_NEW_COLOR = "#F0BE40"
LEVEL_BAR_LABEL_COLOR = "#E4E4E4"
LEVEL_BAR_ZERO_LABEL_COLOR = "#7A7A7A"
LEVEL_BAR_BASELINE_COLOR = "#5A5A5A"
LEVEL_BAR_GRID_COLOR = "#444444"
LEVEL_BAR_TOP_COLOR = "#8A8A8A"

def __generate_single_song_sync(idx: int, card_type: str, song: models.DMSong, cover: Image.Image) -> Image.Image:
    with Image.open(os.path.join(ASSET_PATH, f"{card_type}_card.png")) as overlay:
        bg = Image.new("RGBA", overlay.size)
        with cover.resize((160, 160)) as _cover:
            bg.paste(_cover)
        bg.alpha_composite(overlay)

    draw = ImageDraw.Draw(bg)
    font_bd = ImageFont.truetype(os.path.join(FONT_PATH, "Respect_bd.ttf"), 23)
    font_rg = ImageFont.truetype(os.path.join(FONT_PATH, "Respect_rg.ttf"), 30)
    draw.text((10, 141), song.dlc_code, font=font_bd, fill=constants.DLC_COLOR.get(song.dlc_code, 'white'), anchor="lm")
    draw.text((165, 21), util.wrap_text(song.title, font_rg, 300), font=font_rg, fill='white', anchor="lm")

    font_bd = font_bd.font_variant(size=30)
    draw.text((230, 95), f"{song.score:.2f}%", font=font_bd, fill='white', anchor="lm")
    draw.text((292, 135), f"{song.djpower:.4f}", font=font_bd, fill='#F0BE40', anchor="lm")

    font_bd = font_bd.font_variant(size=26)
    draw.text((516, 17), f"#{idx}", font=font_bd, fill="black" if card_type == "new" else "#333333", anchor="mm")

    is_sc = song.pattern == "SC"
    with util.assemble_diff_strip_level(is_sc=is_sc, level_to=song.level, diff_star_path=DIFF_STAR_PATH) as diff_strip:
        bg.alpha_composite(diff_strip, (165, 52))

    if mc_state := util.get_mc_state(song.score, song.max_combo):
        with Image.open(os.path.join(ASSET_PATH, f"{mc_state}.png")) as mc_overlay:
            bg.alpha_composite(mc_overlay)

    return bg

async def generate_single_song(idx: int, card_type: str, song: models.DMSong) -> Image.Image:
    with await api_handler.get_cover(song.songid) as cover:
        img = await asyncio.to_thread(__generate_single_song_sync, idx, card_type, song, cover)
    return img


async def assemble_song_cards(songs: list[models.DMSong], card_type: str) -> Image.Image | None:
    gap = 20
    layout_width = 5
    bg = None

    for idx, song in enumerate(songs):
        with await generate_single_song(idx + 1, card_type, song) as song_image:
            if bg is None:
                bg = Image.new(
                    "RGBA",
                    (
                        (song_image.width + gap) * layout_width,
                        (song_image.height + gap) * ceil(len(songs) / layout_width)
                    )
                )

            x = (idx % 5) * (song_image.width + gap)
            y = (idx // 5) * (song_image.height + gap)
            bg.paste(song_image, (x, y))

    return bg


def level_bucket(song: models.DMSong) -> str:
    """The histogram bucket a best-100 entry belongs to."""
    merged = LEVEL_BUCKET_MERGED.get((song.pattern == "SC", song.level))
    if merged is not None:
        return merged
    return f"SC{song.level}" if song.pattern == "SC" else str(song.level)


def level_djpower_totals(data: models.DMBests) -> dict[str, tuple[Decimal, Decimal]]:
    """Raw djpower per level bucket, split into (basic-70, new-30) so mixed buckets can be stacked."""
    totals = {bucket: [Decimal(0), Decimal(0)] for bucket in LEVEL_BUCKET_ORDER}
    for column, songs in ((0, data.basic), (1, data.new)):
        for song in songs:
            values = totals.get(level_bucket(song))
            if values is not None:
                values[column] += song.djpower
    return {bucket: (values[0], values[1]) for bucket, values in totals.items()}


def draw_level_distribution(bg: Image.Image, data: models.DMBests) -> None:
    """Draw the level histogram into the grey area beside the "BASIC 70" section header.

    Every bar is the accumulated djpower of the best 100 records in one level bucket, as a
    share of the maximum 10000 djpower. Buckets that receive both basic-70 and new-30 records
    are stacked: the basic part in light grey, the new part in gold.
    """
    x0, y0, x1, y1 = LEVEL_BAR_BOX
    height = y1 - y0
    conv_const, _ = api_handler.get_convert_constant(data.bmode)
    totals = level_djpower_totals(data)

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

    for idx, bucket in enumerate(LEVEL_BUCKET_ORDER):
        center = x0 + (idx + 0.5) * slot_width
        left = int(round(center - bar_width / 2))
        right = left + bar_width - 1
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
        draw.text((center, LEVEL_BAR_LABEL_Y), bucket, font=font, fill=label_color, anchor="mt")


def assemble_background(data: models.DMBests, is_max: bool) -> Image.Image:
    bmode_strip_box = (119, 40, 151, 468)
    emblem_lt = (1029, 129)

    bg = Image.open(os.path.join(ASSET_PATH, "bg.png"))
    draw = ImageDraw.Draw(bg)

    djpower_tier, djpower_level = util.get_djpower_tier(data.total_djpower)
    djpower_desc = util.format_djpower_tier(djpower_tier, djpower_level)
    djpower_color = constants.DJPOWER_TIER_COLOR[djpower_tier]

    if random() < 0.1 and os.path.exists(os.path.join(EMBLEM_PATH, f"{djpower_tier}_0.png")): # Easter egg
        djpower_level = 0

    if os.path.exists(os.path.join(EMBLEM_BG_PATH, f"{data.username}.png")):
        with Image.open(os.path.join(EMBLEM_BG_PATH, f"{data.username}.png")) as emblem_bg:
            bg.alpha_composite(emblem_bg, emblem_lt)

    if not is_max:
        with Image.open(os.path.join(EMBLEM_PATH, f"{djpower_tier}_{djpower_level}.png")) as emblem:
            bg.alpha_composite(emblem, emblem_lt)

    font_bd = ImageFont.truetype(os.path.join(FONT_PATH, "Respect_bd.ttf"), 320)
    font_rg = ImageFont.truetype(os.path.join(FONT_PATH, "Respect_rg.ttf"), 80)
    font_lt = ImageFont.truetype(os.path.join(FONT_PATH, "Respect_lt.ttf"), 58)

    draw.rectangle(bmode_strip_box, fill=constants.BMODE_COLOR[data.bmode])
    draw.text((282, 370), str(data.bmode), font=font_bd, fill='white', anchor="ms")
    draw.text((1535, 187), data.username, font=font_rg, fill='white', anchor="lm")
    font_bd = font_bd.font_variant(size=64)
    draw.text((1535, 281), djpower_desc, font=font_bd, fill=djpower_color, anchor="lm")
    font_rg = font_rg.font_variant(size=120)
    if is_max:
        draw.text((1535, 375), f"10000.0000", font=font_rg, fill='white', anchor="lm")
    else:
        # Only draw interger with white and djpower color
        str_djpower = str(round(data.total_djpower, 4))
        draw.text((1538, 378), str_djpower.split('.')[0], font=font_rg, fill=djpower_color, anchor="lm")
        draw.text((1535, 375), str_djpower.split('.')[0], font=font_rg, fill='white', anchor="lm")
        # Draw decimal value if djpower is not 10000, decimal value is smaller and grey
    if not data.total_djpower == 10000:
        draw.text((1535 + font_rg.getlength(str_djpower.split('.')[0]), 385), "." + str_djpower.split('.')[1],
            font=font_rg.font_variant(size=100), fill='grey', anchor="lm")    
    font_rg = font_rg.font_variant(size=42)
    draw.text((1795, 464), f"{data.total_djpower_raw:.4f}", font=font_rg, fill='white', anchor="lm")

    font_rg = font_rg.font_variant(size=76)
    font_rg_s = font_rg.font_variant(size=46)

    draw.text((2520, 580), f"{data.total_basic_djpower:.4f}", font=font_rg, fill='white', anchor="mm")
    draw.text((2850, 600), f"{data.total_basic_djpower_raw:.4f}", font=font_rg_s, fill='white', anchor="mm")

    draw.text((2520, 3295), f"{data.total_new_djpower:.4f}", font=font_rg, fill='white', anchor="mm")
    draw.text((2850, 3315), f"{data.total_new_djpower_raw:.4f}", font=font_rg_s, fill='white', anchor="mm")

    conv_const, maxpower = api_handler.get_convert_constant(data.bmode)
    draw.text((570, 4553), f"{conv_const:.8f} ({maxpower:.2f})", font=font_lt, fill='white', anchor="ls")

    draw_level_distribution(bg, data)
    return bg
