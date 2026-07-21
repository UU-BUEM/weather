# COSMO-REA6 — plan

Confidence: HIGH. Production-ready; percentile analyzer exists.

## Status
Download/decompress/transform/export/pipeline implemented.
CosmoPercentileAnalyzer (P10/P50/P90 GHI, 1995–2018) complete.

## Small touch-ups (low priority)
- export.py docstring: old `buem.weather` path → current package path.
- Hoist local imports in export.py/pipeline.py to module level (global-
  imports convention); run audit_imports.py on cosmo_rea6/*.py.
- Reconcile local naming.py (newer) with GitHub main; commit.
- Keep ruff/flake8/markdownlint clean.

## No open functional issues.
Reference implementation for the other providers.
