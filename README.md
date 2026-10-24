# DJMAX Score Image Generator

This library use [V-ARCHIVE](https://v-archive.net/) as data source.

> **Repository shape**: only the Windows single-file exe is built now (`app.py` +
> `build_exe.ps1`, output in `dist-exe/`). The old script entry points were removed and their
> features moved into the exe menu — see [README-EXE.md](README-EXE.md). The `generate.*`
> library API below is still available.

## Top 100 Generators

- `generate.generate_bests(username, bmode)`
    - Generate the user's top 100 chart.
    - `username`: the user's V-ARCHIVE account username.
    - `bmode`: button mode, can be one of 4, 5, 6, 8.

- `generate.generate_bests_theoretical(bmode)`
    - Generate the theoretical (max djpower) top 100 chart of the current version.
    - `bmode`: button mode, can be one of 4, 5, 6, 8.

## Scorelist Generators

- `generate.generate_scorelist(username, bmode, is_sc, level)`
    - Generate the user's score overview of a certain level.
    - `username`: the user's V-ARCHIVE account username.
    - `bmode`: button mode, can be one of 4, 5, 6, 8.
    - `is_sc`: (boolean) indicate whether the `level` is in SC levels.
    - `level`: the level to generate, 1-15.

- `generate.generate_scorelist_new(username, bmode, diff)`
    - Generate the user's score overview of new songs in current version.
    - `username`: the user's V-ARCHIVE account username.
    - `bmode`: button mode, can be one of 4, 5, 6, 8.
    - `diff`: difficulty, can be one of NM, HD, MX, SC.

- `generate.generate_scorelist_pack(username, bmode, diff, pack)`
    - Generate the user's score overview of songs in a certain pack.
    - `username`: the user's V-ARCHIVE account username.
    - `bmode`: button mode, can be one of 4, 5, 6, 8.
    - `diff`: difficulty, can be one of NM, HD, MX, SC.
    - `pack`: the pack to generate, as in V-ARCHIVE's `dlcCode`.
    - **NOTE:** You should validate the `pack` param before passing it in, the full dlc list can be retrieved with `api_handler.fetch_dlc_list()`.

- `generate.generate_scorelist_pp(username, bmode)`
    - Generate the user's perfect-played score overview.
    - `username`: the user's V-ARCHIVE account username.
    - `bmode`: button mode, can be one of 4, 5, 6, 8.

## Local Cache Generators

The generators below produce the same charts, but read the archive from the local record store in
`records/` instead of the V-ARCHIVE API, so a repeated run spends no requests. The store has two
layers: `full_varecord.json` holds the raw API responses, one entry per button mode, and
`records_db.parquet` is the merged, render-ready form built from them — the hand-maintained tag
table (`analyzer/djmax_songs_tags.csv`) is already joined and its `tags_score` already computed
inside it, so a read is a plain parquet read (`db_meta.json` records which account it holds and
which schema it was built with). `data_fetcher.ensure_db_available(username)` — called by every
local generator — is the only network-touching step: it is a no-op while the store already serves
`username`, rebuilds the parquet offline when only the song database or the tag table moved under
it, and otherwise downloads all four modes. The reading and converting itself
(`data_converter.load_records_db`, `fetch_bests`, `fetch_scorelist*`) is pure local file work and
refuses a store that holds another account rather than silently using it. The song database, the
dlc list and the djpower conversion factor come from the cache (`djmax_bests/cache`), which
`api_handler.remove_cache()` may clear at any time — the record store sits outside it and
survives that.

- `generate.generate_bests_local(username, bmode)`
- `generate.generate_scorelist_local(username, bmode, is_sc, level)`
- `generate.generate_scorelist_new_local(username, bmode, diff)`
- `generate.generate_scorelist_pack_local(username, bmode, diff, pack)`
- `generate.generate_scorelist_pp_local(username, bmode)`

Parameters are the same as their online counterparts.

Fill the record store once with `python refresh.py` — its `username` is the account everything
renders — before the first run; the online
generators above (and `api_handler.fetch_song_db()`) also cache whatever they fetch.
`records/` is **not** in the repository: it holds one account's records, so every clone regenerates it
from its own account with that same command (the directory is created on the first write).
`generate.generate_bests_theoretical` has no local variant: it only needs the song database,
which `api_handler` reads from the cached `songs.json`.

## Utilities

`prefetch_covers.py`: cache all missing covers.

`refresh.py`: the manual refreshment method, and the one place the account is configured. The
`username` global at its top is the **primary account**: the refresh, the records_db build and
`db_meta.json` are keyed to it, and every entry script (`runrun.py`, `all.py`, `summary.py`,
`target.py`) imports it from there and renders that account. Those scripts do not refresh on
their own any more — run `python refresh.py` manually whenever the records should be updated.
The script refreshes the two caches `api_handler` cannot refresh
by itself: the djpower conversion factor (`maxpower_<bmode>.txt`, reused from the cache forever once it
exists) and the archive records of that account (`records/`, the record store: `full_varecord.json`
holding all four button modes plus the `records_db.parquet` built from them). It then calls the
cache-aware methods, so a cold `songs.json` / `dlcs.json` is
filled as well (before the records, so the records_db rebuild merges in the fresh song database).
Jacket covers are handled by `prefetch_covers.py`.
There is no partial refresh: `refresh.py` always rewrites the whole raw layer through
`data_fetcher.fetch_all()`, so `full_varecord.json` has a single writer and can never hold entries
from two accounts.
The rebuild json-loads all four keys, so a missing or empty entry breaks it — that is why the raw
layer is replaced as a whole rather than one mode at a time. An entry that is unreadable, or that
carries no account marker, makes the store unservable: `records_db.parquet` refuses to be rebuilt
from it and `db_meta.json` is left as it was, so the next local run fetches all four modes for the
account it was asked for.

### Play history (`records/history/`)

V-ARCHIVE keeps only each chart's current best record, so a superseded score is gone from the API
the moment it is beaten. `analyzer/history.py` accumulates what can still be accumulated, and every
refresh feeds it automatically (`data_fetcher` folds the freshly fetched state into the history
before rebuilding `records_db.parquet`):

- `play_events.parquet` — an append-only log of play events, one row per play. The first refresh
  seeds every current best at its own `updatedAt` (the archive's play timestamp), so the history
  starts with real depth; every later refresh diffs the new raw records against the last snapshot
  and appends one event per chart whose score rose or that appeared. Events fire only on
  score/max-combo changes, so a game patch that recomputes djpower never fakes a play. Events are
  keyed per account — switching the primary account never fakes events.
- `snapshots/` — the raw layer archived on every content change (gzip, kept forever) so the event
  log can be re-derived if it is ever corrupted.

The finer the refresh cadence, the finer the history: plays between two refreshes survive
only as their final best, so refresh after a play session.
**Deleting `records/history/` loses every superseded score permanently** — the API cannot replay
them. 

Read side (what a renderer would consume):

- `history.recent_plays(username, n=100)` — the latest events across all button modes, newest
  first, each with the chart's previous best and the score/djpower deltas against it.
- `history.chart_progression(username, songid, button, pattern)` — one chart's full score trajectory.
- `history.totals_over_time(username)` — per-mode total djpower after every play, replayed from the
  events with the same top-70/30 + convert-constant formula (and 10000 cap) as the modecards.
- `history.load_play_events(username)` — the bare log, for anything else.

`inspect_history.py` renders the same chart for another account: it fetches all four button modes
of the `username` set below its header (a cross-mode top 100 needs every mode) and keeps them in
memory, so the local record store is never read or written. A single snapshot cannot know
superseded scores, so that chart draws results only — no score/djpower increments — and final
mode totals without a daily gain. Output: `output/inspect/<username>/History_<date>.png`.

The read APIs also reconcile with the current store: bests that sit in `records/` but not yet in
the log (e.g. a refresh that was interrupted) still show up, and the next refresh's snapshot diff
closes the gap for good. An older raw snapshot you happen to have (e.g. a saved
`full_varecord_<date>.json`) can be backfilled into the log: call
`history.update_history(username, older_texts)` once — seeding is absorbed by the dedup key, so
only that snapshot's superseded bests are added (set the newest snapshot in
`records/history/snapshots/` aside for the call, then run `update_history` with the current state
to restore the snapshot timeline).

`runrun.py`: scratch entry point for a single chart. Edit the variables at the top (`bmode`,
`levels`, `difficult`, `dlc`, `tag_name`, `tag_level`), then pick the task on the
`await ...()` line inside `main()` — `best()`, `theoretical()`, `level()`, `new()`, `perfect()`,
`pack()` or `tag()`. It renders the primary account (the `username` in refresh.py).

The `tag()` task charts how far one account has cleared the songs that carry a given tag, and writes
the result to `output/tag_<bmode>B/<tag_name>_<tag_level>.png`. It takes:

- `username`: the V-ARCHIVE account to look up (the primary account, set in refresh.py).
- `bmode`: button mode, one of 4, 5, 6, 8.
- `tag_name`: the tag to look up — `Jack`, `Longjack`, `Stream` (or `FX`), `Stair`, `Trill`, `Chord`,
  `Long`, `Side`, `Complex`, `SV`, `DoubleStairs`, `6B Stair`, `6B Basic`, `Read` or `Spike`.
- `tag_level`: the tag's difficulty, `1`-`3` (drawn as I / II / III in the header).

`all.py`: render every chart for one account in one go (4 button modes × levels 1-15 × both SC
and non-SC, plus new songs, perfect plays, bests and theoretical bests).

`summary.py`: render the summary chart.

The entry scripts (`runrun.py`, `all.py`, `summary.py`, `target.py`) render entirely from the local
record store and spend no requests on it — refresh manually with `python refresh.py` first whenever
the store should be updated. If the store holds a different account than the primary account a
generator was asked for, that generator fetches all four modes once (`data_fetcher.ensure_db_available`)
and rebuilds the store, so switching the primary account costs either a manual refresh or one
automatic fetch on the next render.
Because `AnalyzeUtil` reads the record store, everything built on it (`tag()`, the target plan, the
summary, the scorelist renderers used by `level()` / `pack()` / `pp()`) sees the modes that store
holds. The store is always written wholesale by `refresh.py`, so its four entries belong to one
account; a store left over from another account is refused, not merged.
Output goes under `output/` beside the script, creating every target directory on demand. 

# Troubleshooting

- Wrong djpower / tier values, missing new songs, or anything else looks outdated
    - The cached conversion factor or song database is stale. Run `refresh.py` for the
      conversion factor and the archive records; `api_handler.remove_cache()` clears everything
      under `djmax_bests/cache` (maxpower, `songs.json`, `dlcs.json`) and the
      next run downloads what it needs. The conversion factor is never re-fetched on its own once
      cached, so a new season needs `refresh.py` (or a manual delete of the `maxpower_*.txt`).
      The record store in `records/` is outside the cache and survives a wipe; deleting
      `records/records_db.parquet` alone is also safe — the next run rebuilds it offline.

- A chart shows another account's data
    - The record store belongs to one account, and `db_meta.json` records which. A local generator
      asked for a different account refuses the stored records and fetches all four modes for the
      account it was asked for; a direct read reports
      `records_db holds 'SomeoneElse' account, not 'You'`. Run `python refresh.py` once to rewrite
      the store for the account you are working on (the `username` set in refresh.py).
      `api_handler.remove_cache()` clears the whole cache.

- `records_db holds no account, not 'You'` / `records_db cannot be rebuilt`
    - `records/records_db.parquet` is the derived, render-ready form of the raw records. It is
      rebuilt offline whenever it is missing, was built by an older version of the code, or is
      older than its sources (`full_varecord.json`, `songs.json`, `analyzer/djmax_songs_tags.csv`)
      — no requests involved. This error means the raw layer is missing entries too, so there is
      nothing to rebuild from: run `python refresh.py` once.
