"""Card renderer for the target generator.

Copied from generators/bests_generator/components.py so the projected top 100 keeps the exact
bests look; the differences are

  * cards take a `PlanEntry` (the plan knows what has to be played) instead of a `DMSong`;
  * a chart that has to be played uses the shared task card -- assets/new.png for a chart that
    newly enters the list, assets/up.png for one that was already listed and only gets a better
    score -- whichever bucket the song belongs to, so the card colour alone says which kind of
    task it is;
  * such a card also gets the matching corner badge (gold "NEW" / cyan "UP"); untouched cards
    keep their bucket card and no badge;
  * a chart that has a real floor rating shows it at the bottom-right of its cover, opposite the
    DLC code, in the same style the summary cards use (see summary_generator/tools.single_song).

Assets and fonts are read from this module's own assets/ directory (a copy of the bests one),
and `assemble_background` is copied in as well, so this package no longer imports
generators/bests_generator at all.
"""
from __future__ import annotations

import asyncio
import os
from math import ceil
from random import random

from PIL import Image, ImageDraw, ImageFont

from ... import api_handler, constants, models, util
from .target_plan import PlanEntry

ASSET_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
FONT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "fonts")
EMBLEM_PATH = os.path.join(ASSET_PATH, "emblems")
EMBLEM_BG_PATH = os.path.join(ASSET_PATH, "emblem_bg")
DIFF_STAR_PATH = os.path.join(ASSET_PATH, "diff_stars")

__all__ = ["assemble_background", "assemble_song_cards", "generate_single_song"]

#: card image + badge per task kind; charts without a task keep their bucket card
TASK_STYLE = {
    "new": {"card": "new.png", "color": (240, 190, 64), "label": "NEW"},
    "improve": {"card": "up.png", "color": (37, 222, 255), "label": "UP"},
}
BADGE_BOX = (446, 112, 552, 152)
BADGE_FONT_SIZE = 26


def _card_asset(card_type: str, task: str) -> str:
    """Task cards are shared between buckets; everything else uses the bucket card."""
    style = TASK_STYLE.get(task)
    return style["card"] if style else f"{card_type}_card.png"


def _draw_task_badge(draw: ImageDraw.ImageDraw, task: str) -> None:
    """Corner badge of a card that has to be played."""
    style = TASK_STYLE.get(task)
    if style is None:
        return
    color = style["color"]
    badge_font = ImageFont.truetype(os.path.join(FONT_PATH, "Respect_bd.ttf"), BADGE_FONT_SIZE)
    draw.rounded_rectangle(BADGE_BOX, radius=8, fill=(16, 16, 16, 235), outline=color, width=2)
    center = ((BADGE_BOX[0] + BADGE_BOX[2]) / 2, (BADGE_BOX[1] + BADGE_BOX[3]) / 2)
    draw.text(center, style["label"], font=badge_font, fill=color, anchor="mm")


def __generate_single_song_sync(idx: int, card_type: str, entry: PlanEntry,
                                cover: Image.Image) -> Image.Image:
    with Image.open(os.path.join(ASSET_PATH, _card_asset(card_type, entry.task))) as overlay:
        bg = Image.new("RGBA", overlay.size)
        with cover.resize((160, 160)) as _cover:
            bg.paste(_cover)
        bg.alpha_composite(overlay)

    draw = ImageDraw.Draw(bg)
    font_bd = ImageFont.truetype(os.path.join(FONT_PATH, "Respect_bd.ttf"), 23)
    font_rg = ImageFont.truetype(os.path.join(FONT_PATH, "Respect_rg.ttf"), 30)
    draw.text((10, 141), entry.pattern.dlc_code, font=font_bd,
              fill=constants.DLC_COLOR.get(entry.pattern.dlc_code, 'white'), anchor="lm")
    # Real floor rating, opposite the DLC code across the cover. Charts without a rated floor
    # show nothing here -- the design estimate is an ordering key, not a rating.
    if entry.pattern.floor is not None:
        floor_font = ImageFont.truetype(os.path.join(FONT_PATH, "Respect_bd.ttf"), 26)
        draw.text((152, 141), f"{entry.pattern.floor}", font=floor_font, fill='white',
                  anchor="rm", stroke_fill='mediumslateblue', stroke_width=1)
    draw.text((165, 21), util.wrap_text(entry.pattern.title, font_rg, 300), font=font_rg,
              fill='white', anchor="lm")

    font_bd = font_bd.font_variant(size=30)
    rate_text = f"{entry.score:.2f}%"
    draw.text((230, 95), rate_text, font=font_bd, fill='white', anchor="lm")
    # how much a chart with an existing record still has to gain, next to the rate
    record_score = entry.pattern.record_score
    if entry.task and record_score is not None:
        gain = entry.score - record_score
        if gain > 0:
            draw.text((230 + font_bd.getlength(rate_text), 95), f"(+{gain:.2f}%)",
                      font=font_bd, fill='lightgrey', anchor="lm")
    draw.text((292, 135), f"{entry.djpower:.4f}", font=font_bd, fill='#F0BE40', anchor="lm")

    font_bd = font_bd.font_variant(size=26)
    draw.text((516, 17), f"#{idx}", font=font_bd,
              fill="black" if card_type == "new" else "#333333", anchor="mm")

    is_sc = entry.pattern.pattern == "SC"
    with util.assemble_diff_strip_level(is_sc=is_sc, level_to=entry.pattern.level,
                                        diff_star_path=DIFF_STAR_PATH) as diff_strip:
        bg.alpha_composite(diff_strip, (165, 52))

    # MC/PP badges only describe a record the player really has, so tasks never show them
    mc_state = None if entry.task else util.get_mc_state(
        entry.score, entry.pattern.record_max_combo)
    if mc_state:
        with Image.open(os.path.join(ASSET_PATH, f"{mc_state}.png")) as mc_overlay:
            bg.alpha_composite(mc_overlay)

    _draw_task_badge(draw, entry.task)
    return bg


async def generate_single_song(idx: int, card_type: str, entry: PlanEntry) -> Image.Image:
    with await api_handler.get_cover(entry.pattern.songid) as cover:
        return await asyncio.to_thread(__generate_single_song_sync, idx, card_type, entry, cover)


async def assemble_song_cards(entries: list[PlanEntry], card_type: str) -> Image.Image | None:
    gap = 20
    layout_width = 5
    bg = None

    for idx, entry in enumerate(entries):
        with await generate_single_song(idx + 1, card_type, entry) as song_image:
            if bg is None:
                bg = Image.new(
                    "RGBA",
                    (
                        (song_image.width + gap) * layout_width,
                        (song_image.height + gap) * ceil(len(entries) / layout_width)
                    )
                )

            x = (idx % 5) * (song_image.width + gap)
            y = (idx // 5) * (song_image.height + gap)
            bg.paste(song_image, (x, y))

    return bg


# --------------------------------------------------------------------------------------
# background / header
# --------------------------------------------------------------------------------------
def assemble_background(data: models.DMBests, is_max: bool) -> Image.Image:
    """The shared bests header, copied verbatim from generators/bests_generator/components.py.

    Keeping the copy here is what makes this package independent of the bests generator; the
    rendering (mode strip, tier emblem, totals, conversion factor) is unchanged. `is_max` is
    kept for fidelity -- the target generator always renders the normal header.
    """
    bmode_strip_box = (119, 40, 151, 468)
    emblem_lt = (1029, 129)

    bg = Image.open(os.path.join(ASSET_PATH, "bg.png"))
    draw = ImageDraw.Draw(bg)

    djpower_tier, djpower_level = util.get_djpower_tier(data.total_djpower)
    djpower_desc = util.format_djpower_tier(djpower_tier, djpower_level)
    djpower_color = constants.DJPOWER_TIER_COLOR[djpower_tier] + '80'

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
        draw.text((1535, 375), f"10000", font=font_rg, fill='white', anchor="lm")
    else:
        # Only draw interger with white and djpower color
        str_djpower = str(round(data.total_djpower, 4))
        draw.text((1538, 378), str_djpower.split('.')[0], font=font_rg, fill=djpower_color, anchor="lm")
        draw.text((1535, 375), str_djpower.split('.')[0], font=font_rg, fill='#FFFFFF80', anchor="lm")
        # Draw decimal value if djpower is not 10000, decimal value is smaller and grey
    if not data.total_djpower == 10000:
        draw.text((1535 + font_rg.getlength(str_djpower.split('.')[0]), 385), "." + str_djpower.split('.')[1],
            font=font_rg.font_variant(size=100), fill='grey', anchor="lm")
    font_rg = font_rg.font_variant(size=42)
    draw.text((1795, 464), f"{data.total_djpower_raw:.4f}", font=font_rg, fill='grey', anchor="lm")

    font_rg = font_rg.font_variant(size=76)
    font_rg_s = font_rg.font_variant(size=46)

    draw.text((2520, 580), f"{data.total_basic_djpower:.4f}", font=font_rg, fill='white', anchor="mm")
    draw.text((2850, 600), f"{data.total_basic_djpower_raw:.4f}", font=font_rg_s, fill='white', anchor="mm")

    draw.text((2520, 3295), f"{data.total_new_djpower:.4f}", font=font_rg, fill='white', anchor="mm")
    draw.text((2850, 3315), f"{data.total_new_djpower_raw:.4f}", font=font_rg_s, fill='white', anchor="mm")

    conv_const, maxpower = api_handler.get_convert_constant(data.bmode)
    draw.text((570, 4553), f"{conv_const:.8f} ({maxpower:.2f})", font=font_lt, fill='white', anchor="ls")

    return bg
