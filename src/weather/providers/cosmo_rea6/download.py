"""Download COSMO-REA6 GRIB files from the DWD OpenData server.

Supports two transports:

* **HTTPS** (default) — uses ``urllib.request`` from the standard library;
  no extra dependencies.  Resume via ``Range`` header is attempted when the
  server supports it.
* **FTP** — available as a fallback via :func:`download_ftp`.  Uses
  :mod:`ftplib` (stdlib).

Both paths perform an **integrity check** by comparing the local file size
to the remote ``Content-Length`` (HTTPS) or ``SIZE`` (FTP) *before*
downloading, so an already-complete file is never re-fetched.

Typical usage::

    from buem.weather.download import download_attribute_month
    download_attribute_month("SWDIRS_RAD", 2018, 1, dest_dir=Path("/data"))
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from ...common.download import download_ftp_atomic, download_https_atomic
from .config import ATTRIBUTES, grib_filename, grib_url, get_config

logger = logging.getLogger(__name__)


def _download_https(url: str, dest: Path) -> Path:
    return download_https_atomic(url, dest, logger=logger)


# ---------------------------------------------------------------------------
# FTP transport (fallback)
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
        Attribute name (must be a key in
        :data:`~buem.weather.config.ATTRIBUTES`).
    year : int
        Four-digit year (e.g. 2018).
    month : int
        Month (1–12).
    dest_dir : Path, optional
        Download directory.  Defaults to ``<work_dir>/download/<attribute>/``.
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
            f"Unknown attribute '{attribute}'.  "
            f"Valid: {', '.join(sorted(ATTRIBUTES))}"
        )

    cfg = get_config()
    if dest_dir is None:
        dest_dir = cfg["download_dir"] / attribute
    dest_dir.mkdir(parents=True, exist_ok=True)

    fname = grib_filename(attribute, year, month)
    url = grib_url(attribute, year, month, base_url=base_url)
    dest = dest_dir / fname

    return _download_https(url, dest)


def download_all(
    year: int | None = None,
    months: list[int] | None = None,
    attributes: list[str] | None = None,
    *,
    dest_dir: Path | None = None,
    base_url: str | None = None,
) -> list[Path]:
    """Download all requested GRIB files for a given year.

    Parameters
    ----------
    year : int, optional
        Year to download (default from config: 2018).
    months : list[int], optional
        Months to download (default from config: 1–12).
    attributes : list[str], optional
        Attributes to download (default from config: all five).
    dest_dir : Path, optional
        Root download directory.  Per-attribute sub-directories are created.
    base_url : str, optional
        Override DWD base URL.

    Returns
    -------
    list[Path]
        Paths to all downloaded ``.grb.bz2`` files.
    """
    cfg = get_config()
    year = year or cfg["year"]
    months = months or cfg["months"]
    attributes = attributes or cfg["attributes"]

    # Build list of (attribute, month) jobs
    jobs = [
        (attr, m) for attr in attributes for m in months
    ]

    def _download_one(args: tuple[str, int]) -> Path:
        attr, m = args
        return download_attribute_month(
            attr, year, m, dest_dir=dest_dir, base_url=base_url
        )

    # Download in parallel — each file goes to a separate server path,
    # so concurrent connections are safe and ≈N× faster.
    # Cap at 8 workers to avoid overloading the remote source.
    max_workers = min(len(jobs), cfg["ncores"], 8)
    logger.info(
        "Downloading %d files with %d parallel workers", len(jobs), max_workers
    )

    downloaded: list[Path] = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_download_one, j): j for j in jobs}
        for future in as_completed(futures):
            attr, m = futures[future]
            try:
                p = future.result()
                downloaded.append(p)
            except Exception:
                logger.exception("Failed to download %s month %d", attr, m)
                raise

    logger.info("Downloaded %d files.", len(downloaded))
    return downloaded
