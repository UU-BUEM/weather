# Weather

## Pipeline design intention

This pipeline is designed for server runs and not individual computer.
It produces either raw or processed data which can be used for
modules related to estimating renewable energy potentials, solar
gains in buildings, and demands of multiple energy-related sectors.
Currently, this pipeline standardizes three weather databases:

- `COSMO-REA6`
- `MERRA2`
- `ERA5-LAND`

<!-- markdownlint-disable MD013 -->
[![CI](https://github.com/UU-BUEM/weather/actions/workflows/ci.yml/badge.svg)](https://github.com/UU-BUEM/weather/actions/workflows/ci.yml)
[![Release](https://github.com/UU-BUEM/weather/actions/workflows/release.yml/badge.svg)](https://github.com/UU-BUEM/weather/actions/workflows/release.yml)
<!-- markdownlint-enable MD013 -->

Standalone weather processing repository for `UU-BUEM`.

This repository uses a provider-based architecture with a standard Python `src/` layout and
separate infrastructure folders for environment and container assets.

## Project Structure

```text
weather/
├── src/                           # Python package (src-layout standard)
│   └── weather/
│       ├── common/
│       │   ├── __init__.py
│       │   ├── cleanup.py
│       │   ├── decompress.py
|       |   ├── derived_attributes.py
│       │   ├── download.py
|       |   ├── env.py
|       |   ├── merge.py
|       |   ├── parallel.py
|       |   ├── percentile_poe.py
│       │   ├── percentile.py
│       │   └── validate.py
│       ├── providers/
│       │   ├── __init__.py
|       |   ├── base_decompressor.py
|       |   ├── base_downloader.py
|       |   ├── base_percentile.py
│       │   ├── base.py
│       │   ├── cosmo_rea6/
│       │   │   ├── __init__.py
│       │   │   ├── config.py
│       │   │   ├── download.py
│       │   │   ├── decompress.py
│       │   │   ├── transform.py
│       │   │   ├── export.py
│       │   │   └── pipeline.py
│       │   ├── merra2/
│       │   │   ├── __init__.py
|       |   |   ├── config.py
|       |   |   ├── downloaded_attributes.py
|       |   |   └── downloader.py
│       │   └── era5_land/
│       │       ├── __init__.py
|       |       ├── config.py
|       |       ├── downloaded_attributes.py
|       |       └──downloader.py
|       ├── tests/
|       |   ├── test_derived_attributes.py
|       |   ├── test_multi_year.py
|       |   ├── test_one_month.py
|       |   ├── test_one_year.py
|       |   ├── test_percentile_poe.py
|       |   ├── test_percentile.py
|       |   ├── test_pipeline_integration.py
|       |   └── test_validation.py
│       ├── __init__.py
│       ├── __main__.py
│       ├── _version.py
│       ├── cli.py
│       ├── from_csv.py 
|       ├── registry.py 
│       └── settings.py
├── infrastructure/
│   ├── env/
│   │   └── weather_env.yml
│   └── container/
│       ├── Dockerfile
│       ├── docker-compose.yml
|       ├── entrypoint.sh
|       └── weather.def
├── scripts/
│   ├── build_container.sh
│   ├── common.sh  
│   ├── decompress.sh 
│   ├── download.sh 
│   ├── grb.sh build_container.sh
│   ├── run_pipeline_container.sh 
│   ├── run_pipeline.sh
│   └── setup_env.sh
├── meta.yaml           # Conda build recipe (at repo root)
├── pyproject.toml      # Package metadata & setuptools config
├── setup.ps1           # Windows PowerShell setup script
├── setup.bat           # Windows cmd.exe setup script
├── setup.sh            # For local Linux/macOS and HPC systems
├── .github/
│   ├── workflows/
│   │   ├── ci.yml      # Lint, type-check, test on push/PR
│   │   └── release.yml # Build & publish on v* tag
│   └── agents/
│       └── uu-buem-align.agent.md
├── .gitignore
├── LICENSE
├── README.md
└── CONTRIBUTING.md
```

## Provider Model

- `cosmo-rea6`: implemented
- `merra-2`: scaffolded
- `era5-land`: scaffolded

Naming recommendation:

- Keep `providers` as the folder name.
- Reason: this is the most common and industry-recognized term for pluggable
  data backends/sources; alternatives like `specific` are less explicit.
- If preferred, `sources` is a valid alternative, but `providers` is clearer
  for code architecture and extension.

Pipeline stages per provider:

- `download`
- `decompress`
- `transform`
- `final processing` (export)

Segregation rule:

- `src/weather/common/`: shared mechanics (e.g., HTTP/FTP download helpers,
  decompression primitives, retry/rate-limit/auth utilities).
- `src/weather/providers/<dataset>/`: dataset-specific definitions (variable
  lists, filenames/endpoints, transformations, derived fields, orchestration).

## Run Paths

For a source checkout, install the package in editable mode first:

```bash
conda env create -f infrastructure/env/weather_env.yml
conda activate weather_env
pip install -e .
```

Then use `python -m weather ...` or the `weather` console script:

```bash
python -m weather info
python -m weather validate
python -m weather run --provider cosmo-rea6 --months 1
```

If you install the package as a conda recipe, the `weather` command is
available directly:

```bash
weather info
weather validate
weather run --provider cosmo-rea6 --months 1
```

The pipeline for single year and multi-year is also ready now.
For executing this, the following test files need to be executed.

```bash
python ./src/weather/tests/test_one_year.py
```

with the following flags:

```text
  --year (default: 2018)
  --months (default: None)
  --ncores
  ...
```

and

```bash
python ./src/weather/tests/test_multi_year.py
```

with the following flags:

```text
  --from-year (default: 1995)
  --to-year (inclusive) (default: 2018)
  --ncores
  ...
```

The rest can be checked with `--help` or `-h`

Default provider can be set with:

```bash
export WEATHER_PROVIDER=cosmo-rea6
```

## Shell Script Paths

- Shared script config: `scripts/common.sh`
- Slurm full run: `scripts/run_pipeline.sh`
- Slurm container run: `scripts/run_pipeline_container.sh`
- Build container image: `scripts/build_container.sh`
- Create/update conda env: `scripts/setup_env.sh`

Default server paths used by scripts:

- Repository: `~/weather`
- Python source root: `~/weather/src`
- Data/work dir: `<repo>/data/cosmo_rea6` (or override in `.env`)

## Container and Environment Paths

- Conda environment file: `infrastructure/env/weather_env.yml`
- Dockerfile: `infrastructure/container/Dockerfile`
- Conda recipe: `meta.yaml`
- Apptainer definition: `infrastructure/container/weather.def`
- Compose file: `infrastructure/container/docker-compose.yml` (canonical;
  the root `docker-compose.yml` was removed to avoid duplication)

## Path Configuration (.env)

Create `.env` from `.env.example` to keep all runtime paths centralized.

```bash
cp .env.example .env
```

Key variables:

- `WEATHER_DATA_DIR` (default fallback: `<repo>/data`)
- `COSMO_WORK_DIR` (default fallback: `<WEATHER_DATA_DIR>/cosmo_rea6`)
- `WEATHER_PROVIDER` (default: `cosmo-rea6`)

Build examples:

```bash
# Docker
bash scripts/build_container.sh docker

# Apptainer (definition build)
bash scripts/build_container.sh def
```

## Notes

- COSMO-REA6 is production-ready in this structure.
- MERRA-2 and ERA5-Land have package directories ready for implementation.
- New provider-specific modules should be added under `src/weather/providers/<provider_name>/`.
