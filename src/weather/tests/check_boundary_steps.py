#!/usr/bin/env python3
"""Determine EXACTLY which forecast steps the GRIB contains at the month
boundary — specifically whether the previous month's last day has step 23
as well as step 24.

Why this matters
----------------
The first timestamp of a monthly file (``<1st> 00:00``) is produced by
``dataDate=<prev month last day>, step=24``.  To DE-ACCUMULATE it we need
step 23 of that same forecast day (increment = a[24] - a[23]).

* If step 23 IS present -> the first hour can be computed correctly, and
  we should keep it.
* If step 23 is ABSENT  -> the first hour cannot be computed from THIS
  file alone.  It must be taken from the PREVIOUS month's file (where the
  same instant is that file's LAST timestamp and de-accumulates fine), or
  left NaN and reconciled at concatenation time.

This script lists every ssrd message for the first two dataDates so you
can see precisely what is there.

Usage::

    python check_boundary_steps.py PATH.grib --lat 52.0 --lon 5.0
"""

from __future__ import annotations

import argparse
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
        "--messages", type=int, default=4000,
        help="Scan enough messages to cover the first two dataDates",
    )
    args = ap.parse_args()

    grib = Path(args.grib)
    if not grib.exists():
        sys.exit(f"not found: {grib}")

    import eccodes  # type: ignore

    lat = args.lat
    lon = args.lon % 360.0

    # date -> {step: value}
    by_date: dict[int, dict[int, float]] = defaultdict(dict)
    order: list[int] = []

    count = 0
    with open(grib, "rb") as f:
        while count < args.messages:
            gid = eccodes.codes_grib_new_from_file(f)
            if gid is None:
                break
            count += 1
            try:
                if eccodes.codes_get(gid, "shortName") != args.var:
                    continue
                date = int(eccodes.codes_get(gid, "dataDate"))
                step = int(eccodes.codes_get(gid, "step"))
                try:
                    val = eccodes.codes_grib_find_nearest(
                        gid, lat, lon
                    )[0].value
                except Exception:  # noqa: BLE001
                    val = float("nan")
                if date not in by_date:
                    order.append(date)
                by_date[date][step] = val
                # Stop once we have two full dataDates.
                if len(order) >= 3:
                    break
            finally:
                eccodes.codes_release(gid)

    if not order:
        sys.exit(f"No '{args.var}' messages found.")

    print(f"File: {grib.name}")
    print(f"Variable: {args.var}   probe cell lat={args.lat} lon={args.lon}\n")

    for date in order[:2]:
        steps = sorted(by_date[date])
        print("=" * 60)
        print(f"dataDate = {date}")
        print(f"  steps present: {steps}")
        print(f"  count: {len(steps)}")
        if steps:
            print(f"  {'step':>5s} {'value (J/m2)':>16s}")
            for s in steps:
                print(f"  {s:>5d} {by_date[date][s]:>16.1f}")
        print()

    first_date = order[0]
    first_steps = sorted(by_date[first_date])

    print("=" * 60)
    print("VERDICT")
    print("=" * 60)
    if first_steps == [24] or (24 in first_steps and 23 not in first_steps):
        print(
            f"  dataDate {first_date} contains ONLY step(s) {first_steps}.\n"
            "  => Step 23 is ABSENT, so the first timestamp of the month\n"
            "     CANNOT be de-accumulated from this file alone.\n"
            "  => Correct handling: keep it as NaN here and take the value\n"
            "     from the PREVIOUS month's file at concatenation time\n"
            "     (there it is the LAST timestamp and computes correctly)."
        )
    elif 23 in first_steps and 24 in first_steps:
        print(
            f"  dataDate {first_date} contains steps 23 AND 24.\n"
            "  => The first timestamp CAN be de-accumulated correctly\n"
            "     (increment = a[24] - a[23]).  No NaN should appear.\n"
            "  => If the pipeline still yields NaN there, it is a code bug."
        )
    else:
        print(
            f"  dataDate {first_date} steps: {first_steps}\n"
            "  => Unexpected layout; inspect the table above."
        )


if __name__ == "__main__":
    main()
