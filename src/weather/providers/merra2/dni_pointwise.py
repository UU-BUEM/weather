"""Point- / region-wise DNI and DHI extraction for MERRA-2.

MERRA-2 stores only total shortwave (``GHI``, direct from the
instantaneous ``SWGDN`` field — no de-accumulation needed, unlike
ERA5-Land's ``ssrd``).  Splitting it into Direct Normal Irradiance (DNI)
and Diffuse Horizontal Irradiance (DHI) requires a *decomposition
model* — and every such model carries real estimation uncertainty
(RMSE ~80-120 W/m²).  Rather than bake one model choice into the
archive, the bulk pipeline stores GHI only and you compute DNI/DHI
*here*, at the location(s) you actually need, choosing the accuracy /
speed trade-off yourself.

Why point-of-use, not bulk?
---------------------------
The standard decomposition models (DISC, DIRINT, BRL) are formulated
per site and operate on a 1-D time series.  Applying them to the full
``(time, y, x)`` grid means looping/batching over every cell, which is
slow and — because the result is a *model estimate* — usually not
worth precomputing for the whole archive. This is also the reason
``transform.py`` doesn't compute DNI/DHI in bulk: pvlib's DIRINT/DISC
are 1-D-per-site and cannot broadcast over MERRA-2's full grid (see
``transform.py``'s module docstring). Extracting one building location
(or a small bounding box) and decomposing just that is fast
(milliseconds to seconds) and keeps the modelling assumptions explicit.

Two paths are provided:

* :func:`extract_dni_dhi_dirint` — pvlib **DIRINT** (Perez et al.,
  1992): pressure-aware, fast, good default.
* :func:`extract_dni_dhi_disc` — pvlib **DISC** then complete the
  irradiance triangle; the classic Maxwell (1987) model.

Both use pvlib's NREL **SPA** solar position (gold-standard, <0.0003°)
for the single column — affordable because it is one location, unlike
the gridded case where Spencer is used for speed (see
``transform.spencer_zenith``, reused from ``era5_land.transform``).

Timestamp note
--------------
MERRA-2's hourly timestamps sit at ``HH:30`` (the averaging-interval
midpoint), not ``HH:00`` like ERA5-Land/COSMO (see
``docs/MERRA2_PIPELINE_GUIDE.md``'s "Timestamp convention" section).
This has no effect here: the solar position (and hence DNI/DHI split)
is computed at whatever timestamp the GHI series is actually indexed
by, so the ``HH:30`` offset is handled correctly automatically — there
is nothing to adjust in this module for it.

Usage
-----
::

    import xarray as xr
    from weather.providers.merra2.dni_pointwise import (
        extract_dni_dhi_dirint,
    )

    ds = xr.open_mfdataset(
        "/data/soma/merra2/output/MERRA2_2018_??_all_attrs.nc"
    )
    # Pick a location (nearest grid cell to a lat/lon):
    cell = ds.sel(latitude=52.1, longitude=4.3, method="nearest")

    result = extract_dni_dhi_dirint(
        ghi=cell["GHI"].to_series(),
        latitude=float(cell["latitude"]),
        longitude=float(cell["longitude"]),
        pressure=cell["PS"].to_series(),   # Pa, optional
    )
    dni = result["DNI"]   # pandas Series, W/m^2
    dhi = result["DHI"]
"""

from __future__ import annotations

from typing import Any

from ...common.dni_reconstruction import reconstruct_dni_dhi


def extract_dni_dhi_dirint(
    ghi: Any,
    latitude: float,
    longitude: float,
    pressure: Any | None = None,
) -> dict[str, Any]:
    """DNI/DHI for one location via pvlib DIRINT (pressure-aware).

    Parameters
    ----------
    ghi : pandas.Series
        Hourly GHI (W/m^2) indexed by (tz-aware or naive UTC)
        timestamps, as stored by the MERRA-2 pipeline (``HH:30``).
    latitude, longitude : float
        Location in degrees.
    pressure : pandas.Series or float, optional
        Surface pressure in **Pascals** (MERRA-2 ``PS`` is already Pa,
        same convention as ERA5-Land's ``sp``). Defaults to standard
        atmosphere.

    Returns
    -------
    dict
        ``{"DNI": Series, "DHI": Series}`` in W/m^2, clipped >= 0.
    """
    return reconstruct_dni_dhi(
        ghi, latitude, longitude, method="dirint", pressure=pressure
    )


def extract_dni_dhi_disc(
    ghi: Any,
    latitude: float,
    longitude: float,
    pressure: Any | None = None,
) -> dict[str, Any]:
    """DNI/DHI for one location via pvlib DISC (Maxwell 1987).

    Same signature and return shape as :func:`extract_dni_dhi_dirint`.
    DISC is the predecessor of DIRINT; provided for comparison /
    validation.
    """
    return reconstruct_dni_dhi(
        ghi, latitude, longitude, method="disc", pressure=pressure
    )
