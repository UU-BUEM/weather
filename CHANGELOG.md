# Changelog

All notable changes to this project will be documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

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

- Renamed `Dockerfile.weather` → `Dockerfile`; image tag `buem-weather` → `weather`.
- Renamed `buem_weather.sif` → `weather.sif` in all scripts.
- Set `python=3.14` in `weather_env.yml`; removed
  `lbzip2` (OS package, not conda).
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
