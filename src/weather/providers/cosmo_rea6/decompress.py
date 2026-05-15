"""Decompress COSMO-REA6 ``.grb.bz2`` files to raw GRIB.

Three strategies are supported — chosen automatically or via the
``COSMO_DECOMPRESSOR`` environment variable:

1. **pbzip2** — parallel BZIP2 (fastest on multi-core servers).
2. **lbzip2** — alternative parallel BZIP2.
3. **Python bz2** — stdlib fallback; no external tools needed.

The decompressor writes to a temporary file and atomically renames it to
the target name, so a crash never leaves a half-written GRIB file.

Typical usage::

    from buem.weather.decompress import decompress_file
    grb = decompress_file(Path("SWDIRS_RAD.2D.201801.grb.bz2"))
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from ...common.decompress import decompress_bz2_file, detect_decompressor
from .config import get_config

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Decompressor detection
# ---------------------------------------------------------------------------

def _detect_decompressor() -> str:
    """Return the best available decompressor command name.

    Checks ``COSMO_DECOMPRESSOR`` env var first, then probes the ``PATH``
    for ``lbzip2`` and ``pbzip2`` in order.  Falls back to ``"python"``
    which triggers the pure-Python :mod:`bz2` path.

    lbzip2 is preferred over pbzip2 because it scales better with many
    cores and has lower per-thread overhead.

    Returns
    -------
    str
        One of ``"lbzip2"``, ``"pbzip2"``, or ``"python"``.
    """
    cfg = get_config()
    preferred = cfg["decompressor"]
    return detect_decompressor(preferred=preferred)


# ---------------------------------------------------------------------------
# Per-strategy decompression
# ---------------------------------------------------------------------------

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
    months: list[int] | None = None,
    threads: int | None = None,
) -> list[Path]:
    """Decompress all ``.grb.bz2`` files for the configured attributes/year.

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
    attributes, year, months : optional
        Override the defaults from :func:`~buem.weather.config.get_config`.
    threads : int, optional
        Threads per decompress job.

    Returns
    -------
    list[Path]
        Paths to all decompressed ``.grb`` files.
    """
    from .config import grib_filename

    cfg = get_config()
    src_dir = src_dir or cfg["download_dir"]
    dest_dir = dest_dir or cfg["decompress_dir"]
    attributes = attributes or cfg["attributes"]
    year = year or cfg["year"]
    months = months or cfg["months"]

    jobs: list[tuple[Path, Path]] = []
    for attr in attributes:
        for m in months:
            bz2_name = grib_filename(attr, year, m)
            bz2_path = src_dir / attr / bz2_name
            if not bz2_path.exists():
                logger.warning("Missing compressed file: %s", bz2_path)
                continue
            jobs.append((bz2_path, dest_dir / attr))

    if not jobs:
        logger.warning("No files found to decompress.")
        return []

    # Strategy: decompress multiple files concurrently, dividing total
    # cores across concurrent jobs.  For N files and C total cores:
    #   - parallel_files = min(N, max(2, C // 4))
    #   - threads_per_file = max(1, C // parallel_files)
    # This keeps all cores busy while avoiding I/O contention.
    ncores = cfg["ncores"]
    n_files = len(jobs)
    parallel_files = min(n_files, max(2, ncores // 4))
    threads_per_file = threads or max(1, ncores // parallel_files)

    decompressor = _detect_decompressor()
    logger.info(
        "Decompressing %d files: %d concurrent jobs × %d threads (%s)",
        n_files, parallel_files, threads_per_file, decompressor,
    )

    def _do_decompress(args: tuple[Path, Path]) -> Path:
        bz2_path, out_dir = args
        return decompress_file(
            bz2_path, dest_dir=out_dir, threads=threads_per_file,
        )

    output_paths: list[Path] = []
    with ThreadPoolExecutor(max_workers=parallel_files) as pool:
        futures = {pool.submit(_do_decompress, j): j for j in jobs}
        for future in as_completed(futures):
            bz2_path, _ = futures[future]
            try:
                grb = future.result()
                output_paths.append(grb)
            except Exception:
                logger.exception("Failed to decompress %s", bz2_path)
                raise

    logger.info("Decompressed %d files.", len(output_paths))
    return output_paths
