"""ERA5-Land pipeline configuration.

All settings are resolved through
:class:`~weather.settings.EnvSettings`.

Typical usage::

    from weather.providers.era5_land.config import get_config
    cfg = get_config()
    print(cfg["work_dir"])
"""

from __future__ import annotations

from typing import Any

from ...settings import EnvSettings
from .downloaded_attributes import ATTRIBUTES


def get_config() -> dict[str, Any]:
    """Return the fully-resolved ERA5-Land configuration.

    Returns
    -------
    dict[str, Any]
        Keys: ``work_dir``, ``download_dir``, ``processed_dir``,
        ``output_dir``, ``year``, ``attributes``, ``ncores``,
        ``threads_per_job``, ``conda_env``.
    """
    return {
        "work_dir": EnvSettings.era5_work_dir(),
        "download_dir": EnvSettings.era5_download_dir(),
        "processed_dir": EnvSettings.era5_processed_dir(),
        "output_dir": EnvSettings.era5_output_dir(),
        "year": EnvSettings.era5_year(),
        "attributes": list(ATTRIBUTES.keys()),
        "ncores": EnvSettings.era5_ncores(),
        "threads_per_job": EnvSettings.era5_threads_per_job(),
        "conda_env": EnvSettings.era5_conda_env(),
        "dataset": EnvSettings.era5_cds_dataset(),
        "data_format": EnvSettings.era5_data_format(),
        "download_format": EnvSettings.era5_download_format(),
        "cds_url": EnvSettings.era5_cds_url(),
        "cds_key": EnvSettings.era5_cds_key(),
    }
