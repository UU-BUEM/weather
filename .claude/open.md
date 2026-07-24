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
- [merra2] DONE (code): added the `lnd` collection (`M2T1NXLND`:
  `SNODP`, `PRECSNOLAND`) and `U50M`/`V50M` (free within the existing
  `slv` collection) — needed by a confirmed downstream consumer
  (github.com/THD-Spatial-AI/merra2-energy-pipeline). 3 collections now,
  not 2. `build_monthly_dataset()`'s signature changed (new `lnd_paths`
  positional arg); the one caller (`pipeline.py`) updated. Verified
  against synthetic local NetCDF4 files, **not** a live GES DISC
  download — no network download triggered. See
  `docs/MERRA2_PIPELINE_GUIDE.md` and `.claude/merra2/merra2_context.md`.
- [geo] DONE (code): new `src/weather/geo/` package (`countries.py`,
  `bbox.py`, `crop.py`) + `weather geo {crop,list}` CLI — moves country
  bbox lookup and real NetCDF cropping (`cdo sellonlatbox`) into this
  repo so `merra2-energy-pipeline` doesn't need its own copy. Trimmed
  from that repo's `countries.py`: no `TIMEZONES`, no German/French/
  English alias table, no pan-Europe entry. `cdo` added to
  `weather_env.yml`. Not live-tested against `cdo` on this machine (not
  installed here; `ruff`/`mypy` pass, pure-logic unit tests written but
  **not run** — this dev machine's `weather_env` has a pre-existing,
  unrelated numpy+pytest crash on Windows, `blas_fpe_check` raising a
  fatal exception on `import numpy` under pytest's rewrite loader,
  reproduces even on a trivial numpy-only test and on existing
  unmodified test files — needs investigating separately, e.g. via CI or
  a fresh env). See the `## geo` section below for the COSMO limitation.

## geo
- [geo] COSMO-REA6 cannot be cropped by `weather.geo.crop` yet: its
  production export has no lat/lon coordinates at all (only rotated-pole
  `rlat`/`rlon` dims). cfgrib does write 2-D WGS84 `latitude`/`longitude`
  during `transform.py`, but only the experimental/unused `compute_dni()`
  diagnostic reads them (`transform.py:434-439`) — the real assembly
  path drops them before export. Fixing this needs a COSMO export change
  (attach lat/lon as auxiliary coords, or a CF `grid_mapping` variable so
  `cdo` can crop the rotated grid directly) — deliberately not attempted
  as part of the `geo/` submodule to avoid scope creep on an unrelated
  pipeline.
- [geo] `weather_env`'s local pytest crash (see above) blocked running
  `test_geo_countries.py` on this dev machine — re-run once that's fixed
  or via CI.

## era5_land
- [era5_land] Bulk 1950–2025 run not yet executed — see plan checklist.
  Apply _ffill_time import fix first.
- [era5_land] After run: MANDATORY repair_month_boundaries.py then
  verify_months.py before merge/percentile.
- [era5_land] pipeline_interleaved.py deferred (deliberately).

## cosmo_rea6
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
- [cosmo_rea6] ALBEDO — the downstream PV consumer that motivated this
  question (`pysam-photovoltaic-energy-simulation`, `scripts/main.py`)
  turned out NOT to need a real optical albedo field at all: it derives
  a crude threshold albedo purely from *snow depth*
  (`0.6 if snow_depth_cm > 1 else 0.2`, fed from MERRA-2's `SNODP`).
  COSMO already has the equivalent field — `H_SNOW` (physical snow
  depth, meters, `role: "passthrough"`) — downloaded since the original
  run, so **no new attribute or code was needed** to satisfy this
  consumer. A *real*, physically-derived COSMO albedo remains a
  documented option if some future consumer needs true optical albedo
  rather than a snow-depth proxy: DWD's full parameter table
  (`ParameterTables_REA6.pdf`) lists `SOBS_RAD` (net shortwave,
  instantaneous — NOT `ASOB_S`, its average-type sibling), giving
  `albedo = ((SWDIRS_RAD+SWDIFDS_RAD) - SOBS_RAD) / (SWDIRS_RAD+
  SWDIFDS_RAD)`. Deliberately not built — no confirmed consumer needs it
  today. `compare_providers.py` now compares `SNOW_DEPTH` across all
  three providers (COSMO `H_SNOW`, MERRA-2 `SNODP` — both physical
  depth in m and directly comparable; ERA5-Land `sd` — water-equivalent
  depth, NOT directly comparable without a density conversion, see that
  module's docstring).

## cross-provider
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
