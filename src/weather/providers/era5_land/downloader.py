"""ERA5-Land concrete downloader (stub — requires CDS API key).

Implements :class:`~weather.providers.base_downloader.BaseDownloader`
for the Copernicus Climate Data Store (CDS) ERA5-Land dataset.

Authentication requirements
---------------------------
ERA5-Land data is retrieved via the **cdsapi** Python library, which
requires a free Copernicus account and an API key:

1. Register at https://cds.climate.copernicus.eu/
2. Accept the ERA5-Land terms of use on the CDS portal.
3. Create ``~/.cdsapirc``::

       url: https://cds.climate.copernicus.eu/api
       key: <your-personal-access-token>

4. Install the client::

       conda install -c conda-forge cdsapi

Dataset reference:
  https://cds.climate.copernicus.eu/datasets/reanalysis-era5-land

Download characteristics
------------------------
* **Request-queue model**: the CDS API queues requests server-side and
  returns a download URL only after processing completes (minutes to
  hours for large requests).  This means :meth:`remote_size` cannot
  return a meaningful value before the download starts — it returns
  ``None`` so that :meth:`~.base_downloader.BaseDownloader.is_complete`
  falls back to existence checking only.
* **Monthly granularity**: the CDS API supports one request per
  variable per month (all hours), which maps cleanly onto
  :class:`~.base_downloader.DownloadJob`.
* **Output format**: ``.nc`` (NetCDF4) by default; no decompression
  step is needed.

Status
------
This module provides the ``Era5Downloader`` class skeleton.
Implement :meth:`_fetch` to complete it.
"""

from __future__ import annotations

import calendar
import logging
from pathlib import Path
from typing import Any

from ..base_downloader import BaseDownloader, DownloadJob

logger = logging.getLogger(__name__)


class Era5Downloader(BaseDownloader):
    """ERA5-Land downloader via the Copernicus CDS API.

    Parameters
    ----------
    config : dict
        Pipeline configuration as returned by
        :func:`~weather.providers.era5_land.config.get_config`.
        Required keys: ``work_dir``, ``download_dir``.

    Notes
    -----
    The CDS API is request-queue-based.  A single API call may take
    minutes to hours depending on server load.  For this reason
    ``remote_size`` always returns ``None``, and
    :meth:`~.base_downloader.BaseDownloader.is_complete` relies on
    local-file existence alone (non-zero size) rather than a size
    comparison.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self._cfg = config

    # ------------------------------------------------------------------
    # BaseDownloader implementation
    # ------------------------------------------------------------------

    def remote_size(self, job: DownloadJob) -> int | None:
        """Always returns ``None`` for ERA5-Land.

        The CDS API does not report file size until after the request
        has been processed and queued for download.
        """
        return None  # CDS does not support pre-download size queries

    def local_path(self, job: DownloadJob) -> Path:
        """Return the local destination path for this CDS request.

        Files are stored under
        ``<download_dir>/<attribute>/<attribute>_<YYYY>_<MM>.<ext>``.

        ``<ext>`` is ``grib`` by default and follows
        ``config["data_format"]``.
        """
        ext = str(self._cfg.get("data_format", "grib")).lower().strip()
        if ext == "netcdf":
            ext = "nc"
        fname = (
            f"{job.attribute}_{job.year}_{job.month:02d}.{ext}"
        )
        return (
            self._cfg["download_dir"] / job.attribute / fname
        )

    def _fetch(self, job: DownloadJob) -> Path:
        """Submit one ERA5-Land monthly CDS request and download result.

        Request granularity is one variable for one month, which keeps
        server-side jobs smaller and easier to retry.
        """
        try:
            import cdsapi
        except ImportError as exc:
            raise RuntimeError(
                "cdsapi is required for ERA5-Land downloads. "
                "Install it with: conda install -c conda-forge cdsapi"
            ) from exc

        if job.attribute not in self._cfg["attributes"]:
            valid = ", ".join(sorted(self._cfg["attributes"]))
            raise ValueError(
                "Unknown ERA5-Land attribute "
                f"{job.attribute!r}. Valid: {valid}"
            )

        days_in_month = calendar.monthrange(job.year, job.month)[1]
        request = {
            "variable": [job.attribute],
            "year": str(job.year),
            "month": f"{job.month:02d}",
            "day": [f"{d:02d}" for d in range(1, days_in_month + 1)],
            "time": [f"{h:02d}:00" for h in range(24)],
            "data_format": self._cfg.get("data_format", "grib"),
            "download_format": self._cfg.get(
                "download_format", "unarchived"
            ),
        }

        client_kwargs: dict[str, str] = {}
        cds_url = str(self._cfg.get("cds_url", "")).strip()
        cds_key = str(self._cfg.get("cds_key", "")).strip()
        if cds_url and cds_key:
            client_kwargs = {"url": cds_url, "key": cds_key}

        client = cdsapi.Client(**client_kwargs)
        dataset = str(
            self._cfg.get("dataset", "reanalysis-era5-land")
        ).strip()

        dest = self.local_path(job)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".part")

        logger.info(
            "ERA5 CDS request: %s %04d-%02d %s",
            job.attribute,
            job.year,
            job.month,
            self._cfg.get("data_format", "grib"),
        )

        if tmp.exists():
            tmp.unlink()

        try:
            result = client.retrieve(dataset, request)
            result.download(str(tmp))
            if tmp.stat().st_size == 0:
                raise RuntimeError(
                    f"Empty ERA5-Land download for {job}: {tmp}"
                )
            tmp.replace(dest)
            return dest
        finally:
            if tmp.exists():
                tmp.unlink(missing_ok=True)
