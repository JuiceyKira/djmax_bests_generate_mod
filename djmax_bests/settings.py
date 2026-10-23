"""User settings read from settings.ini beside the executable (project root in a checkout).

The file is created with documented defaults on first run, because the summary knobs
(nickname / photo / preferred buttons / signature) and the target-plan knobs (floor cap /
balance rounds) used to be module constants that every user had to edit in code.

It is re-read on every access, so saving the file is enough — the next generated chart picks the
new values up without restarting the app.
"""
import configparser
import os

from . import paths

DEFAULT_TEXT = """; DJMAX 成绩图生成器设置
; 改完保存即可，下一次生成时生效，不需要重启程序。
; 以 ; 或 # 开头的是注释；等号右边留空表示“用程序默认值”。

[summary]
; 显示名称；留空 = 直接显示账号名
nickname =
; 头像使用的曲绘 songid；留空 = 每次随机
photo_id = 456
; 高亮的按键模式（4,5,6,8 的子集，逗号分隔）
prefer_button = 6,8
; 签名栏文字；留空 = 不写签名
info = steam 179448484

[target]
; 难度上限（floor 单位，例如 6.0）；留空 = 不限制
floor_cap =
; basic/new 配额平衡的尝试轮数
balance_rounds = 8

[refresh]
; 曲库 / DLC 列表 / 换算系数超过多少天就重新下载（0 = 每次都更新）
max_age_days = 7
"""

_VALID_BUTTONS = (4, 5, 6, 8)


def ensure_exists() -> str:
    """Create settings.ini with defaults when it is missing; return its path."""
    if not os.path.exists(paths.CONFIG_FILE):
        try:
            with open(paths.CONFIG_FILE, "w", encoding="utf-8") as handle:
                handle.write(DEFAULT_TEXT)
        except OSError:
            pass        # a read-only folder must not stop the app; defaults still apply
    return paths.CONFIG_FILE


def _load() -> configparser.ConfigParser:
    parser = configparser.ConfigParser()
    try:
        parser.read(paths.CONFIG_FILE, encoding="utf-8")
    except (configparser.Error, OSError):
        parser = configparser.ConfigParser()
    return parser


def _get(parser: configparser.ConfigParser, section: str, key: str, fallback: str = "") -> str:
    try:
        return parser.get(section, key, fallback=fallback).strip()
    except (configparser.Error, ValueError):
        return fallback


def summary_options() -> dict:
    """nickname / photo_id / prefer_button / info for the summary chart."""
    parser = _load()

    nickname = _get(parser, "summary", "nickname") or None

    photo_text = _get(parser, "summary", "photo_id")
    photo_id = int(photo_text) if photo_text.isdigit() else None

    prefer: list[int] = []
    for part in _get(parser, "summary", "prefer_button", "4,5,6,8").replace(" ", "").split(","):
        if part.isdigit() and int(part) in _VALID_BUTTONS and int(part) not in prefer:
            prefer.append(int(part))
    if not prefer:
        prefer = list(_VALID_BUTTONS)

    info = _get(parser, "summary", "info")

    return {"nickname": nickname, "photo_id": photo_id,
            "prefer_button": prefer, "info": info}


def target_options() -> dict:
    """floor_cap / balance_rounds for the target-DJPower plan."""
    parser = _load()

    cap_text = _get(parser, "target", "floor_cap").lower()
    floor_cap = None
    if cap_text and cap_text not in ("none", "null", "-"):
        try:
            floor_cap = float(cap_text)
        except ValueError:
            floor_cap = None

    rounds_text = _get(parser, "target", "balance_rounds", "8")
    balance_rounds = int(rounds_text) if rounds_text.isdigit() else 8

    return {"floor_cap": floor_cap, "balance_rounds": balance_rounds}


def refresh_options() -> dict:
    """max_age_days for the cache re-download policy (song db / dlc list / maxpower)."""
    parser = _load()
    text = _get(parser, "refresh", "max_age_days", "7")
    try:
        max_age_days = float(text)
    except ValueError:
        max_age_days = 7.0
    if max_age_days < 0:
        max_age_days = 7.0
    return {"max_age_days": max_age_days}
