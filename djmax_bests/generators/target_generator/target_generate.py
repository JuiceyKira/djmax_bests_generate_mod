"""Render a TargetPlan as a bests-style image.

Layout is the bests one: the shared background (mode strip, DJ tier emblem, totals, conversion
factor) with the basic cards at (100, 691) and the new cards at (100, 3405), and it reads its
numbers from the projected top 100, so the header shows the total the plan actually reaches.
"""
from __future__ import annotations

import os
from decimal import Decimal

from PIL import Image, ImageDraw, ImageFont

from ... import api_handler
from .components import FONT_PATH, assemble_background, assemble_song_cards
from .target_plan import TargetPlan

BASIC_START = (100, 691)
NEW_START = (100, 3405)


def _caption(plan: TargetPlan) -> str:
    def number(value: Decimal) -> str:
        return format(value.normalize(), "f")

    text = f"TGT {number(plan.target_total)} : {number(plan.accuracy)}%"
    if plan.floor_cap is not None:
        text += f" (⤒{number(plan.floor_cap)})"
    if not plan.reachable:
        text += "  BEST EFFORT"
    return text


def _draw_caption(image: Image.Image, plan: TargetPlan) -> None:
    """The requested target, next to the total the plan actually reaches in the header."""
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(os.path.join(FONT_PATH, "Respect_rg.ttf"), 46)
    fill = '#E96464' if not plan.reachable else 'lightgrey'
    draw.text((200, 420), _caption(plan), font=font, fill=fill, anchor="lm")


def _draw_min_accuracy(image: Image.Image, plan: TargetPlan) -> None:
    """On an unreachable target, the accuracy the missing charts would have to be played at.

    Drawn on its own centred line under the caption; omitted when even 100% cannot get there
    (then only a higher difficulty cap would help).
    """
    # if plan.reachable or plan.min_accuracy is None:
    #     return
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(os.path.join(FONT_PATH, "Respect_rg.ttf"), 46)
    draw.text((200, 470), f"MIN ACC: {plan.min_accuracy}%", font=font,
              fill='lightgrey' if plan.reachable or plan.min_accuracy is None else '#E96464', anchor="lm")


def _draw_current_total(image: Image.Image, plan: TargetPlan) -> None:
    """What the button is worth right now, under the projected total the header draws."""
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(os.path.join(FONT_PATH, "Respect_rg.ttf"), 56)
    draw.text((1535, 524), f"NOW {plan.current_total}", font=font, fill='white', anchor="lm")
    draw.text((2080, 394), f"(↑{(plan.achieved_total - plan.current_total):.2f})", font=font, fill=(150, 150, 150), anchor="lm")


async def generate_target_image(plan: TargetPlan) -> Image.Image:
    """The projected top 100 of `plan`, marked up with the charts that have to be played.

    The background's 10% "easter egg" (the base tier emblem instead of the tier one) is left to
    the global RNG: the same plan renders a different emblem from one render to the next.
    """
    data = plan.to_dmbests()

    song_db = await api_handler.fetch_song_db()
    bg = assemble_background(data, is_max=False, song_db=song_db)
    basic_section = await assemble_song_cards(plan.basic.entries, "basic")
    new_section = await assemble_song_cards(plan.new.entries, "new")
    if basic_section is not None:
        bg.alpha_composite(basic_section, BASIC_START)
    if new_section is not None:
        bg.alpha_composite(new_section, NEW_START)
    _draw_current_total(bg, plan)
    _draw_caption(bg, plan)
    _draw_min_accuracy(bg, plan)
    return bg
