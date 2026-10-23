import os
import time

from PIL import Image

from . import api_handler, models, generators, paths
from .analyzer import data_fetcher, data_converter


async def generate_bests(username: str, bmode: int) -> Image.Image:
    bests_data = await api_handler.fetch_bests(username, bmode)
    return await generators.generate_bests_image(bests_data)


async def generate_bests_theoretical(bmode: int) -> Image.Image:
    song_db = await api_handler.fetch_song_db()
    bests_data = models.DMBests.get_theoretical_bests(bmode, song_db)
    return await generators.generate_bests_image(bests_data, is_max=True)


async def generate_scorelist(username: str, bmode: int, is_sc: bool, level: int) -> Image.Image:
    scorelist_data = await api_handler.fetch_scorelist(username, bmode, is_sc, level)
    return await generators.generate_scorelist_by_level(scorelist_data)


async def generate_scorelist_new(username: str, bmode: int, diff: str) -> Image.Image:
    scorelist_data = await api_handler.fetch_scorelist_new(username, bmode, diff)
    return await generators.generate_scorelist_by_pack(scorelist_data, "NEW")


async def generate_scorelist_pack(username: str, bmode: int, diff: str, pack: str) -> Image.Image:
    scorelist_data = await api_handler.fetch_scorelist_pack(username, bmode, diff, pack)
    return await generators.generate_scorelist_by_pack(scorelist_data, pack)


async def generate_scorelist_pp(username: str, bmode: int) -> Image.Image:
    scorelist_data = await api_handler.fetch_scorelist_pp(username, bmode)
    return await generators.generate_scorelist_pp(scorelist_data)


# ---------------------------------------------------------------------------
# Local-record-store variants: same rendering as above, but the data is read from
# records/records_db.parquet through data_converter instead of the network. Rendering is
# shared, so both families produce identical images for identical data.
#
# data_fetcher.ensure_db_available() is the only network-touching step: it is a no-op while the
# store already serves `username`, and otherwise downloads the records (or rebuilds the store
# offline when only the song database moved under it). data_converter's readers themselves
# never touch the network and refuse a store that holds another account.
# There is no local variant of generate_bests_theoretical: it only needs the song
# database, which api_handler reads from the cached songs.json.
# ---------------------------------------------------------------------------

async def generate_bests_local(username: str, bmode: int) -> Image.Image:
    await data_fetcher.ensure_db_available(username)
    bests_data = await data_converter.fetch_bests(username, bmode)
    return await generators.generate_bests_image(bests_data)


async def generate_scorelist_local(username: str, bmode: int, is_sc: bool, level: int) -> Image.Image:
    await data_fetcher.ensure_db_available(username)
    scorelist_data = await data_converter.fetch_scorelist(username, bmode, is_sc, level)
    return await generators.generate_scorelist_by_level(scorelist_data)


async def generate_scorelist_new_local(username: str, bmode: int, diff: str) -> Image.Image:
    await data_fetcher.ensure_db_available(username)
    scorelist_data = await data_converter.fetch_scorelist_new(username, bmode, diff)
    return await generators.generate_scorelist_by_pack(scorelist_data, "NEW")


async def generate_scorelist_pack_local(username: str, bmode: int, diff: str, pack: str) -> Image.Image:
    await data_fetcher.ensure_db_available(username)
    scorelist_data = await data_converter.fetch_scorelist_pack(username, bmode, diff, pack)
    return await generators.generate_scorelist_by_pack(scorelist_data, pack)


async def generate_scorelist_pp_local(username: str, bmode: int) -> Image.Image:
    await data_fetcher.ensure_db_available(username)
    scorelist_data = await data_converter.fetch_scorelist_pp(username, bmode)
    return await generators.generate_scorelist_pp(scorelist_data)


async def generate_all_local(username: str) -> None:
    """Render every single (non-summary) chart for `username` from the local store.

    This is the exe menu's `[2] 生成全部图片`: bests (full-size + resized copy), every level's
    SC and non-SC scorelist, new songs for all four difficulties, perfect plays and the
    theoretical top 100. Everything is offline; the store must already serve `username`
    (data_fetcher.ensure_db_available handles that on the first call).
    """
    def save(image: Image.Image, *parts: str) -> str:
        path = os.path.join(paths.OUTPUT_DIR, *parts)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        image.save(path)
        print(f'Saved {path}')
        return path

    for mode in (4, 5, 6, 8):
        image = await generate_bests_local(username, mode)
        save(image, f'best_{username}_{mode}B.png')
        resized = image.resize((1540, 2346), Image.Resampling.LANCZOS)
        save(resized, f'best_{mode}B',
             f'best_{username}_{mode}B_{time.strftime("%Y%m%d_%H%M", time.localtime())}.png')

    for mode in (4, 5, 6, 8):
        for level in range(1, 16):
            image = await generate_scorelist_local(username, mode, True, level)
            save(image, f'level_{mode}B', f'scorelist_{mode}B_sc{level}.png')
            image = await generate_scorelist_local(username, mode, False, level)
            save(image, f'level_{mode}B', f'scorelist_{mode}B_{level}.png')

    for mode in (4, 5, 6, 8):
        for diff in ("NM", "HD", "MX", "SC"):
            image = await generate_scorelist_new_local(username, mode, diff)
            save(image, f'level_{mode}B', f'scorelist_new_{mode}B{diff}.png')

    for mode in (4, 5, 6, 8):
        image = await generate_scorelist_pp_local(username, mode)
        save(image, f'scorelist_pp_{mode}B.png')

    for mode in (4, 5, 6, 8):
        print(f'Generating theoretical for {username} - {mode}B')
        image = await generate_bests_theoretical(mode)
        save(image, 'theoretical', f'theoretical_{mode}B.png')
