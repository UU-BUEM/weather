#!/usr/bin/env python3
"""Single-year MERRA-2 pipeline: all 12 months of one year.

Downloads, transforms, and exports 12 monthly files
``MERRA2_<YYYY>_<MM>_all_attrs.nc`` into the output folder.

Usage
-----
::

    python src/weather/tests/test_merra2_one_year.py --year 2018 --ncores 12
    python src/weather/tests/test_merra2_one_year.py \\
        --year 2018 --skip-download --resume

Flags
-----
--year YEAR         Year to process (default: MERRA_YEAR / config)
--months M [M ...]  Subset of months (default: 1..12)
--work-dir DIR      Override MERRA_WORK_DIR
--ncores N          Transform workers (default: config)
--skip-download     Re-use existing daily NetCDF4 files
--resume            Skip months whose output .nc already exists
--cleanup           Delete daily files after successful export
"""

from __future__ import annotations

import argparse
import logging

from weather.common.cli_flags import (
    add_cleanup_flag,
    add_resume_flag,
    add_skip_download_flag,
)
from weather.providers.merra2.pipeline import run_pipeline
from weather.settings import EnvSettings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="MERRA-2 single-year pipeline test",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--year", type=int, default=None, metavar="YEAR")
    p.add_argument(
        "--months", type=int, nargs="+", default=None, metavar="M",
        help="Subset of months to process (default: all 12)",
    )
    p.add_argument("--work-dir", default=None, metavar="DIR")
    p.add_argument("--ncores", type=int, default=None, metavar="N")
    add_skip_download_flag(p)
    add_resume_flag(p)
    add_cleanup_flag(p, default=EnvSettings.merra2_cleanup())
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    months = args.months
    if months:
        bad = [m for m in months if not 1 <= m <= 12]
        if bad:
            raise SystemExit(f"months out of range (1-12): {bad}")

    run_pipeline(
        year=args.year,
        months=months,
        work_dir=args.work_dir,
        ncores=args.ncores,
        skip_download=args.skip_download,
        resume=args.resume,
        cleanup=args.cleanup,
    )


if __name__ == "__main__":
    main()
