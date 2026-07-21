#!/usr/bin/env python3
"""Multi-year ERA5-Land pipeline: every year in a range.

Mirrors the COSMO-REA6 ``test_cosmo_multi_year.py`` flag structure and
delegates each year to ``test_era5_one_year.py`` in a child process.

Flow
----
::

    test_era5_multi_year.py
      ├─ ThreadPoolExecutor(max_workers=parallel_years)
      │    └─ For each year in [from_year … to_year]:
      │         subprocess: python test_era5_one_year.py --year YEAR
      │              └─ Phase 1 — Download (CDS, low concurrency)
      │              └─ Phase 2 — Transform + Export
      │                  └─ 12 × ERA5_LAND_<YYYY>_<MM>_all_attrs.nc
      └─ Summary: pass/fail per year

ERA5-Land coverage
------------------
ERA5-Land runs from **1950 to present**, with a preliminary
back-extension to **1940**.  The defaults below cover 1940 → 2025;
adjust ``--to-year`` as newer years are released.

.. note::
   Download is rate-limited by the Copernicus CDS request queue, not by
   local CPU.  Running many years in parallel mostly multiplies the
   number of queued CDS requests; raise ``--parallel-years`` cautiously
   and watch for CDS rejections.

Usage
-----
All years (sequential)::

    python src/weather/tests/test_era5_multi_year.py \\
        --from-year 1940 --to-year 2025 --ncores 12

Two years at a time::

    python src/weather/tests/test_era5_multi_year.py \\
        --from-year 2000 --to-year 2018 --ncores 24 --parallel-years 2

Resume an interrupted run::

    python src/weather/tests/test_era5_multi_year.py \\
        --from-year 1940 --to-year 2025 --resume

Flags
-----
--from-year YEAR     First year (default: 1940)
--to-year YEAR       Last year, inclusive (default: 2025)
--ncores N           Total transform cores shared across parallel years
--parallel-years N   Years to run simultaneously (default: 1)
--work-dir DIR       Override ERA5_WORK_DIR
--resume             Skip years where all 12 monthly NCs exist
--skip-download      Re-use existing monthly GRIBs
--night-mask         Enable Spencer SZA night-masking (default off)
--cleanup            Delete GRIBs after successful export
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

_here = Path(__file__).resolve().parent
_TEST_ONE_YEAR = _here / "test_era5_one_year.py"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("era5_multi_year")


def _all_monthly_exist(year: int, out_dir: Path) -> bool:
    """True if all 12 monthly NCs for *year* are already present."""
    return all(
        (out_dir / f"ERA5_LAND_{year}_{m:02d}_all_attrs.nc").exists()
        for m in range(1, 13)
    )


def run_year(
    year: int,
    ncores_per_year: int,
    args: argparse.Namespace,
) -> tuple[int, bool, str]:
    """Run ``test_era5_one_year.py`` for *year* in a child process."""
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
    if args.night_mask:
        cmd.append("--night-mask")
    if args.cleanup:
        cmd.append("--cleanup")

    logger.info("  [start] year %d  (ncores: %d)", year, ncores_per_year)
    result = subprocess.run(cmd, check=False)  # noqa: S603
    if result.returncode == 0:
        return year, True, "OK"
    return year, False, f"exit code {result.returncode}"


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Multi-year ERA5-Land pipeline — processes every year in "
            "[from_year, to_year] via test_era5_one_year.py."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--from-year", type=int, default=1940, metavar="YEAR")
    p.add_argument("--to-year", type=int, default=2025, metavar="YEAR")
    p.add_argument(
        "--ncores", type=int, default=None, metavar="N",
        help="Total transform cores shared across parallel years",
    )
    p.add_argument(
        "--parallel-years", type=int, default=1, metavar="N",
        help="Years to run simultaneously (cores divided evenly)",
    )
    p.add_argument("--work-dir", default=None, metavar="DIR")
    p.add_argument("--resume", action="store_true")
    p.add_argument("--skip-download", action="store_true")
    p.add_argument("--night-mask", action="store_true")
    p.add_argument("--cleanup", action="store_true")
    return p.parse_args()


def main() -> None:
    args = _parse_args()

    if args.ncores is None:
        try:
            ncores = int(os.environ.get("ERA5_NCORES", "4"))
        except ValueError:
            ncores = 4
    else:
        ncores = args.ncores

    parallel = max(1, args.parallel_years)
    ncores_per_year = max(1, ncores // parallel)
    years = list(range(args.from_year, args.to_year + 1))

    # CDS runs ~one job per account at a time, so running multiple years
    # in parallel does NOT speed up downloads — the extra years' requests
    # just queue.  It only overlaps transforms, at the cost of dividing
    # cores and complicating the run.  Warn if the user set it > 1.
    if parallel > 1:
        cds_conc = os.environ.get("ERA5_CDS_MAX_CONCURRENT", "1")
        logger.warning(
            "--parallel-years=%d: downloads are CDS-queue-limited "
            "(ERA5_CDS_MAX_CONCURRENT=%s), so parallel years do NOT "
            "download faster — they only overlap transforms while "
            "splitting cores %d ways. --parallel-years 1 is recommended.",
            parallel, cds_conc, parallel,
        )

    # Resolve output dir for the fast whole-year resume check.
    out_dir: Path | None = None
    if args.work_dir:
        out_dir = Path(args.work_dir) / "output"
    else:
        _wd = os.environ.get("ERA5_WORK_DIR")
        if _wd:
            out_dir = Path(_wd) / "output"

    logger.info("=" * 68)
    logger.info("ERA5-Land Multi-Year Pipeline")
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
    passed: list[int] = []
    failed: list[tuple[int, str]] = []
    skipped: list[int] = []

    years_to_run: list[int] = []
    for yr in years:
        if args.resume and out_dir and _all_monthly_exist(yr, out_dir):
            logger.info("  SKIP year %d — all 12 monthly NCs present", yr)
            skipped.append(yr)
        else:
            years_to_run.append(yr)

    if not years_to_run:
        logger.info("All years already complete. Nothing to do.")
    elif parallel == 1:
        for yr in years_to_run:
            _yr, ok, msg = run_year(yr, ncores_per_year, args)
            if ok:
                passed.append(_yr)
            else:
                failed.append((_yr, msg))
            logger.info(
                "  [%s] year %d  %s",
                "done " if ok else "FAIL ", _yr, msg,
            )
    else:
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

    elapsed = time.perf_counter() - t_total
    logger.info("")
    logger.info("=" * 68)
    logger.info("Multi-Year Pipeline — COMPLETE")
    logger.info(
        "  Passed  : %d  %s",
        len(passed), str(sorted(passed)) if passed else "",
    )
    if skipped:
        logger.info("  Skipped : %d", len(skipped))
    if failed:
        logger.error(
            "  FAILED  : %d  %s",
            len(failed), str(sorted(failed)),
        )
    logger.info(
        "  Total time : %.1f s  (%.1f min)", elapsed, elapsed / 60,
    )
    logger.info("=" * 68)

    if failed:
        failed_str = ", ".join(str(y) for y, _ in sorted(failed))
        sys.exit(f"{len(failed)} year(s) failed: {failed_str}")


if __name__ == "__main__":
    main()
