#!/usr/bin/env python3
"""Generate P10/P50/P90 representative-year weather files for COSMO-REA6.

Reads the monthly NetCDF files produced by :mod:`weather.tests.test_one_year`
(12 files per year, 1995–2018) and derives three representative-year weather
files using a per-cell percentile methodology.  No annual merge step is
required; the 12 monthly files are opened together via ``open_mfdataset``.

Methodology
-----------
For each spatial cell in the 824 × 848 COSMO-REA6 grid:

1. Compute the **annual cumulative GHI** (W·h/m²) for every year in the
   analysis period.
2. Find the percentile value (P10 / P50 / P90) of that cell's 24-year GHI
   distribution.
3. Select the **actual calendar year** whose observed GHI is closest to that
   percentile value.
4. Copy the full hourly time series for all variables from the selected year
   into the output file for that cell.

Different cells in the same P50 file can come from different years; the
``source_year(rlat, rlon)`` variable in each output file records the origin.

::

                          ┌──────────────────────────────────────┐
                          │  Monthly NC files (12 per year)       │
                          │  COSMO_REA6_1995_01_all_attrs.nc      │
                          │  …  COSMO_REA6_1995_12_all_attrs.nc   │
                          │  …                                    │
                          │  COSMO_REA6_2018_01_all_attrs.nc      │
                          │  …  COSMO_REA6_2018_12_all_attrs.nc   │
                          └─────────────┬────────────────────────┘
                                        │  open_mfdataset (per year)
                                        │  annual_metric()
                                        ▼
                          ┌─────────────────────────────┐
                          │ metric_stack (24, 824, 848)  │
                          │  annual GHI sum per cell     │
                          └─────────────┬───────────────┘
                                        │ select_representative_years()
                                        ▼
                          ┌─────────────────────────────────────────┐
                          │  year_map(rlat, rlon) per percentile    │
                          │  P10: cell(i,j) → 2010                  │
                          │  P50: cell(i,j) → 2007                  │
                          │  P90: cell(i,j) → 2015                  │
                          └─────────────┬───────────────────────────┘
                                        │  _mosaic_years()
                                        ▼
                          ┌─────────────────────────────────────────┐
                          │  COSMO_REA6_p10_representative.nc        │
                          │  COSMO_REA6_p50_representative.nc        │
                          │  COSMO_REA6_p90_representative.nc        │
                          │  shape: (8760, 824, 848) per variable    │
                          └─────────────────────────────────────────┘

Usage
-----
Basic (1995–2018, default P10/P50/P90 on GHI)::

    python src/weather/tests/test_percentile.py \\
        --from-year 1995 --to-year 2018 --ncores 94

Custom percentiles and output directory::

    python src/weather/tests/test_percentile.py \\
        --from-year 1995 --to-year 2018 \\
        --percentiles 5,50,95 \\
        --output-dir /data/soma/percentile \\
        --ncores 94

Flags
-----
--from-year YEAR          First year of analysis period (required)
--to-year   YEAR          Last year inclusive (required)
--percentiles P[,P,...]   Comma-separated integer percentile levels
                           (default: 10,50,90)
--output-dir DIR          Override output directory
                           (default: <COSMO_OUTPUT_DIR>/percentile)
--ncores N                Dask thread count (default: COSMO_NCORES or 4)
--work-dir DIR            Override COSMO_WORK_DIR
--dry-run                 Print plan without writing any files
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------
_here = Path(__file__).resolve().parent   # src/weather/tests/
_src = _here.parent.parent               # src/
if (_src / "weather").is_dir() and str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

os.environ.setdefault("HDF5_USE_FILE_LOCKING", "FALSE")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("cr6_pct")


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Generate P10/P50/P90 representative-year weather files "
            "for COSMO-REA6 (1995–2018 or any sub-range)"
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
        "--percentiles", default="10,50,90", metavar="P[,P,...]",
        help="Integer percentile levels, comma-separated",
    )
    p.add_argument(
        "--output-dir", default=None, metavar="DIR",
        help=(
            "Output directory (default: <COSMO_OUTPUT_DIR>/percentile)"
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

    # Parse percentile list
    try:
        args.percentile_list = [
            int(x.strip()) / 100.0
            for x in args.percentiles.split(",")
            if x.strip()
        ]
    except ValueError:
        p.error(
            "--percentiles must be integers separated by commas, "
            "e.g. 10,50,90"
        )

    invalid = [p for p in args.percentile_list if not 0 < p < 1]
    if invalid:
        p.error(
            f"Percentile values must be between 1 and 99: "
            f"{[int(v*100) for v in invalid]}"
        )

    return args


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """Entry point for the COSMO-REA6 percentile file generator."""
    args = _parse_args()

    if args.work_dir:
        os.environ["COSMO_WORK_DIR"] = args.work_dir
    if args.ncores is not None:
        os.environ["COSMO_NCORES"] = str(args.ncores)

    from weather.providers.cosmo_rea6.config import get_config
    from weather.providers.cosmo_rea6.percentile import CosmoPercentileAnalyzer

    cfg = get_config()
    ncores: int = cfg["ncores"]
    years = list(range(args.from_year, args.to_year + 1))
    n_years = len(years)
    pcts = args.percentile_list
    pct_labels = [f"P{int(round(p*100)):02d}" for p in pcts]

    out_dir = (
        Path(args.output_dir) if args.output_dir
        else cfg["output_dir"] / "percentile"
    )

    logger.info("=" * 68)
    logger.info("COSMO-REA6 Percentile Weather File Generator")
    logger.info(
        "  Analysis period : %d – %d  (%d year(s))",
        years[0], years[-1], n_years,
    )
    logger.info("  Percentiles     : %s", ", ".join(pct_labels))
    logger.info("  Ranking metric  : annual cumulative GHI (W·h/m²)")
    logger.info("  Spatial grid    : 824 × 848 COSMO-REA6 rotated-pole")
    logger.info("  Output dir      : %s", out_dir)
    logger.info("  Cores           : %d", ncores)
    logger.info("=" * 68)

    # ── Dry-run mode ──────────────────────────────────────────────────
    if args.dry_run:
        logger.info("DRY RUN — no files written.")
        for p in pcts:
            fname = f"COSMO_REA6_p{int(round(p*100)):02d}_representative.nc"
            logger.info("  Would create: %s", out_dir / fname)
        return

    # ── Check that all monthly NC files exist ─────────────────────────
    missing = []
    for year in years:
        for month in range(1, 13):
            fname = f"COSMO_REA6_{year}_{month:02d}_all_attrs.nc"
            if not (cfg["output_dir"] / fname).exists():
                missing.append(f"{year}-{month:02d}")
    if missing:
        logger.error(
            "Missing %d monthly NC file(s). "
            "Run test_one_year.py for each affected year.",
            len(missing),
        )
        for m in missing[:10]:
            logger.error("  %s", m)
        if len(missing) > 10:
            logger.error("  … and %d more.", len(missing) - 10)
        sys.exit(1)

    # ── Run analyser ──────────────────────────────────────────────────
    t_total = time.perf_counter()

    analyzer = CosmoPercentileAnalyzer(output_dir=out_dir, ncores=ncores)
    out_paths = analyzer.run(years=years, percentiles=pcts)

    elapsed = time.perf_counter() - t_total

    logger.info("")
    logger.info("=" * 68)
    logger.info("COSMO-REA6 Percentile Files — COMPLETE")
    for p, path in sorted(out_paths.items()):
        mb = path.stat().st_size / (1024 * 1024)
        logger.info(
            "  P%02d  %s  (%.0f MB)",
            int(round(p * 100)), path.name, mb,
        )
    logger.info("  Wall time : %.1f s  (%.1f min)", elapsed, elapsed / 60)
    logger.info("=" * 68)


if __name__ == "__main__":
    main()
