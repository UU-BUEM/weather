# `weather/tests/` — Pipeline Scripts & Unit Tests

This folder mixes real **pytest unit tests** with **pipeline entry-point
scripts** (named `test_*` for historical reasons — they were originally
written as integration tests, but are really CLI runners you invoke by
hand or from `scripts/`). Read the category tables below before assuming
a `test_*.py` file is something `pytest` will exercise.

## At a glance

| Category | Files | Run via |
| --- | --- | --- |
| pytest unit tests | `test_validation.py`, `test_derived_attributes.py`, `test_pipeline_integration.py` | `pytest` |
| COSMO-REA6 pipeline runners | `test_one_month.py`, `test_one_year.py`, `test_multi_year.py` | `python <file>.py --help` |
| ERA5-Land pipeline runners | `test_era5_one_month.py`, `test_era5_one_year.py`, `test_era5_multi_year.py` | same |
| ERA5-Land boundary tools | `repair_month_boundaries.py`, `verify_months.py` | same |
| ERA5-Land diagnostic scripts (historical) | `check_boundary_steps.py`, `check_first_hour.py`, `diagnose_nc.py`, `enumerate_month.py`, `inspect_era5_eccodes.py`, `inspect_era5_grib.py` | same |
| MERRA-2 pipeline runners | `test_merra2_one_month.py`, `test_merra2_one_year.py`, `test_merra2_multi_year.py` | same |
| Lint tool | `audit_imports.py` | `python audit_imports.py <files...>` |
| Unwired helper | `mock_download.py` | not currently used by anything (see below) |

> **Note:** `test_percentile.py` no longer exists in this folder — COSMO's
> percentile logic now lives in `providers/cosmo_rea6/percentile_index.py`
> and is invoked directly, not via a `tests/` runner script. If you see it
> referenced elsewhere (e.g. older docs), that reference is stale.

---

## pytest unit tests

Real, synthetic-data tests collected by `pytest -q --cov=weather` (the CI gate):

| File | Covers |
| --- | --- |
| `test_validation.py` | `common/validate.py` and `common/cleanup.py` with temp files |
| `test_derived_attributes.py` | `common/derived_attributes.py` — irradiance derivation (night masking, energy balance, no negatives) across all 3 providers |
| `test_pipeline_integration.py` | `cosmo_rea6` pipeline/transform/config: checksum verification, path validation, GRIB error handling, environment validation (mocked, no network) |

```bash
conda activate weather_env
pytest src/weather/tests/test_validation.py \
       src/weather/tests/test_derived_attributes.py \
       src/weather/tests/test_pipeline_integration.py -v
```

---

## COSMO-REA6 pipeline (production, reference implementation)

Execution order for a complete dataset:

```text
1. test_one_month.py   ← sanity check: single month, single year
2. test_one_year.py    ← single year: 12 monthly NCs
3. test_multi_year.py  ← all years: threads test_one_year.py per year
        (merge step, outside tests/: python -m weather.common.merge, per year)
4. providers/cosmo_rea6/percentile_index.py  ← P10/P50/P90 representative years
```

| File | Purpose |
| --- | --- |
| `test_one_month.py` | Download + decompress + transform 1 month of all 5 attributes |
| `test_one_year.py` | Full-year pipeline; produces 12 monthly NCs |
| `test_multi_year.py` | Delegates to `test_one_year.py` per year, optionally via `ThreadPoolExecutor` |

```bash
python src/weather/tests/test_one_month.py --year 2018 --month 6 --ncores 8
python src/weather/tests/test_one_year.py --year 2018 --ncores 94
python src/weather/tests/test_multi_year.py --from-year 1995 --to-year 2018 --ncores 94
```

Common flags: `--work-dir DIR` · `--ncores N` · `--skip-download` ·
`--skip-decompress` · `--no-cleanup` · `--resume`. Full reference: `--help`.

---

## ERA5-Land pipeline

Execution order (boundary repair is **mandatory** before any analysis —
see below):

```text
1. test_era5_one_month.py  ← sanity check: single month
2. test_era5_one_year.py   ← single year: 12 monthly NCs
3. test_era5_multi_year.py ← all years: subprocesses test_era5_one_year.py per year
4. repair_month_boundaries.py  ← mandatory: fixes the first-hour cross-month
                                  accumulation defect in GHI/sf
5. verify_months.py        ← QA report: run before AND after step 4
```

| File | Purpose |
| --- | --- |
| `test_era5_one_month.py` | Download (CDS) + transform + export one month |
| `test_era5_one_year.py` | Full year; 12 monthly NCs. `--night-mask` opt-in (off by default) |
| `test_era5_multi_year.py` | Subprocesses `test_era5_one_year.py` per year in `[--from-year, --to-year]` |

```bash
python src/weather/tests/test_era5_one_month.py --year 2018 --months 6
python src/weather/tests/test_era5_one_year.py --year 2018 --ncores 12
python src/weather/tests/test_era5_multi_year.py --from-year 2018 --to-year 2020 --ncores 12
```

Common flags: `--work-dir DIR` · `--ncores N` · `--skip-download` ·
`--resume` · `--cleanup` · `--night-mask` (era5-only, default off).

### Boundary tools (mandatory step 4-5 above)

ERA5-Land's monthly GRIB structure means each monthly file's **first**
hourly stamp is a raw cross-month accumulation artifact for the
accumulated variables (`GHI`, `sf`) — physically nonsensical until
repaired. See `repair_month_boundaries.py`'s module docstring for the
full mechanics.

| File | Purpose |
| --- | --- |
| `repair_month_boundaries.py` | Repairs every monthly file's first-hour `GHI`/`sf` value using the previous month's last-day sum. Non-destructive (original value preserved in `<var>_boundary_raw`), disk-based predecessor lookup (safe to run over any `--from-year`/`--to-year` range, or `--months YYYY-MM ...` for specific months), fully idempotent. |
| `verify_months.py` | Read-only QA: hour counts, month span, cross-file continuity, boundary status, NaN profile. Run before **and** after repair to confirm the difference. |

```bash
python src/weather/tests/repair_month_boundaries.py               # whole archive
python src/weather/tests/repair_month_boundaries.py --months 2019-01 2020-06
python src/weather/tests/verify_months.py --lat 69.0 --lon 25.0    # optional point probe
```

### Diagnostic scripts (historical — kept for future investigations)

Written to diagnose a specific GRIB de-accumulation/month-boundary
anomaly (now understood and fixed by `repair_month_boundaries.py`
above). Not part of the regular pipeline; no assertions, ad hoc CLI
args, print-based output. Kept because the same class of anomaly could
resurface with a future CDS/eccodes change, and re-deriving these from
scratch would be slower than reading them.

| File | Purpose |
| --- | --- |
| `check_boundary_steps.py` | Checks whether GRIB step 23 (not just step 24) exists at month boundaries |
| `check_first_hour.py` | Traces whether a first-hour GHI NaN originates from missing source data vs. a pipeline bug |
| `diagnose_nc.py` | Diagnoses one ERA5-Land monthly NetCDF output (time axis, NaN/zero stats, boundary repair status) |
| `enumerate_month.py` | Enumerates every GRIB message of one variable in a monthly file |
| `inspect_era5_eccodes.py` | Low-memory GRIB inspector via raw eccodes (avoids cfgrib's full-file indexing) |
| `inspect_era5_grib.py` | Inspects a GRIB file via `cfgrib.open_datasets` (multiple hypercubes/variables/grid shape) |

---

## MERRA-2 pipeline

Same structure as ERA5-Land, no boundary-repair step needed (`SWGDN` is
instantaneous, not accumulated — see `providers/merra2/transform.py`).

| File | Purpose |
| --- | --- |
| `test_merra2_one_month.py` | Download (OPeNDAP) + transform + export one month |
| `test_merra2_one_year.py` | Full year; 12 monthly NCs |
| `test_merra2_multi_year.py` | Subprocesses `test_merra2_one_year.py` per year in `[--from-year, --to-year]` |

```bash
python src/weather/tests/test_merra2_one_month.py --year 2018 --month 3
python src/weather/tests/test_merra2_one_year.py --year 2018 --ncores 12
python src/weather/tests/test_merra2_multi_year.py --from-year 1980 --to-year 2025 --ncores 12
```

Common flags: `--work-dir DIR` · `--ncores N` · `--skip-download` ·
`--resume` · `--cleanup`. Requires NASA Earthdata credentials
(`EARTHDATA_USERNAME`/`EARTHDATA_PASSWORD` or `~/.netrc`) — see
`docs/MERRA2_PIPELINE_GUIDE.md`.

---

## Other files

| File | Purpose |
| --- | --- |
| `audit_imports.py` | Static check: flags `np./xr./pd./cfgrib.` used inside a function without a module-level or local import (enforces CLAUDE.md's global-imports-only rule). Accepts glob patterns (expanded internally, so it works the same from bash and PowerShell): `python audit_imports.py src/weather/providers/era5_land/*.py` |
| `mock_download.py` | Stub HTTP responses for a no-network download test. **Not currently imported by any test or conftest** — kept as scaffolding for a future no-network CI check (matching the Docker entrypoint's `check` mode), not dead code to be confused with an active test dependency. |

For the full flag reference of any pipeline runner, run it with `--help`.
