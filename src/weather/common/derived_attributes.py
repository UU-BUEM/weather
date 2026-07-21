"""Cross-provider irradiance derivation (GHI, DHI, DNI).

Implements the DIRINT pressure-aware decomposition algorithm for
providers that only supply total GHI (MERRA-2, ERA5-Land), and a
direct geometrically-consistent formula for COSMO-REA6 which provides
separate beam and diffuse components.

Algorithm selection by provider
--------------------------------
+-------------+-------+-------+-------+----------------------------------+
| Provider    | GHI   | DHI   | DNI   | Method                           |
+=============+=======+=======+=======+==================================+
| COSMO_REA6  | sum   | direct| guard | SWDIFDS+SWDIRS / cos(z) guard    |
| MERRA2      | passthrough | DIRINT| DIRINT | pvlib.dirint (pressure) |
| ERA5_LAND   | /3600 | DIRINT| DIRINT | pvlib.dirint (pressure)          |
+-------------+-------+-------+-------+----------------------------------+

Post-derivation standardisation
---------------------------------
All formula functions apply the following uniformity rules:

1. **Night masking**: zenith >= 90 deg -> 0.0 W/m2 (no floating-point
   artefacts during darkness).
2. **Physical clipping**: all results clipped to [0, inf).
3. **Pressure units**: pvlib.dirint expects raw Pascals; both MERRA-2
   (PS) and ERA5-Land (sp) provide Pa natively — no conversion needed.

Typical usage::

    from weather.common.derived_attributes import apply_derived_fields

    results = apply_derived_fields(
        ds=my_dataset,
        provider="MERRA2",
        sol_pos={"zenith": zenith_array},
        times=pd.date_range(..., tz="UTC"),
    )
    ghi = results["GHI"]   # np.ndarray, night-masked, clipped >= 0
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Solar zenith threshold (degrees) above which irradiance is forced to 0.
NIGHT_ZENITH_DEG: float = 90.0

#: cos(zenith) guard for COSMO-REA6 DNI — below this (~85 deg) the
#: direct beam path is too long and the division diverges unreliably.
_COS_GUARD: float = 0.087  # cos(85 deg)

#: Standard atmosphere pressure (Pa) used when the dataset has no
#: surface-pressure variable.
_STD_PRESSURE_PA: float = 101325.0


# ---------------------------------------------------------------------------
# Night masking and physical clipping
# ---------------------------------------------------------------------------

def mask_night(
    arr: np.ndarray,
    zenith: np.ndarray,
    threshold: float = NIGHT_ZENITH_DEG,
) -> np.ndarray:
    """Return *arr* with night-time values set to 0.0.

    Parameters
    ----------
    arr : array-like
        Irradiance values (any shape broadcastable with *zenith*).
    zenith : array-like
        Solar zenith angle in degrees.
    threshold : float
        Zenith angle at/above which the result is set to 0.0.
        Default: :data:`NIGHT_ZENITH_DEG` (90 deg).

    Returns
    -------
    np.ndarray
        Clipped and night-masked array.
    """
    arr = np.asarray(arr, dtype=float)
    z = np.asarray(zenith, dtype=float)
    return np.where(z >= threshold, 0.0, arr).clip(min=0.0)


# ---------------------------------------------------------------------------
# DIRINT pressure-aware decomposition (MERRA-2, ERA5-Land)
# ---------------------------------------------------------------------------

def _dirint_dni(
    ghi: np.ndarray,
    zenith: np.ndarray,
    pressure: np.ndarray | float,
    times: Any,
) -> np.ndarray:
    """Compute DNI via the DIRINT algorithm.

    DIRINT (Perez et al., 1992) is a pressure-aware improvement on
    the DISC model.  It accepts surface pressure in Pascals directly;
    no unit conversion is required.

    Parameters
    ----------
    ghi : array-like
        Global Horizontal Irradiance (W/m2).
    zenith : array-like
        Solar zenith angle (degrees).
    pressure : array-like or float
        Surface pressure in Pascals.  Standard atmosphere (101325 Pa)
        is used automatically if the dataset has no pressure variable.
    times : DatetimeIndex or array-like
        UTC timestamps corresponding to the time axis.

    Returns
    -------
    np.ndarray
        DNI in W/m2, clipped to [0, inf).
    """
    import pandas as pd
    import pvlib  # optional heavy dependency

    idx = pd.DatetimeIndex(times)
    ghi_s = pd.Series(np.asarray(ghi, dtype=float), index=idx)
    zen_s = pd.Series(np.asarray(zenith, dtype=float), index=idx)
    pres_s = pd.Series(
        np.broadcast_to(
            np.asarray(pressure, dtype=float),
            ghi_s.shape,
        ).copy(),
        index=idx,
    )

    dni = pvlib.irradiance.dirint(
        ghi=ghi_s,
        solar_zenith=zen_s,
        times=idx,
        pressure=pres_s,
    ).fillna(0.0).clip(lower=0.0)

    return dni.values


def _dirint_dhi(
    ghi: np.ndarray,
    zenith: np.ndarray,
    pressure: np.ndarray | float,
    times: Any,
) -> np.ndarray:
    """Compute DHI = GHI - DNI * cos(zenith) via the DIRINT algorithm.

    Uses the radiation energy-balance equation after computing DNI via
    :func:`_dirint_dni`.  Result is clipped to [0, inf) to prevent
    small negative residuals from floating-point arithmetic.

    Parameters
    ----------
    ghi, zenith, pressure, times
        Same as :func:`_dirint_dni`.

    Returns
    -------
    np.ndarray
        DHI in W/m2, clipped to [0, inf).
    """
    dni = _dirint_dni(ghi, zenith, pressure, times)
    cos_z = np.cos(np.radians(np.asarray(zenith, dtype=float)))
    dhi = np.asarray(ghi, dtype=float) - dni * cos_z
    return dhi.clip(min=0.0)


# ---------------------------------------------------------------------------
# COSMO-REA6 formula functions
# ---------------------------------------------------------------------------

def _cosmo_ghi(
    ds: dict[str, Any],
    sol_pos: dict[str, Any],
    times: Any,
) -> np.ndarray:
    """GHI = SWDIFDS_RAD + SWDIRS_RAD, night-masked."""
    ghi = (
        np.asarray(ds["SWDIFDS_RAD"], dtype=float)
        + np.asarray(ds["SWDIRS_RAD"], dtype=float)
    )
    return mask_night(ghi, sol_pos["zenith"])


def _cosmo_dhi(
    ds: dict[str, Any],
    sol_pos: dict[str, Any],
    times: Any,
) -> np.ndarray:
    """DHI = SWDIFDS_RAD (diffuse component), night-masked."""
    return mask_night(
        np.asarray(ds["SWDIFDS_RAD"], dtype=float),
        sol_pos["zenith"],
    )


def _cosmo_dni(
    ds: dict[str, Any],
    sol_pos: dict[str, Any],
    times: Any,
) -> np.ndarray:
    """DNI = SWDIRS_RAD / cos(zenith) with a zenith guard.

    Values where cos(zenith) <= ``_COS_GUARD`` (~85 deg) are set to 0
    to prevent divergence near the horizon.
    """
    cos_z = np.cos(
        np.radians(np.asarray(sol_pos["zenith"], dtype=float))
    )
    safe_cos = np.where(cos_z > _COS_GUARD, cos_z, np.nan)
    dni = np.asarray(ds["SWDIRS_RAD"], dtype=float) / safe_cos
    return mask_night(
        np.nan_to_num(dni, nan=0.0),
        sol_pos["zenith"],
    )


# ---------------------------------------------------------------------------
# MERRA-2 formula functions
# ---------------------------------------------------------------------------

def _merra2_ghi(
    ds: dict[str, Any],
    sol_pos: dict[str, Any],
    times: Any,
) -> np.ndarray:
    """GHI = SWGDN (instantaneous W/m2), night-masked."""
    return mask_night(
        np.asarray(ds["SWGDN"], dtype=float),
        sol_pos["zenith"],
    )


def _merra2_dhi(
    ds: dict[str, Any],
    sol_pos: dict[str, Any],
    times: Any,
) -> np.ndarray:
    """DHI via DIRINT pressure-aware decomposition.

    Surface pressure is read from ``ds["PS"]`` (Pa).  Falls back to
    standard atmosphere when the key is absent.
    """
    pressure = ds.get("PS", _STD_PRESSURE_PA)
    dhi = _dirint_dhi(
        ds["SWGDN"], sol_pos["zenith"], pressure, times
    )
    return mask_night(dhi, sol_pos["zenith"])


def _merra2_dni(
    ds: dict[str, Any],
    sol_pos: dict[str, Any],
    times: Any,
) -> np.ndarray:
    """DNI via DIRINT pressure-aware decomposition.

    Surface pressure is read from ``ds["PS"]`` (Pa).  Falls back to
    standard atmosphere when the key is absent.
    """
    pressure = ds.get("PS", _STD_PRESSURE_PA)
    dni = _dirint_dni(
        ds["SWGDN"], sol_pos["zenith"], pressure, times
    )
    return mask_night(dni, sol_pos["zenith"])


# ---------------------------------------------------------------------------
# ERA5-Land formula functions
# ---------------------------------------------------------------------------

def _era5_ghi(
    ds: dict[str, Any],
    sol_pos: dict[str, Any],
    times: Any,
) -> np.ndarray:
    """GHI = ssrd / 3600 (J/m2 -> W/m2), night-masked."""
    ghi = np.asarray(ds["ssrd"], dtype=float) / 3600.0
    return mask_night(ghi, sol_pos["zenith"])


def _era5_dhi(
    ds: dict[str, Any],
    sol_pos: dict[str, Any],
    times: Any,
) -> np.ndarray:
    """DHI via DIRINT pressure-aware decomposition.

    Surface pressure is read from ``ds["sp"]`` (Pa).  Falls back to
    standard atmosphere when the key is absent.
    """
    ghi = (np.asarray(ds["ssrd"], dtype=float) / 3600.0).clip(
        min=0.0
    )
    pressure = ds.get("sp", _STD_PRESSURE_PA)
    dhi = _dirint_dhi(ghi, sol_pos["zenith"], pressure, times)
    return mask_night(dhi, sol_pos["zenith"])


def _era5_dni(
    ds: dict[str, Any],
    sol_pos: dict[str, Any],
    times: Any,
) -> np.ndarray:
    """DNI via DIRINT pressure-aware decomposition.

    Surface pressure is read from ``ds["sp"]`` (Pa).  Falls back to
    standard atmosphere when the key is absent.
    """
    ghi = (np.asarray(ds["ssrd"], dtype=float) / 3600.0).clip(
        min=0.0
    )
    pressure = ds.get("sp", _STD_PRESSURE_PA)
    dni = _dirint_dni(ghi, sol_pos["zenith"], pressure, times)
    return mask_night(dni, sol_pos["zenith"])


def _era5_rh(
    ds: dict[str, Any],
    sol_pos: dict[str, Any],
    times: Any,
) -> np.ndarray:
    """Relative humidity (%) via the August-Roche-Magnus approximation.

    Computed from 2 m temperature and 2 m dew point.  Inputs are read
    in **Kelvin** (ERA5-Land raw ``t2m``/``d2m``) and converted to
    Celsius internally::

        RH = 100 * exp( a*Td/(b+Td) - a*T/(b+T) )

    with ``a = 17.625``, ``b = 243.04`` and T, Td in degC.  Result is
    clipped to [0, 100].

    .. note::
       The gridded pipeline computes RH inside
       ``providers.era5_land.transform`` (from raw Kelvin, before unit
       conversion).  This registry entry mirrors that formula so the
       manifest is complete and self-describing; pass raw-Kelvin
       ``t2m``/``d2m`` if calling it directly.
    """
    t2m = np.asarray(ds["t2m"], dtype=float)
    d2m = np.asarray(ds["d2m"], dtype=float)
    t = t2m - 273.15
    td = d2m - 273.15
    a, b = 17.625, 243.04
    rh = 100.0 * np.exp((a * td) / (b + td) - (a * t) / (b + t))
    return np.clip(rh, 0.0, 100.0)


def _era5_wind_speed(
    ds: dict[str, Any],
    sol_pos: dict[str, Any],
    times: Any,
) -> np.ndarray:
    """Scalar 10 m wind speed ``WS_10M = sqrt(u10**2 + v10**2)`` (m/s).

    Magnitude is frame-invariant, so no vector rotation is needed.
    """
    u = np.asarray(ds["u10"], dtype=float)
    v = np.asarray(ds["v10"], dtype=float)
    return np.sqrt(u ** 2 + v ** 2)


# ---------------------------------------------------------------------------
# DERIVED_FIELDS registry
# ---------------------------------------------------------------------------

#: Provider-keyed registry mapping field names to metadata and the
#: callable ``formula(ds, sol_pos, times) -> np.ndarray``.
DERIVED_FIELDS: dict[str, dict[str, dict[str, Any]]] = {
    "COSMO_REA6": {
        "GHI": {
            "description": (
                "Global Horizontal Irradiance "
                "= SWDIFDS_RAD + SWDIRS_RAD"
            ),
            "unit": "W/m2",
            "formula": _cosmo_ghi,
        },
        "DHI": {
            "description": (
                "Diffuse Horizontal Irradiance = SWDIFDS_RAD"
            ),
            "unit": "W/m2",
            "formula": _cosmo_dhi,
        },
        "DNI": {
            "description": (
                "Direct Normal Irradiance "
                "= SWDIRS_RAD / cos(zenith), "
                "guarded at zenith > 85 deg"
            ),
            "unit": "W/m2",
            "formula": _cosmo_dni,
        },
    },
    "MERRA2": {
        "GHI": {
            "description": (
                "Global Horizontal Irradiance = SWGDN"
            ),
            "unit": "W/m2",
            "formula": _merra2_ghi,
        },
        "DHI": {
            "description": (
                "Diffuse Horizontal Irradiance "
                "via DIRINT pressure-aware decomposition"
            ),
            "unit": "W/m2",
            "formula": _merra2_dhi,
        },
        "DNI": {
            "description": (
                "Direct Normal Irradiance "
                "via DIRINT pressure-aware decomposition"
            ),
            "unit": "W/m2",
            "formula": _merra2_dni,
        },
    },
    # ERA5-Land supplies only total shortwave (ssrd), so only GHI is a
    # *gridded* derived field.  DNI/DHI require a per-site decomposition
    # (DIRINT/DISC) whose pvlib implementation is 1-D-in-time and cannot
    # broadcast over (time, y, x); attempting it on the grid raises.
    # Those are therefore provided as an opt-in point/region helper in
    # ``weather.providers.era5_land.dni_pointwise`` rather than here.
    "ERA5_LAND": {
        "GHI": {
            "description": (
                "Global Horizontal Irradiance: ssrd de-accumulated "
                "per UTC day, divided by 3600 s (hourly-mean flux)"
            ),
            "unit": "W/m2",
            "formula": _era5_ghi,
        },
        "RH": {
            "description": (
                "Relative Humidity via Magnus formula from 2 m "
                "temperature and 2 m dew point"
            ),
            "unit": "%",
            "formula": _era5_rh,
        },
        "WS_10M": {
            "description": (
                "Scalar 10 m wind speed from u/v components"
            ),
            "unit": "m/s",
            "formula": _era5_wind_speed,
        },
    },
}

#: Canonical output variable names (provider-agnostic).
OUTPUT_NAMES: tuple[str, ...] = ("GHI", "DHI", "DNI")

#: Valid provider keys.
PROVIDERS: tuple[str, ...] = tuple(DERIVED_FIELDS.keys())


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def apply_derived_fields(
    ds: dict[str, Any],
    provider: str,
    sol_pos: dict[str, Any],
    times: Any,
    fields: list[str] | None = None,
) -> dict[str, np.ndarray]:
    """Compute derived irradiance fields for a given provider.

    Parameters
    ----------
    ds : dict-like or xarray.Dataset
        Source dataset keyed by provider-specific raw variable names.
        Variables are coerced to ``np.ndarray`` internally so both
        plain dicts and xarray Datasets are accepted.
    provider : str
        One of ``"COSMO_REA6"``, ``"MERRA2"``, ``"ERA5_LAND"``.
    sol_pos : dict
        Solar position dict with at minimum a ``"zenith"`` key
        (degrees, 1-D, same length as the time axis).
    times : DatetimeIndex or array-like
        UTC timestamps.  Must be timezone-aware for DIRINT.
    fields : list[str], optional
        Subset of fields to compute.  Default: all fields registered
        for the provider (``["GHI", "DHI", "DNI"]``).

    Returns
    -------
    dict[str, np.ndarray]
        Mapping field name -> numpy array, night-masked and clipped
        to ``[0, inf)``.

    Raises
    ------
    ValueError
        If *provider* is not in :data:`PROVIDERS` or a requested
        *field* is not registered for that provider.

    Examples
    --------
    >>> results = apply_derived_fields(
    ...     ds=my_ds,
    ...     provider="MERRA2",
    ...     sol_pos={"zenith": zenith_arr},
    ...     times=pd.date_range("2018-01-01", periods=N,
    ...                         freq="h", tz="UTC"),
    ... )
    >>> ghi = results["GHI"]
    """
    registry = DERIVED_FIELDS.get(provider)
    if registry is None:
        raise ValueError(
            f"Unknown provider: {provider!r}. "
            f"Valid options: {list(PROVIDERS)}"
        )

    requested = fields or list(registry.keys())
    unknown = [f for f in requested if f not in registry]
    if unknown:
        raise ValueError(
            f"Fields {unknown!r} not registered for "
            f"provider {provider!r}."
        )

    results: dict[str, np.ndarray] = {}
    for name in requested:
        logger.debug(
            "Computing %s for provider %s", name, provider
        )
        results[name] = registry[name]["formula"](
            ds, sol_pos, times
        )
    return results


def field_metadata(provider: str, field: str) -> dict[str, Any]:
    """Return description and unit for a derived field.

    Parameters
    ----------
    provider : str
        Provider key (see :data:`PROVIDERS`).
    field : str
        Field name (e.g. ``"GHI"``).

    Returns
    -------
    dict
        ``{"description": str, "unit": str}``.
    """
    registry = DERIVED_FIELDS.get(provider, {})
    entry = registry.get(field, {})
    return {
        "description": entry.get("description", ""),
        "unit": entry.get("unit", ""),
    }
