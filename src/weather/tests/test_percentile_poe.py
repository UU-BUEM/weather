#!/usr/bin/env python3
"""Generate PoE P10/P50/P90 representative monthly weather files.

Reads the monthly NetCDF files produced by test_one_year.py (12 files per
year) and derives representative monthly weather files using **Probability
of Exceedance (PoE)** based on non-parametric historical ranking (eCDF).

PoE convention (IEC 61724-1 / solar bankability standard)
---------------------------------------------------------
- **P90** — 90 % chance GHI will be **exceeded** → low resource, downside
- **P50** — 50 % chance GHI will be **exceeded** → median, typical year
- **P10** — 10 % chance GHI will be **exceeded** → high resource, upside

No annual merge is required. Each calendar month is processed
independently: for each spatial cell, the year whose monthly GHI is
closest to the PoE target (via eCDF linear interpolation) is selected.
Different cells, and different months, may be drawn from different years.

Algorithm summary
-----------------
For each month m ∈ {01 … 12}:

  1. Load monthly GHI total from each analysis year → metric_stack
     shape (n_years, 824, 848)
  2. Compute ascending-percentile target per cell via numpy eCDF:
       P90 PoE → ascending 10th percentile  (low GHI)
       P50 PoE → ascending 50th percentile  (median)
       P10 PoE → ascending 90th percentile  (high GHI)
  3. Select representative year per cell: argmin |metric - target|
  4. Mosaic hourly data from selected years into output file

Output (36 files, default P10/P50/P90 × 12 months)::

    <output_dir>/percentile_poe/
        COSMO_REA6_poe10_01_representative.nc
        COSMO_REA6_poe10_02_representative.nc
        ...
        COSMO_REA6_poe90_12_representative.nc

Differences from test_percentile.py (annual approach)
------------------------------------------------------
- PoE convention is correct (P90 = low GHI, not high GHI)
- Monthly granularity (not annual) — avoids expensive yearly merge
- Each month's representative year is independent

Usage
-----
Basic (1995–2018, P10/P50/P90, all 12 months)::

    python src/weather/tests/test_percentile_poe.py \\
        --from-year 1995 --to-year 2018 --ncores 94

Subset of months only::

    python src/weather/tests/test_percentile_poe.py \\
        --from-year 1995 --to-year 2018 --months 1,7 --ncores 94

Custom PoE levels::

    python src/weather/tests/test_percentile_poe.py \\
        --from-year 1995 --to-year 2018 --poe-levels 5,50,95 --ncores 94
"""

from __future__ import annotations

import argparse
import logging
import os
import time
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Generate PoE P10/P50/P90 representative monthly weather "
            "files for COSMO-REA6 using empirical CDF (non-parametric)."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--from-year", type=int, required=True, metavar="YEAR",
        help="First year of analysis period (e.g. 1995)",
    )
    p.add_argument(
        "--to-year", type=int, required=True, metavar="YEAR",
        help="Last year inclusive (e.g. 2018)",
    )
    p.add_argument(
        "--poe-levels", default="10,50,90", metavar="P[,P,...]",
        help="Integer PoE levels (% exceedance), comma-separated",
    )
    p.add_argument(
        "--months", default=None, metavar="M[,M,...]",
        help=(
            "Calendar months 1-12, comma-separated.  "
            "Defaults to all 12."
        ),
    )
    p.add_argument(
        "--independent-months", action="store_true",
        help=(
            "Select representative years independently per month "
            "(disables same-year lock across months)."
        ),
    )
    p.add_argument(
        "--output-dir", default=None, metavar="DIR",
        help=(
            "Output directory "
            "(default: <COSMO_OUTPUT_DIR>/percentile_poe)"
        ),
    )
    p.add_argument(
        "--ncores", type=int, default=None, metavar="N",
        help="Dask thread count (default: COSMO_NCORES env var or 4)",
    )
    p.add_argument(
        "--work-dir", default=None, metavar="DIR",
        help="Override COSMO_WORK_DIR",
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Print the plan but do not write any files",
    )
    args = p.parse_args()

    if args.from_year > args.to_year:
        p.error("--from-year must be ≤ --to-year")

    # Parse PoE levels
    try:
        args.poe_level_list = [
            int(x.strip()) / 100.0
            for x in args.poe_levels.split(",")
            if x.strip()
        ]
    except ValueError:
        p.error(
            "--poe-levels must be integers 1–99 comma-separated, "
            "e.g. 10,50,90"
        )
    invalid = [v for v in args.poe_level_list if not 0 < v < 1]
    if invalid:
        p.error(
            f"PoE values must be between 1 and 99: "
            f"{[int(v * 100) for v in invalid]}"
        )

    # Parse months
    if args.months is not None:
        try:
            args.month_list = [
                int(x.strip())
                for x in args.months.split(",")
                if x.strip()
            ]
        except ValueError:
            p.error("--months must be integers 1–12, e.g. 1,7,12")
        invalid_m = [m for m in args.month_list if not 1 <= m <= 12]
        if invalid_m:
            p.error(
                f"Month values out of range 1–12: {invalid_m}"
            )
    else:
        args.month_list = list(range(1, 13))

    return args


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """Entry point for the COSMO-REA6 PoE monthly file generator."""
    args = _parse_args()

    if args.work_dir:
        os.environ["COSMO_WORK_DIR"] = args.work_dir
    if args.ncores is not None:
        os.environ["COSMO_NCORES"] = str(args.ncores)

    from weather.providers.cosmo_rea6.config import get_config
    from weather.providers.cosmo_rea6.percentile_poe import (
        CosmoPoEAnalyzer,
    )

    cfg = get_config()
    ncores: int = cfg["ncores"]
    years = list(range(args.from_year, args.to_year + 1))
    n_years = len(years)
    poes = args.poe_level_list
    poe_labels = [f"P{int(round(p * 100)):02d}" for p in poes]
    months = args.month_list
    month_labels = [f"{m:02d}" for m in months]

    out_dir = (
        Path(args.output_dir) if args.output_dir
        else cfg["output_dir"] / "percentile_poe"
    )

    logger.info("=" * 68)
    logger.info("COSMO-REA6 PoE Monthly Representative File Generator")
    logger.info(
        "  Analysis period : %d – %d  (%d year(s))",
        years[0], years[-1], n_years,
    )
    logger.info(
        "  PoE levels      : %s", ", ".join(poe_labels)
    )
    logger.info(
        "  Months          : %s", ", ".join(month_labels)
    )
    logger.info("  Ranking metric  : monthly cumulative GHI (W·h/m²)")
    logger.info("  Selection       : eCDF argmin-distance per cell")
    logger.info(
        "  Mode            : %s",
        "independent-months"
        if args.independent_months
        else "locked-year across months",
    )
    logger.info("  Spatial grid    : 824 × 848 COSMO-REA6 rotated-pole")
    logger.info("  Output dir      : %s", out_dir)
    logger.info("  Cores           : %d", ncores)
    logger.info("=" * 68)

    # ── Dry-run mode ──────────────────────────────────────────────────
    if args.dry_run:
        logger.info("DRY RUN — no files written.")
        for p in poes:
            poe_int = int(round(p * 100))
            for m in months:
                fname = (
                    f"COSMO_REA6_poe{poe_int:02d}_{m:02d}"
                    "_representative.nc"
                )
                logger.info("  Would create: %s", out_dir / fname)
        logger.info(
            "Total: %d file(s)", len(poes) * len(months)
        )
        return

    # ── Run analyser ──────────────────────────────────────────────────
    t_total = time.perf_counter()

    analyzer = CosmoPoEAnalyzer(
        output_dir=out_dir, ncores=ncores
    )
    out_paths = analyzer.run(
        years=years,
        poe_levels=poes,
        months=months,
        lock_year_across_months=not args.independent_months,
    )

    elapsed = time.perf_counter() - t_total

    logger.info("")
    logger.info("=" * 68)
    logger.info("COSMO-REA6 PoE Monthly Files — COMPLETE")
    for (poe, month), path in sorted(out_paths.items()):
        mb = path.stat().st_size / (1024 * 1024)
        poe_int = int(round(poe * 100))
        logger.info(
            "  PoE%02d-%02d  %s  (%.0f MB)",
            poe_int, month, path.name, mb,
        )
    logger.info(
        "  Total files : %d", len(out_paths)
    )
    logger.info(
        "  Wall time   : %.1f s  (%.1f min)",
        elapsed, elapsed / 60,
    )
    logger.info("=" * 68)


if __name__ == "__main__":
    main()
