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
    dest_dir: Path | None = None,
    base_url: str | None = None,
) -> list[Path]:
    """Download all GRIB files for every attribute across a full year.

    All twelve months (January–December) are always downloaded.
    Uses :class:`~.downloader.CosmoDownloader` for per-file
    check-before-fetch and :func:`~weather.common.parallel.run_parallel`
    for concurrent downloads.

    Parameters
    ----------
    year : int, optional
        Year to download (default from config: 2018).
    attributes : list[str], optional
        Attributes to download (default from config: all).
    dest_dir : Path, optional
        Override the root download directory.
    base_url : str, optional
        Override DWD base URL.

    Returns
    -------
    list[Path]
        Paths to all downloaded ``.grb.bz2`` files.
    """
    cfg = get_config()
    year = year or cfg["year"]
    attributes = attributes or cfg["attributes"]
    if base_url is not None:
        cfg = {**cfg, "base_url": base_url}
    if dest_dir is not None:
        cfg = {**cfg, "download_dir": dest_dir}

    dl = CosmoDownloader(cfg)
    jobs = [
        DownloadJob(attribute=attr, year=year, month=m)
        for attr in attributes
        for m in range(1, 13)
    ]
    max_workers = min(len(jobs), cfg["ncores"], 8)
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
