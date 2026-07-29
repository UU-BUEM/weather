"""Nearest-grid-cell lookup against real 2-D lat/lon coordinates.

Pure numpy — no xarray/cfgrib dependency — so this can be used from the
lightweight point-query path (:mod:`weather.point_query`) without pulling
in a provider's heavy pipeline package.
"""

from __future__ import annotations

from typing import Any

import numpy as np


def find_nearest_cell(ds: Any, latitude: float, longitude: float) -> tuple[int, int]:
    """Return the ``(y, x)`` index of the grid cell nearest to a location.

    Works against any xarray Dataset (or anything exposing ``ds["latitude"]``/
    ``ds["longitude"]`` as 2-D arrays indexed by ``(y, x)``) — used for
    COSMO-REA6's rotated-pole grid, where cell selection can't be done by
    plain lat/lon values (unlike ERA5-Land/MERRA2's regular grid, which use
    ``ds.sel(latitude=..., longitude=..., method="nearest")`` directly).

    Parameters
    ----------
    ds : xarray.Dataset
        A dataset carrying 2-D ``latitude``/``longitude`` coordinates
        indexed by ``(y, x)`` (e.g. COSMO-REA6's
        ``build_month_dataset``/``build_annual_dataset`` output, after
        the coordinate-retention fix).
    latitude, longitude : float
        Target location in degrees (WGS84).

    Returns
    -------
    tuple[int, int]
        ``(iy, ix)`` grid indices of the nearest cell — use with
        ``ds.isel(y=iy, x=ix)``.

    Raises
    ------
    KeyError
        If *ds* has no ``latitude``/``longitude`` coordinates.
    """
    if "latitude" not in ds.coords or "longitude" not in ds.coords:
        raise KeyError(
            "Dataset has no latitude/longitude coordinates; re-run the "
            "pipeline to regenerate the export with per-cell coordinates."
        )
    lat_2d = np.asarray(ds["latitude"].values)
    lon_2d = np.asarray(ds["longitude"].values)
    dist2 = (lat_2d - latitude) ** 2 + (lon_2d - longitude) ** 2
    iy, ix = (int(v) for v in np.unravel_index(np.argmin(dist2), dist2.shape))
    return iy, ix
