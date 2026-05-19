"""Validation and integrity checking utilities for weather datasets."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path


def validate_file_integrity(
    filepath: Path,
    *,
    expected_size: int | None = None,
    expected_hash: str | None = None,
    hash_algo: str = "sha256",
    logger: logging.Logger | None = None,
) -> tuple[bool, str]:
    """Validate file integrity (size and optional hash check).

    Parameters
    ----------
    filepath : Path
        File to validate.
    expected_size : int, optional
        Expected file size in bytes.
    expected_hash : str, optional
        Expected checksum (hex string).
    hash_algo : str
        Hash algorithm ('md5', 'sha1', 'sha256', etc.).
    logger : logging.Logger, optional
        Logger instance for diagnostics.

    Returns
    -------
    (bool, str)
        (is_valid, message) tuple.
    """
    log = logger or logging.getLogger(__name__)

    if not filepath.exists():
        return False, f"File not found: {filepath}"

    if filepath.stat().st_size == 0:
        return False, f"File is empty: {filepath}"

    if expected_size is not None:
        actual = filepath.stat().st_size
        if actual != expected_size:
            return (
                False,
                f"Size mismatch: expected {expected_size}, got {actual}",
            )

    if expected_hash is not None:
        try:
            actual_hash = compute_file_hash(
                filepath,
                algo=hash_algo,
                logger=log,
            )
            if actual_hash.lower() != expected_hash.lower():
                return (
                    False,
                    f"Hash mismatch: expected {expected_hash}, "
                    f"got {actual_hash}",
                )
        except Exception as e:
            return False, f"Hash computation failed: {e}"

    return True, "OK"


def compute_file_hash(
    filepath: Path,
    *,
    algo: str = "sha256",
    blocksize: int = 1 << 20,
    logger: logging.Logger | None = None,
) -> str:
    """Compute file hash (streaming for large files)."""
    log = logger or logging.getLogger(__name__)
    log.debug("Computing %s hash for %s", algo, filepath)
    h = hashlib.new(algo)
    with open(filepath, "rb") as f:
        while chunk := f.read(blocksize):
            h.update(chunk)
    return h.hexdigest()


def cleanup_directory(
    directory: Path,
    *,
    pattern: str = "*",
    recursive: bool = False,
    dry_run: bool = False,
    logger: logging.Logger | None = None,
) -> int:
    """Remove files matching pattern (for cleanup after export).

    Parameters
    ----------
    directory : Path
        Directory to clean.
    pattern : str
        Glob pattern (default: '*' removes all).
    recursive : bool
        If True, use ** for recursive search.
    dry_run : bool
        If True, log what would be deleted without deleting.
    logger : logging.Logger, optional
        Logger instance.

    Returns
    -------
    int
        Number of files deleted (or would be deleted if dry_run).
    """
    log = logger or logging.getLogger(__name__)

    if not directory.exists():
        return 0

    if recursive:
        pattern = f"**/{pattern}"
    files = list(directory.glob(pattern))

    count = 0
    for fp in files:
        if not fp.is_file():
            continue
        if dry_run:
            log.info("[DRY RUN] Would delete: %s", fp)
            count += 1
        else:
            try:
                fp.unlink()
                log.info("Deleted: %s", fp)
                count += 1
            except Exception as e:
                log.warning("Failed to delete %s: %s", fp, e)

    return count


def detect_corrupt_files(
    directory: Path,
    *,
    pattern: str = "*.grb*",
    min_size: int = 1024,
    logger: logging.Logger | None = None,
) -> list[Path]:
    """Find potentially corrupt files (e.g., truncated downloads).

    Parameters
    ----------
    directory : Path
        Directory to scan.
    pattern : str
        File glob pattern.
    min_size : int
        Minimum expected file size in bytes.
    logger : logging.Logger, optional
        Logger instance.

    Returns
    -------
    list[Path]
        List of files suspected to be corrupt.
    """
    log = logger or logging.getLogger(__name__)
    corrupt: list[Path] = []

    if not directory.exists():
        return corrupt

    for fp in directory.glob(pattern):
        if not fp.is_file():
            continue
        if fp.stat().st_size < min_size:
            corrupt.append(fp)
            log.warning("Suspect: %s (size: %d)", fp, fp.stat().st_size)

    return corrupt
