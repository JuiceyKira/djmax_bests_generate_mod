"""Single-entry application for the Windows build (PyInstaller) and for source checkouts.

There is no python.exe, no runtime folder and no .py file beside the executable: the menu, the
renderers and the data layer all live inside the exe. Everything writable is kept next to it:

    DJMAX-Bests.exe
    settings.ini
    data/
        account.txt
        cache/      songs.json, dlcs.json, maxpower_*.txt
        covers/     jacket images
        records/    the local record store
    output/         generated images (beside data/, not inside it)

The menu runs in one asyncio loop for the whole session, so the shared httpx client never gets
used across event loops; it is closed once on exit.
"""
import asyncio
import os
import sys
import time

# The exe has no launcher to set PYTHONUTF8: force UTF-8 for redirected output (logs, pipes).
# The Windows console itself is written through the Unicode API, so this does not affect it.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from djmax_bests import paths

# Keep matplotlib's font cache inside the app's writable folder instead of the user profile,
# so a portable copy leaves no trace outside its own directory. PyInstaller's mplconfig runtime
# hook pre-sets this to a throw-away temp dir, so it must be overridden, not defaulted.
os.environ["MPLCONFIGDIR"] = os.path.join(paths.APP_DIR, ".matplotlib")

from djmax_bests import api_handler, settings

paths.ensure_app_dirs()
settings.ensure_exists()
paths.tags_csv_path()        # seed data/djmax_songs_tags.csv from the bundled default
COPIED = paths.seed_covers()


# --------------------------------------------------------------------------------------
# small console helpers
# --------------------------------------------------------------------------------------
def set_title() -> None:
    if os.name != "nt":
        return
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleTitleW("DJMAX 成绩图生成器v1.0.0")
    except Exception:
        pass


def clear() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def pause() -> None:
    try:
        input("\n按回车继续……")
    except EOFError:
        pass


def ask(prompt: str, default: str | None = None, choices: tuple[str, ...] | None = None) -> str:
    """Ask for a value; empty input takes `default`; `choices` are matched case-insensitively."""
    suffix = f"（回车 = {default}）" if default else ""
    while True:
        raw = input(f"{prompt}{suffix}：").strip()
        if not raw:
            if default is not None:
                return default
            print("不能为空，请重新输入。")
            continue
        if choices and raw.upper() not in [c.upper() for c in choices]:
            print("可选值：" + " / ".join(choices))
            continue
        return raw.upper() if choices else raw


def saved(path: str) -> None:
    print(f"\n[完成] 已保存 {path}")


# --------------------------------------------------------------------------------------
# account
# --------------------------------------------------------------------------------------
def read_account() -> str:
    name = ""
    try:
        with open(paths.ACCOUNT_FILE, "r", encoding="utf-8-sig") as handle:
            name = handle.read().strip()
    except OSError:
        pass
    if name:
        os.environ["DJMAX_USERNAME"] = name
        return name

    print("\n首次使用：请输入你的 V-ARCHIVE 账号名（区分大小写）。")
    while True:
        name = input("账号名：").strip()
        if name:
            break
        print("账号名不能为空。")
    write_account(name)
    print("已保存到 data/account.txt，之后可在菜单 [8] 修改。")
    return name


def write_account(name: str) -> None:
    with open(paths.ACCOUNT_FILE, "w", encoding="utf-8") as handle:
        handle.write(name + "\n")
    os.environ["DJMAX_USERNAME"] = name


# --------------------------------------------------------------------------------------
# tasks
# --------------------------------------------------------------------------------------
async def cmd_refresh(name: str) -> None:
    from djmax_bests import refresh as refresh_module
    started = time.time()
    await refresh_module.refresh_caches(name)
    print(f"=== refresh done in {time.time() - started:.1f}s ===")


async def cmd_all(name: str) -> None:
    from djmax_bests import generate
    await generate.generate_all_local(name)


def cmd_summary(name: str) -> None:
    from djmax_bests.generators.summary_generator import summary_generate

    opts = settings.summary_options()
    summary, modecards = summary_generate.generate_summary(
        name, opts["nickname"], opts["photo_id"], opts["prefer_button"], opts["info"])
    summary.save(os.path.join(paths.OUTPUT_DIR, "summary.png"))
    for bmode, image in modecards.items():
        image.save(os.path.join(paths.OUTPUT_DIR, f"summary_{bmode}B.png"))
    saved(os.path.join(paths.OUTPUT_DIR, "summary.png") + "（以及 4 张模式卡）")


async def cmd_history(name: str) -> None:
    from datetime import datetime

    from djmax_bests.generators.history_generator import history_generate

    raw = ask("日期 YYYYMMDD（回车 = 最近一天）", "")
    day = None
    while raw:
        try:
            day = datetime.strptime(raw, "%Y%m%d").date()
            break
        except ValueError:
            raw = ask("格式应为 YYYYMMDD，请重新输入（回车 = 最近一天）", "")

    days: list = []
    image = await history_generate.generate_history(name, False, day, days)
    if days and days[0] is not None:
        filename = f"History_{days[0]:%Y%m%d}.png"
    else:
        filename = f"History_{time.strftime('%Y%m%d', time.localtime())}.png"
    directory = os.path.join(paths.OUTPUT_DIR, "history")
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, filename)
    image.save(path)
    saved(path)


async def cmd_target(name: str) -> None:
    from djmax_bests.analyzer import data_analyzer
    from djmax_bests.generators.target_generator import target_generate, target_plan

    opts = settings.target_options()
    cap_default = opts["floor_cap"]

    bmode = int(ask("按键模式 [4/5/6/8]", "4", ("4", "5", "6", "8")))
    total = float(ask("目标总分", "6200"))
    accuracy = float(ask("预计准确率", "99.0"))
    cap_hint = "不限制" if cap_default is None else f"{cap_default:g}"
    cap_raw = ask(f"难度上限（floor，如 6.1；回车 = {cap_hint}）", "")
    if cap_raw:
        cap = None if cap_raw.lower() in ("none", "-") else float(cap_raw)
    else:
        cap = cap_default

    analyzer = data_analyzer.AnalyzeUtil().spawn_analyzer(bmode)
    plan = target_plan.build_plan(bmode, total, accuracy, cap, username=name,
                                  analyzer=analyzer, balance=True,
                                  balance_rounds=opts["balance_rounds"])
    print("\n" + plan.describe())
    if not plan.reachable:
        print(f"  !! 该目标在 {plan.accuracy}% 准确率下不可达，图中展示的是当前能达到的最好状态")

    image = await target_generate.generate_target_image(plan)
    saved(_save(image, "target", f"{_target_output_name(plan)}.png"))


def _target_output_name(plan) -> str:
    """File stem for a target plan image (`target_<user>_<b>B_<total>_<acc>pct[_cap…]`)."""
    def number(value) -> str:
        return format(value.normalize(), "f")

    stem = (f"target_{plan.username}_{plan.bmode}B_"
            f"{number(plan.target_total)}_{number(plan.accuracy)}pct")
    if plan.floor_cap is not None:
        stem += f"_cap{number(plan.floor_cap)}"
    return stem


async def cmd_single(name: str) -> None:
    from djmax_bests import generate
    from djmax_bests.generators.history_generator import song_history_generate
    from djmax_bests.generators.summary_generator.tag_scorelist_generate import tag_scorelist

    while True:
        clear()
        print("\n  单图生成\n")
        print("    [1] Top 100")
        print("    [2] 等级成绩总览（含 SC）")
        print("    [3] 新曲成绩总览")
        print("    [4] 曲包成绩总览")
        print("    [5] Perfect Play 总览")
        print("    [6] 标签推歌进度")
        print("    [7] 单曲成绩轨迹")
        print("    [8] 理论值 Top 100（不需要账号成绩）")
        print("    [0] 返回\n")
        choice = input("请输入序号后回车：").strip()
        if choice in ("", "0"):
            return
        if choice not in "12345678" or len(choice) != 1:
            continue

        bmode = int(ask("按键模式 [4/5/6/8]", "4", ("4", "5", "6", "8")))
        try:
            if choice == "1":
                image = await generate.generate_bests_local(name, bmode)
                path = _save(image, f"best_{name}_{bmode}B.png")
            elif choice == "2":
                level = int(ask("等级 1-15", "15"))
                image = await generate.generate_scorelist_local(name, bmode, False, level)
                _save(image, f"level_{bmode}B", f"scorelist_{bmode}B_{level}.png")
                image = await generate.generate_scorelist_local(name, bmode, True, level)
                path = _save(image, f"level_{bmode}B", f"scorelist_{bmode}B_sc{level}.png")
            elif choice == "3":
                diff = ask("难度 NM/HD/MX/SC", "SC", ("NM", "HD", "MX", "SC"))
                image = await generate.generate_scorelist_new_local(name, bmode, diff)
                path = _save(image, f"level_{bmode}B", f"scorelist_new_{bmode}B{diff}.png")
            elif choice == "4":
                diff = ask("难度 NM/HD/MX/SC", "SC", ("NM", "HD", "MX", "SC"))
                pack = ask("曲包代码（V-ARCHIVE 的 dlcCode，如 DNF）", "RV")
                image = await generate.generate_scorelist_pack_local(name, bmode, diff, pack)
                path = _save(image, f"level_{bmode}B", "dlc", f"scorelist_{pack}_{bmode}B{diff}.png")
            elif choice == "5":
                image = await generate.generate_scorelist_pp_local(name, bmode)
                path = _save(image, f"perfect_{bmode}B.png")
            elif choice == "6":
                tag = ask("标签（Jack/Longjack/Stream/Stair/Trill/Chord/Long/Side/Complex/SV/…）", "Jack")
                level = int(ask("标签难度 1-3", "3"))
                image = tag_scorelist(name, bmode, tag, level)
                path = _save(image, f"tag_{bmode}B", f"{tag}_{level}.png")
            elif choice == "8":
                # Account-independent: only the song database is needed, so this works even
                # before the first score refresh.
                image = await generate.generate_bests_theoretical(bmode)
                path = _save(image, "theoretical", f"theoretical_{bmode}B.png")
            else:
                songid = int(ask("歌曲 ID（songid）", "1"))
                diff = ask("难度 NM/HD/MX/SC", "SC", ("NM", "HD", "MX", "SC"))
                image = await song_history_generate.generate_song_history(name, songid, bmode, diff)
                path = _save(image, "history", "songs", f"SongHistory_{bmode}B{diff}_{songid}.png")
            saved(path)
        except Exception as error:      # a failed render must not take the menu down
            print(f"\n[失败] {type(error).__name__}: {error}")
            print("若提示记录库缺失，请先运行菜单 [1] 刷新成绩。")
        pause()


def _save(image, *parts: str) -> str:
    path = os.path.join(paths.OUTPUT_DIR, *parts)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    image.save(path)
    return path


def _save_under(root: str, image, *parts: str) -> str:
    path = os.path.join(root, *parts)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    image.save(path)
    return path


def _reset_analyzer() -> None:
    """Drop an injected (foreign) frame so the next local task reloads records_db."""
    from djmax_bests.analyzer import data_analyzer
    data_analyzer.AnalyzeUtil.merged_df = None
    data_analyzer.AnalyzeUtil._analyzers.clear()


async def cmd_inspect() -> None:
    """Look at somebody else's account.

    Mirrors the inspect_*.py entry points: records come straight from the API for the requested
    account and stay in memory (fetch_all(write=False) / fetch_one), so the local record store is
    never read or written. Renders land in data/output/inspect/<username>/.
    """
    from djmax_bests import generate
    from djmax_bests.analyzer import data_analyzer, data_fetcher
    from djmax_bests.generators.history_generator import history_generate, song_history_generate
    from djmax_bests.generators.summary_generator import summary_generate
    from djmax_bests.generators.summary_generator.tag_scorelist_generate import tag_scorelist
    from djmax_bests.generators.target_generator import target_generate, target_plan

    name = ask("要查询的 V-ARCHIVE 账号名（区分大小写）")
    root = os.path.join(paths.OUTPUT_DIR, "inspect", name)
    print(f"\n将查询 {name}：成绩只在内存中使用，不会写入本地记录库。")

    async def ensure_song_db() -> None:
        """A fresh install has no cache yet, and the injected frame is merged with songs.json."""
        if not os.path.exists(os.path.join(api_handler.CACHE_PATH, "songs.json")):
            await api_handler.fetch_song_db()

    async def single_mode(bmode: int) -> dict:
        await ensure_song_db()
        texts = {str(bmode): data_fetcher.fetch_one(name, bmode)}
        data_analyzer.AnalyzeUtil.use_varecords(texts)
        return texts

    async def all_modes() -> dict:
        await ensure_song_db()
        texts = data_fetcher.fetch_all(name, write=False)
        data_analyzer.AnalyzeUtil.use_varecords(texts)
        return texts

    try:
        while True:
            clear()
            print(f"\n  查询他人成绩：{name}\n")
            print("    [1] Top 100")
            print("    [2] 等级成绩总览（含 SC）")
            print("    [3] 新曲成绩总览")
            print("    [4] 曲包成绩总览")
            print("    [5] Perfect Play 总览")
            print("    [6] 标签推歌进度")
            print("    [7] 单曲成绩轨迹")
            print("    [8] 总结图")
            print("    [9] 最近 50 局")
            print("    [10] 目标 DJPower 规划")
            print("    [0] 返回\n")
            choice = input("请输入序号后回车：").strip()
            if choice in ("", "0"):
                return
            if choice not in {"1", "2", "3", "4", "5", "6", "7", "8", "9", "10"}:
                continue

            try:
                # Summary and the recent-plays chart span every button mode, so they must not
                # ask for one; everything else renders a single mode.
                bmode = None
                if choice not in ("8", "9"):
                    bmode = int(ask("按键模式 [4/5/6/8]", "4", ("4", "5", "6", "8")))
                if choice == "1":
                    image = await generate.generate_bests(name, bmode)
                    path = _save_under(root, image, f"best_{bmode}B",
                                       f"best_{name}_{bmode}B_{time.strftime('%Y%m%d_%H%M')}.png")
                elif choice == "2":
                    level = int(ask("等级 1-15", "15"))
                    image = await generate.generate_scorelist(name, bmode, False, level)
                    _save_under(root, image, f"level_{bmode}B", f"scorelist_{bmode}B_{level}.png")
                    image = await generate.generate_scorelist(name, bmode, True, level)
                    path = _save_under(root, image, f"level_{bmode}B", f"scorelist_{bmode}B_sc{level}.png")
                elif choice == "3":
                    diff = ask("难度 NM/HD/MX/SC", "SC", ("NM", "HD", "MX", "SC"))
                    image = await generate.generate_scorelist_new(name, bmode, diff)
                    path = _save_under(root, image, f"level_{bmode}B", f"scorelist_new_{bmode}B{diff}.png")
                elif choice == "4":
                    diff = ask("难度 NM/HD/MX/SC", "SC", ("NM", "HD", "MX", "SC"))
                    pack = ask("曲包代码（dlcCode，如 DNF）", "RV")
                    image = await generate.generate_scorelist_pack(name, bmode, diff, pack)
                    path = _save_under(root, image, f"level_{bmode}B", "dlc",
                                       f"scorelist_{pack}_{bmode}B{diff}.png")
                elif choice == "5":
                    image = await generate.generate_scorelist_pp(name, bmode)
                    path = _save_under(root, image, f"perfect_{bmode}B.png")
                elif choice == "6":
                    await single_mode(bmode)
                    tag = ask("标签（Jack/Longjack/Stream/Stair/Trill/Chord/Long/Side/Complex/SV/…）", "Jack")
                    level = int(ask("标签难度 1-3", "3"))
                    image = tag_scorelist(name, bmode, tag, level)
                    path = _save_under(root, image, f"tag_{bmode}B", f"{tag}_{level}.png")
                elif choice == "7":
                    texts = await single_mode(bmode)
                    songid = int(ask("歌曲 ID（songid）", "1"))
                    diff = ask("难度 NM/HD/MX/SC", "SC", ("NM", "HD", "MX", "SC"))
                    image = await song_history_generate.generate_song_history_snapshot(
                        name, texts, songid, bmode, diff)
                    path = _save_under(root, image, "history", "songs",
                                       f"SongHistory_{bmode}B{diff}_{songid}.png")
                elif choice == "8":
                    await all_modes()
                    # another account's summary always uses the stock presentation: settings.ini
                    # describes your own card, not theirs
                    summary, modecards = summary_generate.generate_summary(name)
                    _save_under(root, summary, "summary.png")
                    for button, card in modecards.items():
                        _save_under(root, card, f"summary_{button}B.png")
                    path = os.path.join(root, "summary.png")
                elif choice == "9":
                    await ensure_song_db()
                    texts = data_fetcher.fetch_all(name, write=False)
                    recent = ask("范围：1 = 最近 50 局，2 = 最近一天", "1", ("1", "2")) == "1"
                    image = await history_generate.generate_history_snapshot(name, texts, recent)
                    stamp = time.strftime("%Y%m%d_%H%M" if recent else "%Y%m%d")
                    filename = f"History_R50_{stamp}.png" if recent else f"History_{stamp}.png"
                    path = _save_under(root, image, "history", filename)
                else:
                    texts = await single_mode(bmode)
                    opts = settings.target_options()
                    cap_default = opts["floor_cap"]
                    total = float(ask("目标总分", "6200"))
                    accuracy = float(ask("预计准确率", "99.0"))
                    cap_hint = "不限制" if cap_default is None else f"{cap_default:g}"
                    cap_raw = ask(f"难度上限（floor，如 6.1；回车 = {cap_hint}）", "")
                    if cap_raw:
                        cap = None if cap_raw.lower() in ("none", "-") else float(cap_raw)
                    else:
                        cap = cap_default
                    analyzer = data_analyzer.AnalyzeUtil().spawn_analyzer(bmode)
                    plan = target_plan.build_plan(bmode, total, accuracy, cap, username=name,
                                                  analyzer=analyzer, balance=True,
                                                  balance_rounds=opts["balance_rounds"])
                    print("\n" + plan.describe())
                    image = await target_generate.generate_target_image(plan)
                    path = _save_under(root, image, "target",
                                       f"target_{name}_{bmode}B_{total:g}_{accuracy:g}pct.png")
                saved(path)
            except Exception as error:
                print(f"\n[失败] {type(error).__name__}: {error}")
            pause()
    finally:
        # The analyzers were pointed at the inspected account; drop that frame so a local task
        # afterwards reads records_db again instead of silently reusing somebody else's data.
        _reset_analyzer()


# --------------------------------------------------------------------------------------
# menu
# --------------------------------------------------------------------------------------
def print_menu(name: str) -> None:
    clear()
    print()
    print("  " + "=" * 58)
    print("                  DJMAX 成绩图生成器v1.0.0")
    print(f"                  当前账号：{name}")
    print("  " + "=" * 58)
    print()
    print("    [1] 刷新成绩        联网下载，首次使用或出了新成绩时运行")
    print("    [2] 生成全部图片    离线，约 200 张，耗时较长")
    print("    [3] 生成总结图      总览 + 4 张模式卡")
    print("    [4] 生成游玩历史    最近一次刷新以来的成绩变化")
    print("    [5] 目标 DJPower    规划达到目标总分需要打哪些谱面")
    print("    [6] 单图生成        Top 100 / 等级 / 新曲 / 曲包 / PP / 标签")
    print()
    print("    [7] 打开 output 目录")
    print("    [8] 修改账号")
    print("    [9] 查询他人成绩    只读API响应，不写入本地记录库")
    print("    [0] 退出")
    print()


async def menu() -> int:
    name = read_account()
    while True:
        print_menu(name)
        try:
            choice = input("请输入序号后回车：").strip()
        except EOFError:
            return 0
        if choice in ("", "0"):
            return 0
        try:
            if choice == "1":
                await cmd_refresh(name)
            elif choice == "2":
                await cmd_all(name)
            elif choice == "3":
                cmd_summary(name)
            elif choice == "4":
                await cmd_history(name)
            elif choice == "5":
                await cmd_target(name)
            elif choice == "6":
                await cmd_single(name)
                continue
            elif choice == "7":
                if os.path.isdir(paths.OUTPUT_DIR):
                    os.startfile(paths.OUTPUT_DIR)      # noqa: S606 - Windows shell open
                else:
                    print("\noutput 目录还不存在，先出一次图吧。")
            elif choice == "8":
                name = change_account(name)
            elif choice == "9":
                await cmd_inspect()
                continue
            else:
                continue
        except KeyboardInterrupt:
            raise
        except Exception as error:
            print(f"\n[失败] {type(error).__name__}: {error}")
            print("若提示记录库缺失，请先运行菜单 [1] 刷新成绩。")
        if choice != "6":
            pause()
        name = read_account()


def change_account(current: str) -> str:
    print(f"\n当前账号：{current}")
    new_name = input("输入新的 V-ARCHIVE 账号名（直接回车取消）：").strip()
    if not new_name:
        return current
    write_account(new_name)
    print(f"\n[完成] 已切换为 {new_name}。")
    print("注意：本地记录库属于旧账号，下次刷新会整体重写。")
    return new_name


async def main() -> None:
    set_title()
    if COPIED:
        print("首次运行：已放置占位曲绘，其余曲绘会在刷新成绩时下载。")
    await menu()
    if not api_handler.client.is_closed:
        await api_handler.aclose()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n已取消。")
