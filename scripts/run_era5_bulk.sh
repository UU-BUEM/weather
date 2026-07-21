#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# ERA5-Land Weather Pipeline — Bulk Multi-Year Run (interactive server / tmux)
# ──────────────────────────────────────────────────────────────────────────────
# Wraps the full ERA5-Land workflow with conda activation, PYTHONPATH, and a
# timestamped log file, for long-running interactive execution inside tmux
# on a plain (non-SLURM) server:
#
#   1. test_era5_multi_year.py    download + transform + export (per year)
#   2. repair_month_boundaries.py mandatory: fix first-hour GHI/sf boundary
#   3. verify_months.py           QA report over the whole output folder
#
# Steps 2-3 always run over the WHOLE output directory (not just the years
# passed to this call) — repair_month_boundaries.py is fully idempotent and
# disk-based, so re-running it on already-repaired months is a cheap no-op,
# and this way an incremental/partial bulk run always keeps the entire
# archive self-consistent, not just the slice touched this time.
#
# Usage (inside a tmux session):
#   bash scripts/run_era5_bulk.sh --from-year 1950 --to-year 2025 --resume
#   bash scripts/run_era5_bulk.sh --from-year 2018 --to-year 2018 --ncores 24  # smoke test
#
# All arguments are forwarded verbatim to test_era5_multi_year.py only (not
# to repair/verify, which always run whole-archive with defaults). Run
# repair_month_boundaries.py / verify_months.py directly for more granular
# control (e.g. --months, --dry-run, --lat/--lon point probes).
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# ── Source shared configuration (conda activation, PYTHONPATH) ─────────────
source "${COSMO_SCRIPTS_DIR:-${HOME}/weather/scripts}/common.sh"

_activate_conda_env
_setup_pythonpath

# ── ERA5-specific defaults (override via env or .env) ──────────────────────
export ERA5_WORK_DIR="${ERA5_WORK_DIR:-${WEATHER_DATA_DIR}/era5_land}"
export ERA5_NCORES="${ERA5_NCORES:-$(( $(nproc 2>/dev/null || echo 16) - 8 ))}"
mkdir -p "${ERA5_WORK_DIR}"

LOG_DIR="${ERA5_WORK_DIR}/logs"
mkdir -p "${LOG_DIR}"
LOG_FILE="${LOG_DIR}/era5_bulk_$(date +%Y%m%d_%H%M%S).log"

echo "============================================================"
echo "ERA5-Land Weather Pipeline — Bulk Run"
echo "  Node:       $(hostname)"
echo "  ERA5_WORK_DIR:  ${ERA5_WORK_DIR}"
echo "  ERA5_NCORES:    ${ERA5_NCORES}"
echo "  Log file:   ${LOG_FILE}"
echo "  Started:    $(date)"
echo "  Args:       $*"
echo "============================================================"

# ── Step 1: Download + transform + export ──────────────────────────────────
# tee to both the terminal (visible via tmux attach) and a log file. -e is
# relaxed just for this call so a failed/partial multi-year run doesn't
# skip steps 2-3 below (repair/verify should still run on whatever DID
# get produced); the pipeline's own exit code is preserved and surfaced
# at the very end.
echo "STEP 1/3: test_era5_multi_year.py $*"
set +e
python "${COSMO_SRC_DIR}/weather/tests/test_era5_multi_year.py" "$@" \
    2>&1 | tee -a "${LOG_FILE}"
pipeline_status="${PIPESTATUS[0]}"
set -e

# ── Step 2: Boundary repair (mandatory, whole archive, idempotent) ─────────
echo ""
echo "STEP 2/3: repair_month_boundaries.py (whole output_dir)"
python "${COSMO_SRC_DIR}/weather/tests/repair_month_boundaries.py" \
    2>&1 | tee -a "${LOG_FILE}"

# ── Step 3: QA verification (read-only) ─────────────────────────────────────
echo ""
echo "STEP 3/3: verify_months.py (whole output_dir)"
python "${COSMO_SRC_DIR}/weather/tests/verify_months.py" \
    2>&1 | tee -a "${LOG_FILE}"

echo ""
echo "============================================================"
echo "ERA5-Land bulk run finished at $(date)"
echo "  Download+transform exit code: ${pipeline_status}"
echo "  Log: ${LOG_FILE}"
echo "============================================================"

exit "${pipeline_status}"
