# Weather Pipeline — Windows PowerShell Setup
# ─────────────────────────────────────────────────────────────────────────────
# Usage:  .\setup.ps1 [-EnvName weather_env] [-Force]
#
# Installs the package in editable mode with:  pip install -e .
# Use `python -m weather ...` after activation.
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

# ── Install package (editable mode via pip) ───────────────────────────────
Write-Host ""
Write-Host "Installing weather package in editable mode..."
$dataRoot = Join-Path $repoRoot "data"
$cosmoWorkDir = Join-Path $dataRoot "cosmo_rea6"

New-Item -ItemType Directory -Force -Path $dataRoot, $cosmoWorkDir | Out-Null

Write-Host "Configuring environment paths..."
conda env config vars set -n $EnvName WEATHER_DATA_DIR=$dataRoot COSMO_WORK_DIR=$cosmoWorkDir

conda run -n $EnvName pip install -e .
if ($LASTEXITCODE -ne 0) {
    Write-Error "pip install -e . failed — check output above."
    exit 1
}
Write-Host "  Package installed. Use: python -m weather info"

# ── Verify installation ───────────────────────────────────────────────────
Write-Host ""
Write-Host "Verifying installation..."
conda run -n $EnvName python -m weather info
if ($LASTEXITCODE -ne 0) {
    Write-Warning "Verification failed — check output above."
}

# ── Done ──────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "================================================================"
Write-Host "  Setup complete."
Write-Host ""
Write-Host "  Reactivate: conda deactivate; conda activate $EnvName"
Write-Host "  Verify:     python -m weather info"
Write-Host "================================================================"
