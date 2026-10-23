"""The read side of the record store: load records_db and convert it for the generators.

data_fetcher downloads the raw records and persists their merge with the song database as
records/records_db.parquet — with the hand-maintained tags csv already joined and tags_score
already computed there, at build time. This module reads that parquet, decodes the two tag
columns (stored as JSON text, see data_fetcher) and converts the result into the models the
renderers consume: list[Song] for the summary charts, and VAResponse → DMBests / DMScorelist for
the bests and scorelist charts (through the same models.py builders the old local_api used, so
outputs are unchanged).

Every reader is pure local file work; a stale parquet is rebuilt offline from the raw layer.
Making sure the store exists, is current and holds the requested account is
data_fetcher.ensure_db_available() (the generate.*_local entry points call it). A direct read
against a missing store or one holding another account raises RecordsDbError instead of
downloading.
"""
import json
from decimal import Decimal
from typing import Any, Literal

import pandas as pd
from pydantic import BaseModel

from .. import api_handler, models
from . import data_fetcher

# Mirrors the archive query api_handler issues: sort=djpower, order=desc, limit=70/30.
BEST_BASIC_LIMIT = 70
BEST_NEW_LIMIT = 30


class RecordsDbError(RuntimeError):
    """records_db.parquet cannot serve a read.

    Either it does not exist and the raw layer (records/full_varecord.json) cannot rebuild it,
    or it holds another account. Run `python refresh.py` (username is set in refresh.py), or
    call data_fetcher.ensure_db_available(username) like the generate.*_local entry points do.
    """


class RecordsDbAccountMismatch(RecordsDbError):
    """The store holds a different account than the one asked for."""


# ---------------- Pydantic 模型 ----------------
class SongTags(BaseModel):
    jack: tuple[float, float] | None = None
    longjack: tuple[float, float] | None = None
    stream: tuple[float, float] | None = None
    stair: tuple[float, float] | None = None
    trill: tuple[float, float] | None = None
    chord: tuple[float, float] | None = None
    longjob: tuple[float, float] | None = None
    side: tuple[float, float] | None = None
    complex: tuple[float, float] | None = None
    speedvaration: tuple[float, float] | None = None
    doublestairs: tuple[float, float] | None = None
    stair6: tuple[float, float] | None = None
    main6b: tuple[float, float] | None = None
    read: tuple[float, float] | None = None
    difficultyspikes: tuple[float, float] | None = None


class Song(BaseModel):
    songid: int
    title: str
    pattern: Literal["NM", "HD", "MX", "SC"]
    level: int
    dlc_code: str
    button: int
    floor_name: Decimal | None = None
    is_new: bool
    is_sc: bool
    score: Decimal | None = None
    max_combo: bool | None = None
    djpower: Decimal | None = None
    max_djpower: Decimal
    tags: SongTags | None = None


# ======================================================================
# Loading: records_db.parquet → the full merged frame
# ======================================================================

def _tags_from_json(text: Any) -> dict:
    """One stored tag cell back as a dict; an empty one when it is not usable."""
    if not isinstance(text, str):
        return {}
    try:
        tags = json.loads(text)
    except ValueError:
        return {}
    return tags if isinstance(tags, dict) else {}


def _decode_tags(db: pd.DataFrame) -> pd.DataFrame:
    """The stored frame as the readers consume it: both tag columns back as dicts.

    data_fetcher stores them as JSON text (see its _attach_tags), so a reader decodes them here
    instead of joining the tags csv and recomputing tags_score. max_combo is an object column
    with holes (True/False for cleared rows only); a parquet round-trip turns those holes into
    None, and the old in-memory pipeline had NaN — restore NaN so both pipelines produce the
    exact same frame.
    """
    db = db.copy()
    db['max_combo'] = db['max_combo'].map(lambda v: float('nan') if pd.isna(v) else v)
    for col in ('tags', 'tags_score'):
        db[col] = db[col].map(_tags_from_json)
    return db


def load_records_db() -> pd.DataFrame:
    """The stored records_db as the full merged frame (tags and tags_score included).

    Purely local. A missing, stale or older-schema parquet is rebuilt offline from the raw layer
    first (data_fetcher.save_records_db: full_varecord.json + songs.json + the tags csv, no
    requests). Raises RecordsDbError when not even the raw layer exists yet — run
    `python refresh.py`.
    """
    if data_fetcher.db_is_stale():
        try:
            data_fetcher.save_records_db()
        except FileNotFoundError as error:
            raise RecordsDbError(str(error)) from error
    return _decode_tags(pd.read_parquet(data_fetcher.records_db_path()))


def records_db_from_varecord(varecord: dict) -> pd.DataFrame:
    """The full merged frame straight from freshly downloaded {bmode: raw response text}.

    The path the inspector scripts inject through AnalyzeUtil.use_varecords(): the on-disk store
    is neither read nor written, and there is no staleness or account machinery — the caller
    just downloaded these records. The frame is built exactly as the parquet is built (tags
    joined and scored) and decoded like a stored one. The mapping may be partial (a single
    fetched button mode); the frame then covers exactly the modes it holds.
    """
    return _decode_tags(data_fetcher.build_records_db(varecord))


# ======================================================================
# Convert: dataframe → Songs(containing more info)
# ======================================================================

def dataframe_to_song(df: pd.DataFrame) -> Song:
    """Convert single line DataFrame to Song。"""
    if len(df) == 0:
        raise ValueError("dataframe_to_song: DataFrame 为空")
    if len(df) > 1:
        raise ValueError(
            f"dataframe_to_song: 期望 1 行，实际收到 {len(df)} 行"
        )
    row = df.iloc[0].to_dict()
    return _row_to_song(row)


def dataframe_to_song_list(df: pd.DataFrame) -> list[Song]:
    """Convert multiple lines DataFrame to List[Song]。"""
    records = df.to_dict(orient="records")
    return [_row_to_song(row) for row in records]


# Assist methods
def _row_to_song(row: dict[str, Any]) -> Song:
    data = {
        "songid": int(row["songid"]),
        "title": str(row["title"]),
        "pattern": str(row["pattern"]),
        "level": int(row["level"]),
        "dlc_code": str(row["dlc_code"]),
        "button": int(row["button"]),
        "floor_name": _to_decimal_or_none(row.get("floor_name")),
        "is_new": bool(row["is_new"]),
        "is_sc": bool(row["is_sc"]),
        "score": _to_decimal_or_none(row.get("score")),
        "max_combo": _to_bool_or_none(row.get("max_combo")),
        "djpower": _to_decimal_or_none(row.get("djpower")),
        "max_djpower": _to_decimal(row.get("max_djpower")),
        "tags": _build_song_tags(row.get("tags"), row.get("tags_score")),
    }
    return Song.model_validate(data)


def _is_na(v: Any) -> bool:
    return v is None or (isinstance(v, float) and pd.isna(v))


def _to_decimal(value: Any) -> Decimal:
    if _is_na(value):
        return Decimal(0)
    return Decimal(str(value))


def _to_decimal_or_none(value: Any) -> Decimal | None:
    if _is_na(value):
        return None
    return Decimal(str(value))


def _to_bool_or_none(value: Any) -> bool | None:
    if _is_na(value):
        return None
    return bool(value)


def _build_song_tags(tags: Any, tags_score: Any) -> SongTags | None:
    """根据 tags / tags_score 两个 dict 构建 SongTags。"""
    if not isinstance(tags, dict) or not tags:
        return None
    if not isinstance(tags_score, dict):
        tags_score = {}

    data: dict[str, tuple[float, float] | None] = {}
    for field in SongTags.model_fields:
        v1 = tags.get(field)
        v2 = tags_score.get(field)
        data[field] = (
            None if v1 is None or v2 is None
            else (float(v1), float(v2))
        )
    return SongTags(**data)


# ======================================================================
# Convert: dataframe → the models that vanilla local generators use
# ======================================================================

def _floor_from_cell(value) -> Decimal | None:
    """A floor_name cell ('None' where the song database has no floor) back to Decimal."""
    text = str(value)
    if text in ('None', 'nan', '<NA>'):
        return None
    return Decimal(text)


def records_to_va_response(username: str, bmode: int) -> "models.VAResponse":
    """One button mode's records as a VAResponse, rebuilt from the stored records_db.

    Only the cleared rows come back — the same content one raw V-ARCHIVE response carried — so
    models.DMBests / DMScorelist can keep consuming them unchanged. Raises
    RecordsDbAccountMismatch when the store holds another account; call
    data_fetcher.ensure_db_available(username) first (the generate.*_local entry points do).
    """
    db = load_records_db()                  # may rebuild offline, which refreshes db_meta.json
    meta = data_fetcher.read_db_meta()
    stored = str(meta.get('username') or '')
    if stored.casefold() != username.casefold():
        raise RecordsDbAccountMismatch(
            f'records_db holds {stored or "no"} account, not {username!r} — run '
            f'data_fetcher.ensure_db_available({username!r}), or set username in refresh.py and '
            'run it first')

    rows = db[(db['button'] == bmode) & db['cleared']]
    records = [models.VARecord(
        title=int(row.songid),
        name=str(row.title),
        dlcCode=str(row.dlc_code),
        pattern=str(row.pattern),
        level=int(row.level),
        floorName=_floor_from_cell(row.floor_name),
        score=Decimal(str(row.score)),
        maxCombo=bool(row.max_combo),
        djpower=Decimal(str(row.djpower)),
        newTab=bool(row.is_new),
    ) for row in rows.itertuples()]
    return models.VAResponse(nickname=stored, button=bmode, records=records)


def _subset(response: "models.VAResponse", records) -> "models.VAResponse":
    """A copy of response carrying only the selected records."""
    return models.VAResponse(nickname=response.nickname, button=response.button, records=list(records))


def _top_by_djpower(records, limit: int) -> list:
    """The archive's own top-N selection: sort by djpower descending, then cut."""
    return sorted(records, key=lambda record: record.djpower, reverse=True)[:limit]


async def fetch_bests(username: str, bmode: int) -> "models.DMBests":
    response = records_to_va_response(username, bmode)
    # The archive hands back the top 70 / top 30 by djpower, and DMBests.from_va_response
    # drops score < 90 afterwards, so trim to the same limits first to match that result.
    return models.DMBests.from_va_response(
        _subset(response, _top_by_djpower([r for r in response.records if not r.newTab], BEST_BASIC_LIMIT)),
        _subset(response, _top_by_djpower([r for r in response.records if r.newTab], BEST_NEW_LIMIT)),
    )


async def fetch_scorelist(username: str, bmode: int, is_sc: bool, level: int) -> "models.DMScorelist":
    response = records_to_va_response(username, bmode)
    # Same filter as api_handler's query: pattern=SC (or NM,HD,MX) with levelMin=levelMax=level.
    records = [r for r in response.records
               if r.level == level and ((r.pattern == 'SC') if is_sc else (r.pattern != 'SC'))]
    song_db = await api_handler.fetch_song_db()
    return models.DMScorelist.from_va_response_level(is_sc, level, song_db, _subset(response, records))


async def fetch_scorelist_new(username: str, bmode: int, diff: str) -> "models.DMScorelist":
    response = records_to_va_response(username, bmode)
    # api_handler's query: pattern=<diff>, newTab=true.
    records = [r for r in response.records if r.newTab and r.pattern == diff]
    song_db = await api_handler.fetch_song_db()
    return models.DMScorelist.from_va_response_new(diff, song_db, _subset(response, records))


async def fetch_scorelist_pack(username: str, bmode: int, diff: str, pack: str) -> "models.DMScorelist":
    response = records_to_va_response(username, bmode)
    # api_handler's query: pattern=<diff>, dlc=<pack>.
    records = [r for r in response.records if r.dlcCode == pack and r.pattern == diff]
    song_db = await api_handler.fetch_song_db()
    return models.DMScorelist.from_va_response_pack(diff, pack, song_db, _subset(response, records))


async def fetch_scorelist_pp(username: str, bmode: int) -> "models.DMScorelist":
    response = records_to_va_response(username, bmode)
    # from_va_response_pp keeps the score == 100 records itself; the whole list is correct here.
    return models.DMScorelist.from_va_response_pp(response)


