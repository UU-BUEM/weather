"""End-to-end MERRA-2 weather processing pipeline.

Orchestrates, for one year:

    1. **Download** — fetch daily rad/slv/lnd NetCDF4 files (OPeNDAP,
       cropped to the configured Europe box) from NASA GES DISC.
    2. **Transform** — merge each month's ~90 daily files (3
       collections x ~30 days), convert units, derive GHI/WS_10M/RH.
    3. **Export** — write one compressed NetCDF-4 per month.

There is **no decompress phase**: MERRA-2 files are already NetCDF4.
DNI/DHI are **not** computed in bulk — see
:mod:`~weather.providers.merra2.transform`'s module docstring.

Pipeline flow
-------------
::

    run_pipeline(year=YYYY)
      ├── Phase 1 — Download (<=opendap_max_concurrent requests)
      │     3 collections x n_days -> download/MERRA2_<collection>_<YYYYMMDD>.nc4
      └── Phase 2 — Transform + Export (per month, process pool)
            merge daily rad+slv+lnd files -> GHI/WS_10M/RH
            -> output/MERRA2_<YYYY>_<MM>_all_attrs.nc

Typical usage::

    from weather.providers.merra2.pipeline import run_pipeline
    run_pipeline(year=2018)
"""

from __future__ import annotations

import calendar
import contextlib
import logging
import multiprocessing
import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from .config import get_config
from .download import download_all
from .downloader import Merra2Downloader, Merra2DownloadJob
from .export import export_netcdf, output_filename
from .transform import build_monthly_dataset

logger = logging.getLogger(__name__)

# Prevent HDF5 file-locking deadlocks on network/parallel file systems.
os.environ.setdefault("HDF5_USE_FILE_LOCKING", "FALSE")


# ---------------------------------------------------------------------------
# Per-month worker (top-level so ProcessPoolExecutor 'spawn' can pickle it)
# ---------------------------------------------------------------------------

def _transform_export_one(
    rad_paths: list[str],
    slv_paths: list[str],
    lnd_paths: list[str],
    year: int,
    month: int,
    output_dir: str,
    complevel: int,
    *,
    skip_existing: bool = False,
    cleanup: bool = False,
) -> str:
    """Transform + export one month.  Runs in a spawned worker process.

    Parameters
    ----------
    skip_existing : bool
        Skip if the output ``.nc`` already exists and is non-empty.
    cleanup : bool
        Remove the source daily files after a successful export.

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

    all_paths = (*rad_paths, *slv_paths, *lnd_paths)
    missing = [p for p in all_paths if not Path(p).exists()]
    if missing:
        return f"{year}-{month:02d}: FAIL (missing {len(missing)} daily file(s))"

    try:
        ds = build_monthly_dataset(
            [Path(p) for p in rad_paths],
            [Path(p) for p in slv_paths],
            [Path(p) for p in lnd_paths],
            year=year,
            month=month,
        )
        export_netcdf(
            ds,
            year=year,
            month=month,
            output_dir=Path(output_dir),
            complevel=complevel,
        )
        ds.close()
        if cleanup:
            for p in all_paths:
                with contextlib.suppress(OSError):
                    Path(p).unlink()
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
    complevel: int = 1,
    skip_download: bool = False,
    resume: bool = False,
    cleanup: bool | None = None,
) -> list[Path]:
    """Execute the MERRA-2 pipeline for *year*.

    Parameters
    ----------
    year : int, optional
        Target year (default: ``config["year"]``).
    months : list[int], optional
        Subset of months 1-12 (default: all).
    work_dir : Path, optional
        Override ``MERRA_WORK_DIR`` for this run.
    ncores : int, optional
        Worker processes for the transform phase (default:
        ``config["ncores"]``).  Capped at the number of months.
    complevel : int
        zlib level for NetCDF output (default 1).
    skip_download : bool
        Assume daily NetCDF4 files already present in ``download_dir``.
    resume : bool
        Skip months whose output ``.nc`` already exists.
    cleanup : bool, optional
        Remove the downloaded daily files after successful export.
        Default: ``config["cleanup"]`` (``MERRA_CLEANUP`` env var,
        itself defaulting to ``False`` -- keep everything).

    Returns
    -------
    list[Path]
        Paths of monthly NetCDF outputs (existing or freshly written).
    """
    if work_dir:
        os.environ["MERRA_WORK_DIR"] = str(work_dir)

    cfg = get_config()
    year = year or cfg["year"]
    months = months or list(range(1, 13))
    ncores = ncores or cfg["ncores"]
    cleanup = cfg["cleanup"] if cleanup is None else cleanup

    t0 = time.perf_counter()
    logger.info("=" * 60)
    logger.info("MERRA-2 Weather Pipeline")
    logger.info("  Year:        %d", year)
    logger.info("  Months:      %s", months)
    logger.info("  Work dir:    %s", cfg["work_dir"])
    logger.info("=" * 60)

    # ── Phase 1: Download ───────────────────────────────────────────
    if not skip_download:
        logger.info("STEP 1/2: Downloading daily NetCDF4 files")
        t1 = time.perf_counter()
        download_all(year=year, months=months)
        logger.info("  Download done in %.1f s", time.perf_counter() - t1)
    else:
        logger.info("STEP 1/2: Download skipped (--skip-download)")

    # Resolve daily file paths (2 collections x n_days) per month via
    # the downloader's own path logic.
    downloader = Merra2Downloader(cfg)

    def _daily_paths(month: int, collection: str) -> list[str]:
        n_days = calendar.monthrange(year, month)[1]
        return [
            str(downloader.local_path(
                Merra2DownloadJob(
                    collection=collection, year=year, month=month, day=d,
                )
            ))
            for d in range(1, n_days + 1)
        ]

    # ── Phase 2: Transform + Export (process pool over months) ──────
    logger.info("STEP 2/2: Transform + export (%d workers)", ncores)
    t2 = time.perf_counter()
    out_dir = cfg["output_dir"]
    out_dir.mkdir(parents=True, exist_ok=True)

    job_args = [
        (
            _daily_paths(m, "rad"),
            _daily_paths(m, "slv"),
            _daily_paths(m, "lnd"),
            year,
            m,
            str(out_dir),
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
                _transform_export_one, *a, skip_existing=resume,
                cleanup=cleanup,
            ): a[4]  # month (index shifted by the new lnd_paths arg)
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

    failures = [r for r in results if "FAIL" in r]
    elapsed = time.perf_counter() - t0
    logger.info("=" * 60)
    logger.info(
        "MERRA-2 pipeline %s: year %d (%.1f s)",
        "COMPLETE" if not failures else "COMPLETE WITH FAILURES",
        year, elapsed,
    )
    if failures:
        logger.error("  %d month(s) failed: %s", len(failures), failures)
    logger.info("=" * 60)

    return [out_dir / output_filename(year, m) for m in months]
