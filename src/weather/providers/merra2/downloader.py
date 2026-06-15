"""MERRA-2 concrete downloader (stub — requires NASA Earthdata auth).

Implements :class:`~weather.providers.base_downloader.BaseDownloader`
for the NASA GES DISC MERRA-2 archive.

Authentication requirements
---------------------------
MERRA-2 data is distributed via the NASA GES DISC OPeNDAP/HTTPS
server.  Access requires a **free** NASA Earthdata account:

1. Register at https://urs.earthdata.nasa.gov/
2. In *Applications > Authorized Apps*, add
   **"NASA GESDISC DATA ARCHIVE"** to your approved list.
3. Create or update ``~/.netrc``::

       machine urs.earthdata.nasa.gov
           login  <your_username>
           password <your_password>

4. Set permissions: ``chmod 600 ~/.netrc``

Python's :mod:`urllib.request` reads ``~/.netrc`` automatically, so
no credentials appear in code.  Alternatively, set the environment
variables ``EARTHDATA_USER`` and ``EARTHDATA_PASS`` and pass them to
:func:`~weather.common.download.download_https_atomic`.

Download granularity
--------------------
Unlike COSMO-REA6 (one file per attribute per month), MERRA-2 files
are **one NetCDF4 file per day** in collections such as
``M2T1NXRAD.5.12.4`` (hourly radiation) or ``M2T1NXSLV.5.12.4``
(hourly surface variables).

Collection reference:
  https://disc.gsfc.nasa.gov/datasets?project=MERRA-2

A full MERRA-2 downloader therefore needs a ``Merra2DownloadJob``
dataclass with a ``date`` field (or ``year``/``month``/``day``), and
the ``remote_size`` implementation must query the GES DISC OPeNDAP
file catalog for each collection/date combination.

Status
------
This module provides the ``Merra2Downloader`` class skeleton.
Implement the three abstract methods to complete it.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ..base_downloader import BaseDownloader, DownloadJob

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# GES DISC collection URLs (adjust for the target MERRA-2 product)
# ---------------------------------------------------------------------------
#: Hourly radiation flux collection (shortwave, longwave, cloud forcing).
_GES_DISC_RAD = (
    "https://goldsmr4.gesdisc.eosdis.nasa.gov/data"
    "/MERRA2/M2T1NXRAD.5.12.4"
)
#: Hourly single-level diagnostics (temperature, wind, surface pressure).
_GES_DISC_SLV = (
    "https://goldsmr4.gesdisc.eosdis.nasa.gov/data"
    "/MERRA2/M2T1NXSLV.5.12.4"
)


class Merra2Downloader(BaseDownloader):
    """MERRA-2 downloader for NASA GES DISC HTTPS.

    Parameters
    ----------
    config : dict
        Pipeline configuration as returned by
        :func:`~weather.providers.merra2.config.get_config`.
        Required keys: ``work_dir``, ``download_dir``.

    Notes
    -----
    MERRA-2 files are one NetCDF4 per *day*, not per month.
    Extend ``DownloadJob`` or define a ``Merra2DownloadJob``
    with a ``day`` field to address individual files.

    The ``remote_size`` method requires a catalog lookup against
    the GES DISC OpenDAP file listing (e.g.
    ``https://goldsmr4.gesdisc.eosdis.nasa.gov/opendap/…/catalog.xml``).
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self._cfg = config

    # ------------------------------------------------------------------
    # BaseDownloader implementation (stubs — complete before use)
    # ------------------------------------------------------------------

    def remote_size(self, job: DownloadJob) -> int | None:
        """Query the GES DISC catalog for the file size.

        .. todo::
            Implement with a HEAD request to the resolved GES DISC URL.
            Requires ``~/.netrc`` credentials for
            ``urs.earthdata.nasa.gov``.
        """
        raise NotImplementedError(
            "Merra2Downloader.remote_size: not yet implemented. "
            "Implement with a HEAD request to the GES DISC catalog "
            "using ~/.netrc credentials."
        )

    def local_path(self, job: DownloadJob) -> Path:
        """Return the local destination path.

        .. todo::
            Map (attribute, year, month) to the MERRA-2 per-day file
            naming convention:
            ``MERRA2_400.<collection>.<YYYYMMDD>.nc4``.
        """
        raise NotImplementedError(
            "Merra2Downloader.local_path: not yet implemented. "
            "MERRA-2 files are per-day, not per-month. "
            "Define a Merra2DownloadJob with a 'day' field."
        )

    def _fetch(self, job: DownloadJob) -> Path:
        """Download from GES DISC via authenticated HTTPS.

        .. todo::
            Build the GES DISC URL for the requested collection/date,
            then call :func:`~weather.common.download.download_https_atomic`
            with netrc-based auth.

            Example URL pattern::

                https://goldsmr4.gesdisc.eosdis.nasa.gov/data/
                MERRA2/M2T1NXRAD.5.12.4/2018/01/
                MERRA2_400.tavg1_2d_rad_Nx.20180101.nc4
        """
        raise NotImplementedError(
            "Merra2Downloader._fetch: not yet implemented. "
            "Requires NASA Earthdata credentials in ~/.netrc."
        )
