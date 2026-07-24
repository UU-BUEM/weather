#!/usr/bin/env python3
"""Full-year COSMO-REA6 pipeline: all 12 months, every attribute
registered in ``downloaded_attributes.ATTRIBUTES``.

test_cosmo_one_year.py
  └─ _decompress_all()
       └─ cosmo_rea6/decompress.py :: decompress_file()
            └─ common/decompress.py :: decompress_bz2_file()
                 ├─ detect_decompressor()   ← shutil.which("lbzip2"),
                 |                           then "pbzip2", then "python"
                 ├─ _decompress_external()  ← subprocess.run(
                 |                           ["lbzip2", "-d", "-n", "4", ...]
                 |                           )
                 └─ _decompress_python()    ← bz2.open(src) +
                                            shutil.copyfileobj()

Runs in three bulk phases:

  Phase 1 — Download:   all (month × attr) bz2 files in parallel,
                        up to min(n_tasks, ncores) concurrent threads.
                        With 96 cores and 12 months × 9 attrs = 108
                        tasks, all cores run simultaneously.

  Phase 2 — Decompress: all bz2 files in parallel,
                        up to min(n_tasks, ncores) processes.
                        bzip2 is CPU-bound; all cores engaged here.

  Phase 3 — Transform + Export: one month at a time so peak memory
                        stays bounded (~30 GB/month).  Dask uses all
                        allocated cores per month.  Decompressed .grb
                        files are removed after each month's NetCDF.

Output files
------------
One NetCDF per month: ``COSMO_REA6_<YYYY>_<MM>_all_attrs.nc``
All files written to ``<COSMO_WORK_DIR>/output/`` (or ``--work-dir``).

Note
----
Annual merge is a separate post-processing step, not part of this
script.  Use ``weather.common.merge.NetCDFMerger`` or the merge CLI::

    python -m weather.common.merge \\
        --input  <out_dir>/COSMO_REA6_<YYYY>_??_all_attrs.nc \\
        --output <out_dir>/COSMO_REA6_<YYYY>_annual_all_attrs.nc

Usage
-----
Basic (year 2018, 80 cores)::

    python src/weather/tests/test_cosmo_one_year.py --year 2018 --ncores 80

Resume an interrupted run (skips months whose output NC exists)::

    python src/weather/tests/test_cosmo_one_year.py --year 2018 --ncores 80 \\
        --resume

Process only specific months (e.g. re-run a failed month)::

    python src/weather/tests/test_cosmo_one_year.py --year 2018 --months 7,8

Full set of options::

    python src/weather/tests/test_cosmo_one_year.py \\
        --year 2018 --ncores 80 \\
        --work-dir /data/soma/cosmo_rea6 \\
        --resume

Flags
-----
--year YEAR             Four-digit year (default: 2018)
--ncores N              Total worker count (default: COSMO_NCORES or 4)
--work-dir DIR          Override COSMO_WORK_DIR for this run
--resume                Skip months whose output NetCDF already exists
--months M[,M,...]      Comma-separated months to process (default: 1-12)
--skip-download         Assume .grb.bz2 files are already present
--skip-decompress       Assume .grb files are already present
--skip-dni              Skip experimental per-cell DNI computation
--no-cleanup            Keep all intermediate files
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

from weather.settings import EnvSettings

if TYPE_CHECKING:
    import xarray  # noqa: F401

# Prevent HDF5 file-locking deadlocks on GPFS / NFS file systems (HPC).
os.environ.setdefault("HDF5_USE_FILE_LOCKING", "FALSE")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("cr6_year")


# ---------------------------------------------------------------------------
# Bulk download and decompress helpers (Phases 1 and 2)
# ---------------------------------------------------------------------------

def _download_all(
    months: list[int],
    year: int,
    attrs: list[str],
    dl_dir: Path,
    n_workers: int,
) -> None:
    """Download all (month, attr) .grb.bz2 files in parallel.

    Uses *n_workers* concurrent threads.  Files already on disk are
    skipped automatically by ``download_attribute_month``.
    """
    from weather.providers.cosmo_rea6.download import download_attribute_month

    tasks = [(m, a) for m in months for a in attrs]
    with ThreadPoolExecutor(max_workers=n_workers) as pool:
        futs = {
            pool.submit(
                download_attribute_month,
                attr, year, month,
                dest_dir=dl_dir / attr,
            ): (month, attr)
            for month, attr in tasks
        }
        for fut in as_completed(futs):
            month, attr = futs[fut]
            bz2 = fut.result()
            if bz2.stat().st_size == 0:
                raise RuntimeError(
                    f"Empty file after download: {bz2}"
                )
            logger.debug(
                "  [dl  done] %02d  %-12s  %s", month, attr, bz2.name,
            )


def _decompress_all(
    months: list[int],
    year: int,
    attrs: list[str],
    dl_dir: Path,
    dc_dir: Path,
    n_workers: int,
    threads: int,
) -> None:
    """Decompress all (month, attr) .grb.bz2 files in parallel.

    Uses *n_workers* processes (bzip2 is CPU-bound).  Raises
    ``FileNotFoundError`` if an expected bz2 file is missing.
    """
    from weather.providers.cosmo_rea6.decompress import decompress_file
    from weather.providers.cosmo_rea6.naming import grib_filename

    tasks = [(m, a) for m in months for a in attrs]
    bz2_map: dict[tuple[int, str], Path] = {}
    for month, attr in tasks:
        bz2_name = grib_filename(attr, year, month)
        bz2_path = dl_dir / attr / bz2_name
        if not bz2_path.exists():
            raise FileNotFoundError(
                f"Compressed file not found: {bz2_path}"
            )
        bz2_map[(month, attr)] = bz2_path

    with ProcessPoolExecutor(max_workers=n_workers) as pool:
        futs = {
            pool.submit(
                decompress_file,
                bz2_path,
                dest_dir=dc_dir / attr,
                threads=threads,
            ): (month, attr)
            for (month, attr), bz2_path in bz2_map.items()
        }
        for fut in as_completed(futs):
            month, attr = futs[fut]
            grb = fut.result()
            logger.info(
                "  [dc  done] %02d  %-12s  %s", month, attr, grb.name,
            )


# ---------------------------------------------------------------------------
# Post-phase integrity checks
# ---------------------------------------------------------------------------

# GRIB edition 1 and 2 files both begin with the ASCII string "GRIB".
_GRIB_MAGIC = b"GRIB"


def _verify_downloads(
    months: list[int],
    year: int,
    attrs: list[str],
    dl_dir: Path,
    n_workers: int,
) -> None:
    """Verify all (month × attr) bz2 files against the DWD Content-Length.

    Checks
    ------
    1. Every expected file exists and is non-empty.
    2. Local byte count matches the server's ``Content-Length`` header
       (parallel HEAD requests, up to *n_workers* concurrent).
       Files where DWD returns no ``Content-Length`` pass with a
       debug log rather than failing.

    Overhead: ~108 HEAD requests ÷ n_workers threads; with 96 workers
    this completes in 1–3 s (2 batches × ~50–150 ms RTT to DWD),
    negligible relative to the download phase.

    Raises ``RuntimeError`` listing every failing file.
    """
    from concurrent.futures import (  # noqa: PLC0415
        ThreadPoolExecutor,
        as_completed,
    )

    from weather.common.download import (  # noqa: PLC0415
        remote_size_https,
    )
    from weather.providers.cosmo_rea6.naming import (  # noqa: PLC0415
        grib_filename,
        grib_url,
    )

    tasks = [(m, a) for m in months for a in attrs]
    n_exp = len(tasks)
    logger.info(
        "  Verifying %d bz2 file sizes against DWD …", n_exp,
    )

    def _check(month: int, attr: str) -> tuple[str, str]:
        fname = grib_filename(attr, year, month)
        local = dl_dir / attr / fname
        if not local.exists() or local.stat().st_size == 0:
            return "missing", f"{attr}/{fname}"
        remote_sz = remote_size_https(grib_url(attr, year, month))
        if remote_sz is None:
            logger.debug(
                "  no Content-Length from DWD for %s/%s—skipped",
                attr, fname,
            )
            return "ok", ""
        local_sz = local.stat().st_size
        if local_sz != remote_sz:
            return "mismatch", (
                f"{attr}/{fname}: local={local_sz:,} B  "
                f"remote={remote_sz:,} B"
            )
        return "ok", ""

    missing: list[str] = []
    mismatches: list[str] = []
    with ThreadPoolExecutor(max_workers=min(n_exp, n_workers)) as pool:
        futs = {
            pool.submit(_check, m, a): (m, a)
            for m, a in tasks
        }
        for fut in as_completed(futs):
            kind, msg = fut.result()
            if kind == "missing":
                missing.append(str(msg))
            elif kind == "mismatch":
                mismatches.append(str(msg))

    issues: list[str] = []
    if missing:
        issues.append(
            f"Missing/empty ({len(missing)}):\n"
            + "\n".join(f"    {x}" for x in sorted(missing))
        )
    if mismatches:
        issues.append(
            f"Size mismatch ({len(mismatches)}):\n"
            + "\n".join(f"    {x}" for x in sorted(mismatches))
        )
    if issues:
        raise RuntimeError(
            "Download verification FAILED:\n" + "\n".join(issues)
        )
    logger.info(
        "  Download verification OK  (%d/%d files match DWD sizes)",
        n_exp, n_exp,
    )


def _verify_decompressed(
    months: list[int],
    year: int,
    attrs: list[str],
    dl_dir: Path,
    dc_dir: Path,
) -> None:
    """Verify all (month × attr) .grb files after Phase 2.

    Checks
    ------
    1. Every expected .grb exists and is non-empty.
    2. Decompressed size > compressed size (bzip2 always expands
       GRIB data; a file that didn't expand is truncated/corrupt).
    3. First 4 bytes are ``b"GRIB"`` (edition 1 or 2 magic number).

    Raises ``RuntimeError`` summarising every failing file.
    """
    from weather.providers.cosmo_rea6.naming import (  # noqa: PLC0415
        grib_filename,
    )

    tasks = [(m, a) for m in months for a in attrs]
    n_exp = len(tasks)
    logger.info("  Verifying %d decompressed .grb files ...", n_exp)

    bad: list[str] = []

    for month, attr in tasks:
        fname = grib_filename(attr, year, month)
        bz2_path = dl_dir / attr / fname
        grb_name = fname.removesuffix(".bz2")
        grb_path = dc_dir / attr / grb_name

        if not grb_path.exists():
            bad.append(f"Missing .grb: {attr}/{grb_name}")
            continue

        grb_sz = grb_path.stat().st_size
        if grb_sz == 0:
            bad.append(f"Empty .grb: {attr}/{grb_name}")
            continue

        # bzip2 always expands data; smaller-or-equal means truncation
        if bz2_path.exists():
            bz2_sz = bz2_path.stat().st_size
            if grb_sz <= bz2_sz:
                bad.append(
                    f"Not expanded: {attr}/{grb_name} "
                    f"({grb_sz:,} B \u2264 bz2 {bz2_sz:,} B)"
                )
                continue

        with open(grb_path, "rb") as fh:
            magic = fh.read(4)
        if magic != _GRIB_MAGIC:
            bad.append(
                f"Bad GRIB header: {attr}/{grb_name} "
                f"(got {magic!r})"
            )

    if bad:
        raise RuntimeError(
            f"Decompression verification FAILED "
            f"({len(bad)} issue(s)):\n"
            + "\n".join(f"  {b}" for b in bad)
        )
    logger.info(
        "  Decompress verification OK  (%d/%d files)", n_exp, n_exp,
    )


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Full-year COSMO-REA6 pipeline — all registered attributes "
            "(see downloaded_attributes.py), 12 months processed sequentially"
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--year", type=int, default=2018,
        help="Four-digit year",
    )
    p.add_argument(
        "--ncores", type=int, default=None, metavar="N",
        help="Total worker count (default: COSMO_NCORES env var or 4)",
    )
    p.add_argument(
        "--work-dir", default=None, metavar="DIR",
        help="Override COSMO_WORK_DIR for this run",
    )
    p.add_argument(
        "--resume", action="store_true",
        help=(
            "Skip months whose output NetCDF already exists "
            "(safe restart after a failure)"
        ),
    )
    p.add_argument(
        "--months", default=None, metavar="M[,M,...]",
        help="Comma-separated months to process (default: 1-12)",
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
        default=not EnvSettings.cosmo_cleanup(),
        help=(
            "Keep intermediate files (downloads, decompressed GRIBs, "
            "cfgrib index files).  Default: keep them (COSMO_CLEANUP=false, "
            "the default) unless COSMO_CLEANUP=true in .env, in which case "
            "intermediates are removed after each month's NetCDF is written "
            "and this flag is needed to opt back into keeping them."
        ),
    )
    args = p.parse_args()
    if args.months is not None:
        try:
            month_list = [
                int(m.strip()) for m in args.months.split(",")
            ]
            if not all(1 <= m <= 12 for m in month_list):
                raise ValueError
            args.months = month_list
        except ValueError:
            p.error(
                "--months must be comma-separated integers 1-12, "
                f"got: {args.months!r}"
            )
    else:
        args.months = list(range(1, 13))
    return args


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:  # noqa: C901 — intentionally long (pipeline steps)
    args = _parse_args()

    # Imports first so load_repo_env() runs (triggered by settings.py at
    # import time).  CLI overrides applied after so they win over .env.
    import dask  # noqa: PLC0415

    from weather.common.env import repo_root as _repo_root
    from weather.providers.cosmo_rea6.config import get_config
    from weather.providers.cosmo_rea6.export import export_netcdf
    from weather.providers.cosmo_rea6.naming import grib_filename
    from weather.providers.cosmo_rea6.transform import build_month_dataset

    # Shared helpers — import after path bootstrap to avoid circular issues.
    # logging.basicConfig in test_cosmo_one_month is a no-op here (already set).
    from weather.tests.test_cosmo_one_month import (  # noqa: PLC0415
        _ALL_ATTRS,
        _log_dni_stats,
        _report_dni_outliers,
    )

    # CLI overrides win over .env values (applied after load_repo_env).
    if args.work_dir:
        os.environ["COSMO_WORK_DIR"] = args.work_dir
    if args.ncores is not None:
        os.environ["COSMO_NCORES"] = str(args.ncores)

    try:
        import xarray  # noqa: F401 -- fail fast with a clear message below
    except ImportError:
        sys.exit(
            "xarray is not installed.  "
            "Run: conda install conda-forge::xarray"
        )

    cfg = get_config()
    year: int = args.year
    ncores: int = cfg["ncores"]
    threads: int = cfg["threads_per_job"]
    # Explicitly pin dask thread count so the full core budget is used
    # regardless of what os.cpu_count() returns in this SLURM context.
    dask.config.set(num_workers=ncores)
    dl_dir: Path = cfg["download_dir"]
    dc_dir: Path = cfg["decompress_dir"]
    out_dir: Path = cfg["output_dir"]
    log_dir: Path = cfg["log_dir"]
    months: list[int] = args.months
    do_dl = not args.skip_download
    do_dc = not args.skip_decompress

    for d in (dl_dir, dc_dir, out_dir, log_dir):
        d.mkdir(parents=True, exist_ok=True)

    # ── File logging ──────────────────────────────────────────────────────
    from datetime import datetime as _dt
    _ts = _dt.now().strftime("%Y%m%d_%H%M%S")
    _log_path = log_dir / f"COSMO_REA6_{year}_annual_{_ts}.log"
    _fh = logging.FileHandler(_log_path, encoding="utf-8")
    _fh.setLevel(logging.DEBUG)
    _fh.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logging.getLogger().addHandler(_fh)
    logger.info("Log file: %s", _log_path)

    # ── .env detection log ────────────────────────────────────────────────
    _root = _repo_root()
    _env_file = next(
        (
            p for p in (_root / ".env", Path.cwd() / ".env")
            if p.is_file()
        ),
        None,
    )
    if _env_file:
        logger.info(".env loaded from: %s", _env_file)
    else:
        logger.warning(
            "No .env file found.  "
            "Set WEATHER_DATA_DIR in a .env to control output location."
        )

    logger.info("=" * 68)
    logger.info(
        "COSMO-REA6 Annual Pipeline — all %d registered attributes",
        len(_ALL_ATTRS),
    )
    logger.info("  Year       : %d", year)
    logger.info(
        "  Months     : %s",
        ", ".join(f"{m:02d}" for m in months),
    )
    logger.info("  Attributes : %s", ", ".join(_ALL_ATTRS))
    logger.info(
        "  Cores      : %d  (threads/job: %d)", ncores, threads,
    )
    logger.info("  Work dir   : %s", cfg["work_dir"])
    logger.info("  Output dir : %s", out_dir)
    logger.info(
        "  Resume     : %s",
        "yes — skip existing months" if args.resume else "no",
    )
    logger.info(
        "  DNI        : %s",
        "skip (--skip-dni)" if args.skip_dni else "enabled",
    )
    logger.info("=" * 68)

    t_total = time.perf_counter()
    nc_paths: list[Path] = []
    skipped: list[int] = []
    failed: list[tuple[int, str]] = []

    # Determine which months actually need processing so the bulk phases
    # only download/decompress what the transform loop will consume.
    months_to_process = [
        m for m in months
        if not (
            args.resume
            and (out_dir / f"COSMO_REA6_{year}_{m:02d}_all_attrs.nc").exists()
        )
    ]

    # ── Phase 1/3: Bulk download ──────────────────────────────────────────
    # All (month × attr) bz2 pairs are independent — engage all cores.
    if do_dl and months_to_process:
        n_tasks = len(months_to_process) * len(_ALL_ATTRS)
        n_workers = min(n_tasks, ncores)
        t_ph = time.perf_counter()
        logger.info("")
        logger.info(
            "═══ Phase 1/3 — Bulk download: %d files  (%d threads) ═══",
            n_tasks, n_workers,
        )
        _download_all(months_to_process, year, _ALL_ATTRS, dl_dir, n_workers)
        logger.info(
            "═══ Phase 1/3 done  %.1f s ═══",
            time.perf_counter() - t_ph,
        )

    # ── Phase 2/3: Bulk decompress ────────────────────────────────────────
    # Same logic: up to 108 independent bzip2 tasks — engage all cores.
    if do_dc and months_to_process:
        n_tasks = len(months_to_process) * len(_ALL_ATTRS)
        n_workers = min(n_tasks, ncores)
        t_ph = time.perf_counter()
        logger.info("")
        logger.info(
            "═══ Phase 2/3 — Bulk decompress: %d files  (%d processes) ═══",
            n_tasks, n_workers,
        )
        _decompress_all(
            months_to_process, year, _ALL_ATTRS,
            dl_dir, dc_dir, n_workers, threads,
        )
        _verify_decompressed(
            months_to_process, year, _ALL_ATTRS, dl_dir, dc_dir,
        )
        # DWD Content-Length check — run synchronously here, before bz2
        # cleanup, so the local bz2 files still exist to be stat()'d.
        # Kept sequential (not concurrent with ProcessPoolExecutor) to
        # avoid the Linux fork-after-thread deadlock in shutdown(wait=True).
        # Wall time: < 60 s (2 rounds × 94 HEAD requests at 30 s max each).
        if do_dl:
            _verify_downloads(
                months_to_process, year, _ALL_ATTRS, dl_dir, n_workers,
            )
        logger.info(
            "═══ Phase 2/3 done  %.1f s ═══",
            time.perf_counter() - t_ph,
        )
        # bz2 deletion is gated: only runs after all verify steps pass.
        # Remove bz2 files only for the months we just processed.
        if do_dl and not args.no_cleanup:
            logger.info(
                "  Removing bz2 files for %d month(s) ...",
                len(months_to_process),
            )
            for _attr in _ALL_ATTRS:
                for _m in months_to_process:
                    _bz2 = dl_dir / _attr / grib_filename(_attr, year, _m)
                    if _bz2.exists():
                        try:
                            _bz2.unlink()
                            logger.debug("Deleted bz2: %s", _bz2.name)
                        except OSError as _e:
                            logger.warning(
                                "Could not delete %s: %s", _bz2, _e,
                            )

    # ── Phase 3/3: Transform + Export (sequential per month) ─────────────
    # Sequential because each month needs ~30 GB RAM; dask saturates all
    # cores within each month via the threaded scheduler.
    logger.info("")
    logger.info(
        "═══ Phase 3/3 — Transform + Export: %d months ═══", len(months),
    )

    for i, month in enumerate(months):
        out_fname = f"COSMO_REA6_{year}_{month:02d}_all_attrs.nc"
        out_path = out_dir / out_fname

        logger.info("")
        logger.info(
            "─── Month %02d/%02d  (%d-%02d) "
            "─────────────────────────────────",
            i + 1, len(months), year, month,
        )

        # ── Resume check ──────────────────────────────────────────────────
        if args.resume and out_path.exists():
            size_mb = out_path.stat().st_size / (1024 * 1024)
            logger.info(
                "  SKIP (--resume): %s already exists (%.0f MB)",
                out_fname, size_mb,
            )
            skipped.append(month)
            nc_paths.append(out_path)
            continue

        t_month = time.perf_counter()
        try:
            # ── Step 1+2: Open GRIBs + Transform ────────────────────────────
            # build_month_dataset() is the single shared assembly function
            # (also used by test_cosmo_one_month.py) -- see its docstring
            # and transform.py's module docstring for what it does.
            # dask.config.set(num_workers=ncores) was called before the
            # loop, so the threaded scheduler uses all allocated cores.
            # open_grib_month uses chunks={"time": 168} so the task graph
            # has enough parallelism to saturate those cores.
            t0 = time.perf_counter()
            logger.info(
                "  [1-2/3] Opening %d GRIB files + transforming "
                "(dask %d workers) ...", len(_ALL_ATTRS), ncores,
            )
            ds_out, datasets = build_month_dataset(
                year, month, compute_dni_field=not args.skip_dni,
            )
            if not args.skip_dni:
                logger.info("  Computing per-cell DNI (experimental) ...")
                _log_dni_stats(ds_out["DNI"], datasets["SWDIRS_RAD"])

            shapes = {k: list(v.shape) for k, v in ds_out.data_vars.items()}
            logger.info("  Variable shapes: %s", shapes)
            logger.info(
                "  [1-2/3] done %.1f s", time.perf_counter() - t0,
            )

            # ── Step 3: Export NetCDF ─────────────────────────────────────
            t0 = time.perf_counter()
            logger.info("  [3/3] Exporting NetCDF ...")
            nc_path = export_netcdf(ds_out, out_path, year=year)
            size_mb = nc_path.stat().st_size / (1024 * 1024)
            logger.info(
                "  [3/3] done %.1f s  (%.0f MB)",
                time.perf_counter() - t0, size_mb,
            )

            # ── Cleanup decompressed GRIBs and cfgrib index files ─────────
            # Delete only THIS month's .grb/.idx/.lock files so that the
            # next month's decompressed GRIBs are not prematurely removed.
            if not args.no_cleanup and do_dc:
                logger.info(
                    "  Removing GRIBs for month %02d ...", month,
                )
                for _ds in datasets.values():
                    _ds.close()
                for _attr in _ALL_ATTRS:
                    _grb_name = (
                        grib_filename(_attr, year, month)
                        .removesuffix(".bz2")
                    )
                    _grb = dc_dir / _attr / _grb_name
                    for _p in [
                        _grb,
                        _grb.parent / (_grb.name + ".idx"),
                        _grb.parent / (_grb.name + ".lock"),
                    ]:
                        if _p.exists():
                            try:
                                _p.unlink()
                                logger.debug("Deleted: %s", _p.name)
                            except OSError as _e:
                                logger.warning(
                                    "Could not delete %s: %s", _p, _e,
                                )

            # ── DNI outlier report ────────────────────────────────────────
            if not args.skip_dni:
                _report_dni_outliers(nc_path, threshold=1400.0)

            month_elapsed = time.perf_counter() - t_month
            logger.info(
                "  Month %02d done  %s  (%.0f MB)  %.1f s",
                month, nc_path.name, size_mb, month_elapsed,
            )
            nc_paths.append(nc_path)

        except Exception as exc:  # noqa: BLE001
            month_elapsed = time.perf_counter() - t_month
            logger.error(
                "  Month %02d FAILED after %.1f s: %s",
                month, month_elapsed, exc,
                exc_info=True,
            )
            failed.append((month, str(exc)))

    # ── Final summary ─────────────────────────────────────────────────────
    total_elapsed = time.perf_counter() - t_total
    total_size_mb = sum(
        p.stat().st_size / (1024 * 1024)
        for p in nc_paths if p.exists()
    )
    logger.info("")
    logger.info("=" * 68)
    logger.info("COSMO-REA6 Annual Pipeline — COMPLETE")
    logger.info("  Year         : %d", year)
    logger.info(
        "  Processed    : %d  month(s)",
        len(nc_paths) - len(skipped),
    )
    if skipped:
        logger.info(
            "  Skipped      : %s  (--resume)",
            ", ".join(f"{m:02d}" for m in skipped),
        )
    if failed:
        logger.error(
            "  FAILED       : %s",
            ", ".join(f"{m:02d}" for m, _ in failed),
        )
    logger.info(
        "  Total size   : %.0f MB  (%d file(s))",
        total_size_mb, len(nc_paths),
    )
    logger.info("  Total time   : %.1f s", total_elapsed)
    logger.info("  Output dir   : %s", out_dir)
    logger.info("=" * 68)

    # ── Cleanup empty attribute subdirectories ────────────────────────────
    # After all months complete, the per-attribute folders under dl_dir and
    # dc_dir should be empty (files were deleted above).  Try to rmdir each
    # one.  rmdir fails silently if a folder is non-empty (e.g. another year
    # is still running with --parallel-years), so this is always safe.
    if not args.no_cleanup:
        for _parent in (dl_dir, dc_dir):
            if not _parent.exists():
                continue
            for _attr_dir in sorted(_parent.iterdir()):
                if _attr_dir.is_dir():
                    try:
                        _attr_dir.rmdir()
                        logger.debug(
                            "Removed empty attr dir: %s", _attr_dir,
                        )
                    except OSError:
                        pass  # non-empty — another year still running, skip

    if failed:
        sys.exit(
            f"{len(failed)} month(s) failed: "
            + ", ".join(str(m) for m, _ in failed)
        )


if __name__ == "__main__":
    main()
