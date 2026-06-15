"""File cleanup and corruption detection for weather pipeline."""

from __future__ import annotations

import logging
from pathlib import Path

from . import validate


def cleanup_work_directory(
    work_dir: Path,
    *,
    cleanup_downloads: bool = True,
    cleanup_decompressed: bool = True,
    cleanup_locks: bool = True,
    dry_run: bool = False,
    logger: logging.Logger | None = None,
) -> None:
    """Clean up download and decompressed files after successful export.

    Parameters
    ----------
    work_dir : Path
        Root directory to search (e.g. the download or decompress dir).
        Files are located recursively so per-attribute subdirectories
        (e.g. ``work_dir/PS/``, ``work_dir/T_2M/``) are included.
    cleanup_downloads : bool
        If True, remove ``.grb.bz2`` compressed download files.
    cleanup_decompressed : bool
        If True, remove ``.grb`` decompressed GRIB files.
    cleanup_locks : bool
        If True, remove cfgrib index/lock files (``.idx``, ``.lock``).
        cfgrib writes a per-GRIB ``.idx`` sidecar the first time it reads
        a file; these can be safely deleted and will be regenerated on the
        next read.
    dry_run : bool
        If True, log what would be deleted without deleting.
    logger : logging.Logger, optional
        Logger instance.
    """
    log = logger or logging.getLogger(__name__)

    if cleanup_downloads:
        count = validate.cleanup_directory(
            work_dir,
            pattern="*.grb.bz2",
            recursive=True,
            dry_run=dry_run,
            logger=log,
        )
        log.info("Cleaned up %d downloaded files (.grb.bz2).", count)

    if cleanup_decompressed:
        count = validate.cleanup_directory(
            work_dir,
            pattern="*.grb",
            recursive=True,
            dry_run=dry_run,
            logger=log,
        )
        log.info("Cleaned up %d decompressed files (.grb).", count)

    if cleanup_locks:
        idx_count = validate.cleanup_directory(
            work_dir,
            pattern="*.idx",
            recursive=True,
            dry_run=dry_run,
            logger=log,
        )
        lock_count = validate.cleanup_directory(
            work_dir,
            pattern="*.lock",
            recursive=True,
            dry_run=dry_run,
            logger=log,
        )
        total = idx_count + lock_count
        if total:
            log.info(
                "Cleaned up %d lock/index files (%d .idx, %d .lock).",
                total, idx_count, lock_count,
            )


def detect_and_remove_corrupt_files(
    work_dir: Path,
    *,
    pattern: str = "*.grb.bz2",
    min_size: int = 1024,
    remove: bool = True,
    logger: logging.Logger | None = None,
) -> list[Path]:
    """Detect corrupt/truncated downloads and optionally remove.

    Returns list of detected (and removed if remove=True) files.
    """
    log = logger or logging.getLogger(__name__)
    corrupt = validate.detect_corrupt_files(
        work_dir,
        pattern=pattern,
        min_size=min_size,
        logger=log,
    )

    if remove and corrupt:
        for fp in corrupt:
            try:
                fp.unlink()
                log.info("Removed corrupt file: %s", fp)
            except Exception as e:
                log.warning("Failed to remove %s: %s", fp, e)

    return corrupt
