"""COSMO-REA6 concrete decompressor.

Implements
:class:`~weather.providers.base_decompressor.BaseDecompressor`
for COSMO-REA6 ``.grb.bz2`` files.

The COSMO-REA6 archive distributes each monthly GRIB file as a
BZIP2-compressed archive (``.grb.bz2``).  This module decompresses
them to plain ``.grb`` using the best available decompressor:

* **lbzip2** — parallel BZIP2 (preferred; lowest per-thread overhead).
* **pbzip2** — parallel BZIP2 (fallback if lbzip2 is absent).
* **Python bz2** — stdlib fallback; no external tools needed.

Typical usage::

    from weather.providers.cosmo_rea6.decompressor import (
        CosmoDecompressor,
    )
    from weather.providers.base_downloader import DownloadJob
    from weather.providers.cosmo_rea6.config import get_config

    dc = CosmoDecompressor(get_config())
    grb = dc.get(DownloadJob("SWDIRS_RAD", 2018, 6))
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ...common.decompress import decompress_bz2_file, detect_decompressor
from ..base_decompressor import BaseDecompressor
from ..base_downloader import DownloadJob
from .naming import grib_filename

logger = logging.getLogger(__name__)


class CosmoDecompressor(BaseDecompressor):
    """COSMO-REA6 bz2 -> GRIB decompressor.

    Parameters
    ----------
    config : dict
        Pipeline configuration dictionary as returned by
        :func:`~weather.providers.cosmo_rea6.config.get_config`.
        Required keys: ``download_dir``, ``decompress_dir``,
        ``threads_per_job``, ``decompressor``.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self._cfg = config

    # ------------------------------------------------------------------
    # BaseDecompressor implementation
    # ------------------------------------------------------------------

    def compressed_path(self, job: DownloadJob) -> Path:
        """Return path to the downloaded ``.grb.bz2`` file."""
        fname = grib_filename(job.attribute, job.year, job.month)
        return (
            self._cfg["download_dir"] / job.attribute / fname
        )

    def decompressed_path(self, job: DownloadJob) -> Path:
        """Return expected path after decompression (``.grb``)."""
        fname = grib_filename(
            job.attribute, job.year, job.month
        ).removesuffix(".bz2")
        return (
            self._cfg["decompress_dir"] / job.attribute / fname
        )

    def _decompress_file(self, src: Path, dest: Path) -> Path:
        """Decompress *src* to *dest* using the best available tool.

        The decompressor is resolved once (lbzip2 > pbzip2 > Python
        bz2) according to ``config["decompressor"]`` and what is
        actually present in ``PATH``.
        """
        dest.parent.mkdir(parents=True, exist_ok=True)
        decompressor = detect_decompressor(
            preferred=self._cfg.get("decompressor", "")
        )
        logger.info(
            "Decompressing %s -> %s  [%s]",
            src.name,
            dest.name,
            decompressor,
        )
        return decompress_bz2_file(
            src,
            dest=dest,
            threads=self._cfg.get("threads_per_job", 4),
            preferred_decompressor=decompressor,
            logger=logger,
        )
