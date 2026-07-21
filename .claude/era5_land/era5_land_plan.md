# ERA5-Land — plan & run procedure

## Status
Pipeline complete + validated (multi-month + Arctic-cell; boundary repair
float32-exact). Ready for bulk 1950–2025 run. NEXT task after run =
percentile (era5_land_percentile_plan.md).

## Before launching (checklist)
1. Ensure `_ffill_time` `import xarray` fix is in transform.py (blocker).
2. `python src/weather/tests/audit_imports.py
   src/weather/providers/era5_land/*.py src/weather/tests/*.py` → all [OK].
3. weather_env.yml: add `aria2` + `bottleneck`; `conda env update -n
   weather_env -f infrastructure/env/weather_env.yml --prune`; `which aria2c`.
4. Append ERA5 block to server .env (keep COSMO lines): ERA5_AREA,
   ERA5_CDS_MAX_CONCURRENT=1, ERA5_DOWNLOAD_CONNECTIONS=8, ERA5_USE_ARIA2=1,
   ERA5_NCORES=6.
5. Verify creds+config one-liner (get_config → cds_key, area, ncores).
6. SMOKE-TEST one month; watch `MB/s`.

## Bulk run (sequential — recommended)
```bash
tmux new -s era5 ; conda activate weather_env
mkdir -p /data/soma/era5_land/logs
LOG=/data/soma/era5_land/logs/era5_$(date +%Y%m%d_%H%M%S).log
python src/weather/tests/test_era5_multi_year.py \
    --from-year 1950 --to-year 2025 --ncores 6 --resume 2>&1 | tee "$LOG"
```
- `--parallel-years 1` (default; >1 = no download speedup, CDS 1 job/acct;
  a warning fires).
- NO `--cleanup` (keep ~1.26 TB GRIB; fits 15 TB; avoids re-download).
- Expect ~1–2+ weeks; download-queue-bound.

## After ALL months (mandatory, in order)
```bash
python src/weather/tests/repair_month_boundaries.py /data/soma/era5_land/output
python src/weather/tests/verify_months.py       /data/soma/era5_land/output
```
1950-01 = 743 h from 01:00 is EXPECTED (OK "archive start").

## Then: merge → percentile
`weather.common.merge` per year (12 monthly → annual NC), then build
`Era5PercentileAnalyzer`. See era5_land_percentile_plan.md.

## Monitoring
`tail -f $LOG`; `grep -c ' OK' $LOG`; `grep FAIL $LOG` (re-run --resume);
`grep MB/s $LOG | tail`; `ls .../output/*.nc | wc -l`; `df -h`.

## Deferred (NOT run #1)
- pipeline_interleaved.py: ~75 h (~25%) theoretical; HELD BACK (least-
  tested; risky unattended; saving swamped by CDS-queue variance; output
  byte-identical → switchable mid-archive; no good "start at X%").
- sde float-noise -7.35e-24 (=0); clip only if a consumer objects.
