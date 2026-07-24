#!/usr/bin/env python3
"""Multi-year COSMO-REA6 pipeline: all years from 1995 to 2018.

Flow
----
::

    test_cosmo_multi_year.py
      ├─ ThreadPoolExecutor(max_workers=parallel_years)
      │    └─ For each year in [from_year … to_year]:
      │         subprocess: python test_cosmo_one_year.py --year YEAR
      │           --ncores (ncores // parallel_years) [flags]
      │              └─ Phase 1 — Download   (ThreadPoolExecutor)
      │              └─ Phase 2 — Decompress (ProcessPoolExecutor)
      │              └─ Phase 3 — Transform/Export
      │                  └─ 12 × COSMO_REA6_<YYYY>_<MM>_all_attrs.nc
      │
      └─ Summary: pass/fail per year

Parallelism
-----------
By default years run **sequentially** (``--parallel-years 1``).
Increase to run multiple years simultaneously.  Each active year
receives ``ncores // parallel_years`` dask workers.

Example breakdown with 96 cores and 24 years (1995–2018):

+-------------------+-------------+-----------+-----------+
| --parallel-years  | cores/year  | ~min/year | ~total    |
+===================+=============+===========+===========+
| 1 (default)       | 96          | 30        | ~12 h     |
| 2                 | 48          | 40        | ~8 h      |
| 4                 | 24          | 60        | ~6 h      |
+-------------------+-------------+-----------+-----------+

Memory: each active year needs ~30 GB peak (one month at a time).
With ``--parallel-years 4`` on a 256 GB node → ~120 GB peak — safe.

Output
------
For each year:
  12 × ``COSMO_REA6_<YYYY>_<MM>_all_attrs.nc`` in ``<out_dir>/``

Annual merge (post-processing, optional — needed for percentile
analysis):
  ``python -m weather.common.merge \\``
  ``    --input  <out>/COSMO_REA6_<YYYY>_??_all_attrs.nc \\``
  ``    --output <out>/COSMO_REA6_<YYYY>_annual_all_attrs.nc``

Usage
-----
Basic (all 24 years, sequential)::

    python src/weather/tests/test_cosmo_multi_year.py \\
        --from-year 1995 --to-year 2018 --ncores 94

Parallel (4 years at once)::

    python src/weather/tests/test_cosmo_multi_year.py \\
        --from-year 1995 --to-year 2018 \\
        --ncores 96 --parallel-years 4

Resume interrupted run::

    python src/weather/tests/test_cosmo_multi_year.py \\
        --from-year 1995 --to-year 2018 --ncores 94 --resume

Flags
-----
--from-year YEAR        First year to process (default: 1995)
--to-year YEAR          Last year to process  (default: 2018)
--ncores N              Total cores shared across parallel years
--parallel-years N      Number of years to process simultaneously
                        (default: 1; cores are divided evenly)
--work-dir DIR          Override COSMO_WORK_DIR
--resume                Skip years where all 12 monthly NCs exist
--skip-download         Re-use existing .grb.bz2 files
--skip-decompress       Re-use existing .grb files
--skip-dni              Skip experimental per-cell DNI computation
--no-cleanup            Keep all intermediate files
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from weather.settings import EnvSettings

_here = Path(__file__).resolve().parent   # src/weather/tests/
_TEST_ONE_YEAR = _here / "test_cosmo_one_year.py"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("cr6_multi_year")


# ---------------------------------------------------------------------------
# Per-year runner
# ---------------------------------------------------------------------------

def _all_monthly_exist(year: int, out_dir: Path) -> bool:
    """Return True if all 12 monthly NCs for *year* are already present."""
    return all(
        (out_dir / f"COSMO_REA6_{year}_{m:02d}_all_attrs.nc").exists()
        for m in range(1, 13)
    )


def run_year(
    year: int,
    ncores_per_year: int,
    args: argparse.Namespace,
) -> tuple[int, bool, str]:
    """Run ``test_cosmo_one_year.py`` for *year* in a child process.

    Parameters
    ----------
    year:
        Four-digit year to process.
    ncores_per_year:
        Core budget passed as ``--ncores`` to the subprocess.
    args:
        Parsed CLI namespace from this script (flags are forwarded).

    Returns
    -------
    tuple[int, bool, str]
        ``(year, success, message)``
    """
    cmd = [
        sys.executable, str(_TEST_ONE_YEAR),
        "--year", str(year),
        "--ncores", str(ncores_per_year),
    ]
    if args.work_dir:
        cmd += ["--work-dir", args.work_dir]
    if args.resume:
        cmd.append("--resume")
    if args.skip_download:
        cmd.append("--skip-download")
    if args.skip_decompress:
        cmd.append("--skip-decompress")
    if args.skip_dni:
        cmd.append("--skip-dni")
    if args.no_cleanup:
        cmd.append("--no-cleanup")

    logger.info("  [start] year %d  (ncores: %d)", year, ncores_per_year)
    result = subprocess.run(cmd, check=False)  # noqa: S603

    if result.returncode == 0:
        return year, True, "OK"
    return year, False, f"exit code {result.returncode}"


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Multi-year COSMO-REA6 pipeline — processes every year in "
            "[from_year, to_year] by delegating to test_cosmo_one_year.py."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--from-year", type=int, default=EnvSettings.cosmo_from_year(),
        metavar="YEAR",
        help="First year to process (default: COSMO_FROM_YEAR env var or 1995)",
    )
    p.add_argument(
        "--to-year", type=int, default=EnvSettings.cosmo_to_year(),
        metavar="YEAR",
        help=(
            "Last year to process, inclusive "
            "(default: COSMO_TO_YEAR env var or 2018)"
        ),
    )
    p.add_argument(
        "--ncores", type=int, default=None, metavar="N",
        help=(
            "Total core budget shared across all parallel years "
            "(default: COSMO_NCORES env var or 4)"
        ),
    )
    p.add_argument(
        "--parallel-years", type=int, default=1, metavar="N",
        help=(
            "Number of years to run simultaneously.  "
            "Each year receives ncores // parallel_years workers.  "
            "Increase carefully: each active year peaks at ~30 GB RAM."
        ),
    )
    p.add_argument(
        "--work-dir", default=None, metavar="DIR",
        help="Override COSMO_WORK_DIR for all subprocesses",
    )
    p.add_argument(
        "--resume", action="store_true",
        help=(
            "Skip years where all 12 monthly NCs already exist. "
            "Also forwarded to test_cosmo_one_year.py (skips individual months)."
        ),
    )
    p.add_argument(
        "--skip-download", action="store_true",
        help="Re-use existing .grb.bz2 files",
    )
    p.add_argument(
        "--skip-decompress", action="store_true",
        help="Re-use existing .grb files",
    )
    p.add_argument(
        "--skip-dni", action="store_true",
        help="Skip experimental per-cell DNI computation",
    )
    p.add_argument(
        "--no-cleanup", action="store_true",
        default=not EnvSettings.cosmo_cleanup(),
        help="Keep intermediate files (default: keep, via COSMO_CLEANUP)",
    )
    return p.parse_args()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    import os  # noqa: PLC0415
    import time  # noqa: PLC0415

    args = _parse_args()

    # Resolve ncores from env if not given on CLI
    if args.ncores is None:
        try:
            ncores = int(os.environ.get("COSMO_NCORES", "4"))
        except ValueError:
            ncores = 4
    else:
        ncores = args.ncores

    parallel = max(1, args.parallel_years)
    ncores_per_year = max(1, ncores // parallel)

    years = list(range(args.from_year, args.to_year + 1))

    # Resolve output dir for the fast-resume whole-year check
    out_dir: Path | None = None
    if args.work_dir:
        out_dir = Path(args.work_dir) / "output"
    else:
        _cosmo_dir = os.environ.get("COSMO_WORK_DIR")
        if _cosmo_dir:
            out_dir = Path(_cosmo_dir) / "output"

    logger.info("=" * 68)
    logger.info("COSMO-REA6 Multi-Year Pipeline")
    logger.info(
        "  Years          : %d – %d  (%d total)",
        args.from_year, args.to_year, len(years),
    )
    logger.info("  Parallel years : %d", parallel)
    logger.info(
        "  Cores/year     : %d  (total %d ÷ %d)",
        ncores_per_year, ncores, parallel,
    )
    logger.info(
        "  Resume         : %s",
        "yes — skip complete years" if args.resume else "no",
    )
    logger.info("=" * 68)

    t_total = time.perf_counter()
    passed:  list[int] = []
    failed:  list[tuple[int, str]] = []
    skipped: list[int] = []

    # Fast-skip: if resume + all 12 monthly NCs exist, skip subprocess call
    years_to_run: list[int] = []
    for yr in years:
        if args.resume and out_dir and _all_monthly_exist(yr, out_dir):
            logger.info(
                "  SKIP year %d — all 12 monthly NCs present", yr,
            )
            skipped.append(yr)
        else:
            years_to_run.append(yr)

    if not years_to_run:
        logger.info("All years already complete.  Nothing to do.")
    elif parallel == 1:
        # Sequential — simple loop, cleaner log output
        for yr in years_to_run:
            _yr, ok, msg = run_year(yr, ncores_per_year, args)
            if ok:
                passed.append(_yr)
                logger.info("  [done ] year %d  OK", _yr)
            else:
                failed.append((_yr, msg))
                logger.error("  [FAIL ] year %d  %s", _yr, msg)
    else:
        # Parallel — ThreadPoolExecutor manages concurrent subprocesses.
        # subprocess.run() releases the GIL so threads are fine here.
        with ThreadPoolExecutor(max_workers=parallel) as pool:
            futures = {
                pool.submit(run_year, yr, ncores_per_year, args): yr
                for yr in years_to_run
            }
            for fut in as_completed(futures):
                _yr, ok, msg = fut.result()
                if ok:
                    passed.append(_yr)
                    logger.info("  [done ] year %d  OK", _yr)
                else:
                    failed.append((_yr, msg))
                    logger.error("  [FAIL ] year %d  %s", _yr, msg)

    # ── Summary ───────────────────────────────────────────────────────────
    elapsed = time.perf_counter() - t_total
    logger.info("")
    logger.info("=" * 68)
    logger.info("Multi-Year Pipeline — COMPLETE")
    logger.info(
        "  Passed  : %d  %s",
        len(passed),
        str(sorted(passed)) if passed else "",
    )
    if skipped:
        logger.info(
            "  Skipped : %d  (all 12 monthly NCs already present)",
            len(skipped),
        )
    if failed:
        logger.error(
            "  FAILED  : %d  %s",
            len(failed),
            str([(yr, msg) for yr, msg in sorted(failed)]),
        )
    logger.info(
        "  Total time : %.1f s  (%.1f min)", elapsed, elapsed / 60,
    )
    logger.info("=" * 68)

    if failed:
        failed_str = ", ".join(str(y) for y, _ in sorted(failed))
        sys.exit(f"{len(failed)} year(s) failed: {failed_str}")

    # ── Final directory cleanup ───────────────────────────────────────────
    # Try to remove the download/ and decompress/ parent directories now
    # that all years have cleared their per-attribute subdirs.  This only
    # succeeds when every attr subdir was already removed by test_one_year;
    # it silently skips if any content remains or paths are unknown.
    if not args.no_cleanup and out_dir is not None:
        _work_path = out_dir.parent   # work_dir = parent of output/
        for _d_name in ("download", "decompress"):
            _d = _work_path / _d_name
            if _d.exists():
                try:
                    _d.rmdir()
                    logger.info("Removed empty dir: %s", _d)
                except OSError:
                    pass  # still has content — leave it


if __name__ == "__main__":
    main()
