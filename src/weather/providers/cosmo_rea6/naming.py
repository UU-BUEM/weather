"""COSMO-REA6 file-naming conventions.

Generates standard filenames and DWD OpenData URLs for COSMO-REA6
GRIB files.  Kept separate from the pipeline configuration so that
download, decompress, and other modules can import naming helpers
without pulling in the full config resolution logic.

Typical usage::

    from weather.providers.cosmo_rea6.naming import grib_filename, grib_url
    name = grib_filename("SWDIRS_RAD", 2018, 1)
    url  = grib_url("SWDIRS_RAD", 2018, 1)
"""

from __future__ import annotations

import os

# ---------------------------------------------------------------------------
# File naming conventions
# ---------------------------------------------------------------------------
# Raw GRIB files on DWD follow the pattern:
#   {ATTR}.2D.{YYYYMM}.grb.bz2
# e.g. SWDIRS_RAD.2D.201801.grb.bz2


def grib_filename(attribute: str, year: int, month: int) -> str:
    """Return the standard GRIB filename for a given attribute/period.

    Parameters
    ----------
    attribute : str
        COSMO-REA6 attribute name (e.g. ``"SWDIRS_RAD"``).
    year : int
        Four-digit year.
    month : int
        Month number (1-12).

    Returns
    -------
    str
        Filename like ``SWDIRS_RAD.2D.201801.grb.bz2``.
    """
    return f"{attribute}.2D.{year}{month:02d}.grb.bz2"


def grib_url(
    attribute: str,
    year: int,
    month: int,
    base_url: str | None = None,
) -> str:
    """Return the full download URL for a COSMO-REA6 GRIB file.

    Parameters
    ----------
    attribute : str
        COSMO-REA6 attribute name.
    year, month : int
        Target period.
    base_url : str, optional
        Override the DWD base URL (useful for mirrors or local servers).

    Returns
    -------
    str
        Full URL to the ``.grb.bz2`` file.
    """
    base = base_url or os.environ.get(
        "COSMO_BASE_URL",
        (
            "https://opendata.dwd.de/climate_environment/REA/"
            "COSMO_REA6/hourly/2D"
        ),
    )
    fname = grib_filename(attribute, year, month)
    return f"{base}/{attribute}/{fname}"
