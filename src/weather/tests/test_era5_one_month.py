#!/usr/bin/env python3
"""Single-month ERA5-Land pipeline test.

Downloads, transforms, and exports one month to
``ERA5_LAND_<YYYY>_<MM>_all_attrs.nc``.

Usage
-----
::

    python src/weather/tests/test_era5_one_month.py --year 2018 --month 1
    python src/weather/tests/test_era5_one_month.py \\
        --year 2018 --month 1 --skip-download --resume

Flags
-----
--year YEAR         Year to process (default: ERA5_YEAR / config)
--month MONTH       Month 1-12 (required)
--work-dir DIR      Override ERA5_WORK_DIR
--ncores N          Transform workers (default: config)
--night-mask        Enable Spencer SZA night-masking of GHI (default off)
--skip-download     Re-use an existing monthly GRIB
--resume            Skip if the output .nc already exists
--cleanup           Delete the GRIB after a successful export
"""

from __future__ import annotations

import argparse
import logging

from weather.common.cli_flags import (
    add_cleanup_flag,
    add_resume_flag,
    add_skip_download_flag,
)
from weather.providers.era5_land.pipeline import run_pipeline
from weather.settings import EnvSettings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="ERA5-Land single-month pipeline test",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--year", type=int, default=None, metavar="YEAR")
    p.add_argument(
        "--month", type=int, required=True, metavar="MONTH",
        help="Month to process (1-12)",
    )
    p.add_argument("--work-dir", default=None, metavar="DIR")
    p.add_argument("--ncores", type=int, default=None, metavar="N")
    p.add_argument("--night-mask", action="store_true")
    add_skip_download_flag(p)
    add_resume_flag(p)
    add_cleanup_flag(p, default=EnvSettings.era5_cleanup())
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
        night_mask=args.night_mask,
        skip_download=args.skip_download,
        resume=args.resume,
        cleanup=args.cleanup,
    )


if __name__ == "__main__":
    main()
