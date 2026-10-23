"""Build the accuracy -> djpower-ratio lookup table used by the target generator.

The game's djpower ratio is a pure function of the *displayed* accuracy (two decimals): every
cached record with the same accuracy yields the same djpower / maxDjpower ratio, up to the
4th-decimal rounding of the stored djpower (measured spread inside one accuracy: <= 1.3e-05).
That makes the real curve recoverable from the stored archive records, which matters because the fitted
`djpower_calc_opt()` in analyzer/data_analyzer.py deviates from it by up to ~0.0056 in
ratio, i.e. up to ~56 points on the 10000-point DJPower scale -- enough to flip a "reachable or
not" verdict.

Output: accuracy_ratio.csv beside this module. It deliberately does not live under
djmax_bests/cache, so api_handler.remove_cache() never deletes it (same policy as
analyzer's hand-maintained djmax_songs_tags.csv).

Usage:
    python build_accuracy_table.py                      # rebuild from the default record store
    python build_accuracy_table.py --source <file.json> # from another full_varecord.json
    python build_accuracy_table.py --print              # also dump a few sample rows
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from decimal import Decimal
from statistics import fmean

if __package__ in (None, ""):  # allow `python build_accuracy_table.py` from anywhere
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))))

from djmax_bests import api_handler
from djmax_bests.analyzer.data_analyzer import djpower_calc_opt

TABLE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "accuracy_ratio.csv")

ACCURACY_MIN = 90.00
ACCURACY_MAX = 100.00
ACCURACY_STEP = 0.01
DECIMALS = 9


def fit_ratio(accuracy: float) -> float:
    """The fitted curve (fallback), evaluated at high resolution to avoid quantisation."""
    return float(djpower_calc_opt(accuracy, 1e7)) / 1e7


def measured_ratios(path: str) -> dict[float, list[float]]:
    """accuracy -> list of djpower / maxDjpower observed for that accuracy."""
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    table: dict[float, list[float]] = {}
    for mode_text in raw.values():
        for record in (json.loads(mode_text).get("records") or []):
            score, djpower, max_djpower = record.get("score"), record.get("djpower"), record.get("maxDjpower")
            if score is None or not djpower or not max_djpower:
                continue
            table.setdefault(round(float(score), 2), []).append(float(djpower) / float(max_djpower))
    return table


def build(source: str) -> list[tuple[float, float, str]]:
    """The full grid: (accuracy, ratio, source) with source in {measured, interp, fit}."""
    measured = {accuracy: fmean(values) for accuracy, values in measured_ratios(source).items()}
    anchors = sorted(measured)

    count = round((ACCURACY_MAX - ACCURACY_MIN) / ACCURACY_STEP) + 1
    rows: list[tuple[float, float, str]] = []
    for index in range(count):
        accuracy = round(ACCURACY_MIN + index * ACCURACY_STEP, 2)
        if accuracy in measured:
            rows.append((accuracy, measured[accuracy], "measured"))
            continue
        lower = [a for a in anchors if a < accuracy]
        upper = [a for a in anchors if a > accuracy]
        if lower and upper and upper[0] - lower[-1] > 0:
            low, high = lower[-1], upper[0]
            weight = (accuracy - low) / (high - low)
            rows.append((accuracy, measured[low] + (measured[high] - measured[low]) * weight, "interp"))
        else:
            rows.append((accuracy, fit_ratio(accuracy), "fit"))

    # The real curve is monotone in accuracy; running max removes the 4th-decimal noise dips.
    peak = 0.0
    for index, (accuracy, ratio, source) in enumerate(rows):
        peak = max(peak, ratio)
        rows[index] = (accuracy, peak, source)
    return rows


def write(rows: list[tuple[float, float, str]], source: str, out: str) -> None:
    measured_rows = [(a, r) for a, r, s in rows if s == "measured"]
    worst = max(((abs(r - fit_ratio(a)), a, r) for a, r in measured_rows), default=(0.0, 0.0, 0.0))
    spread = 0.0
    raw = measured_ratios(source)
    for values in raw.values():
        if len(values) > 1:
            spread = max(spread, max(values) - min(values))

    header = [
        "accuracy -> djpower ratio lookup table (ratio = djpower / maxDjpower).",
        f"source cache: {source}",
        f"measured accuracies: {len(raw)} ({len(measured_rows)} grid points), "
        f"max spread inside one accuracy: {spread:.2e}",
        f"generated: {__import__('time').strftime('%Y-%m-%d %H:%M:%S')}",
        f"worst |measured - fit|: {worst[0]:.6f} at accuracy {worst[1]:.2f} "
        f"(~{worst[0] * 10000:.1f} points on the 10000 scale)",
        "columns: accuracy, ratio, source (measured | interp | fit)",
    ]
    with open(out, "w", encoding="utf-8", newline="") as f:
        for line in header:
            f.write(f"# {line}\n")
        writer = csv.writer(f)
        writer.writerow(["accuracy", "ratio", "source"])
        for accuracy, ratio, kind in rows:
            writer.writerow([f"{accuracy:.2f}", f"{ratio:.{DECIMALS}f}", kind])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rebuild accuracy_ratio.csv from the stored records.")
    parser.add_argument("--source", default=os.path.join(api_handler.RECORDS_PATH, "full_varecord.json"),
                        help="full_varecord.json to read (default: the record store api_handler uses)")
    parser.add_argument("--out", default=TABLE_PATH, help="output CSV (default: beside this module)")
    parser.add_argument("--print", dest="show", action="store_true", help="print sample rows")
    args = parser.parse_args(argv)

    if not os.path.exists(args.source):
        parser.error(f"{args.source} does not exist; run refresh.py <username> first")

    rows = build(args.source)
    write(rows, args.source, args.out)
    kinds = {kind: sum(1 for _, _, k in rows if k == kind) for kind in ("measured", "interp", "fit")}
    print(f"Wrote {args.out} ({len(rows)} rows: {kinds})")
    if args.show:
        for accuracy, ratio, kind in rows[::50]:
            print(f"  {accuracy:6.2f} -> {ratio:.{DECIMALS}f}  ({kind})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
