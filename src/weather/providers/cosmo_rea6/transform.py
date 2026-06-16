"""Transform raw COSMO-REA6 GRIB fields into analysis-ready variables.

Reads decompressed GRIB files with :mod:`xarray` + ``cfgrib``, applies unit
conversions, computes derived fields (GHI, DHI, WS_10M, DNI), and assembles
:class:`xarray.Dataset` objects with the COSMO-REA6 rotated-pole coordinates
and auxiliary WGS84 ``latitude`` / ``longitude`` coordinates.

Key conversions and derived variables:

+--------+----------+-------------+----------------------------------+
| Field  | Raw unit | Output unit | Formula / source                 |
+========+==========+=============+==================================+
| T      | K        | °C          | T_2M − 273.15                    |
| GHI    | W/m²     | W/m²        | SWDIFDS_RAD + SWDIRS_RAD         |
| DHI    | W/m²     | W/m²        | SWDIFDS_RAD                      |
| WS_10M | m/s      | m/s         | √(U_10M² + V_10M²)               |
| DNI    | W/m²     | W/m²        | SWDIRS_RAD / cos(θ_z) [exp.]     |
+--------+----------+-------------+----------------------------------+

See :func:`compute_dni` for the DNI methodology and
``docs/dni_methodology.md`` for a full algorithm comparison
(Spencer 1971 vs. Meeus vs. NREL SPA).

Typical usage::

    from weather.providers.cosmo_rea6.transform import (
        open_grib_month, build_annual_dataset, compute_dni,
    )
    ds_jan = open_grib_month("SWDIRS_RAD", 2018, 1)
    ds_year = build_annual_dataset(2018)
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    import xarray  # noqa: F401  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)


def _import_xarray():
    """Lazy-import xarray (heavy dependency, not needed at module level)."""
    try:
        import xarray as xr  # noqa: F811  # type: ignore[import-untyped]
        return xr
    except ImportError as exc:
        raise ImportError(
            "xarray is required for weather transformation.  "
            "Install with: conda install conda-forge::xarray"
        ) from exc


# ---------------------------------------------------------------------------
# GRIB reading
# ---------------------------------------------------------------------------

def _open_grib_robust(
    grb_path: Path,
    attribute: str,
    xr: Any,
) -> Any:
    """Open a GRIB file, handling ``uvRelativeToGrid`` ambiguity.

    Strategy
    --------
    1. Try without any ``filter_by_keys`` — works for the vast majority
       of COSMO-REA6 files.
    2. If cfgrib raises ``DatasetBuildError`` (file contains both
       ``uvRelativeToGrid=0`` and ``uvRelativeToGrid=1`` messages), retry
       with each value in turn and return the first non-empty dataset.

    This avoids hard-coding a per-attribute flag, which breaks for months
    where DWD packed the same attribute with a different ``uvRelativeToGrid``
    encoding than usual.
    """
    _common = dict(engine="cfgrib", chunks={"time": 168})

    # Pass 1 — no filter (handles ~22/24 years without any issue)
    try:
        ds = xr.open_dataset(str(grb_path), **_common)
        if ds.data_vars:
            return ds
    except Exception as exc:
        # Catch cfgrib's DatasetBuildError for uvRelativeToGrid ambiguity
        error_msg = str(exc)
        if "multiple values for unique key" not in error_msg:
            # Re-raise non-ambiguity errors (file not found, corrupt GRIB)
            raise RuntimeError(
                f"Failed to open GRIB file {grb_path}: {error_msg}"
            ) from exc

    # Pass 2 — ambiguous file; try uvRelativeToGrid=0 then =1
    for uv_flag in (0, 1):
        try:
            ds = xr.open_dataset(
                str(grb_path),
                filter_by_keys={"uvRelativeToGrid": uv_flag},
                **_common,
            )
            if ds.data_vars:
                logger.debug(
                    "%s: resolved with uvRelativeToGrid=%d",
                    grb_path.name, uv_flag,
                )
                return ds
        except OSError as exc:
            # File I/O errors - log and continue to next flag
            logger.debug(
                "uvRelativeToGrid=%d failed for %s: %s",
                uv_flag, grb_path.name, exc,
            )
            continue
        except Exception as exc:
            # Other errors (e.g., cfgrib parsing errors) - log and continue
            logger.debug(
                "uvRelativeToGrid=%d raised unexpected error for %s: %s",
                uv_flag, grb_path.name, exc,
            )
            continue

    raise RuntimeError(
        f"Could not open GRIB file with any uvRelativeToGrid filter: "
        f"{grb_path}"
    )


def open_grib_month(
    attribute: str,
    year: int,
    month: int,
    *,
    grb_dir: Path | None = None,
) -> xarray.Dataset:
    """Open a single monthly GRIB file as an xarray Dataset.

    Parameters
    ----------
    attribute : str
        COSMO-REA6 attribute name (e.g. ``"T_2M"``).
    year, month : int
        Target period.
    grb_dir : Path, optional
        Directory containing decompressed ``.grb`` files
        (per-attribute sub-dirs).
        Defaults to ``<work_dir>/decompress/<attribute>/``.

    Returns
    -------
    xarray.Dataset
        Dataset with dimensions ``(time, y, x)`` in native rotated-pole
        coordinates.
    """
    xr = _import_xarray()
    from .config import get_config

    cfg = get_config()
    if grb_dir is None:
        grb_dir = cfg["decompress_dir"] / attribute

    grb_name = f"{attribute}.2D.{year}{month:02d}.grb"
    grb_path = grb_dir / grb_name

    if not grb_path.exists():
        raise FileNotFoundError(f"GRIB file not found: {grb_path}")

    logger.info("Opening GRIB: %s", grb_path)
    return _open_grib_robust(grb_path, attribute, xr)


def open_grib_year(
    attribute: str,
    year: int,
    *,
    grb_dir: Path | None = None,
) -> xarray.Dataset:
    """Open and concatenate all monthly GRIB files for one attribute/year.

    All twelve months (January–December) are loaded automatically.
    Uses :func:`xarray.open_mfdataset` with ``parallel=True`` for
    concurrent I/O across months via dask.delayed.

    Parameters
    ----------
    attribute : str
        COSMO-REA6 attribute name.
    year : int
        Target year.
    grb_dir : Path, optional
        Root directory for decompressed GRIBs.

    Returns
    -------
    xarray.Dataset
        Concatenated along the ``time`` dimension.
    """
    xr = _import_xarray()
    from .config import get_config

    cfg = get_config()
    if grb_dir is None:
        grb_dir = cfg["decompress_dir"]

    attr_dir = grb_dir / attribute
    paths = []
    for m in range(1, 13):
        p = attr_dir / f"{attribute}.2D.{year}{m:02d}.grb"
        if not p.exists():
            raise FileNotFoundError(f"GRIB file not found: {p}")
        paths.append(str(p))

    logger.info(
        "Opening %d GRIB files for %s (parallel=True)",
        len(paths), attribute,
    )
    combined = xr.open_mfdataset(
        paths,
        engine="cfgrib",
        combine="nested",
        concat_dim="time",
        parallel=True,
        chunks={"time": 168},  # ~1 week per chunk; fits in memory
        compat="override",
        coords="minimal",
        data_vars="minimal",
    )
    logger.info(
        "Loaded %s for %d: %d timesteps, grid %s",
        attribute, year, combined.sizes["time"],
        "x".join(str(s) for s in combined.sizes.values()),
    )
    return combined


# ---------------------------------------------------------------------------
# Unit conversions
# ---------------------------------------------------------------------------

def convert_temperature(
    ds: xarray.Dataset, var_name: str = "t2m"
) -> xarray.DataArray:
    """Convert temperature from Kelvin to Celsius.

    Parameters
    ----------
    ds : xarray.Dataset
        Dataset containing the temperature variable.
    var_name : str
        Name of the temperature variable in the dataset
        (cfgrib default: ``"t2m"``).

    Returns
    -------
    xarray.DataArray
        Temperature in °C.
    """
    da = ds[var_name]
    # Guard against double-conversion: cfgrib may pre-decode to °C.
    # Sample one cell rather than calling .max() to avoid materialising
    # the full dask array.
    if hasattr(da.values, 'flat'):
        sample = float(da.values.flat[0])
    else:
        sample = float(da.isel({d: 0 for d in da.dims}).values)
    if sample > 100:  # clearly Kelvin (typical range 230–320 K)
        logger.info(
            "Converting T_2M from Kelvin to Celsius (sample=%.1f K)",
            sample,
        )
        da = da - 273.15
        da.attrs["units"] = "degC"
    else:
        logger.info(
            "T_2M appears to already be in Celsius (sample=%.1f)",
            sample,
        )
        da.attrs["units"] = "degC"
    da.attrs["long_name"] = "Temperature at 2m"
    return da


def compute_ghi(
    ds_diffuse: xarray.Dataset,
    ds_direct: xarray.Dataset,
    diffuse_var: str = "SWDIFDS_RAD",
    direct_var: str = "SWDIRS_RAD",
) -> xarray.DataArray:
    """Compute Global Horizontal Irradiance: GHI = diffuse + direct.

    Parameters
    ----------
    ds_diffuse : xarray.Dataset
        Dataset with the SWDIFDS_RAD field.
    ds_direct : xarray.Dataset
        Dataset with the SWDIRS_RAD field.
    diffuse_var, direct_var : str
        Variable names inside the datasets.  cfgrib sometimes lowercases
        or uses short_name; the function tries common alternatives.

    Returns
    -------
    xarray.DataArray
        GHI in W/m².

    Notes
    -----
    Both inputs are clipped to ``[0, ∞)`` before summing — negative
    irradiance (rare GRIB artefact) is physically impossible.
    """
    diffuse = _resolve_var(ds_diffuse, diffuse_var)
    direct = _resolve_var(ds_direct, direct_var)

    ghi = diffuse.clip(min=0) + direct.clip(min=0)
    ghi.attrs = {"units": "W/m2", "long_name": "Global Horizontal Irradiance"}
    return ghi


def compute_dhi(
    ds_diffuse: xarray.Dataset,
    diffuse_var: str = "SWDIFDS_RAD",
) -> xarray.DataArray:
    """Extract Diffuse Horizontal Irradiance: DHI = SWDIFDS_RAD.

    Parameters
    ----------
    ds_diffuse : xarray.Dataset
        Dataset with the diffuse radiation field.
    diffuse_var : str
        Variable name.

    Returns
    -------
    xarray.DataArray
        DHI in W/m².
    """
    dhi = _resolve_var(ds_diffuse, diffuse_var).clip(min=0)
    dhi.attrs = {"units": "W/m2", "long_name": "Diffuse Horizontal Irradiance"}
    return dhi


def compute_wind_speed(
    ds_u: xarray.Dataset,
    ds_v: xarray.Dataset,
    u_var: str = "u10",
    v_var: str = "v10",
) -> xarray.DataArray:
    """Compute scalar wind speed: WS = sqrt(U² + V²).

    The magnitude is identical in both the rotated-pole and WGS84
    coordinate systems, so no vector rotation is needed for this
    derived quantity.

    Parameters
    ----------
    ds_u, ds_v : xarray.Dataset
        Datasets with U and V wind components.
    u_var, v_var : str
        Variable names.

    Returns
    -------
    xarray.DataArray
        Wind speed at 10 m in m/s.
    """
    xr = _import_xarray()
    u = _resolve_var(ds_u, u_var)
    v = _resolve_var(ds_v, v_var)
    ws: xarray.DataArray = xr.DataArray(
        np.sqrt(u ** 2 + v ** 2),
        coords=u.coords,
        dims=u.dims,
        attrs={"units": "m/s", "long_name": "Wind speed at 10m"},
    )
    return ws


def compute_dni(
    ds_direct: xarray.Dataset,
    *,
    elevation_threshold: float = 5.0,
) -> xarray.DataArray:
    """Compute per-cell Direct Normal Irradiance (DNI) in W/m².

    DNI = SWDIRS_RAD / cos(θ_z), where θ_z is the solar zenith angle,
    derived analytically from the grid's WGS84 latitude/longitude and
    UTC time using the Spencer (1971) formula.

    Cells where the solar elevation is below *elevation_threshold* are
    set to zero instead of dividing by a near-zero cos(θ_z).  This is
    physically correct — there is no direct beam below the horizon —
    and avoids the artificial inflation that a simple cos-clip produces
    at low sun angles.

    When the input dataset is dask-backed (the normal case after
    :func:`open_grib_month`), the entire SZA computation is performed
    lazily with ``dask.array``, chunked on **both** the time axis (168
    time steps per chunk) and the spatial axes (~206 × 212 cells per
    chunk).  This produces ≈ 80 independent tasks for a one-month
    824 × 848 grid, filling many cores on the dask threaded scheduler.

    .. note::
        **Why not pvlib?**  pvlib's ``get_solarposition`` is designed
        for ``(DatetimeIndex, scalar_lat, scalar_lon)`` — one location
        at a time.  For a 824 × 848 grid you would need ~700 k serial
        calls or a time loop, which is many times slower than a fully
        vectorised Spencer formula broadcast over the same grid.  pvlib
        is the right tool for single-site analysis or DISC decomposition
        from GHI; for rasterised grids, Spencer is preferred.

    .. warning::
        This is an **experimental** diagnostic intended for testing and
        exploration only.  Use GHI with a pvlib DISC decomposition for
        production-quality DNI estimates.

    Parameters
    ----------
    ds_direct : xarray.Dataset
        SWDIRS_RAD dataset from :func:`open_grib_month`.  Must have
        ``latitude`` and ``longitude`` as 2-D auxiliary coordinates
        (written automatically by cfgrib for COSMO-REA6 GRIBs).
    elevation_threshold : float
        Minimum solar elevation in degrees for which DNI is reported.
        Cells where the sun is below this angle are set to zero.
        Default is 5.0 (i.e. sun must be at least 5° above horizon).

    Returns
    -------
    xarray.DataArray
        DNI in W/m², same spatiotemporal shape as SWDIRS_RAD.
        Zero where solar elevation < *elevation_threshold*.

    Notes
    -----
    ``cos_sza_safe`` is clipped to ``[1e-3, 1.0]``.  The lower bound prevents
    division-by-zero at the horizon (dask evaluates both branches of
    ``xr.where`` before masking, so an ``inf`` in the un-masked branch
    would propagate into the output).  The upper bound prevents float32
    rounding in the Spencer dot-product from pushing ``cos(θ_z)`` above 1.0,
    which would give ``DNI < SWDIRS_RAD`` for above-threshold cells.

    References
    ----------
    Spencer, J. W. (1971). Fourier series representation of the position
    of the sun.  *Search*, 2(5), 172.
    """
    import pandas as pd

    xr = _import_xarray()

    var_name = next(iter(ds_direct.data_vars))
    swdirs = ds_direct[var_name]

    if (
        "latitude" not in ds_direct.coords
        or "longitude" not in ds_direct.coords
    ):
        raise ValueError(
            "Dataset is missing 'latitude'/'longitude' coordinates. "
            "cfgrib writes these from COSMO-REA6 GRIBs automatically; "
            "verify the GRIB file contains a valid grid description."
        )

    # 2-D geographic coordinates (y, x)  [float32 saves memory]
    lat_2d = ds_direct["latitude"].values.astype("float32")
    lon_2d = ds_direct["longitude"].values.astype("float32")

    ts = pd.DatetimeIndex(swdirs.time.values)
    doy = ts.dayofyear.values.astype("float32")                    # (T,)
    utc_h = (ts.hour + ts.minute / 60.0).values.astype("float32")  # (T,)

    ny, nx = lat_2d.shape
    T = doy.shape[0]

    da_mod: Any = None
    try:
        import dask.array as da_mod
        _dask_backed = hasattr(swdirs.data, "__dask_graph__")
    except ImportError:
        _dask_backed = False

    m: Any
    if _dask_backed:
        _chunks = swdirs.chunks
        assert _chunks is not None
        time_chunks = _chunks[0]
        # Spatial chunks: quarter the grid (~206 × 212 for 824 × 848).
        # This gives T/168 × 4 × 4 ≈ 80 independent dask tasks, enough
        # to saturate many-core machines.  Increase the divisor to reduce
        # per-chunk memory; decrease it if the task graph overhead matters.
        y_chunk = max(1, ny // 4)
        x_chunk = max(1, nx // 4)
        mem_mb = T * ny * nx * 4 / (1024 * 1024)
        n_chunks = len(time_chunks) * ((ny + y_chunk - 1) // y_chunk) * (
            (nx + x_chunk - 1) // x_chunk
        )
        logger.info(
            "  DNI: %d×%d×%d float32 dask"
            " (time chunks %s, spatial %d×%d → %d tasks, ~%.0f MB)",
            T, ny, nx, time_chunks, y_chunk, x_chunk, n_chunks, mem_mb,
        )
        doy_bc = da_mod.from_array(
            doy[:, None, None], chunks=(time_chunks, 1, 1)
        )
        utc_h_bc = da_mod.from_array(
            utc_h[:, None, None], chunks=(time_chunks, 1, 1)
        )
        # Chunk lat/lon spatially so the broadcast result inherits chunks
        # on all three axes → full 3-D task graph.
        lat_bc = da_mod.from_array(
            lat_2d[None], chunks=(1, y_chunk, x_chunk)
        )
        lon_bc = da_mod.from_array(
            lon_2d[None], chunks=(1, y_chunk, x_chunk)
        )
        m = da_mod
    else:
        mem_mb = T * ny * nx * 4 / (1024 * 1024)
        logger.info(
            "  DNI: %d×%d×%d float32 numpy (~%.0f MB)", T, ny, nx, mem_mb,
        )
        doy_bc = doy[:, None, None]
        utc_h_bc = utc_h[:, None, None]
        lat_bc = lat_2d[None]
        lon_bc = lon_2d[None]
        m = np

    # Spencer (1971): day-angle, declination, equation of time, hour angle
    B = (2.0 * np.pi / 365.0) * (doy_bc - 1.0)

    # Solar declination (radians)
    decl = (
        0.006918
        - 0.399912 * m.cos(B) + 0.070257 * m.sin(B)
        - 0.006758 * m.cos(2*B) + 0.000907 * m.sin(2*B)
        - 0.002697 * m.cos(3*B) + 0.001480 * m.sin(3*B)
    )

    # Equation of time (hours)
    eot = (
        0.000075
        + 0.001868 * m.cos(B) - 0.032077 * m.sin(B)
        - 0.014615 * m.cos(2*B) - 0.040890 * m.sin(2*B)
    ) * (229.18 / 60.0)

    # Hour angle (radians): 15°/h, longitude + EoT correction
    hour_angle = (
        15.0 * (utc_h_bc + lon_bc / 15.0 + eot - 12.0)
    ) * (np.pi / 180.0)
    lat_rad = lat_bc * (np.pi / 180.0)

    # cos(zenith) — unclipped, used for elevation masking below
    cos_sza_raw = (
        m.sin(lat_rad) * m.sin(decl)
        + m.cos(lat_rad) * m.cos(decl) * m.cos(hour_angle)
    )

    # Solar elevation in degrees; arcsin input clamped to [-1, 1] for safety
    elevation = (
        m.arcsin(m.clip(cos_sza_raw, -1.0, 1.0)) * (180.0 / np.pi)
    )   # degrees, shape (T, y, x)

    # Clip to [1e-3, 1.0]: lower → finite division at horizon;
    # upper → corrects float32 rounding above 1.0 (see docstring Notes).
    cos_sza_safe = m.clip(cos_sza_raw, 1e-3, 1.0)

    cos_da: xarray.DataArray = xr.DataArray(cos_sza_safe, dims=swdirs.dims)
    elev_da: xarray.DataArray = xr.DataArray(elevation, dims=swdirs.dims)

    dni_raw: xarray.DataArray = swdirs / cos_da
    # Zero-out cells where sun is below threshold (physically: no direct beam)
    dni: xarray.DataArray = xr.where(
        elev_da >= elevation_threshold, dni_raw, 0.0
    ).rename("DNI")

    dni.attrs = {
        "long_name": "Direct Normal Irradiance (experimental per-cell)",
        "units": "W/m2",
        "note": (
            f"DNI = SWDIRS_RAD / cos(SZA) where elevation >= "
            f"{elevation_threshold} deg, else 0. "
            "SZA from Spencer (1971). "
            "Experimental — use pvlib DISC from GHI for production DNI."
        ),
    }
    logger.info(
        "  DNI computed; elevation threshold %.1f deg"
        " (%s backend)",
        elevation_threshold,
        "dask" if _dask_backed else "numpy",
    )
    return dni


def _strip_scalar_coords(da: xarray.DataArray) -> xarray.DataArray:
    """Drop all non-dimension scalar coordinates from a DataArray.

    cfgrib attaches scalar coordinates like ``heightAboveGround``, ``step``,
    ``surface``, and ``valid_time`` to each dataset.  These values differ
    across variables (e.g. T_2M has ``heightAboveGround=2``, wind has
    ``heightAboveGround=10``, radiation has none) and cause
    ``MergeError: conflicting values`` when DataArrays are combined into a
    single :class:`xarray.Dataset`.

    Dropping these non-dimension coordinates is safe because the information
    is already captured in the variable names and metadata.
    """
    drop = [c for c in da.coords if c not in da.dims]
    return da.drop_vars(drop) if drop else da


# Mapping from COSMO-REA6 canonical names to the eccodes/cfgrib short names
# that cfgrib may assign when decoding GRIBs.  Each CR6 per-attribute GRIB
# contains exactly one variable, so cfgrib's internal renaming does not
# affect which data are returned — only which name they appear under.
_CFGRIB_ALIASES: dict[str, tuple[str, ...]] = {
    "PS":         ("sp",),
    "H_SNOW":     ("sde", "sd"),
    "SNOW_GSP":   ("lssf", "sf"),
    "SNOW_CON":   ("snoc", "csf"),
    "T_2M":       ("2t", "t2m"),
    "U_10M":      ("10u", "u10"),
    "V_10M":      ("10v", "v10"),
    "SWDIRS_RAD": ("ssrd", "fdir"),
    "SWDIFDS_RAD": ("sdiff", "ssrdc"),
}


def _resolve_var(ds: xarray.Dataset, preferred: str) -> xarray.DataArray:
    """Resolve a variable from a dataset, trying common cfgrib aliases.

    cfgrib decodes COSMO GRIB variables using the eccodes short-name table,
    which may differ from the COSMO-REA6 shorthand names (e.g. 'PS' becomes
    'sp', 'H_SNOW' becomes 'sde').  This helper tries the caller's preferred
    name first, then any known cfgrib aliases, then the first data variable
    (safe because each per-attribute GRIB file contains exactly one variable).

    Parameters
    ----------
    ds : xarray.Dataset
    preferred : str
        Preferred variable name (COSMO-REA6 shorthand).

    Returns
    -------
    xarray.DataArray

    Raises
    ------
    KeyError
        If the dataset has no data variables.
    """
    if preferred in ds:
        return ds[preferred]

    # Try lowercase match
    lower = preferred.lower()
    for name in ds.data_vars:
        if str(name).lower() == lower:
            return ds[name]

    # Try known cfgrib eccodes aliases (no warning — expected behaviour)
    for alias in _CFGRIB_ALIASES.get(preferred, ()):
        if alias in ds:
            logger.debug(
                "'%s' decoded by cfgrib as '%s' (eccodes alias)",
                preferred, alias,
            )
            return ds[alias]

    # Last resort: take the only variable in the file (each GRIB is
    # per-attribute, so there is exactly one data variable)
    data_vars = list(ds.data_vars)
    if data_vars:
        logger.debug(
            "'%s' not found by name; using sole data variable '%s'",
            preferred, data_vars[0],
        )
        return ds[data_vars[0]]

    raise KeyError(f"No data variables in dataset; expected '{preferred}'")


# ---------------------------------------------------------------------------
# Full annual dataset assembly
# ---------------------------------------------------------------------------

def build_annual_dataset(
    year: int | None = None,
    *,
    grb_dir: Path | None = None,
    include_wind_components: bool = True,
) -> xarray.Dataset:
    """Assemble a complete annual dataset with all derived variables.

    Reads all five raw attributes for all twelve months, applies unit
    conversions, computes GHI/DHI/WS_10M/T, and merges into a single
    :class:`xarray.Dataset`.

    Parameters
    ----------
    year : int, optional
        Target year (default from config).
    grb_dir : Path, optional
        Root decompressed-GRIB directory.
    include_wind_components : bool
        If ``True`` (default), keep raw ``U_10M`` and ``V_10M`` in the
        output alongside the scalar ``WS_10M``.  A metadata warning is
        attached noting that U/V are in rotated-pole coordinates.

    Returns
    -------
    xarray.Dataset
        Variables: ``T``, ``GHI``, ``DHI``, ``WS_10M``, and optionally
        ``U_10M``, ``V_10M``.  Coordinates include the native rotated-pole
        grid (``rlat``, ``rlon``) and auxiliary WGS84 ``latitude`` /
        ``longitude`` (if the COSMO_REA6_CONST file has been downloaded).

    Notes
    -----
    DNI is not included in the output of this function.  Use
    :func:`compute_dni` on the individual monthly datasets if per-grid-cell
    DNI is needed, or apply a pvlib DISC decomposition from GHI for
    single-site analysis.
    """
    xr = _import_xarray()
    from .config import get_config

    cfg = get_config()
    year = year or cfg["year"]

    ncores = cfg["ncores"]
    # Threaded scheduler: all threads share one process address space,
    # which is more memory-efficient than multi-process for large arrays.
    import dask
    dask.config.set(scheduler="threads", num_workers=ncores)
    logger.info("Dask threaded scheduler: %d threads", ncores)

    logger.info("Building annual dataset for %d", year)

    # Load all 5 raw attributes in parallel — cfgrib I/O is the slowest
    # part, and each attribute reads independent files on disk.
    attrs_to_load = ["SWDIFDS_RAD", "SWDIRS_RAD", "T_2M", "U_10M", "V_10M"]

    def _load(attr: str) -> xarray.Dataset:
        return open_grib_year(attr, year, grb_dir=grb_dir)

    logger.info("Reading %d attributes in parallel (%d threads)...",
                len(attrs_to_load), min(len(attrs_to_load), ncores))
    n_workers = min(len(attrs_to_load), ncores)
    with ThreadPoolExecutor(max_workers=n_workers) as pool:
        results = list(pool.map(_load, attrs_to_load))

    ds_diffuse, ds_direct, ds_temp, ds_u, ds_v = results

    # Derive fields
    T = convert_temperature(ds_temp)
    GHI = compute_ghi(ds_diffuse, ds_direct)
    DHI = compute_dhi(ds_diffuse)
    WS = compute_wind_speed(ds_u, ds_v)

    # Strip conflicting non-dimension scalar coordinates (e.g.
    # heightAboveGround, step, surface) before merging — cfgrib attaches
    # different values for different GRIB sources which causes MergeError.
    T = _strip_scalar_coords(T)
    GHI = _strip_scalar_coords(GHI)
    DHI = _strip_scalar_coords(DHI)
    WS = _strip_scalar_coords(WS)

    # Assemble output dataset
    out = xr.Dataset(
        {
            "T": T,
            "GHI": GHI,
            "DHI": DHI,
            "WS_10M": WS,
        },
        attrs={
            "title": f"COSMO-REA6 processed weather data — {year}",
            "source": (
                "DWD COSMO-REA6 reanalysis "
                "(https://opendata.dwd.de/climate_environment/REA/COSMO_REA6/)"
            ),
            "spatial_resolution": "0.055° (~6 km)",
            "temporal_resolution": "1 hour",
            "processing": "buem.weather pipeline",
            "conventions": "CF-1.8",
            "note_DNI": (
                "DNI is not included in this file. "
                "Use compute_dni() on individual monthly datasets for "
                "per-grid-cell DNI, or apply pvlib DISC decomposition "
                "from GHI for single-site analysis."
            ),
        },
    )

    if include_wind_components:
        u_raw = _strip_scalar_coords(_resolve_var(ds_u, "u10"))
        v_raw = _strip_scalar_coords(_resolve_var(ds_v, "v10"))
        u_raw.attrs["long_name"] = (
            "U-component of wind at 10m (rotated-pole grid north)"
        )
        u_raw.attrs["warning"] = (
            "This field uses COSMO-REA6 rotated-pole grid coordinates.  "
            "For true-north wind direction, apply the rotated-pole → WGS84 "
            "vector rotation using pyproj or the COSMO rotation angle."
        )
        v_raw.attrs["long_name"] = (
            "V-component of wind at 10m (rotated-pole grid north)"
        )
        v_raw.attrs["warning"] = u_raw.attrs["warning"]
        out["U_10M"] = u_raw
        out["V_10M"] = v_raw

    logger.info(
        "Annual dataset assembled: %d variables, %d timesteps",
        len(out.data_vars), out.sizes.get("time", 0),
    )
    return out
