#!/usr/bin/env python3
"""Single-month MERRA-2 pipeline test.

Downloads, transforms, and exports one month to
``MERRA2_<YYYY>_<MM>_all_attrs.nc``.

Usage
-----
::

    python src/weather/tests/test_merra2_one_month.py --year 2018 --month 1
    python src/weather/tests/test_merra2_one_month.py \\
        --year 2018 --month 1 --skip-download --resume

Flags
-----
--year YEAR         Year to process (default: MERRA_YEAR / config)
--month MONTH       Month 1-12 (required)
--work-dir DIR      Override MERRA_WORK_DIR
--ncores N          Transform workers (default: config)
--skip-download     Re-use existing daily NetCDF4 files
--resume            Skip if the output .nc already exists
--cleanup           Delete daily files after a successful export
"""

from __future__ import annotations

import argparse
import logging

from weather.providers.merra2.pipeline import run_pipeline
from weather.settings import EnvSettings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="MERRA-2 single-month pipeline test",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--year", type=int, default=None, metavar="YEAR")
    p.add_argument(
        "--month", type=int, required=True, metavar="MONTH",
        help="Month to process (1-12)",
    )
    p.add_argument("--work-dir", default=None, metavar="DIR")
    p.add_argument("--ncores", type=int, default=None, metavar="N")
    p.add_argument("--skip-download", action="store_true")
    p.add_argument("--resume", action="store_true")
    p.add_argument(
        "--cleanup", action="store_true",
        default=EnvSettings.merra2_cleanup(),
        help="Delete daily files after export (default: keep, via MERRA_CLEANUP)",
    )
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    if not 1 <= args.month <= 12:
        raise SystemExit(f"--month {args.month} out of range (1-12)")

    run_pipeline(
        year=args.year,
        months=[args.month],
        work_dir=args.work_dir,
        ncores=args.ncores,
        skip_download=args.skip_download,
        resume=args.resume,
        cleanup=args.cleanup,
    )


if __name__ == "__main__":
    main()
