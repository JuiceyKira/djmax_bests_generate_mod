"""The play-history chart: recent plays from records/history, one row per play.

Layout, top to bottom (width fixed at 2200, loop.png tiled as the background): a header band
showing the RESPECT logo (this module's own assets/logo.png) at the left, the light-weight
"HISTORY" title right of it and the account name in the regular face at the bar's right end,
vertically centred in the translucent bar the summary cover draws — no user photo, no
signature/info line; then
  1. the four button modes in their own columns, each a coloured accent bar plus, top to bottom,
     "<n>B TUNES" in that mode's colour, the djpower tier name in the tier's colour and, on the
     last line, the mode's final total djpower with the djpower it gained on that mode's most
     recent day with records (from history.replay_view) on its right; the column holding the
     highest total carries a BEST badge. Thin white separators divide the columns;
  2. then one section per play day, newest day first: the day as a left-aligned title with
     that day's play count (official adjustment rows are drawn but not counted) and its
     max-combo and perfect-play counts (max_combo.png /
     perfect.png) on its right, the record list's column header (TITLE / RATE / DJPOWER), and that
     day's plays, newest first — one row each: button badge with the play's local time
     (TIMEZONE) beneath it — a '+' prefixes the time when the local date has overflowed the
     section's day — cover, pattern badge, title on the left; MC/PP counter, score (result +
     increment) and djpower (result) plus the mode-total increase the play caused on the right.

Two windows pick which plays those sections hold, both sliced from the newest play backwards:
`recent100 = True` takes the latest MAX_ROWS plays; `recent100 = False` takes one whole play day —
the latest day holding a record in any mode, or, when `date` is given, the latest such day on or
before it — which is exactly the day the mode gains are measured over. Either window stops at
MAX_ROWS, so a busy window keeps its newest rows. Days are the stored (UTC) calendar days.

Everything below the header band is offset by its height (330), so the band never covers chart
content. Geometry is written as plain numbers; only the fonts are shared module-level objects,
sized per call with font_variant.

The chart is returned as a PIL image; this module never writes to disk. Saving is up to the
caller (runrun.py / inspect_history.py), which own its output path and file name.

`generate_history_snapshot(username, texts)` renders the same chart straight from a fetched
{bmode: raw text} snapshot — inspect_history.py uses it to look at another account without
touching the local store. A single snapshot cannot know superseded scores, so that variant
draws results only (no score/djpower increments) and final mode totals without a daily gain —
but the top-70/30 greying still applies, since the snapshot replays its own bests.
"""
import json
import os
from datetime import date
from zoneinfo import ZoneInfo
from decimal import Decimal

import pandas as pd
from PIL import Image, ImageDraw, ImageFont

from ... import api_handler, constants, util
from ...analyzer import data_converter, history

ASSETS_PATH = os.path.join(os.path.dirname(__file__), 'assets')
FONT_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'fonts')

WIDTH = 2200

TOP_PAD = 70
SECTION1_GAP = 55
TITLE_H = 120
HEADER_ROW_H = 58
ROW_H = 104
BOTTOM_PAD = 80


LEFT = 80
RIGHT = WIDTH - 80
BLOCK_W = (RIGHT - LEFT) // 4 + 15

MAX_ROWS = 50          # the record cap: recent window is sliced here
MAX_ROWS_SINGLEDAY = 200    # the record cap: a single play day is sliced here
BMODES = (4, 5, 6, 8)

PATTERN_COLORS = {'NM': '#F0A62E', 'HD': '#EA7F42',
                  'MX': '#E8506E', 'SC': '#AB54D6'}

# the timezone row times are displayed in (the day sections themselves stay on the stored
# UTC days; a row whose local date overflows the section's day gets a '+' before its time)
# Change this will also change song_history_generate's timezone
TIMEZONE = ZoneInfo("Asia/Shanghai")

font_bd = ImageFont.truetype(os.path.join(FONT_PATH, 'Respect_bd.ttf'), 100)
font_rg = ImageFont.truetype(os.path.join(FONT_PATH, 'Respect_rg.ttf'), 100)
font_lt = ImageFont.truetype(os.path.join(FONT_PATH, 'Respect_lt.ttf'), 100)

_counter_mc = Image.open(os.path.join(ASSETS_PATH, 'MC_counter.png')).convert('RGBA')
_counter_pp = Image.open(os.path.join(ASSETS_PATH, 'PP_counter.png')).convert('RGBA')
_icon_mc = Image.open(os.path.join(ASSETS_PATH, 'max_combo.png')).convert('RGBA')
_icon_pp = Image.open(os.path.join(ASSETS_PATH, 'perfect.png')).convert('RGBA')
_background = Image.open(os.path.join(ASSETS_PATH, 'loop.png')).convert('RGBA')
_logo = Image.open(os.path.join(ASSETS_PATH, 'logo.png')).convert('RGBA')


# ======================================================================
# Data selector
# ======================================================================

def _as_day(value):
    """A date the caller entered as a date-like object or a string. None passes through; an
    unreadable string raises, because silently ignoring it would chart the wrong day."""
    if value is None or isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value.strip())
    return value.date() if hasattr(value, 'date') else value


def _target_day(totals, prefer=None):
    """The single play day the one-day window reports: the latest day holding a record in any mode,
    or — when `prefer` (a date, or a 'YYYY-MM-DD' string) is given — the latest such day on or
    before it, so an entered date with no records falls back to the closest earlier day that has
    them, and an entered date older than the whole log falls back to its earliest day. None only
    when `totals` is empty. Days are the stored (UTC) calendar days."""
    if totals is None or totals.empty:
        return None
    days = sorted(totals['datetime'].dt.date.unique())
    prefer = _as_day(prefer)
    if prefer is None:
        return days[-1]
    eligible = [day for day in days if day <= prefer]
    return eligible[-1] if eligible else days[0]


def _recent_one_day(events: pd.DataFrame, day):
    """One whole play day's plays, newest first — the `date` selection (recent100 = False).

    `day` is the day _target_day resolved, so the rows and the mode gains describe the same play.
    It is selected from the whole replayed stream and only then capped at MAX_ROWS_SINGLEDAY:
    taking the newest MAX_ROWS_SINGLEDAY first would let the cap swallow an older day entirely,
    charting nothing at all. A None day (`totals` empty) falls back to the newest
    MAX_ROWS_SINGLEDAY. `events` is replay_view's uncapped newest-first stream."""
    if day is None:
        return events.head(MAX_ROWS_SINGLEDAY).reset_index(drop=True)
    return (events[events['datetime'].dt.date == day]
            .head(MAX_ROWS_SINGLEDAY).reset_index(drop=True))


def _recent(events: pd.DataFrame):
    """The latest MAX_ROWS plays across all modes, newest first — the recent100 = True selection.
    `events` is replay_view's uncapped newest-first stream; the cap lands wherever it lands, so
    the day the cap falls in simply carries fewer rows."""
    return events.head(MAX_ROWS).reset_index(drop=True)


# ======================================================================
# Caculator
# ======================================================================

def _mode_total_gains(totals, prefer=None) -> dict:
    """Per button mode: (total djpower as of the reported day, the djpower gained on that day —
    None when no such day exists).

    The day is one day, not a window: the latest day holding a record in *any* mode, or, when
    `prefer` (a date) is given, the latest such day on or before it. Both numbers follow that day,
    so tracing back into the past shows the totals and tiers the modes stood at *then*, not today's:
    the total is the mode's last value on or before the day — its closing total that day, or the
    total it still carried if it did not play — and the gain is that day's last value minus the
    last one before it (0 when the mode did not play that day, since its closing total did not
    move). A mode with no records up to that day reports (0, None).
    """
    if totals.empty:
        return {bmode: (Decimal(0), None) for bmode in BMODES}
    day = _target_day(totals, prefer)
    if day is None:
        return {bmode: (Decimal(0), None) for bmode in BMODES}

    info = {}
    for bmode in BMODES:
        series = totals[totals['button'] == bmode].sort_values('datetime', kind='stable')
        up_to_day = series[series['datetime'].dt.date <= day]
        if up_to_day.empty:                         # the mode had not played yet by that day
            info[bmode] = (Decimal(0), None, False)
            continue
        total = up_to_day.iloc[-1]['total_djpower']
        played = up_to_day[up_to_day['datetime'].dt.date == day]
        if played.empty:                            # the mode has played, but not on that day
            info[bmode] = (total, Decimal(0), False)
            continue
        before = series[series['datetime'].dt.date < day]
        start = before.iloc[-1]['total_djpower'] if len(before) else Decimal(0)
        info[bmode] = (total, util.cut_digits(played.iloc[-1]['total_djpower'] - start, 4), True)
    return info


def _mode_totals_snapshot(totals) -> dict:
    """Per button mode: (final total djpower, no gain, whether the mode holds a record on the
    latest day with one) — the snapshot path's counterpart of _mode_total_gains.

    A single snapshot cannot honestly compute a day's djpower gain — the gain is always None and
    the totals are the snapshot's final values, not a day's closing ones. `played` still follows
    the one day the one-day window reports — the latest day holding a record in any mode, the
    same day _target_day resolves for the rows — so a mode without a record on it draws grey
    exactly as it does on the local path.
    """
    if totals is None or totals.empty:
        return {bmode: (Decimal(0), None, False) for bmode in BMODES}
    day = _target_day(totals)
    info = {}
    for bmode in BMODES:
        series = totals[totals['button'] == bmode].sort_values('datetime', kind='stable')
        total = series.iloc[-1]['total_djpower'] if len(series) else Decimal(0)
        played = bool((series['datetime'].dt.date == day).any())
        info[bmode] = (total, None, played)
    return info


def _chart_extras() -> dict:
    """{(songid, button, pattern): (floor name, max djpower, dlc code, hint)} from the local
    records store.

    The play-event log carries no floorName, and its maxDjpower is the value at play time —
    the chart wants the store's current one, so it asks the store. dlc_code and hint are
    song-side attributes the log never carried. Any member is None when the store has no
    value for it. Returns an empty mapping when that store cannot serve the request (missing
    or stale, another account): those lines are then simply left out rather than failing the
    chart."""
    try:
        db = data_converter.load_records_db()
    except (OSError, ValueError, KeyError, data_converter.RecordsDbError):
        return {}
    rows = db[['songid', 'button', 'pattern', 'floor_name', 'max_djpower', 'dlc_code', 'hint']]
    return {(int(r.songid), int(r.button), str(r.pattern)):
            (r.floor_name, r.max_djpower, r.dlc_code, r.hint) for r in rows.itertuples()}


def _chart_extras_from_texts(texts: dict) -> dict:
    """{(songid, button, pattern): (floor name, max djpower, dlc code, hint)} straight from a
    fetched {bmode: raw response text}.

    The inspector path's counterpart of _chart_extras: a temporary records_db is built from
    the fetched response (songs joined, tags scored — exactly as the parquet is built), so
    this path gets the same song-side dlc_code and hint the local store serves, without
    touching the account-bound store. Any member is None when the frame has no value for it.
    Returns an empty mapping when the frame cannot be built."""
    try:
        db = data_converter.records_db_from_varecord(texts)
    except (OSError, ValueError, KeyError, data_converter.RecordsDbError):
        return {}
    rows = db[['songid', 'button', 'pattern', 'floor_name', 'max_djpower', 'dlc_code', 'hint']]
    return {(int(r.songid), int(r.button), str(r.pattern)):
            (r.floor_name, r.max_djpower, r.dlc_code, r.hint) for r in rows.itertuples()}

# ======================================================================
# Image generator
# ======================================================================

def _draw_header(canvas: Image.Image, username: str) -> None:
    """The chart's header band, over the same translucent bar the summary cover draws: the RESPECT
    logo at the left end, the light "HISTORY" title right of it, the account name in the regular
    face at the bar's right end, centred on the bar. No user photo, no signature/info line.
    Pillow's 'rm' anchor puts the ink of a single line of caps/lowercase ~10px below the anchor y
    (it allows for descenders), so the name's y takes that much back to make the *visible* text
    centre on the bar rather than only its anchor point."""
    bar = Image.new('RGBA', (WIDTH, 330))
    ImageDraw.Draw(bar).rectangle([(0, 135), (WIDTH, 255)], fill=(0, 0, 0, 100))
    canvas.alpha_composite(bar)
    canvas.alpha_composite(_logo, (100, 0))
    draw = ImageDraw.Draw(canvas)
    draw.text((320, 145), 'HISTORY', font=font_lt.font_variant(size=140), fill='white', anchor='lt')
    draw.text((WIDTH - 100, 190), username, font=font_rg.font_variant(size=90),
              fill='white', anchor='rm')


def _draw_button_summary(canvas: Image.Image, mode_info: dict, y: int, show_gain: bool = True) -> int:
    """The four button mode columns. Each block is a coloured accent bar with "<n>B TUNES" (mode colour),
    the djpower tier name (tier colour) and the final total djpower (white) stacked against it;
    the total's increase follows on the same line when a day gain is available. The highest total
    carries a BEST badge beside its label. Returns the section's height (the accent bar, 24..156,
    plus 16px above and below it) so the caller can lay the rest of the chart out below."""
    draw = ImageDraw.Draw(canvas)
    label_font, tier_font = font_bd.font_variant(size=40), font_bd.font_variant(size=42)
    score_font, gain_font = font_rg.font_variant(size=72), font_rg.font_variant(size=36)

    section_h = 124
    best = max(BMODES, key=lambda b: mode_info[b][0])
    bar_top = y + 16

    for i, bmode in enumerate(BMODES):
        block_x = LEFT + i * BLOCK_W
        text_x = block_x + 34          # 14px right of the accent bar
        total, gain, played_bool = mode_info[bmode]
        mode_color = constants.BMODE_COLOR[bmode]
        tier, step = util.get_djpower_tier(total)
        tier_color, tier_text = constants.DJPOWER_TIER_COLOR[tier], util.format_djpower_tier(tier, step)

        # the column's accent bar, in the mode's own colour
        draw.rectangle([(block_x, bar_top), (block_x + 8, y + 186)], fill=mode_color if played_bool else 'grey')

        label = f'{bmode}B TUNES'
        draw.text((text_x, y + 22), label, font=label_font, fill=mode_color if played_bool else 'grey', anchor='lt')

        if bmode == best:
            playpoint = round(float(total) * 0.48, 2)
            playpoint_length = round(font_bd.font_variant(size=60).getlength(str(playpoint)))
            _best_badge(draw, int(text_x + draw.textlength(label, font=label_font)) + 18, y + 14)
            draw.text((2180, 22), str(playpoint), font=font_bd.font_variant(size=60), fill='grey', anchor='rt')
            with Image.open(os.path.join(ASSETS_PATH, 'playpoint.png')).convert('RGBA') as img:
                canvas.alpha_composite(img, (2100 - playpoint_length,10))
            if gain is not None and gain != 0:
                draw.text((2180, 72), f"↑ {(float(gain) * 0.48):.2f}", font=font_bd.font_variant(size=40), 
                          fill='gold', anchor='rt')
        draw.text((text_x, y + 90), tier_text, font=tier_font, fill=tier_color, anchor='lm')

        score_text = f'{float(total):.4f}'
        if not show_gain:
            draw.text((text_x - 2, y + 155), score_text.split(".")[0], font=score_font, fill='white', anchor='lm')
            draw.text((text_x - 2 + int(draw.textlength(score_text.split(".")[0], font=score_font)), y + 160), 
                  "."+score_text.split(".")[1], font=score_font.font_variant(size=54), fill='white', anchor='lm')
            continue

        # the total sits on the text lane; the increase trails it with a fixed gap
        draw.text((text_x - 2, y + 155), score_text.split(".")[0], font=score_font, fill='white', anchor='lm')
        draw.text((text_x - 2 + int(draw.textlength(score_text.split(".")[0], font=score_font)), y + 160), 
                  "."+score_text.split(".")[1], font=score_font.font_variant(size=54), fill='white', anchor='lm')
        if gain is not None and gain != 0:
            # the day gain can go negative when an official maxpower adjustment steps the
            # total down between two plays — the arrow carries the direction
            gain_text = (f'↑{float(gain):.4f}' if gain > 0
                         else f'↓{float(-gain):.4f}')
            draw.text((text_x + int(draw.textlength(score_text, font=score_font)) - 48, y + 160),
                    gain_text, font=gain_font, fill=mode_color, anchor='lm')


    return section_h


def _draw_title_row(canvas: Image.Image, day, records_count:int, mc_count: int, pp_count: int, y: int) -> None:
    """Date and today's summary — the day's play count, its max combos and its perfect plays.
    The caller passes plays only: adjustment rows are left out of all three counts."""
    draw = ImageDraw.Draw(canvas)
    center = y + TITLE_H / 2
    draw.text((LEFT, center), f'{day.year}.{day.month:02d}.{day.day:02d}',
              font=font_bd.font_variant(size=64), fill='white', anchor='lm')
    
    # right-aligned groups: [max_combo icon + count] [perfect icon + count]
    icon_pp = _icon_pp.copy()
    icon_pp.thumbnail((56, 60))
    icon_mc = _icon_mc.copy()
    icon_mc.thumbnail((56, 60))
    
    # Perfect play
    text_width = int(draw.textlength(str(pp_count), font=font_bd.font_variant(size=52)))
    x = RIGHT
    draw.text((x, center), str(pp_count), font=font_bd.font_variant(size=52), fill='white', anchor='rm')
    x -= int(text_width + 2 * icon_pp.size[0])
    canvas.alpha_composite(icon_pp, (x, int(center - icon_pp.size[1] / 2)))
    
    # Max combo
    text_width = int(draw.textlength(str(mc_count), font=font_bd.font_variant(size=52)))
    x -= 56
    draw.text((x - 14, center), str(mc_count), font=font_bd.font_variant(size=52), fill='white', anchor='rm')
    x -= int(text_width + 2 * icon_mc.size[0])
    canvas.alpha_composite(icon_mc, (x, int(center - icon_mc.size[1] / 2)))
    
    # Today records
    text_width = int(draw.textlength(str(records_count), font=font_bd.font_variant(size=52)))
    x -= 56
    draw.text((x - 14, center), str(records_count), font=font_bd.font_variant(size=52), fill='white', anchor='rm')
    x -= int(text_width)
    draw.text((x - 50, center), 'RECORD:', font=font_bd.font_variant(size=52), fill='white', anchor='rm')


def _draw_column_header(canvas: Image.Image, y: int) -> None:
    """The record list's column header, drawn between the day title and the first row. TITLE sits
    on the song titles' left edge; RATE and DJPOWER are centred over their columns. The score is
    left-anchored at x=1360 in font_bd 40, the djpower at x=1790 in font_rg 40, so over the rows
    the columns are centred near 1360 + 134/2 = 1427 and 1790 + 146/2 = 1863."""
    draw = ImageDraw.Draw(canvas)
    font = font_bd.font_variant(size=40)
    center = y + HEADER_ROW_H / 2
    draw.text((LEFT + 312, center), 'TITLE', font=font, fill='white', anchor='lm')
    draw.text((1360 + 134 / 2, center), 'RATE', font=font, fill='white', anchor='mm')
    draw.text((1790 + 146 / 2, center), 'DJPOWER', font=font, fill='white', anchor='mm')


def _draw_record_row(canvas: Image.Image, row, cover: Image.Image, y: int,
                     show_deltas: bool = True, extras: dict | None = None) -> None:
    pattern = str(row.pattern)
    # the chart's floor and theoretical max djpower, from the store or the fetched response
    floor, max_djpower, dlc_code, hint = (
        extras or {}).get((int(row.songid), int(row.button), pattern), (None,) * 4)
    dlc_color = constants.DLC_COLOR.get(dlc_code, 'white')

    draw = ImageDraw.Draw(canvas)
    top = y + (ROW_H - 84) // 2

    _badge(canvas, LEFT, y + (ROW_H - 46) // 2, 70, 46,
           constants.BMODE_COLOR[int(row.button)], f'{int(row.button)}B', font_bd.font_variant(size=30))
    canvas.alpha_composite(cover.resize((84, 84)).convert('RGBA'), (LEFT + 88, top))
    # the dlc bar, flush against the cover's right edge
    draw.rectangle([LEFT + 172, top, LEFT + 174, top + 83], fill=dlc_color)

    badge_y = y + (ROW_H - 46) // 2
    _badge(canvas, LEFT + 192, badge_y, 96, 46,
           PATTERN_COLORS.get(pattern, (150, 150, 150)),
           f'{pattern} {int(row.level)}', font_rg.font_variant(size=30))
    
    # the play's local time under the button badge; '+' when the local date has overflowed
    # the section's (UTC) day
    local = row.datetime.tz_convert(TIMEZONE)
    time_text = local.strftime('%H:%M')
    if local.date() != row.datetime.date():
        time_text = '+' + time_text
    draw.text((LEFT + 35, y + ROW_H - 6), time_text,
              font=font_rg.font_variant(size=26), fill='darkgrey', anchor='ms')


    # the floor, centred under its badge, its baseline pinned above the row separator
    if floor is not None and str(floor) not in ('None', 'nan', '<NA>'):
        draw.text((LEFT + 240, y + ROW_H - 6), str(floor), font=font_rg.font_variant(size=26),
                  fill='darkgrey', anchor='ms')

    title = util.wrap_text(str(row.title), font_rg.font_variant(size=40), 700)
    draw.text((LEFT + 312, y + ROW_H / 2 - 2), title, font=font_rg.font_variant(size=40), fill='white', anchor='lm')

    # right side, left to right: MC/PP counter, score result (+ increment), djpower result
    # (+ the mode-total increase this play caused)
    if row.score == 100:
        canvas.alpha_composite(_counter_pp, (1245, y + (ROW_H - 70) // 2))
    elif row.max_combo:
        canvas.alpha_composite(_counter_mc, (1245, y + (ROW_H - 70) // 2))

    # One layout for both paths — the column positions are the delta layout's; a snapshot simply
    # has nothing to put in the increment columns, so those stay empty instead of shifting the
    # score and djpower left.
    draw.text((1360, y + ROW_H / 2 - 2), f'{float(row.score):.2f}%',
              font=font_bd.font_variant(size=40), fill=(232, 76, 61) if row.score == 100 else 'white', anchor='lm')
    if show_deltas:
        if row.prev_score != row.prev_score:        # NaN: the chart's first record (244, 106, 138)
            draw.text((1590, y + ROW_H / 2 - 2), 'NEW', font=font_rg.font_variant(size=36), fill=(244, 106, 138), anchor='lm')
        elif row.is_adjustment:                     # official recompute / reclassification
            draw.text((1590, y + ROW_H / 2 - 2), 'ADJ', font=font_rg.font_variant(size=36), fill=(130, 130, 130), anchor='lm')
        else:
            draw.text((1590, y + ROW_H / 2 - 2), f'+{float(row.delta_score):.2f}',
                      font=font_rg.font_variant(size=36), fill=(76, 217, 122), anchor='lm')
            
    # A play that moved its mode's replayed total by 0 never reached that mode's top-70 basic /
    # top-30 new set, so its djpower is greyed out — the chart's only sign that the number on this
    # row earned nothing. Both paths define total_gain: the snapshot replays its own bests, so
    # its greying follows its own replay.
    dodged = row.total_gain == 0
    draw.text((1790, y + ROW_H / 2 - 2), f'{float(row.djpower):.4f}',
              font=font_rg.font_variant(size=40), fill=(130, 130, 130) if dodged else 'white', anchor='lm')
    
    # the chart's theoretical max djpower, right under the value, in the floor line's style
    if max_djpower is not None and str(max_djpower) not in ('None', 'nan', '<NA>'):
        draw.text((1790, y + ROW_H - 6), f'{float(max_djpower):.2f}',
                  font=font_rg.font_variant(size=26), fill='lemonchiffon' if row.is_new
                  else 'darkgrey', anchor='ls')

    # the mode's replayed total after this play minus before it — 0.0000 when the play
    # stayed out of its mode's top-70/30
    if show_deltas and row.total_gain != 0:
        # pool-routing steps from reclassifications can make a row's own contribution negative
        gain_text = f'+{row.total_gain}' if row.total_gain > 0 else f'{row.total_gain}'
        draw.text((1980, y + ROW_H / 2 - 2), gain_text,
                  font=font_rg.font_variant(size=36), fill=constants.BMODE_COLOR[int(row.button)], anchor='lm')

    # separtor
    draw.line([LEFT, y + ROW_H - 1, RIGHT, y + ROW_H - 1], fill=(255, 255, 255, 36), width=2)


async def _render(username: str, recent, totals, *, show_deltas: bool, show_gain: bool,
                  prefer=None, extras: dict | None = None) -> Image.Image:
    """The shared drawing core: the header band, mode totals and then one section per play day —
    each with its date title, that day's counts and the column header over its rows — newest day
    first, the rows inside a day newest first. `prefer` narrows the day whose gain the mode columns
    report (already resolved by the caller, so None means "the latest day with records"); `extras`
    maps (songid, button, pattern) to (floor name, max djpower), drawn under the pattern badge and
    under the djpower value; an empty/None mapping leaves those lines out."""
    if recent.empty:
        raise ValueError(f'no play records for {username!r} — run `python refresh.py` first')

    # the days in play order, newest first (the caller already applied the recent100/date window)
    day_groups = [(day, group)
                  for day, group in recent.groupby(recent['datetime'].dt.date, sort=False)]

    if show_gain:
        mode_info = _mode_total_gains(totals, prefer)
    else:
        mode_info = _mode_totals_snapshot(totals)

    # the header band is 330 tall; the section reports its own height, so it is drawn first and the
    # day sections are laid out below whatever it used
    rows_total = sum(len(group) for _, group in day_groups)
    height = (330 + TOP_PAD + 164 + SECTION1_GAP
              + len(day_groups) * (TITLE_H + HEADER_ROW_H)
              + rows_total * ROW_H
              + BOTTOM_PAD)

    canvas = Image.new('RGBA', (WIDTH, height))
    for y in range(0, height, _background.size[1]):
        canvas.paste(_background, (0, y))

    _draw_header(canvas, username)
    section1_h = _draw_button_summary(canvas, mode_info, 260 + TOP_PAD, show_gain=show_gain)
    y = 330 + TOP_PAD + section1_h + SECTION1_GAP
    covers: dict[int, Image.Image] = {}

    for day, group in day_groups:
        # the three counts describe the day's plays: adjustment rows are not plays, so they stay
        # out of all of them (an adjustment carries a score and a max_combo of its own that the
        # day must not credit as new records)
        plays = group[~group['is_adjustment']]
        _draw_title_row(canvas, day, len(plays),
                        int(plays['max_combo'].sum()),
                        int((plays['score'] == 100).sum()),
                        y)
        _draw_column_header(canvas, y + TITLE_H)
        y += TITLE_H + HEADER_ROW_H
        for row in group.itertuples():
            if row.songid not in covers:
                covers[row.songid] = await api_handler.get_cover(int(row.songid))
            _draw_record_row(canvas, row, covers[row.songid], y, show_deltas=show_deltas,
                             extras=extras)
            y += ROW_H

    return canvas


# ======================================================================
# Assist tools
# ======================================================================

def _badge(canvas: Image.Image, x: int, y: int, w: int, h: int,
           color: tuple | str, text: str, font: ImageFont.FreeTypeFont) -> None:
    """Button mode and pattern"""
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle([x, y, x + w, y + h], radius=10, fill=color)
    draw.text((x + w / 2, y + h / 2 - 2), text, font=font, fill='white', anchor='mm')


def _rounded(img: Image.Image, radius: int = 12) -> Image.Image:
    """Round song covers"""
    img = img.convert('RGBA')
    mask = Image.new('L', img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, img.size[0] - 1, img.size[1] - 1], radius=radius, fill=255)
    img.putalpha(mask)
    return img

def _best_badge(draw: ImageDraw.ImageDraw, x: int, y: int) -> None:
    """The red BEST tag drawn beside the leading mode column's label."""
    font = font_bd.font_variant(size=28)
    w = int(draw.textlength('BEST', font=font)) + 28
    draw.polygon([(x, y), (x + w, y), (x + w - 20, y + 20), (x + w, y + 40), (x, y + 40)], fill=(229, 56, 65))
    draw.text((x + 40, y + 20), 'BEST', font=font, fill='white', anchor='mm')


# ======================================================================
# Interface
# ======================================================================

async def generate_history(username: str, recent100: bool = True, date=None,
                           target_date: list | None = None) -> Image.Image:
    """Render the play-history chart for `username` from the event log, with per-record
    increments; see the module docstring for the layout. Each row's floor name is looked up in the
    records store. `recent100` picks the window: True the latest MAX_ROWS plays, False the one play day
    `date` selects (the same day the mode gains are measured over). `date` is None for "the latest
    day with records", or a date to trace back from. The image is returned, not written.

    Passing a list as `target_date` gets the day actually charted appended to it — the day `date`
    resolved to, which is the one a caller should name the output file after."""
    events, totals = history.replay_view(username)
    if recent100:
        recent = _recent(events)
        day = None
    else:
        day = _target_day(totals, date)
        recent = _recent_one_day(events, day)
    if target_date is not None:
        target_date.append(day)
    return await _render(username, recent, totals, show_deltas=True, show_gain=True,
                         prefer=day, extras=_chart_extras())

async def generate_history_snapshot(username: str, texts: dict, recent100: bool = True) -> Image.Image:
    """Render the play-history chart straight from one fetched {bmode: raw response text}
    snapshot — the inspect_history path, for an account that must not touch the local store.
    Rows show results only: a single snapshot cannot know superseded scores, so there are no
    score/djpower increments, and the mode blocks show final totals without a daily gain. The
    top-70/30 greying still applies — each play's total_gain comes from replaying the snapshot's
    own bests, the same replay the totals come from. `recent100` picks the
    record window exactly as in generate_history, the one-day window being the latest day with
    records (this path takes no date). The image is returned, not written.

    The event frame drops floorName, but the raw response holds it, so the floor line under each
    pattern badge is filled from `texts` itself — the store is never queried on this path."""
    events, totals, gains = history.snapshot_view(username, texts)
    # a play's mode-total gain comes from the same replay walk as the totals — snapshot_view
    # returns both — so rows grey out on the top-70/30 exactly as they do on the local path
    events['total_gain'] = gains
    events = events.sort_values(['datetime'] + history.CHART_KEYS, ascending=False, kind='stable')
    if recent100:
        recent = events.head(MAX_ROWS).reset_index(drop=True)
    else:
        day = _target_day(totals)
        recent = (events[events['datetime'].dt.date == day].head(MAX_ROWS_SINGLEDAY).reset_index(drop=True)
                  if day is not None else events.head(MAX_ROWS_SINGLEDAY).reset_index(drop=True))
    return await _render(username, recent, totals, show_deltas=False, show_gain=False,
                         extras=_chart_extras_from_texts(texts))

