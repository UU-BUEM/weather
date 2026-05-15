# Weather Pipeline — Windows PowerShell Setup
# ─────────────────────────────────────────────────────────────────────────────
# Usage:  .\setup.ps1 [-EnvName weather_env] [-Force]
#
# Installs the package with:  conda develop src
# This makes imports available from src/ for development.
# Use `python -m weather ...` in this mode.
# If conda develop is unavailable, falls back to PYTHONPATH.
# ─────────────────────────────────────────────────────────────────────────────

param(
    [string]$EnvName = "weather_env",
    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Write-Host "================================================================"
Write-Host "  Weather Pipeline — Environment Setup"
Write-Host "  Environment : $EnvName"
Write-Host "  Date        : $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host "================================================================"

# ── Locate conda ──────────────────────────────────────────────────────────
$condaCmd = Get-Command conda -ErrorAction SilentlyContinue
if (-not $condaCmd) {
    Write-Error @"
conda not found in PATH.
Install Miniconda from https://docs.conda.io/en/latest/miniconda.html
then restart this terminal and rerun setup.ps1.
"@
    exit 1
}
Write-Host "Using conda: $(conda --version)"

# ── Locate weather_env.yml ────────────────────────────────────────────────
$repoRoot  = $PSScriptRoot
$envYml    = Join-Path $repoRoot "infrastructure\env\weather_env.yml"

if (-not (Test-Path $envYml)) {
    Write-Error "weather_env.yml not found at: $envYml"
    exit 1
}

# ── Create or update conda environment ────────────────────────────────────
$envExists = conda env list | Select-String -SimpleMatch $EnvName
if ($envExists -and -not $Force) {
    Write-Host ""
    Write-Host "Environment '$EnvName' already exists — updating..."
    conda env update -n $EnvName -f $envYml --prune
} else {
    if ($Force -and $envExists) {
        Write-Host "Removing existing environment '$EnvName' (--Force)..."
        conda env remove -n $EnvName -y
    }
    Write-Host ""
    Write-Host "Creating conda environment '$EnvName'..."
    conda env create -f $envYml
}

# ── Install package (conda develop src — like BuEM) ───────────────────────
Write-Host ""
Write-Host "Installing package with conda develop..."
$srcPath = Join-Path $repoRoot "src"
$dataRoot = Join-Path $repoRoot "data"
$cosmoWorkDir = Join-Path $dataRoot "cosmo_rea6"
$condaBldPath = Join-Path $repoRoot ".conda-bld"

New-Item -ItemType Directory -Force -Path $dataRoot, $cosmoWorkDir, $condaBldPath | Out-Null

Write-Host "Configuring environment paths..."
conda env config vars set -n $EnvName WEATHER_DATA_DIR=$dataRoot COSMO_WORK_DIR=$cosmoWorkDir CONDA_BLD_PATH=$condaBldPath

conda develop $srcPath
if ($LASTEXITCODE -ne 0) {
    Write-Warning "conda develop failed (conda-build missing?); falling back to PYTHONPATH."
    conda env config vars set -n $EnvName PYTHONPATH=$srcPath
    Write-Host "  PYTHONPATH set. Use: python -m weather info"
} else {
    Write-Host "  Source path registered for imports. Use: python -m weather info"
}

# ── Done ──────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "================================================================"
Write-Host "  Setup complete."
Write-Host ""
Write-Host "  Reactivate: conda deactivate; conda activate $EnvName"
Write-Host "  Verify:     python -m weather info"
Write-Host "================================================================"
