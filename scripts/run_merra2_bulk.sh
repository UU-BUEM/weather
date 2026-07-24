#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# MERRA-2 Weather Pipeline — Bulk Multi-Year Run (interactive server / tmux)
# ──────────────────────────────────────────────────────────────────────────────
# Wraps the full MERRA-2 workflow with conda activation, PYTHONPATH, and a
# timestamped log file, for long-running interactive execution inside tmux
# on a plain (non-SLURM) server:
#
#   1. test_merra2_multi_year.py  download (OPeNDAP) + transform + export (per year)
#   2. verify_merra2_months.py    QA report over the whole output folder
#
# Unlike ERA5-Land, there is NO boundary-repair step: MERRA-2's GHI (`SWGDN`)
# is already instantaneous, not accumulated, so there is no de-accumulation /
# first-hour boundary problem to fix (see docs/MERRA2_PIPELINE_GUIDE.md,
# "GHI = SWGDN directly"). Step 2 always runs over the WHOLE output directory
# (not just the years passed to this call) so an incremental/partial bulk run
# still verifies the entire archive, not just the slice touched this time.
#
# Usage (inside a tmux session):
#   bash scripts/run_merra2_bulk.sh --from-year 1980 --to-year 2025 --resume
#   bash scripts/run_merra2_bulk.sh --from-year 2018 --to-year 2018 --ncores 24  # smoke test
#
# All arguments are forwarded verbatim to test_merra2_multi_year.py only (not
# to verify, which always runs whole-archive with defaults). Run
# verify_merra2_months.py directly for more granular control (e.g.
# --lat/--lon/--start/--end point probes).
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# ── Source shared configuration (conda activation, PYTHONPATH) ─────────────
source "${COSMO_SCRIPTS_DIR:-${HOME}/weather/scripts}/common.sh"

_activate_conda_env
_setup_pythonpath

# ── MERRA-2-specific defaults (override via env or .env) ───────────────────
# Note the MERRA_ (not MERRA2_) prefix, matching MERRA_WORK_DIR/MERRA_YEAR/
# MERRA_NCORES elsewhere in this codebase (settings.py, .env.example).
export MERRA_WORK_DIR="${MERRA_WORK_DIR:-${WEATHER_DATA_DIR}/merra2}"
export MERRA_NCORES="${MERRA_NCORES:-$(( $(nproc 2>/dev/null || echo 16) - 8 ))}"
mkdir -p "${MERRA_WORK_DIR}"

LOG_DIR="${MERRA_WORK_DIR}/logs"
mkdir -p "${LOG_DIR}"
LOG_FILE="${LOG_DIR}/merra2_bulk_$(date +%Y%m%d_%H%M%S).log"

echo "============================================================"
echo "MERRA-2 Weather Pipeline — Bulk Run"
echo "  Node:        $(hostname)"
echo "  MERRA_WORK_DIR:  ${MERRA_WORK_DIR}"
echo "  MERRA_NCORES:    ${MERRA_NCORES}"
echo "  Log file:    ${LOG_FILE}"
echo "  Started:     $(date)"
echo "  Args:        $*"
echo "============================================================"

# ── Step 1: Download + transform + export ──────────────────────────────────
# tee to both the terminal (visible via tmux attach) and a log file. -e is
# relaxed just for this call so a failed/partial multi-year run doesn't
# skip step 2 below (verify should still run on whatever DID get produced);
# the pipeline's own exit code is preserved and surfaced at the very end.
echo "STEP 1/2: test_merra2_multi_year.py $*"
set +e
python "${COSMO_SRC_DIR}/weather/tests/test_merra2_multi_year.py" "$@" \
    2>&1 | tee -a "${LOG_FILE}"
pipeline_status="${PIPESTATUS[0]}"
set -e

# ── Step 2: QA verification (read-only) ─────────────────────────────────────
echo ""
echo "STEP 2/2: verify_merra2_months.py (whole output_dir)"
python "${COSMO_SRC_DIR}/weather/tests/verify_merra2_months.py" \
    2>&1 | tee -a "${LOG_FILE}"

echo ""
echo "============================================================"
echo "MERRA-2 bulk run finished at $(date)"
echo "  Download+transform exit code: ${pipeline_status}"
echo "  Log: ${LOG_FILE}"
echo "============================================================"

exit "${pipeline_status}"
