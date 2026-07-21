# Changelog

All notable changes to this project will be documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.2.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

## [1.4.0] - 2026-07-21

### Added

- **ERA5-Land: full pipeline implementation** — provider is now
  `status: implemented` (was `scaffold`). Added
  `src/weather/providers/era5_land/download.py` (monthly CDS download
  orchestration), `downloader.py` (rewritten CDS request/retry logic),
  `fast_download.py` (parallel multi-connection HTTP range download of
  the CDS result), `transform.py` (GRIB → analysis-ready dataset:
  de-accumulate `ssrd`, Spencer SZA night-mask), `export.py` (monthly
  NetCDF-4, zlib, float32), `pipeline.py` (wires download → transform →
  export for one year), `pipeline_interleaved.py` (overlaps download and
  transform so wall-clock time is `max(download, transform)` instead of
  their sum), `dni_pointwise.py` (opt-in point/region DNI-DHI
  decomposition via pvlib DIRINT/DISC, since ERA5-Land only stores GHI
  in bulk), and `sample_call.py` (reference snippet for the ECMWF
  Datastores client / cdsapi).
- **ERA5-Land: percentile support** —
  `src/weather/providers/era5_land/percentile_index.py`, a structural
  port of COSMO's KS-distance P10/P50/P90 representative-year script.
- **MERRA-2: full pipeline implementation** — provider is now
  `status: implemented` (was `scaffold`). Added
  `src/weather/providers/merra2/download.py` (OPeNDAP download
  orchestration per `(collection, day)`), rewritten `downloader.py`
  (Earthdata/URS session handling), `transform.py` (merges daily
  `rad`/`slv` collections into a monthly dataset, derives GHI/WS_10M/RH),
  `export.py` (monthly NetCDF-4, zlib, float32), and `pipeline.py`
  (wires download → transform → export for one year).
- **CLI** (`src/weather/cli.py`): added `--months` (ERA5-Land subset of
  months), `--ncores` (ERA5-Land/COSMO worker count), `--no-night-mask`
  (disable Spencer SZA night-masking, ERA5-Land only), and `--resume`
  (skip months/years whose output already exists). `_cmd_run` now
  branches on `provider.name` to build provider-specific kwargs, since
  ERA5-Land's `run_pipeline` signature differs from COSMO's.
- **`settings.py`**: added `EnvSettings.merra2_area()` / `era5_area()`
  (CDS-style `"N,W,S,E"` bounding-box parsing, both default to the same
  Europe box `72,-11,34,32`) and `merra2_opendap_max_concurrent()`
  (default 8, since GES DISC has no per-account job queue, unlike CDS).
- **`common/net.py`**: added `_AuthPreservingSession` and
  `build_session(..., preserve_auth_hosts=...)` — re-attaches the
  `Authorization` header across the cross-host redirect chain used by
  NASA Earthdata login, which `requests` strips by default as a CSRF
  precaution.
- **`common/derived_attributes.py`**: added `_era5_rh` (Magnus-formula
  relative humidity from `t2m`/`d2m`) and `_era5_wind_speed`
  (`sqrt(u10**2 + v10**2)`), registered as `ERA5_LAND.RH` and
  `ERA5_LAND.WS_10M` in `DERIVED_FIELDS`.
- **`providers/merra2/downloaded_attributes.py`**: added `COLLECTIONS`
  dict (`rad`/`slv` GES DISC collection names) and an
  `attrs_by_collection()` helper; each attribute entry now tags its
  source `collection`. Replaced `SNODP`/`PRECSNOLAND` with `QV2M`
  (specific humidity, feeds the RH formula) and `ALBEDO`.
- **Docs**: `docs/BULK_RUN_GUIDE_ERA5-LAND.md`, `docs/DOWNLOAD_AND_LOGGING.md`,
  `docs/MERRA2_PIPELINE_GUIDE.md`.
- **Tests/tools**: ERA5-Land pipeline runners (`test_era5_one_month.py`,
  `test_era5_one_year.py`, `test_era5_multi_year.py`), MERRA-2 pipeline
  runners (`test_merra2_one_month.py`, `test_merra2_one_year.py`,
  `test_merra2_multi_year.py`), ERA5-Land boundary/diagnostic tools
  (`repair_month_boundaries.py`, `verify_months.py`,
  `check_boundary_steps.py`, `check_first_hour.py`, `diagnose_nc.py`,
  `enumerate_month.py`, `inspect_era5_eccodes.py`, `inspect_era5_grib.py`),
  and `audit_imports.py` (lint tool enforcing global-imports-only).
- **`scripts/run_era5_bulk.sh`**: launch script for a full ERA5-Land
  bulk run.
- **`CLAUDE.md`** and **`.claude/`**: added the persistent project
  context file and per-provider `.claude/{cosmo_rea6,era5_land,merra2}/`
  context/plan docs, plus `.claude/open.md` / `resolved.md` issue
  tracking.

### Changed

- **`providers/README.md`**: `base_percentile.py` documented as dead
  code — the template-method P10/P50/P90 design was superseded by the
  standalone `percentile_index.py` scripts now used by both COSMO-REA6
  and ERA5-Land.
- **`providers/era5_land/__init__.py`** / **`providers/merra2/__init__.py`**:
  now thin façades over their `pipeline.run_pipeline`;
  `validate_environment()` checks real package imports and credentials
  (CDS `~/.cdsapirc` / Earthdata auth) instead of a static message;
  `run_pipeline()` translates/drops COSMO-only CLI kwargs rather than
  erroring.
- **`providers/era5_land/config.py`**: added `area`, `cds_max_concurrent`,
  `cds_max_retries`, `download_connections` to the resolved config dict.
- **`providers/merra2/config.py`**: added `area` and
  `opendap_max_concurrent`.
- **COSMO-REA6**: default `--complevel` (zlib compression) changed from
  `5` to `1` in `cli.py` and `providers/cosmo_rea6/pipeline.py`, trading
  file size for faster writes; `export.py`/`naming.py` docstrings
  updated from stale `buem.weather.*` import paths.
- **`.env.example`**: rewritten to cover all three providers — added
  `ERA5_DATA_FORMAT`, `ERA5_CDS_MAX_CONCURRENT`, `ERA5_USE_ARIA2`,
  `ERA5_CDS_URL`/`ERA5_CDS_KEY`, `ERA5_AREA`,
  `EARTHDATA_USERNAME`/`PASSWORD`, `MERRA2_OPENDAP_MAX_CONCURRENT`,
  `MERRA2_AREA`.
- **`infrastructure/env/weather_env.yml`**: added `ecmwf-datastores-client`
  and `aria2` (parallel multi-connection downloader); pinned
  `python=3.12.*` explicitly.
- **`scripts/common.sh`**: `.env` is now stripped of `\r` before
  `source`, so a CRLF-saved `.env` no longer breaks on the Linux server.
- **`.gitignore`**: added `deploy_to_server.ps1`.
- **`LICENSE`**: copyright year range updated `2024-2026` → `2025-2027`.
- **`src/weather/tests/README.md`**: rewritten with a category table
  (pytest units vs. pipeline runners vs. diagnostic tools) covering the
  new ERA5-Land/MERRA-2 runners and tools.

### Fixed

- **`common/derived_attributes.py`**: `ERA5_LAND` registry no longer
  advertises `DHI`/`DNI` (those require a per-site DIRINT/DISC
  decomposition that cannot broadcast over a `(time, y, x)` grid — moved
  to the opt-in `dni_pointwise.py` helper); `test_derived_attributes.py`
  updated to match (`GHI`/`RH`/`WS_10M` for ERA5-Land).
- Lint/type fixes across new diagnostic scripts under `src/weather/tests/`
  (`audit_imports.py`, `check_first_hour.py`, `enumerate_month.py`,
  `inspect_era5_grib.py`) and `providers/era5_land/pipeline_interleaved.py`
  to satisfy `ruff check src/` and `mypy src`.
- **`providers/era5_land/sample_call.py`**: removed a module-level
  `client.check_authentication()` network call and hardcoded local
  Windows paths (`D:/test/...`) from download targets.

---

## [1.3.0] - 2026-06-28

### Added

- Included a docs folder with the following files:
  `debugging.md`, `dni_methodology.md`, `git-push-workflow.md`,
  `parallelization.md`, `percentile_methodology.md`, and `qa.md`.
- `./src/weather/providers/cosmo_rea6/percentile_index.py` — calculates
  percentiles (P10, P50, and P90) using the FH method and GHI as the
  basis for each cell and each month.

### Changed

- Added versions to python packages in weather_env.yml.
- Added `relative humidity` attribute to `downloaded_attributes.py`
  of `cosmo-rea6`, `era5_land`, and `merra2` submodules.
- Minor updates to .gitignore, CONTRIBUTING.md, and README.md

---

## [1.2.0] — 2026-06-15

### Added

- `./infrastructure/container/entrypoint.sh` — routes to the appropriate
  pipeline script based on the PIPELINE_MODE environment variable.
- `./src/weather/common/derived_attributes.py` — Cross-provider irradiance
  derivation (GHI, DHI, DNI).
- `./src/weather/common/merge.py` — NetCDF-4 / HDF5 monthly-to-annual merge
  utilities.
- `./src/weather/common/parallel.py` — Shared thread-pool executor for
  I/O-bound parallel tasks.
- `./src/weather/common/percentile_poe.py` and `./src/weather/common/percentile.py`
  — different method to calculate weather percentile years with P10, P50, and
  P90 representation.
- `./src/weather/providers/merra2/` — Scafolding addition related to MERRA2
  with config.py, downloaded_attributes,py, downloader.py, main.py,
  base_decompressor.py, base_downloader.py, base_percentile.py,and
  corresponding README.md files addition.
- `./src/weather/providers/era5_land/` — Scafolding addition related to
  config.py, downloaded_attributes,py, and downloader.py similar to
  MERRA2.
- `./src/weather/tests/` — added multiple test files to test processing
  of one month, one year, multi-year, and percentile weather data
  processing along with integration pipeline testing.
- `./src/weather/settings.py` — provides a centralized environment for
  the entire weather pipeline.
- `setup.sh` — creates or updates the conda environment and installs
  the package in editable mode.

### Changed

- **workflows**: addition of "on" event that triggers workflow. For
  ci.yml, this should be triggered when there is a push event on the
  `main` and `develop` branches. In release.yml, this is triggered with
  a tag starting with `v`.
- **container**: changes to `Dockerfile` and `docker-compose.yml`
  to consider single and multi-year weather data processing.
- **`weather_env.yml`**: addition of `Jupyter`, `matplotlib=3.10.*`,
  `lbzip2` and `h5py=3.11.*`.
- **scripts**: multiple files adjusted for full year processing.
  Still need to be adjusted for multi-year processing.
- **`/src/weather/common/`**: ``cleanup.py` updated to adjust the
  cleanup pattern of downloaded and decompressed files. `download.py`
  added functions to compute- and save SHA256 checksum of a file.
  Finally, `env.py` adjusted loading of environment files.
- **`/src/weather/providers/cosmo_rea6/`**: changes to the pipeline
  related to parallel processing, multi-year processing, and making
  download of attributes modular.
- **`/src/weather/providers/<merra2/era5_land>`**: corresponding
  `__init__.py` update related to environment path definition.
- **`setup.ps1` / `setup.bat`**: `conda develop src` replaced with
  `conda run -n $EnvName pip install -e .`; `CONDA_BLD_PATH` configuration
  removed.
- **environment**: `.pyproject.toml` and `meta.yaml` update related to
  pip install due to addition of new python packages. `MD018` set to
  `false` in `.markdownlint.json`.

---

## [1.1.0] — 2026-05-19

### Added

- `.github/workflows/ci.yml` — automated lint (ruff), type-check (mypy),
  pytest with coverage, and CLI smoke test on every push/PR.
- `.github/workflows/release.yml` — build sdist + wheel and publish to GitHub
  Releases automatically on `v*` tag push.
- `.github/agents/uu-buem-align.agent.md` — VS Code Copilot custom agent for
  UU-BUEM cross-repo standardisation workflows.
- `.markdownlint.json` — MD013 (100-char lines, tables exempt) and MD024
  (siblings-only duplicate headings); aligned with `UU-BUEM/occupancy`.
- `.yamllint.yml` — excludes `meta.yaml` from YAML linting (Jinja2 templates
  are pre-processed by conda-build before YAML parsing).
- `.vscode/settings.json` — classifies `meta.yaml` as `jinja` language to
  suppress cascading false-positive YAML errors in VS Code.
- `setup.bat` — restored missing Windows cmd.exe setup script; mirrors
  `setup.ps1` behaviour.
- Post-install verification step (`python -m weather info`) in `setup.ps1`
  and `setup.bat`.
- OCI `LABEL` metadata (`source`, `description`, `licenses`) in `Dockerfile`.

### Changed

- **Python**: requirement lowered from `>=3.14` (pre-release) to `>=3.12`
  across `pyproject.toml`, `meta.yaml`, `weather_env.yml`, ruff
  `target-version`, and mypy `python_version`. Python 3.14 can be
  re-targeted once conda-forge packages have stable 3.14 builds.
- **Dependencies**: all core deps pinned with minimum (and where appropriate
  upper) version bounds in `pyproject.toml`; optional extras pinned too
  (`pvlib>=0.10`, `pyarrow>=15.0`, `cdsapi>=0.7`); dev extras given minimum
  versions (`mypy>=1.8`, `pytest>=7.4`, `pytest-cov>=4.1`, `ruff>=0.6`).
- **`weather_env.yml`**: all packages pinned for reproducibility
  (`numpy=1.26.*`, `pandas=2.2.*`, `scipy=1.13.*`, etc.); `conda-build`
  removed (no longer needed); `pip: -e .` added so the package is installed
  editable on `conda env create`.
- **`conda_build_config.yaml`**: added `pandas: 2.2` and `python: 3.12` pins.
- **`meta.yaml`**: version now derived from git tag via Jinja2
  `GIT_DESCRIBE_TAG`; `python >=3.14` → `>=3.12`; optional extras
  (`cdsapi`, `pvlib`, `pyarrow`) removed from mandatory `run` deps; explicit
  version bounds added to all run dependencies; `test.imports` expanded to
  include `weather.providers`.
- **`setup.ps1` / `setup.bat`**: `conda develop src` replaced with
  `conda run -n $EnvName pip install -e .`; `CONDA_BLD_PATH` configuration
  removed.
- **Docker**: base image pinned `continuumio/miniconda3:latest` →
  `:24.1.2-0` in both `Dockerfile` and `weather.def`.
- **`docker-compose.yml`**: image tag `weather:latest` →
  `weather:${WEATHER_VERSION:-latest}`.
- **`pyproject.toml`**: `write_to` → `version_file` (setuptools-scm ≥ 8
  non-deprecated API); `fallback_version` set to `1.1.0`.
- **`_version.py`**: added `version`, `version_tuple`, `__commit_id__`,
  `commit_id` aliases to match occupancy format.
- **`__init__.py`**: `_version` import wrapped in `try/except ImportError`
  with `"1.1.0"` fallback — prevents import failure in source-only installs.
- **`.gitignore`**: `.vscode/settings.json` (wrongly ignored) changed to
  `.vscode/*` + `!.vscode/settings.json` so workspace settings are tracked.
- **`CONTRIBUTING.md`**: removed `conda develop` references; fixed MD013
  line-length violation.

### Fixed

- `from_csv.py`: removed `Path(__file__).parents[2]` path hack (now requires
  an explicit absolute path); fixed deprecated `'H'` → `'h'` pandas resample
  alias; guarded Feather/pyarrow cache behind `try/except ImportError`;
  removed `if __name__ == "__main__"` debug block with hardcoded Windows path.

---

## [1.0.0] — 2026-05-18

### Added

- Provider-based architecture: `cosmo-rea6` (implemented), `merra-2` and
  `era5-land` scaffolds.
- `src/` layout with `src/weather/` package and proper `pyproject.toml`.
- `common/` module with shared download (`download.py`), decompression
  (`decompress.py`), and HTTP/auth utilities (`net.py`).
- `cli.py` for structured CLI commands (`info`, `validate`, `run`).
- Lazy provider registry to avoid eager import of all provider modules.
- Docker multi-stage `Dockerfile` + `docker-compose.yml` for local dev.
- Apptainer definition `weather.def` for HPC (Snellius/SLURM).
- `pyproject.toml` with dynamic versioning from `_version.py`.
- `setup.ps1` / `setup.bat` for one-command Windows dev environment setup.

### Changed

- Renamed `Dockerfile.weather` → `Dockerfile`; image tag `buem-weather` →
  `weather`.
- Renamed `buem_weather.sif` → `weather.sif` in all scripts.
- Set `python=3.14` in `weather_env.yml`; removed `lbzip2` (OS package,
  not conda).
- Updated `from_csv.py` path resolution from `buem_root` to repo root.

### Removed

- Stale `buem` references throughout container files and shell scripts.

---

## [0.1.0] — 2026-05-13

### Initial Release

- Initial extraction from the `buem` monorepo.
- COSMO-REA6 download → decompress → transform → export pipeline.
- Shell scripts for Snellius HPC: `setup_env.sh`, `run_pipeline.sh`,
  `run_pipeline_container.sh`, `build_container.sh`.
