"""COSMO-REA6 concrete downloader.

Implements :class:`~weather.providers.base_downloader.BaseDownloader`
for the DWD OpenData COSMO-REA6 archive.

Data source
-----------
All COSMO-REA6 files are freely accessible over HTTPS (no credentials
required) at::

    https://opendata.dwd.de/climate_environment/REA/COSMO_REA6/hourly/2D/

File naming follows the pattern resolved by :func:`.naming.grib_url`.

Typical usage::

    from weather.providers.cosmo_rea6.downloader import CosmoDownloader
    from weather.providers.base_downloader import DownloadJob
    from weather.providers.cosmo_rea6.config import get_config

    dl = CosmoDownloader(get_config())
    path = dl.get(DownloadJob("SWDIRS_RAD", 2018, 6))
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ...common.download import download_https_atomic, remote_size_https
from ..base_downloader import BaseDownloader, DownloadJob
from .naming import grib_filename, grib_url

logger = logging.getLogger(__name__)


class CosmoDownloader(BaseDownloader):
    """COSMO-REA6 HTTPS downloader backed by DWD OpenData.

    Parameters
    ----------
    config : dict
        Pipeline configuration dictionary as returned by
        :func:`~weather.providers.cosmo_rea6.config.get_config`.
        Required keys: ``download_dir``, optionally ``base_url``.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self._cfg = config

    # ------------------------------------------------------------------
    # BaseDownloader implementation
    # ------------------------------------------------------------------

    def remote_size(self, job: DownloadJob) -> int | None:
        """Query remote file size via HTTP HEAD request.

        Returns ``None`` when the DWD server omits
        ``Content-Length``.
        """
        url = grib_url(
            job.attribute,
            job.year,
            job.month,
            base_url=self._cfg.get("base_url"),
        )
        return remote_size_https(url)

    def local_path(self, job: DownloadJob) -> Path:
        """Return ``<download_dir>/<attribute>/<filename>.grb.bz2``."""
        fname = grib_filename(job.attribute, job.year, job.month)
        return self._cfg["download_dir"] / job.attribute / fname

    def _fetch(self, job: DownloadJob) -> Path:
        """Download via HTTPS, write atomically, verify size."""
        url = grib_url(
            job.attribute,
            job.year,
            job.month,
            base_url=self._cfg.get("base_url"),
        )
        dest = self.local_path(job)
        dest.parent.mkdir(parents=True, exist_ok=True)
        logger.info(
            "Downloading %s -> %s", url, dest.name
        )
        return download_https_atomic(url, dest, logger=logger)
