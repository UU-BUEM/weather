# Resolved issues & settled decisions

Do not re-raise. "BY-DESIGN" are deliberate choices.

## era5_land — fixed bugs
- Global-grid eccodes MemoryAllocationError → Europe crop (~24× smaller).
- Longitude 0–360 vs −180 (edition-2 sde) → all-NaN merge → fixed by
  _normalize_longitude before merge.
- xr.where dim reorder in step-deaccum → transpose(*a.dims).
- .stack() left time last → transpose to (time,lat,lon).
- Calendar trim dropped month's real last hour + orphaned first stamp →
  keep native window, drop only phantom all-NaN stamps.
- fill-first-hour-with-0 destroyed Arctic midnight-sun → cross-month
  repair_month_boundaries.py (float32-exact).
- _ffill_time missing `import xarray` in fallback → crashed every month
  where bottleneck absent → fixed (global import).
- repair `"REPAIRED" in status` matched "UNREPAIRED" → false-skip →
  .startswith("BOUNDARY_REPAIRED").
- repair grid-mismatch crash → logged + skipped.
- Panoply "Scaling coefficient" → strip GRIB_* attrs.

## era5_land — BY-DESIGN
- ERA5-Land 0.1°, not ERA5 0.25°/ARCO-Zarr (that lake is ERA5).
- Pipeline night_mask OFF by default (raw GHI); DNI-path masking in
  derived_attributes is separate and ON.
- No numba in the TRANSFORM (I/O+zlib bound); numba IS used in
  percentile_index. wgrib2/CDO rejected.
- ERA5_CDS_MAX_CONCURRENT=1 (CDS 1 job/account). ERA5_NCORES=6 (I/O-bound,
  NOT 94). No --cleanup for bulk (keep 1.26 TB GRIB). DNI/DHI bulk not
  computed in pipeline; dni_pointwise.py opt-in.
- Consecutive .nc don't overlap → plain open_mfdataset clean.
- fast_download parallelism within one transfer, not extra CDS requests.

## cross-provider — settled
- RH source differs BY-DESIGN: COSMO direct RELHUM_2M, ERA5 dew-point
  Magnus, MERRA-2 q-based. Do NOT unify.
- Radiation: COSMO splits direct/diffuse (needs night-mask for DNI
  inversion); ERA5/MERRA-2 give GHI directly (DIRINT). BY-DESIGN.
- derived_attributes.apply_derived_fields is the ONE cross-provider entry
  for GHI/DHI/DNI; all night-mask + enforce GHI=DHI+DNI·cos(zenith).
- Output granularity: COSMO annual, ERA5 monthly; percentile bridges via
  weather.common.merge (monthly→annual) then load_annual_dataset.
- Compute: COSMO CPU-bound (94, bz2) vs ERA5 I/O-bound (6). BY-DESIGN.
- setuptools-scm `_version.py` must stay git-ignored (tracking broke CI).
- Design: template-method base classes + DICT attribute registries +
  common/ utils. Keep it.

## merra2 — fixed bugs

- Full 1980-2025 bulk run (`test_merra2_multi_year.py`, 2026-07-24) failed
  exactly 2 of 46 years: 2020 and 2021 (`exit code 1`), all other 44 years
  OK. Root cause: `downloader.py`'s `_stream_prefix(year)` hardcodes a
  single GES DISC "stream" number (400) for the whole 2011-9999 range, but
  NASA occasionally reprocesses individual months under a bumped runid
  (401) — confirmed from the run's log: September 2020 and June-September
  2021 all 404 under stream 400 (verified these are the *only* affected
  months; every other 2020/2021 month, and all of 2022+, fetched fine
  under 400). The 404 (`requests.HTTPError`, a subclass of `OSError`) was
  also being caught by `exponential_backoff(exceptions=(OSError,))` and
  retried 5 times before finally propagating — wasted ~20s per file on a
  permanent failure with no chance of succeeding. Fixed: `_fetch` now
  tries `(primary, primary + 1)` stream candidates per file, using a new
  `_StreamNotFound` (plain `Exception`, not `OSError`) to skip the
  useless backoff retries and fall straight to the next candidate on a
  404; transient errors (503, timeouts) still retry against the same
  stream as before. `build_url()` gained an optional `stream` param to
  support this. Deliberately NOT hardcoding "Sep 2020 + Jun-Sep 2021" as
  a date range in `_STREAM_RANGES` — GES DISC's reprocessing windows are
  reported as scattered/non-contiguous (see the Earthdata Forum thread
  "Differences in file names in certain waves of MERRA 2"), so a fallback
  is the only approach that survives the *next* reprocessed wave too.
  **Verified live** (2026-07-25): re-ran 2020/2021 alone against the
  fixed downloader — both completed clean. Full 1980-2025 archive
  (46/46 years, 552 monthly files) now complete; a `verify_merra2_months
  .py` pass over the full `output/` dir (esp. the 2019->2020,
  2020->2021, 2021->2022 boundaries) is the one remaining check, see
  `.claude/merra2/merra2_plan.md`.

## geo — fixed bugs

- crop_netcdf() always failed against real cdo (first live-tested in CI,
  not on this dev machine — cdo has no win-64 conda-forge build): mkstemp
  pre-creates the output tmp file, and cdo refuses to overwrite an
  existing file by default → added `-O` to the cdo invocation. Also added
  `log.error(stderr)` before raising (previously swallowed via
  `capture_output=True` + `check=True`, so the CI failure showed only
  "returned non-zero exit status 1" with no diagnosable reason).
