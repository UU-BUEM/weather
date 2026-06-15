"""Decompress COSMO-REA6 ``.grb.bz2`` files to raw GRIB.

Three strategies are supported — chosen automatically or via the
``COSMO_DECOMPRESSOR`` environment variable:

1. **lbzip2** — parallel BZIP2 (preferred; lowest per-thread overhead).
2. **pbzip2** — parallel BZIP2 (fallback if lbzip2 is absent).
3. **Python bz2** — stdlib fallback; no external tools needed.

The decompressor writes to a temporary file and atomically renames it
to the target name, so a crash never leaves a half-written GRIB file.

:func:`decompress_all` uses
:class:`~weather.providers.cosmo_rea6.decompressor.CosmoDecompressor`
for check-before-decompress logic and
:func:`~weather.common.parallel.run_parallel` for concurrent execution.

Typical usage::

    from weather.providers.cosmo_rea6.decompress import decompress_file
    grb = decompress_file(Path("SWDIRS_RAD.2D.201801.grb.bz2"))
"""

from __future__ import annotations

import logging
from pathlib import Path

from ...common.decompress import decompress_bz2_file
from ...common.parallel import run_parallel
from ..base_downloader import DownloadJob
from .config import get_config
from .decompressor import CosmoDecompressor

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def decompress_file(
    src: Path,
    *,
    dest_dir: Path | None = None,
    threads: int | None = None,
) -> Path:
    """Decompress a single ``.grb.bz2`` file to GRIB.

    If the output already exists and is non-empty, decompression is skipped.

    Parameters
    ----------
    src : Path
        Path to the compressed ``.grb.bz2`` file.
    dest_dir : Path, optional
        Directory for the decompressed output.  Defaults to same directory
        as *src* with ``.bz2`` stripped.
    threads : int, optional
        Threads for pbzip2/lbzip2 (default from config).

    Returns
    -------
    Path
        Path to the decompressed ``.grb`` file.
    """
    grb_name = src.name.removesuffix(".bz2")
    if dest_dir is None:
        dest = src.parent / grb_name
    else:
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / grb_name

    cfg = get_config()
    threads = threads or cfg["threads_per_job"]
    return decompress_bz2_file(
        src,
        dest=dest,
        threads=threads,
        preferred_decompressor=cfg["decompressor"],
        logger=logger,
    )


def decompress_all(
    src_dir: Path | None = None,
    *,
    dest_dir: Path | None = None,
    attributes: list[str] | None = None,
    year: int | None = None,
    threads: int | None = None,
) -> list[Path]:
    """Decompress all ``.grb.bz2`` files for a full year.

    All twelve months (January–December) are always processed.

    Parameters
    ----------
    src_dir : Path, optional
        Root directory containing per-attribute sub-dirs with
        ``.grb.bz2`` files.
        Defaults to ``<work_dir>/download/``.
    dest_dir : Path, optional
        Root directory for decompressed output
        (per-attribute sub-dirs created).
        Defaults to ``<work_dir>/decompress/``.
    attributes, year : optional
        Override config defaults.
    threads : int, optional
        Threads per decompress job.

    Returns
    -------
    list[Path]
        Paths to all decompressed ``.grb`` files.
    """
    cfg = get_config()
    src_dir = src_dir or cfg["download_dir"]
    attributes = attributes or cfg["attributes"]
    year = year or cfg["year"]
    if dest_dir is not None:
        cfg = {**cfg, "decompress_dir": dest_dir}
    if threads is not None:
        cfg = {**cfg, "threads_per_job": threads}

    # Build DownloadJob list — skip jobs whose source file is absent.
    from .naming import grib_filename

    dc = CosmoDecompressor(cfg)
    jobs: list[DownloadJob] = []
    for attr in attributes:
        for m in range(1, 13):
            bz2_name = grib_filename(attr, year, m)
            bz2_path = src_dir / attr / bz2_name
            if not bz2_path.exists():
                logger.warning(
                    "Missing compressed file: %s", bz2_path
                )
                continue
            jobs.append(
                DownloadJob(attribute=attr, year=year, month=m)
            )

    if not jobs:
        logger.warning("No files found to decompress.")
        return []

    # Strategy: decompress multiple files concurrently.
    # For N files and C total cores:
    #   parallel_files = min(N, max(2, C // 4))
    #   threads_per_file = max(1, C // parallel_files)
    ncores = cfg["ncores"]
    n_files = len(jobs)
    parallel_files = min(n_files, max(2, ncores // 4))
    logger.info(
        "Decompressing %d files: %d concurrent jobs",
        n_files,
        parallel_files,
    )

    output_paths = run_parallel(
        fn=dc.get,
        jobs=jobs,
        max_workers=parallel_files,
        logger=logger,
    )
    logger.info("Decompressed %d files.", len(output_paths))
    return output_paths
