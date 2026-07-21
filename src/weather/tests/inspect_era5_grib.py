#!/usr/bin/env python3
"""Inspect an ERA5-Land monthly GRIB without loading it all into RAM.

ERA5-Land CDS GRIBs often contain MULTIPLE hypercubes in one file:
variables with different stepType / time resolution / GRIB edition
cannot share a single cfgrib cube.  This script uses
``cfgrib.open_datasets`` (the cfgrib function, which returns a LIST of
datasets) so it survives those files, and reports each cube separately.

Checks
------
1. Which variables (cfgrib short names) are present, and in which cube.
2. Grid shape and coordinate names (latitude/longitude vs y/x).
3. Whether ``ssrd`` is genuinely ACCUMULATED (monotonic within each UTC
   day, resetting at 00 UTC) — the assumption GHI de-accumulation rests
   on.

Usage
-----
::

    python inspect_era5_grib.py D:/.../ERA5_LAND_2018_03_all_attrs.grib
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


def _open_cubes(grib: str) -> list[Any]:
    """Return a list of xarray Datasets (one per cfgrib hypercube)."""
    import cfgrib  # type: ignore

    return cfgrib.open_datasets(
        grib,
        backend_kwargs={"indexpath": ""},
    )


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("grib", help="Path to the ERA5-Land monthly GRIB")
    p.add_argument(
        "--hours", type=int, default=36,
        help="How many leading hours of ssrd to print for one cell",
    )
    p.add_argument(
        "--lat", type=float, default=None,
        help="Latitude of a known LAND cell to sample (skips ocean hunt)",
    )
    p.add_argument(
        "--lon", type=float, default=None,
        help="Longitude of a known LAND cell (0-360 or -180..180)",
    )
    args = p.parse_args()

    grib = Path(args.grib)
    if not grib.exists():
        sys.exit(f"File not found: {grib}")

    print(f"File: {grib}  ({grib.stat().st_size / 1e9:.1f} GB)\n")

    cubes = _open_cubes(str(grib))
    print(f"cfgrib split the file into {len(cubes)} hypercube(s).\n")

    print("=" * 64)
    print("HYPERCUBES")
    print("=" * 64)
    ssrd_cube = None
    for i, ds in enumerate(cubes):
        dvars = list(ds.data_vars)
        print(f"  cube {i}: vars={dvars}")
        print(f"          dims={dict(ds.sizes)}")
        print(f"          coords={list(ds.coords)}")
        if "time" in ds.coords and ds["time"].size > 1:
            tvals = pd.DatetimeIndex(ds["time"].values)
            step_h = (tvals[1] - tvals[0]).total_seconds() / 3600.0
            print(
                f"          time: {ds['time'].size} steps, "
                f"~{step_h:.0f} h apart, {tvals[0]} .. {tvals[-1]}"
            )
        if "ssrd" in dvars:
            ssrd_cube = ds
        print()

    ds0 = cubes[0]
    print("=" * 64)
    print("COORDINATES (cube 0)")
    print("=" * 64)
    lat_name = next(
        (c for c in ("latitude", "lat", "y") if c in ds0.coords), "?"
    )
    lon_name = next(
        (c for c in ("longitude", "lon", "x") if c in ds0.coords), "?"
    )
    print(f"  lat coord: {lat_name}   lon coord: {lon_name}")
    if lat_name in ds0.coords:
        latv = np.asarray(ds0[lat_name].values)
        lonv = np.asarray(ds0[lon_name].values)
        print(f"  lat: {latv.min():.2f}..{latv.max():.2f} ({latv.size} pts)")
        print(f"  lon: {lonv.min():.2f}..{lonv.max():.2f} ({lonv.size} pts)")
    print()

    print("=" * 64)
    print("ssrd ACCUMULATION CHECK")
    print("=" * 64)
    if ssrd_cube is None:
        print("  !! ssrd not found in any cube — cannot verify.")
        for ds in cubes:
            ds.close()
        return

    ssrd = ssrd_cube["ssrd"]
    print(f"  ssrd dims: {ssrd.dims}  shape: {ssrd.shape}")

    lat_dim = next(
        (d for d in ssrd.dims if d in ("latitude", "lat", "y")), None
    )
    lon_dim = next(
        (d for d in ssrd.dims if d in ("longitude", "lon", "x")), None
    )
    if lat_dim is None or lon_dim is None:
        print(f"  !! could not identify lat/lon dims in {ssrd.dims}")
        for ds in cubes:
            ds.close()
        return

    # MEMORY SAFETY: eccodes decodes a FULL 1801x3600 field per GRIB
    # message even to read one cell.  Reading across all 32 'time' x 24
    # 'step' messages (768 fields) overruns memory.  So we:
    #   1) pick ONE forecast day (single 'time' index)  -> 24 messages
    #   2) reduce lat/lon to scalar indices on that slice
    #   3) call .load() on the resulting (step,) vector only.
    # This verifies within-day accumulation, which is all that's needed.
    has_step = "step" in ssrd.dims
    has_time = "time" in ssrd.dims

    # choose a mid 'time' (forecast day) that is fully inside the month
    ti = min(ssrd.sizes["time"] // 2, ssrd.sizes["time"] - 1) if has_time else None

    # mid-grid spatial guess; ERA5-Land oceans are NaN so we may need to
    # hunt along latitude.  Each probe loads only ONE day's 24 values.
    iy0 = ssrd.sizes[lat_dim] // 2
    ix0 = ssrd.sizes[lon_dim] // 4

    # If the user gave a known land lat/lon, resolve it to indices and
    # skip the hunt entirely (fastest, avoids ocean NaN columns).
    user_cell = False
    if args.lat is not None and args.lon is not None:
        latc = np.asarray(ssrd_cube[lat_dim].values)
        lonc = np.asarray(ssrd_cube[lon_dim].values)
        lon_q = args.lon % 360.0 if lonc.max() > 180.0 else args.lon
        iy0 = int(np.abs(latc - args.lat).argmin())
        ix0 = int(np.abs(lonc - lon_q).argmin())
        user_cell = True
        print(
            f"  using user cell lat={args.lat} lon={args.lon} "
            f"-> [{lat_dim}={iy0}, {lon_dim}={ix0}]"
        )

    def _one_day_cell(iy: int, ix: int) -> np.ndarray:
        sel: dict[str, int] = {lat_dim: iy, lon_dim: ix}
        if has_time and ti is not None:
            sel["time"] = ti
        da = ssrd.isel(sel)  # dims: (step,) or scalar
        if "step" in da.dims:
            # Read ONE step at a time so eccodes decodes a single GRIB
            # message per call (caps peak memory regardless of grid size).
            n_steps = da.sizes["step"]
            vals = np.empty(n_steps, dtype="float64")
            for s in range(n_steps):
                vals[s] = float(da.isel(step=s).load().values)
            return vals
        return np.asarray(da.load().values).reshape(-1)

    series = None
    chosen = None
    hunt_range = [0] if user_cell else range(
        0, min(ssrd.sizes[lat_dim] // 2, 300), 3
    )
    for dy in hunt_range:
        iy = min(iy0 + dy, ssrd.sizes[lat_dim] - 1)
        cand = _one_day_cell(iy, ix0)
        if not np.all(np.isnan(cand)):
            series = cand
            chosen = {lat_dim: iy, lon_dim: ix0, "time_idx": ti}
            break
    if series is None:
        series = _one_day_cell(iy0, ix0)
        chosen = {lat_dim: iy0, lon_dim: ix0, "time_idx": ti}

    # valid_time for this one forecast day (tiny, safe to load)
    if "valid_time" in ssrd_cube.coords and has_time and has_step:
        vt = ssrd_cube["valid_time"].isel(time=ti)
        tindex = pd.DatetimeIndex(np.asarray(vt.load().values).reshape(-1))
    elif has_step:
        tindex = pd.Index(np.arange(series.size), name="step")
    else:
        tindex = pd.Index([0])

    print(f"  sampling cell {chosen}")
    print(f"  (one forecast day, {series.size} steps)\n")
    print(f"  {'valid_time / step':<24s} {'ssrd (J/m^2)':>16s} "
          f"{'delta':>14s}")
    prev = None
    for t, val in zip(tindex, series, strict=False):
        delta = "" if prev is None else f"{val - prev:>14.1f}"
        print(f"  {str(t):<24s} {val:>16.1f} {delta}")
        prev = val

    print()
    diffs = np.diff(series)
    # Within a single forecast day an accumulated field is non-decreasing
    # (allowing tiny float noise).
    if np.all(diffs >= -1.0):
        print(
            "  VERDICT: ssrd is NON-DECREASING within the forecast day "
            "=> ACCUMULATED. The transform de-accumulates along 'step', "
            "which is correct for this file."
        )
    else:
        neg = np.where(diffs < -1.0)[0]
        print(
            f"  VERDICT: ssrd DECREASES within the day at step(s) {neg}. "
            "If only at the very first step it is the reset; otherwise "
            "re-check the transform assumption before trusting GHI."
        )

    for ds in cubes:
        ds.close()


if __name__ == "__main__":
    main()
