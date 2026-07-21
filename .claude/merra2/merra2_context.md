# MERRA-2 — engineering context

Confidence: HIGH — implementation complete (download/transform/export/
pipeline all implemented and wired into the CLI). Not yet run end-to-end
against real GES DISC data (needs the user's Earthdata credentials on
the target server); see `docs/MERRA2_PIPELINE_GUIDE.md` for the full
verification checklist.

## Status

- `downloaded_attributes.py`: COMPLETE — 9 raw attrs across 2
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
- **2 collections** (not 3): `M2T1NXRAD.5.12.4` (`rad`: `SWGDN`,
  `ALBEDO`) and `M2T1NXSLV.5.12.4` (`slv`: `T2M`, `QV2M`, `U2M`, `V2M`,
  `U10M`, `V10M`, `PS`). `SNODP`/`PRECSNOLAND` (which would need a 3rd
  collection, `M2T1NXLND`) are intentionally NOT downloaded — `ALBEDO`
  was judged higher-value and comes free within the `rad` request
  already being made. Documented future extension, not implemented.
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
