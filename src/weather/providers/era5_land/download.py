"""ERA5-Land download orchestration.

Provides :func:`download_all`, the ERA5-Land analogue of
``cosmo_rea6.download.download_all``.  Because one CDS request fetches
*all* configured variables for a month (see
:mod:`~weather.providers.era5_land.downloader`), the unit of work here
is **one month**, not one (attribute, month) pair.

Concurrency
-----------
The CDS API enforces a per-user limit on simultaneously *active*
requests and queues the rest.  Flooding it with many parallel requests
yields no speed-up and risks rejections, so concurrency is capped by
``config["cds_max_concurrent"]`` (default 4) rather than the much
larger CPU-core count used for local COSMO work.

Typical usage::

    from weather.providers.era5_land.download import download_all
    paths = download_all(year=2018)             # all 12 months
    paths = download_all(year=2018, months=[1]) # January only
"""

from __future__ import annotations

import logging

from ...common.parallel import run_parallel
from ..base_downloader import DownloadJob
from .config import get_config
from .downloader import ALL_ATTRS, Era5Downloader

logger = logging.getLogger(__name__)


def download_all(
    year: int | None = None,
    months: list[int] | None = None,
    *,
    max_concurrent: int | None = None,
) -> list:
    """Download every configured ERA5-Land variable for *year*.

    One CDS request (and one output file) is issued per month.  Already
    present, non-empty files are skipped by
    :meth:`~weather.providers.base_downloader.BaseDownloader.get`.

    Parameters
    ----------
    year : int, optional
        Target year (default: ``config["year"]``).
    months : list[int], optional
        Subset of months 1-12 (default: all 12).
    max_concurrent : int, optional
        Override the CDS concurrency cap
        (default: ``config["cds_max_concurrent"]``).

    Returns
    -------
    list[pathlib.Path]
        Local paths of the downloaded (or already-present) monthly
        files, in completion order.
    """
    cfg = get_config()
    year = year or cfg["year"]
    months = months or list(range(1, 13))
    cap = max_concurrent or cfg.get("cds_max_concurrent", 4)

    downloader = Era5Downloader(cfg)
    jobs = [
        DownloadJob(attribute=ALL_ATTRS, year=year, month=m)
        for m in months
    ]

    logger.info(
        "ERA5-Land download: year %d, %d month(s), "
        "%d variables/month, concurrency %d",
        year, len(jobs), len(cfg["attributes"]), cap,
    )

    # Each job is a full CDS round-trip (queue + transfer), so this is
    # I/O/wait-bound — a thread pool with a small cap is ideal.
    return run_parallel(
        fn=downloader.get,
        jobs=jobs,
        max_workers=cap,
        logger=logger,
    )
