# Weather

Standalone weather processing repository for `UU-BUEM`.

This repository uses a provider-based architecture with a standard Python `src/` layout and separate infrastructure folders for environment and container assets.

## Project Structure

```text
weather/
├── src/
│   └── weather/
│       ├── __init__.py
│       ├── __main__.py
│       ├── _version.py
│       ├── cli.py
│       ├── registry.py
│       ├── common/
│       │   ├── __init__.py
│       │   ├── cleanup.py
│       │   ├── decompress.py
│       │   ├── download.py
│       │   ├── validate.py
│       │   └── ...
│       ├── providers/
│       │   ├── __init__.py
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
│       │   │   └── __init__.py
│       │   └── era5_land/
│       │       └── __init__.py
│       └── from_csv.py
├── infrastructure/
│   ├── env/
│   │   └── weather_env.yml
│   └── container/
│       ├── Dockerfile
│       └── docker-compose.yml
├── scripts/
│   ├── common.sh
│   ├── setup_env.sh
│   ├── run_pipeline.sh
│   ├── run_pipeline_container.sh
│   ├── build_container.sh
│   ├── download.sh
│   ├── decompress.sh
│   └── grb.sh
├── meta.yaml           # Conda build recipe (at repo root)
├── pyproject.toml      # Package metadata & setuptools config
├── setup.ps1           # Windows setup script
├── setup.bat           # Windows batch setup
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

The root `docker-compose.yml` was removed to avoid duplicated container
definitions. Use `infrastructure/container/docker-compose.yml` as the single
canonical compose file.

## Run Paths

For a source checkout, use `python -m weather ...` with `src/` on
`PYTHONPATH`.

```bash
export PYTHONPATH=$(pwd)/src
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

## Path Configuration (.env)

Create `.env` from `.env.example` to keep all runtime paths centralized.

```bash
cp .env.example .env
```

Key variables:

- `WEATHER_DATA_DIR` (default fallback: `<repo>/data`)
- `COSMO_WORK_DIR` (default fallback: `<WEATHER_DATA_DIR>/cosmo_rea6`)
- `CONDA_BLD_PATH` (recommended: `<repo>/.conda-bld`)

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
