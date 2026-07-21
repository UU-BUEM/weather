# Open issues / TODOs

## >>> NEXT MAJOR TASKS <<<
- [era5_land] **Percentile analyzer** — DONE (code): `era5_land/
  percentile_index.py`, a KS-distance port of COSMO's actual
  `percentile_index.py` (NOT the dead `BasePercentileAnalyzer` design).
  Needs a live smoke test after bulk run + boundary repair. See
  .claude/era5_land/era5_land_percentile_plan.md.
- [merra2] **Complete provider** from scaffold: per-DAY job, implement
  downloader (3 stubs), then download/transform/export/pipeline. GES DISC
  netrc; SWGDN=GHI directly; q-based RH. See .claude/merra2_plan.md.

## era5_land
- [era5_land] Bulk 1950–2025 run not yet executed — see plan checklist.
  Apply _ffill_time import fix first.
- [era5_land] After run: MANDATORY repair_month_boundaries.py then
  verify_months.py before merge/percentile.
- [era5_land] pipeline_interleaved.py deferred (deliberately).

## cosmo_rea6
- [cosmo_rea6] export.py docstring references old `buem.weather` path.
- [cosmo_rea6] Local imports in export.py/pipeline.py — hoist to module
  level.
- [cosmo_rea6] Reconcile local naming.py (newer) with GitHub main.

## cross-provider
- [all] Run audit_imports.py across every provider; enforce global-imports.
- [all] Keep ruff/flake8/markdownlint clean; honour pyproject.toml/.flake8/
  markdownlint.json/conda_build_config.yml at root.
- [all] Confirm the three providers share the Europe box cell-for-cell
  (COSMO rotated-pole vs ERA5/MERRA2 regular grid — verify alignment).

## external (context only)
- [envelope-extractor] Apeldoorn municipality boundary bug pending
  diagnostics (separate UU-BUEM package).
