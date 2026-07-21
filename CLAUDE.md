# CLAUDE.md — weather package

Persistent context for Claude Code. Load the per-provider `.claude/` file
in play; check `.issues/` before working. Keep these docs updated when code
changes (same commit).

## >>> NEXT MAJOR TASKS <<<

1. **ERA5-Land percentile** — DONE (code). `providers/era5_land/
   percentile_index.py` mirrors COSMO's actual `percentile_index.py`
   (Finkelstein-Schafer KS-distance on monthly GHI; `base_percentile.
   BasePercentileAnalyzer` is dead code, superseded in commit `17d5eea`).
   Still needs a live smoke test AFTER bulk run + boundary repair.
   → `.claude/era5_land/era5_land_percentile_plan.md`
2. **MERRA-2 end-to-end verification** — code is complete (download via
   OPeNDAP/Earthdata session, transform, export, pipeline all
   implemented; see `.claude/merra2/merra2_context.md`), but not yet run
   against real GES DISC data. Do a single-month smoke test
   (`test_merra2_one_month.py`) once Earthdata credentials are
   configured, before a full bulk run. → `.claude/merra2/merra2_plan.md`
3. **MERRA-2 percentile / dni_pointwise** (optional, lower priority) —
   same pattern as ERA5-Land's pending percentile task once MERRA-2 is
   verified live; a point-wise DNI/DHI helper is also a documented,
   not-yet-built extension. → `.claude/merra2/merra2_plan.md`

## Operating rules for Claude Code (read first)

- **Minimize tokens.** Load only the provider file(s) in play; don't
  re-read files already in context; prefer dense edits over restating.
- **Right-size effort.** Trivial edits → just do them. Cross-provider or
  multi-file → plan briefly first. Don't over-engineer.
- **Keep docs current.** Change code/behaviour/decisions → update that
  provider's `.claude/*_context.md`/`*_plan.md` and `.issues/` in the SAME
  change. These are the source of truth for the next session.
- **Maintain modularity + simplicity.** Shared logic in `common/` and the
  `base_*` classes; provider-specific logic in the provider. Same module
  roles across providers.
- **Summarize file changes at the end of every response.** List every file
  created/modified/deleted in that turn (repo-relative paths), or state
  explicitly "No files were updated" if the turn was read-only (answering a
  question, investigating, reviewing). Keeps an audit trail the user can
  scan without re-deriving it from the conversation.

## Lint / tooling compliance (exact — CI enforces)

CI (`.github/workflows/ci.yml`) runs, and all must pass:
`ruff check src/` · `mypy src` · `pytest -q --cov=weather` ·
`python -m weather info`.

- **ruff** (`[tool.ruff]` in pyproject): line-length 88, target py312,
  select `E,F,W,I,UP,B,SIM`, ignore `E501`. So: sorted imports (I),
  pyupgrade (UP), bugbear (B), simplify (SIM). Global-imports-only.
  Bare excepts use `except Exception:  # noqa: BLE001`.
- **mypy**: `ignore_missing_imports=true`, `strict=false`, py312.
- **markdownlint** (`.markdownlint.json`): MD013 line_length **100**
  (tables exempt), MD018 off, MD024 siblings_only (duplicate headings OK
  if not siblings). Wrap prose at 100, label fenced blocks, blank lines
  around headings/lists/fences.
- **yamllint** (`.yamllint.yml`): line-length max 120; `meta.yaml` is
  ignored (Jinja2). Keep other YAML ≤120 and valid.
- **versions (pinned across UU-BUEM repos)**: python >=3.12 (NOT 3.14 — no
  conda-forge cfgrib/eccodes builds), numpy 1.26.*, pandas 2.2.*. Don't
  bump these.
- **packaging**: conda-only workflow; `pip install -e . --no-deps` (never
  `conda develop`); binaries (aria2, lbzip2, eccodes, cfgrib) in
  `weather_env.yml`, Python deps in `pyproject.toml`; `meta.yaml` version
  via Jinja2 `{% set version = ... %}`; never commit `_version.py`
  (setuptools-scm, `version_file=src/weather/_version.py`).

## CLI, containers, cross-repo

- **CLI**: `python -m weather {info,validate,run}` (entry `weather.cli:main`).
  `validate.py` at root runs env/CLI/tests/structure/docker checks.
- **Containers** (`infrastructure/container/`): Dockerfile, docker-compose.yml,
  entrypoint.sh route by `PIPELINE_MODE` ∈ {single-year, multi-year, merge,
  percentile, check}. `check` = imports + `weather info` + unit tests, no
  data. Env is `infrastructure/env/weather_env.yml`.
- **Cross-repo (UU-BUEM)**: weather ‖ occupancy ‖ buem share pins, CI
  (`.github/workflows/ci.yml`), Docker base (continuumio/miniconda3),
  `infrastructure/env/` layout, and `pip install -e .`. A change to any of
  these here usually needs the parallel change in the sibling repos.
  See `.github/agents/uu-buem-align.agent.md`.

## Repo tree (key paths)

```text
weather/
├── CLAUDE.md                      # this file (always loaded)
├── .claude/                       # per-provider context + plans (on-demand)
├── .issues/                       # open.md, resolved.md (check before work)
├── pyproject.toml  .markdownlint.json  .yamllint.yml
├── conda_build_config.yaml  meta.yaml  validate.py  CHANGELOG.md
├── .github/
│   ├── workflows/ci.yml  workflows/release.yml
│   ├── skills/weather-runtime-error-debug/SKILL.md  # numba-first debug
│   └── agents/uu-buem-align.agent.md                # cross-repo aligner
├── infrastructure/
│   ├── env/weather_env.yml
│   └── container/Dockerfile  docker-compose.yml  entrypoint.sh
└── src/weather/
    ├── settings.py                # EnvSettings: all *_ env → typed values
    ├── registry.py  cli.py  __main__.py
    ├── common/                    # shared, provider-agnostic
    │   ├── derived_attributes.py  # apply_derived_fields (GHI/DHI/DNI, all providers)
    │   ├── download.py            # https/ftp atomic, checksums
    │   ├── decompress.py          # bz2 helpers (lbzip2/pbzip2/python)
    │   ├── parallel.py            # run_parallel (thread/process pools)
    │   ├── merge.py               # monthly NC → annual NC (unused by percentile now)
    │   ├── percentile.py          # select_representative_years (dead code, unused)
    │   ├── net.py  validate.py  cleanup.py  env.py
    │   └── dni_methodology.md
    ├── providers/
    │   ├── base.py                # WeatherProvider Protocol
    │   ├── base_downloader.py     # is_complete→skip / _fetch ; DownloadJob
    │   ├── base_decompressor.py   # is_decompressed→skip / _decompress_file
    │   ├── base_percentile.py     # unused/dead code — see percentile_index.py
    │   ├── README.md
    │   ├── cosmo_rea6/            # PRODUCTION (reference impl)
    │   │   ├── config, downloaded_attributes, naming
    │   │   ├── download, downloader, decompress, decompressor
    │   │   ├── transform, export, pipeline, percentile_index, __init__
    │   ├── era5_land/             # pipeline DONE; bulk-run pending
    │   │   ├── config, downloaded_attributes
    │   │   ├── downloader, fast_download, download
    │   │   ├── transform, export, pipeline, pipeline_interleaved
    │   │   ├── percentile_index, dni_pointwise, __init__
    │   └── merra2/                # pipeline DONE; live verification pending
    │       ├── config, downloaded_attributes
    │       ├── downloader (OPeNDAP + Earthdata session), download
    │       ├── transform, export, pipeline, __init__
    └── tests/                      # runners + tools + pytest units
        ├── (pytest) test_validation, test_derived_attributes,
        │            test_pipeline_integration
        ├── (COSMO)  test_one_month, test_one_year, test_multi_year,
        │            test_percentile
        ├── (ERA5)   test_era5_one_month, test_era5_one_year,
        │            test_era5_multi_year
        ├── (ERA5 tools) repair_month_boundaries, verify_months,
        │            diagnose_nc, enumerate_month, check_boundary_steps,
        │            check_first_hour, inspect_era5_eccodes,
        │            inspect_era5_grib, audit_imports
        ├── (MERRA-2) test_merra2_one_month, test_merra2_one_year,
        │            test_merra2_multi_year
        └── mock_download            # CI helper
```

## Provider module roles (uniform)

config.py (EnvSettings→dict) · downloaded_attributes.py (raw-attr DICT) ·
naming.py (filenames/URLs; COSMO) · downloader.py (`BaseDownloader`) ·
download.py (orchestration) · decompress[or].py (`BaseDecompressor`; COSMO
bz2 only) · transform.py (raw→analysis-ready) · export.py (NetCDF, zlib
complevel=1, float32) · pipeline.py (wire phases; idempotent) ·
percentile_index.py (standalone KS-distance P10/P50/P90 script; optional) ·
`__init__.py` (façade).

## Providers at a glance (from source)

| provider   | source           | res        | files              | output         | ncores   |
|------------|------------------|------------|--------------------|----------------|----------|
| cosmo_rea6 | DWD OpenData     | 6 km       | monthly bz2        | monthly→annual | 94 (CPU) |
| era5_land  | Copernicus CDS   | 0.1°       | monthly nc         | monthly        | 6 (I/O)  |
| merra2     | GES DISC OPeNDAP | 0.5×0.625° | daily nc4, 2 coll. | monthly        | 8 (I/O)  |

- **RH source differs BY-DESIGN:** COSMO direct RELHUM_2M; ERA5-Land
  dew-point Magnus; MERRA-2 q-based. Do NOT unify.
- **Radiation:** COSMO splits direct(SWDIRS)+diffuse(SWDIFDS); ERA5-Land &
  MERRA-2 give GHI directly (ssrd-derived / SWGDN).
- `common/derived_attributes.apply_derived_fields(ds, provider, sol_pos,
  times)` is the ONE cross-provider entry for GHI/DHI/DNI. All providers
  night-mask + enforce GHI=DHI+DNI·cos(zenith); DNI cos-guard at zenith>85.
  (ERA5 pipeline's `night_mask=False` default concerns the monthly GHI
  field, distinct from this DNI-path masking.)

## Hard conventions (do not violate)

1. **Global imports only.** numpy/xarray/pandas/cfgrib at module top, never
   inside functions. Exception: optional dep in `try/except ImportError`
   (e.g. bottleneck). A local-import bug already cost a full failed run.
   Audit: `tests/audit_imports.py`. (Some COSMO modules still import inside
   functions — clean up when touched.)
2. **Extensibility via DICTs.** Raw attrs in `downloaded_attributes.py`;
   derived vars registered in `derived_attributes.py`. Add/remove = data
   edit, not code change.
3. **Simple, direct solutions.** Automate over hand-maintain; decide over
   asking repeatedly.
4. `from __future__ import annotations` in every module. NumPy docstrings;
   type hints; `logging` not print. Atomic writes (temp→rename).
   `HDF5_USE_FILE_LOCKING=FALSE` for NetCDF on parallel FS.
5. Python 3.12+; src-layout; setuptools-scm (never commit `_version.py`).

## Environment

conda env `weather_env`; prefer conda. Dev Windows; prod Linux `sd26`
(user `sahoo002`), 94 cores, 1 TB RAM, 15 TB disk. GitHub `UU-BUEM`.
