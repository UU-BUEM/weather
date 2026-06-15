"""End-to-end COSMO-REA6 weather processing pipeline.

Orchestrates the full workflow:

    1. **Download** — fetch ``.grb.bz2`` files from DWD OpenData.
    2. **Decompress** — parallel bz2 decompression to raw GRIB.
    3. **Transform** — read GRIB with xarray/cfgrib, convert units,
       compute derived fields (GHI, DHI, T, WS_10M).
    4. **Export** — write a single compressed NetCDF-4 file.

Each step is idempotent: re-running skips files that are already
present and have the expected size.

Pipeline flow
-------------
::

    pipeline.run_pipeline(year=YYYY)
      │
      ├── Phase 1 — Download (ThreadPoolExecutor, up to ncores workers)
      │     9 attributes × 12 months = 108 tasks
      │     DWD OpenData HTTPS  →  download/<attr>/<attr>.2D.<YYYYMM>.grb.bz2
      │     (skip if bz2 present and valid size)
      │
      ├── Phase 2 — Decompress (ProcessPoolExecutor, up to ncores workers)
      │     108 bz2 files → decompress/<attr>/<attr>.2D.<YYYYMM>.grb
      │     lbzip2 / pbzip2 / python-bz2 fallback
      │     Cleanup: delete bz2 after successful decompress
      │
      └── Phase 3 — Transform + Export (per month, up to ncores workers)
            For each of 12 months:
              cfgrib.open_datasets  →  xarray.Dataset (dask-backed)
              apply_derived_fields  →  GHI, DHI, T, WS_10M, DNI …
              export.to_netcdf  →  output/COSMO_REA6_<YYYY>_<MM>_all_attrs.nc
              cleanup: delete GRIB files for this month

Typical usage (from Python)::

    from weather.providers.cosmo_rea6.pipeline import run_pipeline
    nc_path = run_pipeline(year=2018)

From the CLI::

    weather run --year 2018
    weather run           # uses COSMO_YEAR from .env / env var
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# Prevent HDF5 file-locking deadlocks on network/parallel file systems (GPFS).
os.environ.setdefault("HDF5_USE_FILE_LOCKING", "FALSE")


def run_pipeline(
    year: int | None = None,
    attributes: list[str] | None = None,
    *,
    work_dir: Path | None = None,
    output_path: Path | None = None,
    include_wind_components: bool = True,
    complevel: int = 1,
    skip_download: bool = False,
    skip_decompress: bool = False,
    cleanup: bool = False,
) -> Path:
    """Execute the full weather processing pipeline.

    Parameters
    ----------
    year : int, optional
        Target year (default from config: 2018).
    attributes : list[str], optional
        COSMO-REA6 attributes (default: all five).
    work_dir : Path, optional
        Override the root working directory.
    output_path : Path, optional
        Override the output NetCDF file path.
    include_wind_components : bool
        Keep raw U_10M / V_10M in the NetCDF (default ``True``).
    complevel : int
        zlib compression level for NetCDF (default 5).
    skip_download : bool
        Skip downloading (assume ``.grb.bz2`` files already present).
    skip_decompress : bool
        Skip decompression (assume ``.grb`` files already present).

    Returns
    -------
    Path
        Path to the output NetCDF file.
    """
    from .config import get_config
    from .decompress import decompress_all
    from .download import download_all
    from .export import export_netcdf
    from .transform import build_annual_dataset

    cfg = get_config()
    year = year or cfg["year"]
    attributes = attributes or cfg["attributes"]

    # Allow work_dir override
    if work_dir:
        import os
        os.environ["COSMO_WORK_DIR"] = str(work_dir)
        cfg = get_config()  # re-resolve

    t0 = time.perf_counter()
    logger.info("=" * 60)
    logger.info("COSMO-REA6 Weather Pipeline")
    logger.info("  Year:       %d", year)
    logger.info("  Attributes: %s", attributes)
    logger.info("  Work dir:   %s", cfg["work_dir"])
    logger.info("=" * 60)

    # Step 1: Download
    if not skip_download:
        logger.info("STEP 1/4: Downloading GRIB files")
        t1 = time.perf_counter()
        download_all(year=year, attributes=attributes)
        logger.info("  Download completed in %.1f s", time.perf_counter() - t1)
    else:
        logger.info("STEP 1/4: Download skipped (--skip-download)")

    # Step 2: Decompress
    if not skip_decompress:
        logger.info("STEP 2/4: Decompressing GRIB files")
        t2 = time.perf_counter()
        decompress_all(
            attributes=attributes, year=year,
        )
        logger.info(
            "  Decompress completed in %.1f s",
            time.perf_counter() - t2,
        )
    else:
        logger.info("STEP 2/4: Decompress skipped (--skip-decompress)")

    # Step 3: Transform
    logger.info("STEP 3/4: Transforming to analysis-ready variables")
    t3 = time.perf_counter()
    ds = build_annual_dataset(
        year=year,
        include_wind_components=include_wind_components,
    )
    logger.info("  Transform completed in %.1f s", time.perf_counter() - t3)

    # Step 4: Export
    logger.info("STEP 4/4: Exporting to NetCDF")
    t4 = time.perf_counter()
    nc_path = export_netcdf(
        ds,
        output_path=output_path,
        complevel=complevel,
        year=year,
    )
    logger.info("  Export completed in %.1f s", time.perf_counter() - t4)

    # Step 5: Cleanup (optional)
    if cleanup:
        import shutil

        logger.info("STEP 5: Cleaning up downloaded and decompressed files")
        for dir_key in ("download_dir", "decompress_dir"):
            d = Path(cfg[dir_key])
            if d.exists():
                shutil.rmtree(d)
                logger.info("  Removed %s", d)

    elapsed = time.perf_counter() - t0
    logger.info("=" * 60)
    logger.info("Pipeline complete: %s (%.1f s total)", nc_path, elapsed)
    logger.info("=" * 60)

    return nc_path


def validate_environment() -> list[str]:
    """Check that all required tools and libraries are available.

    Returns
    -------
    list[str]
        List of issues found (empty = all OK).
    """
    issues: list[str] = []

    # Python packages
    for pkg in ("xarray", "cfgrib", "netCDF4", "pyproj", "eccodes"):
        try:
            __import__(pkg)
        except ImportError:
            issues.append(
                f"Python package '{pkg}' not installed.  "
                f"Install with: conda install conda-forge::{pkg}"
            )

    # External decompressors (optional but recommended)
    import shutil
    for cmd in ("pbzip2", "lbzip2"):
        if shutil.which(cmd):
            break
    else:
        issues.append(
            "No parallel decompressor found (pbzip2 or lbzip2).  "
            "The Python bz2 fallback is much slower.  "
            "Install with: conda install conda-forge::pbzip2"
        )

    # Config sanity
    from .config import get_config
    cfg = get_config()
    if cfg["year"] < 1995 or cfg["year"] > 2019:
        issues.append(
            f"COSMO_YEAR={cfg['year']} is outside COSMO-REA6 range "
            "(1995-2019)."
        )

    # Path validation and writable checks
    path_issues = _validate_paths(cfg)
    issues.extend(path_issues)

    return issues


def _validate_paths(cfg: dict) -> list[str]:
    """Validate that all required directories exist and are writable.

    Parameters
    ----------
    cfg : dict
        Pipeline configuration dictionary.

    Returns
    -------
    list[str]
        List of path validation issues (empty = all OK).
    """
    issues: list[str] = []
    import os

    # Check work directory
    work_dir = cfg["work_dir"]
    try:
        work_dir.mkdir(parents=True, exist_ok=True)
    except (OSError, PermissionError) as exc:
        issues.append(
            f"Cannot create work directory {work_dir}: {exc}"
        )
        return issues

    # Check subdirectories are writable
    for dir_key in ("download_dir", "decompress_dir", "output_dir"):
        dir_path = Path(cfg[dir_key])
        try:
            dir_path.mkdir(parents=True, exist_ok=True)
        except (OSError, PermissionError) as exc:
            issues.append(
                f"Cannot create {dir_key} {dir_path}: {exc}"
            )
            continue

        # Test writability by creating a temporary file
        try:
            test_file = dir_path / ".write_test"
            test_file.touch()
            test_file.unlink()
        except (OSError, PermissionError) as exc:
            issues.append(
                f"Directory {dir_path} is not writable: {exc}"
            )

    # Check available disk space (require at least 10GB free)
    # Only on Unix-like systems (Linux, macOS), not on Windows
    if hasattr(os, 'statvfs'):
        try:
            stat = os.statvfs(work_dir)
            free_gb = stat.f_bavail * stat.f_frsize / (1024 ** 3)
            if free_gb < 10:
                issues.append(
                    f"Insufficient disk space on {work_dir}: "
                    f"{free_gb:.1f} GB free (minimum 10 GB required)"
                    )
        except (OSError, AttributeError):
            # statvfs not available on Windows, skip disk space check
            pass

    return issues
