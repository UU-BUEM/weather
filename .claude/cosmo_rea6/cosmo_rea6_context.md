# COSMO-REA6 — engineering context

Confidence: HIGH (from actual source). Reference provider the others follow.

## Source & format
- DWD OpenData, free HTTPS, no creds. Base URL (env `COSMO_BASE_URL`):
  `.../REA/COSMO_REA6/hourly/2D`. Files: one per attr per month,
  `{ATTR}.2D.{YYYYMM}.grb.bz2`, URL `{base}/{ATTR}/{fname}` (naming.py).
- ~6 km, CORDEX-EU11, **rotated-pole**; dims `y`/`x`. Winds U_10M/V_10M in
  rotated-pole grid-north (kept as-is, both as raw components in the
  output AND as derived `WS_10M` — fixed 2026-07-30 to also keep the
  raw components, matching ERA5-Land/MERRA-2, which always did; COSMO
  used to be the only one of the three that discarded them). Coverage
  1995–2019 (validate enforces).

## Raw attributes (11) — downloaded_attributes.py (DICT)
H_SNOW(m, canonical_name SNOW_DEPTH), PS(Pa), RELHUM_2M(%, canonical_name
RH), SNOW_CON(kg/m², formula — feeds combined SNOWFALL), SNOW_GSP(kg/m²,
formula — feeds combined SNOWFALL), SOBS_RAD(W/m², formula — feeds
derived ALBEDO, added 2026-07-26), SWDIFDS_RAD(W/m², diffuse, instant),
SWDIRS_RAD(W/m², direct, instant), T_2M(K→°C), U_10M, V_10M(m/s). Keys:
dwd_name, description, unit_raw, unit_target, conversion, **role**
(`"formula"` vs `"passthrough"` — single source of truth for which
attrs need hand-written derivation code vs generic assembly),
**canonical_name** (output var name when it differs from the key, e.g.
RELHUM_2M → RH, H_SNOW → SNOW_DEPTH). `pipeline.py::run_pipeline()`
reads attributes straight from `config.get_config()["attributes"]`
(itself `list(ATTRIBUTES.keys())`) — the old hand-duplicated `_ALL_ATTRS`
list in `test_cosmo_one_month.py` that used to silently drop RELHUM_2M
(see `.claude/open.md`) no longer exists; there is nothing left to drift
out of sync. `transform.build_month_dataset()` is the one shared
per-month assembly function; `pipeline.py::run_pipeline()` is the one
shared orchestrator (download → decompress → per-month transform+export)
that `test_cosmo_one_month.py`/`test_cosmo_one_year.py` call into — see
"Pipeline architecture" below.

## Key contrasts (do NOT unify)
- **RH DIRECT** (RELHUM_2M, %). COSMO does NOT compute RH — it's a raw
  model field, passed through as-is (unlike ERA5 dew-point Magnus or
  MERRA-2 q-based). Wired end-to-end in code as of this session, but the
  2018 data on disk predates the fix — needs a re-run to actually appear.
- **lat/lon now retained** (`build_month_dataset`/`build_annual_dataset`):
  cfgrib already decodes real 2-D WGS84 `latitude`/`longitude` from the
  source GRIBs, but `_strip_scalar_coords` used to drop them (it drops
  *all* non-dimension coords, not just scalar ones) before export —
  fixed for `point_query.get_point_weather`/`weather.geo.crop` (see
  `.claude/open.md`'s `## geo`/`## point_query`). Verified against real
  DWD data this session (Feb 2018, via the refactored
  `test_cosmo_one_month.py` -> `pipeline.py::run_pipeline()`):
  lat/lon present, `get_point_weather(provider="cosmo-rea6")` round-trips
  correctly. Same pattern as RH above still applies to the *existing*
  archive though: **the already-completed multi-year COSMO archive on
  `sd26` predates this fix and has no lat/lon at all — still needs a
  transform+export re-run there** (not download/decompress/percentile)
  before point-query or cropping work against it.
- **COSMO now has a derived ALBEDO** (2026-07-26, reversing an earlier
  "no albedo field exists for COSMO" note): no DWD-native albedo field,
  but `SOBS_RAD` (net shortwave at surface, in DWD's parameter table —
  NOT `ASOB_S`, its average-type sibling) enables `ALBEDO = (GHI -
  SOBS_RAD) / GHI` (`transform.compute_albedo`), NaN at night. ERA5-Land's
  `fal` renamed to `ALBEDO` too, for a shared canonical name across all
  three providers. See `.claude/open.md`'s `## cosmo_rea6` entry.
- **Radiation split at source:** SWDIFDS(diffuse)+SWDIRS(direct), both
  instant. `derived_attributes` builds GHI/DHI/DNI: DHI=SWDIFDS,
  DNI=SWDIRS/cos(zenith) (horizon-divergent → COSMO needs Spencer-SZA
  night-mask; ERA5/MERRA-2 give GHI directly and use DIRINT).
- **Output is per-MONTH, not annual**, as of this session:
  `pipeline.py::run_pipeline()` now calls `build_month_dataset()` in a
  per-month loop (matching ERA5-Land/MERRA-2's shape), writing 12
  separate `COSMO_REA6_<YYYY>_<MM>_all_attrs.nc` files directly — it no
  longer calls `build_annual_dataset()` (which is now unused outside its
  own definition and docstring cross-references; not deleted, since that
  wasn't part of this session's scope — flag before removing it).
  `percentile_index.py` (the actual percentile script) reads the MONTHLY
  files directly, so this change doesn't affect it — it never depended
  on an annual-merge step, despite older docs describing one. ERA5-Land
  is per-MONTH natively too, so its `percentile_index.py` port needed no
  merge step either. An annual *merge* (concatenating the 12 monthly
  files into one) is still available as an explicit post-processing step
  via `weather.common.merge`, unchanged.
- **CPU-bound** (bz2): COSMO_NCORES=94, THREADS_PER_JOB=1. Don't copy 94 to
  I/O-bound providers.

## Pipeline (3 phases) — all in `pipeline.py::run_pipeline(year, months=None, ...)`
1 Bulk download (ThreadPool, `download.download_all(months=...)`): all
  (month × attr) .grb.bz2 in parallel; `download.verify_downloads()`
  checks against DWD's Content-Length afterwards; skip if already valid.
2 Bulk decompress (ProcessPool, `decompress.decompress_all(months=...)`):
  bz2→GRIB via lbzip2>pbzip2>python-bz2 (COSMO_DECOMPRESSOR); atomic;
  `decompress.verify_decompressed()` checks GRIB magic + expansion
  afterwards; bz2 cleanup gated on both checks passing.
3 Transform+Export, sequential per month (bounded ~30 GB peak/month):
  `transform.build_month_dataset()` → derived (GHI/DHI/DNI/T/WS) →
  `export.export_netcdf()` (zlib complevel=1, float32) →
  `transform.log_dni_stats()`/`report_dni_outliers()` → cleanup this
  month's decompressed GRIB/idx/lock (glob-aware — see "Touch-ups" for
  the hash-suffix bug this fixed). `resume=True` skips months whose
  output already exists (upfront, before phases 1-2 even run for them).
`--cleanup` (positive flag, `common/cli_flags.add_cleanup_flag()` —
renamed from the old `--no-cleanup` this session for parity with
ERA5-Land/MERRA-2) controls all of it; each phase idempotent regardless.
`test_cosmo_one_month.py`/`test_cosmo_one_year.py` are thin CLI wrappers
around this function — no pipeline logic lives in `tests/` anymore.

## Shared bases (providers/)
base_downloader (is_complete→skip/_fetch; DownloadJob(attr,year,month)),
base_decompressor (is_decompressed→skip/_decompress_file), base.py
(WeatherProvider Protocol). base_percentile.py (BasePercentileAnalyzer)
exists in-tree but is DEAD CODE — no provider uses it (see below).

## percentile_index.py (resolved gotchas)
The PRODUCTION percentile script — standalone, does NOT subclass
`base_percentile.BasePercentileAnalyzer` (that older `percentile.py` /
`CosmoPercentileAnalyzer` design was deleted in commit `17d5eea` and
replaced with this Finkelstein-Schafer KS-distance implementation).
P10/P50/P90 GHI mosaics 1995–2018, per-cell KS-distance match to pooled
thresholds on daily GHI sums. Gotchas: 2 mosaic workers; engine="netcdf4";
CuPy/GPU conflicts w/ spawned workers; NFS write-lock → local /tmp then
move; dims y/x (not rlat/rlon); OOM from stacking all years avoided by
processing per-month with straggler-hiding; submission timeout killed
queued months (none set — let months run to completion). numba IS used
here (`WEATHER_USE_NUMBA_KS=1`) — the
`.github/skills/weather-runtime-error-debug` SKILL defaults to numba-first
for this hot path. ERA5-Land's `percentile_index.py` is a direct
structural port of this file.

## Env (.env)
COSMO_WORK_DIR, COSMO_BASE_URL, COSMO_CONST_URL, COSMO_NCORES=94,
COSMO_THREADS_PER_JOB=1, COSMO_DECOMPRESSOR, COSMO_LOG_DIR, COSMO_YEAR.

## Touch-ups (low priority)
export.py docstring references old `buem.weather` path; export.py/pipeline.py
have some local imports (hoist to module level); reconcile local naming.py
with GitHub main.

FIXED this session: the per-month GRIB cleanup guessed the cfgrib index
sidecar filename as `<grib_name>.idx`, but cfgrib actually names it
`<grib_name>.<content-hash>.idx` (confirmed from a real rerun's log,
e.g. `H_SNOW.2D.201801.grb.5b7b6.idx`) — the guess never matched, so
`.idx` deletion silently no-op'd every time, orphaning it once its
parent `.grb` was deleted. This is exactly what was found on the `sd26`
production server (`decompress/` had only ~70 KB of stray `.idx` files
left, `.grb`/`.bz2` all gone). Now globs `<grib_name>.*.idx` too; lives
in `pipeline.py::run_pipeline()`'s per-month cleanup block (moved there
from `test_cosmo_one_year.py` along with the rest of the pipeline logic
— see CLAUDE.md NEXT MAJOR TASKS item 6).
