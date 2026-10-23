"""The write side of the record store: download, merge, persist as records_db.parquet.

Two layers live in records/ (outside the cache, so api_handler.remove_cache() cannot clear them):

    full_varecord.json    the raw layer: {bmode: raw response text}, one entry per button mode,
                          exactly as the V-ARCHIVE API returned it (fetch_one / fetch_all).
                          The source of truth for a rebuild.
    records_db.parquet    the derived layer ("records_db"): the song database merged with the
                          records, max_djpower filled in, and the hand-maintained tags csv
                          already joined and scored — so reading the store is a plain parquet
                          read. Both tag columns are stored as JSON text: a dict column does not
                          survive a parquet round-trip unchanged (pyarrow pads an empty dict out
                          to one None per key seen in any other row), and JSON text round-trips
                          exactly. data_converter decodes them. The song database's own tags ride
                          along as the plain-text `hint` column ("group-code" per tag, prefixed
                          with "standard" for the charts the song database flags so).
    db_meta.json          which account the parquet holds, when it was built and with which
                          `schema`. `username` is None when the raw layer's entries mix accounts;
                          db_is_stale() rebuilds a store written by older code.

Network entry points (everything else is local file work):
    ensure_db_available(username)      no-op when the parquet already serves `username`; offline
                                      rebuild when only songs.json or the tags csv moved under
                                      it; full four-mode download when the store is missing or
                                      foreign. The generate.*_local entry points call this once,
                                      so data_converter's readers can stay pure local reads.
    refresh_records(username)         re-downloads all four button modes and rebuilds. It is what
                                      refresh.py calls.

Reading is data_converter's job: load_records_db() for the whole store,
records_db_from_varecord() for freshly downloaded records that must not touch the disk.
"""
import asyncio
import json
import os
from datetime import datetime
from decimal import Decimal
from typing import Literal

import pandas as pd
from pydantic import BaseModel, Field

from .. import api_handler, paths, util

# Share api_handler's cache directory (djmax_bests/cache): maxpower, songs.json and dlcs.json all
# live there, so api_handler.remove_cache() clears this module's copies of those too.
CACHE_PATH = api_handler.CACHE_PATH

# The record store lives outside the cache (records/), so a cache wipe cannot take it away.
RECORDS_PATH = api_handler.RECORDS_PATH

BMODES = (4, 5, 6, 8)

RECORDS_DB_FILENAME = 'records_db.parquet'
DB_META_FILENAME = 'db_meta.json'

# Hand-maintained tag database: one row per chart, one column per feature. In an exe build it
# lives in data/ (seeded from the bundled default) so it can be replaced without rebuilding;
# in a source checkout it stays beside this module. db_is_stale() watches its mtime.
TAGS_CSV_PATH = paths.tags_csv_path()

# The parquet layout's version, recorded in db_meta.json so that db_is_stale() rebuilds a store
# written by older code. 2 = the tag columns live in the parquet (schema 1 kept them out).
# 3 = adds the hint column, the song database's tags as text (schema 2 had no hint).
DB_SCHEMA = 3

# The parquet's pinned schema — also the shape of the merged frame the readers hand out. The
# last two are the tag columns, joined from TAGS_CSV_PATH at build time and stored as JSON text.
# `hint` is the song database's own tags (see build_songdf), so it merges in from the song side.
RECORDS_DB_COLUMNS = ['songid', 'title', 'button', 'pattern', 'level', 'is_sc', 'floor_name',
                      'dlc_code', 'is_new', 'hint', 'score', 'max_combo', 'djpower',
                      'max_djpower', 'rating', 'datetime', 'cleared', 'tags', 'tags_score']

MERGE_KEYS = ['songid', 'button', 'pattern']

# The tags csv's join keys, the column its feature dicts land in, and their score counterpart.
ATTR_KEYS = ['songid', 'title', 'pattern', 'level', 'button']
TAG_COL = 'tags'
TAGS_SCORE_COL = 'tags_score'


# ======================================================================
# Validate data input
# ======================================================================

class SongDB(BaseModel):
    songid: int
    title: str
    pattern: Literal["NM", "HD", "MX", "SC"]
    level: int
    dlc_code: str
    button: int
    floor_name: Decimal | None = Field(alias='floorName')
    is_new: bool
    # The pattern's tags as one string ("group-code" per tag, ','-joined; "standard" in front for
    # a chart songs.json flags `standard`), None when the chart has neither.
    hint: str | None = None





class SongRecords(BaseModel):
    songid: int
    title: str
    pattern: Literal["NM", "HD", "MX", "SC"]
    level: int
    dlc_code: str
    button: int
    floor_name: Decimal | None
    is_new: bool
    score: Decimal
    max_combo: bool
    djpower: Decimal
    max_djpower: Decimal
    rating: Decimal | None
    # API's updatedAt: ISO-8601 UTC ("2026-08-17T08:21:14.000Z"); null when the archive omits it.
    datetime: datetime | None


# ======================================================================
# Import & merge
# ======================================================================
def _prep_songs(df: pd.DataFrame) -> pd.DataFrame:
    """ songdb_df formation"""
    df = df.copy()
    df['songid'] = df['songid'].astype(int)
    df['button'] = df['button'].astype(int)
    df['level'] = df['level'].astype(int)
    df['is_new'] = df['is_new'].astype(bool)
    df['pattern'] = df['pattern'].astype(str).str.upper()
    df['dlc_code'] = df['dlc_code'].astype(str)
    df['title'] = df['title'].astype(str)
    df['floor_name'] = df['floor_name'].astype(str)
    df['is_sc'] = df['pattern'].eq('SC')
    return df

def _prep_records(df: pd.DataFrame) -> pd.DataFrame:
    """recorddf formation"""
    df = df.copy()
    df['songid'] = df['songid'].astype(int)
    df['button'] = df['button'].astype(int)
    df['level'] = df['level'].astype(int)
    df['pattern'] = df['pattern'].astype(str).str.upper()
    df['max_combo'] = df['max_combo'].astype(bool)
    for col in ['score', 'djpower', 'max_djpower', 'rating']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    # updatedAt as a real timestamp (UTC, as the archive sends it); missing ones become NaT.
    df['datetime'] = pd.to_datetime(df['datetime'], utc=True, errors='coerce')
    return df

def _prep_tags(df: pd.DataFrame) -> pd.DataFrame:
    """The wide tags csv as one feature dict per chart, keyed by ATTR_KEYS."""
    df = df.copy()
    df['button'] = df['button'].astype(int)
    df['level'] = df['level'].astype(int)
    df['pattern'] = df['pattern'].astype(str).str.upper()
    df['title'] = df['title'].astype(str)

    feature_cols = [c for c in df.columns if c not in ATTR_KEYS]
    for c in feature_cols:
        df[c] = pd.to_numeric(df[c], errors='coerce')

    def row_to_dict(row):
        return {c: row[c] for c in feature_cols if pd.notna(row[c])}

    df[TAG_COL] = df[feature_cols].apply(row_to_dict, axis=1)
    return df[ATTR_KEYS + [TAG_COL]]

def _chart_hint(hints, standard: bool = False) -> str | None:
    """A chart's hints list (songs.json's pattern info) as one hint string; None when unhinted.

    One "group-code" pair per hint — "assist-half" — several hints joined by ','
    ("assist-max,svam-variable"), the order the song database lists them in. A chart whose pattern
    info carries `standard: true` gets "standard" in front ("standard,assist-max"): the flag has
    no column of its own, and the hint is where a chart's own attributes are shown.
    """
    pairs = []
    if isinstance(hints, list):
        pairs = [f"{t['tagGroup']}-{t['tagCode']}" for t in hints
                 if isinstance(t, dict) and 'tagGroup' in t and 'tagCode' in t]
    if standard:
        pairs.insert(0, 'standard')
    return ','.join(pairs) or None

def _load_song_db() -> list:
    """Song database produced by api_handler (CACHE_PATH/songs.json); fetched once if absent."""
    db_path = os.path.join(CACHE_PATH, 'songs.json')
    if not os.path.exists(db_path):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(api_handler.fetch_song_db())
        else:
            raise RuntimeError(
                f'{db_path} is missing and cannot be fetched from inside a running event '
                'loop; await api_handler.fetch_song_db() there instead.'
            )
    with open(db_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def build_songdf():
    songs = []
    # entry = "title" "name" "composer" "dlcCode" "newTab" "patterns : {buttonmode : button_diffs"
    for entry in _load_song_db():
        song_info = {'songid': entry.get('title'),
                     'title': entry.get('name'),
                     #'composer': entry.get('composer'),
                     'dlc_code': entry.get('dlcCode'),
                     'is_new': entry.get('newTab'),}

    # Fetch button & difficulties
    # button_mode = "4B", button_diffs = { diff(NM,HD,MX,SC) : info{level:6, floor:23, floorName:2.3} ｝
        for button_mode, button_diffs in entry.get('patterns', {}).items():
            for diff, info in button_diffs.items():
                song = song_info.copy()
                song['button'] = str(button_mode)[:1]
                song['pattern'] = diff
                for key, value in info.items():
                    song[key] = value
                if not song.get('floorName'): song['floorName'] = None
                song['hint'] = _chart_hint(info.get('tags'), info.get('standard'))
                songs.append(song)

    songdb_validated = [SongDB.model_validate(data) for data in songs]
    songdb_df = pd.DataFrame([data.model_dump() for data in songdb_validated])
    return songdb_df


# The columns build_recorddf produces — also the shape of its empty result, for a mapping
# whose only mode has no records at all (e.g. an untouched 5B).
RECORDS_COLUMNS = ['songid', 'title', 'pattern', 'level', 'dlc_code', 'button',
                   'floor_name', 'is_new', 'score', 'max_combo', 'djpower',
                   'max_djpower', 'rating', 'datetime']

def _varecord_buttonlist(varecord: dict) -> list[int]:
    """The button modes a {bmode: raw response text} mapping holds, in canonical order.

    The mapping may be partial — the inspector scripts fetch a single button mode and inject
    it without touching the store — but an empty one has nothing to build from.
    """
    buttons = [bmode for bmode in BMODES if str(bmode) in varecord]
    if not buttons:
        raise ValueError('varecord holds no button mode entries (expected keys "4"/"5"/"6"/"8")')
    return buttons


def build_recorddf(varecord: dict | None = None):
    """The mapping's button modes' records as a dataframe.

    `varecord` is a {bmode: raw response text} mapping; it defaults to the stored
    full_varecord.json. It may be partial — only the modes it holds are built (see
    _varecord_buttonlist), which is what the single-mode inspector fetches rely on.
    """
    records = []
    # Fetch song basic info
    if varecord is None:
        varecord = read_full_varecord()
    for button_mode in _varecord_buttonlist(varecord):
        button_pack = json.loads(varecord[f"{button_mode}"])
        button_records = button_pack.get("records")

        for entry in button_records:
            entry["button"] = button_mode
            record_info = {'songid': entry.get('title'),
                           'title': entry.get('name'),
                           'pattern': entry.get('pattern'),
                           'level': entry.get('level'),
                           'dlc_code': entry.get('dlcCode'),
                           'button': entry.get('button'),
                           'floor_name': entry.get('floorName'),
                           'is_new': entry.get('newTab'),
                           'score': entry.get('score'),
                           'max_combo': entry.get('maxCombo'),
                           'djpower': entry.get('djpower'),
                           'max_djpower': entry.get('maxDjpower'),
                           'rating': entry.get('rating'),
                           'datetime': entry.get('updatedAt')
                           }

            records.append(record_info)

    records_validated = [SongRecords.model_validate(data) for data in records]
    if records_validated:
        recorddf = pd.DataFrame([data.model_dump() for data in records_validated])
    else:
        recorddf = pd.DataFrame(columns=RECORDS_COLUMNS)
    return recorddf


def _fill_maxpower(df: pd.DataFrame, col: str = 'max_djpower',) -> pd.DataFrame:
    """Fill the theoretical max djpower of the rows that have no record yet."""
    df = df.copy()

    def compute(row):
        level = int(row['level'])
        is_sc = row['is_sc']
        coeff = util.diff_coeff(level, is_sc)
        return float(util.djpower_pp(coeff))

    mask = df[col].isna()
    if mask.any():
        df.loc[mask, col] = df[mask].apply(compute, axis=1)
    return df


# ======================================================================
# The hand-maintained tags csv: joined and scored at build time
# ======================================================================

# Generate tags score by using djpower/max djpower ratio(caculates tags score like vanilla game)
def compute_tags_score(df: pd.DataFrame,
                       tags_col: str = 'tags',
                       out_col: str = 'tags_score') -> pd.DataFrame:

    df = df.copy()

    djpower = pd.to_numeric(df['djpower'], errors='coerce')
    max_djpower = pd.to_numeric(df['max_djpower'], errors='coerce')

    valid = (
        djpower.notna()
        & max_djpower.notna()
        & (max_djpower != 0)
        & df[tags_col].apply(lambda d: isinstance(d, dict) and bool(d))
    )

    df[out_col] = pd.Series([{} for _ in range(len(df))],
                        index=df.index,
                        dtype=object)
    ratios = djpower[valid] / max_djpower[valid]

    def build(tags, ratio):
        return {k: v * ratio for k, v in tags.items()}

    df.loc[valid, out_col] = pd.Series(
        [build(tags, ratio)
         for tags, ratio in zip(df.loc[valid, tags_col], ratios)],
        index=df.index[valid],
        dtype=object,
    )

    return df


def _tags_to_json(tags) -> str:
    """One tag dict as the JSON text the parquet stores; an empty dict stays an empty JSON dict."""
    return json.dumps(tags if isinstance(tags, dict) else {})


def _attach_tags(df: pd.DataFrame) -> pd.DataFrame:
    """Join the tags csv onto the merged frame and add tags_score, both stored as JSON text.

    This is the whole reason an edit to the hand-maintained csv needs no re-download: it is done
    here, at build time, and db_is_stale() watches the csv's mtime, so an edited csv only forces an
    offline rebuild of the parquet.
    """
    attributes = pd.read_csv(TAGS_CSV_PATH, encoding='utf-8-sig')
    df = pd.merge(df, _prep_tags(attributes), on=ATTR_KEYS, how='left')
    df[TAG_COL] = df[TAG_COL].apply(lambda x: x if isinstance(x, dict) else {})
    df = compute_tags_score(df)
    for col in (TAG_COL, TAGS_SCORE_COL):
        df[col] = df[col].map(_tags_to_json)
    return df

# ======================================================================
# The records_db store (records/records_db.parquet + records/db_meta.json)
# ======================================================================

def build_records_db(varecord: dict | None = None) -> pd.DataFrame:
    """The frame the parquet stores: song database ⊕ records, max_djpower filled, tags attached.

    `varecord` is forwarded to build_recorddf(): None means "read the stored
    full_varecord.json"; a mapping means "use these records" — what
    data_converter.records_db_from_varecord passes for the inspector scripts, which
    download them. A full mapping builds all four modes exactly as the parquet stores them; a
    partial one builds only the modes it holds, with the song side filtered to match — so a
    single-mode injection yields exactly that mode's frame. The hand-maintained tags csv is
    joined and scored by _attach_tags, so the returned frame carries the tags / tags_score
    columns the parquet does — as JSON text — and the song database's tags ride along as the
    plain-text hint column, merged in from the song side.

    Records whose (songid, button, pattern) the song database does not know drop out of the
    left merge; that is reported, because it means the cached songs.json is older than the
    records and a refresh is due.
    """
    if varecord is None:
        varecord = read_full_varecord()
    modes = _varecord_buttonlist(varecord)

    songs = _prep_songs(build_songdf())
    if len(modes) < len(BMODES):
        songs = songs[songs['button'].isin(modes)]
    records = _prep_records(build_recorddf(varecord))

    record_cols = MERGE_KEYS + ['score', 'max_combo', 'djpower',
                                'max_djpower', 'rating', 'datetime']
    merged = pd.merge(songs, records[record_cols], on=MERGE_KEYS, how='left')
    merged['cleared'] = merged['score'].notna()
    merged = _fill_maxpower(merged)
    merged = _attach_tags(merged)

    matched = int(merged['cleared'].sum())
    if matched < len(records):
        dropped = len(records) - matched
        print(f'warning: {dropped} record(s) have no row in the song database and drop out of '
              'records_db — the cached songs.json is older than the records; run a refresh')
    return merged[RECORDS_DB_COLUMNS]




def records_db_path() -> str:
    """Path of the parquet holding the merged record store."""
    return os.path.join(RECORDS_PATH, RECORDS_DB_FILENAME)


def db_meta_path() -> str:
    return os.path.join(RECORDS_PATH, DB_META_FILENAME)


def read_db_meta() -> dict:
    """db_meta.json as a dict; empty when it is missing or unreadable."""
    try:
        with open(db_meta_path(), 'r', encoding='utf-8') as f:
            meta = json.load(f)
    except (OSError, ValueError):
        return {}
    return meta if isinstance(meta, dict) else {}


def _tags_stamp() -> tuple[float, int] | None:
    """(mtime, size) of the tag table; None when the file is missing."""
    try:
        info = os.stat(TAGS_CSV_PATH)
    except OSError:
        return None
    return (info.st_mtime, info.st_size)


def db_is_stale() -> bool:
    """True when records_db.parquet cannot serve a read as it is.

    Missing, built by an older schema (db_meta.json's `schema`), built from a different version
    of the tag table (its mtime/size is stamped into db_meta.json, so replacing the csv with a
    file that carries an older timestamp still triggers a rebuild), or older than a file it is
    built from: the raw layer, the song database, or the tags csv.
    """
    db = records_db_path()
    if not os.path.exists(db):
        return True
    meta = read_db_meta()
    if meta.get('schema') != DB_SCHEMA:
        return True
    stamp = _tags_stamp()
    if stamp is not None and meta.get('tags_stamp') != list(stamp):
        return True
    built = os.path.getmtime(db)
    for source in (full_varecord_path(), os.path.join(CACHE_PATH, 'songs.json'), TAGS_CSV_PATH):
        if os.path.exists(source) and os.path.getmtime(source) > built:
            return True
    return False


def save_records_db() -> None:
    """Rebuild records_db.parquet from the raw layer and refresh db_meta.json.

    Purely offline: reads full_varecord.json (the raw layer), songs.json and the tags csv, never
    the network. Raises FileNotFoundError when the raw layer is missing entries or unreadable — a
    full refresh has to fill it first (ensure_db_available / refresh_records do that on their own).

    Both outputs are staged beside their targets and swapped in with os.replace, so an
    interrupted rebuild leaves the previous store intact instead of a truncated parquet.

    db_meta.json records whose account the parquet holds — all four raw entries agree (modulo
    case) or the username is None, a mixed store that data_converter's account-checked readers
    refuse and ensure_db_available repairs with a full fetch — and the `schema` it was built with.
    """
    os.makedirs(RECORDS_PATH, exist_ok=True)
    combined = read_full_varecord()
    # _entry_account() parses a whole payload, so the completeness gate and the account stamp
    # share one pass over the four entries instead of parsing each of them twice.
    accounts = {bmode: _entry_account(combined.get(str(bmode))) for bmode in BMODES}
    missing = [f'{bmode}B' for bmode, account in accounts.items() if account is None]
    if missing:
        raise FileNotFoundError(
            f'full_varecord.json cannot serve {", ".join(missing)} yet, so records_db cannot be '
            'rebuilt — run a refresh first (menu [1])')

    db = build_records_db(combined)

    names = {account.casefold() for account in accounts.values()}
    username = accounts[BMODES[0]] if len(names) == 1 else None
    meta = {'username': username,
            'built_at': datetime.now().isoformat(timespec='seconds'),
            'schema': DB_SCHEMA}
    tags_stamp = _tags_stamp()
    if tags_stamp is not None:
        meta['tags_stamp'] = list(tags_stamp)

    # The two replaces are adjacent (no I/O between them), so the pair is inconsistent for
    # microseconds at most; the parquet lands first and the meta describing it follows.
    parquet_path = records_db_path()
    meta_path = db_meta_path()
    parquet_tmp = parquet_path + '.tmp'
    meta_tmp = meta_path + '.tmp'
    try:
        db.to_parquet(parquet_tmp, index=False)
        with open(meta_tmp, 'w', encoding='utf-8') as f:
            json.dump(meta, f, indent=4)
        os.replace(parquet_tmp, parquet_path)
        os.replace(meta_tmp, meta_path)
    finally:
        for leftover in (parquet_tmp, meta_tmp):
            if os.path.isfile(leftover):
                os.remove(leftover)
    print(f'records_db rebuilt ({len(db)} rows, account {username or "mixed"})')


async def ensure_db_available(username: str) -> None:
    """Make records_db.parquet serve `username`, downloading only when it cannot.

    The one call the local generators make before reading (see generate.*_local):
      - store missing or holding another account → full four-mode fetch (a partial store
        cannot yield a single-account parquet, so partial data escalates to a full fetch);
      - store present and current → a no-op, not even a request;
      - only songs.json moved under the store → an offline rebuild, still no requests.
    Raises on network failure; callers that prefer to fall back to the stored data catch it.
    """
    if not os.path.exists(os.path.join(CACHE_PATH, 'songs.json')):
        await api_handler.fetch_song_db()   # an offline rebuild needs it, and this is the
        # only way to get it from inside a running event loop

    meta = read_db_meta()
    if str(meta.get('username') or '').casefold() != username.casefold():
        stored = meta.get('username')
        print(f'records_db holds {stored!r}, fetching all four modes for {username!r}')
        fetch_all(username)
        _absorb_new_records(username)
        return

    if not db_is_stale():
        return
    try:
        save_records_db()                   # offline rebuild from the raw layer
    except FileNotFoundError:
        fetch_all(username)                 # raw layer gone or unusable; re-download
        _absorb_new_records(username)


def refresh_records(username: str) -> None:
    """Re-download all four button modes for `username` and rebuild records_db.parquet.

    `fetch_all` rewrites the raw layer wholesale, so the store can never end up mixing accounts;
    the parquet is rebuilt from that layer afterwards, so readers never see a half-updated store.
    """
    fetch_all(username)
    _absorb_new_records(username)


def _absorb_new_records(username: str) -> None:
    """Fold a freshly fetched record state into the stores: the play history first, then the
    records_db rebuild. History comes first because it is derived straight from the raw layer —
    a crash after this point still leaves both consistent, and the next refresh's snapshot diff
    self-heals anything the crash interrupted.
    """
    from . import history                   # lazy: history reads this module's raw-layer helpers
    history.update_history(username, read_full_varecord())
    save_records_db()


# ======================================================================
# The raw layer (records/full_varecord.json) — network and file primitives
# ======================================================================

def full_varecord_path() -> str:
    """Path of the combined file holding every button mode's record list.

    It lives in RECORDS_PATH (records/), not in CACHE_PATH, so `remove_cache()` cannot clear it.
    """
    return os.path.join(RECORDS_PATH, 'full_varecord.json')


def read_full_varecord() -> dict[str, str]:
    """The combined file as {bmode: raw response text}; empty when it is missing or unreadable."""
    try:
        with open(full_varecord_path(), 'r', encoding='utf-8') as f:
            combined = json.load(f)
    except (OSError, ValueError):
        return {}
    return combined if isinstance(combined, dict) else {}


def write_full_varecord(combined: dict) -> None:
    os.makedirs(RECORDS_PATH, exist_ok=True)    # records/ is not part of the cache and is not in git
    with open(full_varecord_path(), 'w', encoding='utf-8') as f:
        json.dump(combined, f, indent=4)


def fetch_one(username: str, bmode: int) -> str:
    """Download one button mode's full record list. Returns the raw text; writes nothing."""
    print(f'Fetching archive for {username} - {bmode}b')
    response = api_handler.get_with_retry(api_handler.build_req_url(username, bmode))
    response.raise_for_status()
    return response.text


def fetch_all(username: str, write: bool = True) -> dict[str, str]:
    """Download every button mode and return {bmode: raw response text}.

    With `write` (the default) the result also rewrites full_varecord.json, the raw layer the
    records_db is rebuilt from, keeping it up to date. `write=False` only returns the mapping
    and leaves that file alone — the inspector scripts use it to look at another account
    without mixing it into the local record store.
    """
    texts = {str(bmode): fetch_one(username, bmode) for bmode in BMODES}
    if write:
        write_full_varecord(texts)
        print(f'Saved {len(texts)} modes to full_varecord.json')
    return texts


def _entry_account(text) -> str | None:
    """Nickname stored in one record payload, or None when the payload is unusable.

    A payload whose account cannot be established is None as well — a missing, null, empty or
    non-string `nickname`. Such an entry parses, but it cannot be attributed to an account, so a
    store built from it could not be served to anyone: save_records_db's completeness check
    treats it exactly like an unreadable entry, and ensure_db_available repairs the store with a
    full fetch.
    """
    if not isinstance(text, str):
        return None
    try:
        payload = json.loads(text)
    except ValueError:
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get('records'), list):
        return None
    nickname = payload.get('nickname')
    return nickname if isinstance(nickname, str) and nickname else None


