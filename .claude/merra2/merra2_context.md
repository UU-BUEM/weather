# MERRA-2 — engineering context

Confidence: HIGH — implementation complete AND verified live. Full 2018
(12 months, all 3 collections incl. `lnd`) re-run against real GES DISC
data, checked with `tests/verify_merra2_months.py` (correct hour counts,
`HH:30` span, no gaps, plausible NaN/min-max on all variables incl.
`SNODP`/`PRECSNOLAND`/`U50M`/`V50M`). See `docs/MERRA2_PIPELINE_GUIDE.md`
for the checklist and the `export_netcdf` skip-if-exists bug found and
fixed during this rerun (also affected COSMO-REA6 and ERA5-Land's
`export.py` — see `.claude/open.md`).

## Status

- `downloaded_attributes.py`: COMPLETE — 14 raw attrs across 3
  collections (see below), each tagged with a `collection` field;
  `attrs_by_collection()` groups them for the downloader.
- `config.py`: COMPLETE — adds `area` (Europe box, `EnvSettings
  .merra2_area()`) and `opendap_max_concurrent` on top of the
  pre-existing `MERRA2_*`/`MERRA_*` env-backed keys.
- `downloader.py`: COMPLETE — `Merra2DownloadJob` (collection, year,
  month, day), all 3 `BaseDownloader` methods implemented (OPeNDAP
  constraint-URL construction, existence-based completeness, streamed
  fetch via an Earthdata-authenticated, redirect-safe session).
- `download.py`: COMPLETE — `download_all()` expands to one job per
  (collection, day), parallelized via `common.parallel.run_parallel`.
- `transform.py`: COMPLETE — merges rad+slv daily files into a monthly
  dataset, converts units, derives GHI (via the registry, GHI-only),
  `WS_10M`, and a new specific-humidity-based RH formula.
- `export.py` / `pipeline.py`: COMPLETE — near-verbatim ERA5-Land
  pattern (zlib complevel=1, float32; download -> transform+export per
  month via `ProcessPoolExecutor`; no decompress phase).
- `__init__.py`: COMPLETE — `MERRA2Provider` implements the full
  `WeatherProvider` protocol; `validate_environment()` reuses
  `common.net.earthdata_auth()` rather than reimplementing credential
  checks.
- Test scripts added: `test_merra2_one_month.py`, `test_merra2_one_year
  .py`, `test_merra2_multi_year.py` — mirror the ERA5-Land equivalents'
  CLI flags exactly (no `--night-mask`, since GHI is always
  night-masked unconditionally, no opt-in toggle needed).
- Shared infra change: `common/net.py`'s `build_session()` gained a
  `preserve_auth_hosts` parameter (see below) — used only by MERRA-2
  today, but generic enough for any future Earthdata-style provider.

## Source & format

- NASA GES DISC, accessed via **OPeNDAP** (not plain full-file HTTPS).
  Server-side bbox subsetting means no global daily file is ever
  downloaded — only the configured Europe box.
- Auth: free Earthdata account -> `EARTHDATA_USERNAME`/
  `EARTHDATA_PASSWORD` env vars, or `~/.netrc` (`machine
  urs.earthdata.nasa.gov`) — see `weather.common.net.earthdata_auth()`.
  NASA's URS<->GES-DISC redirect chain strips `Authorization` by
  default; `common.net.build_session(preserve_auth_hosts={...})` fixes
  this (see `Merra2Downloader._get_session`).
- 0.5°x0.625°, hourly. **Files per-DAY nc4** (not per-month like
  ERA5-Land), addressed via `Merra2DownloadJob(collection, year, month,
  day)` — sanctioned by `base_downloader.py`'s own docstring, which
  names MERRA-2 as the provider expected to define its own job type.
- **3 collections**: `M2T1NXRAD.5.12.4` (`rad`: `SWGDN`, `ALBEDO`),
  `M2T1NXSLV.5.12.4` (`slv`: `T2M`, `T2MDEW` (added 2026-07-26, free —
  same collection, canonical output `T_DEW`), `QV2M`, `U2M`, `V2M`,
  `U10M`, `V10M`, `U50M`, `V50M`, `PS`), and `M2T1NXLND.5.12.4` (`lnd`:
  `SNODP`,
  `PRECSNOLAND`). `lnd` added because a confirmed downstream consumer
  (github.com/THD-Spatial-AI/merra2-energy-pipeline,
  `src/data_pipeline/config.py`) needs `SNODP`/`PRECSNOLAND` for its PV
  snow-loss model and `U50M`/`V50M` (hub-height wind) for its wind
  model — `U50M`/`V50M` came free within the already-fetched `slv`
  request. `build_monthly_dataset()` now takes `(rad_paths, slv_paths,
  lnd_paths, *, year, month)` — was `(rad_paths, slv_paths, ...)`, a
  breaking signature change; the one caller (`pipeline.py`'s
  `_transform_export_one`) was updated. `PRECSNOLAND` arrives as
  kg/m^2/s, converted to kg/m^2/h in `_convert_units` to match COSMO's
  SNOW_GSP+SNOW_CON / ERA5-Land's `sf` convention. Verified against
  synthetic local NetCDF4 files (not live GES DISC — no download
  triggered).
- Host `goldsmr4.gesdisc.eosdis.nasa.gov`. No decompression (NetCDF4
  throughout). Output is **monthly** (`MERRA2_<YYYY>_<MM>_all_attrs.nc`),
  matching ERA5-Land's convention — not annual like COSMO.

## Raw attributes (9) — downloaded_attributes.py (DICT)

RAD: `SWGDN` (W/m^2, = GHI directly, instantaneous — no de-accum, no
boundary problem, simpler than ERA5-Land's accumulated `ssrd`),
`ALBEDO` (dimensionless fraction).
SLV: `T2M` (K->degC), `QV2M` (kg/kg, specific humidity — feeds RH),
`U2M`/`V2M`/`U10M`/`V10M` (m/s), `PS` (Pa).
Keys: `m2_name`, `collection`, `description`, `unit_raw`, `unit_target`,
`conversion`.

## Key contrasts (do NOT unify)

- **RH is specific-humidity-based** (`QV2M` + `T2M` + `PS` -> vapor
  pressure -> Bolton 1980 saturation curve), not dew-point (ERA5-Land's
  Magnus) nor direct % (COSMO's `RELHUM_2M`). Ordering note: unlike
  ERA5-Land, this formula needs `T2M` in **Celsius** (post-conversion),
  not Kelvin — see `transform._compute_rh`'s docstring and
  `docs/MERRA2_PIPELINE_GUIDE.md`.
- **GHI = SWGDN directly**, instantaneous — no de-accumulation, no
  month-boundary repair script needed (unlike ERA5-Land's `ssrd`).
- **DNI/DHI intentionally NOT computed in bulk** — the registry's
  DIRINT-based formulas are 1-D-per-site and can't broadcast over the
  full grid (same limitation ERA5-Land hit). `transform.py` requests
  only `fields=["GHI"]` from `apply_derived_fields`. A future
  `merra2/dni_pointwise.py` (mirroring ERA5-Land's) is documented, not
  built.
- Europe footprint: same box as ERA5-Land (`N,W,S,E = 72,-11,34,32`),
  but on MERRA-2's own native 0.5°x0.625° grid — **not** regridded/
  interpolated onto ERA5-Land's 0.1° grid. Cross-provider regridding is
  a separate future task if ever needed.
- **Output naming (2026-07-26 rename, see `.claude/open.md`'s
  `## cross-provider` entry)**: raw `m2_name`s above are unchanged, but
  `transform.py` now renames on export: `T2M`→`T` (pre-existing),
  `T2MDEW`→`T_DEW` (new attr added same day — free, same `slv`
  collection already fetched; matches COSMO's derived `T_DEW` and
  ERA5-Land's renamed `d2m`), `U10M`/`V10M`→`U_10M`/`V_10M`,
  `U2M`/`V2M`→`U_2M`/`V_2M`, `U50M`/`V50M`→`U_50M`/`V_50M`,
  `SNODP`→`SNOW_DEPTH` (same physical quantity as COSMO's renamed
  `H_SNOW`), `PRECSNOLAND`→`SNOWFALL` (matches ERA5-Land's renamed
  `sf`/COSMO's combined `SNOW_CON`+`SNOW_GSP`). `PS`/`QV2M`/`ALBEDO`
  were already canonical, unchanged. Not yet live-tested — takes effect
  on the next MERRA-2 rerun; the already-completed 46-year archive
  still has the raw names above (and no `T2MDEW` at all — needs a
  rerun to appear, unlike the other renames which are just a schema
  change on data already fetched).
- **Live-tested 2026-07-30** (`test_merra2_one_month.py --year 2018
  --month 3`, fresh real GES DISC download, ~52s total): all 16
  variables present incl. `T_DEW`/`U_50M`/`V_50M`. **Real finding, NOT
  a pipeline bug**: MERRA-2's native `T2MDEW` violates `T_DEW <= T`
  in ~3.2% of finite (time, y, x) triples (up to 3.74 K over T,
  mean/median excess 0.45/0.32 K when it happens) — confirmed present
  in the RAW downloaded daily NC4 file itself (checked directly,
  before any of our pipeline's merge/convert code touches it), so this
  is a genuine NASA/GEOS-5 diagnostic-consistency characteristic, not
  something introduced here. Contrast: COSMO's derived `T_DEW` (0
  violations, mathematically guaranteed by construction) and
  ERA5-Land's native `d2m` (0 violations across ~62M points, checked
  the same day against real 2018-03 data — ECMWF's own dew-point
  diagnostic is fully self-consistent with its `T2M`). Only ~43% of
  MERRA-2's violations are near-saturation/sub-freezing (where an
  ice-vs-liquid saturation-curve subtlety could partly explain a small
  Td>T reading); the rest occur at RH as low as 75%, so this looks
  like a genuine, if modest, cross-diagnostic inconsistency in GEOS-5's
  post-processing rather than a single fully-explained physical effect.
  Worth flagging to anyone consuming MERRA-2's `T_DEW` downstream:
  don't assume `RH<=100%`-equivalent invariants derived from it always
  hold exactly, the way they do for COSMO's or ERA5-Land's `T_DEW`.
  `ALBEDO`/`SNOWFALL`/`SNOW_DEPTH` all otherwise look correct (NaN
  patterns match the documented `lnd`-collection gaps, ranges physical).

## Env (.env) — MERRA2_*/MERRA_* via EnvSettings

`MERRA_WORK_DIR`, `MERRA_YEAR`, `MERRA_NCORES`, `MERRA_THREADS_PER_JOB`,
`MERRA_CONDA_ENV` (pre-existing, note the `MERRA_` not `MERRA2_` prefix
for these), plus new: `MERRA2_AREA` (default the Europe box above),
`MERRA2_OPENDAP_MAX_CONCURRENT` (default 8). Credentials via the
generic `EARTHDATA_USERNAME`/`EARTHDATA_PASSWORD` (not MERRA2-prefixed
— shared with any future Earthdata-based provider).

## Compute profile

I/O-bound (many small daily HTTPS/OPeNDAP requests + NetCDF read/merge).
`opendap_max_concurrent` defaults to 8 (higher than ERA5-Land's CDS-
queue-limited default, since GES DISC's OPeNDAP server has no
per-account job queue) — confirm empirically once real runs happen.
