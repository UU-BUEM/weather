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
    months: list[int] | None = None,
    threads: int | None = None,
    max_workers: int | None = None,
) -> list[Path]:
    """Decompress ``.grb.bz2`` files for one or more months.

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
    months : list[int], optional
        Months to decompress (default: all 12).
    threads : int, optional
        bzip2 threads per decompress job (default: config
        ``threads_per_job``, normally 1 -- see *max_workers* below).
    max_workers : int, optional
        Concurrent decompress jobs (default: ``min(n_tasks, ncores)``,
        i.e. one job per core when ``threads_per_job=1``; lower this if
        *threads* > 1 to avoid oversubscription).

    Returns
    -------
    list[Path]
        Paths to all decompressed ``.grb`` files.
    """
    cfg = get_config()
    src_dir = src_dir or cfg["download_dir"]
    attributes = attributes or cfg["attributes"]
    year = year or cfg["year"]
    months = months or list(range(1, 13))
    if dest_dir is not None:
        cfg = {**cfg, "decompress_dir": dest_dir}
    if threads is not None:
        cfg = {**cfg, "threads_per_job": threads}

    # Build DownloadJob list — skip jobs whose source file is absent.
    from .naming import grib_filename

    dc = CosmoDecompressor(cfg)
    jobs: list[DownloadJob] = []
    for attr in attributes:
        for m in months:
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

    if max_workers is None:
        max_workers = min(len(jobs), cfg["ncores"])
    logger.info(
        "Decompressing %d files: %d concurrent jobs",
        len(jobs),
        max_workers,
    )

    output_paths = run_parallel(
        fn=dc.get,
        jobs=jobs,
        max_workers=max_workers,
        logger=logger,
    )
    logger.info("Decompressed %d files.", len(output_paths))
    return output_paths


# GRIB edition 1 and 2 files both begin with the ASCII string "GRIB".
_GRIB_MAGIC = b"GRIB"


def verify_decompressed(
    year: int,
    attributes: list[str],
    months: list[int],
    dl_dir: Path,
    dc_dir: Path,
) -> None:
    """Verify every (month, attribute) decompressed ``.grb`` file.

    Checks each file exists, is non-empty, expanded relative to its
    source ``.bz2`` (bzip2 always expands GRIB data -- a same-or-smaller
    size means truncation), and begins with the GRIB magic number.

    Parameters
    ----------
    year : int
        Target year.
    attributes : list[str]
        Attributes expected to have been decompressed.
    months : list[int]
        Months expected to have been decompressed.
    dl_dir : Path
        Root download directory (for the bz2-size comparison).
    dc_dir : Path
        Root decompress directory (per-attribute subdirs).

    Raises
    ------
    RuntimeError
        Summarising every failing file.
    """
    from .naming import grib_filename

    tasks = [(m, a) for m in months for a in attributes]
    n_exp = len(tasks)
    logger.info("Verifying %d decompressed .grb files ...", n_exp)

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

        if bz2_path.exists():
            bz2_sz = bz2_path.stat().st_size
            if grb_sz <= bz2_sz:
                bad.append(
                    f"Not expanded: {attr}/{grb_name} "
                    f"({grb_sz:,} B <= bz2 {bz2_sz:,} B)"
                )
                continue

        with open(grb_path, "rb") as fh:
            magic = fh.read(4)
        if magic != _GRIB_MAGIC:
            bad.append(f"Bad GRIB header: {attr}/{grb_name} (got {magic!r})")

    if bad:
        raise RuntimeError(
            f"Decompression verification FAILED ({len(bad)} issue(s)):\n"
            + "\n".join(f"  {b}" for b in bad)
        )
    logger.info("Decompress verification OK (%d/%d files)", n_exp, n_exp)
