"""Fast parallel download of a CDS result URL.

Why
---
``cdsapi``'s ``result.download()`` pulls the file over a SINGLE HTTP
stream.  Measured on a real ERA5-Land month: 1314.6 MB in 369 s =
**3.56 MB/s**, while the CDS object store and a well-connected server can
sustain far more.  Across ~900 monthly files that single-stream transfer
costs roughly 92 hours; at 30 MB/s the same data moves in ~11 hours.

This module fetches the SAME url with several concurrent HTTP range
requests, writing each chunk into its own slice of a pre-allocated file.
It falls back cleanly to a single stream when the server does not support
range requests.

Usage::

    from weather.providers.era5_land.fast_download import download_parallel

    result = client.retrieve(dataset, request)   # cdsapi, as before
    download_parallel(result.location, dest, connections=8)

Notes
-----
* The CDS object store (``object-store.os-api.cci2.ecmwf.int``) supports
  HTTP Range, so parallel chunks work.  If a future endpoint does not,
  ``_supports_range`` returns False and we transparently fall back.
* Concurrency here is over BYTE RANGES OF ONE FILE — it does not increase
  the number of CDS *requests*, so it cannot trip the API's per-account
  job limit.  It is safe with ``ERA5_CDS_MAX_CONCURRENT=1``.
* On Linux, ``aria2c`` (if installed) is even faster; set
  ``ERA5_USE_ARIA2=1`` to use it when available.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests  # type: ignore

logger = logging.getLogger(__name__)

#: Default number of parallel HTTP range connections.
DEFAULT_CONNECTIONS = 8

#: Minimum file size (bytes) worth splitting; below this the overhead of
#: multiple connections is not repaid.
_MIN_PARALLEL_SIZE = 32 * 1024 * 1024   # 32 MB

_CHUNK = 4 * 1024 * 1024                # 4 MB socket read buffer


def _remote_size_and_range(url: str, timeout: int = 60):
    """Return (size_bytes, supports_range).  size is None if unknown."""
    try:
        r = requests.head(url, timeout=timeout, allow_redirects=True)
        r.raise_for_status()
        size = r.headers.get("Content-Length")
        accepts = r.headers.get("Accept-Ranges", "").lower()
        return (int(size) if size else None), (accepts == "bytes")
    except Exception as exc:  # noqa: BLE001
        logger.debug("HEAD failed (%s); assuming no range support", exc)
        return None, False


def _download_single(url: str, dest: Path, timeout: int = 600) -> Path:
    """Plain single-stream download (fallback path)."""
    logger.info("Downloading (single stream): %s", dest.name)
    with requests.get(url, stream=True, timeout=timeout) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=_CHUNK):
                if chunk:
                    f.write(chunk)
    return dest


def _fetch_range(url: str, start: int, end: int, dest: Path,
                 timeout: int, attempts: int = 4) -> int:
    """Fetch bytes [start, end] and write them at offset *start*.

    Retries transient failures; returns the number of bytes written.
    """
    headers = {"Range": f"bytes={start}-{end}"}
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            with requests.get(
                url, headers=headers, stream=True, timeout=timeout
            ) as r:
                r.raise_for_status()
                written = 0
                # Open per-thread; each writes a disjoint slice.
                with open(dest, "r+b") as f:
                    f.seek(start)
                    for chunk in r.iter_content(chunk_size=_CHUNK):
                        if chunk:
                            f.write(chunk)
                            written += len(chunk)
                return written
        except Exception as exc:  # noqa: BLE001
            last = exc
            if attempt == attempts:
                break
            delay = min(30.0, 2.0 ** attempt)
            logger.warning(
                "range %d-%d failed (attempt %d/%d): %s; retry in %.0fs",
                start, end, attempt, attempts, exc, delay,
            )
            time.sleep(delay)
    raise RuntimeError(f"range {start}-{end} failed: {last}")


def _try_aria2(url: str, dest: Path, connections: int) -> bool:
    """Use aria2c if available and enabled.  Returns True on success."""
    if os.getenv("ERA5_USE_ARIA2", "").strip() not in ("1", "true", "yes"):
        return False
    exe = shutil.which("aria2c")
    if not exe:
        logger.debug("ERA5_USE_ARIA2 set but aria2c not on PATH")
        return False
    logger.info("Downloading with aria2c (-x%d): %s", connections, dest.name)
    cmd = [
        exe,
        f"-x{connections}", f"-s{connections}",
        "-k", "8M",                 # min split size
        "--file-allocation=none",
        "--summary-interval=0",
        "--console-log-level=warn",
        "-d", str(dest.parent),
        "-o", dest.name,
        url,
    ]
    try:
        subprocess.run(cmd, check=True)  # noqa: S603
        return dest.exists() and dest.stat().st_size > 0
    except subprocess.CalledProcessError as exc:
        logger.warning("aria2c failed (%s); falling back", exc)
        return False


def download_parallel(
    url: str,
    dest: Path,
    *,
    connections: int | None = None,
    timeout: int = 900,
) -> Path:
    """Download *url* to *dest* using parallel HTTP range requests.

    Parameters
    ----------
    url : str
        The CDS result location (``result.location`` from cdsapi).
    dest : Path
        Destination file.  Written atomically via a ``.part`` temp file.
    connections : int, optional
        Number of concurrent range requests
        (default: ``ERA5_DOWNLOAD_CONNECTIONS`` or 8).
    timeout : int
        Per-request timeout in seconds.

    Returns
    -------
    Path
        *dest*, on success.
    """
    if connections is None:
        connections = int(
            os.getenv("ERA5_DOWNLOAD_CONNECTIONS", str(DEFAULT_CONNECTIONS))
        )
    connections = max(1, connections)

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    if tmp.exists():
        tmp.unlink()

    # Optional aria2c fast path (Linux servers).
    if _try_aria2(url, tmp, connections):
        tmp.replace(dest)
        return dest

    size, ranged = _remote_size_and_range(url)

    if not ranged or size is None or size < _MIN_PARALLEL_SIZE \
            or connections == 1:
        reason = (
            "server does not accept ranges" if not ranged
            else "unknown size" if size is None
            else "file below parallel threshold" if size < _MIN_PARALLEL_SIZE
            else "connections=1"
        )
        logger.info("Single-stream download (%s)", reason)
        _download_single(url, tmp, timeout=timeout)
        tmp.replace(dest)
        return dest

    # Pre-allocate the file so threads can seek into their own slices.
    with open(tmp, "wb") as f:
        f.truncate(size)

    part = size // connections
    bounds = []
    for i in range(connections):
        start = i * part
        end = size - 1 if i == connections - 1 else (start + part - 1)
        bounds.append((start, end))

    mb = size / (1024 * 1024)
    logger.info(
        "Downloading %s: %.1f MB via %d parallel connections",
        dest.name, mb, connections,
    )
    t0 = time.perf_counter()

    try:
        with ThreadPoolExecutor(max_workers=connections) as pool:
            futs = {
                pool.submit(_fetch_range, url, s, e, tmp, timeout): (s, e)
                for s, e in bounds
            }
            got = 0
            for fut in as_completed(futs):
                got += fut.result()
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise

    actual = tmp.stat().st_size
    if actual != size:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(
            f"size mismatch after parallel download: expected {size}, "
            f"got {actual}"
        )

    elapsed = time.perf_counter() - t0
    logger.info(
        "Download complete: %s (%.1f MB in %.1f s = %.1f MB/s)",
        dest.name, mb, elapsed, mb / max(elapsed, 1e-6),
    )
    tmp.replace(dest)
    return dest
