# DJMAX Score Image Generator

A library that renders DJMAX RESPECT V scores from [V-ARCHIVE](https://v-archive.net/) as images.

> Installation, menu and configuration of the Windows single-file exe live in
> [README-EXE.md](README-EXE.md). This document describes the image-generation modules.
> [简体中文](README_zh.md)

## Environment

- Python 3.10+ (the bundled `.venv` uses CPython 3.14.6);
- dependencies in `requirements.txt`:

```powershell
uv venv .venv --python 3.14
uv pip install -r requirements.txt
```

Every generator is `async` and returns a `PIL.Image.Image`; saving is up to the caller.

## Fonts

- The body fonts (`Respect_bd.ttf` / `Respect_rg.ttf` / `Respect_lt.ttf`) ship with the repo — nothing to install;
- Only the skill radar, `tools.plot_tags_score_radar()`, asks for **Sarasa Mono HC SemiBold**, which is
  **not** distributed with this repo or the exe and has to be installed by hand:
  - open the [be5invis/Sarasa-Gothic](https://github.com/be5invis/Sarasa-Gothic) releases and download
    `SarasaMonoHC-TTF-<version>.7z` (currently `SarasaMonoHC-TTF-1.0.42.7z`, ~64 MB);
  - right-click `SarasaMonoHC-SemiBold.ttf` → *Install* (or *Install for all users*), then restart the app;
- Used by the summary sheet from `summary_generate.generate_summary()`, and the single-chart
  progression images from `song_history_generate.generate_song_history()` / `generate_song_history_snapshot()`;
- matplotlib registers the weight as part of the family name, hence the exact string `Sarasa Mono HC SemiBold`;
- Nothing crashes without it, but each render spams `findfont: Generic family 'sans-serif' not found ...`
  and the radar labels fall back to DejaVu Sans, so widths and line breaks drift from the design;
- If the images stay unchanged after installing, delete the font cache: `.matplotlib/` in the repo root,
  `data/.matplotlib/` for the exe.

Verify that the font is registered (`Sarasa Mono HC SemiBold` must show up):

```powershell
python -c "import matplotlib.font_manager as fm; print([f.name for f in fm.fontManager.ttflist if 'Sarasa Mono HC' in f.name])"
```

---

## Top 100 generators

- `generate.generate_bests(username, bmode)`
    - Render an account's Top 100 online.
    - `username`: V-ARCHIVE account name (case-sensitive).
    - `bmode`: button mode, 4 / 5 / 6 / 8.
    - Queries the `djpower` list (70 Basic + 30 New).

- `generate.generate_bests_theoretical(bmode)`
    - Render the current version's theoretical (maximum DJPower) Top 100.
    - `bmode`: button mode, 4 / 5 / 6 / 8.
    - Needs only the song database (`songs.json`), no account scores; titled `Max DJPower`.

## Scorelist generators

- `generate.generate_scorelist(username, bmode, is_sc, level)`
    - Full scorelist for one level.
    - `is_sc`: `True` when the level is an SC level.
    - `level`: 1–15.

- `generate.generate_scorelist_new(username, bmode, diff)`
    - Scorelist of the current version's new songs.
    - `diff`: `NM` / `HD` / `MX` / `SC`.

- `generate.generate_scorelist_pack(username, bmode, diff, pack)`
    - Scorelist of one pack.
    - `pack`: V-ARCHIVE `dlcCode` (e.g. `DNF`, `VE`, `PLI4`); validate it yourself —
      `api_handler.fetch_dlc_list()` returns the full list.

- `generate.generate_scorelist_pp(username, bmode)`
    - Perfect Play (100%) scorelist.

## Local record-store generators

The functions below produce the same images but read from the local store
(`records/records_db.parquet`) and consume no requests. Each one first calls
`data_fetcher.ensure_db_available(username)`: a no-op when the store already serves the account,
an offline rebuild when only the song database or tag table moved, and a full four-mode download
otherwise. Readers refuse a store belonging to another account.

- `generate.generate_bests_local(username, bmode)`
- `generate.generate_scorelist_local(username, bmode, is_sc, level)`
- `generate.generate_scorelist_new_local(username, bmode, diff)`
- `generate.generate_scorelist_pack_local(username, bmode, diff, pack)`
- `generate.generate_scorelist_pp_local(username, bmode)`
- `generate.generate_all_local(username)`
    - Renders every single chart (4 modes × 15 levels × SC/non-SC, new songs, Perfect Play,
      Top 100 and theoretical Top 100) into `<project>/output/`; returns `None`.
    - Same file naming as the exe's `[2] Generate everything`.

Parameters are identical to their online counterparts.

The store has two layers: `records/full_varecord.json` keeps the raw API responses for all four
modes, and `records/records_db.parquet` is the derived, directly renderable layer (song database,
tag table and `max_djpower` merged in). `records/db_meta.json` records the account and build
version. `records/` is not in the repository; generate it once with
`refresh_records(username)` / `ensure_db_available(username)`.

## Summary generator

- `summary_generate.generate_summary(username, nickname=None, photo=None, prefer_button=[4, 5, 6, 8], info='')`
    - Renders the 2200 px summary sheet plus 4 mode cards.
    - `username`: account the store belongs to (also shown on the cover).
    - `nickname`: overrides the displayed name when set.
    - `photo`: jacket songid used as the avatar; `None` or out of range = random.
    - `prefer_button`: button modes to highlight.
    - `info`: signature text.
    - Returns `(summary, modecards)` where `modecards` is `{4: Image, 5: Image, 6: Image, 8: Image}`.
    - The skill radar on the right is drawn by matplotlib; see “Fonts” above (Sarasa Mono HC SemiBold).

- `tag_scorelist_generate.tag_scorelist(username, bmode, tag, level)`
    - Renders the progress of one tag (synchronous, returns `Image`).
    - `tag`: `Jack`, `Longjack`, `Stream` (or `FX`), `Stair`, `Trill`, `Chord`, `Long`, `Side`,
      `Complex`, `SV`, `DoubleStairs`, `6B Stair`, `6B Basic`, `Read`, `Spike`.
    - `level`: tag difficulty 1–3 (drawn as I / II / III).

Both read the local store through `AnalyzeUtil`; for another account inject its records with
`AnalyzeUtil.use_varecords(...)` first (see “Data layer”).

## Play-history generators

- `history_generate.generate_history(username, recent100=True, date=None, target_date=None)`
    - Renders the play-history chart from the local event log.
    - `recent100=True`: latest n plays(adjust MAX_ROWS); `False`: the day selected by `date`.
    - `date=None` means “the latest day with records”; a `datetime.date` traces back from it.
    - Pass a list as `target_date` to receive the day actually charted (useful for file names).
    - Rows carry the chart's previous best and score/DJPower gains; mode blocks show daily total
      movement.

- `history_generate.generate_history_snapshot(username, texts, recent100=True)`
    - Renders straight from a `{bmode: raw response text}` snapshot (inspect path; never reads
      the local store).
    - A single snapshot cannot know beaten scores, so it shows results only, without deltas.

Readers for custom rendering:

- `history.replay_view(username)` — returns `(events, totals)`: event rows (with each chart's
  previous best and gains) plus the mode total after every play; this is what the history chart
  reads.
- `history.chart_progression(username, songid, button, pattern)` — one chart's full trajectory.
- `history.load_play_events(username=None)` — the bare event log.
- `history.update_history(username, texts)` / `history.verify_history()` — write and self-check.

## Single-chart history generators

- `song_history_generate.generate_song_history(username, songid, button, pattern)`
    - Renders one chart's full score trajectory from the local store; the radar in the top right
      needs Sarasa Mono HC SemiBold as well.

- `song_history_generate.generate_song_history_snapshot(username, texts, songid, button, pattern)`
    - Same, from a `{bmode: raw response text}` snapshot (inspect path).

## Target-DJPower generators

- `target_plan.build_plan(bmode, target_total, accuracy, floor_cap=None, *, username='Max DJPower', analyzer=None, balance=True, balance_rounds=7)`
    - Works out which charts to play to reach a target total; returns a `TargetPlan`.
    - `target_total`: target DJPower total.
    - `accuracy`: expected accuracy as a percentage number (e.g. `99.2`).
    - `floor_cap`: optional difficulty cap in floor units; `None` = no cap.
    - `username`: owner of the plan (used in names / images).
    - `analyzer`: a `RecordAnalyzer`; `None` builds one from the store.
    - `balance` / `balance_rounds`: search the basic/new split and how many rounds to try.
    - The plan exposes `reachable`, `achieved_total`, `current_total`, `min_accuracy`, `tasks`,
      `basic` / `new`; `plan.describe()` returns a readable summary.

- `target_generate.generate_target_image(plan)`
    - Renders a `TargetPlan` in the Top 100 layout: gold `NEW` = play from scratch, cyan `UP` =
      improve; the header shows target, achieved total, current value and minimum accuracy.

## Data layer

- `data_fetcher.ensure_db_available(username)`
    - Makes the store serve `username`: no-op when current, offline rebuild when only the song
      database or tag table changed, full four-mode download otherwise.

- `data_fetcher.refresh_records(username)`
    - Force-download all four modes and rebuild the store (what the exe's `[1]` uses).

- `data_converter.load_records_db()`
    - The merged DataFrame (with `tags` / `tags_score`); rebuilds offline when stale.

- `data_analyzer.AnalyzeUtil`
    - `spawn_analyzer(bmode)`: read-only analyzer for one button mode.
    - `spawn_analyzer_full()`: analyzer spanning all four modes.
    - `use_varecords({bmode: raw response text})`: inject another account's records; reset it
      afterwards (`AnalyzeUtil.merged_df = None`) so local charts read the store again.

## Example

```python
import asyncio

from djmax_bests import api_handler, generate
from djmax_bests.generators.summary_generator import summary_generate


async def main():
    bests = await generate.generate_bests_local("YourName", 6)
    bests.save("best_6B.png")

    theoretical = await generate.generate_bests_theoretical(4)
    theoretical.save("theoretical_4B.png")

    summary, modecards = summary_generate.generate_summary("YourName", info="steam xxxx")
    summary.save("summary.png")

    await api_handler.aclose()


asyncio.run(main())
```

## Building the exe

See the “构建” section of [README-EXE.md](README-EXE.md).

## License

MIT, see [LICENSE](LICENSE). Game data and jackets belong to DJMAX / NEOWIZ and V-ARCHIVE.
