# CLAUDE.md — weather package

Persistent context for Claude Code. Load the per-provider `.claude/` file
in play; check `.issues/` before working. Keep these docs updated when code
changes (same commit).

## >>> NEXT MAJOR TASKS <<<

1. **ERA5-Land percentile** — DONE (code). `providers/era5_land/
   percentile_index.py` mirrors COSMO's actual `percentile_index.py`
   (Finkelstein-Schafer KS-distance on monthly GHI; `base_percentile.
   BasePercentileAnalyzer` is dead code, superseded in commit `17d5eea`).
   Still needs a live smoke test AFTER bulk run + boundary repair.
   → `.claude/era5_land/era5_land_percentile_plan.md`
2. **MERRA-2 end-to-end verification** — DONE. Full 1980-2025 archive
   (46 years, 552 monthly files) run against real GES DISC data,
   verified via `tests/verify_merra2_months.py` (hour counts, `HH:30`
   span, cross-month/cross-year continuity incl. every year boundary,
   NaN/min-max plausibility). Bugs found and fixed along the way: stale
   raw GES DISC global attrs leaking through `xr.merge` (now cleared in
   `transform.py`); a multi-month `ProcessPoolExecutor` export deadlock
   (dask threaded-write lock contention — `export.py` now computes each
   variable before `to_netcdf()`, matching ERA5-Land); and a GES DISC
   stream-number 404 (NASA reprocessed Sep 2020 + Jun-Sep 2021 under
   runid 401 instead of 400 — `downloader.py` now falls back to the
   next stream on a 404 instead of hardcoding one runid per year range).
   → `.claude/merra2/merra2_plan.md`
3. **MERRA-2 percentile / dni_pointwise** — DONE. `providers/merra2/
   percentile_index.py` mirrors ERA5-Land/COSMO's KS-distance approach;
   `providers/merra2/dni_pointwise.py` mirrors ERA5-Land's point-wise
   DNI/DHI helper. `percentile_index.py` run for real against the full
   46-year archive (not just a 2018 smoke test): 36 output files, genuine
   per-cell `source_year` diversity confirmed (P50 45-46/46 years per
   month, P10/P90 32-43/46). `dni_pointwise.py` still only smoke-tested
   against 2018. Also found + fixed a real cross-provider bug in
   `dni_pointwise.py` (both providers): a tz-naive/tz-aware pressure
   index mismatch on `.reindex()` silently produced all-NaN pressure ->
   all-NaN airmass -> DNI always exactly 0, no exception raised. Fixed
   in both `era5_land/dni_pointwise.py` and `merra2/dni_pointwise.py`
   via a shared `_align_pressure()` helper. → `.claude/merra2/merra2_plan.md`
4. **Country bbox + cropping (`geo/`)** — DONE. New standalone
   `src/weather/geo/` package: `countries.py` (trimmed port of the
   downstream `merra2-energy-pipeline` repo's `countries.py` — bbox dict
   only, no timezones, no multilingual aliases), `bbox.py` (`BBox` in
   this repo's own `[N,W,S,E]` convention, with explicit converters to
   CDO's different axis order), `crop.py` (real `cdo sellonlatbox`
   subprocess cropping, not just a lookup). CLI: `weather geo
   {crop,list}`. Works today for ERA5-Land/MERRA-2 output NetCDFs.
   COSMO-REA6 was blocked on missing lat/lon in its production export;
   `transform.py` now retains it (see item 5) but a COSMO transform+export
   rerun is still needed before `weather geo crop` works against COSMO
   output — see `.claude/open.md`. Not wired into any `pipeline.py`
   (standalone post-processing step by design).
5. **Point-query entry point for downstream consumers** — DONE (code),
   **not yet live-tested against real archives**. New `weather.
   get_point_weather(lat, lon, year, provider=...)` (`point_query.py`,
   re-exported from `__init__.py`) extracts hourly `T`/`GHI`/`DHI`/`DNI`
   for the nearest already-processed grid cell — no pipeline run
   involved. Built for `buem`'s dynamic per-building weather fetch
   (`buem.config.weather_cache`). Shared helpers: `common.
   dni_reconstruction.reconstruct_dni_dhi` (consolidates the pvlib
   DIRINT/DISC logic previously duplicated across `era5_land/
   dni_pointwise.py`, `merra2/dni_pointwise.py`, and `from_csv.py`) and
   `common.geo_lookup.find_nearest_cell` (COSMO's non-regular grid).
   `pyproject.toml` split into a light base + `pointquery`/`pipeline`
   extras so this path doesn't pull in cfgrib/dask/eccodes. Required two
   provider-side schema changes to make COSMO/MERRA-2 point-queryable at
   all: COSMO's `transform.py` now retains the real 2-D WGS84 lat/lon
   cfgrib already decodes (previously dropped by `_strip_scalar_coords`
   before export — see `## geo` in `.claude/open.md`), and MERRA-2's
   `transform.py` renames `T2M`→`T` to match COSMO/ERA5-Land. **Neither
   already-completed archive has these retroactively**: MERRA-2 is
   handled backward-compatibly (`point_query._temperature_series` falls
   back to `T2M` when `T` is absent — no rerun needed), but COSMO has no
   fallback for missing lat/lon — `get_point_weather(provider=
   "cosmo-rea6")` raises `KeyError` against the already-completed COSMO
   archive until COSMO's transform+export phase is rerun (not
   download/decompress/percentile). ERA5-Land's `t2m`→`T` rename and
   `y`/`x`+lat/lon convention both predate this change, so the run
   currently in progress on `sd26` should come out point-query-compatible
   without a rerun — spot-check the first finished output file's schema
   once available (never tested against real ERA5-Land output).
   Verified: `ruff`/`mypy` clean, existing `pytest` suite unaffected,
   plus a manual end-to-end smoke test against synthetic NetCDFs shaped
   like real ERA5-Land and COSMO output, and a permanent
   `tests/test_point_query.py` added covering `point_query.py`/
   `dni_reconstruction.py`/`geo_lookup.py` (11 tests). The COSMO lat/lon
   fix itself has now been verified against real DWD data too (see item
   6) — `get_point_weather(provider="cosmo-rea6")` confirmed working
   against a freshly-regenerated real month.
6. **COSMO-REA6 aligned with ERA5-Land/MERRA-2's architecture + cleanup
   centralized** — DONE. Investigating why a production COSMO run on
   `sd26` had its `download`/`decompress` intermediates deleted (likely
   a stale pre-`565fd47` checkout — that commit is what centralized
   `COSMO_CLEANUP` defaulting `False`) surfaced two structural drifts,
   both fixed:
   (a) **Cleanup had 4 overlapping knobs for COSMO** (`COSMO_CLEANUP`,
   each script's own hand-declared `--no-cleanup`, and the container's
   separate `COSMO_NO_CLEANUP` — which `docker-compose.yml` wired in but
   never wired in the real `COSMO_CLEANUP` at all, so inside the
   container only the phantom variable had any effect) vs. ERA5-Land/
   MERRA-2's one var + one positive `--cleanup` flag. Fixed: new
   `common/cli_flags.py` (`add_cleanup_flag`/`add_resume_flag`/
   `add_skip_download_flag`/`add_skip_decompress_flag`) is now the one
   place every `test_<provider>_*.py` script wires its flags from
   (COSMO's `--no-cleanup` renamed to `--cleanup` for parity — a
   deliberate breaking CLI change, every in-repo reference updated in
   the same change); `docker-compose.yml`/`entrypoint.sh` now pass
   `COSMO_CLEANUP` straight through instead of the phantom variable.
   (b) **COSMO's test files contained the real pipeline** (bulk
   download/decompress, resume, cleanup, DNI-outlier diagnostics —
   `test_cosmo_one_year.py`/`test_cosmo_one_month.py` were 744/636 lines
   vs. ERA5-Land/MERRA-2's 68-71-line thin CLI wrappers around their own
   `pipeline.py::run_pipeline()`), while COSMO's own `pipeline.py` did
   something different and simpler — two drifting implementations of
   the same pipeline. Fixed: all of it now lives in
   `providers/cosmo_rea6/` — `download.py`/`decompress.py` gained
   `months=`-aware `download_all()`/`decompress_all()` plus new
   `verify_downloads()`/`verify_decompressed()`; `transform.py` gained
   `log_dni_stats()`/`report_dni_outliers()`; `pipeline.py::run_pipeline
   (year, months=None, ...)` now does per-month sequential transform+
   export with resume, matching ERA5-Land/MERRA-2's shape exactly (and
   returns `list[Path]`, so `CosmoREA6Provider`'s CLI adapter now matches
   `ERA5LandProvider`/`MERRA2Provider`'s pattern too). COSMO's
   `test_cosmo_one_month/one_year.py` are now thin wrappers (~80-115
   lines); `test_cosmo_multi_year.py` unchanged in shape (was already a
   thin subprocess-fan-out script, just updated to the new flag name).
   Verified: `ruff check src/`/`mypy src` clean repo-wide, full `pytest`
   suite unaffected, and a real end-to-end rerun of the new thin
   `test_cosmo_one_month.py` against cached real Feb-2018 DWD GRIBs
   (correct DNI stats, zero outliers, lat/lon present,
   `get_point_weather` round-trip confirmed).

## Operating rules for Claude Code (read first)

- **Minimize tokens.** Load only the provider file(s) in play; don't
  re-read files already in context; prefer dense edits over restating.
- **Right-size effort.** Trivial edits → just do them. Cross-provider or
  multi-file → plan briefly first. Don't over-engineer.
- **Keep docs current.** Change code/behaviour/decisions → update that
  provider's `.claude/*_context.md`/`*_plan.md` and `.issues/` in the SAME
  change. These are the source of truth for the next session.
- **Maintain modularity + simplicity.** Shared logic in `common/` and the
  `base_*` classes; provider-specific logic in the provider. Same module
  roles across providers.
- **Summarize file changes at the end of every response.** List every file
  created/modified/deleted in that turn (repo-relative paths), or state
  explicitly "No files were updated" if the turn was read-only (answering a
  question, investigating, reviewing). Keeps an audit trail the user can
  scan without re-deriving it from the conversation.

## Lint / tooling compliance (exact — CI enforces)

CI (`.github/workflows/ci.yml`) runs, and all must pass:
`ruff check src/` · `mypy src` · `pytest -q --cov=weather` ·
`python -m weather info`.

- **ruff** (`[tool.ruff]` in pyproject): line-length 88, target py312,
  select `E,F,W,I,UP,B,SIM`, ignore `E501`. So: sorted imports (I),
  pyupgrade (UP), bugbear (B), simplify (SIM). Global-imports-only.
  Bare excepts use `except Exception:  # noqa: BLE001`.
- **mypy**: `ignore_missing_imports=true`, `strict=false`, py312.
- **markdownlint** (`.markdownlint.json`): MD013 line_length **100**
  (tables exempt), MD018 off, MD024 siblings_only (duplicate headings OK
  if not siblings). Wrap prose at 100, label fenced blocks, blank lines
  around headings/lists/fences.
- **yamllint** (`.yamllint.yml`): line-length max 120; `meta.yaml` is
  ignored (Jinja2). Keep other YAML ≤120 and valid.
- **versions (pinned across UU-BUEM repos)**: python >=3.12 (NOT 3.14 — no
  conda-forge cfgrib/eccodes builds), numpy 1.26.*, pandas 2.2.*. Don't
  bump these.
- **packaging**: conda-only workflow; `pip install -e . --no-deps` (never
  `conda develop`); binaries (aria2, lbzip2, eccodes, cfgrib, cdo) in
  `weather_env.yml`, Python deps in `pyproject.toml`; `meta.yaml` version
  via Jinja2 `{% set version = ... %}`; never commit `_version.py`
  (setuptools-scm, `version_file=src/weather/_version.py`).

## CLI, containers, cross-repo

- **CLI**: `python -m weather {info,validate,run,geo}` (entry
  `weather.cli:main`; `geo` has `{crop,list}` subcommands, see below).
  `validate.py` at root runs env/CLI/tests/structure/docker checks.
- **Containers** (`infrastructure/container/`): Dockerfile, docker-compose.yml,
  entrypoint.sh route by `PIPELINE_MODE` ∈ {single-year, multi-year, merge,
  percentile, check}. `check` = imports + `weather info` + unit tests, no
  data. Env is `infrastructure/env/weather_env.yml`. Cleanup is controlled
  by `COSMO_CLEANUP` (passed straight through to the container; read
  directly by `EnvSettings.cosmo_cleanup()`) — the container previously
  had a separate `COSMO_NO_CLEANUP` variable that `docker-compose.yml`
  never actually connected to the real `COSMO_CLEANUP`, so only the
  phantom variable had any effect inside the container; fixed this
  session, see NEXT MAJOR TASKS item 6.
- **Cross-repo (UU-BUEM)**: weather ‖ occupancy ‖ buem share pins, CI
  (`.github/workflows/ci.yml`), Docker base (continuumio/miniconda3),
  `infrastructure/env/` layout, and `pip install -e .`. A change to any of
  these here usually needs the parallel change in the sibling repos.
  See `.github/agents/uu-buem-align.agent.md`.

## Repo tree (key paths)

```text
weather/
├── CLAUDE.md                      # this file (always loaded)
├── .claude/                       # per-provider context + plans (on-demand)
├── .issues/                       # open.md, resolved.md (check before work)
├── pyproject.toml  .markdownlint.json  .yamllint.yml
├── conda_build_config.yaml  meta.yaml  validate.py  CHANGELOG.md
├── .github/
│   ├── workflows/ci.yml  workflows/release.yml
│   ├── skills/weather-runtime-error-debug/SKILL.md  # numba-first debug
│   └── agents/uu-buem-align.agent.md                # cross-repo aligner
├── infrastructure/
│   ├── env/weather_env.yml
│   └── container/Dockerfile  docker-compose.yml  entrypoint.sh
└── src/weather/
    ├── settings.py                # EnvSettings: all *_ env → typed values
    ├── registry.py  cli.py  __main__.py
    ├── point_query.py             # get_point_weather: single-location T/GHI/
    │                              # DHI/DNI from already-processed archives
    │                              # (no pipeline run) -- see NEXT MAJOR TASKS
    ├── common/                    # shared, provider-agnostic
    │   ├── derived_attributes.py  # apply_derived_fields + shared formulas
    │   │                          # (wind_speed, magnus_rh, bolton_rh,
    │   │                          # ghi_from_diffuse_direct, dni_from_direct)
    │   │                          # -- single source of truth; each provider's
    │   │                          # transform.py imports and calls these
    │   ├── solar_position.py      # spencer_zenith (ERA5-Land/MERRA-2; COSMO
    │   │                          # has its own dask-chunked inline version,
    │   │                          # see compute_dni's docstring for why)
    │   ├── dni_reconstruction.py  # reconstruct_dni_dhi: shared pvlib DIRINT/
    │   │                          # DISC point-of-use decomposition, used by
    │   │                          # point_query.py + both dni_pointwise.py's
    │   ├── geo_lookup.py          # find_nearest_cell: COSMO's non-regular
    │   │                          # grid (used by point_query.py)
    │   ├── cli_flags.py           # add_cleanup_flag/add_resume_flag/
    │   │                          # add_skip_download_flag/
    │   │                          # add_skip_decompress_flag -- the one
    │   │                          # place every test_<provider>_*.py wires
    │   │                          # its shared argparse flags from
    │   ├── download.py            # https/ftp atomic, checksums
    │   ├── decompress.py          # bz2 helpers (lbzip2/pbzip2/python)
    │   ├── parallel.py            # run_parallel (thread/process pools)
    │   ├── merge.py               # monthly NC → annual NC (unused by percentile now)
    │   ├── percentile.py          # select_representative_years (dead code, unused)
    │   └── net.py  validate.py  cleanup.py  env.py
    ├── geo/                       # country bbox + NetCDF cropping (provider-agnostic)
    │   ├── bbox.py                 # BBox([N,W,S,E]) + to_cdo_lonlatbox()/to_area_list()
    │   ├── countries.py            # COUNTRIES dict, get_bbox/list_countries
    │   ├── crop.py                 # crop_netcdf/crop_to_country (cdo subprocess)
    │   └── __init__.py             # façade
    ├── providers/
    │   ├── base.py                # WeatherProvider Protocol
    │   ├── base_downloader.py     # is_complete→skip / _fetch ; DownloadJob
    │   ├── base_decompressor.py   # is_decompressed→skip / _decompress_file
    │   ├── base_percentile.py     # unused/dead code — see percentile_index.py
    │   ├── README.md
    │   ├── cosmo_rea6/            # PRODUCTION (reference impl)
    │   │   ├── config, downloaded_attributes, naming
    │   │   ├── download, downloader, decompress, decompressor
    │   │   ├── transform, export, pipeline, percentile_index, __init__
    │   ├── era5_land/             # pipeline DONE; bulk-run pending
    │   │   ├── config, downloaded_attributes
    │   │   ├── downloader, fast_download, download
    │   │   ├── transform, export, pipeline, pipeline_interleaved
    │   │   ├── percentile_index, dni_pointwise, __init__
    │   └── merra2/                # pipeline DONE; 2018 verified live
    │       ├── config, downloaded_attributes
    │       ├── downloader (OPeNDAP + Earthdata session), download
    │       ├── transform, export, pipeline
    │       ├── percentile_index, dni_pointwise, __init__
    └── tests/                      # runners + tools + pytest units
        ├── (pytest) test_validation, test_derived_attributes,
        │            test_pipeline_integration
        ├── (COSMO)  test_cosmo_one_month, test_cosmo_one_year,
        │            test_cosmo_multi_year
        ├── (ERA5)   test_era5_one_month, test_era5_one_year,
        │            test_era5_multi_year
        ├── (ERA5 tools) repair_month_boundaries, verify_months,
        │            diagnose_nc, enumerate_month, check_boundary_steps,
        │            check_first_hour, inspect_era5_eccodes,
        │            inspect_era5_grib, audit_imports
        ├── (MERRA-2) test_merra2_one_month, test_merra2_one_year,
        │            test_merra2_multi_year, verify_merra2_months
        ├── compare_providers         # cross-provider (COSMO/ERA5/MERRA-2)
        │            point + domain comparison; xlsx + matplotlib report
        └── mock_download            # CI helper
```

## Provider module roles (uniform)

config.py (EnvSettings→dict) · downloaded_attributes.py (raw-attr DICT) ·
naming.py (filenames/URLs; COSMO) · downloader.py (`BaseDownloader`) ·
download.py (orchestration) · decompress[or].py (`BaseDecompressor`; COSMO
bz2 only) · transform.py (raw→analysis-ready) · export.py (NetCDF, zlib
complevel=1, float32) · pipeline.py (`run_pipeline(year, months=None,
...) -> list[Path]`; wire phases; per-month resume; idempotent — same
shape across all three providers as of this session, see NEXT MAJOR
TASKS item 6) · percentile_index.py (standalone KS-distance P10/P50/P90
script; optional) · `__init__.py` (façade; CLI adapter absorbs
COSMO-flavoured `weather run` kwargs it doesn't need, matching
`ERA5LandProvider`/`MERRA2Provider`). Every `test_<provider>_
{one_month,one_year,multi_year}.py` is a thin CLI shim over its
provider's `run_pipeline()` — no pipeline logic in `tests/` itself;
shared flags come from `common/cli_flags.py`.

## Providers at a glance (from source)

| provider   | source           | res        | files              | output         | ncores   |
|------------|------------------|------------|--------------------|----------------|----------|
| cosmo_rea6 | DWD OpenData     | 6 km       | monthly bz2        | monthly→annual | 94 (CPU) |
| era5_land  | Copernicus CDS   | 0.1°       | monthly nc         | monthly        | 6 (I/O)  |
| merra2     | GES DISC OPeNDAP | 0.5×0.625° | daily nc4, 3 coll. | monthly        | 8 (I/O)  |

- **RH source differs BY-DESIGN:** COSMO direct RELHUM_2M; ERA5-Land
  dew-point Magnus; MERRA-2 q-based (Bolton 1980). Do NOT unify — but
  each provider's OWN formula is now single-sourced (see next bullet).
- **Radiation:** COSMO splits direct(SWDIRS)+diffuse(SWDIFDS); ERA5-Land &
  MERRA-2 give GHI directly (ssrd-derived / SWGDN).
- `common/derived_attributes.apply_derived_fields(ds, provider, sol_pos,
  times)` is the registry/testable-in-isolation entry for GHI/DHI/DNI/RH/
  WS_10M (plain numpy or xarray in, works on tiny synthetic 1-D test
  fixtures — see `tests/test_derived_attributes.py`). The gridded
  production pipelines (each provider's `transform.py`) do NOT call
  `apply_derived_fields` directly (COSMO/ERA5-Land need dask-chunked
  xarray-native code for grid-scale performance) — instead, as of this
  session, every provider's `transform.py` imports and calls the SAME
  underlying pure formulas (`wind_speed`, `magnus_rh`, `bolton_rh`,
  `ghi_from_diffuse_direct`, `dni_from_direct` — all in
  `derived_attributes.py`; `spencer_zenith` in `solar_position.py`) that
  the registry also calls, closing a real drift risk: `derived_attributes
  .py`'s copies used to be independently hand-duplicated versions of each
  provider's `transform.py` math (2 concrete bugs found and fixed: COSMO
  GHI wasn't clipping each component before summing, and COSMO DNI was
  missing the upper cos(zenith) bound — see docs/dni_methodology.md §5).
  All providers night-mask + enforce GHI=DHI+DNI·cos(zenith); DNI
  cos-guard at zenith>85 (`derived_attributes.DNI_ELEVATION_THRESHOLD_DEG`,
  imported by COSMO's `compute_dni` rather than a separate hardcoded
  literal). (ERA5 pipeline's `night_mask=False` default concerns the
  monthly GHI field, distinct from this DNI-path masking.)
- **Cross-provider comparison:** `tests/compare_providers.py` — point-wise
  (DNI/DHI/GHI/T/RH/SF/ALBEDO) + whole-Europe domain stats across all three
  2018 outputs; xlsx (one sheet/provider) + csv/parquet + matplotlib. Real,
  documented differences (not bugs — see `docs/provider_differences.md`
  for the quantified numbers and physical explanations): MERRA-2 RH reads
  ~6 pts higher than ERA5-Land (different formula families — Magnus vs
  specific-humidity-based, by design, do NOT unify); ERA5-Land/MERRA-2
  albedo agree closely in summer, diverge most in the snow-transition
  months; COSMO/ERA5-Land snowfall monthly totals are similar but hourly
  timing barely correlates (r≈0.4) — different resolution/microphysics.
  A COSMO-only `dni_method_comparison()` cross-checks its native exact
  DNI/DHI (`SWDIRS_RAD`/cos(θz), Spencer solar position — NOT a GHI
  decomposition) against pvlib's exact closure formula with NREL SPA
  zenith (isolates solar-position precision) and, for reference only,
  pvlib DIRINT (a GHI-only decomposition — the wrong tool for COSMO,
  since its DHI is already known, but the only option ERA5-Land/MERRA-2
  have; see `docs/dni_methodology.md` sec 11). This script still
  reconstructs COSMO's lat/lon analytically from the rotated-pole grid
  definition (best-effort, not verified against DWD's CONST file) — it
  has not been switched over to the real per-cell coordinates
  `transform.py` now retains (see NEXT MAJOR TASKS item 5), since the
  already-completed COSMO 2018 archive this script reads predates that
  fix. COSMO RH
  (`RELHUM_2M`, wired end-to-end via `downloaded_attributes.py`'s
  `role`/`canonical_name` fields and `transform.build_month_dataset`)
  and MERRA-2 snowfall/snow-depth (`PRECSNOLAND`/`SNODP`, the `lnd`
  collection) both now appear in the live-regenerated 2018 data (see
  the MERRA-2/COSMO providers table note below). COSMO ALBEDO remains
  deliberately unbuilt: the downstream consumer that raised the question
  (`pysam-photovoltaic-energy-simulation`) turned out to need only a
  snow-depth-driven threshold, not real optical albedo, and COSMO
  already has the equivalent field (`H_SNOW`) — see `compare_providers
  .py`'s `SNOW_DEPTH` column and its module docstring. A true optical
  albedo stays a documented option via DWD's `SOBS_RAD` (net shortwave,
  instantaneous — NOT `ASOB_S`, its average-type sibling): `albedo =
  ((SWDIRS_RAD + SWDIFDS_RAD) - SOBS_RAD) / (SWDIRS_RAD + SWDIFDS_RAD)`,
  not built since no confirmed consumer needs it.

## Country bbox + cropping (`geo/`)

`weather.geo` exists so the downstream consumer
`THD-Spatial-AI/merra2-energy-pipeline` doesn't need its own country-bbox
or cropping logic — it should only do energy-potential analysis on data
this repo has already cropped to the country it needs.

- `countries.get_bbox(name)` / `list_countries()` — ~30 European
  countries, trimmed port of that repo's `countries.py`: dropped the
  `TIMEZONES` table and the German/French/English multilingual alias
  table entirely (not partially kept); the pan-Europe entry is also
  dropped since it's already the implicit default domain for every
  provider here. `uk`/`united_kingdom` and `czech_republic`/`czechia`
  remain as independent canonical entries (that's how upstream defined
  them, not an alias lookup).
- `bbox.BBox(north, west, south, east)` — canonical field order matches
  this repo's own existing convention (`ERA5_AREA`/`MERRA2_AREA`, both
  `[N,W,S,E]`), so `COUNTRIES` values are a drop-in for that env-var
  pattern via `.to_area_list()`. CDO's `sellonlatbox` uses a **different**
  axis order (`west,east,south,north`); `.to_cdo_lonlatbox()` converts
  explicitly rather than leaving that to be re-derived per call site.
- `crop.crop_netcdf()` / `crop.crop_to_country()` — real cropping (not a
  lookup): subprocess wrapper around `cdo sellonlatbox`, atomic tmp-file
  and rename like `common/decompress.py`. **Works today for ERA5-Land
  and MERRA-2** output NetCDFs (regular, CF-compliant lat/lon grid).
  **Does not yet work for COSMO-REA6** — `transform.py` now retains the
  2-D WGS84 lat/lon cfgrib decodes (previously dropped by
  `_strip_scalar_coords` before export; see NEXT MAJOR TASKS item 5 and
  `.claude/open.md`), but the already-completed COSMO archive predates
  that fix and still has no lat/lon at all — needs a transform+export
  rerun before `weather geo crop` can be tried against it.
- **Not wired into any provider's `pipeline.py`.** `weather geo crop` is
  a standalone post-processing step run against an already-exported
  output file, by design — ask before auto-wiring it into `run_pipeline()`.

## Hard conventions (do not violate)

1. **Global imports only.** numpy/xarray/pandas/cfgrib at module top, never
   inside functions. Exception: optional dep in `try/except ImportError`
   (e.g. bottleneck). A local-import bug already cost a full failed run.
   Audit: `tests/audit_imports.py`. (Some COSMO modules still import inside
   functions — clean up when touched.)
2. **Extensibility via DICTs.** Raw attrs in `downloaded_attributes.py`;
   derived vars registered in `derived_attributes.py`. Add/remove = data
   edit, not code change.
3. **Simple, direct solutions.** Automate over hand-maintain; decide over
   asking repeatedly.
4. `from __future__ import annotations` in every module. NumPy docstrings;
   type hints; `logging` not print. Atomic writes (temp→rename).
   `HDF5_USE_FILE_LOCKING=FALSE` for NetCDF on parallel FS.
5. Python 3.12+; src-layout; setuptools-scm (never commit `_version.py`).
6. **One centralized default per cross-cutting knob, not one per
   entrypoint.** e.g. `COSMO_CLEANUP`/`ERA5_CLEANUP`/`MERRA_CLEANUP`
   (`EnvSettings.*_cleanup()` -> each `config.py`'s `cfg["cleanup"]`) is
   the single default every `pipeline.py`'s `run_pipeline(cleanup: bool
   | None = None, ...)` resolves from, and every `test_<provider>_
   one_month/one_year/multi_year.py`'s own positive `--cleanup` CLI flag
   (declared via the shared `common/cli_flags.add_cleanup_flag()` —
   the one place that argparse wiring happens, so no script can drift
   onto a different flag polarity/name) resolves from too; same pattern
   for `*_FROM_YEAR`/`*_TO_YEAR`
   (`EnvSettings.*_from_year()`/`*_to_year()`) on the three
   `multi_year.py` scripts' `--from-year`/`--to-year` defaults — change
   the env var once, every entrypoint picks it up; the CLI flag still
   overrides per-invocation. Don't hardcode a knob's default
   independently at each call site.
7. **No `sys.path` manipulation.** `weather` is always `pip install -e .
   --no-deps` (see packaging, above) — every module/script imports it
   directly (`from weather.x import y`), never via a `sys.path.insert`
   bootstrap. (`sys.path` controls the *import* search path, an
   unrelated concern from `pathlib`/`os.path`, which build filesystem
   path strings — swapping one for the other isn't a fix; the fix is
   relying on the editable install, which the project already mandates.)

## Environment

conda env `weather_env`; prefer conda. Dev Windows; prod Linux `sd26`
(user `sahoo002`), 94 cores, 1 TB RAM, 15 TB disk. GitHub `UU-BUEM`.
