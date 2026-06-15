"""COSMO-REA6 Probability-of-Exceedance representative monthly files.

Default mode is **year-locked across months**: for each PoE level and cell,
one representative year is selected from annual GHI totals and reused for all
calendar months.

Optional mode (**independent months**) selects a separate representative year
for each month.

PoE convention (IEC 61724-1 / solar bankability standard)
---------------------------------------------------------
- **P90** (90 % exceedance) → low GHI, conservative / downside scenario
- **P50** (50 % exceedance) → median GHI, typical / expected scenario
- **P10** (10 % exceedance) → high GHI, optimistic / upside scenario

Output
------
For each (PoE level, calendar month) combination one NetCDF file is written.
With the default P10/P50/P90 and all 12 months this produces 36 files::

    COSMO_REA6_poe10_01_representative.nc  …  poe10_12_representative.nc
    COSMO_REA6_poe50_01_representative.nc  …  poe50_12_representative.nc
    COSMO_REA6_poe90_01_representative.nc  …  poe90_12_representative.nc

Files can be merged into annual composites afterwards if needed.

Key differences from ``CosmoPercentileAnalyzer``
-------------------------------------------------
+------------------------------+-----------------------------+
| Property                     | Old annual analyser         |
+==============================+=============================+
| Granularity                  | Annual (8760 h per year)    |
+------------------------------+-----------------------------+
| PoE P90 = ?                  | High GHI (ascending P90)    |
+------------------------------+-----------------------------+
| Requires annual merge?       | Yes (was slow, often failed)|
+------------------------------+-----------------------------+

+------------------------------+-----------------------------+
| Property                     | This PoE analyser           |
+==============================+=============================+
| Granularity                  | Year-locked across months   |
+------------------------------+-----------------------------+
| PoE P90 = ?                  | Low GHI (ascending P10) ✓   |
+------------------------------+-----------------------------+
| Requires annual merge?       | No — reads monthly NC files |
+------------------------------+-----------------------------+
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from weather.common.percentile_poe import select_representative_years_poe

logger = logging.getLogger(__name__)


class CosmoPoEAnalyzer:
    """PoE representative-file generator for COSMO-REA6.

    Parameters
    ----------
    output_dir : Path, optional
        Output directory.  Defaults to
        ``<cfg.output_dir>/percentile_poe``.
    ncores : int, optional
        Dask thread count.  Defaults to ``cfg["ncores"]``.
    """

    def __init__(
        self,
        output_dir: Path | None = None,
        ncores: int | None = None,
    ) -> None:
        from weather.providers.cosmo_rea6.config import get_config
        cfg = get_config()
        self._cfg = cfg
        self._ncores = ncores if ncores is not None else cfg["ncores"]
        self._output_dir = (
            output_dir
            if output_dir is not None
            else cfg["output_dir"] / "percentile_poe"
        )
        import dask
        dask.config.set(num_workers=self._ncores)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _monthly_nc_path(self, year: int, month: int) -> Path:
        """Return the path of the monthly output NC for *year*/*month*."""
        fname = f"COSMO_REA6_{year}_{month:02d}_all_attrs.nc"
        return Path(self._cfg["output_dir"]) / fname

    def check_inputs(
        self, years: list[int], months: list[int]
    ) -> None:
        """Raise FileNotFoundError if any required monthly NC is absent."""
        missing = []
        for year in years:
            for month in months:
                if not self._monthly_nc_path(year, month).exists():
                    missing.append(f"{year}-{month:02d}")
        if missing:
            n = len(missing)
            lines = "\n".join(f"  {m}" for m in missing[:10])
            tail = (
                f"\n  … and {n - 10} more" if n > 10 else ""
            )
            raise FileNotFoundError(
                f"Missing {n} monthly NC file(s):\n{lines}{tail}\n"
                "Run test_one_year.py (or test_multi_year.py) first."
            )

    def _load_monthly_ghi_sum(
        self, year: int, month: int
    ) -> np.ndarray:
        """Sum GHI over time for one monthly NC → shape ``(ny, nx)``."""
        import xarray as xr
        fpath = self._monthly_nc_path(year, month)
        with xr.open_dataset(
            str(fpath), engine="netcdf4", chunks="auto"
        ) as ds:
            return ds["GHI"].sum("time").values.astype(np.float32)

    def _build_metric_stack(
        self, years: list[int], month: int
    ) -> np.ndarray:
        """Build monthly GHI metric stack for one calendar month.

        Parameters
        ----------
        years : list[int]
        month : int  1–12

        Returns
        -------
        np.ndarray
            Shape ``(n_years, ny, nx)``.
        """
        slices = []
        for year in years:
            logger.info(
                "  Loading GHI metric: %d-%02d", year, month
            )
            slices.append(self._load_monthly_ghi_sum(year, month))
        return np.stack(slices, axis=0)

    def _build_annual_metric_stack(
        self,
        years: list[int],
        months: list[int],
    ) -> np.ndarray:
        """Build annual-equivalent GHI metric stack across selected months.

        For each year, sums monthly GHI totals over *months* and returns an
        array of shape ``(n_years, ny, nx)``.
        """
        slices = []
        for year in years:
            logger.info(
                "  Loading locked-year GHI metric: year %d", year
            )
            acc = None
            for month in months:
                m_sum = self._load_monthly_ghi_sum(year, month)
                if acc is None:
                    acc = m_sum
                else:
                    acc = acc + m_sum
            if acc is None:
                raise RuntimeError("No months provided for annual metric.")
            slices.append(acc.astype(np.float32))
        return np.stack(slices, axis=0)

    def _mosaic_month(
        self,
        year_map: np.ndarray,
        month: int,
        poe_level: float,
        all_years: list[int],
        output_path: Path,
    ) -> Path:
        """Write one (poe_level, month) representative NC file.

        For each unique year in *year_map*, copies the relevant spatial
        cells from that year's monthly NC into the output buffer.

        Parameters
        ----------
        year_map : np.ndarray
            Shape ``(ny, nx)`` int32. Representative year per cell.
        month : int
            Calendar month 1–12.
        poe_level : float
            PoE level (0–1).
        all_years : list[int]
            Full analysis period (for metadata).
        output_path : Path
            Destination NetCDF file.

        Returns
        -------
        Path
            *output_path* after writing.
        """
        import xarray as xr

        poe_int = int(round(poe_level * 100))
        unique_years = sorted(
            int(y) for y in np.unique(year_map) if y != -9999
        )
        if not unique_years:
            raise RuntimeError(
                f"year_map for PoE{poe_int} month {month:02d} "
                "contains no valid years."
            )

        # Probe first year for grid metadata
        with xr.open_dataset(
            str(self._monthly_nc_path(unique_years[0], month)),
            engine="netcdf4",
        ) as ds_ref:
            data_vars = [str(v) for v in ds_ref.data_vars]
            time_dim = "time"
            spatial_dims = [
                d for d in ds_ref.dims if d != time_dim
            ]
            ny = ds_ref.dims[spatial_dims[0]]
            nx = ds_ref.dims[spatial_dims[1]]
            n_t = ds_ref.dims[time_dim]
            static_coord_meta = []
            for key in ds_ref.coords:
                if time_dim in ds_ref[key].dims:
                    continue
                coord_dims = tuple(str(d) for d in ds_ref[key].dims)
                coord_vals = np.asarray(ds_ref[key].values)
                static_coord_meta.append(
                    (str(key), coord_dims, coord_vals)
                )
            var_attrs = {
                v: dict(ds_ref[v].attrs) for v in data_vars
            }
            time_values = ds_ref[time_dim].values

        # Allocate output buffers
        buffers: dict[str, np.ndarray] = {
            v: np.full((n_t, ny, nx), np.nan, dtype=np.float32)
            for v in data_vars
        }

        # Fill year by year (at most one annual NC in RAM at once)
        for year in unique_years:
            mask = year_map == year
            ys, xs = np.where(mask)
            if len(ys) == 0:
                continue
            logger.info(
                "  Mosaic PoE%d month %02d: year %d  (%d cells)",
                poe_int, month, year, len(ys),
            )
            with xr.open_dataset(
                str(self._monthly_nc_path(year, month)),
                engine="netcdf4",
                chunks="auto",
            ) as ds:
                t_len = min(ds.dims[time_dim], n_t)
                for v in data_vars:
                    src = ds[v].isel(
                        {time_dim: slice(0, t_len)}
                    ).values
                    buffers[v][:t_len, ys, xs] = src[:, ys, xs]

        # Assemble output Dataset
        coords: dict = {
            time_dim: (time_dim, time_values),
        }
        for key, coord_dims, coord_vals in static_coord_meta:
            coords[key] = (coord_dims, coord_vals)

        data_dict: dict = {
            v: (
                (time_dim, spatial_dims[0], spatial_dims[1]),
                buffers[v],
                var_attrs.get(v, {}),
            )
            for v in data_vars
        }
        data_dict["source_year"] = (
            spatial_dims,
            year_map.astype(np.int32),
            {
                "long_name": (
                    f"Calendar year selected as PoE P{poe_int:02d} "
                    f"representative for month {month:02d}"
                ),
                "units": "year",
                "valid_range": [min(all_years), max(all_years)],
                "_FillValue": np.int32(-9999),
            },
        )

        ds_out = xr.Dataset(data_dict, coords=coords)
        ds_out.attrs.update({
            "title": (
                f"PoE P{poe_int:02d} representative weather file "
                f"— month {month:02d}"
            ),
            "poe_level": float(poe_level),
            "calendar_month": month,
            "analysis_years": (
                f"{min(all_years)}-{max(all_years)}"
            ),
            "n_analysis_years": len(all_years),
            "ranking_metric": "monthly cumulative GHI (W·h/m²)",
            "selection_method": (
                "eCDF argmin-distance per cell (non-parametric)"
            ),
            "Conventions": "CF-1.8",
        })

        enc: dict = {}
        for v in data_vars:
            enc[v] = {
                "zlib": True, "complevel": 1, "dtype": "float32"
            }
        enc["source_year"] = {
            "zlib": True, "complevel": 1, "dtype": "int32"
        }

        output_path.parent.mkdir(parents=True, exist_ok=True)
        logger.info(
            "  Writing PoE%d-%02d → %s",
            poe_int, month, output_path.name,
        )
        ds_out.to_netcdf(
            str(output_path), encoding=enc, format="NETCDF4"
        )
        mb = output_path.stat().st_size / (1024 * 1024)
        logger.info(
            "  PoE%d-%02d written: %.0f MB", poe_int, month, mb,
        )
        return output_path

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        years: list[int] | range,
        poe_levels: list[float] | None = None,
        months: list[int] | None = None,
        lock_year_across_months: bool = True,
    ) -> dict[tuple[float, int], Path]:
        """Build all PoE representative monthly files.

        In default locked mode, one representative year per cell and PoE
        level is selected from annual-equivalent GHI totals and reused for
        all months.  In independent mode, each month selects its own year.

        Parameters
        ----------
        years : list[int] or range
            Full analysis period, e.g. ``range(1995, 2019)``.
        poe_levels : list[float], optional
            PoE levels as fractions.
            Defaults to ``[0.10, 0.50, 0.90]`` (P10/P50/P90).
        months : list[int], optional
            Calendar months 1–12.  Defaults to all 12.
        lock_year_across_months : bool, optional
            If ``True`` (default), enforce the same representative year for
            all months per cell and PoE level. If ``False``, select years
            independently per month.

        Returns
        -------
        dict[(float, int), Path]
            Maps ``(poe_level, month)`` to the written output file.
        """
        _poes = (
            poe_levels
            if poe_levels is not None
            else [0.10, 0.50, 0.90]
        )
        _months = (
            months
            if months is not None
            else list(range(1, 13))
        )
        _years = list(years)

        self.check_inputs(_years, _months)
        self._output_dir.mkdir(parents=True, exist_ok=True)

        out_paths: dict[tuple[float, int], Path] = {}

        locked_year_maps: dict[float, np.ndarray] | None = None
        if lock_year_across_months:
            logger.info("=" * 60)
            logger.info(
                "Locked-year mode: building annual-equivalent metric "
                "stack (%d years)",
                len(_years),
            )
            annual_stack = self._build_annual_metric_stack(
                _years, _months
            )
            locked_year_maps = select_representative_years_poe(
                annual_stack, _years, _poes
            )

        for month in _months:
            logger.info("=" * 60)
            if lock_year_across_months:
                logger.info(
                    "Month %02d — using locked-year map from annual "
                    "metric stack", month
                )
                year_maps = locked_year_maps or {}
            else:
                logger.info(
                    "Month %02d — building independent monthly GHI "
                    "metric stack (%d years)",
                    month, len(_years),
                )
                stack = self._build_metric_stack(_years, month)
                year_maps = select_representative_years_poe(
                    stack, _years, _poes
                )

            for poe, year_map in year_maps.items():
                poe_int = int(round(poe * 100))
                fname = (
                    f"COSMO_REA6_poe{poe_int:02d}_{month:02d}"
                    "_representative.nc"
                )
                out_path = self._output_dir / fname
                out_paths[(poe, month)] = self._mosaic_month(
                    year_map=year_map,
                    month=month,
                    poe_level=poe,
                    all_years=_years,
                    output_path=out_path,
                )

        return out_paths
