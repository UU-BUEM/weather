# Changelog

All notable changes to this project will be documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

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
