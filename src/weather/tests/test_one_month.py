#!/usr/bin/env python3
"""End-to-end pipeline test: download, decompress, and process one month of
COSMO-REA6 data, exercising all 9 available attributes.

Downloads all nine COSMO-REA6 raw attributes in parallel, decompresses them
with a pipeline that overlaps download and decompression (producer-consumer
pattern), then computes all derived variables and writes a single NetCDF file.

Derived variables written to the output NetCDF
-----------------------------------------------
  T         — 2-m air temperature (°C)
  GHI       — Global Horizontal Irradiance (W/m²)
  DHI       — Diffuse Horizontal Irradiance (W/m²)
  WS_10M    — Wind speed at 10 m (m/s)
  DNI       — Direct Normal Irradiance [experimental] (W/m²)
  PS        — Surface pressure (Pa)
  H_SNOW    — Snow depth (m)
  SNOW_GSP  — Stratiform snow (kg/m²)
  SNOW_CON  — Convective snow (kg/m²)

Usage
-----
Basic::

    python src/weather/tests/test_one_month.py

Custom year/month::

    python src/weather/tests/test_one_month.py --year 2018 --month 6

Full set of options::

    python src/weather/tests/test_one_month.py \\
        --year 2018 --month 1 \\
        --work-dir /scratch/cosmo_test \\
        --ncores 8 \\
        --skip-dni

Re-use already-downloaded files::

    python src/weather/tests/test_one_month.py --skip-download
    python src/weather/tests/test_one_month.py --skip-download
    --skip-decompress

Flags
-----
--year YEAR             Four-digit year (default: 2018)
--month M               Month 1-12 (default: 1)
--work-dir DIR          Override COSMO_WORK_DIR for this run only
--ncores N              Total worker count (default: COSMO_NCORES env var or 4)
--skip-download         Assume .grb.bz2 files are already present
--skip-decompress       Assume .grb files are already present
--skip-dni              Skip experimental per-cell DNI computation

Pipeline flow
-------------
::

    test_one_month.py
      │
      ├── Phase 1 — Download (ThreadPoolExecutor, 9 × 1 = 9 parallel tasks)
      │     For each of the 9 COSMO-REA6 attributes:
      │       HTTP GET  →  download/<attr>/<attr>.2D.<YYYYMM>.grb.bz2
      │       (skip if bz2 already present and valid)
      │
      ├── Phase 2 — Decompress (ProcessPoolExecutor, up to ncores workers)
      │     For each of the 9 bz2 files:
      │       lbzip2 / pbzip2 / python-bz2  →  decompress/<attr>/….grb
      │       (skip if GRIB already present and valid)
      │
      └── Phase 3 — Transform + Export (single month)
            cfgrib.open_datasets(<all 9 GRIBs>)
              →  apply_derived_fields: GHI, DHI, DNI, T, WS_10M …
              →  export.to_netcdf (zlib, complevel=1, float32)
              →  <work_dir>/output/COSMO_REA6_<YYYY>_<MM>_all_attrs.nc
              →  cleanup: delete GRIB files

Output: 1 × COSMO_REA6_<YYYY>_<MM>_all_attrs.nc  (shape: 8760×824×848 or
        similar; 9 derived variables + static coords lat/lon)
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from concurrent.futures import (
    ProcessPoolExecutor,
    ThreadPoolExecutor,
    as_completed,
)
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import xarray

# ---------------------------------------------------------------------------
# Path bootstrap — allows running without a prior `pip install -e .`
# ---------------------------------------------------------------------------
_here = Path(__file__).resolve().parent   # src/weather/tests/
_src = _here.parent.parent               # src/
if (_src / "weather").is_dir() and str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("cr6_test")

# All nine COSMO-REA6 attributes (order preserved in logs)
_ALL_ATTRS: list[str] = [
    "PS",
    "SWDIFDS_RAD",
    "SWDIRS_RAD",
    "T_2M",
    "U_10M",
    "V_10M",
    "H_SNOW",
    "SNOW_GSP",
    "SNOW_CON",
]


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="End-to-end 1-month COSMO-REA6 pipeline test"
        " (all 9 attributes)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--year",  type=int, default=2018, help="Four-digit year")
    p.add_argument(
        "--month", type=int, default=1, metavar="M",
        help="Month 1-12",
    )
    p.add_argument(
        "--work-dir", default=None, metavar="DIR",
        help="Override COSMO_WORK_DIR for this run",
    )
    p.add_argument(
        "--ncores", type=int, default=None, metavar="N",
        help="Total worker count (default: COSMO_NCORES env var or 4)",
    )
    p.add_argument(
        "--skip-download", action="store_true",
        help="Re-use existing .grb.bz2 files",
    )
    p.add_argument(
        "--skip-decompress", action="store_true",
        help="Re-use existing .grb files",
    )
    p.add_argument(
        "--skip-dni", action="store_true",
        help="Skip experimental per-cell DNI computation",
    )
    p.add_argument(
        "--no-cleanup", action="store_true",
        help="Keep intermediate files (downloads, decompressed GRIBs, "
             "cfgrib index files).  By default, .grb.bz2 files are removed "
             "after decompression and .grb/.idx files are removed after "
             "the NetCDF is written.",
    )
    args = p.parse_args()
    if not 1 <= args.month <= 12:
        p.error(f"--month must be 1-12, got {args.month}")
    return args


# ---------------------------------------------------------------------------
# Parallel pipeline: download → decompress
# ---------------------------------------------------------------------------

def _pipeline_download_decompress(
    attrs: list[str],
    year: int,
    month: int,
    dl_dir: Path,
    dc_dir: Path,
    ncores: int,
    threads_per_job: int,
) -> dict[str, Path]:
    """Download all attrs concurrently, decompress each as it arrives.

    Uses a thread pool for downloads (I/O-bound) and a process pool for
    decompression (CPU-bound bzip2).  A decompress job is submitted to
    the process pool as soon as its download completes, so the two pools
    overlap and cores are never left idle.

    Parameters
    ----------
    attrs :
        Attribute names to process.
    year, month :
        Target period.
    dl_dir, dc_dir :
        Root directories for downloaded and decompressed files.
    ncores :
        Total worker budget shared between the two pools.
    threads_per_job :
        bzip2 threads for each decompression worker process.

    Returns
    -------
    dict[str, Path]
        Mapping ``attr → decompressed .grb path``.
    """
    from weather.providers.cosmo_rea6.decompress import decompress_file
    from weather.providers.cosmo_rea6.download import download_attribute_month

    n = len(attrs)
    dl_workers = min(n, max(1, ncores // 2))
    dc_workers = min(n, max(1, ncores - dl_workers))

    logger.info(
        "  Pipeline: %d download threads  |  %d decompress workers",
        dl_workers, dc_workers,
    )

    grb_paths: dict[str, Path] = {}

    # ProcessPoolExecutor is outer so it stays alive while downloads run
    with ProcessPoolExecutor(max_workers=dc_workers) as dc_pool:
        dc_futures: dict = {}
        with ThreadPoolExecutor(max_workers=dl_workers) as dl_pool:
            dl_futures: dict = {}
            for attr in attrs:
                (dl_dir / attr).mkdir(parents=True, exist_ok=True)
                fut = dl_pool.submit(
                    download_attribute_month,
                    attr, year, month,
                    dest_dir=dl_dir / attr,
                )
                dl_futures[fut] = attr

            # Producer-consumer: submit decompress as each download finishes
            for dl_fut in as_completed(dl_futures):
                attr = dl_futures[dl_fut]
                bz2_path = dl_fut.result()   # re-raises on error
                logger.info("  [dl  done] %-12s  %s", attr, bz2_path.name)
                (dc_dir / attr).mkdir(parents=True, exist_ok=True)
                dc_fut = dc_pool.submit(
                    decompress_file,
                    bz2_path,
                    dest_dir=dc_dir / attr,      # keyword-only
                    threads=threads_per_job,      # keyword-only
                )
                dc_futures[dc_fut] = attr
        # dl_pool is fully shut down here; all dc jobs already submitted

        for dc_fut in as_completed(dc_futures):
            attr = dc_futures[dc_fut]
            grb_path = dc_fut.result()   # re-raises on error
            logger.info("  [dc  done] %-12s  %s", attr, grb_path.name)
            grb_paths[attr] = grb_path

    return grb_paths


# ---------------------------------------------------------------------------
# DNI diagnostics
# ---------------------------------------------------------------------------

def _log_dni_stats(
    dni: xarray.DataArray,
    ds_direct: xarray.Dataset,
) -> None:
    """Log DNI distribution stats and consistency checks (informational only).

    Samples every 24th timestep (≈1 snapshot/day) to keep memory low.
    Does not modify any data or raise exceptions.

    Notes on expected value ranges
    --------------------------------
    Negative DNI is structurally impossible: SWDIRS_RAD ≥ 0 always (it is an
    irradiance from the CR6 reanalysis model) and cos_sza is clipped to a
    small positive value, so the division cannot produce a negative result.

    Checks logged
    -------------
    - SWDIRS = 0 → DNI = 0  (consistency between input and output).
    - DNI ≥ SWDIRS_RAD for all daytime cells  (cos_sza ≤ 1, so dividing
      by it can only increase or preserve the value).
    - Percentile distribution of daytime-only DNI values.
    - Zero fraction (= night + below-elevation-threshold fraction).
    """
    import numpy as np_

    logger.info("  DNI stats (daily sample) ...")

    raw_name = next(iter(ds_direct.data_vars))
    swdirs = ds_direct[raw_name]

    stride = max(1, len(dni.time) // 31)
    try:
        dni_s = (
            dni.isel(time=slice(None, None, stride))
            .values.ravel().astype("float32")
        )
        sw_s = (
            swdirs.isel(time=slice(None, None, stride))
            .values.ravel().astype("float32")
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("  DNI stats skipped — could not compute sample: %s",
                       exc)
        return

    n_total = len(dni_s)

    # Consistency: SWDIRS = 0 → DNI must be 0
    mask_night = sw_s <= 0.0
    n_bad = int((mask_night & (dni_s > 0.1)).sum())
    if n_bad > 0:
        logger.warning(
            "  SWDIRS=0 but DNI>0: %d cells — check CR6 data or formula",
            n_bad,
        )
    else:
        logger.info("  SWDIRS=0 → DNI=0  (consistent)")

    # Consistency: DNI ≥ SWDIRS for cells where DNI > 0 (cos_sza ≤ 1 always).
    # We exclude DNI = 0 cells because the elevation threshold deliberately
    # zeros DNI when sun elevation < 5°, even if SWDIRS_RAD is small but
    # non-zero (CR6 assigns tiny SWDIRS values at grazing incidence).
    # Those zeroed cells are correct behaviour, not a formula error.
    mask_day = sw_s > 1.0
    n_day = int(mask_day.sum())
    mask_active = mask_day & (dni_s > 0.0)   # sun above threshold
    n_active = int(mask_active.sum())
    n_zeroed = n_day - n_active              # correctly zeroed by threshold
    if n_zeroed > 0:
        logger.info(
            "  %d daytime cells zeroed by elevation threshold (correct)",
            n_zeroed,
        )
    if n_active > 0:
        n_bad2 = int((mask_active & (dni_s < sw_s * 0.99)).sum())
        if n_bad2 > 0:
            logger.warning(
                "  DNI < SWDIRS_RAD: %d / %d above-threshold cells"
                " — unexpected (cos_sza clamped to 1.0, check formula)",
                n_bad2, n_active,
            )
        else:
            logger.info(
                "  DNI >= SWDIRS_RAD for all %d above-threshold cells",
                n_active,
            )

    # Distribution
    pct_zero = 100.0 * float((dni_s == 0.0).sum()) / n_total
    logger.info("DNI zero fraction (night + below-threshold): %.1f%%",
                pct_zero)

    dni_day = dni_s[mask_day]
    if len(dni_day) > 0:
        logger.info(
            "DNI daytime percentiles (n=%d):"
            "p25=%.0f  p50=%.0f  p75=%.0f  p95=%.0f  p99=%.0f  max=%.0f  W/m²",
            len(dni_day),
            float(np_.percentile(dni_day, 25)),
            float(np_.percentile(dni_day, 50)),
            float(np_.percentile(dni_day, 75)),
            float(np_.percentile(dni_day, 95)),
            float(np_.percentile(dni_day, 99)),
            float(dni_day.max()),
        )


def _report_dni_outliers(nc_path: Path, threshold: float = 1400.0) -> None:
    """Open the saved NetCDF and report cells where DNI exceeds *threshold*.

    Finds all grid cells whose peak DNI across all timesteps is >= threshold,
    then logs their latitude, longitude, grid indices (y, x), and peak value.
    At most 20 cells are listed individually; the total count is always shown.

    Parameters
    ----------
    nc_path : Path
        Path to the exported NetCDF file.
    threshold : float
        W/m² above which a cell is considered an outlier.  Default 1400 W/m².
        The solar constant is ~1361 W/m² at TOA; surface DNI cannot reach
        this value, so any cell >= 1400 W/m² indicates unphysical CR6 data
        or a formula error in compute_dni.
    """
    import numpy as np_

    try:
        import xarray as xr_
    except ImportError:
        logger.warning("  xarray not available — DNI outlier report skipped")
        return

    logger.info("=" * 68)
    logger.info("DNI OUTLIER REPORT  (threshold >= %.0f W/m²)", threshold)

    with xr_.open_dataset(nc_path) as ds:
        if "DNI" not in ds:
            logger.info("DNI not present in output file (--skip-dni was used)")
            return

        dni = ds["DNI"]

        # Peak DNI at each grid cell across all timesteps → shape (y, x)
        dni_peak = dni.max(dim="time").values.astype("float32")
        mask = dni_peak >= threshold
        n_cells = int(mask.sum())
        total_cells = int(mask.size)

        if n_cells == 0:
            logger.info(
                "  No cells with DNI >= %.0f W/m²  "
                "(all values within physical range)",
                threshold,
            )
            return

        pct = 100.0 * n_cells / total_cells
        logger.warning(
            "  %d / %d grid cells (%.4f%%) have peak DNI >= %.0f W/m²",
            n_cells, total_cells, pct, threshold,
        )

        # Retrieve lat/lon for reporting
        has_coords = (
            "latitude" in ds.coords and "longitude" in ds.coords
        )
        if has_coords:
            lat2d = ds["latitude"].values
            lon2d = ds["longitude"].values

        ys, xs = np_.where(mask)
        vals = dni_peak[mask]
        # Show up to 20 worst cells, sorted by descending peak DNI
        order = np_.argsort(vals)[::-1][:20]

        logger.warning(
            "  Top %d cells by peak DNI:", min(20, n_cells)
        )
        for rank, idx in enumerate(order):
            y, x = int(ys[idx]), int(xs[idx])
            peak = float(vals[idx])
            if has_coords:
                logger.warning(
                    "    #%02d  lat=%7.3f  lon=%7.3f"
                    "  (y=%d, x=%d)  peak=%.1f W/m²",
                    rank + 1, float(lat2d[y, x]), float(lon2d[y, x]),
                    y, x, peak,
                )
            else:
                logger.warning(
                    "    #%02d  y=%d  x=%d  peak=%.1f W/m²",
                    rank + 1, y, x, peak,
                )

        if n_cells > 20:
            logger.warning(
                "  ... and %d more cells (not listed)", n_cells - 20
            )

    logger.info("=" * 68)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    args = _parse_args()

    # Import first so load_repo_env() runs (triggered by settings.py at
    # import time).  CLI overrides are applied immediately after so they
    # take precedence over any .env values.
    from weather.common.cleanup import cleanup_work_directory
    from weather.common.env import repo_root as _repo_root
    from weather.providers.cosmo_rea6.config import get_config
    from weather.providers.cosmo_rea6.decompress import decompress_file
    from weather.providers.cosmo_rea6.download import download_attribute_month
    from weather.providers.cosmo_rea6.export import export_netcdf
    from weather.providers.cosmo_rea6.naming import grib_filename
    from weather.providers.cosmo_rea6.transform import (
        _resolve_var,
        _strip_scalar_coords,
        compute_dhi,
        compute_dni,
        compute_ghi,
        compute_wind_speed,
        convert_temperature,
        open_grib_month,
    )

    # CLI overrides — applied after imports so they win over .env values.
    if args.work_dir:
        os.environ["COSMO_WORK_DIR"] = args.work_dir
    if args.ncores is not None:
        os.environ["COSMO_NCORES"] = str(args.ncores)

    try:
        import xarray as xr
    except ImportError:
        sys.exit(
            "xarray is not installed. "
            "Run: conda install conda-forge::xarray"
        )

    cfg = get_config()

    # Report which .env file was found (or warn if none) so HPC users can
    # immediately confirm that their path settings are being picked up.
    _root = _repo_root()
    _env_candidates = [_root / ".env", Path.cwd() / ".env"]
    _env_file = next((p for p in _env_candidates if p.is_file()), None)
    if _env_file:
        logger.info(".env loaded from: %s", _env_file)
    else:
        logger.warning(
            "No .env file found (checked %s).  "
            "Using environment variables / built-in defaults.  "
            "Create a .env from .env.example and set "
            "WEATHER_DATA_DIR to your shared storage path.",
            " and ".join(str(p) for p in _env_candidates),
        )

    year: int = args.year
    month: int = args.month
    ncores: int = cfg["ncores"]
    threads: int = cfg["threads_per_job"]
    dl_dir: Path = cfg["download_dir"]
    dc_dir: Path = cfg["decompress_dir"]
    out_dir: Path = cfg["output_dir"]
    log_dir: Path = cfg["log_dir"]

    for d in (dl_dir, dc_dir, out_dir, log_dir):
        d.mkdir(parents=True, exist_ok=True)

    # ── File logging ─────────────────────────────────────────────────────
    # A per-run log file captures everything including DEBUG messages from
    # cfgrib alias resolution, dask, and xarray — useful for post-mortem
    # analysis on HPC without re-running.  The console handler (set above
    # at module level) stays at INFO so the terminal stays readable.
    from datetime import datetime as _dt
    _ts = _dt.now().strftime("%Y%m%d_%H%M%S")
    _log_fname = f"COSMO_REA6_{year}_{month:02d}_{_ts}.log"
    _log_path = log_dir / _log_fname
    _fh = logging.FileHandler(_log_path, encoding="utf-8")
    _fh.setLevel(logging.DEBUG)
    _fh.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logging.getLogger().addHandler(_fh)
    logger.info("Log file: %s", _log_path)

    logger.info("=" * 68)
    logger.info("COSMO-REA6 One-Month Pipeline Test — all 9 attributes")
    logger.info("  Year       : %d", year)
    logger.info("  Month      : %02d", month)
    logger.info("  Attributes : %s", ", ".join(_ALL_ATTRS))
    logger.info("  Cores      : %d  (threads/job: %d)", ncores, threads)
    logger.info("  Work dir   : %s", cfg["work_dir"])
    logger.info("  Log dir    : %s", log_dir)
    logger.info("  DNI        : %s", "skip (--skip-dni)" if args.skip_dni else
                "enabled (experimental)")
    logger.info("=" * 68)

    # Warn when the work dir is inside the repo (almost always wrong on HPC:
    # it means COSMO_WORK_DIR is unset or set to a relative path that resolves
    # to the local drive instead of the shared storage).
    try:
        _work = cfg["work_dir"]
        if _work.is_relative_to(_root):
            logger.warning(
                "Work dir is INSIDE the repository (%s).  "
                "On HPC this usually means COSMO_WORK_DIR is not set or is "
                "still the default relative path from .env.example.  "
                "Set WEATHER_DATA_DIR (or COSMO_WORK_DIR) in your .env to "
                "a shared/scratch location, e.g. WEATHER_DATA_DIR=/data/soma",
                _work,
            )
    except Exception:
        pass

    t_total = time.perf_counter()

    # ── Step 1: Download + Decompress ────────────────────────────────────
    t0 = time.perf_counter()
    do_dl = not args.skip_download
    do_dc = not args.skip_decompress

    if do_dl and do_dc:
        logger.info("STEP 1/4: Download + Decompress (pipeline, %d attrs) ...",
                    len(_ALL_ATTRS))
        _pipeline_download_decompress(
            _ALL_ATTRS, year, month, dl_dir, dc_dir, ncores, threads,
        )

    elif do_dl:
        # Only download; decompress skipped
        logger.info("STEP 1/4: Download only (%d attrs, skip-decompress) ...",
                    len(_ALL_ATTRS))
        n_workers = min(len(_ALL_ATTRS), ncores)
        with ThreadPoolExecutor(max_workers=n_workers) as pool:
            futures = {
                pool.submit(
                    download_attribute_month,
                    attr, year, month,
                    dest_dir=dl_dir / attr,
                ): attr
                for attr in _ALL_ATTRS
            }
            for fut in as_completed(futures):
                attr = futures[fut]
                bz2 = fut.result()
                logger.info("  [dl  done] %-12s  %s", attr, bz2.name)

    elif do_dc:
        # Only decompress; download skipped — find existing bz2 files
        logger.info("STEP 1/4: Decompress only (%d attrs, skip-download) ...",
                    len(_ALL_ATTRS))
        bz2_map: dict[str, Path] = {}
        for attr in _ALL_ATTRS:
            bz2_name = grib_filename(attr, year, month)
            bz2_path = dl_dir / attr / bz2_name
            if not bz2_path.exists():
                sys.exit(f"ERROR: compressed file not found: {bz2_path}")
            bz2_map[attr] = bz2_path

        n_workers = min(len(_ALL_ATTRS), ncores)
        with ProcessPoolExecutor(max_workers=n_workers) as pool:
            futures = {
                pool.submit(
                    decompress_file,
                    bz2,
                    dest_dir=dc_dir / attr,    # keyword-only
                    threads=threads,            # keyword-only
                ): attr
                for attr, bz2 in bz2_map.items()
            }
            for fut in as_completed(futures):
                attr = futures[fut]
                grb = fut.result()
                logger.info("  [dc  done] %-12s  %s", attr, grb.name)

    else:
        logger.info(
            "STEP 1/4: Both download and decompress skipped "
            "(re-using existing files)"
        )

    logger.info("  Step 1 time: %.1f s", time.perf_counter() - t0)

    # Remove downloaded .grb.bz2 files now that decompression is complete.
    # (Only when we both downloaded and decompressed in this run; if the
    # user passed --skip-download or --skip-decompress the source files
    # may be shared and should not be removed.)
    if not args.no_cleanup and do_dl and do_dc:
        logger.info("  Removing downloaded .grb.bz2 files ...")
        cleanup_work_directory(
            dl_dir,
            cleanup_downloads=True,
            cleanup_decompressed=False,
            cleanup_locks=False,
        )

    # ── Step 2: Open GRIB files ───────────────────────────────────────────
    t0 = time.perf_counter()
    logger.info("STEP 2/4: Opening %d GRIB files ...", len(_ALL_ATTRS))
    datasets = {}
    for attr in _ALL_ATTRS:
        datasets[attr] = open_grib_month(attr, year, month)
    logger.info("  Step 2 time: %.1f s", time.perf_counter() - t0)

    # ── Step 3: Transform ────────────────────────────────────────────────
    t0 = time.perf_counter()
    logger.info("STEP 3/4: Transforming ...")

    T = _strip_scalar_coords(convert_temperature(datasets["T_2M"]))
    GHI = _strip_scalar_coords(
        compute_ghi(datasets["SWDIFDS_RAD"], datasets["SWDIRS_RAD"])
    )
    DHI = _strip_scalar_coords(compute_dhi(datasets["SWDIFDS_RAD"]))
    WS = _strip_scalar_coords(
        compute_wind_speed(datasets["U_10M"], datasets["V_10M"])
    )

    # Pass-through: rename to canonical names and add minimal attrs
    PS = _strip_scalar_coords(_resolve_var(datasets["PS"], "PS")).rename("PS")
    PS.attrs.update({"units": "Pa", "long_name": "Surface pressure"})

    HSNOW = (
        _strip_scalar_coords(_resolve_var(datasets["H_SNOW"], "H_SNOW"))
        .rename("H_SNOW")
    )
    HSNOW.attrs.update({"units": "m", "long_name": "Snow depth"})

    SGSP = (
        _strip_scalar_coords(_resolve_var(datasets["SNOW_GSP"], "SNOW_GSP"))
        .rename("SNOW_GSP")
    )
    SGSP.attrs.update({"units": "kg/m2", "long_name": "Stratiform snow"})

    SCON = (
        _strip_scalar_coords(_resolve_var(datasets["SNOW_CON"], "SNOW_CON"))
        .rename("SNOW_CON")
    )
    SCON.attrs.update({"units": "kg/m2", "long_name": "Convective snow"})

    data_vars: dict = {
        "T":        T,
        "GHI":      GHI,
        "DHI":      DHI,
        "WS_10M":   WS,
        "PS":       PS,
        "H_SNOW":   HSNOW,
        "SNOW_GSP": SGSP,
        "SNOW_CON": SCON,
    }

    if not args.skip_dni:
        logger.info("  Computing per-cell DNI (experimental) ...")
        DNI = _strip_scalar_coords(compute_dni(datasets["SWDIRS_RAD"]))
        data_vars["DNI"] = DNI
        logger.info(
            "  DNI range: [%.1f, %.1f] W/m² (zero = sun below 5° threshold)",
            float(DNI.min()), float(DNI.max()),
        )
        _log_dni_stats(DNI, datasets["SWDIRS_RAD"])

    ds_out = xr.Dataset(data_vars)

    shapes = {k: list(v.shape) for k, v in ds_out.data_vars.items()}
    logger.info("  Variable shapes: %s", shapes)
    logger.info("  Step 3 time: %.1f s", time.perf_counter() - t0)

    # ── Step 4: Export NetCDF ─────────────────────────────────────────────
    t0 = time.perf_counter()
    logger.info("STEP 4/4: Exporting NetCDF ...")
    out_fname = f"COSMO_REA6_{year}_{month:02d}_all_attrs.nc"
    out_path = out_dir / out_fname
    nc_path = export_netcdf(ds_out, out_path, year=year)
    size_mb = nc_path.stat().st_size / (1024 * 1024)
    logger.info("  Step 4 time: %.1f s", time.perf_counter() - t0)

    elapsed = time.perf_counter() - t_total
    logger.info("=" * 68)
    logger.info(
        "Test PASSED  —  %s  (%.0f MB, total %.1f s)",
        nc_path.name, size_mb, elapsed,
    )
    logger.info("  Output: %s", nc_path)
    logger.info("=" * 68)

    # ── Cleanup decompressed GRIBs and cfgrib index/lock files ───────────
    # All dask computations are complete at this point (export_netcdf called
    # .compute() internally), so the .grb files are no longer needed.
    # Closing the xarray datasets releases cfgrib file handles before we
    # delete the files (required on Windows; harmless on Linux).
    if not args.no_cleanup and do_dc:
        logger.info(
            "  Closing GRIB datasets and removing intermediate files ..."
        )
        for _ds in datasets.values():
            _ds.close()
        cleanup_work_directory(
            dc_dir,
            cleanup_downloads=False,
            cleanup_decompressed=True,
            cleanup_locks=True,
        )

    # ── Post-export DNI outlier report ────────────────────────────────────
    if not args.skip_dni:
        _report_dni_outliers(nc_path, threshold=1400.0)


if __name__ == "__main__":
    main()
