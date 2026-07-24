# MERRA-2 — completion status

**DONE.** Implementation complete following the ERA5-Land/COSMO-REA6
pattern (OPeNDAP access, 3 collections, monthly output, no decompress
phase). See `merra2_context.md` for the current engineering state and
`docs/MERRA2_PIPELINE_GUIDE.md` for the full user-facing guide (auth
setup, collection/attribute table, RH formula derivation, grid-alignment
caveat, running the pipeline).

## What was built

1. `Merra2DownloadJob(collection, year, month, day)` in `downloader.py`
   — per-day, per-collection granularity (sanctioned by
   `base_downloader.py`'s own docstring, which names MERRA-2 as the
   example provider needing a different job shape).
2. `downloader.py`: all 3 `BaseDownloader` stubs implemented — OPeNDAP
   constraint-URL construction (`_bbox_indices`/`build_url`),
   existence-based `remote_size` (always `None`, like ERA5-Land's CDS
   queue rationale), `_fetch` via an Earthdata-authenticated,
   redirect-safe session (`common.net.build_session(...,
   preserve_auth_hosts=...)`).
3. `download.py`: `download_all()` — one job per (collection, day),
   parallelized via `common.parallel.run_parallel`.
4. `transform.py`: merges rad+slv daily files -> monthly dataset; `T2M`
   K->degC; `GHI = SWGDN` direct (via the registry, `fields=["GHI"]`
   only — DHI/DNI deliberately NOT computed, see below); `WS_10M =
   sqrt(U10M**2+V10M**2)`; new specific-humidity RH formula
   (`_compute_rh`, Bolton 1980); dims renamed to `y`/`x` matching
   COSMO/ERA5-Land.
5. `export.py`/`pipeline.py`: near-verbatim ERA5-Land pattern (zlib
   complevel=1, float32; `ProcessPoolExecutor` per-month transform+
   export; no decompress phase).
6. `__init__.py`: `MERRA2Provider` completes the `WeatherProvider`
   protocol; `validate_environment()` reuses `common.net
   .earthdata_auth()`.
7. Test scripts: `test_merra2_one_month.py`, `test_merra2_one_year.py`,
   `test_merra2_multi_year.py` (mirror ERA5-Land's exactly, no
   `--night-mask` flag needed).

## Deliberate scope decisions (see docs/MERRA2_PIPELINE_GUIDE.md for why)

- **3 collections** (was 2 until a confirmed downstream consumer,
  github.com/THD-Spatial-AI/merra2-energy-pipeline, needed snow/hub-
  height-wind data): `M2T1NXRAD` (SWGDN + ALBEDO) + `M2T1NXSLV` (T2M,
  QV2M, U/V winds at 2/10/50 m, PS) + `M2T1NXLND` (SNODP,
  PRECSNOLAND). `build_monthly_dataset()`'s signature grew a
  `lnd_paths` third positional arg — a breaking change, the sole
  caller (`pipeline.py`) was updated. Not live-tested (verified against
  synthetic local NetCDF4 files only — no GES DISC download triggered).
- **GHI only in bulk** — DHI/DNI deferred to a future
  `merra2/dni_pointwise.py` (mirrors ERA5-Land's opt-in point-wise
  helper), since pvlib DIRINT can't broadcast over the full grid.
- **No cross-provider regridding** — same geographic Europe box as
  ERA5-Land, but MERRA-2's own native 0.5°x0.625° grid, not
  interpolated onto ERA5-Land's 0.1° grid.

## Live smoke test — 2018-03 (`data/merra2/`)

A single month has already been run against real GES DISC data:
`data/merra2/download/MERRA2_{rad,slv}_201803*.nc4` (31 daily files/
collection) -> `data/merra2/output/MERRA2_2018_03_all_attrs.nc` (744
hourly steps, `y=77, x=71`). Confirms:

- **Monthly output granularity works as designed.** Daily `.nc4`s stay
  in `download_dir`; only one merged monthly file lands in `output_dir`
  — there is no lingering per-day output bug. (`download.py`'s use of
  a separate `download_dir` vs `output_dir` in `config.py` already
  keeps these apart; no code change needed here.)
- **Day-boundary continuity checked and OK.** Time index is a clean,
  gap-free hourly sequence across all 30 within-month day boundaries
  (`np.diff` step size uniformly 60 min); per-variable hour-to-hour
  deltas at `23:30 -> 00:30` boundaries are the same order of magnitude
  as (often smaller than) ordinary hour-to-hour deltas elsewhere in the
  month, for every attribute (`PS`, `T2M`, `U/V10M`, `U/V2M`, `QV2M`,
  `WS_10M`, `RH`). `GHI` is exactly 0.0 on both sides of every boundary
  (night mask); `ALBEDO` is `NaN` on both sides (~47% of steps, all
  night hours — a genuine GES DISC raw-data characteristic, not a
  stitching artifact). No cross-month check yet (only 2018-03 has been
  run); redo this check after an annual run to confirm the Feb->Mar and
  Mar->Apr month-boundary transitions too.
- **Bug found + fixed: MERRA-2 output was NOT structurally on par with
  COSMO/ERA5-Land's global attrs.** `transform.py`'s `xr.merge(...,
  combine_attrs="override")` silently carried over one arbitrary daily
  source file's raw GES DISC global attrs (`Filename`, `GranuleID`,
  `RangeBeginningDate`/`RangeEndingDate` scoped to just that one day,
  OPeNDAP request-URL `history`, and a stale `'Conventions': 'CF-1'`)
  into the exported monthly file, because `ds.attrs.setdefault(...)`
  only fills in *missing* keys — it never overwrote these pre-existing
  raw ones. ERA5-Land's `transform.py` avoids this by explicitly
  stripping `GRIB_*`/per-var leftover attrs before finalizing; MERRA-2
  had no equivalent step. **Fixed**: `transform.py` now does
  `ds.attrs.clear()` before setting `provider`/`Conventions`/
  `grid_note`, so the exported global attrs are clean and match COSMO/
  ERA5-Land's convention (verified: re-running `build_monthly_dataset`
  on the existing 2018-03 daily files now yields exactly
  `{'provider': 'MERRA2', 'Conventions': 'CF-1.8', 'grid_note': ...}`).
  **The existing `data/merra2/output/MERRA2_2018_03_all_attrs.nc` was
  exported before this fix and still has the stale raw attrs — it
  should be regenerated** (`--skip-download --months 3`, no `--resume`,
  or delete the file first) before being used as a reference.
- **Structural comparison vs COSMO/ERA5-Land, otherwise**: same NetCDF-4
  format, float32 + zlib(complevel=1) encoding, `(time, y, x)` dims with
  `latitude`/`longitude` as coords — this part matches. Grid extents
  differ only because each provider keeps its own native resolution
  (MERRA-2 77x71 cells vs ERA5-Land 381x431 for the same Europe box) —
  expected, not a defect. Raw attribute names are kept as-is per
  provider (e.g. MERRA-2's `PS`/`QV2M`/`U10M` vs ERA5-Land's `sp`/`d2m`/
  `u10`), consistent with each provider's own `downloaded_attributes.py`
  DICT convention.
- **Datetime index does NOT align with COSMO/ERA5-Land, and this is
  expected, not a bug.** MERRA-2 `tavg1_2d` collections timestamp each
  hourly value at `HH:30` (verified: `2018-03-01T00:30`, `T01:30`, …),
  because SWGDN/T2M/etc. are true hourly *time-averages* labeled at
  the averaging-interval midpoint — unlike ERA5-Land, which timestamps
  on the hour (`T01:00`, `T02:00`, …). Shifting MERRA-2's index to
  `HH:00` to force alignment would mislabel the averaging window rather
  than fix a defect. Leave-as-is + document, since silently shifting
  timestamps would be more surprising
  than the current documented offset. **Decided (user, 2026-07-21):
  leave as-is, document only** — no relabeling/resample code added.
  See `docs/MERRA2_PIPELINE_GUIDE.md`'s "Timestamp convention" section
  and `transform.py`'s module docstring.

## Full-year 2018 verification (`verify_merra2_months.py`)

Added `src/weather/tests/verify_merra2_months.py` (mirrors `verify_months.py`
for ERA5-Land): checks hour counts, `HH:30` span, cross-month/cross-year
continuity, aggregated NaN%/min-max vs plausible ranges, and a
multi-month point profile (`--lat/--lon --start/--end`). Findings from
running it against `data/merra2/2018` (all 12 months):

- **Month-to-month continuity: OK for all 12 boundaries.** Every file
  has exactly `24 x days_in_month` steps, spans `<1st> 00:30 .. <last>
  23:30`, and the last stamp of month N is exactly 1h before the first
  stamp of month N+1 (checked Jan->Feb ... Nov->Dec, including the
  Feb 28 -> Mar 1 non-leap-year boundary). No gaps, overlaps, or dupes.
- **Min/max sanity — two apparent outliers, both explained, not bugs:**
  - `T2M` max ~49°C (2018-07-15, lat 34.0/lon 6.25) — this cell is in
    the Sahara/Maghreb margin, not continental Europe; the configured
    "Europe" bbox's southern edge (34°N) reaches into North Africa, so
    Saharan summer heat is expected there, not an anomaly.
  - `PS` min ~74-77 kPa, consistently at lat 46.0/lon 7.5 (the Alps) —
    consistent with high-altitude terrain reducing surface pressure;
    not a defect. Tighten `_PLAUSIBLE_RANGE["PS"]` lower bound in the
    verify script if this cell should be excluded from the box, or
    leave it (it's real topography, not corrupted data).
  - Everything else (`RH`, `QV2M`, winds, `WS_10M`, `ALBEDO`, `GHI`)
    fell inside the plausible ranges for the whole year.
- **March 2018 and June 2018 were manually deleted and regenerated**
  (`--skip-download`) after the attrs fix above; June regenerated
  cleanly in the same batch run, March did not (see below).
- **Real bug found: concurrent-month transform+export can hang.**
  `test_merra2_one_year.py --year 2018 --months 3 6 --skip-download`
  ran both months in the same `ProcessPoolExecutor` batch (2 workers).
  June's worker finished and logged `2018-06: OK`; March's worker never
  logged completion. ~30 minutes later the March worker process was
  still alive but had accumulated only ~5s of CPU time (`Get-Process`
  showed `WorkingSet` ~460MB, `CPU` ~5s at both the 5-min and 30-min
  marks) — the signature of a stuck/blocked process, not one still
  computing. The half-written `MERRA2_2018_03_all_attrs.nc` was locked
  by the OS (`Device or resource busy` on delete) confirming the file
  was still open for writing. **This produced a red herring**: reading
  that half-written file mid-hang showed "100% NaN, 3.5 MB", which
  looked like data corruption but was actually just an incomplete HDF5
  write being read while still in progress — not a defect in
  `transform.py`/`export.py`'s logic itself.
  **Resolution**: killed the stuck process (`Stop-Process`, user
  confirmed), deleted the partial file, and reran **March alone**
  (`--months 3 --skip-download`, no other month in the same batch) —
  completed cleanly in 6.9s, 90.1 MB, 0% NaN, correct attrs. Full-year
  `verify_merra2_months.py` now shows all 12 months OK (0% NaN on every
  non-radiation variable, correct hour counts/continuity everywhere).
  **Root-caused and fixed.** Reproduced the hang a second time
  (`--months 3 6 --skip-download` again, after deleting both outputs)
  and attached `py-spy dump --pid <march_worker>` mid-hang. Verdict:
  the March worker's `MainThread` was blocked in
  `to_netcdf -> dask.array.core.store -> compute -> get_async`, and
  **all 22 of its dask worker threads** (`ThreadPoolExecutor-0_0`
  .. `_21` — one per `ncores`) were stuck at
  `xarray.backends.locks.CombinedLock.__enter__`, contending for
  xarray's netCDF4/HDF5 write lock with zero progress. The already-
  finished June worker, by contrast, showed a clean idle `MainThread`
  waiting in `multiprocessing.queues.get()` for more pool work — proof
  it wasn't itself part of the deadlock, just correctly idle in the
  pool. Root cause: `export.py` called `ds.to_netcdf()` directly on the
  lazy, `xr.open_mfdataset`-backed dataset from `build_monthly_dataset`,
  which hands the write to dask's default *threaded* scheduler —
  spawning `ncores` (22) threads to write **one** file, all serializing
  on a single write lock. Under `pipeline.py`'s `ProcessPoolExecutor`
  (multiple sibling worker *processes*, each spinning up its own
  22-thread pool for its own single-file write), this deadlocked in
  practice. ERA5-Land's `export.py` already avoids this exact failure
  mode by materialising each variable with `.compute()` one at a time
  *before* calling `to_netcdf()` — MERRA-2's exporter had no equivalent
  step. **Fixed**: `export.py` now does the same variable-by-variable
  `.compute()` pass before `to_netcdf()`, so the write always operates
  on already-in-memory (non-dask) arrays with no multi-threaded write
  contention. **Verified**: reran the exact repro (`--months 3 6
  --skip-download` with both outputs deleted) — completed in 19.1s
  total with no hang (`Computing dask arrays...` -> `Write done in
  5.9s` -> `2018-03: OK`); reran the full `verify_merra2_months.py`
  check afterward — all 12 months still OK, 0% NaN.
- **Process note**: `export_netcdf`'s skip-if-exists check only looks
  at "exists and is non-empty" — it can't tell a good file from a
  stuck/partial one, so a hung run like this can't self-heal via
  `--resume`; a stuck worker's partial output must be deleted manually
  (and the process killed) before rerunning that month.

## `percentile_index.py` and `dni_pointwise.py` — DONE

Both built, mirroring ERA5-Land's modules (which mirror COSMO's
production KS-distance approach — `Merra2PercentileAnalyzer(
BasePercentileAnalyzer)` mentioned in an earlier plan draft was never
the right design; `base_percentile.py`/`percentile.py` are dead code,
same as noted for ERA5-Land/COSMO at the top of `CLAUDE.md`).

- **`percentile_index.py`**: line-for-line port of
  `era5_land.percentile_index` (3-phase load/KS/mosaic pipeline,
  Finkelstein-Schafer KS-distance on monthly GHI, optional Numba
  acceleration). Provider-specific changes only: filename regex/glob
  (`MERRA2_<YYYY>_<MM>_`), output naming (`merra2_p{10,50,90}_MM_
  all_attrs.nc`), `EnvSettings.merra2_output_dir()`/`merra2_ncores()`,
  and a docstring note that MERRA-2 needs **no boundary-repair
  prerequisite** (GHI is instantaneous, not accumulated, so there's no
  ERA5-Land-style first-timestamp artifact to fix before summing daily
  GHI). Smoke-tested end-to-end against the full 2018 output
  (`python -m weather.providers.merra2.percentile_index --source-dir
  data/merra2/output --target-dir <tmp>`) — completed cleanly, wrote
  36 valid files, `source_year` correctly `[2018]` everywhere (the only
  possible answer with a single year of data; real percentile
  separation needs multiple years). Deleted the test output afterward —
  regenerate for real once enough years exist.
  **Run as a module**, not a script (`python -m
  weather.providers.merra2.percentile_index`), since it uses relative
  imports (`from ...settings import EnvSettings`) — same as ERA5-Land's.
- **`dni_pointwise.py`**: point-wise DNI/DHI decomposition (pvlib
  DIRINT/DISC + NREL SPA solar position), identical logic to
  `era5_land.dni_pointwise` — MERRA-2's `PS` (Pa) maps directly onto
  the same `pressure` parameter ERA5-Land's `sp` (Pa) already used.
  Added a docstring note that the `HH:30` timestamp offset needs no
  special handling here (solar position is computed at whatever
  timestamp the GHI series is actually indexed by).
  **Bug found, root-caused, and fixed in both providers.** Smoke-tested
  `extract_dni_dhi_dirint` against a real July-2018 MERRA-2 cell and got
  `DNI` identically `0.0` for all 744 hours. Reproduced the same result
  from the already-shipped `era5_land.dni_pointwise` against a real
  ERA5-Land cell too, confirming it wasn't specific to this port.
  Root cause (found by tracing into `pvlib.irradiance.disc`): both
  functions localize `ghi`'s index to UTC (tz-aware) when it's
  tz-naive, but then did `pd.Series(pressure).reindex(times)` on the
  **caller-supplied pressure series without the same localization** —
  a straight `ds["sp"/"PS"].to_series()` is tz-naive, so reindexing it
  onto a tz-aware index silently returns **all-NaN** (tz-naive and
  tz-aware timestamps never compare equal in pandas — no exception, no
  warning). That all-NaN pressure feeds `pvlib`'s absolute-airmass
  calculation inside `disc()`, producing all-NaN airmass -> all-NaN
  `Kn`/`dni`, which the wrapper then `.fillna(0.0)`s — hence "DNI
  is always exactly 0". Confirmed by checking `disc_out["airmass"]`
  directly: `count 0.0` (all NaN) before the fix.
  **Fixed**: added `_align_pressure()` to both
  `era5_land/dni_pointwise.py` and `merra2/dni_pointwise.py` — matches
  the pressure series' tz-awareness to `times` before reindexing (falls
  back to the scalar/no-pressure path unchanged). **Verified** on real
  2018 data for both providers, both models (DIRINT and DISC), and the
  scalar-pressure (no-`pressure`-arg) path: all now return realistic
  DNI (medians in the hundreds of W/m², max under the ~1361 W/m^2 solar
  constant, correctly zero at night) instead of a flat zero.

## Remaining follow-ups (not blocking, future work)

1. **End-to-end verification against real GES DISC data** — single-month
   smoke test (2018-03) done, see above. Still need a full annual run
   (`test_merra2_one_year.py`) before multi-year.
2. **Optional `M2T1NXLND` collection** — if snow variables (`SNODP`,
   `PRECSNOLAND`) become needed later.
3. Benchmark `opendap_max_concurrent`/`ncores` empirically once real
   runs happen; update `CLAUDE.md`'s provider table (currently `TBD`)
   accordingly.

## Conventions enforced

Global imports only (verified via `audit_imports.py`); attributes stay
a DICT; `from __future__ import annotations`; NumPy docstrings; logging
not print; `ruff`/`mypy` clean (verified against this repo's actual
CI gate, not just a generic linter).
