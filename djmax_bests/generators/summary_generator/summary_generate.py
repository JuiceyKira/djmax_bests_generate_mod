import os
import time

from PIL import Image, ImageDraw, ImageFont
from ... import api_handler
from ...analyzer import data_analyzer
from . import components

ASSETS_PATH = os.path.join(os.path.dirname(__file__), 'assets')
FONT_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)),'fonts')
COVER_PATH = api_handler.COVER_PATH

font_bd = ImageFont.truetype(os.path.join(FONT_PATH, "Respect_bd.ttf"), 100)
font_rg = ImageFont.truetype(os.path.join(FONT_PATH, "Respect_rg.ttf"), 100)
font_lt = ImageFont.truetype(os.path.join(FONT_PATH, "Respect_lt.ttf"), 100)

TAG_NAME = ['Jack', 'Longjack', 'Chord', 'Long', 'Stream', 'Trill', 'Stair']


def draw_cover(username:str, **kwargs):
    analyze_util = data_analyzer.AnalyzeUtil()
    analyzer_full = analyze_util.spawn_analyzer_full()
    analyzer4 = analyze_util.spawn_analyzer(4)
    analyzer5 = analyze_util.spawn_analyzer(5)
    analyzer6 = analyze_util.spawn_analyzer(6)
    analyzer8 = analyze_util.spawn_analyzer(8)
    
    background = Image.new('RGBA',(2200,3000))
    painter = ImageDraw.Draw(background)


    
    with Image.open(os.path.join(ASSETS_PATH,'loop.png'), 'r') as asset_background:
        background.paste(asset_background,(0,0))
        background.paste(asset_background,(0,1000))
        background.paste(asset_background,(0,2000))

    background.alpha_composite(components.decorate_bar())
    with Image.open(os.path.join(ASSETS_PATH, 'logo.png')) as img:
        background.alpha_composite(img, (1200, 0))
    painter.text((2100,145), 'SUMMARY', font=font_lt.font_variant(size=140),anchor='rt')

    background.alpha_composite(components.draw_userinfo(analyzer_full, username, size=1, **kwargs), (0, 0))
    background.alpha_composite(components.draw_overall(analyzer_full, 1), (0,250))
    background.alpha_composite(components.draw_skill(analyzer4, analyzer5, analyzer6, analyzer8, 1), (0,600))

    with Image.open(os.path.join(ASSETS_PATH, 'dj_class.png')) as img:
        background.alpha_composite(img, (100, 1000))
    background.alpha_composite(components.draw_djpower_cover(analyzer4,1), (0, 1060))
    background.alpha_composite(components.draw_djpower_cover(analyzer5,1), (0, 1520))
    background.alpha_composite(components.draw_djpower_cover(analyzer6,1), (0, 2020))
    background.alpha_composite(components.draw_djpower_cover(analyzer8,1), (0, 2500))
    painter.text((2180, 20), f'{time.strftime("%Y.%m.%d %H:%M", time.localtime())}', font=font_rg.font_variant(size=40), fill='dimgrey', anchor='rt')
       
    return background

def draw_modecard(bmode:int) ->Image.Image:
    analyze_util = data_analyzer.AnalyzeUtil()
    analyzer = analyze_util.spawn_analyzer(bmode)
    
    background = Image.new('RGBA',(2200,3750))
    with Image.open(os.path.join(ASSETS_PATH,'loop.png'), 'r') as asset_background:
        background.paste(asset_background,(0,0))
        background.paste(asset_background,(0,1000))
        background.paste(asset_background,(0,2000))
        background.paste(asset_background,(0,3000))

    # Button mode
    background.alpha_composite(components.draw_button(bmode,1), (0, 0))
    # DJ tier description
    background.alpha_composite(components.draw_djtier(analyzer, 0.8)[0], (400, 200))
    # DJ tier emblem
    background.alpha_composite(components.draw_djtier(analyzer, 0.9)[1], (40, 180))
    # DJ POWER
    background.alpha_composite(components.draw_djpower(analyzer, 1), (400, 300))
    # Average rate
    background.alpha_composite(components.draw_avg_score(analyzer, 1), (1300,189))
    # DJ POWER new
    background.alpha_composite(components.draw_nbpower(analyzer, 'new', 1), (1130, 600))
    # DJ POWER basic
    background.alpha_composite(components.draw_nbpower(analyzer, 'basic', 1), (180, 600))
    # DJ POWER progress
    background.alpha_composite(components.draw_powerbar(analyzer, 1500, 1), (350, 550))

    if not analyzer.djpower == 0:
        # Best song in new
        background.alpha_composite(components.draw_best(analyzer,1), (100,825))
        # Difficulties status
        background.alpha_composite(components.draw_diff_stats(analyzer,0.75), (50,1050))
        # Tags score radar chart
        background.alpha_composite(components.draw_radar(analyzer,bmode,0.9), (1205,1120))
        # Highest status
        background.alpha_composite(components.draw_highest(analyzer,0.8), (1160,2030))
        # Levels status
        background.alpha_composite(components.draw_level_stats(analyzer,0.8), (70,2030))
        
        return background
    else: 
        simple_bg = Image.new('RGBA',(2200,850))
        simple_bg.paste(background)
        return simple_bg

def generate_summary(username:str, nickname = None, photo = None, prefer_button = [4, 5, 6, 8], info=''):
    if nickname != None and type(nickname) == str:username = nickname
    print('Creating background')
    canvas = Image.new('RGBA',(2200, 18000))
    height = 0

    cover = draw_cover(username, photo=photo, prefer=prefer_button, info=info)
    canvas.paste(cover,(0,height))
    height += cover.size[1]
    modecard_pack={}

    for button in [4,5,6,8]:
        print(f'Generating {button}B summary')
        modecard = draw_modecard(button)
        canvas.paste(modecard,(0,height))
        height += modecard.size[1]

        # Button individual card
        painter = ImageDraw.Draw(modecard)
        painter.text((2100,75), username, fill='white', font=font_rg.font_variant(size=90),anchor='rt')
        modecard_pack[button] = modecard

    print(f'Assembling background')
    output = Image.new('RGBA',(2200, height))
    output.paste(canvas)
    print('Done')
    return output, modecard_pack