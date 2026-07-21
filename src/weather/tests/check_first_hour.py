#!/usr/bin/env python3
"""Find the TRUE origin of the first-hour GHI NaN, using raw eccodes.

We established that our de-accumulate-before-trim ordering should yield a
computed 0.0 for the first hour (verified on synthetic data with the same
forecast structure).  So a NaN in the real output means the SOURCE data is
missing that value -- not that our pipeline creates it.

This script reads the raw GRIB with eccodes (no cfgrib, no xarray) and
prints, for one land cell:

  * every ssrd message's dataDate / dataTime / step / value
    around the month boundary,
  * specifically whether the message producing valid_time = <1st of month
    00:00> exists at all.

If that message is ABSENT from the file, the NaN is a genuine source-data
gap and filling it with 0 (night) is correct.
If it is PRESENT with a real value, our pipeline is dropping it and we
should fix the pipeline instead.

Usage::

    python check_first_hour.py PATH.grib --lat 52.0 --lon 5.0
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("grib")
    ap.add_argument("--lat", type=float, default=52.0)
    ap.add_argument("--lon", type=float, default=5.0)
    ap.add_argument(
        "--messages", type=int, default=600,
        help="How many messages to scan (enough for the first ~2 days)",
    )
    args = ap.parse_args()

    grib = Path(args.grib)
    if not grib.exists():
        sys.exit(f"not found: {grib}")

    import eccodes  # type: ignore

    lat = args.lat
    lon = args.lon % 360.0

    print(f"File: {grib.name}")
    print(f"Probing land cell lat={args.lat}, lon={args.lon}\n")

    rows = []
    count = 0
    with open(grib, "rb") as f:
        while count < args.messages:
            gid = eccodes.codes_grib_new_from_file(f)
            if gid is None:
                break
            count += 1
            try:
                short = eccodes.codes_get(gid, "shortName")
                if short != "ssrd":
                    continue
                date = eccodes.codes_get(gid, "dataDate")
                tm = eccodes.codes_get(gid, "dataTime")
                step = eccodes.codes_get(gid, "step")
                try:
                    near = eccodes.codes_grib_find_nearest(gid, lat, lon)[0]
                    val = near.value
                except Exception:  # noqa: BLE001
                    val = float("nan")
                rows.append((date, tm, int(step), val))
            finally:
                eccodes.codes_release(gid)

    if not rows:
        print("No ssrd messages found in the scanned range.")
        return

    import datetime as dt

    print(f"{'dataDate':>10s} {'time':>5s} {'step':>5s} "
          f"{'valid_time':>17s} {'ssrd (J/m2)':>14s}")
    print("-" * 60)
    for date, tm, step, val in rows[:60]:
        # valid_time = dataDate + dataTime + step hours
        base = dt.datetime.strptime(str(date), "%Y%m%d") + dt.timedelta(
            hours=tm // 100
        )
        vt = base + dt.timedelta(hours=step)
        print(
            f"{date:>10d} {tm:>5d} {step:>5d} "
            f"{vt.strftime('%Y-%m-%d %H:%M'):>17s} {val:>14.1f}"
        )

    # Does a message land exactly on the 1st of the month at 00:00?
    # target = first day of the DOMINANT month at 00:00
    months: Counter[tuple[int, int]] = Counter()
    for date, tm, step, _ in rows:
        b = dt.datetime.strptime(str(date), "%Y%m%d") + dt.timedelta(
            hours=tm // 100
        )
        vt = b + dt.timedelta(hours=step)
        months[(vt.year, vt.month)] += 1
    (yr, mo), _ = months.most_common(1)[0]
    target = dt.datetime(yr, mo, 1, 0, 0)

    print()
    print("=" * 60)
    match = None
    for date, tm, step, val in rows:
        b = dt.datetime.strptime(str(date), "%Y%m%d") + dt.timedelta(
            hours=tm // 100
        )
        vt = b + dt.timedelta(hours=step)
        if vt == target:
            match = (date, tm, step, val)
            break

    if match is None:
        print(
            f"VERDICT: NO ssrd message produces valid_time {target}.\n"
            "  => The source GRIB genuinely lacks the first hour.\n"
            "  => The NaN is a SOURCE gap, not a pipeline bug.\n"
            "  => Filling it with 0 (night) is the correct response."
        )
    else:
        d, t, s, v = match
        print(
            f"VERDICT: ssrd for {target} EXISTS "
            f"(dataDate={d}, step={s}, value={v:.1f}).\n"
            "  => The source HAS the data; our pipeline is dropping it.\n"
            "  => Fix the pipeline rather than filling with 0."
        )


if __name__ == "__main__":
    main()
