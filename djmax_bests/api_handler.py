import asyncio
import time

import httpx, os, urllib.parse
from PIL import Image
from decimal import Decimal


from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from . import models

from . import paths


COVER_PATH = paths.state_path('covers', os.path.join(os.path.dirname(__file__), 'covers'))
CACHE_PATH = paths.state_path('cache', os.path.join(os.path.dirname(__file__), 'cache'))
# Persistent record store, deliberately outside CACHE_PATH: remove_cache() empties the whole cache
# directory, and the archive records have to survive it (same policy as the hand-maintained
# analyzer/djmax_songs_tags.csv and target_generator/accuracy_ratio.csv).
RECORDS_PATH = paths.state_path('records',
                                os.path.join(os.path.dirname(os.path.dirname(__file__)), 'records'))
HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "sh-util-bot/gh:SoreHait/djmax_bests_generate"
}

client = httpx.AsyncClient(headers=HEADERS)
RETRIES = 3

#: How old a cache file may get before the refresh entry re-downloads it. Overridable through
#: settings.ini ([refresh] max_age_days); 7 days is the built-in default.
CACHE_MAX_AGE_DAYS = 7


def cache_age_days(path: str) -> float | None:
    """Age of a cache file in days, or None when it does not exist."""
    try:
        return (time.time() - os.path.getmtime(path)) / 86400
    except OSError:
        return None


def cache_is_stale(path: str, max_age_days: float = CACHE_MAX_AGE_DAYS) -> bool:
    """True when the file is missing or older than `max_age_days`."""
    age = cache_age_days(path)
    return age is None or age > max_age_days


if not os.path.exists(COVER_PATH):
    os.makedirs(COVER_PATH)

if not os.path.exists(CACHE_PATH):
    os.makedirs(CACHE_PATH)


async def get_with_retry_async(url) -> httpx.Response:
    global client, RETRIES

    for _ in range(RETRIES):
        try:
            return await client.get(url)
        except httpx.TimeoutException:
            continue
    raise httpx.TimeoutException(f"Failed to fetch {url} after {RETRIES} retries")

def get_with_retry(url) -> httpx.Response:
    global RETRIES, HEADERS

    for _ in range(RETRIES):
        try:
            return httpx.get(url, headers=HEADERS)
        except httpx.TimeoutException:
            continue
    raise httpx.TimeoutException(f"Failed to fetch {url} after {RETRIES} retries")


async def aclose() -> None:
    """Close the shared HTTP client; meant for scripts that end after their last request.

    Without this the pooled connections are collected after the event loop is gone, which
    prints an ignored `_ProactorBasePipeTransport.__del__` error on Windows.
    """
    await client.aclose()


def _placeholder_cover() -> Image.Image:
    """The bundled placeholder jacket, or a black square when even that is missing."""
    placeholder = os.path.join(COVER_PATH, 'dummy.jpg')
    if os.path.exists(placeholder):
        return Image.open(placeholder)
    return Image.new('RGB', (80, 80), color='black')


async def get_cover(songid: int, quiet: bool = False) -> Image.Image:
    img_path = os.path.join(COVER_PATH, f'{songid}.jpg')
    if os.path.exists(img_path):
        return Image.open(img_path)

    url = f"https://v-archive.net/s3/images/jackets/{songid}.jpg"
    if not quiet:
        print(f'Fetching cover {songid}')
    response = await get_with_retry_async(url)
    if response.status_code == 200:
        with open(img_path, 'wb') as f:
            f.write(response.content)
        return Image.open(img_path)
    if not quiet:
        print(f'Failed to get cover {songid}')
    return _placeholder_cover()


async def prefetch_covers(songids, concurrency: int = 15, quiet: bool = False) -> int:
    """Download the jackets missing from COVER_PATH; returns how many were fetched.

    The executable ships only the placeholder jacket, so the first refresh fills the cover
    folder here (one request per song) instead of carrying ~13 MB of jackets inside the exe.
    Later refreshes find everything present and do nothing.
    """
    ids = list(dict.fromkeys(int(songid) for songid in songids))
    missing = [songid for songid in ids
               if not os.path.exists(os.path.join(COVER_PATH, f'{songid}.jpg'))]
    if not missing:
        if not quiet:
            print(f'    covers: all {len(ids)} jackets present')
        return 0

    if not quiet:
        print(f'    covers: {len(missing)} of {len(ids)} missing, downloading...')
    semaphore = asyncio.Semaphore(concurrency)
    done = 0

    async def worker(songid: int) -> None:
        nonlocal done
        async with semaphore:
            await get_cover(songid, quiet=True)
        done += 1
        if not quiet and done % 50 == 0:
            print(f'      {done}/{len(missing)}')

    await asyncio.gather(*(worker(songid) for songid in missing))
    if not quiet:
        print(f'    covers: {done} downloaded')
    return done

def get_convert_constant(bmode: int, max_age_days: float | None = None) -> tuple[Decimal, Decimal]:
    maxpower_file = os.path.join(CACHE_PATH, f'maxpower_{bmode}.txt')
    if os.path.exists(maxpower_file) and (
            max_age_days is None or not cache_is_stale(maxpower_file, max_age_days)):
        with open(maxpower_file, 'r') as f:
            maxpower = Decimal(f.read().strip())
            return Decimal("10000.0000") / maxpower, maxpower

    print(f'maxpower cache for {bmode}b invalidated, fetching new one')
    url = f"https://v-archive.net/api/v2/archive/DEV/djClass/{bmode}"
    response = get_with_retry(url)
    response.raise_for_status()
    data = response.json()
    with open(maxpower_file, 'w') as f:
        f.write(str(data["maxDjPower"]))
    maxpower = Decimal(str(data["maxDjPower"]))
    return Decimal("10000.0000") / maxpower, maxpower

async def fetch_song_db(max_age_days: float | None = None) -> "models.DMSongDB":
    from .models import DMSongDB
    db_path = os.path.join(CACHE_PATH, 'songs.json')
    if os.path.exists(db_path) and (
            max_age_days is None or not cache_is_stale(db_path, max_age_days)):
        with open(db_path, 'r', encoding='utf-8') as f:
            return DMSongDB.model_validate_json(f.read())

    print("songdb cache invalidated, fetching new one")
    url = "https://v-archive.net/db/v2/songs.json"
    response = await get_with_retry_async(url)
    response.raise_for_status()
    with open(db_path, 'w', encoding='utf-8') as f:
        f.write(response.text)
    return DMSongDB.model_validate_json(response.text)

async def fetch_dlc_list(max_age_days: float | None = None) -> "models.VADLCList":
    from .models import VADLCList
    dlc_path = os.path.join(CACHE_PATH, 'dlcs.json')
    if os.path.exists(dlc_path) and (
            max_age_days is None or not cache_is_stale(dlc_path, max_age_days)):
        with open(dlc_path, 'r', encoding='utf-8') as f:
            return VADLCList.model_validate_json(f.read())

    print("dlc list cache invalidated, fetching new one")
    url = "https://v-archive.net/db/dlcs.json"
    response = await get_with_retry_async(url)
    response.raise_for_status()
    with open(dlc_path, 'w', encoding='utf-8') as f:
        f.write(response.text)
    return VADLCList.model_validate_json(response.text)

def remove_cache():
    cache_files = os.listdir(CACHE_PATH)
    for file in cache_files:
        file_path = os.path.join(CACHE_PATH, file)
        if os.path.isfile(file_path):
            os.remove(file_path)
    print("Cache cleared")


def build_req_url(username: str, bmode: int, **kwargs) -> str:
    query = urllib.parse.urlencode(kwargs)
    return f"https://v-archive.net/api/v2/archive/{username}/button/{bmode}?{query}"

async def fetch_bests(username: str, bmode: int) -> "models.DMBests":
    from .models import DMBests, VAResponse
    print(f'Fetching bests for {username} - {bmode}b')
    url_basic = build_req_url(
        username,
        bmode,
        newTab = "false",
        sort = "djpower",
        order = "desc",
        limit = "70"
    )
    url_new = build_req_url(
        username,
        bmode,
        newTab = "true",
        sort = "djpower",
        order = "desc",
        limit = "30"
    )
    response_basic = await get_with_retry_async(url_basic)
    response_basic.raise_for_status()
    response_new = await get_with_retry_async(url_new)
    response_new.raise_for_status()

    va_resp_basic = VAResponse.model_validate_json(response_basic.text)
    va_resp_new = VAResponse.model_validate_json(response_new.text)
    return DMBests.from_va_response(va_resp_basic, va_resp_new)

async def fetch_scorelist(username: str, bmode: int, is_sc: bool, level: int) -> "models.DMScorelist":
    from .models import DMScorelist, VAResponse
    print(f'Fetching scorelist for {username} - {bmode}b - {"SC" if is_sc else "^SC"} - level {level}')
    url = build_req_url(
        username,
        bmode,
        pattern = "SC" if is_sc else "NM,HD,MX",
        levelMin = level,
        levelMax = level
    )
    response = await get_with_retry_async(url)
    response.raise_for_status()
    song_db = await fetch_song_db()
    va_resp = VAResponse.model_validate_json(response.text)
    return DMScorelist.from_va_response_level(is_sc, level, song_db, va_resp)

async def fetch_scorelist_new(username: str, bmode: int, diff: str) -> "models.DMScorelist":
    from .models import DMScorelist, VAResponse
    print(f'Fetching scorelist for {username} - {bmode}b - NEW - {diff}')
    url = build_req_url(
        username,
        bmode,
        pattern = diff,
        newTab = "true"
    )
    response = await get_with_retry_async(url)
    response.raise_for_status()
    song_db = await fetch_song_db()
    va_resp = VAResponse.model_validate_json(response.text)
    return DMScorelist.from_va_response_new(diff, song_db, va_resp)

async def fetch_scorelist_pack(username: str, bmode: int, diff: str, pack: str) -> "models.DMScorelist":
    from .models import DMScorelist, VAResponse
    print(f'Fetching scorelist for {username} - {bmode}b - {pack} - {diff}')
    url = build_req_url(
        username,
        bmode,
        pattern = diff,
        dlc = pack
    )
    response = await get_with_retry_async(url)
    response.raise_for_status()
    song_db = await fetch_song_db()
    va_resp = VAResponse.model_validate_json(response.text)
    return DMScorelist.from_va_response_pack(diff, pack, song_db, va_resp)

async def fetch_scorelist_pp(username: str, bmode: int) -> "models.DMScorelist":
    from .models import DMScorelist, VAResponse
    print(f'Fetching PP scorelist for {username} - {bmode}b')
    url = build_req_url(
        username,
        bmode,
        sort = "score",
        order = "desc"
    )
    response = await get_with_retry_async(url)
    response.raise_for_status()
    va_resp = VAResponse.model_validate_json(response.text)
    return DMScorelist.from_va_response_pp(va_resp)
