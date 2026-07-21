"""MERRA-2 download orchestration.

Provides :func:`download_all`, the MERRA-2 analogue of
``era5_land.download.download_all``. MERRA-2 files are per-DAY (not
per-month like ERA5-Land, not per-attribute-per-month like COSMO), and
one OPeNDAP request already covers *every* attribute of one collection
(see :mod:`~weather.providers.merra2.downloader`), so the unit of work
here is one **(collection, day)** pair.

Concurrency
-----------
Unlike CDS, GES DISC's OPeNDAP server has no per-account job queue, so
concurrency is capped by ``config["opendap_max_concurrent"]`` (default
8) rather than ERA5-Land's much more conservative ``cds_max_concurrent``
(1-4).

Typical usage::

    from weather.providers.merra2.download import download_all
    paths = download_all(year=2018)              # all 12 months
    paths = download_all(year=2018, months=[1])  # January only
"""

from __future__ import annotations

import calendar
import logging

from ...common.parallel import run_parallel
from .config import get_config
from .downloaded_attributes import COLLECTIONS
from .downloader import Merra2Downloader, Merra2DownloadJob

logger = logging.getLogger(__name__)


def download_all(
    year: int | None = None,
    months: list[int] | None = None,
    *,
    max_concurrent: int | None = None,
) -> list:
    """Download every configured MERRA-2 collection for *year*.

    One OPeNDAP request (and one output file) is issued per
    (collection, day). Already present, non-empty files are skipped by
    :meth:`~weather.providers.base_downloader.BaseDownloader.get`.

    Parameters
    ----------
    year : int, optional
        Target year (default: ``config["year"]``).
    months : list[int], optional
        Subset of months 1-12 (default: all 12).
    max_concurrent : int, optional
        Override the OPeNDAP concurrency cap
        (default: ``config["opendap_max_concurrent"]``).

    Returns
    -------
    list[pathlib.Path]
        Local paths of the downloaded (or already-present) daily
        files, in completion order.
    """
    cfg = get_config()
    year = year or cfg["year"]
    months = months or list(range(1, 13))
    cap = max_concurrent or cfg.get("opendap_max_concurrent", 8)

    downloader = Merra2Downloader(cfg)
    jobs = [
        Merra2DownloadJob(collection=collection, year=year, month=m, day=d)
        for m in months
        for d in range(1, calendar.monthrange(year, m)[1] + 1)
        for collection in COLLECTIONS
    ]

    logger.info(
        "MERRA-2 download: year %d, %d month(s), %d collection(s), "
        "%d job(s), concurrency %d",
        year, len(months), len(COLLECTIONS), len(jobs), cap,
    )

    # Each job is one HTTPS GET (OPeNDAP subset) — I/O-bound, so a
    # thread pool is appropriate.
    return run_parallel(
        fn=downloader.get,
        jobs=jobs,
        max_workers=cap,
        logger=logger,
    )
