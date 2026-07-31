"""Single-location weather lookup from already-processed provider archives.

This module does **not** download or process data itself — it only opens
NetCDF files that a prior ``weather run --provider ... --year ...`` (or
equivalent pipeline call) already produced, and extracts the nearest grid
cell's ``T``/``GHI``/``DHI``/``DNI`` for one ``(latitude, longitude, year)``.
This keeps it import-light: only ``numpy``/``pandas``/``xarray``/``netcdf4``
(the ``pointquery`` extra) plus ``pvlib`` (the ``solar`` extra) for DNI/DHI
reconstruction — never the GRIB/download/transform pipeline stack
(``cfgrib``, ``dask``, ``eccodes``, ``pyproj`` — the ``pipeline`` extra).

Typical usage::

    from weather import get_point_weather

    df = get_point_weather(52.0, 5.0, 2018, provider="era5-land")
    # df: DatetimeIndex, columns T (degC), GHI/DHI/DNI (W/m2)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pandas as pd

from .common.dni_reconstruction import reconstruct_dni_dhi
from .common.env import data_root
from .common.geo_lookup import find_nearest_cell

logger = logging.getLogger(__name__)

_ALIASES: dict[str, str] = {
    "cosmo": "cosmo-rea6",
    "cosmo-rea6": "cosmo-rea6",
    "merra2": "merra-2",
    "merra-2": "merra-2",
    "era5": "era5-land",
    "era5-land": "era5-land",
}

_OUTPUT_SUBDIR: dict[str, str] = {
    "cosmo-rea6": "cosmo_rea6",
    "era5-land": "era5_land",
    "merra-2": "merra2",
}

_REQUIRED_COLUMNS = ("T", "GHI", "DHI", "DNI")


def _import_xarray() -> Any:
    """Lazy-import xarray (the `pointquery` extra, not needed at import time)."""
    try:
        import xarray as xr

        return xr
    except ImportError as exc:
        raise ImportError(
            "xarray and netcdf4 are required for weather.get_point_weather(). "
            "Install with: pip install weather[pointquery]"
        ) from exc


def _output_dir(canonical: str, data_dir: Path | str | None) -> Path:
    """Resolve the directory containing a provider's already-exported files.

    Mirrors each provider's own ``<work_dir>/output`` convention
    (``EnvSettings.<provider>_output_dir()``) without importing the
    provider package itself — importing e.g. ``weather.providers.era5_land``
    would execute that package's ``__init__.py``, which imports its heavy
    pipeline module. *data_dir*, if given, overrides this entirely.
    """
    if data_dir is not None:
        return Path(data_dir)
    return data_root() / _OUTPUT_SUBDIR[canonical] / "output"


def _finalize(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize the index to tz-naive and select the canonical columns."""
    idx = pd.DatetimeIndex(df.index)
    if idx.tz is not None:
        idx = idx.tz_convert(None)
    df = df.copy()
    df.index = idx
    return df[list(_REQUIRED_COLUMNS)]


def _strip_tz(series: pd.Series) -> pd.Series:
    """Return *series* with a tz-naive index, converting if necessary.

    ``reconstruct_dni_dhi`` localizes a tz-naive GHI index to UTC on its
    own internal copy before computing DNI/DHI, so its returned Series can
    come back tz-**aware** even when the caller's GHI/T Series (straight
    off the NetCDF ``time`` coordinate) are tz-naive. Combining tz-naive
    and tz-aware Series in one ``pd.DataFrame({...})`` aligns on the
    union of their indices — which never match between naive and aware
    timestamps — silently producing all-NaN columns. Normalize before
    combining, not after.
    """
    idx = pd.DatetimeIndex(series.index)
    if idx.tz is not None:
        series = series.copy()
        series.index = idx.tz_convert(None)
    return series


def _temperature_series(cell: Any, legacy_name: str) -> pd.Series:
    """Return the Celsius temperature Series, tolerating pre-fix archives.

    Both ERA5-Land and MERRA-2 now export a canonical ``T`` column
    (matching COSMO-REA6); archives produced before that rename carry the
    raw provider name instead (already Celsius, just not renamed).
    """
    if "T" in cell:
        return cell["T"].to_series()
    return cell[legacy_name].to_series()


def _pressure_series(cell: Any, legacy_name: str) -> pd.Series | None:
    """Return the Pa pressure Series, tolerating pre-fix archives.

    ERA5-Land and MERRA-2 now both export a canonical ``PS`` column
    (matching COSMO-REA6); archives produced before that rename carry
    ERA5-Land's raw ``sp`` instead (MERRA-2 was already ``PS``, so its
    legacy name is the same as the canonical one -- a harmless no-op
    lookup). ``None`` if neither is present (falls back to the
    scalar/no-pressure path in :func:`reconstruct_dni_dhi`).
    """
    if "PS" in cell:
        return cell["PS"].to_series()
    if legacy_name in cell:
        return cell[legacy_name].to_series()
    return None


def _get_point_regular_grid(
    latitude: float,
    longitude: float,
    year: int,
    data_dir: Path | str | None,
    *,
    canonical: str,
    filename_glob: str,
    legacy_pressure_var: str,
    legacy_temperature_var: str,
) -> pd.DataFrame:
    """Shared point extraction for ERA5-Land/MERRA-2's regular lat/lon grid."""
    xr = _import_xarray()
    out_dir = _output_dir(canonical, data_dir)
    paths = sorted(out_dir.glob(filename_glob))
    if not paths:
        raise FileNotFoundError(
            f"No processed {canonical} files matching {filename_glob!r} "
            f"under {out_dir}. Run the {canonical} pipeline for {year} "
            "first (weather run --provider "
            f"{canonical} --year {year})."
        )
    ds = xr.open_mfdataset([str(p) for p in paths], combine="by_coords")
    cell = ds.sel(latitude=latitude, longitude=longitude, method="nearest")

    ghi = cell["GHI"].to_series()
    t = _temperature_series(cell, legacy_temperature_var)
    pressure = _pressure_series(cell, legacy_pressure_var)
    dni_dhi = reconstruct_dni_dhi(
        ghi,
        float(cell["latitude"]),
        float(cell["longitude"]),
        method="dirint",
        pressure=pressure,
    )
    dni = _strip_tz(dni_dhi["DNI"])
    dhi = _strip_tz(dni_dhi["DHI"])
    return _finalize(pd.DataFrame({"T": t, "GHI": ghi, "DNI": dni, "DHI": dhi}))


def _get_point_era5_land(
    latitude: float, longitude: float, year: int, data_dir: Path | str | None
) -> pd.DataFrame:
    return _get_point_regular_grid(
        latitude, longitude, year, data_dir,
        canonical="era5-land",
        filename_glob=f"ERA5_LAND_{year}_??_all_attrs.nc",
        legacy_pressure_var="sp",
        legacy_temperature_var="t2m",
    )


def _get_point_merra2(
    latitude: float, longitude: float, year: int, data_dir: Path | str | None
) -> pd.DataFrame:
    return _get_point_regular_grid(
        latitude, longitude, year, data_dir,
        canonical="merra-2",
        filename_glob=f"MERRA2_{year}_??_all_attrs.nc",
        legacy_pressure_var="PS",
        legacy_temperature_var="T2M",
    )


def _get_point_cosmo_rea6(
    latitude: float, longitude: float, year: int, data_dir: Path | str | None
) -> pd.DataFrame:
    xr = _import_xarray()
    out_dir = _output_dir("cosmo-rea6", data_dir)

    annual_path = out_dir / f"COSMO_REA6_{year}.nc"
    if annual_path.exists():
        ds = xr.open_dataset(str(annual_path))
    else:
        paths = sorted(out_dir.glob(f"COSMO_REA6_{year}_??_all_attrs.nc"))
        if not paths:
            raise FileNotFoundError(
                f"No processed cosmo-rea6 file for {year} under {out_dir} "
                f"(looked for COSMO_REA6_{year}.nc or "
                f"COSMO_REA6_{year}_??_all_attrs.nc). Run the pipeline for "
                f"{year} first (weather run --provider cosmo-rea6 --year "
                f"{year})."
            )
        ds = xr.open_mfdataset([str(p) for p in paths], combine="by_coords")

    iy, ix = find_nearest_cell(ds, latitude, longitude)
    cell = ds.isel(y=iy, x=ix)

    ghi = cell["GHI"].to_series()
    t = _temperature_series(cell, "T_2M")
    cell_lat = float(cell["latitude"]) if "latitude" in cell.coords else latitude
    cell_lon = float(cell["longitude"]) if "longitude" in cell.coords else longitude

    # COSMO-REA6's own per-cell DNI (present when compute_dni_field=True at
    # pipeline time) is explicitly experimental/unreliable near the horizon
    # (see providers.cosmo_rea6.transform.compute_dni's docstring). Always
    # reconstruct DNI/DHI from GHI instead — the same DISC variant buem's
    # own pipeline historically trusted for this data source.
    dni_dhi = reconstruct_dni_dhi(
        ghi, cell_lat, cell_lon,
        method="disc",
        zenith_kind="apparent",
        clip_to_extraterrestrial=True,
        clip_dhi_to_ghi=True,
    )
    dni = _strip_tz(dni_dhi["DNI"])
    dhi = _strip_tz(dni_dhi["DHI"])
    return _finalize(pd.DataFrame({"T": t, "GHI": ghi, "DNI": dni, "DHI": dhi}))


_DISPATCH = {
    "era5-land": _get_point_era5_land,
    "merra-2": _get_point_merra2,
    "cosmo-rea6": _get_point_cosmo_rea6,
}


def get_point_weather(
    latitude: float,
    longitude: float,
    year: int,
    *,
    provider: str = "era5-land",
    data_dir: Path | str | None = None,
) -> pd.DataFrame:
    """Return an hourly T/GHI/DHI/DNI DataFrame for one location/year.

    Extracts the nearest already-processed grid cell to *(latitude,
    longitude)* for *year*. Does **not** download or process data — call
    the relevant provider's pipeline first if nothing has been processed
    yet for that year.

    Parameters
    ----------
    latitude, longitude : float
        Target location in degrees (WGS84).
    year : int
        Calendar year to fetch.
    provider : str
        One of ``"era5-land"`` (default), ``"cosmo-rea6"``, ``"merra-2"``
        (aliases ``era5``, ``cosmo``, ``merra2`` also accepted).
    data_dir : Path or str, optional
        Directory containing the provider's already-exported ``.nc``
        files. Defaults to that provider's own ``<work_dir>/output``
        convention (``weather.common.env.data_root()/<provider>/output``).

    Returns
    -------
    pandas.DataFrame
        Tz-naive hourly ``DatetimeIndex``, columns ``T`` (degC), ``GHI``,
        ``DHI``, ``DNI`` (all W/m^2).

    Raises
    ------
    ValueError
        If *provider* is not recognized.
    FileNotFoundError
        If no processed archive exists for *(provider, year)* under
        *data_dir*.
    ImportError
        If the ``pointquery`` (xarray/netcdf4) or ``solar`` (pvlib)
        extras are not installed.
    """
    normalized = str(provider).strip().lower().replace("_", "-")
    canonical = _ALIASES.get(normalized)
    if canonical is None:
        available = ", ".join(sorted(set(_ALIASES.values())))
        raise ValueError(f"Unknown provider: {provider!r}. Available: {available}")

    return _DISPATCH[canonical](latitude, longitude, year, data_dir)
