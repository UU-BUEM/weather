#!/usr/bin/env python3
"""Enumerate EVERY message of one variable in a monthly ERA5-Land GRIB.

Settles, once and for all:

  * exactly how many hourly timestamps a monthly file contains
    (744? 745? something else),
  * what the FIRST and LAST valid_time are,
  * which forecast steps exist on the first and last dataDate,
  * whether every timestamp has a de-accumulation predecessor
    (i.e. whether it can be converted to an hourly increment).

Reads with raw eccodes (fast, low memory, no cfgrib).

Usage::

    python enumerate_month.py PATH.grib --lat 52.0 --lon 5.0
    python enumerate_month.py PATH.grib --lat 69.0 --lon 25.0   # Arctic
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from collections import defaultdict
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("grib")
    ap.add_argument("--lat", type=float, default=52.0)
    ap.add_argument("--lon", type=float, default=5.0)
    ap.add_argument("--var", default="ssrd")
    ap.add_argument(
        "--show", type=int, default=6,
        help="How many leading/trailing rows to print",
    )
    args = ap.parse_args()

    grib = Path(args.grib)
    if not grib.exists():
        sys.exit(f"not found: {grib}")

    import eccodes  # type: ignore

    lat = args.lat
    lon = args.lon % 360.0

    # (dataDate, step) -> value ; and valid_time -> value
    per_date: dict[int, list[int]] = defaultdict(list)
    records: list[tuple[dt.datetime, int, int, float]] = []

    print(f"File: {grib.name}")
    print(f"Variable: {args.var}   cell lat={args.lat} lon={args.lon}")
    print("Scanning ALL messages (this reads the whole file once)...\n")

    with open(grib, "rb") as f:
        while True:
            gid = eccodes.codes_grib_new_from_file(f)
            if gid is None:
                break
            try:
                if eccodes.codes_get(gid, "shortName") != args.var:
                    continue
                date = int(eccodes.codes_get(gid, "dataDate"))
                tm = int(eccodes.codes_get(gid, "dataTime"))
                step = int(eccodes.codes_get(gid, "step"))
                try:
                    val = eccodes.codes_grib_find_nearest(
                        gid, lat, lon
                    )[0].value
                except Exception:  # noqa: BLE001
                    val = float("nan")
                base = dt.datetime.strptime(str(date), "%Y%m%d") + \
                    dt.timedelta(hours=tm // 100)
                vt = base + dt.timedelta(hours=step)
                per_date[date].append(step)
                records.append((vt, date, step, val))
            finally:
                eccodes.codes_release(gid)

    if not records:
        sys.exit(f"No '{args.var}' messages found.")

    records.sort(key=lambda r: r[0])

    print("=" * 70)
    print("TIMESTAMP SPAN")
    print("=" * 70)
    print(f"  total {args.var} messages : {len(records)}")
    print(f"  first valid_time        : {records[0][0]}")
    print(f"  last  valid_time        : {records[-1][0]}")
    span_h = int(
        (records[-1][0] - records[0][0]).total_seconds() // 3600
    ) + 1
    print(f"  span (inclusive hours)  : {span_h}")
    uniq = len({r[0] for r in records})
    print(f"  unique timestamps       : {uniq}")
    if uniq != len(records):
        print("  !! duplicate timestamps present")
    print()

    print("=" * 70)
    print("FORECAST DAYS (dataDate -> steps present)")
    print("=" * 70)
    dates = sorted(per_date)
    truncated = len(dates) > 4
    shown = dates[:2] + dates[-2:] if truncated else dates

    def _print_date(d: int) -> None:
        steps = sorted(per_date[d])
        compact = (
            f"{steps[0]}..{steps[-1]}"
            if steps == list(range(steps[0], steps[-1] + 1))
            else str(steps)
        )
        print(f"  {d}: {len(steps):>2d} step(s)  [{compact}]")

    for i, d in enumerate(shown):
        if truncated and i == 2:
            print("  ...")
        _print_date(d)
    print()

    print("=" * 70)
    print(f"FIRST {args.show} AND LAST {args.show} TIMESTAMPS")
    print("=" * 70)
    print(f"  {'valid_time':<20s} {'dataDate':>9s} {'step':>5s} "
          f"{'value (J/m2)':>15s} {'deaccum?':>9s}")

    # A record can be de-accumulated iff (dataDate, step-1) exists,
    # OR it is step 1 (which keeps its own value: the accumulation reset).
    have = {(r[1], r[2]) for r in records}

    def deaccum_ok(date: int, step: int) -> str:
        if step == 1:
            return "yes(res)"      # step 1 = reset, value is the increment
        return "yes" if (date, step - 1) in have else "NO"

    for vt, d, s, v in records[: args.show]:
        print(f"  {str(vt):<20s} {d:>9d} {s:>5d} {v:>15.1f} "
              f"{deaccum_ok(d, s):>9s}")
    print(f"  {'...':<20s}")
    for vt, d, s, v in records[-args.show:]:
        print(f"  {str(vt):<20s} {d:>9d} {s:>5d} {v:>15.1f} "
              f"{deaccum_ok(d, s):>9s}")
    print()

    # Which timestamps CANNOT be de-accumulated?
    bad = [
        (vt, d, s) for vt, d, s, _ in records
        if deaccum_ok(d, s) == "NO"
    ]
    print("=" * 70)
    print("VERDICT")
    print("=" * 70)
    print(f"  Messages that CANNOT be de-accumulated: {len(bad)}")
    for vt, d, s in bad[:5]:
        print(f"    {vt}  (dataDate={d}, step={s} — step {s-1} missing)")
    print()

    first_vt = records[0][0]
    last_vt = records[-1][0]
    usable = len(records) - len(bad)
    print(f"  Raw messages          : {len(records)}")
    print(f"  Usable after deaccum  : {usable}")
    print()
    if len(bad) == 1 and bad[0][0] == first_vt:
        print(
            "  => Exactly ONE unusable message: the FIRST timestamp,\n"
            f"     {first_vt}, which is the previous month's last hour.\n"
            "     Dropping it leaves a clean, fully de-accumulated series:\n"
            f"       {records[1][0]}  ..  {last_vt}\n"
            f"       = {usable} hourly values.\n"
            "     That first hour belongs to the PREVIOUS month's file\n"
            "     (where it is the last timestamp and computes correctly),\n"
            "     so nothing is lost overall."
        )
    elif not bad:
        print("  => Every message can be de-accumulated. Keep all of them.")
    else:
        print("  => Unexpected pattern; inspect the table above.")


if __name__ == "__main__":
    main()
