"""ERA5-Land percentile indexer - pure CPU/numpy implementation.

Mirrors ``cosmo_rea6.percentile_index`` (the KS-distance method actually in
production there; the older ``BasePercentileAnalyzer``/``percentile.py``
approach was superseded and removed). Derives P10, P50, and P90
representative-year mosaics for every grid cell across the ERA5-Land
Europe-crop grid using the Finkelstein-Schafer (FH) KS-distance method
applied to monthly GHI.

Pipeline
--------
1. Load   : monthly NetCDF files (``ERA5_LAND_<YYYY>_<MM>_all_attrs.nc``)
            read in parallel. Daily GHI sums extracted; leap days removed.
2. KS     : For each month and cell, identify the year whose empirical
            GHI CDF most closely matches the pooled P10/P50/P90
            threshold (minimum absolute KS distance). Pure numpy.
3. Mosaic : Spawn workers write 36 output NetCDF files (12 months x
            3 percentiles). Each worker opens one source file at a
            time and copies all variables for winning cells.

Differences from COSMO
-----------------------
- Grid size (``n_y``/``n_lon``) is inferred from the first loaded file
  rather than hardcoded (COSMO's 824x848 does not apply to the ERA5-Land
  Europe crop; the exact shape depends on ``ERA5_AREA``).
- Source/target directories default to ``EnvSettings``-resolved paths
  (``era5_output_dir``), not hardcoded ``/data/soma`` paths.
- Filename pattern is ``ERA5_LAND_<YYYY>_<MM>_all_attrs.nc``.
- Boundary repair MUST have run first (see ``repair_month_boundaries.py``)
  — an unrepaired first stamp would corrupt the January daily GHI sum.

Run with ``--clean`` to remove existing output before re-running.
Existing valid output files are skipped automatically.
"""

from __future__ import annotations

import argparse
import contextlib
import glob
import logging
import os
import re
import shutil
import tempfile
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import (
    ProcessPoolExecutor,
    as_completed,
)

import numpy as np
import xarray as xr

# Disable HDF5 file locking globally.  On NFS/GPFS file
# systems, .lock files left by a killed process cause the
# next open_dataset call to hang indefinitely.
os.environ["HDF5_USE_FILE_LOCKING"] = "FALSE"

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional Numba acceleration
# Set WEATHER_USE_NUMBA_KS=1 to enable the Numba path in _compute_ks_for_month
# ---------------------------------------------------------------------------
try:
    from numba import njit, prange  # type: ignore[import]
    NUMBA_AVAILABLE: bool = True
except Exception:  # noqa: BLE001
    NUMBA_AVAILABLE = False


if NUMBA_AVAILABLE:
    @njit(parallel=True, cache=True)  # type: ignore[misc]
    def _numba_ks_month(
        stacked: np.ndarray,
        val_p10: np.ndarray,
        val_p50: np.ndarray,
        val_p90: np.ndarray,
    ) -> tuple:
        """Compute per-cell KS argmin via a Numba parallel loop.

        Parameters
        ----------
        stacked : np.ndarray, shape (Y, T, R, L), float32
            Daily GHI sums for all years, days, rows, and columns.
        val_p10 : np.ndarray, shape (R, L), float32
            Global P10 threshold per grid cell.
        val_p50 : np.ndarray, shape (R, L), float32
            Global P50 threshold per grid cell.
        val_p90 : np.ndarray, shape (R, L), float32
            Global P90 threshold per grid cell.

        Returns
        -------
        tuple of three np.ndarray, each shape (R, L), int32
            Best-year index arrays for P10, P50, and P90.
        """
        n_years, _n_t, rows, cols = stacked.shape
        best_p10 = np.zeros((rows, cols), dtype=np.int32)
        best_p50 = np.zeros((rows, cols), dtype=np.int32)
        best_p90 = np.zeros((rows, cols), dtype=np.int32)

        for r in prange(rows):  # type: ignore[attr-defined]  # noqa: E741
            for c in range(cols):
                v10 = val_p10[r, c]
                v50 = val_p50[r, c]
                v90 = val_p90[r, c]
                best_d10 = np.float32(1e9)
                best_d50 = np.float32(1e9)
                best_d90 = np.float32(1e9)
                for y in range(n_years):
                    ys = np.sort(stacked[y, :, r, c])
                    ny = len(ys)
                    d10 = abs(
                        np.searchsorted(ys, v10) / ny - np.float32(0.10)
                    )
                    d50 = abs(
                        np.searchsorted(ys, v50) / ny - np.float32(0.50)
                    )
                    d90 = abs(
                        np.searchsorted(ys, v90) / ny - np.float32(0.90)
                    )
                    if d10 < best_d10:
                        best_d10 = d10
                        best_p10[r, c] = y
                    if d50 < best_d50:
                        best_d50 = d50
                        best_p50[r, c] = y
                    if d90 < best_d90:
                        best_d90 = d90
                        best_p90[r, c] = y

        return best_p10, best_p50, best_p90


# ---------------------------------------------------------------------------
# Top-level worker functions
#
# These MUST be defined at module top level (not nested inside a class or
# another function) so that ProcessPoolExecutor with the ``spawn`` start
# method can locate and import them in child processes.  Nesting them
# would make them unpicklable and cause immediate BrokenProcessPool errors.
# ---------------------------------------------------------------------------

_FILENAME_RE = re.compile(r"ERA5_LAND_(\d{4})_(\d{2})_")


def _preprocess_single_file(file_path: str) -> dict:
    """Load one NetCDF file and return day-summed GHI without leap days.

    Parameters
    ----------
    file_path : str
        Absolute path to an ERA5-Land NetCDF file.  The filename must
        contain an ``ERA5_LAND_YYYY_MM_`` segment used to extract year
        and month.

    Returns
    -------
    dict
        On success: keys ``path``, ``year``, ``month``, ``data``
        (numpy array of daily GHI sums, shape ``(days, y, x)``),
        and ``success=True``.
        On failure: keys ``path``, ``success=False``, ``error`` (str).
    """
    try:
        filename = os.path.basename(file_path)
        match = _FILENAME_RE.search(filename)
        if match is None:
            raise ValueError(
                f"Filename does not match expected pattern: {filename}"
            )
        year = int(match.group(1))
        month = int(match.group(2))

        with xr.open_dataset(file_path, engine="netcdf4") as ds:
            if "GHI" not in ds.data_vars:
                raise KeyError(f"Missing 'GHI' variable in {filename}")
            leap_mask = (
                (ds.time.dt.month == 2) & (ds.time.dt.day == 29)
            )
            ghi = ds["GHI"].isel(time=~leap_mask).load()

        daily_sum = (
            ghi.resample(time="1D").sum(dim="time").values
        )
        return {
            "path": file_path,
            "year": year,
            "month": month,
            "data": daily_sum,
            "shape": daily_sum.shape[1:],
            "success": True,
        }
    except Exception as exc:
        return {
            "path": file_path,
            "success": False,
            "error": str(exc),
        }


def _build_month_mosaic(args: tuple) -> str:
    """Build and write P10/P50/P90 NetCDF mosaics for one month.

    Design
    ------
    The KS phase identifies the best source year per grid cell using
    GHI only.  The mosaic phase then copies **all variables** from that
    winning year into the output — GHI is not special here, every
    variable in the source file is carried across.

    The key insight that makes this efficient: once we know which year
    wins each cell for P10/P50/P90, we open **each source file exactly
    once** and write every variable and all three percentiles in a
    single pass.  We never loop over variables as an outer loop, and
    we never re-open the same file more than once.

    Outer loop  : years (one file open per iteration)
    Inner work  : read all variables at once, scatter-write winning
                  cells into all three percentile mosaics simultaneously

    This is safe to call from a spawned worker process because this
    module imports no CUDA/GPU libraries at module level.

    Parameters
    ----------
    args : tuple
        A four-element tuple ``(month_idx, spatial_index_maps,
        file_path_lookup, target_dir)`` where:

        - ``month_idx`` (int): month number 1-12.
        - ``spatial_index_maps`` (dict): maps keys like ``"P10_01"``
          to ``(y, x)`` int32 arrays of best source years.
        - ``file_path_lookup`` (dict): maps ``(year, month)`` tuples
          to NetCDF file paths.
        - ``target_dir`` (str): directory to write output files.

    Returns
    -------
    str
        Status message, e.g. ``"Month 01: OK"`` or a skip reason.
    """
    (
        month_idx,
        spatial_index_maps,
        file_path_lookup,
        target_dir,
    ) = args

    log = logging.getLogger(__name__)
    month_str = f"{month_idx:02d}"

    # Ensure HDF5 locking is disabled inside the spawn worker too.
    # The env var set at module level is not always inherited.
    os.environ["HDF5_USE_FILE_LOCKING"] = "FALSE"

    # ── Clean up stale HDF5 lock files ─────────────────────────
    # HDF5 creates <file>.nc.lock when a writer opens a file and
    # removes it on clean close.  Ctrl+C or SIGKILL leaves them
    # behind, causing the next open_dataset to block forever.
    for _pct in ("p10", "p50", "p90"):
        _lock = os.path.join(
            target_dir,
            f"era5_land_{_pct}_{month_str}_all_attrs.nc.lock",
        )
        if os.path.exists(_lock):
            log.warning(
                "Month %s: removing stale lock file %s",
                month_str, os.path.basename(_lock),
            )
            try:
                os.remove(_lock)
            except OSError as _le:
                log.warning(
                    "Month %s: could not remove lock: %s",
                    month_str, _le,
                )

    # ── Skip if all output files exist and are valid ───────────
    # A file < 1 MB is almost certainly a partial write from an
    # interrupted run.  Remove it and regenerate.
    _min_bytes = 1 * 1024 * 1024
    expected_files = [
        os.path.join(
            target_dir,
            f"era5_land_{pct.lower()}_{month_str}_all_attrs.nc",
        )
        for pct in ("P10", "P50", "P90")
    ]
    if all(os.path.exists(f) for f in expected_files):
        small = [
            f for f in expected_files
            if os.path.getsize(f) < _min_bytes
        ]
        if small:
            log.warning(
                "Month %s: partial write detected (%d file(s)"
                " < 1 MB) — removing and regenerating",
                month_str, len(small),
            )
            for f in small:
                os.remove(f)
        else:
            try:
                for f in expected_files:
                    with xr.open_dataset(f, engine="netcdf4") as _chk:
                        _ = _chk.sizes
                log.info(
                    "Month %s: all output files valid, skipping",
                    month_str,
                )
                return (
                    f"Month {month_str}: skipped (already done)"
                )
            except Exception as _e:
                log.warning(
                    "Month %s: output files corrupt (%s)"
                    " — regenerating",
                    month_str, _e,
                )
                for f in expected_files:
                    if os.path.exists(f):
                        os.remove(f)

    # All unique years that appear as winners in any percentile map
    sorted_years: list[int] = sorted({
        int(y)
        for pct in ("P10", "P50", "P90")
        for key in (f"{pct}_{month_str}",)
        if key in spatial_index_maps
        for y in np.unique(spatial_index_maps[key])
    })
    if not sorted_years:
        return f"Month {month_str}: skipped (no spatial maps)"

    year_to_idx: dict[int, int] = {
        y: i for i, y in enumerate(sorted_years)
    }

    # Per-percentile (R, L) arrays: local year index that wins each cell
    pct_y_idx: dict[str, np.ndarray] = {
        pct: np.vectorize(year_to_idx.__getitem__)(
            spatial_index_maps[f"{pct}_{month_str}"]
        ).astype(np.intp)
        for pct in ("P10", "P50", "P90")
    }

    # Pre-compute winning cell coordinates per (percentile, year) so
    # the inner loop does no repeated boolean operations.
    # pct_winners[(pct, local_yi)] = (row_indices, col_indices)
    pct_winners: dict[tuple, tuple] = {}
    for pct in ("P10", "P50", "P90"):
        for local_yi in range(len(sorted_years)):
            wr, wl = np.where(pct_y_idx[pct] == local_yi)
            if wr.size > 0:
                pct_winners[(pct, local_yi)] = (wr, wl)

    # Scan all years to find a reference file that contains 3-D
    # (time, y, x) variables.
    spatial_dims = {"y", "x"}
    ref_fp: str | None = None
    var_names: list[str] = []
    var_dims: dict[str, tuple] = {}
    var_attrs: dict[str, dict] = {}
    ref_coords = None
    ref_attrs: dict = {}
    t_size: int = 0

    for year in sorted_years:
        fp = file_path_lookup.get((year, month_idx))
        if not fp or not os.path.exists(fp):
            continue
        with xr.open_dataset(fp, engine="netcdf4") as _ref_ds:
            leap = (
                (_ref_ds.time.dt.month == 2)
                & (_ref_ds.time.dt.day == 29)
            )
            _ref_filt = _ref_ds.isel(time=~leap)
            _candidates: list[str] = [
                str(v) for v in _ref_filt.data_vars
                if (
                    set(_ref_filt[v].dims) >= spatial_dims
                    and "time" in _ref_filt[v].dims
                    and _ref_filt[v].ndim == 3
                )
            ]
            if not _candidates:
                log.warning(
                    "Month %s year %d: no 3-D variables in %s,"
                    " trying next year",
                    month_str, year, fp,
                )
                continue
            # Found a usable reference file
            ref_fp = fp
            var_names = _candidates
            var_dims = {
                v: _ref_filt[v].dims for v in var_names
            }
            var_attrs = {
                v: dict(_ref_filt[v].attrs) for v in var_names
            }
            # Materialise coords before the dataset closes
            ref_coords = {
                k: _ref_filt.coords[k].values
                for k in _ref_filt.coords
            }
            ref_attrs = dict(_ref_filt.attrs)
            t_size = _ref_filt.sizes.get("time", 0)
        break  # stop after first usable year

    if ref_fp is None or not var_names:
        return (
            f"Month {month_str}: failed"
            f" (no year had 3-D variables)"
        )

    sample_map = spatial_index_maps[f"P10_{month_str}"]
    n_y, n_x = sample_map.shape

    # Output mosaics: {pct: {var: (T, R, L) float32 array}}
    # Initialised to NaN; only winning cells are written.
    mosaics: dict[str, dict[str, np.ndarray]] = {
        pct: {
            v: np.full(
                (t_size, n_y, n_x),
                np.nan,
                dtype=np.float32,
            )
            for v in var_names
        }
        for pct in ("P10", "P50", "P90")
    }

    # ── Main loop: one file open per year ───────────────────────────
    for local_yi, year in enumerate(sorted_years):
        # Check whether this year wins any cell in any percentile
        has_winners = any(
            (pct, local_yi) in pct_winners
            for pct in ("P10", "P50", "P90")
        )
        if not has_winners:
            continue

        fp = file_path_lookup.get((year, month_idx))
        if fp is None or not os.path.exists(fp):
            log.warning(
                "Month %s year %d: file not found, skipping",
                month_str, year,
            )
            continue

        # Open file once; read all variables in one pass
        with xr.open_dataset(fp, engine="netcdf4") as ds:
            leap = (
                (ds.time.dt.month == 2) & (ds.time.dt.day == 29)
            )
            ds_filt = ds.isel(time=~leap)
            year_vars: dict[str, np.ndarray] = {
                v: ds_filt[v].values.astype(np.float32)
                for v in var_names
                if v in ds_filt.data_vars
                and ds_filt[v].ndim == 3
            }

        actual_t = next(iter(year_vars.values())).shape[0]

        # Write winning cells for every percentile simultaneously
        for pct in ("P10", "P50", "P90"):
            key = (pct, local_yi)
            if key not in pct_winners:
                continue
            wr, wl = pct_winners[key]
            for v, year_data in year_vars.items():
                mosaics[pct][v][:actual_t, wr, wl] = (
                    year_data[:actual_t, wr, wl]
                )

        del year_vars

    # ── Write output files ──────────────────────────────────────────
    # Write to a local temp directory first to avoid NFS locking, then
    # move to the (possibly NFS) target atomically.
    os.makedirs(target_dir, exist_ok=True)
    saved: list[str] = []

    tmp_root = tempfile.mkdtemp(prefix=f"era5_land_m{month_str}_")
    try:
        for pct in ("P10", "P50", "P90"):
            map_key = f"{pct}_{month_str}"
            out_ds = xr.Dataset(coords=ref_coords, attrs=ref_attrs)
            for v in var_names:
                out_ds[v] = (
                    var_dims[v], mosaics[pct][v], var_attrs[v]
                )
            out_ds["source_year"] = (
                ["y", "x"],
                spatial_index_maps[map_key].astype(np.int32),
                {"description": "Source year for this percentile"},
            )
            enc = {
                vn: {
                    "zlib": True,
                    "complevel": 1,
                    "dtype": (
                        "int32" if vn == "source_year"
                        else "float32"
                    ),
                }
                for vn in out_ds.data_vars
            }
            fname = (
                f"era5_land_{pct.lower()}"
                f"_{month_str}_all_attrs.nc"
            )
            tmp_path = os.path.join(tmp_root, fname)
            out_ds.to_netcdf(
                tmp_path,
                encoding=enc,
                engine="netcdf4",
                format="NETCDF4",
            )
            out_ds.close()
            final_path = os.path.join(target_dir, fname)
            shutil.move(tmp_path, final_path)
            saved.append(fname)
    finally:
        # Always remove the local temp dir, even on error
        shutil.rmtree(tmp_root, ignore_errors=True)

    log.info(
        "Month %s done: %s", month_str, ", ".join(saved)
    )
    return f"Month {month_str}: OK"


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

class Era5LandPercentileIndexer:
    """Create monthly P10/P50/P90 mosaics from historical ERA5-Land data.

    The pipeline has three sequential phases:

    1. **Load** (``compile_historical_baselines``): read all input
       NetCDF files (``ERA5_LAND_<YYYY>_<MM>_all_attrs.nc``) in parallel
       using up to ``n_cpu_cores`` workers, extract day-summed GHI, and
       organise results by month and year.

    2. **KS match** (``_compute_ks_for_month``): for each of the 12
       months, find the year whose empirical GHI distribution best
       matches the pooled P10, P50, and P90 thresholds via minimum
       Kolmogorov-Smirnov distance.  Runs in pure vectorised numpy.

    3. **Mosaic** (``construct_and_save_mosaics``): for each month and
       percentile, assemble the best-year hourly data into a spatial
       mosaic and write it to a compressed NetCDF file.  Uses spawned
       worker processes to parallelise across months.

    Straggler-hiding optimisation: the load phase fires the KS callback
    for each month as soon as its last file arrives, so KS work for
    completed months overlaps with the tail of the I/O phase rather
    than waiting for all files.

    Parameters
    ----------
    source_dir : str
        Directory containing input ERA5-Land NetCDF files.  Files must
        match the pattern ``ERA5_LAND_YYYY_MM_*.nc``.
    target_dir : str
        Directory where output percentile NetCDF files are written.
    n_cpu_cores : int, optional
        Number of parallel workers for the file-loading phase.  ERA5-Land
        processing is I/O-bound (unlike COSMO's CPU-bound bz2 decompress),
        so this defaults to 6 to match ``ERA5_NCORES`` rather than COSMO's
        94-core CPU-bound default.
    n_y, n_lon : int, optional
        Grid dimensions.  If ``None`` (default), inferred from the first
        successfully loaded source file — the ERA5-Land Europe-crop grid
        size depends on ``ERA5_AREA`` and should not be hardcoded.
    n_mosaic_workers : int, optional
        Number of parallel workers for the mosaic-writing phase.
        Default: 2.
    """

    def __init__(
        self,
        source_dir: str,
        target_dir: str,
        n_cpu_cores: int = 6,
        n_y: int | None = None,
        n_lon: int | None = None,
        n_mosaic_workers: int = 2,
    ) -> None:
        self.source_dir = source_dir
        self.target_dir = target_dir
        self.n_cpu_cores = n_cpu_cores
        self.n_y = n_y
        self.n_lon = n_lon
        self.n_mosaic_workers = n_mosaic_workers

    # ------------------------------------------------------------------
    # Phase 1: parallel file loading
    # ------------------------------------------------------------------

    def compile_historical_baselines(
        self,
        file_paths: list,
        files_per_month: dict | None = None,
        on_month_ready: Callable | None = None,
    ) -> tuple:
        """Load all NetCDF files in parallel and group by month and year.

        When ``files_per_month`` and ``on_month_ready`` are both
        supplied, the callback is invoked on the main thread the moment
        every file for a given month has been loaded.  This lets KS
        work begin on finished months while the worker pool is still
        processing the remaining (straggler) files.

        Parameters
        ----------
        file_paths : list of str
            Sorted list of absolute paths to input NetCDF files.
        files_per_month : dict, optional
            Mapping ``{month: expected_file_count}`` pre-computed from
            filenames.  Required to trigger ``on_month_ready``.
        on_month_ready : callable, optional
            Function with signature
            ``(month: int, registry: dict, lookup: dict) -> None``
            called as soon as all files for ``month`` are loaded.

        Returns
        -------
        tuple
            A pair ``(monthly_registry, file_path_lookup)`` where:

            - ``monthly_registry`` is
              ``dict[int, dict[int, np.ndarray]]`` mapping
              ``month -> year -> daily_GHI_array``.
            - ``file_path_lookup`` is ``dict[(year, month), str]``
              mapping year/month pairs to their source file paths.
        """
        total = len(file_paths)
        logger.info(
            "Loading %d files with %d workers",
            total,
            self.n_cpu_cores,
        )

        monthly_registry: dict = {m: {} for m in range(1, 13)}
        file_path_lookup: dict = {}
        month_counts: dict = defaultdict(int)

        with ProcessPoolExecutor(
            max_workers=self.n_cpu_cores
        ) as pool:
            futures = {
                pool.submit(_preprocess_single_file, p): p
                for p in file_paths
            }

            for done_idx, fut in enumerate(
                as_completed(futures), 1
            ):
                try:
                    result = fut.result()
                except Exception as exc:
                    logger.error(
                        "Worker exception for %s: %s",
                        futures[fut],
                        exc,
                    )
                    if done_idx % 40 == 0 or done_idx == total:
                        logger.info(
                            "Progress: [%d/%d] (%.1f%%)",
                            done_idx,
                            total,
                            done_idx / total * 100,
                        )
                    continue

                if result["success"]:
                    month = result["month"]
                    year = result["year"]
                    monthly_registry[month][year] = result["data"]
                    file_path_lookup[(year, month)] = result["path"]
                    month_counts[month] += 1

                    if self.n_y is None or self.n_lon is None:
                        self.n_y, self.n_lon = result["shape"]

                    expected = (
                        files_per_month.get(month, -1)
                        if files_per_month is not None
                        else -1
                    )
                    if (
                        on_month_ready is not None
                        and month_counts[month] == expected
                    ):
                        logger.info(
                            "Month %02d ready - starting KS",
                            month,
                        )
                        on_month_ready(
                            month,
                            monthly_registry,
                            file_path_lookup,
                        )
                else:
                    logger.error(
                        "Failed: %s: %s",
                        result["path"],
                        result.get("error"),
                    )

                if done_idx % 40 == 0 or done_idx == total:
                    logger.info(
                        "Progress: [%d/%d] (%.1f%%)",
                        done_idx,
                        total,
                        done_idx / total * 100,
                    )

        return monthly_registry, file_path_lookup

    # ------------------------------------------------------------------
    # Phase 2: KS distribution matching
    # ------------------------------------------------------------------

    def _compute_ks_for_month(
        self,
        month: int,
        monthly_registry: dict,
    ) -> dict:
        """Run KS distribution matching for one month.

        For each grid cell, finds the year whose empirical CDF of
        daily GHI sums most closely matches the pooled P10, P50, and
        P90 thresholds (minimum absolute KS distance).

        Parameters
        ----------
        month : int
            Month number 1-12.
        monthly_registry : dict
            Nested dict ``{month: {year: daily_GHI_array}}``.

        Returns
        -------
        dict
            Keys ``"P10_MM"``, ``"P50_MM"``, ``"P90_MM"`` (where
            ``MM`` is the zero-padded month) each mapping to a
            ``(y, x)`` int32 array of best-source-year values.
            Returns an empty dict if no data is available for the month.
        """
        available_years = sorted(monthly_registry[month].keys())
        n_years = len(available_years)
        if n_years == 0:
            return {}

        if self.n_y is None or self.n_lon is None:
            self.n_y, self.n_lon = (
                monthly_registry[month][available_years[0]].shape[1:]
            )

        max_days = max(
            monthly_registry[month][y].shape[0]
            for y in available_years
        )

        stacked = np.zeros(
            (n_years, max_days, self.n_y, self.n_lon),
            dtype=np.float32,
        )
        for yi, y in enumerate(available_years):
            n_days = monthly_registry[month][y].shape[0]
            stacked[yi, :n_days] = monthly_registry[month][y]

        # Global pooled CDF thresholds: shape (R, L)
        pooled_sorted = np.sort(
            stacked.reshape(
                n_years * max_days, self.n_y, self.n_lon
            ),
            axis=0,
        )
        n_pool = pooled_sorted.shape[0]
        val_p10 = pooled_sorted[int(n_pool * 0.10)]
        val_p50 = pooled_sorted[int(n_pool * 0.50)]
        val_p90 = pooled_sorted[int(n_pool * 0.90)]
        del pooled_sorted

        use_numba = (
            NUMBA_AVAILABLE
            and os.getenv("WEATHER_USE_NUMBA_KS", "0") == "1"
        )
        if use_numba:
            best_p10, best_p50, best_p90 = _numba_ks_month(
                stacked, val_p10, val_p50, val_p90
            )
        else:
            # Per-year CDF fraction: what share of a year's days
            # fall at or below each global threshold?
            # sorted_years shape: (Y, T, R, L)
            sorted_years = np.sort(stacked, axis=1)

            # cdf shape: (Y, R, L)
            cdf_p10 = (
                np.sum(
                    sorted_years <= val_p10[None, None],
                    axis=1,
                ).astype(np.float32)
                / max_days
            )
            cdf_p50 = (
                np.sum(
                    sorted_years <= val_p50[None, None],
                    axis=1,
                ).astype(np.float32)
                / max_days
            )
            cdf_p90 = (
                np.sum(
                    sorted_years <= val_p90[None, None],
                    axis=1,
                ).astype(np.float32)
                / max_days
            )
            del sorted_years

            best_p10 = np.argmin(
                np.abs(cdf_p10 - 0.10), axis=0
            ).astype(np.int32)
            best_p50 = np.argmin(
                np.abs(cdf_p50 - 0.50), axis=0
            ).astype(np.int32)
            best_p90 = np.argmin(
                np.abs(cdf_p90 - 0.90), axis=0
            ).astype(np.int32)
            del cdf_p10, cdf_p50, cdf_p90

        year_arr = np.array(available_years, dtype=np.int32)
        tag = f"{month:02d}"
        logger.info(
            "Month %s KS done (P10 %d unique years, "
            "P50 %d, P90 %d)",
            tag,
            len(np.unique(best_p10)),
            len(np.unique(best_p50)),
            len(np.unique(best_p90)),
        )
        return {
            f"P10_{tag}": year_arr[best_p10],
            f"P50_{tag}": year_arr[best_p50],
            f"P90_{tag}": year_arr[best_p90],
        }

    # ------------------------------------------------------------------
    # Phase 3: mosaic assembly
    # ------------------------------------------------------------------

    def construct_and_save_mosaics(
        self,
        spatial_index_maps: dict,
        file_path_lookup: dict,
    ) -> None:
        """Write 36 output NetCDF files (12 months x 3 percentiles).

        One job per month runs in a pool of ``n_mosaic_workers``
        spawned processes.  ``spawn`` gives each child a clean
        interpreter with no inherited file descriptors or shared state.

        This phase is I/O-bound: each month reads up to N source files.
        Keep ``n_mosaic_workers`` small (1-2) so the workers do not
        saturate NFS/network bandwidth and stall each other.  There is
        no per-job timeout; every month runs to completion.

        Output is written to local temp storage first, then moved to
        the target directory, avoiding NFS write locks and HDF5
        contention.

        Parameters
        ----------
        spatial_index_maps : dict
            Maps keys like ``"P10_01"`` to ``(y, x)`` int32 arrays
            of best-source-year values from ``_compute_ks_for_month``.
        file_path_lookup : dict
            Maps ``(year, month)`` tuples to source NetCDF file paths.
        """
        import multiprocessing

        logger.info("Assembling mosaics -> %s", self.target_dir)
        os.makedirs(self.target_dir, exist_ok=True)

        month_args = [
            (
                month_num,
                spatial_index_maps,
                file_path_lookup,
                self.target_dir,
            )
            for month_num in range(1, 13)
        ]

        ctx = multiprocessing.get_context("spawn")
        with ProcessPoolExecutor(
            max_workers=self.n_mosaic_workers, mp_context=ctx
        ) as pool:
            futures = {
                pool.submit(_build_month_mosaic, a): a[0]
                for a in month_args
            }
            for fut in as_completed(futures):
                month_num = futures[fut]
                try:
                    logger.info(fut.result())
                except Exception as exc:
                    logger.error(
                        "Month %02d failed: %s "
                        "(run with --month %d to retry)",
                        month_num, exc, month_num,
                    )

    # ------------------------------------------------------------------
    # Orchestration
    # ------------------------------------------------------------------

    def execute_indexing_pipeline(self) -> None:
        """Run all three pipeline phases with straggler-hiding overlap.

        Discovers input files, pre-counts files per month, then runs
        the load phase.  As each month's files complete, the KS phase
        starts immediately for that month rather than waiting for all
        files to finish (straggler hiding).  Finally runs the mosaic
        phase once all KS maps are ready.

        Raises
        ------
        FileNotFoundError
            If no ``.nc`` files are found in ``source_dir``.
        """
        file_paths = sorted(
            glob.glob(os.path.join(self.source_dir, "ERA5_LAND_*.nc"))
        )
        if not file_paths:
            raise FileNotFoundError(
                f"No ERA5_LAND_*.nc files found in {self.source_dir}"
            )

        # Check upfront whether all 36 output files exist and are
        # valid.  If so, skip the entire load + KS phases and go
        # straight to the mosaic phase, which will find each month
        # already done and return immediately.
        all_outputs = [
            os.path.join(
                self.target_dir,
                f"era5_land_{pct.lower()}_{m:02d}_all_attrs.nc",
            )
            for pct in ("P10", "P50", "P90")
            for m in range(1, 13)
        ]
        _min_bytes = 1 * 1024 * 1024  # 1 MB
        _existing = [f for f in all_outputs if os.path.exists(f)]
        _small = [
            f for f in _existing
            if os.path.getsize(f) < _min_bytes
        ]
        if _small:
            logger.warning(
                "%d output file(s) look like partial writes"
                " (< 1 MB) — will regenerate: %s",
                len(_small),
                [os.path.basename(f) for f in _small],
            )
            for f in _small:
                os.remove(f)
        elif len(_existing) == len(all_outputs):
            logger.info(
                "All 36 output files exist and appear valid."
                " Nothing to do."
            )
            return

        files_per_month: dict = defaultdict(int)
        for fp in file_paths:
            fname_match = _FILENAME_RE.search(os.path.basename(fp))
            if fname_match is None:
                continue
            files_per_month[int(fname_match.group(2))] += 1

        logger.info(
            "Found %d files; per-month counts: %s",
            len(file_paths),
            dict(sorted(files_per_month.items())),
        )

        spatial_index_maps: dict = {}
        processed_months: set = set()

        def _on_month_ready(
            month: int,
            monthly_registry: dict,
            _lookup: dict,
        ) -> None:
            """KS callback fired when a month's files are all loaded.

            Parameters
            ----------
            month : int
                Month number 1-12.
            monthly_registry : dict
                Current state of the registry (may still be growing
                for other months).
            _lookup : dict
                File-path lookup (unused here; KS only needs registry).
            """
            if month in processed_months:
                return
            processed_months.add(month)
            spatial_index_maps.update(
                self._compute_ks_for_month(month, monthly_registry)
            )

        monthly_registry, file_path_lookup = (
            self.compile_historical_baselines(
                file_paths,
                files_per_month=dict(files_per_month),
                on_month_ready=_on_month_ready,
            )
        )

        # Handle any months not processed via callback
        # (e.g. filename parse failures or count mismatches)
        remaining = [
            month_num
            for month_num in range(1, 13)
            if (
                month_num not in processed_months
                and monthly_registry[month_num]
            )
        ]
        if remaining:
            logger.info(
                "KS for remaining months: %s", remaining
            )
            for month_num in remaining:
                spatial_index_maps.update(
                    self._compute_ks_for_month(
                        month_num, monthly_registry
                    )
                )

        self.construct_and_save_mosaics(
            spatial_index_maps, file_path_lookup
        )
        logger.info("Pipeline complete - 36 output files written.")


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from ...settings import EnvSettings

    _parser = argparse.ArgumentParser(
        description="ERA5-Land percentile indexer",
    )
    _parser.add_argument(
        "--source-dir",
        default=None,
        help=(
            "Directory containing monthly ERA5_LAND_*.nc files."
            " Default: EnvSettings.era5_output_dir()"
        ),
    )
    _parser.add_argument(
        "--target-dir",
        default=None,
        help=(
            "Directory to write percentile output files."
            " Default: <source-dir>/percentile"
        ),
    )
    _parser.add_argument(
        "--clean",
        action="store_true",
        help=(
            "Remove all existing output files before running."
            " Use this to force a full re-run."
        ),
    )
    _parser.add_argument(
        "--month",
        type=int,
        action="append",
        dest="months",
        metavar="M",
        help=(
            "Force re-processing of month M (1-12), deleting"
            " any existing output for that month first."
            " Can be repeated: --month 2 --month 11"
        ),
    )
    _args = _parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s CET - %(levelname)s - %(message)s",
    )

    _log = logging.getLogger(__name__)
    _source = _args.source_dir or str(EnvSettings.era5_output_dir())
    _target = _args.target_dir or os.path.join(_source, "percentile")

    if _args.clean and os.path.exists(_target):
        _log.info(
            "--clean: removing existing output dir %s", _target
        )
        shutil.rmtree(_target)

    # --month: delete only the specified months' output files so
    # the skip-if-exists check forces them to be rebuilt.
    if _args.months:
        for _m in _args.months:
            if not 1 <= _m <= 12:
                _parser.error(
                    f"--month {_m} is out of range (1-12)"
                )
            for _pct in ("p10", "p50", "p90"):
                _f = os.path.join(
                    _target,
                    f"era5_land_{_pct}_{_m:02d}_all_attrs.nc",
                )
                if os.path.exists(_f):
                    os.remove(_f)
                    _log.info(
                        "--month %d: removed %s",
                        _m, os.path.basename(_f),
                    )

    # Clean stale HDF5 lock files from both source and output dirs.
    for _lock_dir in (_source, _target):
        if not os.path.exists(_lock_dir):
            continue
        _locks = [
            os.path.join(_lock_dir, f)
            for f in os.listdir(_lock_dir)
            if f.endswith(".lock")
        ]
        if _locks:
            _log.info(
                "Removing %d stale lock file(s) in %s",
                len(_locks), _lock_dir,
            )
            for _lf in _locks:
                with contextlib.suppress(OSError):
                    os.remove(_lf)

    indexer = Era5LandPercentileIndexer(
        source_dir=_source,
        target_dir=_target,
        n_cpu_cores=EnvSettings.era5_ncores(),
        n_mosaic_workers=2,
    )
    indexer.execute_indexing_pipeline()
