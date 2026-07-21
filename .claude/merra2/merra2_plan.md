# MERRA-2 — completion status

**DONE.** Implementation complete following the ERA5-Land/COSMO-REA6
pattern (OPeNDAP access, 2 collections, monthly output, no decompress
phase). See `merra2_context.md` for the current engineering state and
`docs/MERRA2_PIPELINE_GUIDE.md` for the full user-facing guide (auth
setup, collection/attribute table, RH formula derivation, grid-alignment
caveat, running the pipeline).

## What was built

1. `Merra2DownloadJob(collection, year, month, day)` in `downloader.py`
   — per-day, per-collection granularity (sanctioned by
   `base_downloader.py`'s own docstring, which names MERRA-2 as the
   example provider needing a different job shape).
2. `downloader.py`: all 3 `BaseDownloader` stubs implemented — OPeNDAP
   constraint-URL construction (`_bbox_indices`/`build_url`),
   existence-based `remote_size` (always `None`, like ERA5-Land's CDS
   queue rationale), `_fetch` via an Earthdata-authenticated,
   redirect-safe session (`common.net.build_session(...,
   preserve_auth_hosts=...)`).
3. `download.py`: `download_all()` — one job per (collection, day),
   parallelized via `common.parallel.run_parallel`.
4. `transform.py`: merges rad+slv daily files -> monthly dataset; `T2M`
   K->degC; `GHI = SWGDN` direct (via the registry, `fields=["GHI"]`
   only — DHI/DNI deliberately NOT computed, see below); `WS_10M =
   sqrt(U10M**2+V10M**2)`; new specific-humidity RH formula
   (`_compute_rh`, Bolton 1980); dims renamed to `y`/`x` matching
   COSMO/ERA5-Land.
5. `export.py`/`pipeline.py`: near-verbatim ERA5-Land pattern (zlib
   complevel=1, float32; `ProcessPoolExecutor` per-month transform+
   export; no decompress phase).
6. `__init__.py`: `MERRA2Provider` completes the `WeatherProvider`
   protocol; `validate_environment()` reuses `common.net
   .earthdata_auth()`.
7. Test scripts: `test_merra2_one_month.py`, `test_merra2_one_year.py`,
   `test_merra2_multi_year.py` (mirror ERA5-Land's exactly, no
   `--night-mask` flag needed).

## Deliberate scope decisions (see docs/MERRA2_PIPELINE_GUIDE.md for why)

- **2 collections, not 3**: `M2T1NXRAD` (SWGDN + ALBEDO) +
  `M2T1NXSLV` (T2M, QV2M, U/V winds, PS). `SNODP`/`PRECSNOLAND`
  (`M2T1NXLND`) dropped — ALBEDO judged higher-value and free within
  the existing RAD request.
- **GHI only in bulk** — DHI/DNI deferred to a future
  `merra2/dni_pointwise.py` (mirrors ERA5-Land's opt-in point-wise
  helper), since pvlib DIRINT can't broadcast over the full grid.
- **No cross-provider regridding** — same geographic Europe box as
  ERA5-Land, but MERRA-2's own native 0.5°x0.625° grid, not
  interpolated onto ERA5-Land's 0.1° grid.

## Remaining follow-ups (not blocking, future work)

1. **End-to-end verification against real GES DISC data** — not yet
   run with real Earthdata credentials; do a single-month smoke test
   first (`test_merra2_one_month.py`) before a full bulk run.
2. **Optional `percentile.py`** (`Merra2PercentileAnalyzer(
   BasePercentileAnalyzer)`) — not built in this phase; would need
   `common.merge` (monthly -> annual) first, same as ERA5-Land's
   pending percentile task.
3. **Optional `merra2/dni_pointwise.py`** — point-wise DNI/DHI
   decomposition, mirroring `era5_land/dni_pointwise.py`.
4. **Optional `M2T1NXLND` collection** — if snow variables (`SNODP`,
   `PRECSNOLAND`) become needed later.
5. Benchmark `opendap_max_concurrent`/`ncores` empirically once real
   runs happen; update `CLAUDE.md`'s provider table (currently `TBD`)
   accordingly.

## Conventions enforced

Global imports only (verified via `audit_imports.py`); attributes stay
a DICT; `from __future__ import annotations`; NumPy docstrings; logging
not print; `ruff`/`mypy` clean (verified against this repo's actual
CI gate, not just a generic linter).
