# Contributing

Thank you for your interest in contributing to the **weather** pipeline!

---

## Development Setup

### Prerequisites

- [Miniconda](https://docs.conda.io/en/latest/miniconda.html) or Miniforge
- Python 3.14+
- Git

### Quick Setup (Windows)

```powershell
# One-command setup — creates env + registers package for development
.\setup.ps1
conda activate weather_env
```

The setup script also sets environment vars for clean local paths:

- `WEATHER_DATA_DIR=<repo>\data`
- `COSMO_WORK_DIR=<repo>\data\cosmo_rea6`
- `CONDA_BLD_PATH=<repo>\.conda-bld`

Then verify with:

```powershell
python -m weather info
```

### Quick Setup (Linux / macOS / HPC)

```bash
# Create environment and set up package for development
bash infrastructure/env/setup.sh  # or create manually:
# conda env create -f infrastructure/env/weather_env.yml
# conda activate weather_env
# conda develop src
```

Then verify with:

```bash
python -m weather info
```

---

## Development vs. Deployment

### 🔧 Development Workflow (for contributors)

After running `./setup.ps1` or `conda develop src`:

```powershell
conda activate weather_env
python -m weather info         # ← Use the __main__.py shim
python -m weather validate
python -m weather run --help
```

**Why `python -m weather`?**

- `conda develop src` makes the source directory importable but does NOT install console scripts.
- It's ideal for development because code changes are picked up immediately (no rebuild needed).

### 📦 Installation Workflow (for deployment / end-users)

To test how the package works for users who install it (e.g., after cloning your fork):

```powershell
# Build the conda package
conda install -n weather_env conda-build
conda build .

# Install it into the environment
conda install -n weather_env --use-local weather

# Now the 'weather' command is available directly
weather info
weather validate
weather run --help
```

To remove temporary build/test directories:

```powershell
conda build purge
```

If your local conda config ignores recipe channel settings, run:

```powershell
conda build . -c conda-forge -c defaults
```

**Why `weather` (the console script)?**

- When installed as a package, `setuptools` registers the entry point from `pyproject.toml`
  (`weather = "weather.cli:main"`).
- This creates a `weather.exe` (Windows) or `weather` script (Unix) in the environment's Scripts/ folder.
- Users don't need to understand `python -m`; they just run `weather`.

---

## Build Configuration

**meta.yaml** (at repo root):

- Conda build recipe used by `conda build .`
- Defines host/run dependencies and the build process.
- Recipe version is currently pinned for stable local conda builds.

**pyproject.toml**:

- Standard Python packaging metadata.
- Entry point: `weather = "weather.cli:main"`
- Build backend: `setuptools.build_meta`
- Includes optional dependencies: `solar`, `parquet`, `era5`, `dev`.

---

## Notes

- This project intentionally **avoids `pip install -e`** to prevent mixed pip/conda state.
- `conda develop` is provided by `conda-build` (already in `weather_env.yml`).
- After changes to entry points or dependencies, run `conda develop src` again (or reinstall the package).

---

## Project Structure

```text
weather/
├── src/weather/              # Python package (src-layout standard)
│   ├── __init__.py
│   ├── __main__.py           # Enables: python -m weather
│   ├── _version.py           # Single source of version truth (from setuptools-scm)
│   ├── cli.py                # CLI entry point (weather.cli:main)
│   ├── registry.py           # Lazy provider registry
│   ├── common/               # Shared utilities
│   │   ├── __init__.py
│   │   ├── net.py            # HTTP/FTP helpers, retry, auth
│   │   └── ...
│   └── providers/            # Pluggable data providers
│       ├── __init__.py
│       ├── base.py           # Abstract WeatherProvider class
│       ├── cosmo_rea6/       # DWD OpenData (fully implemented)
│       ├── merra2/           # NASA GES DISC (scaffold)
│       └── era5_land/        # Copernicus CDS (scaffold)
├── infrastructure/
│   ├── env/
│   │   └── weather_env.yml   # Conda environment specification
│   └── container/
│       ├── Dockerfile        # Docker build
│       └── docker-compose.yml
├── shell_scripts/            # SLURM / HPC shell scripts (optional)
├── meta.yaml                 # Conda build recipe (at repo root)
├── pyproject.toml            # Package metadata & build config
├── setup.ps1                 # Windows setup script
├── setup.bat                 # Windows batch setup
├── .gitignore
├── LICENSE
├── README.md
└── CONTRIBUTING.md
```

---

## Code Standards

- **Formatter / Linter**: [Ruff](https://docs.astral.sh/ruff/) — `ruff format . && ruff check .`
- **Type checking**: mypy (optional, `mypy src/`)
- **Line length**: 88 characters (Ruff default)
- **Import order**: isort-style via Ruff `I` rule-set
- **Python target**: 3.14+

---

## Adding a New Provider

1. Create `src/weather/providers/<provider_name>/` as a Python package.
2. Add `__init__.py` with a class that inherits from
   `weather.providers.base.WeatherProvider`.
3. Implement the three abstract methods:
   - `get_config_summary() -> dict`
   - `validate_environment() -> None`
   - `run_pipeline(**kwargs) -> None`
4. Register the provider in `src/weather/registry.py` (`_REGISTRY` dict +
   any aliases in `_ALIASES`).
5. Add the provider to `weather_env.yml` if it needs new dependencies.

---

## Running Tests

```bash
pytest
# or with coverage
pytest --cov=weather --cov-report=term-missing
```

---

## Commit Convention

Use [Conventional Commits](https://www.conventionalcommits.org/):

```text
feat: add ERA5-Land download step
fix: correct COSMO bz2 decompression path on Snellius
docs: update provider README section
chore: bump Python 3.14 in weather_env.yml
```

---

## Pull Requests

- Keep PRs focused on a single concern.
- Add or update tests for any changed behaviour.
- Run `ruff format . && ruff check .` before pushing.
- Update `CHANGELOG.md` under `[Unreleased]`.
