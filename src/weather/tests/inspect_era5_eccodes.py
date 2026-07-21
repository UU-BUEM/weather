#!/usr/bin/env python3
"""Lightweight ERA5-Land GRIB inspector using eccodes DIRECTLY.

Why not cfgrib?  ``cfgrib.open_datasets`` scans and indexes EVERY GRIB
message in the file up front (tens of thousands on a global month),
which is heavy and has been triggering eccodes ``MemoryAllocationError``
on large files.  This script instead walks messages one at a time with
the low-level eccodes API, reads only the first ``--messages`` of them,
and extracts a single grid point with ``codes_grib_find_nearest`` — so
peak memory stays tiny and no global index is built.

It answers the two questions that matter:

1. What variables / stepType / units are in the file, and how is the
   time axis structured (dataDate/dataTime/step)?
2. Is ``ssrd`` ACCUMULATED?  It prints ssrd at one land point across the
   first 24 forecast steps so you can see the within-day ramp.

Usage
-----
::

    python inspect_era5_eccodes.py PATH_TO.grib --lat 52.0 --lon 5.0

``--messages`` caps how many GRIB messages are scanned (default 400,
enough to cover the first day of every variable in an all-attrs file).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("grib", help="Path to the ERA5-Land GRIB")
    ap.add_argument("--lat", type=float, default=52.0)
    ap.add_argument("--lon", type=float, default=5.0)
    ap.add_argument(
        "--messages", type=int, default=400,
        help="Max GRIB messages to scan (keeps memory/time bounded)",
    )
    ap.add_argument(
        "--var", default="ssrd",
        help="shortName to track across forecast steps (default ssrd)",
    )
    args = ap.parse_args()

    grib = Path(args.grib)
    if not grib.exists():
        sys.exit(f"File not found: {grib}")

    try:
        import eccodes  # type: ignore
    except ImportError:
        sys.exit(
            "eccodes Python bindings not importable. "
            "They ship with cfgrib (conda install -c conda-forge eccodes)."
        )

    print(f"File: {grib}  ({grib.stat().st_size / 1e9:.1f} GB)")
    print(f"Scanning up to {args.messages} messages...\n")

    # Track unique variable summaries and a per-step ssrd series.
    seen: dict[str, dict] = {}
    # key: (shortName) -> list of (dataDate, dataTime, step, value_at_point)
    track: list[tuple] = []

    lat = args.lat
    lon = args.lon % 360.0  # ERA5-Land longitudes are 0..360

    count = 0
    with open(grib, "rb") as f:
        while count < args.messages:
            gid = eccodes.codes_grib_new_from_file(f)
            if gid is None:
                break
            count += 1
            try:
                short = _get(eccodes, gid, "shortName")
                if short not in seen:
                    seen[short] = {
                        "name": _get(eccodes, gid, "name"),
                        "units": _get(eccodes, gid, "units"),
                        "stepType": _get(eccodes, gid, "stepType"),
                        "typeOfLevel": _get(eccodes, gid, "typeOfLevel"),
                        "edition": _get(eccodes, gid, "edition"),
                        "Ni": _get(eccodes, gid, "Ni"),
                        "Nj": _get(eccodes, gid, "Nj"),
                    }

                # Track the requested var across its forecast steps.
                if short == args.var:
                    date = _get(eccodes, gid, "dataDate")
                    tm = _get(eccodes, gid, "dataTime")
                    step = _get(eccodes, gid, "step")
                    # Nearest-point value — decodes only what's needed.
                    try:
                        nearest = eccodes.codes_grib_find_nearest(
                            gid, lat, lon
                        )[0]
                        val = nearest.value
                    except Exception as exc:  # noqa: BLE001
                        val = float("nan")
                        if count <= 2:
                            print(f"  (find_nearest note: {exc})")
                    track.append((date, tm, step, val))
            finally:
                eccodes.codes_release(gid)

    print("=" * 64)
    print(f"VARIABLES SEEN (in first {count} messages)")
    print("=" * 64)
    print(
        f"  {'short':<8s} {'stepType':<9s} {'units':<12s} "
        f"{'edition':<7s} {'grid':<12s} name"
    )
    for s, meta in sorted(seen.items()):
        grid = f"{meta['Ni']}x{meta['Nj']}"
        print(
            f"  {s:<8s} {str(meta['stepType']):<9s} "
            f"{str(meta['units']):<12s} {str(meta['edition']):<7s} "
            f"{grid:<12s} {meta['name']}"
        )
    print()

    print("=" * 64)
    print(f"{args.var.upper()} ACROSS FORECAST STEPS  "
          f"(point lat={args.lat}, lon={args.lon})")
    print("=" * 64)
    if not track:
        print(f"  No '{args.var}' messages in the first {count} scanned.")
        print("  Try increasing --messages.")
        return

    print(f"  {'dataDate':>10s} {'dataTime':>8s} {'step':>6s} "
          f"{'value':>16s} {'delta':>14s}")
    prev = None
    prev_key = None
    for date, tm, step, val in track[:48]:
        key = (date, tm)
        # reset delta when the forecast day changes
        if key != prev_key:
            delta = "  (new forecast day)"
            prev = val
        else:
            delta = f"{val - prev:>14.1f}" if prev is not None else ""
            prev = val
        prev_key = key
        print(f"  {date:>10d} {tm:>8d} {str(step):>6s} "
              f"{val:>16.1f} {delta}")

    # Verdict on the first forecast day.
    first_key = (track[0][0], track[0][1])
    day_vals = [v for (d, t, s, v) in track if (d, t) == first_key]
    print()
    import math
    diffs = [day_vals[i + 1] - day_vals[i] for i in range(len(day_vals) - 1)]
    nonneg = all((d >= -1.0 or math.isnan(d)) for d in diffs)
    if nonneg and len(day_vals) > 1:
        print(
            f"  VERDICT: {args.var} is NON-DECREASING within the first "
            "forecast day => ACCUMULATED. Step de-accumulation in the "
            "transform is correct."
        )
    elif len(day_vals) <= 1:
        print("  Only one step captured for the first day; "
              "increase --messages.")
    else:
        print(
            f"  VERDICT: {args.var} decreases within the day. Inspect the "
            "table above; a drop only at the first step is the reset."
        )


def _get(eccodes, gid, key):
    """Safely read a GRIB key, returning None if absent."""
    try:
        return eccodes.codes_get(gid, key)
    except Exception:  # noqa: BLE001
        return None


if __name__ == "__main__":
    main()
