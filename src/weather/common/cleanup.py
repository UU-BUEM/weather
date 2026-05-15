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
    dry_run: bool = False,
    logger: logging.Logger | None = None,
) -> None:
    """Clean up download and decompressed files after successful export.

    Parameters
    ----------
    work_dir : Path
        Work directory (e.g., ~/weather_data/cosmo_rea6).
    cleanup_downloads : bool
        If True, remove .grb.bz2 files.
    cleanup_decompressed : bool
        If True, remove .grb files.
    dry_run : bool
        If True, log without deleting.
    logger : logging.Logger, optional
        Logger instance.
    """
    log = logger or logging.getLogger(__name__)

    if cleanup_downloads:
        count = validate.cleanup_directory(
            work_dir,
            pattern="*.grb.bz2",
            dry_run=dry_run,
            logger=log,
        )
        log.info("Cleaned up %d downloaded files.", count)

    if cleanup_decompressed:
        count = validate.cleanup_directory(
            work_dir,
            pattern="*.grb",
            dry_run=dry_run,
            logger=log,
        )
        log.info("Cleaned up %d decompressed files.", count)


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
