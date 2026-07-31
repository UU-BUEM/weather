# Open issues / TODOs

## >>> NEXT MAJOR TASKS <<<
- [era5_land] **Percentile analyzer** — DONE (code): `era5_land/
  percentile_index.py`, a KS-distance port of COSMO's actual
  `percentile_index.py` (NOT the dead `BasePercentileAnalyzer` design).
  Needs a live smoke test after bulk run + boundary repair. See
  .claude/era5_land/era5_land_percentile_plan.md.
- [merra2] **Complete provider** from scaffold: per-DAY job, implement
  downloader (3 stubs), then download/transform/export/pipeline. GES DISC
  netrc; SWGDN=GHI directly; q-based RH. See .claude/merra2_plan.md.
- [merra2] DONE: full 2018 verified (`verify_merra2_months.py`), attrs
  bug fixed (stale raw GES DISC global attrs leaking through
  `xr.merge`), multi-month export deadlock fixed (dask threaded-write
  lock contention — `export.py` now computes each var before
  `to_netcdf()`, matching ERA5-Land). See .claude/merra2/merra2_plan.md.
- [merra2] DONE: Full 1980-2025 bulk run (2026-07-24). 44/46 years OK
  first pass; 2020 and 2021 failed on a GES DISC stream-number 404 (NASA
  reprocessed Sep 2020 and Jun-Sep 2021 under runid 401 instead of 400),
  fixed in `downloader.py` (stream fallback, see `.claude/resolved.md`),
  re-run confirmed both years OK. Full archive (46/46 years, 552 monthly
  files) verified continuous end to end via `verify_merra2_months.py`.
  See `.claude/merra2/merra2_plan.md`.
- [merra2] DONE: percentile indexer (`percentile_index.py`) run for real
  against the full 46-year archive (2026-07-25/26) — all 36 output files
  written, `source_year` diversity confirmed genuine (P50 45-46/46
  years per month, P10/P90 32-43/46). See `.claude/merra2/merra2_plan.md`.
- [merra2] DONE (code): added the `lnd` collection (`M2T1NXLND`:
  `SNODP`, `PRECSNOLAND`) and `U50M`/`V50M` (free within the existing
  `slv` collection) — needed by a confirmed downstream consumer
  (github.com/THD-Spatial-AI/merra2-energy-pipeline). 3 collections now,
  not 2. `build_monthly_dataset()`'s signature changed (new `lnd_paths`
  positional arg); the one caller (`pipeline.py`) updated. Verified
  against synthetic local NetCDF4 files, **not** a live GES DISC
  download — no network download triggered. See
  `docs/MERRA2_PIPELINE_GUIDE.md` and `.claude/merra2/merra2_context.md`.
- [geo] DONE (code + CI-verified): new `src/weather/geo/` package
  (`countries.py`, `bbox.py`, `crop.py`) + `weather geo {crop,list}`
  CLI — moves country bbox lookup and real NetCDF cropping (`cdo
  sellonlatbox`) into this repo so `merra2-energy-pipeline` doesn't need
  its own copy. Trimmed from that repo's `countries.py`: no
  `TIMEZONES`, no German/French/English alias table, no pan-Europe
  entry. `cdo` added to `weather_env.yml` (no win-64 conda-forge build,
  so still can't be exercised on this dev machine — first real `cdo`
  run happened in CI, which caught a real bug, see
  `.claude/resolved.md`'s `## geo` section). See the `## geo` section
  below for the still-open COSMO limitation.

## geo
- [geo] FIXED (code, not yet live-run): COSMO-REA6's `transform.py`
  (`build_month_dataset`/`build_annual_dataset`) now captures the 2-D
  WGS84 `latitude`/`longitude` cfgrib already decodes from the source
  GRIBs (previously dropped by `_strip_scalar_coords`, which drops *all*
  non-dimension coords despite its name, before the real assembly path)
  and re-attaches them as `(y, x)` coords on the output dataset. Done as
  part of the `point_query.py` work (see `## point_query` below), not
  the original `geo/` submodule — but it also unblocks `weather.geo.crop`
  for COSMO, which was the original ask here.
  **Still open**: the already-completed COSMO archive predates this fix
  and has no lat/lon at all, so neither `weather geo crop` nor
  `get_point_weather(provider="cosmo-rea6")` work against it yet — needs
  a COSMO transform+export rerun (not download/decompress/percentile).
  `tests/compare_providers.py`'s analytic rotated-pole-grid
  reconstruction (used because the archive it reads predates this fix)
  has not been switched over to the new real coordinates either.

## point_query
- [point_query] DONE (code), **not yet live-tested against real
  archives**: `weather.get_point_weather(lat, lon, year, provider=...)`
  (new `point_query.py`, re-exported from `__init__.py`) — single-
  location `T`/`GHI`/`DHI`/`DNI` extraction from already-processed
  provider archives, no pipeline run needed. Built for `buem`'s dynamic
  per-building weather fetch (`buem.config.weather_cache.
  get_or_fetch_weather`, which wraps it with a cache + a fallback to
  buem's bundled static CSV on any exception). New `common/
  dni_reconstruction.reconstruct_dni_dhi` consolidates the pvlib
  DIRINT/DISC logic previously duplicated identically across
  `era5_land/dni_pointwise.py`, `merra2/dni_pointwise.py`, and
  `from_csv.CsvWeatherData.reconstruct_dni_from_ghi`; new `common/
  geo_lookup.find_nearest_cell` handles COSMO's non-regular grid.
  `pyproject.toml` split into a light base + `pointquery`/`pipeline`
  extras (buem depends on `weather[pointquery,solar]`, matching exactly)
  so this path doesn't pull in cfgrib/dask/eccodes.
  Required the COSMO lat/lon fix above, plus renaming MERRA-2's `T2M` →
  `T` (matching COSMO/ERA5-Land's existing convention) — **MERRA-2 needs
  no rerun**, `point_query._temperature_series` falls back to the legacy
  `T2M` name when `T` is absent. **COSMO does need a transform+export
  rerun** (see `## geo` above) — no such fallback exists for missing
  lat/lon. ERA5-Land's `t2m`→`T` rename and `y`/`x`+lat/lon convention
  both predate this change, so the run in progress on `sd26` should come
  out compatible without a rerun; spot-check the first finished output
  file's schema once available (never tested against real ERA5-Land
  output).
  Verified so far: `ruff check`/`mypy` clean on all new/changed files,
  full existing `pytest` suite (39 tests) unaffected, `import weather` +
  `python -m weather info` both still work. Also manually smoke-tested
  end-to-end (not a permanent test) against synthetic NetCDFs shaped
  like real ERA5-Land output (`y`/`x` dims, 1-D `latitude`/`longitude`
  aux coords) and real COSMO output (`y`/`x` dims, 2-D lat/lon coords) —
  both produced correct, NaN-free `T`/`GHI`/`DHI`/`DNI`.
  **DONE**: `tests/test_point_query.py` added (11 tests) covering
  `point_query.py`/`dni_reconstruction.py`/`geo_lookup.py` with synthetic
  data shaped like each provider's real export, including a regression
  test that a pre-lat/lon-fix COSMO archive raises `KeyError` (not
  silently wrong data). Also verified against **real** DWD data this
  session: reran the (now-refactored, see `## cosmo_rea6`)
  `test_cosmo_one_month.py` for Feb 2018 against cached GRIBs, confirmed
  lat/lon present and `get_point_weather` round-trips correctly.

## era5_land
- [era5_land] Bulk 1950–2025 run not yet executed — see plan checklist.
  Apply _ffill_time import fix first.
- [era5_land] After run: MANDATORY repair_month_boundaries.py then
  verify_months.py before merge/percentile.
- [era5_land] pipeline_interleaved.py deferred (deliberately).

## cosmo_rea6
- [cosmo_rea6] FIXED (and relocated): the per-month GRIB cleanup
  constructed the cfgrib index sidecar path as `<grib_name>.idx`, but
  cfgrib actually names it `<grib_name>.<content-hash>.idx` (e.g.
  `H_SNOW.2D.201801.grb.5b7b6.idx` — confirmed from a real rerun's log
  output). The hardcoded guess never matched, so `.idx` deletion
  silently no-op'd every time, orphaning it once its parent `.grb` was
  deleted — this is exactly what was found on the production server:
  `decompress/` had only ~70 KB of stray `.idx` files left, `.grb`/
  `.bz2` all gone. Fixed by also globbing `<grib_name>.*.idx`; this
  logic now lives in `pipeline.py::run_pipeline()` (moved there along
  with the rest of the pipeline — see the architecture entry below), not
  in a test file.
  **Root cause of cleanup running at all** (found, not just theorized):
  the user confirmed the production run was **more than 5 days before**
  this investigation (i.e. before 2026-07-24) — which predates commit
  `565fd47` (2026-07-24), the commit that centralized `COSMO_CLEANUP`
  defaulting `False`/keep-everything. A checkout that old still has the
  pre-fix behavior (COSMO defaulting to aggressive cleanup), which alone
  explains the deleted intermediates — no `COSMO_CLEANUP=true`
  misconfiguration needed. Confirm the server's checkout is now current
  before the next rerun.
- [cosmo_rea6] DONE: **cleanup config centralized + COSMO's real pipeline
  moved out of test files into `providers/cosmo_rea6/`**, matching
  ERA5-Land/MERRA-2's architecture. Triggered directly by the two
  findings above (COSMO's 4 overlapping cleanup knobs — `COSMO_CLEANUP`,
  each script's own `--no-cleanup`, and the container's separate
  `COSMO_NO_CLEANUP`, which `docker-compose.yml` wired in while never
  wiring in the real `COSMO_CLEANUP` at all — and COSMO's test files
  containing 636-744 lines of real pipeline logic vs. ERA5-Land/
  MERRA-2's 65-71-line thin wrappers). See `CLAUDE.md`'s NEXT MAJOR
  TASKS item 6 for the full breakdown of what moved where. Verified:
  `ruff check src/`/`mypy src` clean repo-wide, full `pytest` suite
  unaffected, and a real end-to-end rerun of the refactored
  `test_cosmo_one_month.py` against cached real Feb-2018 DWD GRIBs
  (correct DNI stats, zero outliers >= 1400 W/m², lat/lon present,
  `get_point_weather` round-trip confirmed) plus an isolated unit check
  that the `.idx` glob fix actually deletes the hash-suffixed file.
- [cosmo_rea6] export.py docstring references old `buem.weather` path.
- [cosmo_rea6] Local imports in export.py/pipeline.py — hoist to module
  level.
- [cosmo_rea6] Reconcile local naming.py (newer) with GitHub main.
- [cosmo_rea6] FIXED: `test_cosmo_one_month.py`'s `_ALL_ATTRS` was a
  hand-duplicated list, separate from `downloaded_attributes.ATTRIBUTES`
  — `RELHUM_2M` was registered there (units/conversion) but never added
  to `_ALL_ATTRS`, so it was silently never downloaded for any month.
  Fixed: `_ALL_ATTRS` now derives from `ATTRIBUTES.keys()`; added a
  `role` field (`"formula"` vs `"passthrough"`) and `canonical_name` to
  the registry; `transform.build_month_dataset()` is now the single
  shared assembly function (both `test_cosmo_one_month.py` and
  `test_cosmo_one_year.py` call it — previously two independent
  hand-duplicated copies of the same assembly logic). RH wired
  end-to-end (passthrough, canonical name `RH`). **DONE, verified**:
  COSMO 2018 re-run live against real DWD OpenData (all 12 months, all
  10 registered attributes incl. `RELHUM_2M`; 64.6 GB total output, ~5.1
  hours on this dev machine at `--ncores 16`; DNI outlier report clean —
  no cells >= 1400 W/m^2 in any month). Spot-checked at the tool's
  default Arctic-edge cell (70.5N/25E, June): RH now real values (44.6-
  99.1%, mean 78.0%, 0% NaN, was 100% NaN before this rerun), DNI/GHI
  within physical bounds. See the cross-provider live-rerun entry below.
- [cosmo_rea6] ALBEDO — DONE (code, 2026-07-26), reversing the earlier
  "deliberately not built" call. The downstream PV consumer that first
  raised this (`pysam-photovoltaic-energy-simulation`, `scripts/main.py`)
  was re-checked against its *live* source rather than memory: its
  `alb` (PySAM's ground-reflectance transposition input) is still a
  crude threshold (`0.6 if snow_depth_cm > 1 else 0.2`, from MERRA-2's
  `SNODP`) — confirmed neither `pysam` nor `merra2-energy-pipeline`
  reads any provider's real albedo field today. COSMO's `H_SNOW` proxy
  (see below) was always sufficient for *that* threshold. What changed:
  the user plans to refactor `pysam` to use real reanalysis albedo for
  `alb` instead (a genuine accuracy improvement for that specific
  ground-reflectance parameter — a different physical mechanism than
  the snow-on-panel coverage loss the same file models separately from
  snow depth/snowfall, which stays unchanged). That tipped the earlier
  "not built, no confirmed consumer" call: added `SOBS_RAD` (net
  shortwave, instantaneous — NOT `ASOB_S`) to
  `downloaded_attributes.py`; `transform.compute_albedo` derives
  `ALBEDO = (GHI - SOBS_RAD) / GHI` (`GHI = SWDIRS_RAD + SWDIFDS_RAD`),
  NaN at night, matching MERRA-2's own `ALBEDO` NaN-at-night behavior.
  Also renamed ERA5-Land's `fal` → `ALBEDO` (see `## cross-provider`
  below) so all three providers share one canonical field name.
  **Not yet live-tested** — needs a COSMO rerun (one new raw attribute)
  before the next bulk run; a 2017-03 single-month test is planned
  first. `compare_providers.py` still compares `SNOW_DEPTH` across all
  three providers (ERA5-Land's `sd` — water-equivalent depth, NOT
  directly comparable without a density conversion, see that module's
  docstring) — unaffected by the ALBEDO addition, kept for the
  snow-loss-on-panel side of the model. Renamed alongside ALBEDO in the
  same pass: `H_SNOW`'s canonical name -> `SNOW_DEPTH` (matches
  MERRA-2's renamed `SNODP`), and `SNOW_CON`+`SNOW_GSP` -> one combined
  derived `SNOWFALL` field (`transform.compute_snowfall`) matching
  MERRA-2's renamed `PRECSNOLAND`/ERA5-Land's renamed `sf` — see
  `## cross-provider`'s full naming-unification entry for the complete
  picture across all three providers.

## cross-repo

- [harmonization] **Idea, not started (2026-07-30)**: a small shared
  "harmonization" package (env.yml/pyproject.toml/CI-workflow scaffolding)
  that weather/occupancy/buem would each conda-install from, instead of
  today's approach — every shared pin or fix (e.g. the numpy/pandas
  floor-only convention, the `libblas=*=*openblas` fix for the mkl+cupy
  Windows crash, python>=3.12 baseline) gets hand-copied across all three
  repos' own env files and `.github/agents/uu-buem-align.agent.md`'s
  table by hand each time, which is exactly how this repo's numpy/pandas
  caps drifted out of sync in the first place. Would live in its own repo
  under UU-BUEM. Not designed or scoped yet — user is considering it; ask
  before acting if this comes up again.

## cross-provider

- [all] DONE (2026-07-26): full cross-provider attribute-naming
  unification, user explicitly signed off on renaming already-completed
  archives' schemas (superseding the earlier "not touched this session,
  needs an explicit decision" note). All three providers now share one
  canonical name per physical quantity, extending the pattern already
  used for `T`/`GHI`/`DHI`/`RH`/`WS_10M`:
  - **ALBEDO**: ERA5-Land's `fal` renamed (see `## cosmo_rea6`'s ALBEDO
    entry for COSMO's new derived field). `asn` (ERA5-Land's narrower
    snow-only diagnostic, no cross-provider equivalent) intentionally
    keeps its cfgrib short name, unrenamed.
  - **PS**: ERA5-Land's `sp` renamed (COSMO/MERRA-2 already `PS`).
  - **U_10M/V_10M**: canonical form chosen to match COSMO's native
    names and the already-shared `WS_10M`'s underscore style.
    ERA5-Land's `u10`/`v10` and MERRA-2's `U10M`/`V10M` renamed.
    MERRA-2's `U2M`/`V2M`/`U50M`/`V50M` (no cross-provider equivalent —
    COSMO/ERA5-Land don't fetch 2m/50m wind) renamed to `U_2M`/`V_2M`/
    `U_50M`/`V_50M` too, for internal consistency.
  - **SNOW_DEPTH**: COSMO's `H_SNOW` and MERRA-2's `SNODP` are the same
    physical quantity (physical depth in m) — both renamed. ERA5-Land
    was originally assessed as having a genuinely different quantity
    (`sd`, water-equivalent depth) and left deliberately unrenamed —
    **that assessment was wrong, corrected 2026-07-30, see below.**
  - **SNOWFALL**: MERRA-2's `PRECSNOLAND` and ERA5-Land's `sf` renamed.
    COSMO previously exported `SNOW_CON`/`SNOW_GSP` as two separate
    passthrough fields — now combined into one derived `SNOWFALL`
    (`transform.compute_snowfall`, role changed `passthrough`->
    `formula`), matching the other two providers' single-field shape.
  - **Dewpoint checked, not added**: confirmed via DWD's real
    `ParameterTables_REA6.pdf` that COSMO has no dewpoint field at all
    (not just "not downloaded" — genuinely absent from the upstream
    catalog). MERRA-2's GES DISC catalog DOES have `T2MDEW` (2m dew
    point) in the same `slv` collection already fetched — a free
    addition if ever wanted, not added without a confirmed need.
  - **Backward compatibility**: `point_query.py` (`_pressure_series`,
    mirroring the existing `_temperature_series` pattern),
    `compare_providers.py`, and `verify_merra2_months.py`'s
    `_PLAUSIBLE_RANGE` all try the new canonical name first, falling
    back to the old raw name — so all three keep working against the
    already-completed 2018/46-year archives (old names on disk) AND
    any future rerun (new names) without modification. A real latent
    bug was caught and fixed in this pass: `point_query.py`'s
    `_get_point_era5_land` had `pressure_var="sp"` hardcoded with NO
    fallback — the `PS` rename would have silently dropped pressure
    from DNI/DHI reconstruction for any future ERA5-Land archive.
  - **T_DEW (dew point) added, 2026-07-26.** Verified 100% before
    building anything: fetched DWD's real `hourly/2D/` directory
    listing directly (not just the parameter table PDF) — confirmed no
    dew-point field, and no better derivation available either (`QV_2M`
    is listed there too, but using it would need a brand-new download
    for no accuracy gain over deriving from `T_2M`+`RELHUM_2M`, both
    already fetched). Implemented as `dewpoint_from_rh()` in
    `common/derived_attributes.py` — the algebraic inverse of the
    already-existing `magnus_rh()` (same `a=17.625, b=243.04`
    constants), cross-checked against a standard meteorological
    reference independent of the in-repo derivation (±0.35°C accuracy,
    T in [-40,50]°C, Alduchov & Eskridge 1996). COSMO's
    `transform.compute_dewpoint` calls it (free — no new attribute).
    ERA5-Land's native `d2m` renamed to `T_DEW` (measured, not
    derived). MERRA-2 previously had no dewpoint at all; added
    `T2MDEW` as a new raw attribute (free — same `slv` collection
    already fetched for `T2M`/`QV2M`/winds/`PS`), renamed to `T_DEW`.
    All three providers now share one canonical dew-point field name.
  - **COSMO verified live (2026-07-26)**: full `test_cosmo_one_month.py
    --year 2017 --month 3` run against real DWD data (dev machine, 22
    cores, `--ncores 12`) — 11/11 downloads verified, 744 timesteps,
    all 11 output variables present with the new canonical names.
    `T_DEW > T` physical-impossibility check: 0 violations across
    ~520M finite (time, y, x) triples. `ALBEDO`: bounded to [0.047,
    0.829] (within [0,1]), exactly 100% NaN wherever GHI<=1 W/m^2
    (night-mask working correctly — the `RuntimeWarning: invalid value
    /divide by zero` logged during the intermediate divide is expected
    and harmless, masked out by `.where(ghi > 1.0)` before it reaches
    the output; confirmed zero `inf`/leaked-NaN in the final array).
    `SNOWFALL`: non-negative, max 14.7 kg/m^2/h. `SNOW_DEPTH`: max
    40.15 m, matching the ALREADY-DOCUMENTED June 2018 domain-stats max
    of 40.00 m for the same underlying `H_SNOW` field (a known
    permanent glacier/ice-sheet cell in the domain — not a new
    anomaly). `T_DEW`'s extreme minimum (-64.4°C) traced to a genuine
    `RH=0.062%` reading at a Sinai/Red Sea desert-margin cell
    (28.39N/33.84E) — COSMO's domain edge, same pattern as the
    already-documented Saharan-margin temperature extremes elsewhere in
    this codebase, not a formula bug (the formula is mathematically
    consistent with that input; the T_DEW>T check already confirms
    zero violations). DNI outlier report: 0 cells >= 1400 W/m^2.
  - **MERRA-2 verified live (2026-07-30)**: `test_merra2_one_month.py
    --year 2018 --month 3`, fresh GES DISC download (~52s total on the
    dev machine) — all 16 variables present incl. `T_DEW`/`U_50M`/
    `V_50M`. Real, non-bug finding: MERRA-2's native `T2MDEW` violates
    `T_DEW <= T` in ~3.2% of values (confirmed present in the raw
    downloaded file itself, not introduced by this pipeline) — see
    `.claude/merra2/merra2_context.md` for the full writeup and the
    cross-provider contrast (COSMO's derived `T_DEW`: 0 violations by
    construction; ERA5-Land's native `d2m`: 0 violations, checked the
    same day against real data).
  - **ERA5-Land not yet live-tested** for the naming-unification pass
    (though its native `d2m` was independently checked this same
    session as part of the `T2MDEW` investigation above, using the
    already-existing real 2018-03 output — 0 `d2m > T` violations
    across ~62M points).
- [all] DONE (2026-07-30): three more fixes/checks against real local
  data (all three providers already have real 2018-03 output on the
  dev machine, used for this cross-check):
  - **Real bug found + fixed: COSMO now keeps `U_10M`/`V_10M`** in its
    output alongside `WS_10M`, matching ERA5-Land/MERRA-2 (both always
    kept the raw components too) — COSMO used to be the only one of
    the three that discarded them after computing the scalar speed.
    Not previously documented anywhere; found only when asked to
    verify all three providers produce identical output.
  - **Real bug found + fixed: ERA5-Land's `snow_depth` entry in
    `downloaded_attributes.py` was mislabeled.** It claimed `e5l_name:
    "sd"` and described the field as water-equivalent depth, genuinely
    different from COSMO/MERRA-2's physical depth — the reasoning the
    2026-07-26 naming pass used to deliberately leave it unrenamed.
    Verified via three independent sources that this was wrong: (1) the
    real CDS request payload (user-supplied) lists `snow_depth`, not
    `snow_depth_water_equivalent`; (2) the raw downloaded GRIB decodes
    to `GRIB_shortName 'sde'`, `long_name 'Snow depth'` — `'sd'` is the
    OTHER, water-equivalent CDS variable, never actually requested;
    (3) the already-processed 2018-03 output has the variable literally
    named `sde`. Fixed: `e5l_name` corrected to `"sde"`, description/
    unit_target/conversion corrected (no conversion needed — already
    physical meters), and `sde` now renamed to canonical `SNOW_DEPTH`
    in `transform.py`, achieving genuine 3-way unification after all.
    The mislabeling never corrupted any actual value (no
    water-equivalent conversion was ever coded or applied), only the
    description and the naming decision were wrong. Verified against
    the real local GRIB + already-processed output (max 33.33 m,
    identical to the pre-fix number, confirming the fix only changed
    the label, not the data) and against `build_monthly_dataset()` run
    directly on the real file. `compare_providers.py`'s docstring and
    `SNOW_DEPTH` lookup, and `docs/provider_differences.md`'s section 4,
    corrected to match.
  - **`asn` explained, checked against both other providers, nothing
    added.** `asn` = ECMWF's "Snow albedo" (confirmed via real GRIB
    metadata) — the reflectivity of just the snow-covered surface,
    distinct from `fal`/`ALBEDO`'s blended whole-grid-cell reflectivity.
    Checked DWD's real parameter table (COSMO) and GES DISC's
    `M2T1NXRAD` catalog (MERRA-2, confirmed via the Earth Engine
    catalog listing) — neither has an equivalent narrower snow-only
    albedo field. No confirmed consumer needs one; nothing added.
  - **`QV2M` explained, downstream repos re-checked.** Pure intermediate
    for deriving RH, nothing else — confirmed by reading
    `merra2-energy-pipeline/src/data_pipeline/combine.py:199-296`
    (`_specific_humidity_to_rh`), which independently reimplements the
    same specific-humidity -> RH conversion `merra2/transform.py
    ::_compute_rh` already does, for its biomass/geothermal outputs.
    `pysam` (PV) doesn't reference `QV2M`/humidity at all (grepped,
    zero hits). COSMO/ERA5-Land's "equivalent" isn't a specific-humidity
    field — it's simply their own already-unified `RH` (COSMO:
    `RELHUM_2M` direct; ERA5-Land: dew-point Magnus). Since `RH` is
    already canonical across all three, this downstream need is already
    satisfied without adding anything new anywhere.
- [all] Run audit_imports.py across every provider; enforce global-imports.
- [all] Keep ruff/flake8/markdownlint clean; honour pyproject.toml/.flake8/
  markdownlint.json/conda_build_config.yml at root.
- [all] FIXED: formula duplication between each provider's `transform.py`
  and `common/derived_attributes.py`. Every provider's `transform.py` had
  its own independent copy of GHI/DNI/RH/WS_10M math, separate from
  `derived_attributes.py`'s registry copies (used only by
  `test_derived_attributes.py` and any future `apply_derived_fields`
  caller, NOT by the real pipelines) — two real correctness gaps found
  in the process (COSMO GHI clip-order, COSMO DNI missing upper
  cos(zenith) bound). Fixed by extracting shared pure formulas
  (`wind_speed`, `magnus_rh`, `bolton_rh`, `ghi_from_diffuse_direct`,
  `dni_from_direct`) into `derived_attributes.py` and having every
  provider's `transform.py` import and call them — one implementation
  each, not two. Also moved `spencer_zenith` (previously defined in
  `era5_land/transform.py` and cross-imported by `merra2/transform.py`,
  with a TODO already asking for this) to a new `common/solar_position.py`.
  COSMO's `compute_dni` keeps its own dask-chunked inline Spencer/DNI
  computation (deliberately NOT routed through the shared functions,
  which aren't dask-tuned) but now imports the shared elevation-threshold
  constant and the shared post-zenith DNI formula, so the one non-shared
  piece left is exactly the dask-chunking strategy, not the math. Full
  `pytest src/weather/tests/` + synthetic-data numerical checks pass.
  **DONE**: live-tested via a full COSMO 2018 + MERRA-2 2018 re-run
  against real DWD/GES-DISC data (see the live-rerun entry below). ERA5
  was deliberately not touched or run this session (user's account was
  mid-run on an external multi-year ERA5 job) — its formula-dedup
  changes remain code-only/synthetic-verified, not live-tested.
- [all] FIXED (found live, during the COSMO/MERRA-2 2018 re-run):
  `export_netcdf()` in all three providers' `export.py` had its own
  unconditional `if output_path.exists(): skip` check, independent of
  the correct resume-gated skip logic already implemented one layer up
  (`test_cosmo_one_year.py`'s `--resume`; `era5_land`/`merra2`
  `pipeline.py`'s `skip_existing`/`resume`). Effect: re-running a
  provider WITHOUT `--resume` to force regeneration silently wrote
  nothing whenever the output `.nc` already existed — the first live
  MERRA-2 2018 re-run hit exactly this (reported "OK" for all 12
  months while writing zero bytes; SNODP/PRECSNOLAND/U50M/V50M never
  appeared until outputs were deleted and it was re-run). Fixed by
  removing the internal check from all three `export_netcdf()`s; the
  skip/overwrite decision belongs solely to the caller. Code-only fix
  for `era5_land/export.py` — not run this session.
- [all] DONE (partial): `tests/compare_providers.py` confirms the three
  providers share the Europe box, but do NOT align cell-for-cell — ERA5-
  Land/MERRA-2 have real lat/lon and align with each other exactly;
  COSMO has none in its exported files (raw GRIBs cleaned up, no CONST
  file) and its cell is matched via an analytically-reconstructed
  rotated-pole grid, best-effort only (~km-scale, not verified against
  DWD's CONST file). era5_land/merra2 do NOT have COSMO's `_ALL_ATTRS`-
  style duplication bug (checked; their raw-attribute lists already
  derive from their own `downloaded_attributes.py`).
- [all] DONE: centralized the intermediate-file cleanup default. COSMO's
  test runners defaulted to `--no-cleanup=False` (i.e. delete `.bz2`/
  `.grb` after each month) while ERA5-Land/MERRA-2's already defaulted
  to keep everything — an inconsistency the user hit directly (orphaned
  `.sha256` sidecars with no `.bz2` next to them, since cleanup deletes
  the big file but not its checksum). Fixed by adding one boolean setting
  per provider to `settings.py` (`EnvSettings.cosmo_cleanup()` /
  `era5_cleanup()` / `merra2_cleanup()`, env vars `COSMO_CLEANUP`/
  `ERA5_CLEANUP`/`MERRA_CLEANUP`, all defaulting `False` — keep
  everything, matching the user's stated preference now that disk isn't
  a constraint), exposed via each provider's `config.py` as
  `cfg["cleanup"]`. Every `pipeline.py`'s `run_pipeline(cleanup: bool |
  None = None, ...)` now resolves `None` -> `cfg["cleanup"]`, and every
  `test_<provider>_one_month/one_year/multi_year.py`'s own `--cleanup`/
  `--no-cleanup` CLI flag now takes its **default** from the same
  setting instead of a locally hardcoded value — change the env var once
  and every entrypoint picks it up; the CLI flag still overrides
  per-invocation exactly as before. **No cleanup logic was touched** —
  same files get deleted, at the same point in the pipeline, under the
  same conditions; only *where the boolean's default value comes from*
  changed. `.env.example` and `settings.py`'s module docstring document
  the three new keys.
- [all] DONE: same centralization pattern extended to `--from-year`/
  `--to-year` on the three `test_<provider>_multi_year.py` scripts —
  each previously hardcoded its own defaults directly in argparse
  (COSMO 1995/2018, ERA5-Land 1940/2025, MERRA-2 1980/2025). Added
  `EnvSettings.cosmo_from_year()`/`cosmo_to_year()` (env vars
  `COSMO_FROM_YEAR`/`COSMO_TO_YEAR`) and the `era5_`/`merra2_`
  equivalents (`ERA5_FROM_YEAR`/`ERA5_TO_YEAR`,
  `MERRA_FROM_YEAR`/`MERRA_TO_YEAR` — `MERRA_` not `MERRA2_`, matching
  `MERRA_WORK_DIR`/`MERRA_YEAR`), all defaulting to the exact values
  each script already hardcoded, so no behavior changes unless the env
  var is set. Not surfaced in `config.py` (unlike `cleanup`) — these
  are multi-year-script-only concepts, not consumed by `run_pipeline()`.
- [all] DONE: removed the `sys.path.insert(0, str(_src))` "path
  bootstrap" block from COSMO's three test runners
  (`test_cosmo_one_month/one_year/multi_year.py`) — pre-existing (not
  introduced this session), and inconsistent with ERA5-Land/MERRA-2's
  equivalent scripts, which never had it and simply `import weather...`
  directly. `weather` is pip-installed editable in `weather_env`
  (confirmed: `python -c "import weather; print(weather.__file__)"`
  resolves to `src/weather/__init__.py`) and `pip install -e .
  --no-deps` is already the mandatory documented install step (see
  CLAUDE.md's packaging convention) — the bootstrap was solving a
  problem (`import weather` failing) that the project's own standard
  install already solves, via a non-standard mechanism (mutating
  `sys.path`, which controls the *import* search path — an unrelated
  concern from `pathlib`/`os.path`, which build filesystem path
  strings; there was no "use pathlib instead" fix available because
  pathlib doesn't do what `sys.path.insert` does). All three COSMO
  scripts now `from weather.settings import EnvSettings` etc. as plain
  top-level imports, matching ERA5-Land/MERRA-2. Verified: `--help`
  runs clean on all three, full `ruff`/`mypy` pass.

## external (context only)
- [envelope-extractor] Apeldoorn municipality boundary bug pending
  diagnostics (separate UU-BUEM package).
