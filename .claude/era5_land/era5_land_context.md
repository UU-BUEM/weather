# ERA5-Land — engineering context

Confidence: HIGH (built + validated in this project). Every non-obvious
decision + reason, so a new session doesn't re-derive or re-break them.

## Goal
CDS `reanalysis-era5-land` (0.1°, hourly, 1950–present) → monthly NetCDFs
for renewable-energy (solar PV) work.

## Raw attributes (10) — `downloaded_attributes.py` (DICT; add here)
t2m, d2m, u10, v10, sp, sde, sf, asn, fal, ssrd.

## Outputs (per monthly .nc)
`ERA5_LAND_<YYYY>_<MM>_all_attrs.nc`, dims `(time, y, x)`, latitude/
longitude as coord vars (y/x integer indices → matches COSMO for `isel`).
Vars: T(°C, from t2m), T_DEW(°C, renamed from d2m 2026-07-26 — matches
COSMO's derived T_DEW/MERRA-2's renamed T2MDEW), PS(Pa, renamed from sp
2026-07-26), U_10M/V_10M(m/s, renamed from u10/v10 2026-07-26),
SNOW_DEPTH(m, renamed from sde 2026-07-30 -- **not** `sd`: `downloaded_
attributes.py` used to wrongly map this to e5l_name "sd" and describe it
as water-equivalent depth; verified against the real CDS request
payload + raw GRIB metadata + already-processed output that the actual
field is `sde` = physical depth, same quantity as COSMO/MERRA-2 all
along), SNOWFALL(kg/m²/h, renamed from sf 2026-07-26 — matches
MERRA-2/COSMO canonical name), asn (ECMWF "Snow albedo" — reflectivity
of just the snow-covered surface, narrower than ALBEDO's whole-cell
blend; no COSMO/MERRA-2 equivalent exists, kept unrenamed), ALBEDO(1,
renamed from fal 2026-07-26 — matches MERRA-2/COSMO canonical name),
GHI(W/m²), RH(%), WS_10M(m/s). ssrd dropped. GRIB_* attrs
stripped (break Panoply; carry 3.4e38 sentinel). Ocean=NaN (~49%). Span
`<1st> 00:00 .. <last> 23:00`; consecutive files DON'T overlap.

## Derived formulas
- GHI = deaccum_step(ssrd)/3600
- RH = 100·exp(a·Td/(b+Td) − a·T/(b+T)), a=17.625 b=243.04 (dew-point
  Magnus). COSMO direct RELHUM_2M; MERRA-2 q-based. Do NOT unify.
- WS_10M = √(u10²+v10²); sf → ×1000, clip ≥0.
- GHI/DHI/DNI: `common.derived_attributes.apply_derived_fields(ds,
  "ERA5_LAND", sol_pos, times)` uses DIRINT from GHI (pvlib), night-masks,
  enforces GHI=DHI+DNI·cos(zenith). NB night_mask=False in the PIPELINE
  concerns the raw monthly GHI field, NOT this DNI-path masking.

## Percentile (built: `percentile_index.py`)
ERA5-Land output is per-MONTH, same as what COSMO's actual
`percentile_index.py` reads (its KS-distance script reads monthly files
directly, not annual — the annual-merge design in old docs described a
different, now-deleted `base_percentile.py` approach). ERA5's
`percentile_index.py` is a direct structural port: same KS algorithm,
grid size inferred from data instead of hardcoded. See
era5_land_percentile_plan.md.

## Key decisions (+reasons)
- **Europe bbox mandatory** `ERA5_AREA=72,-11,34,32` (N,W,S,E; matches
  MERRA-2 footprint). Crop shrinks each GRIB message ~24×. Fixed eccodes
  MemoryAllocationError on global grid AND storage (43 TB→~1.3 TB).
- Stay ERA5-Land (0.1°); NOT ERA5 (0.25°) nor ARCO/Zarr (that's ERA5).
- Pipeline night_mask OFF by default (ssrd ~0 at night). Opt-in
  --night-mask. numba NOT in the TRANSFORM (I/O+zlib bound; math already
  vectorized) — but numba IS a dep and IS used in percentile_index (see
  the runtime-debug skill). wgrib2 rejected
  (GRIB2-only). CDO rejected. float32, complevel=1.

## GRIB forecast structure (verified via eccodes)
cfgrib splits a month into MULTIPLE cubes (mixed editions 1&2, mixed step).
Main vars arrive `(time=forecast-day, step=1..24)`, NOT flat:
```text
<prev last day>, step 24      -> <1st> 00:00        (1 msg)
<1st>..<last-1>, steps 1..24  -> hourly stamps
<last day>,      steps 1..23  -> ... <last> 23:00
```
`<1st> 00:00` = prev month's last hour; this month's real last hour ships
in NEXT month's file.

## transform.py order (do not reorder)
cfgrib.open_datasets(list) → chunk cubes → `_normalize_longitude` (0–360
edition-2 sde → −180..180, else merge NaN-fills) → `_flatten_to_hourly`
(deaccum ssrd/sf ALONG STEP within each forecast day BEFORE stacking; the
step w/ missing predecessor KEEPS raw value; transpose) → reindex cubes to
first grid (tol 0.01°) → `xr.merge` → `_drop_empty_timestamps` (drop
all-NaN phantom stamps → exactly the calendar month) → `_ffill_time`
(bottleneck fast-path + NumPy fallback; fallback needs `import xarray` — a
missing one caused a full failed run) → RH (from RAW Kelvin), GHI, WS →
y/x int dims, strip GRIB_* → `boundary_status="UNREPAIRED: ..."`.

## Month-boundary problem + solution (do not undo)
`<1st> 00:00` needs `ssrd[prev-last,step24] − step23`. step24 in THIS file;
step23 only in PREVIOUS file. Transform keeps raw value (flagged).
`repair_month_boundaries.py`: `GHI(<1st>00:00) = stored_first − Σ(prev GHI
last-day 01:00..23:00)`. Float32-exact incl. Arctic midnight-sun (69°N July
→ ~24 W/m²; fill-0 destroys it, NaN loses it). Archive 1950-01 = 743 h from
01:00 (no 00:00 stamp) — left untouched. Idempotent (`boundary_status.
startswith("BOUNDARY_REPAIRED")`; NOT substring "REPAIRED" — matches
"UNREPAIRED", caused false-skip bug).

## Download perf
cdsapi single-stream 3.56 MB/s. `fast_download.py`: parallel HTTP range (8)
or aria2c if `ERA5_USE_ARIA2=1`. WITHIN one transfer — not extra CDS
requests — safe w/ concurrency=1. In `downloader._download_result` w/
fallback. Saves ~81 h.

## Config (.env)
ERA5_AREA, ERA5_CDS_MAX_CONCURRENT=1 (1 job/account), ERA5_CDS_MAX_RETRIES,
ERA5_DOWNLOAD_CONNECTIONS=8, ERA5_USE_ARIA2, ERA5_NCORES=6 (I/O+compression
bound — NOT 94; multiplies memory), ERA5_DATA_FORMAT=grib. Creds: prefer
~/.cdsapirc (a leading "5" was once dropped from an env key — verify).

## Bugs fixed (don't reintroduce)
lon 0–360 vs −180 → all-NaN merge; xr.where dim reorder → transpose;
.stack() time-last → transpose; calendar trim dropping real last hour +
orphaning first; fill-0 destroying Arctic boundary; _ffill_time missing
import xarray; repair "REPAIRED" substring false-skip; repair grid-mismatch
crash (logged+skipped); global grid eccodes OOM → Europe crop.

## Tools (src/weather/tests/)
test_era5_one_month/one_year/multi_year.py, repair_month_boundaries.py,
verify_months.py, diagnose_nc.py (FILE --lat --lon --hours),
enumerate_month.py, check_boundary_steps.py, check_first_hour.py,
inspect_era5_eccodes.py, inspect_era5_grib.py, audit_imports.py.
