import os, io
import numpy as np
import matplotlib.pyplot as plt
import matplotlib

from typing import Literal
from decimal import Decimal

from PIL import Image, ImageDraw, ImageFont
from ... import api_handler, util
from ... import constants as c
from ...analyzer import data_analyzer, data_converter

ASSETS_PATH = os.path.join(os.path.dirname(__file__), 'assets')
FONT_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)),'fonts')
COVER_PATH = api_handler.COVER_PATH
EMBLEM_PATH = os.path.join(os.path.dirname(__file__), 'assets\\emblems')

font_bd = ImageFont.truetype(os.path.join(FONT_PATH, "Respect_bd.ttf"), 100)
font_rg = ImageFont.truetype(os.path.join(FONT_PATH, "Respect_rg.ttf"), 100)
font_lt = ImageFont.truetype(os.path.join(FONT_PATH, "Respect_lt.ttf"), 100)

TAG_NAME = ['Jack', 'Longjack', 'Chord', 'Long', 'Stream', 'Trill', 'Stair']


def djtier_color(djpower:Decimal):
    djpower_color = c.DJPOWER_TIER_COLOR[util.get_djpower_tier(djpower)[0]]
    return djpower_color

# 渐变图像生成
def draw_gradient(img, start, end):
    px = img.load()
    for y in range(0, img.height):
        color = tuple(int(start[i] + (end[i] - start[i]) * y / img.height) for i in range(3))
        for x in range(0, img.width):
            px[x, y] = color

#渐变文字生成
def text_gradient(background,xy,font,text,start,end):
    w, h = font.getbbox(text)[2:]
    gradientbox = Image.new("RGB", (w, h))
    draw_gradient(gradientbox, start, end)
    drawmask = Image.new("RGBA", (w, h))
    drawtext = ImageDraw.Draw(drawmask)
    drawtext.text((0, 0), text, font=font)
    background.paste(gradientbox, xy, drawmask)


def resize_image(canvas:Image.Image, size:float) -> Image.Image:
    width, height = canvas.size
    return canvas.resize((round(width*size), round(height*size)),Image.Resampling.LANCZOS)

def button_tunes(bmode:int, size:float):
    drawing_board = Image.new('RGBA',(600,300))
    painter = ImageDraw.Draw(drawing_board)

    painter.rectangle((70, 20, 89, 420), fill='#5BD777'if bmode == 4 else '#62BBE2' if bmode == 5 else '#DE9441' if bmode == 6 else '#878FFA')
    painter.text((130, 40), f'{bmode}', fill='white', anchor='lt', font=font_bd.font_variant(size=180))
    painter.text((250, 50), 'BUTTON', fill='grey', anchor='lt', font=font_bd.font_variant(size=70))
    painter.text((252, 110), 'TUNES', fill='grey', anchor='lt', font=font_lt.font_variant(size=70))
    drawing_board=resize_image(drawing_board, size)
    return drawing_board

def tags_score(skill:dict, width:int, height:int):
    drawing_board = Image.new('RGBA',(2200,600))
    painter = ImageDraw.Draw(drawing_board)
    offset_x = 600
    offset_y = 100

    with Image.open(os.path.join(ASSETS_PATH, 'skills.png')) as img:
        drawing_board.alpha_composite(img, (100, 80))

    def _draw_skill(skill:float, width:int, height:int):
        bg = Image.new('RGBA',((width + 5) * 3,height))
        draw= ImageDraw.Draw(bg)
        rectangles = round(skill // 1)
        if rectangles >= 1:draw.rectangle([(0,0), (0 + (width + 5) * rectangles, height)], fill='coral', width=height)
        draw.rectangle([((5 + width) * rectangles, 0), ((5 + width) * rectangles + round(width * (skill - rectangles)),height)], fill='grey', width=height)

        draw.rectangle([(0,0), ((width + 5)* 3, height)], width=5)
        draw.line([(width + 5,0), (width+5, height)], width=5)
        draw.line([((width + 5) * 2, 0), ((width + 5) * 2, height)], width=5)
        return bg
    


    for tag in TAG_NAME:
        painter.text((offset_x, offset_y - 80), tag, font=font_rg.font_variant(size = 60))
        drawing_board.alpha_composite(_draw_skill(skill[tag], width, height), (offset_x, offset_y))
        painter.text((offset_x + 320, offset_y - 20), f'{skill[tag]}', font=font_bd.font_variant(size = 60))
        if offset_x != 1600: offset_x += 500
        else:
            offset_x = 100
            offset_y += 150

        #offset_y += 100
    return drawing_board

def draw_donut_chart(fill_value, inner_radius=800)->Image.Image:
    """
    根据 fill_value 数值，对无颜色的饼图进行填充 (12点方向起，逆时针，终点无白边)，并挖空中心形成圆环。
    :param fill_value: 填充的数值 (0 到 10000 之间)
    :param base_image_path: 无颜色的饼图文件路径 (png格式，需按12点方向逆时针划分扇区)
    :param output_path: 输出文件的路径
    :param inner_radius: 中间透明圆的半径 (默认450，外半径为900)
    """
    # 1. 加载无颜色的基础饼图
    base_img = Image.open(os.path.join(ASSETS_PATH, 'data_pie_chart.png')).convert('RGBA')
        
    width, height = base_img.size
    cx, cy = width // 2, height // 2
    r = width // 2
    
    # 2. 原始数据与颜色配置
    data = [500, 1900, 1600, 1200, 1000, 800, 800, 800, 400, 400, 300, 200, 80, 20]
    color = ['#A0A0A0', '#A0C4E9', '#72BCCF', '#68C8C5', '#79CEAA', '#81D261', 
             '#B5DA36', '#EFEF65', '#F7C843', '#F19E3B', '#F28140', '#F17055',
             '#F16667', '#EAD1EE']
    
    total = sum(data) # 总和为 10000

        
    # 计算各个扇区的角度
    angles = [value / total * 360 for value in data]
    
    # 3. 创建透明图层用于绘制彩色部分
    overlay = Image.new('RGBA', (width, height), (255, 255, 255, 0))
    draw = ImageDraw.Draw(overlay)
    bbox = [0, 0, width, height]
    
    # 关键修改：起始角度为 -90 (12点钟方向)
    start_angle = -90  
    total_data = 0
    
    # 4. 遍历数据，逆时针绘制彩色扇区
    for i in range(len(data)):
        val = data[i]
        angle = angles[i]
        
        if total_data >= fill_value:
            break
            
        # 逆时针：下一个角度是减去当前角度
        end_angle = start_angle - angle
        
        if total_data + val <= fill_value:
            # 情况A: 当前扇区可以完全填充 (保留白色描边)
            draw.pieslice(bbox, min(start_angle, end_angle), max(start_angle, end_angle), 
                          fill=color[i], outline='grey', width=5)
            total_data += val
            start_angle = end_angle
        else:
            # 情况B: 当前扇区只能部分填充 (终点不保留白色描边)
            ratio = (fill_value - total_data) / val
            partial_angle = angle * ratio
            end_angle = start_angle - partial_angle
            
            # 绘制彩色部分，不设置 outline 以避免截断处出现白线
            draw.pieslice(bbox, min(start_angle, end_angle), max(start_angle, end_angle), 
                          fill=color[i], outline=None)
            
                    
            total_data = fill_value
            break
            
    # 5. 将透明图层与原图合并
    result = Image.alpha_composite(base_img, overlay)
    
    # ================= 新增：挖空中心并绘制圆环白边 =================
    if inner_radius > 0:
        # 计算内圆边界框
        inner_bbox = [cx - inner_radius, cy - inner_radius, cx + inner_radius, cy + inner_radius]
        
        # 在合并后的图像上画一个实心透明圆，并加上白色描边
        draw_result = ImageDraw.Draw(result)
        draw_result.ellipse(inner_bbox, fill=(0, 0, 0, 0), outline=None, width=5)
    # ==============================================================    
    return result


def donuts(value, radius, size):
    drawing_board = Image.new('RGBA',(1800,1800))
    drawing_board.paste(draw_donut_chart(value,radius))
    #Resize
    drawing_board=resize_image(drawing_board, size)
    return drawing_board

def cover_path_or_placeholder(songid) -> str:
    """Cover file for a song, falling back to the bundled placeholder jacket when it is missing.

    The executable ships only `dummy.jpg`; real jackets are downloaded by the first refresh, so a
    song released after that refresh can legitimately have no file yet. The summary must still
    render instead of raising FileNotFoundError.
    """
    path = os.path.join(COVER_PATH, f'{songid}.jpg')
    if os.path.exists(path):
        return path
    placeholder = os.path.join(COVER_PATH, 'dummy.jpg')
    if os.path.exists(placeholder):
        return placeholder
    return os.path.join(ASSETS_PATH, 'dummy.jpg')


def single_song(draw_pattern_text:bool, song: data_converter.Song) -> Image.Image:
        # Main body
        with Image.open(os.path.join(ASSETS_PATH, "card.png" if song.score is None else "card_perfect.png" if song.score == 100 else "card_max.png" if song.max_combo else "card_clear.png" )) as overlay:
            bg = Image.new("RGBA", overlay.size)
            with Image.open(cover_path_or_placeholder(song.songid)) as cover:
                with cover.resize((160, 160)) as _cover:
                    bg.paste(_cover)
            bg.alpha_composite(overlay)

        draw = ImageDraw.Draw(bg)
        font_bd = ImageFont.truetype(os.path.join(FONT_PATH, "Respect_bd.ttf"), 26)


        #DLC code
        draw.text((8, 152), song.dlc_code, font=font_bd, fill=c.DLC_COLOR.get(song.dlc_code, 'white'), anchor="ls")
        #Pattern text
        if draw_pattern_text:
            draw.text((152, 152), f'{song.pattern}{song.level}', font=font_bd, fill=c.DIFF_COLOR[song.pattern], anchor="rs")

        #Score
        font_bd = font_bd.font_variant(size=30)
        draw.text(
            (80, 178),
            "-" if song.score is None else "100%" if song.score == 100 else f"{song.score:.2f}%",
            font=font_bd,
            fill='gray' if song.score is None else 'hotpink' if song.score == 100 else'darkorange' if song.score > 99.89 else 'orange' if song.score >= 99.5 else 'gold' if song.score >= 99 else 'yellow' if song.score >= 98.5 else 'greenyellow' if song.score >= 98 else 'lime' if song.score >= 97 else 'cyan' if song.score >= 96 else 'white',
            anchor="mm"
        )

        # Decorator
        large_bg = Image.new("RGBA", (180, 250))
        large_bg.paste(bg, (0, 25))

        if song.score != None and song.score == 100:
            with Image.open(os.path.join(ASSETS_PATH, "PP_badge.png")) as badge:
                large_bg.alpha_composite(badge, (120, 6))
        elif song.max_combo:
            with Image.open(os.path.join(ASSETS_PATH, "MC_badge.png")) as badge:
                large_bg.alpha_composite(badge, (120, 6))
        #Floor
        draw = ImageDraw.Draw(large_bg)
        if song.floor_name != None: 
            draw.text((0, 0), str(song.floor_name), font=font_bd.font_variant(size=26), fill='white', anchor="lt", stroke_fill='mediumslateblue',stroke_width=1)
        return large_bg

def dummy_song() -> Image.Image:
        # Main body
        with Image.open(os.path.join(ASSETS_PATH, "card.png" )) as overlay:
            bg = Image.new("RGBA", overlay.size)
            with Image.open(cover_path_or_placeholder('dummy')) as cover:
                with cover.resize((160, 160)) as _cover:
                    bg.paste(_cover)
            bg.alpha_composite(overlay)

        draw = ImageDraw.Draw(bg)
        font_bd = ImageFont.truetype(os.path.join(FONT_PATH, "Respect_bd.ttf"), 26)

        #Score
        font_bd = font_bd.font_variant(size=30)
        draw.text((80, 178),"-", font=font_bd, fill='gray', anchor="mm")

        return bg

#Single line only, max to 10
def multi_songs(draw_pattern_text:bool, songlist: list[data_converter.Song]) -> Image.Image:
    bg = Image.new('RGBA', (1800,250))
    count = 0
    for song in songlist:
        bg.alpha_composite(single_song(draw_pattern_text, song),(0 + count * 180, 0))
        count += 1
    return bg

def star_strip(level_from:int, level_to:int, is_sc:bool, size) -> Image.Image:
    drawing_board = util.assemble_diff_strip_base(is_sc=is_sc,level_from=level_from,level_to=level_to,draw_range_indicator=False,diff_star_path=os.path.join(ASSETS_PATH, "diff_stars"))
    drawing_board = resize_image(drawing_board, size)
    return drawing_board

def star_song(songdf:data_analyzer.pd.DataFrame, rendermode:Literal['text', 'max_combo', 'perfect'], number1:int, number2:int = 0, left_icon:bool=False, right_icon:bool=False, progbar:bool=False, text:str = 'Example') -> Image.Image:
    drawing_board = Image.new('RGBA',(1250,300))
    painter = ImageDraw.Draw(drawing_board)

    drawing_board.paste(star_song_simple(songdf,False), (0,20))
    if rendermode in['max_combo','perfect']:
        with Image.open(os.path.join(ASSETS_PATH,f'{rendermode}.png')) as img:
            if left_icon: drawing_board.alpha_composite(img, (0,-20))
            if right_icon: drawing_board.alpha_composite(img, (630,-10))
    else:
        if left_icon: painter.text((0,55), f'{text}', font=font_bd.font_variant(size=80), fill='white',anchor='lt')
        if right_icon: painter.text((760,55), f'{text}', font=font_bd.font_variant(size=80), fill='white',anchor='rt')

    if number2 != 0:
        progress = number1 / number2
        painter.text((1000,55), f'{number1}/{number2}', font=font_bd.font_variant(size=80), fill='gold' if number1 == number2 else 'white',anchor='rt')
        if progbar:
            painter.line([(0,210),(round(1000 * progress),210)],fill='grey',width=15)
            painter.line([(1000,202),(1000,217)],fill='grey',width=5)
    else:painter.text((1000,55), f'{number1}', font=font_bd.font_variant(size=80), fill='white',anchor='rt')
    
    return drawing_board

def star_song_simple(songdf:data_analyzer.pd.DataFrame, strip_downer:bool = True) -> Image.Image:
    drawing_board = Image.new('RGBA',(1250,280))
  
    if songdf.empty: 
        drawing_board.alpha_composite(dummy_song(),(1050,40))
        drawing_board.alpha_composite(star_strip(level_from=-1, level_to=-1, is_sc=False, size=1), (10,150) if strip_downer else (0, 105))
    else:
        song = data_converter.dataframe_to_song(songdf)
        drawing_board.alpha_composite(star_strip(level_from=-1, level_to=song.level, is_sc=song.is_sc, size=1), (10,150) if strip_downer else (0, 105))
        drawing_board.alpha_composite(single_song(True, song),(1050,20))
    return drawing_board

def progbar_deluxe(bar_width:int, bar_height:int, perfect:int, max_combo:int, clear:int, total:int, size:float, frame:bool=False):
    # clear include max_combo(max_combo also include perfect)
    drawing_board = Image.new('RGBA',(2200,50))
    painter = ImageDraw.Draw(drawing_board)
    #painter.rectangle([(0,0),(1000,20)],fill='white',width=5)

    perfect_width= - (- bar_width * perfect // total)
    mc_width = round(bar_width * (max_combo - perfect) / total)
    clear_width = round(bar_width * (clear - max_combo) / total)
    # Bar frame
    painter.rectangle([(0,8), (bar_width, bar_height + 8)], fill=(0, 0, 0, 100))
    painter.line([(round(bar_width/4),8),(round(bar_width/4),bar_height + 8)],fill=(20,20,20,100),width=1)
    painter.line([(round(bar_width/2),8),(round(bar_width/2),bar_height + 8)],fill=(20,20,20,100),width=1)
    painter.line([(round(bar_width*3/4),8),(round(bar_width*3/4),bar_height + 8)],fill=(20,20,20,100),width=1)
    # Progress destination
    if not frame: painter.line([(bar_width - 1,8),(bar_width - 1,bar_height + 8)],fill='white',width=1)
    # Progress
    painter.rectangle([(0,8), (perfect_width, bar_height +8)], fill='pink', width=bar_height)
    if mc_width != 0: painter.rectangle([(perfect_width,8), (perfect_width + mc_width, bar_height + 8)], fill='aquamarine', width=bar_height)
    if clear_width != 0:painter.rectangle([(perfect_width + mc_width,8), (perfect_width + mc_width + clear_width, bar_height + 8)], fill='snow', width=bar_height)

    # Bar outline
    if frame:painter.rectangle([(-1,8),(bar_width + 1,bar_height + 9)], outline='grey',width=1)

    #Resize
    drawing_board=resize_image(drawing_board, size)
    return drawing_board



def _sort_series(series: data_analyzer.pd.Series) -> data_analyzer.pd.Series:
  sort_by=['difficultyspikes', 'read', 'main6b', 'speedvariation',
           'complex', 'doublestairs', 'side', 'longjob', 'stair6', 
           'chord', 'trill', 'stair', 'stream', 'longjack', 'jack']
  # Add index objects only
  remaining = [x for x in sort_by if x in series.index]
  return series.reindex(remaining)


def plot_tags_score_radar(data:data_analyzer.pd.Series,
                          bmode,
                          figsize: tuple = (8, 8),
                          **filter_kwargs):
    
    # Fill NaN to 0
    series = data.fillna(0)

    # Sort series
    series = _sort_series(series)
    raw_labels = series.index.tolist()
    label_map={
            'jack': 'Jack',
            'longjack': 'Longjack',
            'stream': 'FX' if bmode == 8 else 'Stream',
            'stair': 'Stair',
            'trill': 'Trill',
            'chord': 'Chord',
            'longjob': 'Long',
            'side': 'Side',
            'complex': 'Complex',
            'speedvariation': 'SV',
            'doublestairs': 'Double\nStairs',
            'stair6':'6B Stair',
            'main6b': '6B Basic',
            'read': 'Read',
            'difficultyspikes': 'Spike'
        }
    
    # Turn series to lables
    labels = []
    for name in raw_labels:
      labels.append(label_map.get(name, name))
    values = series.tolist()

    # Round radar
    angles = np.linspace(0, 2 * np.pi, len(labels), endpoint=False).tolist()
    values_closed = values + [values[0]]
    angles_closed = angles + [angles[0]]

    # Max value of radar
    r_max = 3

    # Fonts
    matplotlib.rcParams['font.sans-serif'] = ['Sarasa Mono HC SemiBold']
    matplotlib.rcParams['axes.unicode_minus'] = False

    # Draw radar
    fig, ax = plt.subplots(figsize=figsize, subplot_kw=dict(polar=True))
    ax.plot(angles_closed, values_closed, 'o-', linewidth=2)
    ax.fill(angles_closed, values_closed, alpha=0.25)

    # Ticks
    ax.set_xticks(angles)
    ax.set_xticklabels(labels, fontsize=15, color='white',rotation = 0)
    ax.tick_params(pad=10)

    ax.set_ylim(-0.1, r_max)
    ax.set_yticks([1,2,3])
    ax.set_yticklabels(['1','2','3'], fontsize=1, color='white')

    #Combine labels with values
    labels = [f"{name}\n{val:.2f}" for name, val in zip(labels, series.values)]
    ax.set_xticklabels(labels, fontsize=30, color='white')
    
    # Radar style: the same white dashes, but the value rings are straight — drawn by hand as a
    # polygon through the axes at every level, in place of matplotlib's circular r-grid (the
    # radial spokes are matplotlib's theta grid, which stays on).
    ax.grid(True, color='white', linestyle=(0, (10,10)), linewidth=0.8)
    ax.yaxis.grid(False)
    for level in range(1, r_max + 1):
        ax.plot(angles_closed, [level] * len(angles_closed),
                linestyle=(0, (10, 10)), color='white', linewidth=0.8, zorder=0.5)
    ax.spines['polar'].set_visible(False)
    plt.tight_layout()

    # Export to PIL Image
    buf = io.BytesIO()
    fig.savefig(buf, format='png', bbox_inches='tight', dpi=150,transparent=True)
    plt.close(fig)
    buf.seek(0)

    pil_img = Image.open(buf).copy()
    pil_img = pil_img.resize((1000,1000),Image.Resampling.LANCZOS)
    return pil_img