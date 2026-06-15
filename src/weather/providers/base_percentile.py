"""Abstract base class for per-cell percentile weather-file generation.

Defines the **template-method** pattern for building P10/P50/P90
representative-year weather files from any multi-year dataset.

Concrete subclasses (e.g. :class:`~weather.providers.cosmo_rea6.percentile
.CosmoPercentileAnalyzer`) need only implement three abstract methods:

+--------------------------------+------------------------------------------+
| Abstract method                | Provider responsibility                  |
+================================+==========================================+
| :meth:`annual_metric`          | Scalar rank metric per cell (e.g. GHI)   |
+--------------------------------+------------------------------------------+
| :meth:`load_annual_dataset`    | Open the annual processed NetCDF (lazy)  |
+--------------------------------+------------------------------------------+
| :meth:`standard_time_hours`    | Length of normalised output time axis    |
+--------------------------------+------------------------------------------+

All orchestration (stacking metrics, computing percentiles, mosaicking cells
from different years, writing output files) is implemented once here.

Mosaic algorithm
----------------
::

    For each unique representative year Y in year_map:
        load annual_dataset(Y)
        extract cells[i,j] where year_map[i,j] == Y
        place time series into output array

    Write output array with compressed encoding.

The mosaic is performed **year-by-year** so that at most one full annual
dataset is in RAM at once (~4–6 GB per year for COSMO-REA6).  Cells from
different years are merged without any interpolation.

The output file also contains a ``source_year`` variable (shape ``(ny, nx)``)
recording which calendar year was selected for each cell.  This is
essential for reproducibility and auditing.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Sequence

import numpy as np

if TYPE_CHECKING:
    import xarray as xr

logger = logging.getLogger(__name__)


class BasePercentileAnalyzer(ABC):
    """Template-method base class for percentile weather-file generation.

    Parameters
    ----------
    ncores : int
        Dask thread count for lazy dataset compute.  Set once for the
        lifetime of the analyser.

    Notes
    -----
    Subclasses do **not** need to override any concrete methods unless they
    require custom behaviour beyond what the default mosaic provides.
    """

    def __init__(self, ncores: int = 4) -> None:
        self._ncores = ncores
        import dask
        dask.config.set(num_workers=ncores)

    # ------------------------------------------------------------------
    # Abstract interface — subclasses must implement these three methods
    # ------------------------------------------------------------------

    @abstractmethod
    def annual_metric(self, ds: "xr.Dataset") -> "xr.DataArray":
        """Compute the scalar ranking metric per cell for one year.

        Parameters
        ----------
        ds : xarray.Dataset
            Annual processed dataset (lazy dask-backed).

        Returns
        -------
        xarray.DataArray
            Shape ``(ny, nx)``.  Typically the annual sum of GHI in W·h/m².
            Must be fully in-memory (call ``.load()`` if dask-backed).
        """

    @abstractmethod
    def load_annual_dataset(self, year: int) -> "xr.Dataset":
        """Open the annual processed NetCDF for *year* (lazy, dask-backed).

        Parameters
        ----------
        year : int
            Four-digit calendar year.

        Returns
        -------
        xarray.Dataset
            Dataset should be opened as a context manager by the caller
            (``with self.load_annual_dataset(year) as ds: ...``).
        """

    @abstractmethod
    def standard_time_hours(self) -> int:
        """Number of hourly timesteps in the normalised output time axis.

        Returns
        -------
        int
            Typically ``8760`` (non-leap year).  Some providers may use
            ``8784`` (leap year) if all output years are aligned to a
            common leap year.
        """

    # ------------------------------------------------------------------
    # Concrete shared logic
    # ------------------------------------------------------------------

    def build_metric_stack(
        self, years: Sequence[int]
    ) -> np.ndarray:
        """Load annual metrics for every year and return a stacked array.

        Parameters
        ----------
        years : sequence of int
            Years to process (must have corresponding annual NC files).

        Returns
        -------
        np.ndarray
            Shape ``(n_years, ny, nx)``, dtype ``float32``.
        """
        from weather.common.percentile import (  # noqa: F401
            select_representative_years as _sr,
        )
        slices: list[np.ndarray] = []
        for year in years:
            logger.info("  Stacking metric: year %d", year)
            with self.load_annual_dataset(year) as ds:
                metric = self.annual_metric(ds)
                # annual_metric() returns xr.DataArray or np.ndarray
                raw = getattr(metric, "values", metric)
                slices.append(np.asarray(raw, dtype=np.float32))
        return np.stack(slices, axis=0)

    def select_representative_years(
        self,
        years: Sequence[int],
        percentiles: Sequence[float],
    ) -> dict[float, np.ndarray]:
        """Compute the representative-year map for every percentile level.

        Parameters
        ----------
        years : sequence of int
            Full analysis period (e.g. ``range(1995, 2019)``).
        percentiles : sequence of float
            Target levels in ``[0, 1]``, e.g. ``[0.10, 0.50, 0.90]``.

        Returns
        -------
        dict[float, np.ndarray]
            Maps each percentile level to an ``(ny, nx)`` int32 array of
            representative years.
        """
        from weather.common.percentile import select_representative_years
        stack = self.build_metric_stack(years)
        return select_representative_years(stack, years, percentiles)

    def build_percentile_files(
        self,
        years: Sequence[int],
        percentiles: Sequence[float],
        output_dir: Path,
        filename_template: str = "{provider}_p{pct:02d}_representative.nc",
        provider_name: str = "weather",
    ) -> dict[float, Path]:
        """Generate one compressed NetCDF per percentile level.

        Parameters
        ----------
        years : sequence of int
            Full analysis period.
        percentiles : sequence of float
            Target levels in ``[0, 1]``, e.g. ``[0.10, 0.50, 0.90]``.
        output_dir : Path
            Directory for output files (created if absent).
        filename_template : str
            f-string template with ``{provider}`` and ``{pct}`` placeholders.
        provider_name : str
            Short identifier inserted into filenames (e.g. ``"COSMO_REA6"``).

        Returns
        -------
        dict[float, Path]
            Maps each percentile level to the written file path.
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        year_maps = self.select_representative_years(years, percentiles)

        out_paths: dict[float, Path] = {}
        for p, year_map in year_maps.items():
            pct_int = int(round(p * 100))
            fname = filename_template.format(
                provider=provider_name, pct=pct_int
            )
            out_path = output_dir / fname
            logger.info(
                "Building P%02d file → %s", pct_int, out_path.name,
            )
            out_paths[p] = self._mosaic_years(
                year_map=year_map,
                all_years=list(years),
                percentile=p,
                output_path=out_path,
            )

        return out_paths

    def _mosaic_years(
        self,
        year_map: np.ndarray,
        all_years: list[int],
        percentile: float,
        output_path: Path,
    ) -> Path:
        """Write one percentile output file by mosaicking cells per year.

        Algorithm:

        1. Read spatial metadata from the first year (dims, coords, dtypes).
        2. Allocate an output array of shape ``(n_hours, ny, nx)`` for each
           variable (initialised to ``NaN``).
        3. For each unique year in *year_map*:
           - Load only the cells belonging to that year via index arrays.
           - Fill the corresponding columns of the output array.
        4. Write the assembled arrays to NetCDF with zlib compression.

        Parameters
        ----------
        year_map : np.ndarray
            Shape ``(ny, nx)``.  Representative year for each cell.
        all_years : list[int]
            All years in the analysis period (for metadata).
        percentile : float
            Percentile level (0–1) recorded in file global attributes.
        output_path : Path
            Destination NetCDF file.

        Returns
        -------
        Path
            *output_path* after writing.
        """
        import xarray as xr
        import numpy as np

        n_hours = self.standard_time_hours()
        unique_years = sorted(
            int(y) for y in np.unique(year_map) if y != -9999
        )

        if not unique_years:
            raise RuntimeError("year_map contains no valid years (all −9999).")

        # ── Probe first year for grid metadata ────────────────────────
        with self.load_annual_dataset(unique_years[0]) as ds_ref:
            data_vars: list[str] = [
                str(v) for v in ds_ref.data_vars
            ]
            # Detect spatial dimension names (rlat/rlon or y/x)
            time_dim = "time"
            spatial_dims = [d for d in ds_ref.dims if d != time_dim]
            ny = ds_ref.dims[spatial_dims[0]]
            nx = ds_ref.dims[spatial_dims[1]]
            # Preserve static coordinates
            static_coords = {
                k: v.values
                for k, v in ds_ref.coords.items()
                if time_dim not in ds_ref[k].dims
            }
            spatial_dim_names = spatial_dims
            # Store variable attributes for later copy
            var_attrs = {v: dict(ds_ref[v].attrs) for v in data_vars}
            # Build a generic output time axis (hour 0 … n_hours-1)
            time_coords = np.arange(n_hours, dtype=np.int32)

        # ── Allocate output buffers ────────────────────────────────────
        #   shape: (n_hours, ny, nx) per variable
        buffers: dict[str, np.ndarray] = {
            v: np.full((n_hours, ny, nx), np.nan, dtype=np.float32)
            for v in data_vars
        }

        # ── Fill buffers year-by-year ──────────────────────────────────
        for year in unique_years:
            mask = year_map == year
            ys, xs = np.where(mask)   # row/col indices of cells for this year
            n_cells = len(ys)
            if n_cells == 0:
                continue

            logger.info(
                "  Mosaic P%02d: year %d  (%d cells)",
                int(round(percentile * 100)), year, n_cells,
            )
            with self.load_annual_dataset(year) as ds:
                # Trim or pad to standard time length
                t_len = min(ds.dims[time_dim], n_hours)
                for v in data_vars:
                    # Use .values to avoid dask overhead on fancy indexing
                    src = ds[v].isel(
                        {time_dim: slice(0, t_len)}
                    ).values  # (t_len, ny, nx)
                    buffers[v][:t_len, ys, xs] = src[:, ys, xs]

        # ── Assemble output Dataset ────────────────────────────────────
        coords: dict = {
            time_dim: (time_dim, time_coords, {
                "long_name": "hours since start of representative year",
                "units": "hours",
            }),
        }
        coords.update({
            k: (spatial_dim_names, v) if v.ndim == 2
            else (spatial_dim_names[0] if v.ndim == 1 else (), v)
            for k, v in static_coords.items()
        })

        data_dict: dict = {
            v: (
                (time_dim, spatial_dim_names[0], spatial_dim_names[1]),
                buffers[v],
                var_attrs.get(v, {}),
            )
            for v in data_vars
        }
        # Add source_year provenance variable
        data_dict["source_year"] = (
            spatial_dim_names,
            year_map.astype(np.int32),
            {
                "long_name": (
                    f"Calendar year selected as P"
                    f"{int(round(percentile*100)):02d} representative"
                ),
                "units": "year",
                "valid_range": [min(all_years), max(all_years)],
                "_FillValue": np.int32(-9999),
            },
        )

        ds_out = xr.Dataset(data_dict, coords=coords)
        ds_out.attrs.update({
            "title": (
                f"Percentile P{int(round(percentile*100)):02d} "
                "representative year weather file"
            ),
            "percentile_level": float(percentile),
            "analysis_years": f"{min(all_years)}-{max(all_years)}",
            "n_analysis_years": len(all_years),
            "standard_time_hours": n_hours,
            "Conventions": "CF-1.8",
        })

        # ── Write with zlib compression ────────────────────────────────
        enc: dict = {}
        for v in data_vars:
            enc[v] = {"zlib": True, "complevel": 1, "dtype": "float32"}
        enc["source_year"] = {"zlib": True, "complevel": 1, "dtype": "int32"}

        logger.info(
            "  Writing P%02d \u2192 %s",
            int(round(percentile * 100)), output_path.name,
        )
        ds_out.to_netcdf(str(output_path), encoding=enc, format="NETCDF4")
        mb = output_path.stat().st_size / (1024 * 1024)
        logger.info(
            "  P%02d written: %.0f MB", int(round(percentile * 100)), mb,
        )
        return output_path
