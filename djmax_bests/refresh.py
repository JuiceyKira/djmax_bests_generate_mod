"""Refresh the account-independent caches and the archive records for one account.

This is the body behind the exe menu's `[1] 刷新成绩`; there is no root-level refresh script any
more. The account-independent caches (songs.json, dlcs.json, maxpower_*.txt) are re-downloaded
only when missing or older than `[refresh] max_age_days` in settings.ini (7 days by default), so
a routine "I played a few songs" refresh costs one small request per button mode, while a game
update is picked up within a week — or immediately by lowering that value / deleting the cache
file.

All four button modes are refreshed: data_fetcher.refresh_records rewrites the raw layer
wholesale, so the store can never end up mixing accounts, and rebuilds `records_db.parquet`
from it — every reader, the local generators and `AnalyzeUtil` alike, sees the update.

Jackets are prefetched after the refresh: the executable ships only the placeholder, so the
first refresh fills `covers/` and later ones only fetch genuinely new songs.

This never closes the shared HTTP client and never touches the event loop itself.
"""
import os

from . import api_handler, settings
from .analyzer import data_fetcher

BMODES = (4, 5, 6, 8)


async def refresh_caches(username: str) -> None:
    """Refresh maxpower, songs.json, dlcs.json, the archive records and missing jackets."""
    max_age = settings.refresh_options()["max_age_days"]
    labels = ', '.join(f'{bmode}B' for bmode in BMODES)

    print(f"=== caches (re-downloaded when older than {max_age:g} days) ===")
    for bmode in BMODES:
        maxpower_file = os.path.join(api_handler.CACHE_PATH, f'maxpower_{bmode}.txt')
        age = api_handler.cache_age_days(maxpower_file)
        _, maxpower = api_handler.get_convert_constant(bmode, max_age_days=max_age)
        state = 'missing, fetched' if age is None else f'{age:.1f} days old'
        print(f"    maxpower {bmode}B: {maxpower} ({state})")

    song_db = await api_handler.fetch_song_db(max_age_days=max_age)
    dlc_list = await api_handler.fetch_dlc_list(max_age_days=max_age)
    print(f"    songs={len(song_db.root)} dlcs={len(dlc_list.root)}")

    print(f"=== archive records for {username}: {labels} ===")
    data_fetcher.refresh_records(username)

    print("=== jackets ===")
    await api_handler.prefetch_covers([entry.songid for entry in song_db.root])
