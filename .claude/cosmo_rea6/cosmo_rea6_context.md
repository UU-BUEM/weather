# COSMO-REA6 — engineering context

Confidence: HIGH (from actual source). Reference provider the others follow.

## Source & format
- DWD OpenData, free HTTPS, no creds. Base URL (env `COSMO_BASE_URL`):
  `.../REA/COSMO_REA6/hourly/2D`. Files: one per attr per month,
  `{ATTR}.2D.{YYYYMM}.grb.bz2`, URL `{base}/{ATTR}/{fname}` (naming.py).
- ~6 km, CORDEX-EU11, **rotated-pole**; dims `y`/`x`. Winds U_10M/V_10M in
  rotated-pole grid-north (kept as-is). Coverage 1995–2019 (validate
  enforces).

## Raw attributes (10) — downloaded_attributes.py (DICT)
H_SNOW(m), PS(Pa), RELHUM_2M(%), SNOW_CON(kg/m²), SNOW_GSP(kg/m²),
SWDIFDS_RAD(W/m², diffuse, instant), SWDIRS_RAD(W/m², direct, instant),
T_2M(K→°C), U_10M, V_10M(m/s). Keys: dwd_name, description, unit_raw,
unit_target, conversion.

## Key contrasts (do NOT unify)
- **RH DIRECT** (RELHUM_2M, %). COSMO does NOT compute RH. (ERA5 dew-point
  Magnus; MERRA-2 q-based.)
- **Radiation split at source:** SWDIFDS(diffuse)+SWDIRS(direct), both
  instant. `derived_attributes` builds GHI/DHI/DNI: DHI=SWDIFDS,
  DNI=SWDIRS/cos(zenith) (horizon-divergent → COSMO needs Spencer-SZA
  night-mask; ERA5/MERRA-2 give GHI directly and use DIRINT).
- **Output ANNUAL:** `build_annual_dataset` → merged. `percentile_index.py`
  (the actual percentile script) reads the MONTHLY files directly though —
  no annual-merge step in its pipeline, despite older docs describing one.
  ERA5-Land is per-MONTH natively, so its `percentile_index.py` port needed
  no merge step either.
- **CPU-bound** (bz2): COSMO_NCORES=94, THREADS_PER_JOB=1. Don't copy 94 to
  I/O-bound providers.

## Pipeline (3 phases)
1 Download (ThreadPool): 10 attrs×12mo → .grb.bz2; skip if valid.
2 Decompress (ProcessPool): bz2→GRIB via lbzip2>pbzip2>python-bz2
  (COSMO_DECOMPRESSOR); atomic; skip if valid (size>compressed).
3 Transform+Export: cfgrib → derived (GHI/DHI/DNI/T/WS) → export_netcdf
  (zlib complevel=1, float32). Optional --cleanup. Each phase idempotent.

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
