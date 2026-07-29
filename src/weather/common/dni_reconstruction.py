"""Shared single-location DNI/DHI reconstruction from GHI.

This is the single source of truth for the pvlib DIRINT/DISC point-of-use
decomposition previously duplicated identically across
``providers.era5_land.dni_pointwise`` and ``providers.merra2.dni_pointwise``.
Both now delegate here. See those modules for the "why point-of-use, not
bulk" rationale.

Usage::

    from weather.common.dni_reconstruction import reconstruct_dni_dhi

    result = reconstruct_dni_dhi(
        ghi=cell["GHI"].to_series(),
        latitude=52.1, longitude=4.3,
        method="dirint", pressure=cell["sp"].to_series(),
    )
    dni, dhi = result["DNI"], result["DHI"]
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

_STD_PRESSURE_PA: float = 101325.0


def _solar_position(times: Any, latitude: float, longitude: float) -> Any:
    """Return pvlib NREL-SPA solar position for one location."""
    import pvlib  # optional heavy dependency (the `solar` extra)

    return pvlib.solarposition.get_solarposition(
        time=times, latitude=latitude, longitude=longitude
    )


def _align_pressure(pressure: Any, times: pd.DatetimeIndex) -> pd.Series:
    """Return *pressure* reindexed onto *times*, tz-alignment-safe.

    A plain ``.reindex(times)`` against a tz-aware target when *pressure*
    is tz-naive silently returns all-NaN (tz-naive and tz-aware timestamps
    never compare equal), which propagates through pvlib's ``disc``/
    ``dirint`` airmass calculation into an all-zero DNI — no exception, no
    warning, just quietly wrong output. Match tz-awareness before
    reindexing to avoid this.
    """
    if np.isscalar(pressure):
        return pd.Series(pressure, index=times)
    pres = pd.Series(pressure)
    pres_idx = pd.DatetimeIndex(pres.index)
    if pres_idx.tz is None:
        pres_idx = pres_idx.tz_localize("UTC")
    pres.index = pres_idx
    return pres.reindex(times)


def reconstruct_dni_dhi(
    ghi: Any,
    latitude: float,
    longitude: float,
    *,
    method: str = "dirint",
    pressure: Any | None = None,
    zenith_kind: str = "zenith",
    clip_to_extraterrestrial: bool = False,
    clip_dhi_to_ghi: bool = False,
) -> dict[str, pd.Series]:
    """DNI/DHI for one location from a GHI time series.

    Parameters
    ----------
    ghi : pandas.Series
        Hourly GHI (W/m^2) indexed by (tz-aware or naive UTC) timestamps.
    latitude, longitude : float
        Location in degrees.
    method : str
        ``"dirint"`` (Perez et al., 1992; pressure-aware, fast, good
        default) or ``"disc"`` (Maxwell 1987; the DISC predecessor).
    pressure : pandas.Series or float, optional
        Surface pressure in Pascals. Defaults to standard atmosphere.
        Only used by DIRINT/DISC's airmass correction.
    zenith_kind : str
        ``"zenith"`` (true geometric, matches the original per-provider
        ``dni_pointwise`` behaviour) or ``"apparent"`` (refraction-
        corrected, matches ``CsvWeatherData.reconstruct_dni_from_ghi``'s
        historical COSMO-CSV behaviour).
    clip_to_extraterrestrial : bool
        If True, additionally clip DNI to ``pvlib.irradiance.
        get_extra_radiation`` (physical upper bound) — matches
        ``CsvWeatherData.reconstruct_dni_from_ghi``'s behaviour. Default
        False, matching the original per-provider ``dni_pointwise``
        behaviour (relies on the model itself staying physical).
    clip_dhi_to_ghi : bool
        If True, additionally clip DHI to ``ghi`` (diffuse can't exceed
        total horizontal irradiance) — matches ``CsvWeatherData.
        reconstruct_dni_from_ghi``'s behaviour. Default False, matching
        the original per-provider ``dni_pointwise`` behaviour.

    Returns
    -------
    dict
        ``{"DNI": Series, "DHI": Series}`` in W/m^2, clipped >= 0,
        night-masked (zenith >= 90 deg -> 0).
    """
    import pvlib

    if method not in ("dirint", "disc"):
        raise ValueError(
            f"Unknown method: {method!r}. Expected 'dirint' or 'disc'."
        )
    if zenith_kind not in ("zenith", "apparent"):
        raise ValueError(
            f"Unknown zenith_kind: {zenith_kind!r}. "
            "Expected 'zenith' or 'apparent'."
        )

    ghi = pd.Series(ghi)
    times = pd.DatetimeIndex(ghi.index)
    if times.tz is None:
        times = times.tz_localize("UTC")
        ghi.index = times

    solpos = _solar_position(times, latitude, longitude)
    zenith = (
        solpos["apparent_zenith"] if zenith_kind == "apparent"
        else solpos["zenith"]
    )

    if pressure is None:
        pressure = _STD_PRESSURE_PA
    pres = _align_pressure(pressure, times)

    if method == "dirint":
        dni = (
            pvlib.irradiance.dirint(
                ghi=ghi, solar_zenith=zenith, times=times, pressure=pres
            )
            .fillna(0.0)
            .clip(lower=0.0)
        )
    else:
        disc = pvlib.irradiance.disc(
            ghi=ghi, solar_zenith=zenith, datetime_or_doy=times, pressure=pres
        )
        dni = disc["dni"].fillna(0.0).clip(lower=0.0)
        if clip_to_extraterrestrial:
            dni_extra = pvlib.irradiance.get_extra_radiation(times.dayofyear)
            dni = dni.clip(upper=dni_extra)

    cos_z = np.cos(np.radians(zenith))
    dhi_upper = ghi if clip_dhi_to_ghi else None
    dhi = (ghi - dni * cos_z).clip(lower=0.0, upper=dhi_upper)

    # Night mask (zenith >= 90 deg) for consistency with stored GHI.
    night = zenith >= 90.0
    dni[night] = 0.0
    dhi[night] = 0.0

    return {"DNI": dni, "DHI": dhi}
