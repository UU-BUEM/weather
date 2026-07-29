"""Download COSMO-REA6 GRIB files from the DWD OpenData server.

Supports two transports:

* **HTTPS** (default) — uses ``urllib.request``; no extra dependencies.
  Integrity is verified via ``Content-Length`` before writing so an
  already-complete file is never re-fetched.
* **FTP** — available as a fallback via :func:`download_ftp`.
  Uses :mod:`ftplib` (stdlib).

The download logic is encapsulated in
:class:`~weather.providers.cosmo_rea6.downloader.CosmoDownloader`
(see :mod:`providers.base_downloader` for the ABC contract).
Parallel execution is handled by
:func:`~weather.common.parallel.run_parallel`.

Typical usage::

    from weather.providers.cosmo_rea6.download import (
        download_attribute_month,
    )
    download_attribute_month("SWDIRS_RAD", 2018, 1)
"""

from __future__ import annotations

import logging
from pathlib import Path

from ...common.download import download_ftp_atomic
from ...common.parallel import run_parallel
from ..base_downloader import DownloadJob
from .config import get_config
from .downloaded_attributes import ATTRIBUTES
from .downloader import CosmoDownloader

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# FTP transport (fallback — HTTPS preferred)
# ---------------------------------------------------------------------------

def download_ftp(
    host: str,
    remote_path: str,
    dest: Path,
    *,
    user: str = "anonymous",
    passwd: str = "",
) -> Path:
    """Download a single file from an FTP server."""
    return download_ftp_atomic(
        host,
        remote_path,
        dest,
        user=user,
        passwd=passwd,
        logger=logger,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def download_attribute_month(
    attribute: str,
    year: int,
    month: int,
    *,
    dest_dir: Path | None = None,
    base_url: str | None = None,
) -> Path:
    """Download one monthly GRIB file for a single COSMO-REA6 attribute.

    Parameters
    ----------
    attribute : str
        Must be a key in :data:`.downloaded_attributes.ATTRIBUTES`.
    year : int
        Four-digit year (e.g. 2018).
    month : int
        Month (1-12).
    dest_dir : Path, optional
        Download directory.  Defaults to
        ``<work_dir>/download/<attribute>/``.
    base_url : str, optional
        Override the DWD base URL.

    Returns
    -------
    Path
        Path to the local ``.grb.bz2`` file.

    Raises
    ------
    ValueError
        If *attribute* is not a recognised COSMO-REA6 field.
    """
    if attribute not in ATTRIBUTES:
        raise ValueError(
            f"Unknown attribute {attribute!r}.  "
            f"Valid: {', '.join(sorted(ATTRIBUTES))}"
        )

    cfg = get_config()
    if base_url is not None:
        cfg = {**cfg, "base_url": base_url}
    if dest_dir is not None:
        cfg = {**cfg, "download_dir": dest_dir.parent}

    dl = CosmoDownloader(cfg)
    job = DownloadJob(attribute=attribute, year=year, month=month)
    return dl.get(job)


def download_all(
    year: int | None = None,
    attributes: list[str] | None = None,
    *,
    months: list[int] | None = None,
    dest_dir: Path | None = None,
    base_url: str | None = None,
    max_workers: int | None = None,
) -> list[Path]:
    """Download GRIB files for every attribute across one or more months.

    Uses :class:`~.downloader.CosmoDownloader` for per-file
    check-before-fetch and :func:`~weather.common.parallel.run_parallel`
    for concurrent downloads. DWD OpenData is a plain static-file HTTPS
    server (no documented rate limit, unlike CDS/GES DISC) -- worker
    count defaults to one thread per task, capped only by *ncores*, not
    an artificial ceiling.

    Parameters
    ----------
    year : int, optional
        Year to download (default from config: 2018).
    attributes : list[str], optional
        Attributes to download (default from config: all).
    months : list[int], optional
        Months to download (default: all 12).
    dest_dir : Path, optional
        Override the root download directory.
    base_url : str, optional
        Override DWD base URL.
    max_workers : int, optional
        Concurrent download threads (default: ``min(n_tasks, ncores)``).

    Returns
    -------
    list[Path]
        Paths to all downloaded ``.grb.bz2`` files.
    """
    cfg = get_config()
    year = year or cfg["year"]
    attributes = attributes or cfg["attributes"]
    months = months or list(range(1, 13))
    if base_url is not None:
        cfg = {**cfg, "base_url": base_url}
    if dest_dir is not None:
        cfg = {**cfg, "download_dir": dest_dir}

    dl = CosmoDownloader(cfg)
    jobs = [
        DownloadJob(attribute=attr, year=year, month=m)
        for attr in attributes
        for m in months
    ]
    if max_workers is None:
        max_workers = min(len(jobs), cfg["ncores"])
    logger.info(
        "Downloading %d files with %d workers",
        len(jobs),
        max_workers,
    )
    downloaded = run_parallel(
        fn=dl.get,
        jobs=jobs,
        max_workers=max_workers,
        logger=logger,
    )
    logger.info("Downloaded %d files.", len(downloaded))
    return downloaded


def verify_downloads(
    year: int,
    attributes: list[str],
    months: list[int],
    dl_dir: Path,
    *,
    max_workers: int | None = None,
) -> None:
    """Verify every (month, attribute) ``.grb.bz2`` against DWD's Content-Length.

    Checks each expected file exists, is non-empty, and (when DWD returns a
    ``Content-Length`` header) matches the remote byte count exactly.
    Files where DWD returns no ``Content-Length`` pass with a debug log
    rather than failing.

    Parameters
    ----------
    year : int
        Target year.
    attributes : list[str]
        Attributes expected to have been downloaded.
    months : list[int]
        Months expected to have been downloaded.
    dl_dir : Path
        Root download directory (per-attribute subdirs).
    max_workers : int, optional
        Concurrent HEAD requests (default: ``min(n_tasks, 32)``).

    Raises
    ------
    RuntimeError
        Listing every missing or size-mismatched file.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from ...common.download import remote_size_https
    from .naming import grib_filename, grib_url

    tasks = [(m, a) for m in months for a in attributes]
    n_exp = len(tasks)
    if max_workers is None:
        max_workers = min(n_exp, 32)
    logger.info("Verifying %d bz2 file sizes against DWD ...", n_exp)

    def _check(month: int, attr: str) -> tuple[str, str]:
        fname = grib_filename(attr, year, month)
        local = dl_dir / attr / fname
        if not local.exists() or local.stat().st_size == 0:
            return "missing", f"{attr}/{fname}"
        remote_sz = remote_size_https(grib_url(attr, year, month))
        if remote_sz is None:
            logger.debug(
                "no Content-Length from DWD for %s/%s -- skipped", attr, fname,
            )
            return "ok", ""
        local_sz = local.stat().st_size
        if local_sz != remote_sz:
            return "mismatch", (
                f"{attr}/{fname}: local={local_sz:,} B remote={remote_sz:,} B"
            )
        return "ok", ""

    missing: list[str] = []
    mismatches: list[str] = []
    with ThreadPoolExecutor(max_workers=max(1, max_workers)) as pool:
        futs = {pool.submit(_check, m, a): (m, a) for m, a in tasks}
        for fut in as_completed(futs):
            kind, msg = fut.result()
            if kind == "missing":
                missing.append(msg)
            elif kind == "mismatch":
                mismatches.append(msg)

    issues: list[str] = []
    if missing:
        issues.append(
            f"Missing/empty ({len(missing)}):\n"
            + "\n".join(f"    {x}" for x in sorted(missing))
        )
    if mismatches:
        issues.append(
            f"Size mismatch ({len(mismatches)}):\n"
            + "\n".join(f"    {x}" for x in sorted(mismatches))
        )
    if issues:
        raise RuntimeError("Download verification FAILED:\n" + "\n".join(issues))
    logger.info(
        "Download verification OK (%d/%d files match DWD sizes)", n_exp, n_exp,
    )
