"""COSMO-REA6 pipeline configuration.

All settings are resolved through
:class:`~weather.settings.EnvSettings`, which reads environment
variables and the repo-level ``.env`` file.  Import
:func:`get_config` wherever a configuration dict is needed::

    from weather.providers.cosmo_rea6.config import get_config
    cfg = get_config()
    print(cfg["work_dir"])

File-naming helpers live in :mod:`.naming`.
"""

from __future__ import annotations

from typing import Any

from ...settings import EnvSettings
from .downloaded_attributes import ATTRIBUTES
from .naming import grib_filename, grib_url  # noqa: F401 — re-exported


def get_config() -> dict[str, Any]:
    """Return the fully-resolved COSMO-REA6 configuration.

    All paths and scalars come from :class:`~weather.settings.EnvSettings`
    (backed by environment variables / ``.env``).

    Returns
    -------
    dict[str, Any]
        Keys: ``base_url``, ``const_url``, ``work_dir``,
        ``download_dir``, ``decompress_dir``, ``processed_dir``,
        ``output_dir``, ``year``, ``attributes``, ``ncores``,
        ``threads_per_job``, ``decompressor``, ``conda_env``, ``cleanup``.
    """
    return {
        "base_url": EnvSettings.cosmo_base_url(),
        "const_url": EnvSettings.cosmo_const_url(),
        "work_dir": EnvSettings.cosmo_work_dir(),
        "download_dir": EnvSettings.cosmo_download_dir(),
        "decompress_dir": EnvSettings.cosmo_decompress_dir(),
        "processed_dir": EnvSettings.cosmo_processed_dir(),
        "output_dir": EnvSettings.cosmo_output_dir(),
        "log_dir": EnvSettings.cosmo_log_dir(),
        "year": EnvSettings.cosmo_year(),
        "attributes": list(ATTRIBUTES.keys()),
        "ncores": EnvSettings.cosmo_ncores(),
        "threads_per_job": EnvSettings.cosmo_threads_per_job(),
        "decompressor": EnvSettings.cosmo_decompressor(),
        "conda_env": EnvSettings.cosmo_conda_env(),
        "cleanup": EnvSettings.cosmo_cleanup(),
        "max_retries": EnvSettings.cosmo_max_retries(),
    }
