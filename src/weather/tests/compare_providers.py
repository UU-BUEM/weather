#!/usr/bin/env python3
"""Cross-provider comparison: COSMO-REA6 vs ERA5-Land vs MERRA-2.

For a single grid cell (chosen by lat/lon, snapped to each provider's own
native grid) and a chosen month, pulls hourly DNI, DHI, GHI, T, RH, SF, and
ALBEDO from all three providers' 2018 monthly NetCDFs, cross-checks them at
month/week/hour granularity, dumps basic whole-Europe grid stats, and writes
matplotlib figures + a multi-sheet .xlsx report + per-provider .csv/.parquet
files (one sheet/file per provider).

Known, real gaps in the 2018 test dataset this was built against (present
regardless of which cell/month you pick — not a bug in this script):

* **COSMO-REA6 RH and MERRA-2 SF/SNOW_DEPTH require a re-run to appear.**
  ``RELHUM_2M`` (COSMO -> ``RH``) and the ``lnd`` collection
  (``PRECSNOLAND``/``SNODP`` -> MERRA-2's ``SF``/``SNOW_DEPTH``) are both
  correctly wired end-to-end in code, but only take effect once each
  provider's 2018 data is regenerated (see ``.claude/open.md`` /
  ``.claude/merra2/merra2_plan.md`` for the live-rerun status). Columns
  read NaN against any 2018 NetCDF generated before that rerun.
* **COSMO-REA6 ALBEDO is deliberately left NaN, by design, not a gap.**
  A downstream PV consumer (``pysam-photovoltaic-energy-simulation``,
  ``scripts/main.py``) turned out NOT to use a real optical albedo field
  at all -- it derives a crude threshold albedo from *snow depth* alone
  (``0.6 if snow_depth_cm > 1 else 0.2``, fed from MERRA-2's ``SNODP``).
  That need is what :data:`ATTRS`'s ``SNOW_DEPTH`` column below covers,
  and COSMO already has an equivalent raw field (``H_SNOW``, physical
  depth in m, passthrough, downloaded since the original run) -- no new
  attribute or download was needed. A *real*, physically-derived COSMO
  albedo remains possible if some other future consumer needs true
  optical albedo rather than a snow-depth proxy: DWD's full parameter
  table (``ParameterTables_REA6.pdf`` at
  ``opendata.dwd.de/climate_environment/REA/COSMO_REA6/``) lists
  ``SOBS_RAD`` (net shortwave at surface, instantaneous -- matches
  ``SWDIRS_RAD``/``SWDIFDS_RAD``'s convention; NOT ``ASOB_S``, its
  "average"-type sibling), giving ``albedo = ((SWDIRS_RAD +
  SWDIFDS_RAD) - SOBS_RAD) / (SWDIRS_RAD + SWDIFDS_RAD)``. Deliberately
  NOT built -- no confirmed consumer needs it today.
* **SNOW_DEPTH is NOT the same physical quantity across providers.**
  COSMO's ``H_SNOW`` and MERRA-2's ``SNODP`` are both physical snow
  depth in meters (directly comparable). ERA5-Land's ``sd`` is snow
  depth in **meters of water equivalent** -- ``downloaded_attributes.py``
  documents a water-equivalent -> physical-depth conversion (divide by
  snow density / 1000, or assume a fallback density), but that
  conversion is not actually implemented anywhere in
  ``era5_land/transform.py``; ``sd`` passes through raw. Do not compare
  ERA5-Land's SNOW_DEPTH numerically against the other two without
  applying that conversion yourself first.
* **COSMO-REA6's exported NetCDFs carry no lat/lon** (raw GRIBs -- which
  *do* carry real cfgrib-decoded WGS84 lat/lon -- were already deleted by
  the pipeline's cleanup step, and the DWD ``COSMO_REA6_CONST`` static
  file was never downloaded for this run). This script reconstructs
  COSMO's lat/lon analytically from the **published** COSMO-REA6
  rotated-pole grid definition (pole 39.25N/-162.0E, 0.055 deg, 824x848 --
  see :data:`_COSMO_POLE_LAT` et al.). That reconstruction is *not*
  verified against DWD's own CONST file or a raw GRIB locally, so treat
  COSMO's matched cell as best-effort (within a few grid cells / tens of
  km), not pixel-exact. If a CONST file becomes available, replace
  :func:`_cosmo_lat_lon_grid` with a read of its real lat/lon field.
* ERA5-Land and MERRA-2 only store GHI in bulk; DNI/DHI are computed here
  per-point via pvlib DIRINT (:mod:`weather.providers.era5_land.dni_pointwise`
  / :mod:`weather.providers.merra2.dni_pointwise`), exactly as those
  modules are designed to be used -- neither ever stores a direct/diffuse
  split, so a GHI-only decomposition model is the only option available.
  COSMO's DNI/DHI are already gridded and computed *exactly*
  (``SWDIRS_RAD`` and ``SWDIFDS_RAD`` are separately-modelled direct/
  diffuse fields, not decomposed from GHI -- see ``docs/dni_methodology.md``
  sec 4). ``CosmoAdapter.dni_method_comparison()`` cross-checks that exact
  value against two pvlib-based estimates at the matched cell: the same
  exact closure formula with pvlib's solar position instead of Spencer's
  (isolates solar-position precision -- see ``docs/dni_methodology.md``
  sec 11), and, purely as a reference for what ERA5-Land/MERRA-2 are stuck
  with, a DIRINT decomposition that (wrongly, for COSMO) ignores the
  already-known DHI.

Usage::

    python compare_providers.py                        # Arctic-edge default cell, June
    python compare_providers.py --lat 52.1 --lon 5.2 --month 3
    python compare_providers.py --lat 71.0 --lon 25.0 --year 2018 --month 12 \\
        --out-dir D:/scratch/comparison --domain-stats-full-year
"""

from __future__ import annotations

import argparse
import calendar
import logging
import re
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib
import numpy as np
import pandas as pd
import pvlib
import xarray as xr
from pyproj import CRS, Transformer

from weather.providers.cosmo_rea6.config import get_config as _cosmo_config
from weather.providers.era5_land.config import get_config as _era5_config
from weather.providers.era5_land.dni_pointwise import (
    extract_dni_dhi_dirint as _era5_extract_dni_dhi,
)
from weather.providers.merra2.config import get_config as _merra2_config
from weather.providers.merra2.dni_pointwise import (
    extract_dni_dhi_dirint as _merra2_extract_dni_dhi,
)

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402 -- must follow matplotlib.use()
import matplotlib.pyplot as plt  # noqa: E402

logger = logging.getLogger(__name__)

#: The attributes this tool compares, in report/plot order.
ATTRS: tuple[str, ...] = (
    "GHI", "DHI", "DNI", "T", "RH", "SF", "ALBEDO", "SNOW_DEPTH",
)

#: Units for axis labels / report headers (native units as stored).
_UNITS: dict[str, str] = {
    "GHI": "W/m^2", "DHI": "W/m^2", "DNI": "W/m^2",
    "T": "degC", "RH": "%", "SF": "kg/m^2/h", "ALBEDO": "0-1",
    "SNOW_DEPTH": "m (see caveat: not the same physical quantity "
    "across providers)",
}

#: dataviz skill categorical slots 1-3 (blue/orange/aqua) -- pre-validated
#: for all-pairs CVD/contrast in `references/palette.md`; fixed order, one
#: color per provider throughout (never re-cycled).
_COLORS: dict[str, str] = {
    "COSMO-REA6": "#2a78d6",
    "ERA5-Land": "#eb6834",
    "MERRA-2": "#1baf7a",
}
_INK = "#0b0b0b"
_INK_SECONDARY = "#52514e"
_INK_MUTED = "#898781"
_GRID_COLOR = "#e1e0d9"

# ---------------------------------------------------------------------------
# COSMO-REA6 rotated-pole grid geometry (see module docstring caveat above)
# ---------------------------------------------------------------------------
_COSMO_POLE_LON = -162.0
_COSMO_POLE_LAT = 39.25
_COSMO_NY, _COSMO_NX = 824, 848
_COSMO_RES = 0.055
_COSMO_RLAT0 = -23.4
_COSMO_RLON0 = -28.4

_EARTH_RADIUS_KM = 6371.0


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two WGS84 points, in km."""
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dphi = np.radians(lat2 - lat1)
    dlmb = np.radians(lon2 - lon1)
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dlmb / 2) ** 2
    return float(2 * _EARTH_RADIUS_KM * np.arcsin(np.sqrt(a)))


def _cosmo_lat_lon_grid() -> tuple[np.ndarray, np.ndarray]:
    """Reconstruct COSMO-REA6's 2-D WGS84 (lat, lon) grid, shape (824, 848).

    Analytic rotated-pole -> WGS84 transform using the published grid
    definition (see module docstring). No local CONST file or raw GRIB
    is required, but the exact grid origin has not been verified against
    either -- see the caveat at the top of this file.
    """
    rlat = _COSMO_RLAT0 + np.arange(_COSMO_NY) * _COSMO_RES
    rlon = _COSMO_RLON0 + np.arange(_COSMO_NX) * _COSMO_RES
    rlon_2d, rlat_2d = np.meshgrid(rlon, rlat)  # -> (824, 848), matches (y, x)

    rotated = CRS.from_cf({
        "grid_mapping_name": "rotated_latitude_longitude",
        "grid_north_pole_latitude": _COSMO_POLE_LAT,
        "grid_north_pole_longitude": _COSMO_POLE_LON,
    })
    to_wgs84 = Transformer.from_crs(rotated, "EPSG:4326", always_xy=True)
    lon_2d, lat_2d = to_wgs84.transform(rlon_2d, rlat_2d)
    return np.asarray(lat_2d), np.asarray(lon_2d)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MonthFile:
    year: int
    month: int
    path: Path


@dataclass(frozen=True)
class CellLocation:
    provider: str
    iy: int
    ix: int
    lat: float
    lon: float
    requested_lat: float
    requested_lon: float
    distance_km: float


def _domain_stats_from_dataset(
    ds: xr.Dataset, provider: str, year: int, month: int,
) -> pd.DataFrame:
    """Grid-mean/min/max/NaN-fraction per 3-D+ variable, one month."""
    rows: list[dict[str, Any]] = []
    for name in ds.data_vars:
        da = ds[name]
        if da.ndim < 2:
            continue
        rows.append({
            "provider": provider, "year": year, "month": month,
            "variable": str(name),
            "mean": float(da.mean(skipna=True).values),
            "min": float(da.min(skipna=True).values),
            "max": float(da.max(skipna=True).values),
            "nan_frac": float(da.isnull().mean().values),
        })
    return pd.DataFrame(rows)


def _nearest_1d_cell(
    latv: np.ndarray, lonv: np.ndarray, lat: float, lon: float,
) -> tuple[int, int, float, float]:
    """Nearest (iy, ix) on a regular 1-D lat/lon grid, plus the cell's coords."""
    lon_t = lon % 360.0 if lonv.max() > 180.0 else lon
    iy = int(np.abs(latv - lat).argmin())
    ix = int(np.abs(lonv - lon_t).argmin())
    return iy, ix, float(latv[iy]), float(lonv[ix])


#: Cells with solar elevation below this are zeroed -- matches
#: transform.compute_dni's own 5 deg threshold (docs/dni_methodology.md
#: sec 6), so the pvlib-closure DNI is masked the same way as COSMO's
#: native DNI and the two are directly comparable near the horizon.
_DNI_ELEVATION_THRESHOLD_DEG = 5.0


def _pvlib_closure_dni(
    ghi: pd.Series, dhi: pd.Series, latitude: float, longitude: float,
) -> pd.Series:
    """DNI via the exact closure formula ``DNI = (GHI - DHI) / cos(zenith)``
    (pvlib.irradiance.complete_irradiance), using pvlib's NREL SPA solar
    position -- NOT a decomposition model.

    Per docs/dni_methodology.md sec 4.2, a decomposition model (DISC,
    DIRINT, Erbs) is the wrong tool whenever DHI is already known, as it
    is here (both GHI and DHI are already stored for COSMO): it throws
    away real information and adds needless estimation error on top of
    solar-position error. This function isolates just the solar-position
    algorithm's contribution (pvlib NREL SPA vs COSMO's own Spencer 1971)
    by using the exact same closure equation COSMO's ``compute_dni``
    already applies, just with a different (higher-precision, but per
    the docs practically negligible here) zenith source.
    """
    times = pd.DatetimeIndex(ghi.index)
    solpos = pvlib.solarposition.get_solarposition(times, latitude, longitude)
    zenith = solpos["apparent_zenith"]
    closure = pvlib.irradiance.complete_irradiance(zenith, ghi=ghi, dhi=dhi)
    dni = closure["dni"].clip(lower=0.0)
    elevation = 90.0 - zenith
    return dni.where(elevation >= _DNI_ELEVATION_THRESHOLD_DEG, 0.0)


# ---------------------------------------------------------------------------
# Provider adapters
# ---------------------------------------------------------------------------


class ProviderAdapter(ABC):
    """Uniform interface for locating a cell and pulling its time series."""

    name: str
    _pattern: re.Pattern
    _glob: str

    def __init__(self, output_dir: Path | None = None) -> None:
        self.output_dir = output_dir or self._default_output_dir()

    @abstractmethod
    def _default_output_dir(self) -> Path: ...

    def list_months(self) -> list[MonthFile]:
        files = []
        for p in self.output_dir.glob(self._glob):
            m = self._pattern.search(p.name)
            if m:
                files.append(MonthFile(int(m.group(1)), int(m.group(2)), p))
        files.sort(key=lambda f: (f.year, f.month))
        return files

    @abstractmethod
    def find_cell(
        self, lat: float, lon: float, reference_file: MonthFile,
    ) -> CellLocation:
        """Nearest grid cell to (lat, lon). ``reference_file`` is the exact
        monthly file to read the grid from -- pass the target month's file,
        not an arbitrary one (some output dirs carry unrelated leftover
        files, e.g. an old test run for a different year, that may lack
        lat/lon or use a different grid)."""

    @abstractmethod
    def load_point_series(
        self, month_file: MonthFile, cell: CellLocation,
    ) -> pd.DataFrame:
        """Hourly DataFrame, tz-aware UTC index, columns = :data:`ATTRS`."""

    def domain_stats(self, month_file: MonthFile) -> pd.DataFrame:
        with xr.open_dataset(month_file.path, chunks="auto") as ds:
            return _domain_stats_from_dataset(
                ds, self.name, month_file.year, month_file.month,
            )


class CosmoAdapter(ProviderAdapter):
    name = "COSMO-REA6"
    _pattern = re.compile(r"COSMO_REA6_(\d{4})_(\d{2})_all_attrs\.nc$")
    _glob = "COSMO_REA6_*_all_attrs.nc"

    def _default_output_dir(self) -> Path:
        return Path(_cosmo_config()["output_dir"])

    def find_cell(
        self, lat: float, lon: float, reference_file: MonthFile,
    ) -> CellLocation:
        lat2d, lon2d = _cosmo_lat_lon_grid()
        dist2 = (lat2d - lat) ** 2 + (lon2d - lon) ** 2
        iy, ix = (int(v) for v in np.unravel_index(np.argmin(dist2), dist2.shape))
        cell_lat, cell_lon = float(lat2d[iy, ix]), float(lon2d[iy, ix])
        d = _haversine_km(lat, lon, cell_lat, cell_lon)
        return CellLocation(self.name, iy, ix, cell_lat, cell_lon, lat, lon, d)

    def load_point_series(
        self, month_file: MonthFile, cell: CellLocation,
    ) -> pd.DataFrame:
        with xr.open_dataset(month_file.path) as ds:
            pt = ds.isel(y=cell.iy, x=cell.ix)
            idx = pd.DatetimeIndex(pt["time"].values).tz_localize("UTC")
            out = pd.DataFrame(index=idx)
            out["T"] = pt["T"].values
            out["GHI"] = pt["GHI"].values
            out["DHI"] = pt["DHI"].values
            out["DNI"] = pt["DNI"].values if "DNI" in pt else np.nan
            out["RH"] = pt["RH"].values if "RH" in pt else np.nan
            if "SNOW_GSP" in pt and "SNOW_CON" in pt:
                out["SF"] = pt["SNOW_GSP"].values + pt["SNOW_CON"].values
            else:
                out["SF"] = np.nan
            # No native ALBEDO field -- deliberate, see module docstring.
            out["ALBEDO"] = np.nan
            out["SNOW_DEPTH"] = pt["H_SNOW"].values if "H_SNOW" in pt else np.nan
        return out[list(ATTRS)]

    def dni_method_comparison(
        self, month_file: MonthFile, cell: CellLocation,
    ) -> pd.DataFrame:
        """COSMO's native DNI/DHI against two independent pvlib estimates.

        * ``DNI_pvlib_closure`` -- the *exact* closure formula (COSMO's
          own known GHI/DHI, pvlib's NREL SPA solar position instead of
          COSMO's Spencer 1971). Isolates the solar-position algorithm's
          own contribution; per docs/dni_methodology.md sec 2.1 this
          should be tiny; both algorithms are used correctly here since
          neither throws away the known direct/diffuse split (sec 4.2).
        * ``DNI_pvlib_dirint`` / ``DHI_pvlib_dirint`` -- a DIRINT
          decomposition of GHI *alone*, blind to the already-known DHI.
          Not the right tool for COSMO (see sec 4.2 -- included only as
          a reference for the error ERA5-Land/MERRA-2 are stuck with,
          since they never store a direct/diffuse split at all).
        """
        with xr.open_dataset(month_file.path) as ds:
            pt = ds.isel(y=cell.iy, x=cell.ix)
            idx = pd.DatetimeIndex(pt["time"].values).tz_localize("UTC")
            ghi = pd.Series(np.asarray(pt["GHI"].values), index=idx)
            dhi_native = pd.Series(np.asarray(pt["DHI"].values), index=idx)
            pressure = (
                pd.Series(np.asarray(pt["PS"].values), index=idx)
                if "PS" in pt else None
            )
            closure_dni = _pvlib_closure_dni(ghi, dhi_native, cell.lat, cell.lon)
            dirint = _era5_extract_dni_dhi(ghi, cell.lat, cell.lon, pressure=pressure)

            out = pd.DataFrame(index=idx)
            out["GHI"] = ghi.to_numpy()
            out["DNI_native"] = pt["DNI"].values if "DNI" in pt else np.nan
            out["DNI_pvlib_closure"] = closure_dni.to_numpy()
            out["DNI_pvlib_dirint"] = dirint["DNI"].to_numpy()
            out["DHI_native"] = dhi_native.to_numpy()
            out["DHI_pvlib_dirint"] = dirint["DHI"].to_numpy()
        return out


class Era5Adapter(ProviderAdapter):
    name = "ERA5-Land"
    _pattern = re.compile(r"ERA5_LAND_(\d{4})_(\d{2})_all_attrs\.nc$")
    _glob = "ERA5_LAND_*_all_attrs.nc"

    def _default_output_dir(self) -> Path:
        return Path(_era5_config()["output_dir"])

    def find_cell(
        self, lat: float, lon: float, reference_file: MonthFile,
    ) -> CellLocation:
        with xr.open_dataset(reference_file.path) as ds:
            latv = np.asarray(ds["latitude"].values)
            lonv = np.asarray(ds["longitude"].values)
        iy, ix, cell_lat, cell_lon = _nearest_1d_cell(latv, lonv, lat, lon)
        d = _haversine_km(lat, lon, cell_lat, cell_lon)
        return CellLocation(self.name, iy, ix, cell_lat, cell_lon, lat, lon, d)

    def load_point_series(
        self, month_file: MonthFile, cell: CellLocation,
    ) -> pd.DataFrame:
        with xr.open_dataset(month_file.path) as ds:
            pt = ds.isel(y=cell.iy, x=cell.ix)
            idx = pd.DatetimeIndex(pt["time"].values).tz_localize("UTC")
            ghi = pd.Series(np.asarray(pt["GHI"].values), index=idx)
            pressure = (
                pd.Series(np.asarray(pt["sp"].values), index=idx)
                if "sp" in pt else None
            )
            dd = _era5_extract_dni_dhi(ghi, cell.lat, cell.lon, pressure=pressure)
            out = pd.DataFrame(index=idx)
            out["T"] = pt["T"].values
            out["RH"] = pt["RH"].values if "RH" in pt else np.nan
            out["GHI"] = ghi.to_numpy()
            out["DHI"] = dd["DHI"].to_numpy()
            out["DNI"] = dd["DNI"].to_numpy()
            out["SF"] = pt["sf"].values if "sf" in pt else np.nan
            # "fal" = total surface albedo (bare land + snow), comparable
            # to MERRA-2's ALBEDO. "asn" (snow-only albedo) is a
            # different quantity and NOT used here.
            out["ALBEDO"] = pt["fal"].values if "fal" in pt else np.nan
            # "sd" = snow depth in m of WATER EQUIVALENT, not physical
            # depth -- not directly comparable to COSMO/MERRA-2's
            # physical-depth SNOW_DEPTH; see module docstring caveat.
            out["SNOW_DEPTH"] = pt["sd"].values if "sd" in pt else np.nan
        return out[list(ATTRS)]


class Merra2Adapter(ProviderAdapter):
    name = "MERRA-2"
    _pattern = re.compile(r"MERRA2_(\d{4})_(\d{2})_all_attrs\.nc$")
    _glob = "MERRA2_*_all_attrs.nc"

    def _default_output_dir(self) -> Path:
        return Path(_merra2_config()["output_dir"])

    def find_cell(
        self, lat: float, lon: float, reference_file: MonthFile,
    ) -> CellLocation:
        with xr.open_dataset(reference_file.path) as ds:
            latv = np.asarray(ds["latitude"].values)
            lonv = np.asarray(ds["longitude"].values)
        iy, ix, cell_lat, cell_lon = _nearest_1d_cell(latv, lonv, lat, lon)
        d = _haversine_km(lat, lon, cell_lat, cell_lon)
        return CellLocation(self.name, iy, ix, cell_lat, cell_lon, lat, lon, d)

    def load_point_series(
        self, month_file: MonthFile, cell: CellLocation,
    ) -> pd.DataFrame:
        with xr.open_dataset(month_file.path) as ds:
            pt = ds.isel(y=cell.iy, x=cell.ix)
            idx = pd.DatetimeIndex(pt["time"].values).tz_localize("UTC")
            ghi = pd.Series(np.asarray(pt["GHI"].values), index=idx)
            pressure = (
                pd.Series(np.asarray(pt["PS"].values), index=idx)
                if "PS" in pt else None
            )
            dd = _merra2_extract_dni_dhi(ghi, cell.lat, cell.lon, pressure=pressure)
            out = pd.DataFrame(index=idx)
            out["T"] = pt["T2M"].values if "T2M" in pt else pt["T"].values
            out["RH"] = pt["RH"].values if "RH" in pt else np.nan
            out["GHI"] = ghi.to_numpy()
            out["DHI"] = dd["DHI"].to_numpy()
            out["DNI"] = dd["DNI"].to_numpy()
            # PRECSNOLAND (kg/m^2/h after transform.py's unit conversion)
            # matches COSMO's SNOW_GSP+SNOW_CON / ERA5-Land's sf convention.
            # NaN on data generated before the lnd collection was added.
            out["SF"] = (
                pt["PRECSNOLAND"].values if "PRECSNOLAND" in pt else np.nan
            )
            out["ALBEDO"] = pt["ALBEDO"].values if "ALBEDO" in pt else np.nan
            out["SNOW_DEPTH"] = pt["SNODP"].values if "SNODP" in pt else np.nan
        return out[list(ATTRS)]


PROVIDERS: tuple[type[ProviderAdapter], ...] = (CosmoAdapter, Era5Adapter, Merra2Adapter)


# ---------------------------------------------------------------------------
# Robustness checks: month / week / hour granularity
# ---------------------------------------------------------------------------


class RobustnessChecker:
    """Cross-provider agreement at month, week, and hour-of-day granularity."""

    def __init__(
        self,
        month_frames: dict[str, pd.DataFrame],
        year_frames: dict[str, dict[int, pd.DataFrame]],
    ) -> None:
        self.month_frames = month_frames
        self.year_frames = year_frames

    def monthly_summary(self) -> pd.DataFrame:
        """Mean per attribute per provider per month, across the full year."""
        rows = []
        for provider, months in self.year_frames.items():
            for month, frame in months.items():
                for attr in ATTRS:
                    rows.append({
                        "attribute": attr, "month": month, "provider": provider,
                        "mean": frame[attr].mean(skipna=True),
                    })
        long_df = pd.DataFrame(rows)
        return long_df.pivot_table(
            index=["attribute", "month"], columns="provider", values="mean",
        )

    def weekly_summary(self) -> pd.DataFrame:
        """Within the chosen month: ISO-week mean per attribute per provider."""
        rows = []
        for provider, frame in self.month_frames.items():
            f = frame.copy()
            f["week"] = f.index.isocalendar().week.to_numpy()
            wk = f.groupby("week")[list(ATTRS)].mean(numeric_only=True)
            wk.insert(0, "provider", provider)
            rows.append(wk.reset_index())
        return pd.concat(rows, ignore_index=True)

    def diurnal_summary(self) -> pd.DataFrame:
        """Within the chosen month: mean-by-hour-of-day per attribute per provider."""
        rows = []
        for provider, frame in self.month_frames.items():
            f = frame.copy()
            f["hour"] = f.index.hour
            hr = f.groupby("hour")[list(ATTRS)].mean(numeric_only=True)
            hr.insert(0, "provider", provider)
            rows.append(hr.reset_index())
        return pd.concat(rows, ignore_index=True)


# ---------------------------------------------------------------------------
# Excel export
# ---------------------------------------------------------------------------


def _strip_tz(frame: pd.DataFrame, index_name: str) -> pd.DataFrame:
    """Excel/openpyxl has no timezone-aware datetime cell type -- values
    are already UTC, so drop the tz label rather than convert."""
    out = frame.copy()
    out.index = out.index.tz_localize(None)
    out.index.name = index_name
    return out


def write_excel_report(
    path: Path,
    month_frames: dict[str, pd.DataFrame],
    cells: dict[str, CellLocation],
    monthly_summary: pd.DataFrame,
    weekly_summary: pd.DataFrame,
    diurnal_summary: pd.DataFrame,
    domain_stats: pd.DataFrame,
    cosmo_dni_compare: pd.DataFrame | None = None,
    cosmo_dni_stats: pd.DataFrame | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        for provider, frame in month_frames.items():
            sheet = re.sub(r"[^A-Za-z0-9]", "", provider)[:31]
            _strip_tz(frame, "time_utc").to_excel(xw, sheet_name=sheet)

        meta_rows = [
            {
                "provider": c.provider,
                "requested_lat": c.requested_lat, "requested_lon": c.requested_lon,
                "matched_lat": c.lat, "matched_lon": c.lon,
                "distance_from_requested_km": round(c.distance_km, 2),
                "iy": c.iy, "ix": c.ix,
            }
            for c in cells.values()
        ]
        pd.DataFrame(meta_rows).to_excel(xw, sheet_name="Cell_Metadata", index=False)
        monthly_summary.to_excel(xw, sheet_name="Monthly_Summary")
        weekly_summary.to_excel(xw, sheet_name="Weekly_Summary", index=False)
        diurnal_summary.to_excel(xw, sheet_name="Diurnal_Summary", index=False)
        if not domain_stats.empty:
            domain_stats.to_excel(xw, sheet_name="Domain_Stats", index=False)
        if cosmo_dni_compare is not None:
            _strip_tz(cosmo_dni_compare, "time_utc").to_excel(
                xw, sheet_name="COSMO_DNI_Method_Compare",
            )
        if cosmo_dni_stats is not None:
            cosmo_dni_stats.to_excel(
                xw, sheet_name="COSMO_DNI_Method_Stats", index=False,
            )
    logger.info("Wrote Excel report: %s", path)


def write_flat_reports(
    out_dir: Path, month_frames: dict[str, pd.DataFrame], year: int, month: int,
) -> list[Path]:
    """One .csv and one .parquet per provider, alongside the .xlsx."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for provider, frame in month_frames.items():
        slug = re.sub(r"[^A-Za-z0-9]", "", provider)
        stem = f"{slug}_{year}_{month:02d}"
        out = frame.copy()
        out.index.name = "time_utc"

        csv_path = out_dir / f"{stem}.csv"
        out.to_csv(csv_path)
        written.append(csv_path)

        parquet_path = out_dir / f"{stem}.parquet"
        out.to_parquet(parquet_path)
        written.append(parquet_path)
    return written


# ---------------------------------------------------------------------------
# Plotting
# ---------------------------------------------------------------------------


def _style_axis(ax: plt.Axes) -> None:
    ax.grid(True, color=_GRID_COLOR, linewidth=1, linestyle="-")
    ax.set_axisbelow(True)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    for spine in ("left", "bottom"):
        ax.spines[spine].set_color(_INK_MUTED)
    ax.tick_params(colors=_INK_SECONDARY, labelsize=8)


class ComparisonPlotter:
    """Matplotlib figures for the point-wise cross-provider comparison."""

    def __init__(self, month_frames: dict[str, pd.DataFrame], cell_lat: float,
                 cell_lon: float, year: int, month: int) -> None:
        self.month_frames = month_frames
        self.cell_lat = cell_lat
        self.cell_lon = cell_lon
        self.year = year
        self.month = month

    def _plot_attr(
        self,
        ax: plt.Axes,
        attr: str,
        per_provider: dict[str, pd.DataFrame],
        x_label: str,
        *,
        datetime_x: bool,
    ) -> None:
        ax.set_facecolor("#fcfcfb")
        any_data = False
        missing = []
        for provider, frame in per_provider.items():
            series = frame[attr]
            if series.isna().all():
                missing.append(provider)
                continue
            any_data = True
            ax.plot(
                frame.index, series.to_numpy(),
                color=_COLORS[provider], linewidth=2,
                solid_capstyle="round", solid_joinstyle="round",
                label=provider,
            )
        unit = _UNITS[attr]
        subtitle = f"{attr} ({unit})"
        if missing:
            subtitle += f" -- N/A: {', '.join(missing)}"
        ax.set_title(subtitle, fontsize=10, color=_INK, loc="left")
        ax.set_xlabel(x_label, fontsize=8, color=_INK_SECONDARY)
        _style_axis(ax)
        if datetime_x:
            locator = mdates.AutoDateLocator(minticks=5, maxticks=8)
            ax.xaxis.set_major_locator(locator)
            ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
        if any_data:
            ax.legend(fontsize=8, frameon=False, labelcolor=_INK_SECONDARY)

    def _grid_figure(
        self, per_provider: dict[str, pd.DataFrame], x_label: str, title: str,
        *, datetime_x: bool = False,
    ) -> plt.Figure:
        ncols = 2
        n = len(ATTRS)
        full_rows = n // ncols
        has_leftover = n % ncols == 1
        nrows = full_rows + (1 if has_leftover else 0)

        fig = plt.figure(figsize=(13, 3.6 * nrows), facecolor="#fcfcfb")
        fig.suptitle(title, fontsize=13, color=_INK, y=0.995)
        gs = fig.add_gridspec(nrows, ncols)

        paired_attrs = ATTRS[: full_rows * ncols]
        for i, attr in enumerate(paired_attrs):
            ax = fig.add_subplot(gs[i // ncols, i % ncols])
            self._plot_attr(ax, attr, per_provider, x_label, datetime_x=datetime_x)

        if has_leftover:
            # A single leftover attribute (whenever len(ATTRS) is odd) gets
            # its own full-width row instead of sitting next to an empty
            # cell -- more visible, and there's no dead space to hide.
            last_attr = ATTRS[-1]
            ax = fig.add_subplot(gs[nrows - 1, :])
            self._plot_attr(ax, last_attr, per_provider, x_label, datetime_x=datetime_x)

        fig.tight_layout(rect=(0, 0, 1, 0.97))
        return fig

    def hourly_figure(self) -> plt.Figure:
        title = (
            f"Hourly comparison -- {calendar.month_name[self.month]} {self.year} "
            f"@ ({self.cell_lat:.2f}, {self.cell_lon:.2f})"
        )
        return self._grid_figure(
            self.month_frames, "time (UTC)", title, datetime_x=True,
        )

    def diurnal_figure(self, diurnal_summary: pd.DataFrame) -> plt.Figure:
        per_provider = {
            provider: diurnal_summary[diurnal_summary["provider"] == provider]
            .set_index("hour")[list(ATTRS)]
            for provider in diurnal_summary["provider"].unique()
        }
        title = (
            f"Diurnal cycle (mean by hour-of-day) -- "
            f"{calendar.month_name[self.month]} {self.year} "
            f"@ ({self.cell_lat:.2f}, {self.cell_lon:.2f})"
        )
        return self._grid_figure(per_provider, "hour of day (UTC)", title)


#: (output column suffix, human label) for each alternative DNI/DHI
#: estimate compared against COSMO's native value in the stats table.
_DNI_METHOD_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("DNI", "pvlib_closure", "pvlib closure (exact, NREL SPA zenith)"),
    ("DNI", "pvlib_dirint", "pvlib DIRINT (GHI-only decomposition)"),
    ("DHI", "pvlib_dirint", "pvlib DIRINT (GHI-only decomposition)"),
)


def cosmo_dni_method_stats(compare_df: pd.DataFrame) -> pd.DataFrame:
    """Bias/MAE/RMSE/correlation of each alternative estimate vs COSMO's
    native DNI/DHI -- see :data:`_DNI_METHOD_COLUMNS`."""
    rows = []
    for attr, suffix, label in _DNI_METHOD_COLUMNS:
        native = compare_df[f"{attr}_native"]
        est = compare_df[f"{attr}_{suffix}"]
        diff = est - native
        rows.append({
            "attribute": attr,
            "method": label,
            "bias_est_minus_native": diff.mean(),
            "mae": diff.abs().mean(),
            "rmse": float(np.sqrt((diff**2).mean())),
            "correlation": native.corr(est),
        })
    return pd.DataFrame(rows)


def cosmo_dni_method_figure(
    compare_df: pd.DataFrame, cell_lat: float, cell_lon: float,
    year: int, month: int,
) -> plt.Figure:
    """COSMO's native DNI/DHI vs the pvlib closure formula (exact, just a
    different solar-position algorithm) and pvlib DIRINT (GHI-only
    decomposition, blind to the known DHI) -- three independent
    derivations of DNI, two of DHI, at the same cell."""
    fig, axes = plt.subplots(2, 1, figsize=(13, 8), facecolor="#fcfcfb")
    fig.suptitle(
        f"COSMO-REA6: native vs pvlib-derived DNI/DHI -- "
        f"{calendar.month_name[month]} {year} @ ({cell_lat:.2f}, {cell_lon:.2f})",
        fontsize=13, color=_INK, y=0.99,
    )
    series_specs = {
        "DNI": (
            ("DNI_native", _COLORS["COSMO-REA6"], "solid", "native (exact)"),
            (
                "DNI_pvlib_closure", _COLORS["MERRA-2"], "dashed",
                "pvlib closure (exact, NREL SPA zenith)",
            ),
            (
                "DNI_pvlib_dirint", _COLORS["ERA5-Land"], "solid",
                "pvlib DIRINT (GHI-only decomposition)",
            ),
        ),
        "DHI": (
            ("DHI_native", _COLORS["COSMO-REA6"], "solid", "native (exact)"),
            (
                "DHI_pvlib_dirint", _COLORS["ERA5-Land"], "solid",
                "pvlib DIRINT (GHI-only decomposition)",
            ),
        ),
    }
    for ax, attr in zip(axes, ("DNI", "DHI"), strict=True):
        ax.set_facecolor("#fcfcfb")
        for col, color, style, label in series_specs[attr]:
            ax.plot(
                compare_df.index, compare_df[col], color=color,
                linewidth=2, linestyle=style,
                solid_capstyle="round", solid_joinstyle="round",
                label=label,
            )
        ax.set_title(f"{attr} ({_UNITS[attr]})", fontsize=10, color=_INK, loc="left")
        ax.set_xlabel("time (UTC)", fontsize=8, color=_INK_SECONDARY)
        _style_axis(ax)
        locator = mdates.AutoDateLocator(minticks=5, maxticks=8)
        ax.xaxis.set_major_locator(locator)
        ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
        ax.legend(fontsize=8, frameon=False, labelcolor=_INK_SECONDARY)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    return fig


# ---------------------------------------------------------------------------
# Orchestration / CLI
# ---------------------------------------------------------------------------


def _print_cell_report(cells: dict[str, CellLocation]) -> None:
    print("=" * 78)
    print("CELL MATCH (requested -> nearest cell on each provider's own grid)")
    print("=" * 78)
    for c in cells.values():
        print(
            f"  {c.provider:<12s} iy={c.iy:>4d} ix={c.ix:>4d}  "
            f"lat={c.lat:>7.3f} lon={c.lon:>7.3f}  "
            f"({c.distance_km:.1f} km from requested "
            f"{c.requested_lat:.3f},{c.requested_lon:.3f})"
        )
    print()


def _print_table(title: str, df: pd.DataFrame) -> None:
    print("=" * 78)
    print(title)
    print("=" * 78)
    with pd.option_context(
        "display.width", 120, "display.max_rows", 40,
        "display.float_format", "{:.2f}".format,
    ):
        print(df)
    print()


def run_comparison(
    lat: float,
    lon: float,
    year: int,
    month: int,
    dirs: dict[str, Path | None],
    out_dir: Path | None = None,
    domain_stats_full_year: bool = False,
) -> None:
    """Run the full point-wise + domain comparison and write the reports."""
    adapters: dict[str, ProviderAdapter] = {
        cls.name: cls(output_dir=dirs.get(cls.name)) for cls in PROVIDERS
    }

    if out_dir is None:
        first = next(iter(adapters.values()))
        out_dir = first.output_dir.parent.parent / "comparison"

    cells: dict[str, CellLocation] = {}
    targets: dict[str, MonthFile] = {}
    month_frames: dict[str, pd.DataFrame] = {}
    year_frames: dict[str, dict[int, pd.DataFrame]] = {}
    domain_stats_frames: list[pd.DataFrame] = []

    for name, adapter in adapters.items():
        # Restrict to the requested year up front -- an output dir may
        # carry unrelated leftover files from other test runs (e.g. a
        # stray ERA5_LAND_1950_01_all_attrs.nc), which must never be
        # picked as "some file" for grid lookup or full-year aggregation.
        months = [f for f in adapter.list_months() if f.year == year]
        if not months:
            raise FileNotFoundError(
                f"{name}: no {year} monthly files in {adapter.output_dir}"
            )
        target = next((f for f in months if f.month == month), None)
        if target is None:
            raise FileNotFoundError(
                f"{name}: no {year}-{month:02d} file in {adapter.output_dir}"
            )

        logger.info("%s: locating cell nearest (%.3f, %.3f)...", name, lat, lon)
        cell = adapter.find_cell(lat, lon, target)
        cells[name] = cell
        targets[name] = target

        logger.info("%s: extracting %d-%02d point series...", name, year, month)
        month_frames[name] = adapter.load_point_series(target, cell)

        logger.info("%s: extracting full-year point series...", name)
        year_frames[name] = {
            f.month: adapter.load_point_series(f, cell) for f in months
        }

        stats_months = months if domain_stats_full_year else [target]
        for f in stats_months:
            logger.info("%s: domain stats for %d-%02d...", name, f.year, f.month)
            domain_stats_frames.append(adapter.domain_stats(f))

    domain_stats = (
        pd.concat(domain_stats_frames, ignore_index=True)
        if domain_stats_frames else pd.DataFrame()
    )

    _print_cell_report(cells)

    checker = RobustnessChecker(month_frames, year_frames)
    monthly_summary = checker.monthly_summary()
    weekly_summary = checker.weekly_summary()
    diurnal_summary = checker.diurnal_summary()

    _print_table(
        "MONTHLY MEAN, WHOLE YEAR (attribute x month, columns = provider)",
        monthly_summary,
    )
    _print_table(
        f"WEEKLY MEAN WITHIN {calendar.month_name[month]} {year}",
        weekly_summary,
    )
    _print_table(
        f"DIURNAL CYCLE (mean by hour-of-day) WITHIN "
        f"{calendar.month_name[month]} {year}",
        diurnal_summary,
    )
    if not domain_stats.empty:
        _print_table(
            "WHOLE-EUROPE DOMAIN STATS (native grid per provider, "
            "no regridding)",
            domain_stats,
        )

    cosmo_dni_compare: pd.DataFrame | None = None
    cosmo_dni_stats: pd.DataFrame | None = None
    cosmo_adapter = adapters.get("COSMO-REA6")
    if isinstance(cosmo_adapter, CosmoAdapter):
        logger.info("COSMO-REA6: native vs pvlib DNI/DHI comparison...")
        cosmo_dni_compare = cosmo_adapter.dni_method_comparison(
            targets["COSMO-REA6"], cells["COSMO-REA6"],
        )
        cosmo_dni_stats = cosmo_dni_method_stats(cosmo_dni_compare)
        _print_table(
            "COSMO-REA6 DNI/DHI: native (direct/diffuse split) vs "
            "pvlib DIRINT-on-GHI",
            cosmo_dni_stats,
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    xlsx_path = out_dir / f"provider_comparison_{year}_{month:02d}.xlsx"
    write_excel_report(
        xlsx_path, month_frames, cells, monthly_summary, weekly_summary,
        diurnal_summary, domain_stats, cosmo_dni_compare, cosmo_dni_stats,
    )
    flat_paths = write_flat_reports(out_dir, month_frames, year, month)

    ref_cell = cells["ERA5-Land"]
    plotter = ComparisonPlotter(
        month_frames, ref_cell.lat, ref_cell.lon, year, month,
    )

    hourly_fig = plotter.hourly_figure()
    hourly_path = out_dir / f"provider_comparison_hourly_{year}_{month:02d}.png"
    hourly_fig.savefig(hourly_path, dpi=150)
    plt.close(hourly_fig)

    diurnal_fig = plotter.diurnal_figure(diurnal_summary)
    diurnal_path = (
        out_dir / f"provider_comparison_diurnal_{year}_{month:02d}.png"
    )
    diurnal_fig.savefig(diurnal_path, dpi=150)
    plt.close(diurnal_fig)

    dni_method_path = None
    if cosmo_dni_compare is not None:
        dni_method_fig = cosmo_dni_method_figure(
            cosmo_dni_compare, ref_cell.lat, ref_cell.lon, year, month,
        )
        dni_method_path = (
            out_dir / f"provider_comparison_cosmo_dni_method_{year}_{month:02d}.png"
        )
        dni_method_fig.savefig(dni_method_path, dpi=150)
        plt.close(dni_method_fig)

    print(f"Excel report : {xlsx_path}")
    print(f"Hourly plot  : {hourly_path}")
    print(f"Diurnal plot : {diurnal_path}")
    if dni_method_path is not None:
        print(f"DNI-method plot : {dni_method_path}")
    print(f"CSV/Parquet  : {len(flat_paths)} files in {out_dir}")


def _parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument(
        "--lat", type=float, default=70.5,
        help=(
            "Target latitude. Default is an Arctic-edge test point (North "
            "Cape, Norway area) -- the shared domain (~34-72N, ~11W-32E) "
            "has no sub-Saharan coverage, so this is the meaningful "
            "'extreme/edge' case."
        ),
    )
    ap.add_argument("--lon", type=float, default=25.0, help="Target longitude.")
    ap.add_argument("--year", type=int, default=2018, help="Year to compare.")
    ap.add_argument(
        "--month", type=int, default=6, help="Month (1-12) to compare.",
    )
    ap.add_argument(
        "--out-dir", type=Path, default=None,
        help="Output folder for the .xlsx report and .png plots. "
             "Default: <output_dir's grandparent>/comparison",
    )
    ap.add_argument("--cosmo-dir", type=Path, default=None)
    ap.add_argument("--era5-dir", type=Path, default=None)
    ap.add_argument("--merra2-dir", type=Path, default=None)
    ap.add_argument(
        "--domain-stats-full-year", action="store_true",
        help=(
            "Compute whole-Europe domain stats for all 12 months instead "
            "of just the chosen month. Much slower -- COSMO's 824x848 "
            "grid dominates the runtime."
        ),
    )
    ap.add_argument(
        "-v", "--verbose", action="store_true",
        help="INFO-level progress logging.",
    )
    return ap.parse_args()


def main() -> None:
    args = _parse_args()
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if not 1 <= args.month <= 12:
        sys.exit(f"--month must be 1-12, got {args.month}")

    dirs: dict[str, Path | None] = {
        "COSMO-REA6": args.cosmo_dir,
        "ERA5-Land": args.era5_dir,
        "MERRA-2": args.merra2_dir,
    }

    run_comparison(
        lat=args.lat, lon=args.lon, year=args.year, month=args.month,
        dirs=dirs, out_dir=args.out_dir,
        domain_stats_full_year=args.domain_stats_full_year,
    )


if __name__ == "__main__":
    main()
