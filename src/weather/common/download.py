"""Shared download primitives for weather datasets."""

from __future__ import annotations

import contextlib
import ftplib
import logging
import shutil
import tempfile
import urllib.error
import urllib.request
from pathlib import Path


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
) -> Path:
    """Download URL to destination atomically with size checks."""
    log = logger or logging.getLogger(__name__)
    dest.parent.mkdir(parents=True, exist_ok=True)

    expected = remote_size_https(url)
    if dest.exists() and expected and dest.stat().st_size == expected:
        log.info("Already downloaded (size OK): %s", dest.name)
        return dest

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
                f"Size mismatch: expected {expected}, got {actual} for {url}"
            )
        Path(tmp_path).replace(dest)
    except BaseException:
        Path(tmp_path).unlink(missing_ok=True)
        raise

    log.info(
        "Download complete: %s (%d bytes)",
        dest.name,
        dest.stat().st_size,
    )
    return dest


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
