#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# Weather Pipeline — Linux / macOS / HPC Setup
# ──────────────────────────────────────────────────────────────────────────────
# Creates (or updates) the conda environment and installs the package in
# editable mode.  Works on local Linux/macOS and HPC systems (e.g. Snellius)
# that load conda via an Lmod module system.
#
# Usage:
#   bash setup.sh                   # create/update weather_env
#   bash setup.sh my_custom_env     # use a custom environment name
#   bash setup.sh weather_env --force  # remove and recreate from scratch
#
# Prerequisites:
#   - Miniconda / Miniforge in PATH, OR an Lmod system with a conda module.
#   - On HPC: set CONDA_MODULE (and optionally TOOLCHAIN_MODULE) in .env,
#     or export them before running this script.
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

ENV_NAME="${1:-weather_env}"
FORCE="${2:-}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_YML="${SCRIPT_DIR}/infrastructure/env/weather_env.yml"

echo "================================================================"
echo "  Weather Pipeline — Environment Setup"
echo "  Environment : ${ENV_NAME}"
echo "  Date        : $(date '+%Y-%m-%d %H:%M:%S')"
echo "================================================================"

# ── Source .env if present (for CONDA_MODULE, TOOLCHAIN_MODULE, etc.) ────────
if [ -f "${SCRIPT_DIR}/.env" ]; then
    # shellcheck disable=SC1091
    set -a; source "${SCRIPT_DIR}/.env"; set +a
fi

# ── Locate conda (PATH first, then Lmod fallback for HPC) ────────────────────
if ! command -v conda &>/dev/null; then
    TOOLCHAIN="${TOOLCHAIN_MODULE:-}"
    MODULE="${CONDA_MODULE:-}"
    if command -v module &>/dev/null && [ -n "${MODULE}" ]; then
        echo "conda not in PATH — loading module: ${TOOLCHAIN:+$TOOLCHAIN }${MODULE}"
        [ -n "${TOOLCHAIN}" ] && module load "${TOOLCHAIN}" 2>/dev/null || true
        module load "${MODULE}" 2>/dev/null || true
    fi
    if ! command -v conda &>/dev/null; then
        echo "ERROR: conda not found."
        echo "  Install Miniconda: https://docs.conda.io/en/latest/miniconda.html"
        echo "  Or set CONDA_MODULE in .env for HPC Lmod systems."
        exit 1
    fi
fi
echo "Using conda: $(conda --version)"

# ── Resolve environment install location ────────────────────────────────────
# Priority: 1) CONDA_ENV_PREFIX env var  2) ~/.conda/envs if writable
#            3) first writable dir from conda's configured envs_dirs
_resolve_env_prefix() {
    local name="$1"
    # Explicit user override (set CONDA_ENV_PREFIX in .env or shell before running)
    if [ -n "${CONDA_ENV_PREFIX:-}" ]; then
        echo "${CONDA_ENV_PREFIX}/${name}"; return 0
    fi
    # Prefer ~/.conda/envs — user-owned, always takes priority if writable
    if mkdir -p "${HOME}/.conda/envs" 2>/dev/null && [ -w "${HOME}/.conda/envs" ]; then
        echo "${HOME}/.conda/envs/${name}"; return 0
    fi
    # Fall back to first writable entry from conda's configured envs_dirs
    local prefix
    prefix="$(conda info --json 2>/dev/null | python3 -c "
import sys, json, os
name = '${name}'
data = json.load(sys.stdin)
for d in data.get('envs_dirs', []):
    writable = (os.path.isdir(d) and os.access(d, os.W_OK)) or \\\
               (os.path.isdir(os.path.dirname(d)) and os.access(os.path.dirname(d), os.W_OK))
    if writable:
        print(os.path.join(d, name)); break
" 2>/dev/null)"
    [ -n "${prefix}" ] && echo "${prefix}" || echo "${HOME}/.conda/envs/${name}"
}
ENV_PREFIX="$(_resolve_env_prefix "${ENV_NAME}")"
echo "  Env location: ${ENV_PREFIX}"

# ── Initialise conda shell hook ───────────────────────────────────────────────
# Disable nounset temporarily — system Anaconda activate.d scripts may
# reference unbound variables (e.g. QT_XCB_GL_INTEGRATION).
set +u
eval "$(conda shell.bash hook)"
set -u

# ── Verify environment spec exists ────────────────────────────────────────────
if [ ! -f "${ENV_YML}" ]; then
    echo "ERROR: weather_env.yml not found at: ${ENV_YML}"
    exit 1
fi

# ── Create or update conda environment ───────────────────────────────────────
if [ -d "${ENV_PREFIX}" ]; then
    if [ "${FORCE}" = "--force" ]; then
        echo "Removing existing environment '${ENV_NAME}' (--force)..."
        conda env remove -p "${ENV_PREFIX}" -y
        echo "Creating conda environment '${ENV_NAME}'..."
        conda env create -f "${ENV_YML}" --prefix "${ENV_PREFIX}"
    else
        echo "Environment '${ENV_NAME}' exists — updating..."
        conda env update -f "${ENV_YML}" --prefix "${ENV_PREFIX}" --prune
    fi
else
    echo "Creating conda environment '${ENV_NAME}'..."
    conda env create -f "${ENV_YML}" --prefix "${ENV_PREFIX}"
fi

# ── Create data directories ───────────────────────────────────────────────────
DATA_ROOT="${WEATHER_DATA_DIR:-${SCRIPT_DIR}/data}"
COSMO_WORK_DIR="${COSMO_WORK_DIR:-${DATA_ROOT}/cosmo_rea6}"
mkdir -p "${DATA_ROOT}" "${COSMO_WORK_DIR}"
echo "Data root    : ${DATA_ROOT}"
echo "COSMO work   : ${COSMO_WORK_DIR}"

# ── Persist env vars inside the conda environment ────────────────────────────
conda env config vars set \
    -p "${ENV_PREFIX}" \
    WEATHER_DATA_DIR="${DATA_ROOT}" \
    COSMO_WORK_DIR="${COSMO_WORK_DIR}"

# ── Install package in editable mode ─────────────────────────────────────────
echo ""
echo "Installing weather package in editable mode..."
conda run -p "${ENV_PREFIX}" pip install -e . --no-deps
echo "  Done."

# ── Verify ───────────────────────────────────────────────────────────────────
echo ""
echo "Verifying installation..."
if conda run -p "${ENV_PREFIX}" python -m weather info; then
    echo "  Verification passed."
else
    echo "WARNING: verification failed — check output above."
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "================================================================"
echo "  Setup complete."
echo ""
echo "  Activate : conda activate ${ENV_NAME}"
echo "             (or: conda activate ${ENV_PREFIX})"
echo ""
echo "  Note: 'bash setup.sh' cannot activate the env for you"
echo "        (subshell limitation). Run the activate command above."
echo ""
echo "  Cores    : default is 4. Set COSMO_NCORES=N in .env"
echo "             to use more (SLURM: SLURM_CPUS_PER_TASK auto-used)."
echo "  Verify   : python -m weather info"
echo "================================================================"
