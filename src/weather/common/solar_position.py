"""Shared solar-position astronomy — provider-agnostic.

Single source of truth for the Spencer (1971) solar zenith angle
formula, used by every provider that needs it (ERA5-Land, MERRA-2
directly; COSMO-REA6 implements the same algorithm inline in
``providers.cosmo_rea6.transform.compute_dni``, dask-chunked for its
much larger 824x848 grid -- see that function's docstring for why it
isn't routed through this plain-NumPy version, and
``docs/dni_methodology.md`` sec 2-3 for the full accuracy/performance
rationale).

Typical usage::

    from weather.common.solar_position import spencer_zenith

    zenith_deg = spencer_zenith(times, lat, lon)
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def spencer_zenith(
    times: Any,
    lat: np.ndarray,
    lon: np.ndarray,
) -> np.ndarray:
    """Solar zenith angle (degrees) via the Spencer (1971) Fourier series.

    Pure NumPy broadcasting; identical algorithm to the COSMO-REA6
    ``compute_dni`` solar-position step (see ``dni_methodology.md``).

    Parameters
    ----------
    times : pandas.DatetimeIndex
        UTC timestamps (length T).
    lat, lon : np.ndarray
        Geographic latitude/longitude in degrees.  May be 1-D coordinate
        vectors or 2-D auxiliary arrays; broadcasting yields the output
        spatial shape.

    Returns
    -------
    np.ndarray
        Zenith angle in degrees, shape ``(T,) + np.broadcast(lat, lon)``.
    """

    idx = pd.DatetimeIndex(times)
    doy = idx.dayofyear.to_numpy().astype(np.float64)
    utc_h = (
        idx.hour.to_numpy()
        + idx.minute.to_numpy() / 60.0
        + idx.second.to_numpy() / 3600.0
    ).astype(np.float64)

    # Day angle B (radians).
    b = (doy - 1.0) * 2.0 * np.pi / 365.0

    # Equation of time (minutes).
    e_t = 229.18 * (
        0.000075
        + 0.001868 * np.cos(b)
        - 0.032077 * np.sin(b)
        - 0.014615 * np.cos(2 * b)
        - 0.040890 * np.sin(2 * b)
    )

    # Solar declination (radians).
    decl = (
        0.006918
        - 0.399912 * np.cos(b)
        + 0.070257 * np.sin(b)
        - 0.006758 * np.cos(2 * b)
        + 0.000907 * np.sin(2 * b)
        - 0.002697 * np.cos(3 * b)
        + 0.001480 * np.sin(3 * b)
    )

    lat_r = np.radians(np.asarray(lat, dtype=np.float64))
    lon_d = np.asarray(lon, dtype=np.float64)

    # Reshape time-dependent terms to broadcast over spatial dims.
    spatial_ndim = lat_r.ndim
    t_shape = (len(idx),) + (1,) * spatial_ndim
    utc_h_b = utc_h.reshape(t_shape)
    e_t_b = e_t.reshape(t_shape)
    decl_b = decl.reshape(t_shape)
    b_shape = (1,) + lat_r.shape

    # Hour angle omega (radians): lon in degrees, E_t in minutes.
    omega = (np.pi / 12.0) * (
        utc_h_b - 12.0 + lon_d.reshape(b_shape) / 15.0 + e_t_b / 60.0
    )

    lat_b = lat_r.reshape(b_shape)
    cos_z = (
        np.sin(lat_b) * np.sin(decl_b)
        + np.cos(lat_b) * np.cos(decl_b) * np.cos(omega)
    )
    cos_z = np.clip(cos_z, -1.0, 1.0)
    return np.degrees(np.arccos(cos_z))
