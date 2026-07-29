#!/usr/bin/env python3
"""Full-year COSMO-REA6 pipeline: all 12 months (or a subset), every
attribute registered in ``downloaded_attributes.ATTRIBUTES``.

All the real pipeline logic (bulk download/decompress, verification,
per-month transform+export, resume, cleanup, DNI diagnostics) lives in
:mod:`weather.providers.cosmo_rea6.pipeline` -- this script is just a
CLI shim around :func:`~weather.providers.cosmo_rea6.pipeline.run_pipeline`,
matching :mod:`weather.tests.test_era5_one_year` /
:mod:`weather.tests.test_merra2_one_year`.

Output files
------------
One NetCDF per month: ``COSMO_REA6_<YYYY>_<MM>_all_attrs.nc``
All files written to ``<COSMO_WORK_DIR>/output/`` (or ``--work-dir``).

Note
----
Annual merge is a separate post-processing step, not part of this
script.  Use ``weather.common.merge.NetCDFMerger`` or the merge CLI::

    python -m weather.common.merge \\
        --input  <out_dir>/COSMO_REA6_<YYYY>_??_all_attrs.nc \\
        --output <out_dir>/COSMO_REA6_<YYYY>_annual_all_attrs.nc

Usage
-----
Basic (year 2018, 80 cores)::

    python src/weather/tests/test_cosmo_one_year.py --year 2018 --ncores 80

Resume an interrupted run (skips months whose output NC exists)::

    python src/weather/tests/test_cosmo_one_year.py --year 2018 --ncores 80 \\
        --resume

Process only specific months (e.g. re-run a failed month)::

    python src/weather/tests/test_cosmo_one_year.py --year 2018 --months 7 8

Flags
-----
--year YEAR             Four-digit year (default: config)
--months M [M ...]      Subset of months to process (default: all 12)
--ncores N              Total worker count (default: COSMO_NCORES env var or 4)
--work-dir DIR          Override COSMO_WORK_DIR for this run
--skip-download         Assume .grb.bz2 files are already present
--skip-decompress       Assume .grb files are already present
--skip-dni              Skip experimental per-cell DNI computation
--resume                Skip months whose output NetCDF already exists
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
        description=(
            "Full-year COSMO-REA6 pipeline — all registered attributes "
            "(see downloaded_attributes.py), 12 months processed sequentially"
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--year", type=int, default=None, metavar="YEAR")
    p.add_argument(
        "--months", type=int, nargs="+", default=None, metavar="M",
        help="Subset of months to process (default: all 12)",
    )
    p.add_argument("--ncores", type=int, default=None, metavar="N")
    p.add_argument("--work-dir", default=None, metavar="DIR")
    add_skip_download_flag(p)
    add_skip_decompress_flag(p)
    p.add_argument(
        "--skip-dni", action="store_true",
        help="Skip experimental per-cell DNI computation",
    )
    add_resume_flag(p)
    add_cleanup_flag(p, default=EnvSettings.cosmo_cleanup())
    args = p.parse_args()
    if args.months:
        bad = [m for m in args.months if not 1 <= m <= 12]
        if bad:
            p.error(f"--months out of range (1-12): {bad}")
    return args


def main() -> None:
    args = _parse_args()

    run_pipeline(
        year=args.year,
        months=args.months,
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
