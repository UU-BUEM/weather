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
| `base_percentile.py` | Abstract base class | **Dead code** — superseded by the standalone `percentile_index.py` scripts (see below); no provider subclasses it |

### Adding a new provider

1. Create `providers/<name>/` with `__init__.py`.
2. Implement `download.py`, `decompress.py`, `transform.py`, `pipeline.py`
   extending the corresponding base classes.
3. Register the provider name in `weather/registry.py`.
4. Optionally add `percentile.py` extending `base_percentile.py`.

---

## `base_percentile.py` — dead code, do not use for new providers

An earlier template-method design (`annual_metric`/`load_annual_dataset`/
`standard_time_hours`, one annual NetCDF per year) lived in
`cosmo_rea6/percentile.py`. It was **deleted** (commit `17d5eea`, "Added
percentile and documentation") and replaced by the standalone
`percentile_index.py` scripts described below, which do not use
`base_percentile.py` at all. The base class and `common/percentile.py`
still exist in the tree but are unused — check with the team before
building a new provider against them.

## `percentile_index.py` — the actual production pattern (all three providers)

Each of `cosmo_rea6/`, `era5_land/` and `merra2/percentile_index.py` is a
self-contained, three-phase script (no shared base class):

```text
Load (parallel file read)  →  rank years per month/cell  →  Mosaic
(day-summed GHI; leap days    (year nearest the P10/P50/   (spawn workers
 and out-of-month stamps       P90 of cumulative monthly    write 36 NC
 dropped)                      GHI across years)            files)
```

All three read monthly NetCDF files directly (`*_YYYY_MM_*.nc`), pick —
per grid cell and calendar month — the year whose cumulative monthly GHI
is nearest the P10/P50/P90 of those totals across years (ASHRAE TMY3
style), then mosaic every variable from the winning year into
`{provider}_{p10,p50,p90}_{MM}_all_attrs.nc`, with a `source_year`
provenance variable (`-1` where no year has data). The earlier
Finkelstein-Schafer "KS-distance" rule never delivered the requested
P-levels and was replaced on 2026-08-19; see
`docs/percentile_methodology.md` §3.2.1. The scripts differ only in
filename regex, grid handling, and `n_cpu_cores` default (6/8 for the
lighter ERA5-Land/MERRA-2 loads vs COSMO's 94 — local file reads only,
unrelated to COSMO's download `--ncores`).

---

## COSMO-REA6 sub-package (`cosmo_rea6/`)

| File | Purpose |
| --- | --- |
| `__init__.py` | Exposes the provider class |
| `config.py` | Resolves all `COSMO_*` environment variables to typed paths/values |
| `download.py` | Generates DWD OpenData URLs; drives `BaseDownloader` |
| `downloader.py` | Concrete `BaseDownloader` subclass for DWD HTTPS downloads |
| `downloaded_attributes.py` | Dict of the 11 raw attributes downloaded from DWD |
| `decompress.py` | bz2 → GRIB with lbzip2/pbzip2/python-bz2 fallback |
| `decompressor.py` | Concrete `BaseDecompressor` subclass |
| `transform.py` | Opens GRIB with cfgrib; applies derived fields; writes monthly NC |
| `export.py` | `xr.Dataset → NetCDF` with zlib encoding and attribute metadata |
| `naming.py` | Canonical filename helpers for all output paths |
| `pipeline.py` | Orchestrates Phases 1 → 2 → 3 for one year; returned by `WeatherProvider.run_pipeline()` |
| `percentile_index.py` | Standalone P10/P50/P90 representative-month script (see above) |

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
