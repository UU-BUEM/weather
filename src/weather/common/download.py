"""Shared download primitives for weather datasets."""

from __future__ import annotations

import contextlib
import hashlib
import ftplib
import logging
import random
import shutil
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

# HTTP status codes that warrant a retry (transient server/gateway errors)
_TRANSIENT_HTTP_CODES = frozenset({429, 500, 502, 503, 504})
_RETRY_BASE_DELAY = 5.0   # seconds — first retry waits ~5 s
_RETRY_MAX_DELAY = 60.0   # seconds — cap per-retry wait at 1 min


def compute_sha256_checksum(file_path: Path, chunk_size: int = 8192) -> str:
    """Compute SHA256 checksum of a file.

    Parameters
    ----------
    file_path : Path
        Path to the file to checksum.
    chunk_size : int
        Read chunk size in bytes (default 8KB).

    Returns
    -------
    str
        Hexadecimal SHA256 checksum.
    """
    sha256_hash = hashlib.sha256()
    with file_path.open("rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            sha256_hash.update(chunk)
    return sha256_hash.hexdigest()


def get_checksum_file_path(
    download_dir: Path,
    attribute: str,
    year: int,
    month: int,
) -> Path:
    """Get the path to the checksum file for a downloaded GRIB file.

    Parameters
    ----------
    download_dir : Path
        Root download directory.
    attribute : str
        COSMO-REA6 attribute name.
    year : int
        Year.
    month : int
        Month (1-12).

    Returns
    -------
    Path
        Path to the .sha256 checksum file.
    """
    checksum_dir = download_dir / ".checksums"
    checksum_dir.mkdir(parents=True, exist_ok=True)
    fname = f"{attribute}.{year}{month:02d}.sha256"
    return checksum_dir / fname


def save_checksum(file_path: Path, checksum: str) -> None:
    """Save a checksum to a .sha256 file alongside the original.

    Parameters
    ----------
    file_path : Path
        Path to the original file.
    checksum : str
        SHA256 checksum to save.
    """
    checksum_path = file_path.parent / f"{file_path.name}.sha256"
    checksum_path.write_text(checksum + "\n")


def load_checksum(file_path: Path) -> str | None:
    """Load a checksum from a .sha256 file if it exists.

    Parameters
    ----------
    file_path : Path
        Path to the original file.

    Returns
    -------
    str or None
        Checksum string if file exists, None otherwise.
    """
    checksum_path = file_path.parent / f"{file_path.name}.sha256"
    if checksum_path.exists():
        return checksum_path.read_text().strip()
    return None


def verify_checksum(
    file_path: Path,
    expected_checksum: str | None = None,
) -> bool:
    """Verify a file's checksum against an expected value or stored checksum.

    Parameters
    ----------
    file_path : Path
        Path to the file to verify.
    expected_checksum : str, optional
        Expected SHA256 checksum. If None, loads from .sha256 file.

    Returns
    -------
    bool
        True if checksum matches, False otherwise.
    """
    if not file_path.exists():
        return False

    if expected_checksum is None:
        expected_checksum = load_checksum(file_path)
        if expected_checksum is None:
            return False

    actual_checksum = compute_sha256_checksum(file_path)
    return actual_checksum == expected_checksum


def remote_size_https(url: str, *, timeout: int = 30) -> int | None:
    """Return remote Content-Length for an HTTPS URL, if available."""
    try:
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            cl = resp.headers.get("Content-Length")
            return int(cl) if cl else None
    except (urllib.error.URLError, ValueError, OSError):
        return None


def download_https_atomic(
    url: str,
    dest: Path,
    *,
    logger: logging.Logger | None = None,
    timeout: int = 600,
    max_retries: int = 10,
    compute_checksum: bool = True,
) -> Path:
    """Download URL to destination atomically with size and checksum checks.

    Retries up to *max_retries* times on transient HTTP errors
    (503, 502, 429, 504) and connection-level errors, using
    exponential backoff with jitter.

    Parameters
    ----------
    url : str
        URL to download from.
    dest : Path
        Destination file path.
    logger : logging.Logger, optional
        Logger for progress messages.
    timeout : int
        Download timeout in seconds (default 600).
    max_retries : int
        Maximum number of retry attempts (default 10).
    compute_checksum : bool
        If True, compute and save SHA256 checksum after download
        (default True).

    Returns
    -------
    Path
        Path to the downloaded file.
    """
    log = logger or logging.getLogger(__name__)
    dest.parent.mkdir(parents=True, exist_ok=True)

    expected = remote_size_https(url)

    # Check if file already exists and is valid
    if dest.exists():
        if expected and dest.stat().st_size == expected:
            # Verify checksum if requested and checksum file exists
            if compute_checksum:
                stored_checksum = load_checksum(dest)
                if stored_checksum:
                    if verify_checksum(dest, stored_checksum):
                        log.info(
                            "Already downloaded (size & checksum OK): %s",
                            dest.name,
                        )
                        return dest
                    else:
                        log.warning(
                            "Checksum mismatch for existing file %s, "
                            "re-downloading",
                            dest.name,
                        )
                else:
                    log.info(
                        "Already downloaded (size OK, no checksum): %s",
                        dest.name,
                    )
                    return dest
            else:
                log.info("Already downloaded (size OK): %s", dest.name)
                return dest

    last_exc: BaseException | None = None
    for attempt in range(max_retries + 1):
        if attempt:
            delay = (
                min(_RETRY_MAX_DELAY, _RETRY_BASE_DELAY * 2 ** (attempt - 1))
                + random.uniform(0, 5)
            )
            log.warning(
                "Retry %d/%d for %s in %.1f s (last error: %s)",
                attempt, max_retries, dest.name, delay, last_exc,
            )
            time.sleep(delay)

        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=dest.parent,
            prefix=f".{dest.name}.",
            suffix=".part",
        )
        try:
            with (
                open(tmp_fd, "wb") as tmp_f,
                urllib.request.urlopen(url, timeout=timeout) as resp,
            ):
                shutil.copyfileobj(resp, tmp_f, length=1 << 20)

            actual = Path(tmp_path).stat().st_size
            if actual == 0:
                raise RuntimeError(f"Downloaded file is empty: {url}")
            if expected and actual != expected:
                raise RuntimeError(
                    f"Size mismatch: expected {expected},"
                    f" got {actual} for {url}"
                )
            Path(tmp_path).replace(dest)

            # Compute and save checksum if requested
            if compute_checksum:
                checksum = compute_sha256_checksum(dest)
                save_checksum(dest, checksum)
                log.info(
                    "Download complete: %s (%d bytes, sha256: %s)",
                    dest.name,
                    dest.stat().st_size,
                    checksum[:16],
                )
            else:
                log.info(
                    "Download complete: %s (%d bytes)",
                    dest.name,
                    dest.stat().st_size,
                )
            return dest
        except urllib.error.HTTPError as exc:
            Path(tmp_path).unlink(missing_ok=True)
            if exc.code not in _TRANSIENT_HTTP_CODES or attempt == max_retries:
                raise
            last_exc = exc
        except (urllib.error.URLError, OSError) as exc:
            Path(tmp_path).unlink(missing_ok=True)
            if attempt == max_retries:
                raise
            last_exc = exc
        except BaseException:
            Path(tmp_path).unlink(missing_ok=True)
            raise

    raise RuntimeError(f"Unreachable after {max_retries} retries for {url}")


def download_ftp_atomic(
    host: str,
    remote_path: str,
    dest: Path,
    *,
    user: str = "anonymous",
    passwd: str = "",
    timeout: int = 120,
    logger: logging.Logger | None = None,
) -> Path:
    """Download one file from FTP atomically with optional size checks."""
    log = logger or logging.getLogger(__name__)
    dest.parent.mkdir(parents=True, exist_ok=True)

    with ftplib.FTP(host, timeout=timeout) as ftp:
        ftp.login(user=user, passwd=passwd)
        remote_size: int | None = None
        with contextlib.suppress(ftplib.error_perm):
            remote_size = ftp.size(remote_path)

        if (
            dest.exists()
            and remote_size
            and dest.stat().st_size == remote_size
        ):
            log.info("Already downloaded (FTP size OK): %s", dest.name)
            return dest

        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=dest.parent,
            prefix=f".{dest.name}.",
            suffix=".part",
        )
        try:
            with open(tmp_fd, "wb") as tmp_f:
                ftp.retrbinary(
                    f"RETR {remote_path}",
                    tmp_f.write,
                    blocksize=1 << 20,
                )
            Path(tmp_path).replace(dest)
        except BaseException:
            Path(tmp_path).unlink(missing_ok=True)
            raise

    log.info("FTP download complete: %s", dest.name)
    return dest
