"""End-to-end ERA5-Land weather processing pipeline.

Orchestrates, for one year:

    1. **Download** — fetch monthly all-variables GRIB from the
       Copernicus CDS API (low concurrency; queue-based).
    2. **Transform** — read GRIB with cfgrib, convert units,
       de-accumulate ssrd → hourly-mean GHI, Spencer night-mask.
    3. **Export** — write one compressed NetCDF-4 per month.

There is **no decompress phase**: ERA5-Land ``unarchived`` GRIB is a
plain file (unlike COSMO-REA6's ``.grb.bz2``).  DNI/DHI are **not**
computed in bulk — see
:mod:`~weather.providers.era5_land.dni_pointwise`.

Pipeline flow
-------------
::

    run_pipeline(year=YYYY)
      ├── Phase 1 — Download (<=cds_max_concurrent CDS requests)
      │     12 months → download/ERA5_LAND_<YYYY>_<MM>_all_attrs.grib
      └── Phase 2 — Transform + Export (per month, process pool)
            cfgrib read → deaccum ssrd → GHI → night-mask
            → output/ERA5_LAND_<YYYY>_<MM>_all_attrs.nc

Output files for all years land in a single ``output/`` folder, ready
for ``common.merge`` (annual concat) and ``common.percentile_index``.

Typical usage::

    from weather.providers.era5_land.pipeline import run_pipeline
    run_pipeline(year=2018)
"""

from __future__ import annotations

import contextlib
import logging
import multiprocessing
import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from ..base_downloader import DownloadJob
from .config import get_config
from .download import download_all
from .downloader import ALL_ATTRS, Era5Downloader
from .export import export_netcdf, output_filename
from .transform import build_monthly_dataset

logger = logging.getLogger(__name__)

# Prevent HDF5 file-locking deadlocks on network/parallel file systems.
os.environ.setdefault("HDF5_USE_FILE_LOCKING", "FALSE")


# ---------------------------------------------------------------------------
# Per-month worker (top-level so ProcessPoolExecutor 'spawn' can pickle it)
# ---------------------------------------------------------------------------

def _transform_export_one(
    grib_path: str,
    year: int,
    month: int,
    output_dir: str,
    night_mask: bool,
    complevel: int,
    *,
    skip_existing: bool = False,
    cleanup: bool = False,
) -> str:
    """Transform + export one month.  Runs in a spawned worker process.

    Shared by :func:`run_pipeline` and
    :func:`~weather.providers.era5_land.pipeline_interleaved.run_interleaved`.

    Parameters
    ----------
    skip_existing : bool
        Skip if the output ``.nc`` already exists and is non-empty.
    cleanup : bool
        Remove the source GRIB after a successful export.

    Returns
    -------
    str
        Status string, e.g. ``"2018-01: OK"`` or a skip/fail reason.
    """
    os.environ["HDF5_USE_FILE_LOCKING"] = "FALSE"
    log = logging.getLogger(__name__)

    out_path = Path(output_dir) / output_filename(year, month)
    if skip_existing and out_path.exists() and out_path.stat().st_size > 0:
        return f"{year}-{month:02d}: skipped (exists)"

    if not Path(grib_path).exists():
        return f"{year}-{month:02d}: FAIL (missing GRIB {grib_path})"

    try:
        ds = build_monthly_dataset(grib_path, night_mask=night_mask)
        export_netcdf(
            ds,
            year=year,
            month=month,
            output_dir=Path(output_dir),
            complevel=complevel,
        )
        ds.close()
        if cleanup:
            with contextlib.suppress(OSError):
                Path(grib_path).unlink()
        return f"{year}-{month:02d}: OK"
    except Exception as exc:  # noqa: BLE001 - report, don't crash pool
        log.exception("Transform/export failed for %d-%02d", year, month)
        return f"{year}-{month:02d}: FAIL ({exc})"


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def run_pipeline(
    year: int | None = None,
    months: list[int] | None = None,
    *,
    work_dir: Path | None = None,
    ncores: int | None = None,
    night_mask: bool = False,
    complevel: int = 1,
    skip_download: bool = False,
    resume: bool = False,
    cleanup: bool = False,
) -> list[Path]:
    """Execute the ERA5-Land pipeline for *year*.

    Parameters
    ----------
    year : int, optional
        Target year (default: ``config["year"]``).
    months : list[int], optional
        Subset of months 1-12 (default: all).
    work_dir : Path, optional
        Override ``ERA5_WORK_DIR`` for this run.
    ncores : int, optional
        Worker processes for the transform phase (default:
        ``config["ncores"]``).  Capped at the number of months.
    night_mask : bool
        Apply Spencer SZA night-masking to GHI (default False).
    complevel : int
        zlib level for NetCDF output (default 1).
    skip_download : bool
        Assume monthly GRIBs already present in ``download_dir``.
    resume : bool
        Skip months whose output ``.nc`` already exists.
    cleanup : bool
        Remove the downloaded GRIB(s) after successful export.

    Returns
    -------
    list[Path]
        Paths of monthly NetCDF outputs (existing or freshly written).
    """
    if work_dir:
        os.environ["ERA5_WORK_DIR"] = str(work_dir)

    cfg = get_config()
    year = year or cfg["year"]
    months = months or list(range(1, 13))
    ncores = ncores or cfg["ncores"]

    t0 = time.perf_counter()
    logger.info("=" * 60)
    logger.info("ERA5-Land Weather Pipeline")
    logger.info("  Year:        %d", year)
    logger.info("  Months:      %s", months)
    logger.info("  Work dir:    %s", cfg["work_dir"])
    logger.info("  Night mask:  %s", night_mask)
    logger.info("=" * 60)

    # ── Phase 1: Download ───────────────────────────────────────────
    if not skip_download:
        logger.info("STEP 1/2: Downloading monthly GRIB files")
        t1 = time.perf_counter()
        download_all(year=year, months=months)
        logger.info("  Download done in %.1f s", time.perf_counter() - t1)
    else:
        logger.info("STEP 1/2: Download skipped (--skip-download)")

    # Resolve GRIB paths via the downloader's own path logic.
    downloader = Era5Downloader(cfg)

    grib_paths = {
        m: downloader.local_path(
            DownloadJob(attribute=ALL_ATTRS, year=year, month=m)
        )
        for m in months
    }

    # ── Phase 2: Transform + Export (process pool over months) ──────
    logger.info("STEP 2/2: Transform + export (%d workers)", ncores)
    t2 = time.perf_counter()
    out_dir = cfg["output_dir"]
    out_dir.mkdir(parents=True, exist_ok=True)

    job_args = [
        (
            str(grib_paths[m]),
            year,
            m,
            str(out_dir),
            night_mask,
            complevel,
        )
        for m in months
    ]

    workers = max(1, min(ncores, len(job_args)))
    ctx = multiprocessing.get_context("spawn")
    results: list[str] = []
    with ProcessPoolExecutor(max_workers=workers, mp_context=ctx) as pool:
        futures = {
            pool.submit(
                _transform_export_one, *a, skip_existing=resume
            ): a[2]
            for a in job_args
        }
        for fut in as_completed(futures):
            msg = fut.result()
            results.append(msg)
            if "FAIL" in msg:
                logger.error("  %s", msg)
            else:
                logger.info("  %s", msg)

    logger.info("  Transform+export done in %.1f s", time.perf_counter() - t2)

    # ── Optional cleanup of GRIBs ───────────────────────────────────
    if cleanup:
        for m, gp in grib_paths.items():
            out_path = out_dir / output_filename(year, m)
            if out_path.exists() and gp.exists():
                try:
                    gp.unlink()
                    logger.info("  Removed GRIB: %s", gp.name)
                except OSError as exc:
                    logger.warning("  Could not remove %s: %s", gp, exc)

    failures = [r for r in results if "FAIL" in r]
    elapsed = time.perf_counter() - t0
    logger.info("=" * 60)
    logger.info(
        "ERA5-Land pipeline %s: year %d (%.1f s)",
        "COMPLETE" if not failures else "COMPLETE WITH FAILURES",
        year, elapsed,
    )
    if failures:
        logger.error("  %d month(s) failed: %s", len(failures), failures)
    logger.info("=" * 60)

    return [out_dir / output_filename(year, m) for m in months]
