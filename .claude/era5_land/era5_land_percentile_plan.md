# ERA5-Land — percentile task (DONE, pending live verification)

Goal: P10/P50/P90 representative-year GHI mosaics for ERA5-Land, mirroring
COSMO's ACTUAL production implementation. Built in
`providers/era5_land/percentile_index.py`. Still needs to be run against
real (post bulk-run, post boundary-repair) data as a smoke test.

## IMPORTANT: base_percentile.py / CosmoPercentileAnalyzer is DEAD CODE

The old plan (and `CLAUDE.md`, `providers/README.md`) described a
`BasePercentileAnalyzer` template-method design with per-year annual NC
files. That `cosmo_rea6/percentile.py` was DELETED in commit `17d5eea`
("Added percentile and documentation") and replaced with
`cosmo_rea6/percentile_index.py` — a standalone Finkelstein-Schafer
KS-distance script that does NOT use `base_percentile.py` at all.
`base_percentile.py`/`common/percentile.py` still exist in the tree but are
unused by any provider; do not build new providers against them without
checking they're still the intended pattern.

## What was actually built: `era5_land/percentile_index.py`

Direct structural port of `cosmo_rea6/percentile_index.py`:

1. **Load**: parallel-read monthly `ERA5_LAND_<YYYY>_<MM>_all_attrs.nc`
   files (regex `ERA5_LAND_(\d{4})_(\d{2})_`), day-sum GHI, drop leap days.
   ERA5-Land is already monthly (same as COSMO's percentile source, which
   also reads monthly files despite COSMO's pipeline producing "annual"
   output elsewhere) — no merge step needed after all.
2. **KS match**: per month, per cell, argmin KS distance to pooled
   P10/P50/P90 GHI thresholds. Identical algorithm to COSMO (incl. optional
   `WEATHER_USE_NUMBA_KS=1` path).
3. **Mosaic**: spawn-pool workers write `era5_land_{p10,p50,p90}_{MM}_
   all_attrs.nc`, one file open per winning year, all variables +
   `source_year` copied across.

## Deltas from COSMO (deliberate, not oversights)

- Grid size (`n_y`/`n_lon`) is INFERRED from the first loaded file's shape,
  not hardcoded — COSMO's 824×848 doesn't apply; the ERA5-Land Europe crop
  shape depends on `ERA5_AREA`.
- `n_cpu_cores` defaults to 6 (matches `ERA5_NCORES`, I/O-bound), not
  COSMO's 94 (CPU-bound bz2 decompress).
- CLI defaults source/target dirs via `EnvSettings.era5_output_dir()`
  instead of hardcoded `/data/soma/...` paths.

## Still to do (live verification, not code)

- Run against a real multi-year ERA5-Land dataset once the bulk run +
  `repair_month_boundaries.py` are complete and verified — an UNREPAIRED
  January first-stamp (raw, thousands of W/m²) would corrupt the daily GHI
  sum feeding the KS match. Verify `boundary_status` starts with
  `BOUNDARY_REPAIRED` on all source files first.
- Spot-check an Arctic and a mid-Europe cell; confirm `source_year(y,x)` is
  written and within range.
- Confirm `--month`/`--clean` re-run flags behave correctly on real data.
