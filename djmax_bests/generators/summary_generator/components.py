import os, random
from typing import Literal
from decimal import Decimal

from PIL import Image, ImageDraw, ImageFont, ImageEnhance
from ... import api_handler, util
from ... import constants as c
from ...analyzer import data_analyzer, data_converter
from . import tools

ASSETS_PATH = os.path.join(os.path.dirname(__file__), 'assets')
FONT_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)),'fonts')
COVER_PATH = api_handler.COVER_PATH
EMBLEM_PATH = os.path.join(os.path.dirname(__file__), 'assets\\emblems')

font_bd = ImageFont.truetype(os.path.join(FONT_PATH, "Respect_bd.ttf"), 100)
font_rg = ImageFont.truetype(os.path.join(FONT_PATH, "Respect_rg.ttf"), 100)
font_lt = ImageFont.truetype(os.path.join(FONT_PATH, "Respect_lt.ttf"), 100)

TAG_NAME = ['Jack', 'Longjack', 'Chord', 'Long', 'Stream', 'Trill', 'Stair']
#utilities




def draw_userinfo(analyzer:data_analyzer.RecordAnalyzer, username:str, photo=None, prefer:list=[4,5,6,8], info:str='', size:float = 1):
    drawing_board = Image.new('RGBA',(1000,2000))
    painter = ImageDraw.Draw(drawing_board)
    #painter.rectangle([(0,0),(1000,320)],None,'white',width=5)

    # Photo
    painter.rounded_rectangle([(35,35),(305,305)], 30, fill='white', width=5)

    songid_max = analyzer.data['songid'].max()
    if photo == None or type(photo) != int or photo not in range(0, songid_max + 1): photo = random.randint(0, songid_max)
    # Easter egg; a configured photo_id without a cached jacket falls back to the placeholder
    photo_path = os.path.join(COVER_PATH, f'{photo}.jpg')
    if photo != random.randint(0, songid_max) and os.path.exists(photo_path):
        with Image.open(photo_path) as photo_img:
            img = tools.resize_image(photo_img, 2)
            drawing_board.paste(img,(50,50))
    else:
        with Image.open(os.path.join(ASSETS_PATH, 'profile.jpg')) as photo_img:
            drawing_board.paste(photo_img,(50,50))

    # Username
    if len(username)<= 8:
        painter.text((352,47), username, fill='grey', font=font_rg,anchor='lt')
        painter.text((350,45), username, fill='white', font=font_rg,anchor='lt')
    else:         
        painter.text((352,77), username, fill='grey', font=font_rg.font_variant(size=60), anchor='lt')
        painter.text((350,75), username, fill='white', font=font_rg.font_variant(size=60), anchor='lt')

    # Prefer button
    x = 350
    for button in [4,5,6,8]:
        with Image.open(os.path.join(ASSETS_PATH, f'{button}B.png')) as img:
            if button in prefer:drawing_board.alpha_composite(img,(x,155))
            else:
                monochrome = ImageEnhance.Color(img)
                monochromed_img = monochrome.enhance(0)
                drawing_board.alpha_composite(monochromed_img,(x,155))
        x += 150

    # Info
    with Image.open(os.path.join(ASSETS_PATH, 'signature.png')) as img:
        drawing_board.alpha_composite(img,(350,270))
        painter.text((420,285), info, fill='white', font=font_rg.font_variant(size=50),anchor='lm')

    drawing_board=tools.resize_image(drawing_board, size)
    return drawing_board

def draw_overall(analyzer_full:data_analyzer.RecordAnalyzer, size:float):
    drawing_board = Image.new('RGBA',(2200,600))
    painter = ImageDraw.Draw(drawing_board)
    #painter.rectangle([(0,0),(2200,600)],None,'white',width=5)

    with Image.open(os.path.join(ASSETS_PATH, 'clear.png')) as img:
        drawing_board.alpha_composite(img,(100,120))

    painter.text((2100,135), f'{analyzer_full.count_cleared}/{analyzer_full.count_total}', font=font_rg.font_variant(size=70), fill='gold' if analyzer_full.count_cleared == analyzer_full.count_total else 'white',anchor='rt')

    cleared = analyzer_full.count_cleared
    total = analyzer_full.count_total
    max_combo = analyzer_full.count_max_combo
    perfect = analyzer_full.count_perfect_play
    avg_score = analyzer_full.avg_score


    drawing_board.alpha_composite(tools.progbar_deluxe(2000,22,perfect,max_combo,cleared,total,1,True),(100,192))
    painter.text((580, 290), "AVG. RATE", font=font_bd.font_variant(size=70), fill='grey', anchor="lt")
    if avg_score == avg_score: 
        painter.text((554, 243), f'{avg_score:.2f}%', font=font_rg.font_variant(size=140), fill='grey', anchor="rt")
        painter.text((550, 239), f'{avg_score:.2f}%', font=font_rg.font_variant(size=140), fill='white', anchor="rt")
    else: painter.text((550, 239), f'--.--%', font=font_rg.font_variant(size=140), fill='white', anchor="rt")

        # MC/PP status
    with Image.open(os.path.join(ASSETS_PATH,f'max_combo.png')) as img:
        img = tools.resize_image(img,0.8)
        drawing_board.alpha_composite(img,(1450,245))
    painter.text((1760,315), f'{analyzer_full.count_max_combo}', fill='white', font=font_bd.font_variant(size=60), anchor='rm')

    with Image.open(os.path.join(ASSETS_PATH,f'perfect.png')) as img:
        img = tools.resize_image(img,0.8)
        drawing_board.alpha_composite(img,(1800,235))
    painter.text((2096,315), f'{analyzer_full.count_perfect_play}', fill='white', font=font_bd.font_variant(size=60), anchor='rm')

    drawing_board=tools.resize_image(drawing_board, size)
    return drawing_board

def draw_skill(analyzer4:data_analyzer.RecordAnalyzer,analyzer5:data_analyzer.RecordAnalyzer,
               analyzer6:data_analyzer.RecordAnalyzer,analyzer8:data_analyzer.RecordAnalyzer, size:float):
    drawing_board = Image.new('RGBA',(2200,360))

    df = data_analyzer.pd.concat([analyzer4.tags_skill, analyzer5.tags_skill,
                                  analyzer6.tags_skill, analyzer8.tags_skill], axis=1)
    skill_org = df.max(axis=1).to_dict()
    skill_new = {}
    value = []
    for tag in ['jack', 'longjack', 'chord', 'longjob', 'stream', 'trill', 'stair']:
        value.append(skill_org.pop(tag))
    index = 0
    for tag in TAG_NAME:
        skill_new[tag] = round(value[index], 2)
        index += 1

    drawing_board.alpha_composite(tools.tags_score(skill_new, 100,40))
    
    drawing_board=tools.resize_image(drawing_board, size)
    return drawing_board


def draw_djpower_cover(analyzer:data_analyzer.RecordAnalyzer, size:float):
    drawing_board = Image.new('RGBA',(2200,480))
    painter = ImageDraw.Draw(drawing_board)

    drawing_board.alpha_composite(tools.button_tunes(analyzer.bmode,1))

    

    # DJ tier
    drawing_board.alpha_composite(draw_djtier(analyzer,0.6,False)[0], (300,200))
    drawing_board.alpha_composite(draw_djtier(analyzer,0.6,False)[1], (90,190))
    # DJ POWER
    drawing_board.alpha_composite(draw_djpower(analyzer,0.8,False), (300,270))
    drawing_board.alpha_composite(draw_nbpower(analyzer,'basic',0.6,False), (1000,300))
    drawing_board.alpha_composite(draw_nbpower(analyzer,'new',0.6,False), (1000,200))
    # DJ POWER bar
    drawing_board.alpha_composite(draw_powerbar(analyzer,1500,0.8), (165,410))

    # Clear status
    painter.text((1450,250), "CLEAR", fill='white', font=font_bd.font_variant(size=60), anchor='lm')
    painter.text((2100,229), f'{analyzer.count_cleared}/{analyzer.count_total}', font=font_rg.font_variant(size=70), fill='gold' if analyzer.count_cleared == analyzer.count_total else 'white',anchor='rt')

    # MC/PP status
    with Image.open(os.path.join(ASSETS_PATH,f'max_combo.png')) as img:
        img = tools.resize_image(img,0.8)
        drawing_board.alpha_composite(img,(1450,300))
    painter.text((1760,370), f'{analyzer.count_max_combo}', fill='white', font=font_bd.font_variant(size=60), anchor='rm')

    with Image.open(os.path.join(ASSETS_PATH,f'perfect.png')) as img:
        img = tools.resize_image(img,0.8)
        drawing_board.alpha_composite(img,(1800,290))
    painter.text((2096,370), f'{analyzer.count_perfect_play}', fill='white', font=font_bd.font_variant(size=60), anchor='rm')


    drawing_board=tools.resize_image(drawing_board, size)
    return drawing_board

def decorate_bar():
    drawing_board = Image.new('RGBA',(2200,480))
    painter = ImageDraw.Draw(drawing_board)
    painter.rectangle([(0,135), (2200,255)], fill=(0,0,0,100))
    return drawing_board






def draw_djpower(analyzer:data_analyzer.RecordAnalyzer, size:float, convert:bool=True) -> Image.Image:
    drawing_board = Image.new('RGBA',(850,200))
    painter = ImageDraw.Draw(drawing_board)
    #painter.rectangle([(0,0), (850,200)], None, 'white', width=5)

    djpower = analyzer.djpower
    raw_djpower = analyzer.djpower_raw
    djpower_display = str(djpower)
    djpower_display_integral, djpower_display_decimal = djpower_display.split(".")

    # Draw intergal DJ POWER
    if djpower >= 9980:
        # LORD gradient DJ POWER
        tools.text_gradient(drawing_board, (13,-32), font_rg.font_variant(size=180), djpower_display_integral, (231,174,237), (163,222,253))
        painter.text((10, 10), djpower_display_integral, font=font_rg.font_variant(size=180), fill='white', anchor="lt")
    else:
        painter.text((430, 14), djpower_display_integral, font=font_rg.font_variant(size=180), fill=tools.djtier_color(djpower), anchor="rt")
        painter.text((426, 10), djpower_display_integral, font=font_rg.font_variant(size=180), fill='white', anchor="rt")
    # Draw decimal DJ POWER
    if djpower != 10000 and djpower != 0:
        painter.text((780, 40), "." + djpower_display_decimal,
            font=font_rg.font_variant(size=140), fill='grey', anchor="rt")

    #Draw DJ POWER before convert
    if convert:
        convert_constant = (analyzer.djpower_convert_constant - 1) * 100
        if djpower != 0: 
            painter.text((40, 150), f'CONVERT  ⇌  {raw_djpower:.2f}', font=font_rg.font_variant(size=50), fill='white', anchor="lt")
        painter.text((780, 154), f'+ {convert_constant:.2f}%', font=font_rg.font_variant(size=50), fill='grey', anchor="rt")
    #Resize
    drawing_board=tools.resize_image(drawing_board, size)
    return drawing_board

def draw_avg_score(analyzer:data_analyzer.RecordAnalyzer, size:float, right_pos:bool = False) -> Image.Image:
    drawing_board = Image.new('RGBA',(650,260))
    painter = ImageDraw.Draw(drawing_board)
    #painter.rectangle([(0,0), (650,250)], None, 'white', width=5)

    avg_score = analyzer.avg_score
    painter.text((500, 100) if right_pos else (14, 14), "AVERAGE RATE", font=font_bd.font_variant(size=80), fill='grey', anchor="lt")
    if avg_score == avg_score: 
        painter.text((654, 123), f'{avg_score:.2f}%', font=font_rg.font_variant(size=180), fill='grey', anchor="rt")
        painter.text((650, 119), f'{avg_score:.2f}%', font=font_rg.font_variant(size=180), fill='white', anchor="rt")
    else: painter.text((650, 119), f'--.--%', font=font_rg.font_variant(size=180), fill='white', anchor="rt")

    
    #Resize
    drawing_board=tools.resize_image(drawing_board, size)
    return drawing_board


def draw_djtier(analyzer:data_analyzer.RecordAnalyzer, size:float, donuts:bool=True) -> tuple[Image.Image, Image.Image]:
    drawing_board_tier = Image.new('RGBA',(1200,120))
    drawing_board_emblem = Image.new('RGBA',(380,380))
    painter = ImageDraw.Draw(drawing_board_tier)

    djpower = analyzer.djpower
    djpower_tier, djpower_step = util.get_djpower_tier(djpower)
    djpower_title = util.format_djpower_tier(djpower_tier, djpower_step)


    #painter.rectangle([(0,0),(1200,120)],None,'white',width=5)

    # LORD exclusive gradient DJ CLASS description
    if djpower_title == "THE LORD OF DJMAX":
        tools.text_gradient(drawing_board_tier, (13, -8), font_bd, djpower_title, (231, 174, 237), (163, 222, 253))
    else:
        painter.text((14, 14), djpower_title, font=font_bd, fill=tools.djtier_color(djpower), anchor="lt")

    if djpower != 0 and donuts: drawing_board_emblem.alpha_composite(tools.donuts(round(djpower),775,0.2),(10,10))
    with Image.open(os.path.join(EMBLEM_PATH, f"{djpower_tier}_{djpower_step}.png")) as emblem:
        
        img_enhance = ImageEnhance.Brightness(emblem)
        black = img_enhance.enhance(0)
        drawing_board_emblem.alpha_composite(black,(2,2))
        drawing_board_emblem.alpha_composite(emblem)

    

    #Resize
    drawing_board_tier = tools.resize_image(drawing_board_tier, size)
    drawing_board_emblem = tools.resize_image(drawing_board_emblem, size)
    return drawing_board_tier, drawing_board_emblem



def draw_button(bmode:int, size:float) -> Image.Image:
    drawing_board = Image.new('RGBA',(960,200))
    painter = ImageDraw.Draw(drawing_board)
    #painter.rectangle([(0,0),(960,200)],None,'white',width=5)

    painter.polygon([(10,75), (10,170), (920,170), (820,75)], fill=c.BMODE_COLOR[bmode])
    painter.text((50, 10), f'{bmode}', font=font_bd.font_variant(size=200), fill='white', anchor="lt")
    painter.text((190, 90), "BUTTON", font=font_bd.font_variant(size=80), fill=(255,255,255,220), anchor="lt")
    painter.text((540, 92), "TUNES", font=font_lt.font_variant(size=80), fill=(255,255,255,220), anchor="lt")

    #Resize
    drawing_board=tools.resize_image(drawing_board, size)
    return drawing_board

def draw_nbpower(analyzer:data_analyzer.RecordAnalyzer, basic:Literal['basic', 'new'], size:float, detail:bool = True) -> Image.Image:
    drawing_board = Image.new('RGBA',(960,200))
    painter = ImageDraw.Draw(drawing_board)
    #painter.rectangle([(0,0),(960,200)],None,'white',width=5)

    if basic == 'basic':
        cleared = analyzer.count_total_basic
        djpower=analyzer.djpower_basic
        djpower_theo=analyzer.djpower_theo_basic
        perfectgap = analyzer.djpower_perfect_basic - analyzer.djpower_basic
        
    else:
        cleared = analyzer.count_total_new
        djpower=analyzer.djpower_new
        djpower_theo=analyzer.djpower_theo_new
        perfectgap = analyzer.djpower_perfect_new - analyzer.djpower_new


    with Image.open(os.path.join(ASSETS_PATH, f'djpow_{basic}.png'), 'r') as nbicon:
        nbicon=tools.resize_image(nbicon,2)
        drawing_board.alpha_composite(nbicon,(10,30))

    
    painter.text((603, 18) if detail else (603,48), f'{djpower:.2f}' if djpower != 0 else '0', font=font_rg.font_variant(size=120), fill='gray', anchor="rt") 
    painter.text((600, 15) if detail else (603,45), f'{djpower:.2f}' if djpower != 0 else '0', font=font_rg.font_variant(size=120), fill='white', anchor="rt")

    if djpower != 0: 
        if detail: painter.text((620, 40), f'(+{perfectgap:.2f})', font=font_rg.font_variant(size=70), fill='gray', anchor="lt")
        painter.text((28, 40), str(cleared), font=font_bd.font_variant(size=50), fill='white', anchor="mm")
    #Draw theoretical DJ POWER of new or basic
    if detail: painter.text((330, 120), f'/{djpower_theo:.2f}     {(djpower * 10000 // djpower_theo / 100):.2f}%', 
                            font=font_rg.font_variant(size=60), fill='gray', anchor="lt")

    #Resize
    drawing_board=tools.resize_image(drawing_board, size)
    return drawing_board

def draw_powerbar(analyzer:data_analyzer.RecordAnalyzer, width, size:float) -> Image.Image:
    # Values
    djpower_theo_basic = analyzer.djpower_theo_basic
    progress_basic = analyzer.djpower_basic / djpower_theo_basic
    progress_new = analyzer.djpower_new / analyzer.djpower_theo_new

    bar_width, bar_height, bar_thick= width, 20, 5
    bar_middle_y = round(bar_height / 2)
    
    # Ratios for drawing
    nb_ratio = djpower_theo_basic / 10000
    partition_x = round(bar_width * nb_ratio)
    basic_bar_length = round(partition_x * progress_basic)
    new_bar_length = round((bar_width - partition_x) * progress_new)
    basic_gap_length = round((analyzer.djpower_perfect_basic - analyzer.djpower_basic) * bar_width / 10000)
    new_gap_length = round((analyzer.djpower_perfect_new - analyzer.djpower_new) * bar_width / 10000)

    # Initial background and painter
    drawing_board = Image.new('RGBA',(bar_width + bar_thick,bar_height + bar_thick))
    painter = ImageDraw.Draw(drawing_board)
    
    # Progress bar background
    painter.rectangle([(0,0), (bar_width,bar_height)],fill=(0,0,0,100) , width=bar_thick)

    # Basic and new progress
    painter.rectangle([(0,0),(basic_bar_length, bar_height)], fill='#E5AFF1' if progress_basic == 1 else 'silver')
    painter.line([(basic_bar_length, bar_middle_y), (basic_bar_length + basic_gap_length,  bar_middle_y)], 
                 fill=(120,120,120,100), width =bar_height)
    
    painter.rectangle([(bar_width - new_bar_length, 0), (bar_width,bar_height)], fill='#A6DDFC' if progress_new == 1 else 'gold')
    painter.line([(bar_width - new_bar_length -new_gap_length, bar_middle_y), (bar_width - new_bar_length,  bar_middle_y)], 
                 fill=(248,218,57,100), width =bar_height)

    # Progress bar main structure, partition by ratio between basic and new
    #painter.rectangle([(0,0), (bar_width,bar_height)], width=bar_thick)
    painter.line([(partition_x,0), (partition_x, bar_height)], fill='white', width=bar_thick)
    
    #Resize
    drawing_board=tools.resize_image(drawing_board, size)
    return drawing_board

def draw_best(analyzer:data_analyzer.RecordAnalyzer, size:float) -> Image.Image:
    drawing_board = Image.new('RGBA',(2000,250))
    painter = ImageDraw.Draw(drawing_board)
    #painter.rectangle([(0,0),(960,200)],None,'white',width=5)
    
    best_rating = data_converter.dataframe_to_song_list(analyzer.topn_attribute('rating', 10))
    drawing_board.alpha_composite(tools.multi_songs(True, best_rating), (200,0))

    painter.text((5,30), "TOP", font = font_bd.font_variant(size=80), fill='white')
    painter.text((40,120), "10", font = font_bd.font_variant(size=80), fill='white')
    #Resize
    drawing_board=tools.resize_image(drawing_board, size)
    return drawing_board  

def draw_highest(analyzer:data_analyzer.RecordAnalyzer, size:float) -> Image.Image:
    drawing_board = Image.new('RGBA',(1250,2100))
    painter = ImageDraw.Draw(drawing_board)
    #painter.rectangle([(0,0),(1250,2100)],None,'white',width=5)
    with Image.open(os.path.join(ASSETS_PATH,f'highest.png')) as img:
        drawing_board.alpha_composite(img, (0,40))

    clear = analyzer.count_cleared
    max_combo = analyzer.count_max_combo
    perfect = analyzer.count_perfect_play
    over_99_9 = len(analyzer.filter(cleared=True, score_min=99.90, score_max=99.99))
    over_99 = len(analyzer.filter(cleared=True, score_min=99.00, score_max=99.89))
    over_97 = len(analyzer.filter(cleared=True, score_min=97.00, score_max=98.99))
    total = analyzer.count_total

    v_gap = 325
    drawing_board.alpha_composite(tools.star_song(analyzer.highest_cleared, 'text', clear, total ,left_icon=True, text='CLEAR'),(0, 125))
    drawing_board.alpha_composite(tools.star_song(analyzer.highest_perfect_play, 'perfect', perfect, right_icon=True),
                                  (0, 125 + v_gap))
    drawing_board.alpha_composite(tools.star_song(analyzer.highest_max_combo, 'max_combo', max_combo, right_icon=True),
                                  (0, 125 + v_gap * 2))
    drawing_board.alpha_composite(tools.star_song(analyzer.highest_condition(cleared=True, score_min=99.90,score_max=99.99), 
                                                 'text', over_99_9, right_icon=True, text='≥99.9%'), (0, 125 + v_gap * 3))
    drawing_board.alpha_composite(tools.star_song(analyzer.highest_condition(cleared=True, score_min=99.00,score_max=99.89), 
                                                 'text', over_99, right_icon=True, text='≥99%'), (0, 125 + v_gap * 4))
    drawing_board.alpha_composite(tools.star_song(analyzer.highest_condition(cleared=True, score_min=97.00,score_max=98.99), 
                                                 'text', over_97, right_icon=True, text='≥97%'), (0, 125 + v_gap * 5))

    drawing_board.alpha_composite(tools.progbar_deluxe(1000, 15, perfect, max_combo, clear, total, 1), (0, 312))
    #Resize
    drawing_board=tools.resize_image(drawing_board, size)
    return drawing_board

def draw_level_stats(analyzer:data_analyzer.RecordAnalyzer, size:float) -> Image.Image:
    drawing_board = Image.new('RGBA',(1250,2100))
    painter = ImageDraw.Draw(drawing_board)
    #painter.rectangle([(0,0),(1250,2100)],None,'white',width=5)
    with Image.open(os.path.join(ASSETS_PATH,f'clear.png')) as img:
        drawing_board.alpha_composite(img, (0,40))

    # Loop prepare
    level_min = [11, 6, 1]
    is_sc = [True, False]
    y = 150
    v_gap = 325
    # Loop
    for sc in is_sc:
        for level in level_min:
            # Filter level
            data = analyzer.filter(cleared=True, is_sc=sc, level_min=level, level_max=level + 4)
            # Pick highest song
            highest = data.nlargest(1, 'rating')
            # Draw level text, stars and song
            painter.text((0,y + 30), f'SC{level}-{level + 4}' if sc else f'{level}-{level + 4}', 
                         font=font_bd.font_variant(size=80), fill='white', anchor='lt')
            drawing_board.alpha_composite(tools.star_song_simple(highest, False), (0,y))

            # Skip below if not played
            if data.empty:
                # painter.text((0,y + 110), f'SC{level}-{level + 4}' if sc else f'{level}-{level + 4}', 
                #              font=font_bd.font_variant(size=80), fill='white', anchor='lt')
                painter.text((500,y + 180), f'NOT PLAYED', font=font_bd.font_variant(size=80), fill='white', anchor='lt')
                y += v_gap
                continue

            #Get score etc.
            total = len(analyzer.filter(is_sc=sc, level_min=level, level_max=level + 4))
            cleared = data['score'].count()
            avg_score = data['score'].mean()
            max_combo = int(data['max_combo'].sum())
            perfect = int((data['score'] == 100).sum())

            # Average score
            painter.text((0,y + 220), "RATE", fill='white', font=font_bd.font_variant(size=50), anchor='lm')
            painter.text((150, y + 190), f'{avg_score:.2f}%', font=font_rg.font_variant(size=80), fill='white', anchor='lt')

            # Cleared
            painter.text((450,y + 220), "CLEAR", fill='white', font=font_bd.font_variant(size=50), anchor='lm')
            painter.text((1025, y + 190), f'{cleared}/{total}', font=font_rg.font_variant(size=80), fill='gold' 
                         if cleared == total else 'white', anchor='rt')

            # Max combo
            with Image.open(os.path.join(ASSETS_PATH,'MC_counter.png')) as mc_img:
                drawing_board.alpha_composite(mc_img,(400, y + 30))
            painter.text((670, y + 30), f'{max_combo}', font=font_bd.font_variant(size=80), fill='gold' 
                         if max_combo == total else 'white', anchor='rt')

            # Perfect play
            with Image.open(os.path.join(ASSETS_PATH,'PP_counter.png')) as pp_img:
                drawing_board.alpha_composite(pp_img,(720, y + 28))
            painter.text((1020, y + 30), f'{perfect}', font=font_bd.font_variant(size=80), fill='gold' 
                         if perfect == total else 'white', anchor='rt')

            # Progress bar
            drawing_board.alpha_composite(tools.progbar_deluxe(1000,5,perfect,max_combo,cleared,total,1), (0,y + 165))

            # Move to next row
            y += v_gap


    drawing_board=tools.resize_image(drawing_board, size)
    return drawing_board

def draw_diff_stats(analyzer:data_analyzer.RecordAnalyzer, size:float) -> Image.Image:
    drawing_board = Image.new('RGBA',(1300,1500))
    painter = ImageDraw.Draw(drawing_board)
    #painter.rectangle([(0,0),(1250,1200)],None,'white',width=5)
    with Image.open(os.path.join(ASSETS_PATH,f'play_data.png')) as img:
        drawing_board.alpha_composite(img, (30, 98))
    
    #Get list
    stats = []
    df = analyzer.stats_cleared(['pattern'])
    # Check completeness
    df = (df.set_index('pattern').reindex(['NM', 'HD', 'MX', 'SC'], fill_value=0).reset_index())

    for title in ['avg_score','cleared','max_combo','perfect_play']:
        series = df.loc[:, title]
        stats.append(series.to_list())
        #stats.append(analyzer.series_to_list(series))

    total = analyzer.count_pattern

    # Merge list:[[avg_score], [total], [cleared], [max_combo], [perfect_play]]
    # Order in each list is ['NM', 'HD', 'MX', 'SC]
    stats.insert(1, total)
    stats[0] = [round(value, 2) for value in stats[0]]
    
    # Loop to draw table
    x = 330
    y = 400
    h_gap = 290
    v_gap = 180
    for list in stats:
        for attr in list:
            painter.text((x,y),f'{attr}', fill='white',font=font_rg.font_variant(size=80), anchor='mm')
            x += h_gap
        y += v_gap
        x = 330
    # Draw header
    painter.text((250,200), "NM       HD       MX       SC", fill='white', font=font_bd.font_variant(size=100))
    painter.text((50,400), "RATE", fill='white', font=font_bd.font_variant(size=50), anchor='lm')
    painter.text((50,580), "TOTAL", fill='white', font=font_bd.font_variant(size=50), anchor='lm')
    painter.text((50,760), "CLEAR", fill='white', font=font_bd.font_variant(size=50), anchor='lm')
    with Image.open(os.path.join(ASSETS_PATH,'max_combo.png')) as mc_img:
        drawing_board.alpha_composite(mc_img, (50,870))
    with Image.open(os.path.join(ASSETS_PATH,'perfect.png')) as pp_img:
        drawing_board.alpha_composite(pp_img, (50,1050))

    drawing_board=tools.resize_image(drawing_board, size)
    return drawing_board

def draw_radar(analyzer:data_analyzer.RecordAnalyzer, bmode:int, size:float) -> Image.Image:
    drawing_board = Image.new('RGBA',(1000,1000))

    tags_skill = analyzer.tags_skill
    drawing_board.alpha_composite(tools.plot_tags_score_radar(tags_skill,bmode))

    drawing_board=tools.resize_image(drawing_board, size)
    return drawing_board