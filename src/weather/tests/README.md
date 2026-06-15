# `weather/tests/` — Pipeline Scripts

Despite being in a folder named `tests/`, these scripts are **pipeline
entry-points**, not unit tests in the pytest sense (except `test_validation.py`
and `test_derived_attributes.py`).

> **Important:** This folder serves two purposes.
>
> - `test_validation.py` and `test_derived_attributes.py` are **pytest unit
>   tests** that verify module logic with synthetic data.
> - The `test_one_*.py` and `test_multi_year.py` / `test_percentile.py`
>   scripts are **end-to-end pipeline runners** that download real data and
>   produce output files.  They are named `test_*` for historical reasons
>   (they were originally written as integration test scripts).

---

## Scripts — execution order

The scripts must be run in this order for a complete dataset:

```text
1. test_one_month.py   ← sanity check: single month, single year
         │
         │  (once satisfied)
         ▼
2. test_one_year.py    ← single year: 12 monthly NCs
         │
         │  (repeat via multi-year runner)
         ▼
3. test_multi_year.py  ← all years: threads test_one_year.py per year
         │
         │  (merge step, outside tests/)
         │  python -m weather.common.merge  ← per year
         ▼
4. test_percentile.py  ← P10/P50/P90 representative-year files
```

---

## File descriptions

| File | Type | Purpose |
| --- | --- | --- |
| `test_one_month.py` | Pipeline runner | Download + decompress + transform 1 month of all 9 attributes; single-month smoke test |
| `test_one_year.py` | Pipeline runner | Full-year pipeline for one calendar year; produces 12 monthly NCs |
| `test_multi_year.py` | Pipeline runner | Multi-year pipeline; delegates to `test_one_year.py` per year, optionally via `ThreadPoolExecutor` |
| `test_percentile.py` | Pipeline runner | Reads annual NCs; derives P10/P50/P90 representative-year files via per-cell GHI percentile |
| `test_validation.py` | pytest unit test | Validates `common/validate.py` and `common/cleanup.py` with temp files |
| `test_derived_attributes.py` | pytest unit test | Validates irradiance derivation (night masking, energy balance, no negatives) with synthetic data |
| `mock_download.py` | Test helper | Provides stub HTTP responses for download unit tests |

---

## Running the unit tests

```bash
conda activate weather_env
pytest src/weather/tests/test_validation.py src/weather/tests/test_derived_attributes.py -v
```

---

## Running the pipeline scripts

```bash
# 1 — Smoke test: one month
python src/weather/tests/test_one_month.py --year 2018 --month 6 --ncores 8

# 2 — Full year
python src/weather/tests/test_one_year.py --year 2018 --ncores 94

# 3 — All years (sequential)
python src/weather/tests/test_multi_year.py \
    --from-year 1995 --to-year 2018 --ncores 94

# 4 — Merge each year (run from output directory)
for year in $(seq 1995 2018); do
    python -m weather.common.merge \
        --input  "/data/output/COSMO_REA6_${year}_??_all_attrs.nc" \
        --output "/data/output/COSMO_REA6_${year}_annual_all_attrs.nc"
done

# 5 — P10/P50/P90
python src/weather/tests/test_percentile.py \
    --input-dir /data/output \
    --from-year 1995 --to-year 2018
```

---

## Flags common to all pipeline runners

| Flag | Description |
| --- | --- |
| `--work-dir DIR` | Override `COSMO_WORK_DIR`; intermediate files go here |
| `--ncores N` | Dask/thread-pool worker count |
| `--skip-download` | Assume bz2 files are already present |
| `--skip-decompress` | Assume GRIB files are already present |
| `--no-cleanup` | Keep intermediate bz2 and GRIB files |
| `--resume` | Skip months/years whose output NC already exists |

For the full flag reference for each script, run with `--help`.
