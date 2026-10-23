"""The single-chart play-history chart: one chart's plays, newest first, plus its tags radar.

Layout (width fixed at 2200, loop.png tiled as the background): a header with the chart's
identity at the left — button badge, cover, pattern badge, the title as a star strip for the
level, the hint badges under the title (one asset per hint token, from assets/hints/, each named
after the token it stands for; a chart with no hint draws none), and under them the floor name,
the theoretical max djpower and the play count — and the chart's tags radar at the right. The
radar plots the button mode's complete tag vocabulary —
the union of the tags the mode's charts carry in the records store — with the chart's own
maximum values and 0 for the tags it does not have (never the djpower-weighted tags_score),
through summary_generator's plot_tags_score_radar.

Below, the plays from newest to oldest — one row each, the main history chart's right side
verbatim: the MC/PP counter, the score result with its increment (NEW for the chart's first
record) and the djpower result with the top-70/30 greying plus the mode-total increase the play
caused; the left side is the play's own timestamp. A thin separator divides the rows.

Between the two, a compact stats band, wedged into the header block's lower-left free space —
under the song info, left of the radar, above the list: the best rate the list holds on its left,
and on its right when the chart's firsts happened — its first perfect play (FIRST PP), its first
max combo (FIRST MC) and its first play record (FIRST CLEAR). The band needs rows, so a chart with
no plays draws none, and the stamps reach only as far back as the list does (the log's depth; on
the snapshot path, its single current best).

A chart with no recorded plays renders too: the identity block comes from the records store's row
for it (a play list only carries title / level / pattern when there is a play to read them from),
the header's count reads `0 plays`, and a `no plays recorded` line stands in for the rows.

Two sources feed the play list:
  - `generate_song_history(username, songid, button, pattern)` reads the event log through
    history.chart_progression, so every superseded score the log has accumulated comes back,
    with increments;
  - `generate_song_history_snapshot(username, texts, songid, button, pattern)` builds the list
    from one fetched {bmode: raw response text} snapshot — the inspect path, for an account
    that must not touch the local store. A single snapshot cannot know superseded scores, so
    rows show results only and at most the chart's current best comes back.

The tags radar needs the records store (the event log and the raw response carry no tags), so
it is drawn only when the store can serve the chart — a missing, stale or foreign-account
store simply leaves the radar out instead of failing the chart. The tags themselves are
per-chart data, so the radar works for any account.

The chart is returned as a PIL image; this module never writes to disk. Saving is up to the
caller, which owns the output path and file name.
"""
import os
from decimal import Decimal
from zoneinfo import ZoneInfo

import pandas as pd
from PIL import Image, ImageDraw

from ... import api_handler, constants, util
from ...analyzer import data_converter, history
from ..summary_generator import tools
from . import history_generate as hg

WIDTH = hg.WIDTH
ROW_H = hg.ROW_H
LEFT = hg.LEFT
RIGHT = hg.RIGHT
BOTTOM_PAD = hg.BOTTOM_PAD
HEADER_H = 620          # the song-identity block and the radar
STATS_Y = 400           # the rate / firsts band: inside the header's lower-left free space
STATS_ROW_H = 60        # the line pitch of that band's three FIRST_* rows
STATS_LABEL_X = 1200    # the FIRST_* labels, right aligned (the radar starts at 1560)
STATS_TIME_X = 1520     # their timestamps, right aligned a little short of the radar
HEADER_ROW_H = 58       # the record list's column header

GREY = (170, 170, 170)
DODGE_GREY = (130, 130, 130)
DELTA_GREEN = (76, 217, 122)
NEW_PINK = (244, 106, 138)
PERFECT_RED = (232, 76, 61)
SEPARATOR = (255, 255, 255, 36)

RADAR_SIZE = 560

# The hint badges under the title: one asset per hint token, each file named exactly after the
# token it stands for (assets/hints/standard.png, assets/hints/assist-max.png, ...). They are
# drawn HINT_H tall, side by side from the title's left edge; a chart with no hint draws none.
HINT_PATH = os.path.join(hg.ASSETS_PATH, 'hints')
HINT_H = 48             # the assets are 98 px tall; this is the drawn height
HINT_GAP = 14           # between two badges
HINT_X = LEFT + 190     # the title's left edge
HINT_Y = 330            # between the title (270) and the info line (440)


def _real_plays(events: pd.DataFrame) -> pd.DataFrame:
    """Drop the log's adjustment rows (djpower recomputes and is_new reclassifications): they
    are not plays, so they are neither drawn nor counted in the play list or its header count.
    The stamped totals keep those rows, since they really moved the totals. A frame without
    the flag (the snapshot path's first-occurrence rows) gets it as all-False, so the flag can
    be relied on downstream."""
    if 'is_adjustment' not in events.columns:
        events = events.copy()
        events['is_adjustment'] = False
    return events[~events['is_adjustment'].astype(bool)]


def _chart_tags(songid: int, button: int, pattern: str) -> pd.Series | None:
    """The chart's tags as a Series over its button mode's full tag vocabulary: the union of
    the tags every one of the mode's charts carries in the records store, with the chart's own
    maximum value where it has one and 0 where it does not — so the radar always draws the
    mode's complete tag list, not just the axes this chart happens to light up. None only when
    the store cannot serve the request (missing, stale, another account) or the mode has no
    tagged charts at all. The tags are per-chart data, so this works for any account."""
    try:
        db = data_converter.load_records_db()
    except (OSError, ValueError, KeyError, data_converter.RecordsDbError):
        return None
    mode_rows = db[db['button'] == button]
    vocabulary: set[str] = set()
    for tags in mode_rows['tags']:
        if isinstance(tags, dict):
            vocabulary.update(tags)
    if not vocabulary:
        return None
    rows = mode_rows[(mode_rows['songid'] == songid)
                     & (mode_rows['pattern'] == str(pattern).upper())]
    own = rows.iloc[0]['tags'] if not rows.empty else {}
    own = own if isinstance(own, dict) else {}
    return pd.Series({tag: own.get(tag, 0) for tag in vocabulary}, dtype=float)


def _resolve_identity(progression: pd.DataFrame, songid: int, button: int,
                      pattern: str) -> tuple[str, int, str]:
    """The chart's (title, level, pattern) — what the header draws it from.

    The play list's newest row carries them whenever the chart has plays; a chart with none has
    no row to read them from, so the records store — which holds every chart of the song
    database, played or not — is asked instead. Its song side is the same for every account, so
    the snapshot path may use it as well. Raises ValueError when neither knows the chart.
    """
    if not progression.empty:
        row = progression.iloc[0]
        return str(row['title']), int(row['level']), str(row['pattern']).upper()
    try:
        db = data_converter.load_records_db()
    except (OSError, ValueError, KeyError, data_converter.RecordsDbError):
        db = None
    if db is not None:
        rows = db[(db['songid'] == songid) & (db['button'] == button)
                  & (db['pattern'].astype(str).str.upper() == str(pattern).upper())]
        if not rows.empty:
            row = rows.iloc[0]
            return str(row['title']), int(row['level']), str(row['pattern']).upper()
    raise ValueError(
        f'chart {songid} / {button}B / {pattern} has no plays and the records store has no row '
        f'for it either — check songid / button / pattern, or build the store with refresh.py')


def _draw_hint_badges(canvas: Image.Image, hint) -> None:
    """The chart's hint badges under its title: the `hint` string's tokens left to right, each
    one drawn from the asset named after it ("standard,assist-max" → standard.png then
    assist-max.png), left aligned with the title. Nothing is drawn for a chart without a hint —
    None, a parquet's NaN/NA hole or an empty string — nor for a token no asset exists for."""
    if not isinstance(hint, str) or not hint:
        return
    x = HINT_X
    for token in hint.split(','):
        path = os.path.join(HINT_PATH, f'{token.strip()}.png')
        if not os.path.exists(path):
            continue
        with Image.open(path) as asset:
            scale = HINT_H / asset.size[1]
            badge = asset.resize((round(asset.size[0] * scale), HINT_H),
                                 Image.Resampling.LANCZOS).convert('RGBA')
        canvas.alpha_composite(badge, (x, HINT_Y))
        x += badge.size[0] + HINT_GAP


def _draw_song_header(canvas: Image.Image, username: str, identity: tuple[str, int, str],
                      cover: Image.Image, extra_info: dict, tags: pd.Series | None,
                      button: int) -> None:
    """The account name at the top (the title's face, left-aligned with the cover), and the
    chart's identity below it at the left (button badge, cover, pattern badge, the level as a
    star strip, the title with the chart's hint badges under it, and the floor / max djpower /
    dlc / play-count line) with the tags radar at the right. `identity` is the chart's
    (title, level, pattern) and `plays` the size of the list below, so the header draws the same
    block for a chart with no plays. `extra_info` carries the song-side attributes the header
    shows: 'floor', 'max_djpower', 'dlc_code' and 'hint' — the first three are left out of the
    info line when absent, the hint is drawn as badges (`_draw_hint_badges`)."""
    draw = ImageDraw.Draw(canvas)
    title, level, pattern = identity

    # the username's background: a black translucent bar like the summary cover's decorate_bar,
    # tapering toward the bottom (an inverted trapezoid) and stopping short of the radar —
    # composited as its own layer, so the background texture shows through the translucent black
    bar = Image.new('RGBA', (WIDTH, 220))
    ImageDraw.Draw(bar).polygon([(0, 48), (1600, 48), (1500, 122), (0, 122)], fill=(0, 0, 0, 100))
    canvas.alpha_composite(bar)
    draw.text((LEFT, 60), username, font=hg.font_rg.font_variant(size=64),
              fill='white', anchor='lt')

    dlc_color = constants.DLC_COLOR.get(extra_info['dlc_code'], 'white')
    canvas.alpha_composite(hg._rounded(cover.resize((160, 160))), (LEFT, 180))
    
    # canvas.alpha_composite(cover.resize((160, 160)).convert('RGBA'), (LEFT, 180))
    hg._badge(canvas, LEFT + 190, 180, 90, 56, constants.BMODE_COLOR[int(button)],
              f'{int(button)}B', hg.font_bd.font_variant(size=36))
    hg._badge(canvas, LEFT + 296, 180, 90, 56,
              hg.PATTERN_COLORS.get(pattern, (150, 150, 150)),
              pattern, hg.font_rg.font_variant(size=36))
    # the level as a star strip (all stars up to the level lit) instead of a printed number
    strip = tools.star_strip(level_from=-1, level_to=int(level),
                             is_sc=pattern == 'SC', size=1)
    canvas.alpha_composite(strip, (LEFT + 402, 180 + (56 - strip.size[1]) // 2))

    title = util.wrap_text(str(title), hg.font_rg.font_variant(size=64), 1180)
    draw.text((LEFT + 190, 270), title, font=hg.font_rg.font_variant(size=64),
              fill='white', anchor='lt')
    _draw_hint_badges(canvas, extra_info.get('hint'))

    floor = extra_info.get('floor')
    if floor is not None and str(floor) not in ('None', 'nan', '<NA>'):
        draw.text((LEFT + 160, 351), floor, font=hg.font_rg.font_variant(size=30),
            fill='white', anchor='rt', stroke_fill='mediumslateblue',stroke_width=1)
    max_djpower = extra_info.get('max_djpower')
    if max_djpower is not None and str(max_djpower) not in ('None', 'nan', '<NA>'):
        draw.text((LEFT, 140), f'MAX {max_djpower:.2f}', font=hg.font_rg.font_variant(size=32),
            fill='grey', anchor='lt')
    dlc_code = extra_info.get('dlc_code')
    if dlc_code is not None and str(dlc_code) not in ('None', 'nan', '<NA>'):
        draw.text((LEFT, 350), dlc_code, font=hg.font_bd.font_variant(size=32),
                  fill=dlc_color, anchor='lt')

    if tags is not None:
        radar = tools.plot_tags_score_radar(tags, button).resize((RADAR_SIZE, RADAR_SIZE),
                                                                 Image.Resampling.LANCZOS)
        canvas.alpha_composite(radar, (RIGHT - RADAR_SIZE, 20))


def _draw_empty_note(canvas: Image.Image, y: int) -> None:
    """What stands in for the play list when the chart has no recorded plays: the identity block
    above already carries the chart and its `0 plays`, so the list itself just says so, at the
    x the timestamps and the column header use."""
    ImageDraw.Draw(canvas).text((LEFT + 190, y), 'NOT PLAYED',
                                font=hg.font_rg.font_variant(size=90), fill='white', anchor='lt')


def _draw_stats_band(canvas: Image.Image, progression: pd.DataFrame, y: int) -> None:
    """The band wedged between the song info, the tags radar and the play list — it fills the
    free space the header block has left under its identity column and beside the radar, so it
    costs the chart no height of its own.

    Left: RATE and the best score the list holds. Right, one line each, right aligned short of
    the radar: the chart's first perfect play (score 100), its first max combo and its first play
    record — the earliest row of the list that satisfies each, stamped the way the rows stamp
    themselves, with `-` for one the list never reached. `_render` draws this band only when the
    list has rows, and the list is as deep as its source: the event log's own depth on the local
    path, the single current best on the snapshot path (whose FIRST CLEAR is therefore that
    best's play time, not the first ever).
    """
    draw = ImageDraw.Draw(canvas)

    best = float(progression['score'].max())
    draw.text((LEFT + 750, y + 50), 'BEST RATE', font=hg.font_bd.font_variant(size=42),
              fill='white', anchor='rm')
    draw.text((LEFT + 750, y + 125), f'{best:.2f}%', font=hg.font_bd.font_variant(size=70),
              fill=PERFECT_RED if best == 100 else 'white', anchor='rm')
    
    draw.text((LEFT + 300, y + 50), 'PLAY COUNT', font=hg.font_bd.font_variant(size=42),
              fill='white', anchor='rm')
    draw.text((LEFT + 300, y + 125), f'{len(progression)}', font=hg.font_bd.font_variant(size=70),
              fill=PERFECT_RED if best == 100 else 'white', anchor='rm')
    
    stamps = (('FIRST PP', progression.loc[progression['score'] == 100, 'datetime'].min(), 
               PERFECT_RED),
              ('FIRST MC', progression.loc[progression['max_combo'].astype(bool),
                                          'datetime'].min(), 'cyan'),
              ('FIRST CLEAR', progression['datetime'].min(), 'white'))
    for i, (label, when, color) in enumerate(stamps):
        line = y + 28 + i * STATS_ROW_H
        draw.text((STATS_LABEL_X, line), label, font=hg.font_rg.font_variant(size=32),
                  fill=color, anchor='rm')
        text = '-' if pd.isna(when) else when.tz_convert(hg.TIMEZONE).strftime('%Y.%m.%d %H:%M')
        draw.text((STATS_TIME_X, line), text, font=hg.font_rg.font_variant(size=32),
                  fill='white', anchor='rm')


def _draw_column_header(canvas: Image.Image, y: int) -> None:
    """The play list's column header: PLAYED AT over the timestamps (the index column at the
    far left carries no header), RATE and DJPOWER centred over the same columns the main
    history chart's rows use."""
    draw = ImageDraw.Draw(canvas)
    font = hg.font_bd.font_variant(size=40)
    center = y + HEADER_ROW_H / 2
    draw.text((LEFT + 160, center), 'PLAYED AT', font=font, fill='white', anchor='lm')
    draw.text((1360 + 134 / 2, center), 'RATE', font=font, fill='white', anchor='mm')
    draw.text((1790 + 146 / 2, center), 'DJPOWER', font=font, fill='white', anchor='mm')


def _draw_play_row(canvas: Image.Image, row, y: int, index: int,
                   show_deltas: bool = True) -> None:
    """One play, newest first: the play's ordinal (#1 = the oldest play) at the far left, the
    timestamp next to it, then the main history chart's right side — MC/PP counter, score
    result (+ increment), djpower result with the top-70/30 greying (+ the mode-total increase
    the play caused). The snapshot path draws results only: a single snapshot cannot know
    superseded scores."""
    draw = ImageDraw.Draw(canvas)
    center = y + ROW_H / 2 - 2

    draw.text((LEFT, center), f'#{index}',
              font=hg.font_rg.font_variant(size=40), fill=GREY, anchor='lm')
    draw.text((LEFT + 160, center),
              row.datetime.tz_convert(hg.TIMEZONE).strftime('%Y.%m.%d %H:%M'),
              font=hg.font_rg.font_variant(size=40), fill='white', anchor='lm')

    if row.score == 100:
        canvas.alpha_composite(hg._counter_pp, (1245, y + (ROW_H - 70) // 2))
    elif row.max_combo:
        canvas.alpha_composite(hg._counter_mc, (1245, y + (ROW_H - 70) // 2))

    score_color = PERFECT_RED if row.score == 100 else 'white'
    draw.text((1360, center), f'{float(row.score):.2f}%',
              font=hg.font_bd.font_variant(size=40), fill=score_color, anchor='lm')
    if show_deltas:
        if row.prev_score != row.prev_score:        # NaN: the chart's first record
            draw.text((1590, center), 'NEW', font=hg.font_rg.font_variant(size=36),
                      fill=NEW_PINK, anchor='lm')
        else:
            draw.text((1590, center), f'+{float(row.delta_score):.2f}',
                      font=hg.font_rg.font_variant(size=36), fill=DELTA_GREEN, anchor='lm')

    dodged = row.total_gain == 0
    draw.text((1790, center), f'{float(row.djpower):.4f}',
              font=hg.font_rg.font_variant(size=40),
              fill=DODGE_GREY if dodged else 'white', anchor='lm')
    if show_deltas and row.total_gain != 0:
        gain_text = f'+{row.total_gain}' if row.total_gain > 0 else f'{row.total_gain}'
        draw.text((1980, center), gain_text,
                  font=hg.font_rg.font_variant(size=36),
                  fill=constants.BMODE_COLOR[int(row.button)], anchor='lm')

    draw.line([LEFT, y + ROW_H - 1, RIGHT, y + ROW_H - 1], fill=SEPARATOR, width=2)


async def _render(username: str, songid: int, button: int, identity: tuple[str, int, str],
                  progression: pd.DataFrame, extras: dict, tags: pd.Series | None,
                  show_deltas: bool) -> Image.Image:
    """The shared drawing core: the song header (stats band included), the column header and the
    play rows, newest first. `identity` is the chart's (title, level, pattern) — the play list's
    newest row when it has plays, the store's row for the chart otherwise. `progression` arrives
    newest-first with total_gain attached (the snapshot path replays its own bests for it, so the
    greying applies on both paths); an empty one draws the header plus a `NOT PLAYED` line instead
    of the band and the list."""
    height = HEADER_H + HEADER_ROW_H + len(progression) * ROW_H + BOTTOM_PAD
    canvas = Image.new('RGBA', (WIDTH, height))
    for y in range(0, height, hg._background.size[1]):
        canvas.paste(hg._background, (0, y))

    cover = await api_handler.get_cover(int(songid))
    floor, max_djpower, dlc_code, hint = extras.get(
        (int(songid), int(button), identity[2].upper()), (None,) * 4)
    extra_info = {'floor': floor, 'max_djpower': max_djpower,
                  'dlc_code': dlc_code, 'hint': hint}
    _draw_song_header(canvas, username, identity, cover, extra_info, tags, button)
    if progression.empty:
        _draw_empty_note(canvas, 525)
    else:
        _draw_stats_band(canvas, progression, STATS_Y)
        _draw_column_header(canvas, HEADER_H)

    y = HEADER_H + HEADER_ROW_H
    total = len(progression)
    for i, row in enumerate(progression.itertuples()):
        # rows render newest first, so the oldest play — the last row — carries #1
        _draw_play_row(canvas, row, y, index=i+1, show_deltas=show_deltas)
        y += ROW_H

    return canvas


async def generate_song_history(username: str, songid: int, button: int, pattern: str) -> Image.Image:
    """Render one chart's play history for `username` from the event log, newest first, with
    its tags radar; see the module docstring for the layout. A chart the log has no play for
    still renders — its header comes from the store's row for it and the list says so. The image
    is returned, not written."""
    progression = _real_plays(history.chart_progression(username, songid, button, pattern))
    identity = _resolve_identity(progression, songid, button, pattern)
    return await _render(username, songid, button, identity, progression,
                         hg._chart_extras(), _chart_tags(songid, button, pattern),
                         show_deltas=True)


async def generate_song_history_snapshot(username: str, texts: dict, songid: int,
                                         button: int, pattern: str) -> Image.Image:
    """Render one chart's play history straight from a fetched {bmode: raw response text}
    snapshot — the inspect path, for an account that must not touch the local store. A single
    snapshot cannot know superseded scores, so rows show results only and at most the chart's
    current best comes back (the top-70/30 greying still applies — the total_gain comes from
    replaying the snapshot's own bests). A chart the snapshot has no record on still renders,
    its header taken from the local store's row for it (the song side is account-independent).
    The image is returned, not written."""
    events, _totals, gains = history.snapshot_view(username, texts)
    events = _real_plays(events)        # adjustment rows are not plays (a snapshot has none —
    # this only pins the column)
    events['total_gain'] = gains
    progression = events[(events['songid'] == songid)
                         & (events['button'] == button)
                         & (events['pattern'].str.upper() == str(pattern).upper())]
    progression = (progression.sort_values(['datetime'] + history.CHART_KEYS,
                                           ascending=False, kind='stable')
                              .reset_index(drop=True))
    identity = _resolve_identity(progression, songid, button, pattern)
    return await _render(username, songid, button, identity, progression,
                         hg._chart_extras_from_texts(texts),
                         _chart_tags(songid, button, pattern),
                         show_deltas=False)
