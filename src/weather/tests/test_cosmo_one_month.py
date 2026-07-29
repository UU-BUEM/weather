#!/usr/bin/env python3
"""Single-month COSMO-REA6 pipeline test.

Downloads, transforms, and exports one month to
``COSMO_REA6_<YYYY>_<MM>_all_attrs.nc``, exercising every attribute
registered in ``downloaded_attributes.ATTRIBUTES``.

Usage
-----
::

    python src/weather/tests/test_cosmo_one_month.py --year 2018 --month 1
    python src/weather/tests/test_cosmo_one_month.py \\
        --year 2018 --month 1 --skip-download --skip-decompress

Flags
-----
--year YEAR             Four-digit year (default: config)
--month M               Month 1-12 (required)
--work-dir DIR          Override COSMO_WORK_DIR
--ncores N              Total worker count (default: COSMO_NCORES env var or 4)
--skip-download         Re-use existing .grb.bz2 files
--skip-decompress       Re-use existing .grb files
--skip-dni              Skip experimental per-cell DNI computation
--resume                Skip if the output .nc already exists
--cleanup               Delete intermediates after a successful export
"""

from __future__ import annotations

import argparse
import logging

from weather.common.cli_flags import (
    add_cleanup_flag,
    add_resume_flag,
    add_skip_decompress_flag,
    add_skip_download_flag,
)
from weather.providers.cosmo_rea6.pipeline import run_pipeline
from weather.settings import EnvSettings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="COSMO-REA6 single-month pipeline test",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--year", type=int, default=None, metavar="YEAR")
    p.add_argument(
        "--month", type=int, required=True, metavar="MONTH",
        help="Month to process (1-12)",
    )
    p.add_argument("--work-dir", default=None, metavar="DIR")
    p.add_argument("--ncores", type=int, default=None, metavar="N")
    add_skip_download_flag(p)
    add_skip_decompress_flag(p)
    p.add_argument(
        "--skip-dni", action="store_true",
        help="Skip experimental per-cell DNI computation",
    )
    add_resume_flag(p)
    add_cleanup_flag(p, default=EnvSettings.cosmo_cleanup())
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
        skip_decompress=args.skip_decompress,
        skip_dni=args.skip_dni,
        resume=args.resume,
        cleanup=args.cleanup,
    )


if __name__ == "__main__":
    main()
