import os, random, sys
from typing import Literal
from decimal import Decimal
from math import ceil

from PIL import Image, ImageDraw, ImageFont, ImageEnhance
from ... import api_handler, util
from ... import constants
from ...analyzer import data_analyzer, data_converter
from . import tools

ASSETS_PATH = os.path.join(os.path.dirname(__file__), 'assets')
FONT_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)),'fonts')
COVER_PATH = api_handler.COVER_PATH

TAG_DICT = {
    'Jack': 'jack',
    'Longjack': 'longjack',
    'Stream': 'stream',
    'FX':'stream',
    'Stair': 'stair',
    'Trill': 'trill',
    'Chord': 'chord',
    'Long': 'longjob',
    'Side': 'side',
    'Complex': 'complex',
    'SV': 'speedvaration',
    'DoubleStairs': 'doublestairs',
    '6B Stair': 'stair6',
    '6B Basic': 'main6b',
    'Read': 'read',
    'Spike': 'difficultyspikes'
}

# ======================================================================
# 布局常量（基于 scorelist_generator 的排版，宽度固定 2200px）
# ======================================================================
CANVAS_WIDTH = 2200
CARD_SIZE = (180, 250)          # tools.single_song 的返回值尺寸（含 PP/MC 徽章与投影）
LAYOUT_WIDTH = 10               # 每行固定 10 张卡片
L_SPACE = 300                   # 左侧行头区宽度
R_SPACE = 110                   # 右侧留白
TOP_PADDING = 30                # 顶部留白
BOTTOM_PADDING = 30             # 底部留白
CARD_GAP_X = 0                 # 卡片横向间距
CARD_GAP_Y = -20                # 卡片纵向间距（同一等级换行时使用，可为负）
ROW_GAP = 10                  # 相邻行（不同等级）之间的额外间距，可为负
SEPARATOR_OFFSET = 10            # 分隔线相对行顶部的纵向偏移量

COLUMN_PITCH = CARD_SIZE[0] + CARD_GAP_X
GRID_WIDTH = (LAYOUT_WIDTH - 1) * COLUMN_PITCH + CARD_SIZE[0]

# 行头字体
font_bd = ImageFont.truetype(os.path.join(FONT_PATH, "Respect_bd.ttf"), 90)
font_rg = ImageFont.truetype(os.path.join(FONT_PATH, "Respect_rg.ttf"), 40)

# 行头下方两行小字（AVG. / Clear）用的字体与大概位置
LABEL_RIGHT_X = 280             # 两行小字右对齐的 x
LABEL_AVG_Y = 130               # 第一行 AVG. 相对行顶部的偏移
LABEL_CLEAR_Y = 172             # 第二行 Clear 相对行顶部的偏移


# ======================================================================
# 分组
# ======================================================================
def _group_key(song: data_converter.Song) -> str:
    """SC 行头为 SC+等级，非 SC 行头为纯等级。"""
    return f"SC{int(song.level)}" if song.is_sc else f"{int(song.level)}"


def grouping_songs_by_level(songlist: list[data_converter.Song]) -> dict[str, list[data_converter.Song]]:
    """
    按照 is_sc / level 把歌曲归类到对应行：SC 行 -> "SC10"，非 SC 行 -> "10"。
    返回的行顺序：先 SC 且等级降序，再非 SC 且等级降序。
    """
    groups: dict[str, list[data_converter.Song]] = {}
    for song in songlist:
        groups.setdefault(_group_key(song), []).append(song)

    def _sort_key(name: str) -> tuple[int, int]:
        is_sc = name.startswith("SC")
        return (0 if is_sc else 1, -int(name[2:] if is_sc else name))

    return {name: _sort_songs(groups[name]) for name in sorted(groups, key=_sort_key)}


def _sort_songs(songlist: list[data_converter.Song]) -> list[data_converter.Song]:
    """同一行内：已游玩（有分数）在前，分数降序，其余按标题稳定排序。"""
    return sorted(
        songlist,
        key=lambda s: (
            0 if s.score is not None else 1,
            -(float(s.score) if s.score is not None else 0.0),
            s.title,
        ),
    )


# ======================================================================
# 小字统计：AVG. / Clear
# ======================================================================
def _group_stats(songs: list[data_converter.Song]):
    """
    返回 (该组已游玩歌曲的平均 score, 已游玩数量, 该组歌曲总数)。
    一组里没有任何已游玩歌曲时平均值为 None。
    平均值用 util.cut_digits（两位小数，ROUND_FLOOR），与工程内其它平均值一致。
    """
    played = [s.score for s in songs if s.score is not None]
    if not played:
        return 0, 0, len(songs)
    return round(sum(played) / len(played), 2), len(played), len(songs)


def _draw_group_labels(painter: ImageDraw.ImageDraw, songs: list[data_converter.Song],
                       x_right: int, avg_y: int, clear_y: int) -> None:
    """
    在 (x_right, avg_y) / (x_right, clear_y) 处右对齐绘制两行小字：
        AVG.{平均score}%
        Clear {已游玩}/{总数}
    位置与遮挡由调用方决定。
    """
    avg_score, cleared, total = _group_stats(songs)
    avg_text = '100%' if avg_score == 100 else f"{avg_score}%"

    painter.text((x_right - 130, avg_y), f"Avg.",
                 font=font_rg.font_variant(size=36),
                 fill='white',
                 anchor='rs')
    painter.text((x_right, avg_y), avg_text,
                 font=font_bd.font_variant(size=36),
                 fill= 'gold' if avg_score == 100 else 'white',
                 anchor='rs')
    painter.text((x_right - 130, clear_y), f"Clear",
                 font=font_rg.font_variant(size=36),
                 fill='white',
                 anchor='rs')
    painter.text((x_right, clear_y), f'{cleared}/{total}',
                 font=font_bd.font_variant(size=36),
                 fill='gold' if cleared == total else 'white',
                 anchor='rs')

# ======================================================================
# 背景
# ======================================================================
def _assemble_background(height: int) -> Image.Image:
    """使用 assets/loop.png 纵向循环平铺出指定高度的背景。"""
    bg = Image.new("RGBA", (CANVAS_WIDTH, height))
    with Image.open(os.path.join(ASSETS_PATH, 'loop.png')) as loop:
        loop = loop.convert("RGBA")
        pasted_height = 0
        while pasted_height < height:
            bg.alpha_composite(loop, (0, pasted_height))
            pasted_height += loop.height
    return bg


# ======================================================================
# 绘制
# ======================================================================
def _render_song_card(draw_pattern_text: bool, song: data_converter.Song) -> Image.Image:
    """tools.single_song 的容错包装：缺失封面时退回 dummy 卡，避免整张长图渲染失败。"""
    try:
        return tools.single_song(draw_pattern_text, song)
    except (FileNotFoundError, OSError) as exc:
        print(f"tag_scorelist: 无法渲染 {song.songid} ({song.title})，已使用空白卡: {exc}",
              file=sys.stderr)
        card = Image.new("RGBA", CARD_SIZE)
        dummy = tools.dummy_song()
        card.alpha_composite(dummy, ((CARD_SIZE[0] - dummy.width) // 2, (CARD_SIZE[1] - dummy.height) // 2))
        return card


def _row_height(row_count: int) -> int:
    """一个等级行占用的高度：卡片行数 × 卡高 + 行间纵向间距。"""
    grid_rows = (row_count - 1) // LAYOUT_WIDTH + 1
    return grid_rows * CARD_SIZE[1] + (grid_rows - 1) * CARD_GAP_Y


def tag_scorelist_size(grouped: dict[str, list[data_converter.Song]]) -> tuple[int, int]:
    """计算画布尺寸：宽度固定 2200px，高度随行数与行内卡片数动态延展。"""
    height = TOP_PADDING + BOTTOM_PADDING
    for idx, (_, songs) in enumerate(grouped.items()):
        height += _row_height(len(songs))
        if idx != len(grouped) - 1:
            height += ROW_GAP
    return CANVAS_WIDTH, max(height, TOP_PADDING + BOTTOM_PADDING)


def draw_tag_scorelist(grouped: dict[str, list[data_converter.Song]],
                       draw_pattern_text: bool = True) -> Image.Image:
    """
    按行绘制全部歌曲（不论是否游玩）。
    :param grouped: grouping_songs_by_level 的返回值，键为行头（如 "SC10" / "10"）。
    :param draw_pattern_text: 是否在卡片上绘制难度文本（默认绘制，便于区分 NM/HD/MX/SC）。
    """
    if not grouped:
        return _assemble_background(TOP_PADDING + BOTTOM_PADDING)

    width, height = tag_scorelist_size(grouped)
    bg = _assemble_background(height)
    overlay = Image.new("RGBA", (width, height))
    painter = ImageDraw.Draw(overlay)

    y = TOP_PADDING
    last_index = len(grouped) - 1
    for idx, (name, songs) in enumerate(grouped.items()):
        block_height = _row_height(len(songs))

        # 行分隔线（首行不绘制）
#        if idx > 0:
        painter.line(
            [(L_SPACE, y - SEPARATOR_OFFSET), (width - R_SPACE, y - SEPARATOR_OFFSET)],
            fill='white', width=3)

        # 左侧行头：SC 行 "SC15"，非 SC 行 "15"
        painter.text((L_SPACE - 20, y + 55), name,
                     font=font_bd, fill='white', anchor='rm')

        # 行头下方两行小字
        _draw_group_labels(painter, songs,
                           280, y + 130, y + 172)

        for s_idx, song in enumerate(songs):
            col = s_idx % LAYOUT_WIDTH
            if s_idx != 0 and col == 0:
                y += CARD_SIZE[1] + CARD_GAP_Y
            card = _render_song_card(draw_pattern_text, song)
            overlay.alpha_composite(card, (L_SPACE + col * COLUMN_PITCH, y))

        y += CARD_SIZE[1] + (ROW_GAP if idx != last_index else 0)

    bg.alpha_composite(overlay)
    return bg


def generate_tag_scorelist(username:str, bmode:int, tag:str, level:int, songlist: list[data_converter.Song],draw_pattern_text: bool = True) -> Image.Image:
    """
    接收 data_converter.dataframe_to_song_list 传出的 list[Song]，
    使用 tools.single_song 批量绘制成 scorelist 风格的长图。
    """
    scorelist_img = draw_tag_scorelist(grouping_songs_by_level(songlist), draw_pattern_text=draw_pattern_text)
    canvas = Image.new('RGBA',(2200, 536 + scorelist_img.size[1]))
    with Image.open(os.path.join(ASSETS_PATH, 'header.png')) as img:
        canvas.paste(img)
    painter =ImageDraw.Draw(canvas)
    # Button mode and username
    painter.rectangle((70, 20, 89, 464), fill=constants.BMODE_COLOR[bmode])
    painter.text((193, 357), str(bmode), font=font_bd.font_variant(size=270), fill='white', anchor='ms')
    painter.text((873, 165), username, font=font_rg.font_variant(size=80), fill='white', anchor='lm')
    # Tag difficulty text
    tag_text = tag + " "
    for value in range(level):
        tag_text = tag_text + "I"
    painter.text((873, 240), tag_text, font=font_bd.font_variant(size=120), fill='white', anchor='lt')
    # Tag difficulty bar
    def _draw_tag_level(level, x, y, width, height):
        painter.rectangle([(x,y), (x + (width + 5) * level, y + height)], fill='coral', width=height)

        painter.rectangle([(x,y), (x + (width + 5)* 3, y + height)], width=5)
        painter.line([(x + width + 5,y), (x + width + 5, y + height)], width=5)
        painter.line([(x + (width + 5) * 2, y), (x + (width + 5) * 2, y + height)], width=5)
    _draw_tag_level(level, 873, 350, 300, 40)

    played = [s.score for s in songlist if s.score is not None]
    if played: avg_score = round(sum(played) / len(played), 2)
    else: avg_score =0
    painter.text((873, 410), "Avg.", font=font_rg.font_variant(size=60), fill='white', anchor='lt')
    painter.text((1073, 410), f'{avg_score}%', font=font_bd.font_variant(size=60), fill='white', anchor='lt')
    painter.text((1350, 410), "Clear", font=font_rg.font_variant(size=60), fill='white', anchor='lt')
    painter.text((1600, 410), f'{len(played)}/{len(songlist)}', font=font_bd.font_variant(size=60), 
                 fill='gold' if len(played) == len(songlist) else 'white', anchor='lt')
    canvas.paste(scorelist_img, (0,536))
    return canvas

def tag_scorelist(username:str, bmode:int, tag:str, level:int ):
    anaylze_util=data_analyzer.AnalyzeUtil()
    analyzer = anaylze_util.spawn_analyzer(bmode)
    argu = {}
    argu[TAG_DICT[tag]] = level
    songlist = data_converter.dataframe_to_song_list(analyzer.filter_tags(**argu))

    return generate_tag_scorelist(username, bmode, tag, level, songlist, False)