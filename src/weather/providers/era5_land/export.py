"""Export processed ERA5-Land data to compressed NetCDF.

Writes a monthly :class:`xarray.Dataset` from
:func:`~weather.providers.era5_land.transform.build_monthly_dataset`
to a single NetCDF-4 file with zlib compression and float32 encoding,
matching the COSMO-REA6 export conventions.

Output naming::

    ERA5_LAND_<YYYY>_<MM>_all_attrs.nc

Typical usage::

    from weather.providers.era5_land.export import export_netcdf
    export_netcdf(ds, year=2018, month=1)
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING

from .config import get_config

if TYPE_CHECKING:  # pragma: no cover
    import xarray  # noqa: F401

logger = logging.getLogger(__name__)

# Prevent HDF5 file-locking deadlocks on network/parallel file systems.
os.environ.setdefault("HDF5_USE_FILE_LOCKING", "FALSE")


def _build_encoding(ds: xarray.Dataset, complevel: int = 1) -> dict:
    """Build per-variable NetCDF encoding with zlib compression.

    float32 + zlib(complevel=1): halves file size with no meaningful
    precision loss for radiation/temperature/wind, and levels 2-9 give
    diminishing returns for much higher CPU cost.  Identical policy to
    the COSMO-REA6 exporter.
    """
    encoding = {}
    for var in ds.data_vars:
        encoding[var] = {
            "zlib": True,
            "complevel": complevel,
            "dtype": "float32",
        }
    return encoding


def output_filename(year: int, month: int) -> str:
    """Return the canonical monthly filename for *year*/*month*."""
    return f"ERA5_LAND_{year}_{month:02d}_all_attrs.nc"


def export_netcdf(
    ds: xarray.Dataset,
    *,
    year: int,
    month: int,
    output_dir: Path | None = None,
    output_path: Path | None = None,
    complevel: int = 1,
) -> Path:
    """Write the processed monthly dataset to compressed NetCDF-4.

    Parameters
    ----------
    ds : xarray.Dataset
        Processed monthly ERA5-Land dataset (with derived ``GHI``).
    year, month : int
        Used for the default filename.
    output_dir : Path, optional
        Directory for the output file.  Defaults to
        ``config["output_dir"]``.  Ignored if *output_path* is given.
    output_path : Path, optional
        Explicit full output path (overrides *output_dir*).
    complevel : int
        zlib compression level (default 1).

    Returns
    -------
    Path
        Path to the written NetCDF file.
    """
    if output_path is None:
        if output_dir is None:
            output_dir = get_config()["output_dir"]
        output_path = Path(output_dir) / output_filename(year, month)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Materialise dask arrays one variable at a time to bound peak RAM.
    t0 = time.perf_counter()
    logger.info("Computing dask arrays (variable-by-variable)...")
    for var_name in list(ds.data_vars):
        if hasattr(ds[var_name].data, "dask"):
            logger.info("  Computing %s ...", var_name)
            ds[var_name] = ds[var_name].compute()
    logger.info("  Computed in %.1f s", time.perf_counter() - t0)

    encoding = _build_encoding(ds, complevel=complevel)
    logger.info("Writing NetCDF: %s (complevel=%d)", output_path, complevel)

    t1 = time.perf_counter()
    ds.to_netcdf(
        output_path,
        encoding=encoding,
        format="NETCDF4",
        engine="netcdf4",
    )
    logger.info("  Write done in %.1f s", time.perf_counter() - t1)

    size_mb = output_path.stat().st_size / (1024 * 1024)
    logger.info("NetCDF written: %s (%.1f MB)", output_path.name, size_mb)
    return output_path
