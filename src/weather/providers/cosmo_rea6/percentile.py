"""COSMO-REA6 concrete implementation of the percentile weather-file analyser.

Subclasses :class:`~weather.providers.base_percentile.BasePercentileAnalyzer`
with COSMO-REA6-specific implementations of the three abstract methods:

+---------------------+------------------------------------------------------+
| Method              | COSMO-REA6 implementation                            |
+=====================+======================================================+
| ``annual_metric``   | ``ds["GHI"].sum("time")``  (annual GHI, W·h/m²)     |
+---------------------+------------------------------------------------------+
| ``load_annual_dataset`` | Open all 12 monthly NCs via ``open_mfdataset``   |
|                     | (``COSMO_REA6_<year>_??_all_attrs.nc``)              |
+---------------------+------------------------------------------------------+
| ``standard_time_hours`` | 8760 (non-leap normalised year)                  |
+---------------------+------------------------------------------------------+

Why GHI?
--------
GHI (Global Horizontal Irradiance) is the primary solar energy resource
variable and the strongest single indicator of the overall solar climate of a
year.  Annual cumulative GHI integrates both the direct (beam) and diffuse
components and correlates well with cooling loads, PV yield, and building
energy demand.  This aligns with IEC 61724 / ASHRAE 169 TMY methodology.

Output
------
Three NetCDF files are produced:

- ``COSMO_REA6_p10_representative.nc`` — cold/cloudy year
- ``COSMO_REA6_p50_representative.nc`` — median / typical year
- ``COSMO_REA6_p90_representative.nc`` — hot/sunny year

Each file has shape ``(8760, 824, 848)`` per variable plus a
``source_year(rlat, rlon)`` provenance array.
"""

from __future__ import annotations

import logging
from pathlib import Path

import xarray as xr

from ..base_percentile import BasePercentileAnalyzer
from .config import get_config

logger = logging.getLogger(__name__)

_STANDARD_HOURS = 8760  # non-leap year


class CosmoPercentileAnalyzer(BasePercentileAnalyzer):
    """Percentile weather-file analyser for COSMO-REA6 data.

    Parameters
    ----------
    output_dir : Path, optional
        Root output directory.  Defaults to ``<cfg.output_dir>/percentile``.
    ncores : int, optional
        Dask thread count.  Defaults to ``cfg["ncores"]``.

    Examples
    --------
    >>> from pathlib import Path
    >>> from weather.providers.cosmo_rea6.percentile import (
    ...     CosmoPercentileAnalyzer,
    ... )
    >>> ana = CosmoPercentileAnalyzer()
    >>> paths = ana.build_percentile_files(
    ...     years=range(1995, 2019),
    ...     percentiles=[0.10, 0.50, 0.90],
    ...     output_dir=Path("/data/output/percentile"),
    ... )
    """

    def __init__(
        self,
        output_dir: Path | None = None,
        ncores: int | None = None,
    ) -> None:
        cfg = get_config()
        self._cfg = cfg
        _ncores = ncores if ncores is not None else cfg["ncores"]
        super().__init__(ncores=_ncores)
        self._output_dir = (
            output_dir
            if output_dir is not None
            else cfg["output_dir"] / "percentile"
        )

    # ------------------------------------------------------------------
    # Abstract method implementations
    # ------------------------------------------------------------------

    def annual_metric(self, ds: xr.Dataset) -> xr.DataArray:
        """Return the annual cumulative GHI per cell (W·h/m²).

        Parameters
        ----------
        ds : xr.Dataset
            Full annual dataset containing a ``GHI`` variable
            (shape ``(time, rlat, rlon)``).

        Returns
        -------
        xr.DataArray
            Shape ``(rlat, rlon)``, dtype ``float32``.
        """
        ghi_sum = ds["GHI"].sum("time").load()
        return ghi_sum.astype("float32")

    def load_annual_dataset(self, year: int) -> xr.Dataset:
        """Open all monthly COSMO-REA6 NetCDF files for *year* as one dataset.

        Discovers files matching ``COSMO_REA6_<year>_??_all_attrs.nc`` in the
        configured output directory and concatenates them along the time axis
        via :func:`xarray.open_mfdataset`.  No annual merge step is required.

        Parameters
        ----------
        year : int
            Four-digit calendar year (must be in 1995–2018 for standard data).

        Returns
        -------
        xr.Dataset
            Dask-backed dataset (``chunks={"time": 168}``); use as a context
            manager.

        Raises
        ------
        FileNotFoundError
            If no monthly files are found for *year* in ``cfg["output_dir"]``.
        """
        import glob as _glob

        output_dir = self._cfg["output_dir"]
        pattern = str(output_dir / f"COSMO_REA6_{year}_??_all_attrs.nc")
        files = sorted(_glob.glob(pattern))
        if not files:
            raise FileNotFoundError(
                f"No monthly NetCDF files found for year {year}.\n"
                f"Pattern: {pattern}\n"
                "Run test_one_year.py first to generate monthly files."
            )
        if len(files) < 12:
            found_months = [
                int(Path(f).stem.split("_")[2]) for f in files
            ]
            missing_months = [
                m for m in range(1, 13) if m not in found_months
            ]
            logger.warning(
                "Year %d: only %d/12 monthly files found; "
                "missing months: %s",
                year, len(files), missing_months,
            )
        logger.debug(
            "Opening %d monthly file(s) for year %d", len(files), year
        )
        return xr.open_mfdataset(
            files,
            combine="by_coords",
            chunks={"time": 168},
            engine="netcdf4",
        )

    def standard_time_hours(self) -> int:
        """Return 8760 (non-leap year hourly normalisation)."""
        return _STANDARD_HOURS

    # ------------------------------------------------------------------
    # Convenience entry point
    # ------------------------------------------------------------------

    def run(
        self,
        years: list[int] | range,
        percentiles: list[float] | None = None,
    ) -> dict[float, Path]:
        """Build P10/P50/P90 representative files (all in one call).

        Parameters
        ----------
        years : list[int] or range
            Full analysis period, e.g. ``range(1995, 2019)``.
        percentiles : list[float], optional
            Defaults to ``[0.10, 0.50, 0.90]``.

        Returns
        -------
        dict[float, Path]
            Maps each percentile level to the written output file path.
        """
        _pcts = percentiles if percentiles is not None else [0.10, 0.50, 0.90]
        return self.build_percentile_files(
            years=years,
            percentiles=_pcts,
            output_dir=self._output_dir,
            filename_template="COSMO_REA6_p{pct:02d}_representative.nc",
            provider_name="COSMO_REA6",
        )
