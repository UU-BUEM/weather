# `weather/providers/` — Data-Provider Implementations

This folder contains one sub-package per weather data source plus the
abstract base classes that define the shared provider contract.

---

## Sub-packages

| Sub-package | Data source | Status |
| --- | --- | --- |
| `cosmo_rea6/` | DWD COSMO-REA6 reanalysis (1986–2018, 6 km grid over Central Europe) | Production-ready |
| `merra2/` | NASA MERRA-2 reanalysis (global, ~55 km) | Stub / in development |
| `era5_land/` | Copernicus ERA5-Land reanalysis (global, 9 km) | Stub / in development |

---

## Base classes

| File | Pattern | Purpose |
| --- | --- | --- |
| `base.py` | `Protocol` | Minimal typing interface used by the CLI registry (`WeatherProvider`) |
| `base_downloader.py` | Abstract base class | Template-method download skeleton: `is_complete → skip / _fetch` |
| `base_decompressor.py` | Abstract base class | Template-method decompress skeleton: skip-if-done logic |
| `base_percentile.py` | Abstract base class | Template-method P10/P50/P90 representative-year selection (see below) |

### Adding a new provider

1. Create `providers/<name>/` with `__init__.py`.
2. Implement `download.py`, `decompress.py`, `transform.py`, `pipeline.py`
   extending the corresponding base classes.
3. Register the provider name in `weather/registry.py`.
4. Optionally add `percentile.py` extending `base_percentile.py`.

---

## `base_percentile.py` — template-method pattern

```text
                 ┌─────────────────────────────────────────┐
                 │  BasePercentileAnalyzer.run()            │
                 │  (orchestration — implemented once here) │
                 └───────────────┬─────────────────────────┘
                    calls        │        calls
          ┌──────────────────────┼────────────────────────┐
          ▼                      ▼                        ▼
  annual_metric()       load_annual_dataset()    standard_time_hours()
  (abstract)            (abstract)               (abstract)
  ← Provider subclass implements these three methods →
```

Each provider subclass must implement:

- `annual_metric(year)` — returns a scalar GHI (or other rank metric) per
  cell for the given year.
- `load_annual_dataset(year)` — opens the pre-merged annual NetCDF (lazily).
- `standard_time_hours()` — returns 8760 (non-leap) or 8784 (leap-year
  normalisation) for this provider.

All mosaic construction, percentile computation, output file writing, and
`source_year(rlat, rlon)` variable management are implemented once in the
base class.

---

## COSMO-REA6 sub-package (`cosmo_rea6/`)

| File | Purpose |
| --- | --- |
| `__init__.py` | Exposes the provider class |
| `config.py` | Resolves all `COSMO_*` environment variables to typed paths/values |
| `download.py` | Generates DWD OpenData URLs; drives `BaseDownloader` |
| `downloader.py` | Concrete `BaseDownloader` subclass for DWD HTTPS downloads |
| `downloaded_attributes.py` | Enum/list of the 9 available raw attributes |
| `decompress.py` | bz2 → GRIB with lbzip2/pbzip2/python-bz2 fallback |
| `decompressor.py` | Concrete `BaseDecompressor` subclass |
| `transform.py` | Opens GRIB with cfgrib; applies derived fields; writes monthly NC |
| `export.py` | `xr.Dataset → NetCDF` with zlib encoding and attribute metadata |
| `naming.py` | Canonical filename helpers for all output paths |
| `pipeline.py` | Orchestrates Phases 1 → 2 → 3 for one year; returned by `WeatherProvider.run_pipeline()` |
| `percentile.py` | `CosmoPercentileAnalyzer` extending `base_percentile.BasePercentileAnalyzer` |

### COSMO-REA6 per-year pipeline flow

```text
pipeline.py
│
├── Phase 1: Download (parallel)
│   download.py × N attributes × 12 months
│   ─ atomic HTTP GET to DWD OpenData
│   ─ skip if bz2 already present and valid
│
├── Phase 2: Decompress (parallel)
│   decompress.py × N attributes × 12 months
│   ─ lbzip2 / pbzip2 / python-bz2 fallback
│   ─ skip if GRIB already present and valid
│
└── Phase 3: Transform (per month, parallel or sequential)
    transform.py × 12 months
    ─ open GRIBs with cfgrib (dask-backed)
    ─ apply_derived_fields: GHI, DHI, DNI, T, WS_10M …
    ─ export.py → monthly NC (zlib complevel=1 float32)
    ─ cleanup: delete GRIB files after successful write
```
