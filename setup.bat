@echo off
REM Weather Pipeline — Windows Batch Setup
REM Run from the repository root:
REM   setup.bat [env_name]
REM Default env name: weather_env
REM
REM Installs the package in editable mode with:  pip install -e .
REM Use: python -m weather info

setlocal enabledelayedexpansion

set "ENV_NAME=%~1"
if "%ENV_NAME%"=="" set "ENV_NAME=weather_env"

echo ================================================================
echo   Weather Pipeline -- Environment Setup
echo   Environment : %ENV_NAME%
echo ================================================================

REM ── Check conda ──────────────────────────────────────────────────────────
where conda >nul 2>&1
if errorlevel 1 (
    echo ERROR: conda not found in PATH.
    echo Install Miniconda from https://docs.conda.io/en/latest/miniconda.html
    exit /b 1
)

REM ── Locate weather_env.yml ────────────────────────────────────────────────
set "REPO_ROOT=%~dp0"
set "ENV_YML=%REPO_ROOT%infrastructure\env\weather_env.yml"

if not exist "%ENV_YML%" (
    echo ERROR: weather_env.yml not found at %ENV_YML%
    exit /b 1
)

REM ── Create or update environment ──────────────────────────────────────────
conda env list | findstr /C:"%ENV_NAME%" >nul 2>&1
if not errorlevel 1 (
    echo Environment '%ENV_NAME%' exists -- updating...
    conda env update -n "%ENV_NAME%" -f "%ENV_YML%" --prune
) else (
    echo Creating conda environment '%ENV_NAME%'...
    conda env create -f "%ENV_YML%"
)
if errorlevel 1 (
    echo ERROR: conda env create/update failed.
    exit /b 1
)

REM ── Install package (editable mode via pip) ──────────────────────────────
echo.
echo Installing weather package in editable mode...
set "DATA_ROOT=%REPO_ROOT%data"
set "COSMO_WORK_DIR=%DATA_ROOT%\cosmo_rea6"

if not exist "%DATA_ROOT%" mkdir "%DATA_ROOT%"
if not exist "%COSMO_WORK_DIR%" mkdir "%COSMO_WORK_DIR%"

echo Configuring environment paths...
conda env config vars set -n "%ENV_NAME%" WEATHER_DATA_DIR="%DATA_ROOT%" COSMO_WORK_DIR="%COSMO_WORK_DIR%"

conda run -n "%ENV_NAME%" pip install -e .
if errorlevel 1 (
    echo ERROR: pip install -e . failed -- check output above.
    exit /b 1
)
echo   Package installed. Use: python -m weather info

REM ── Verify installation ───────────────────────────────────────────────────
echo.
echo Verifying installation...
conda run -n "%ENV_NAME%" python -m weather info
if errorlevel 1 (
    echo WARNING: Verification failed -- check output above.
)

REM ── Done ──────────────────────────────────────────────────────────────────
echo.
echo ================================================================
echo   Setup complete.
echo.
echo   Reactivate: conda deactivate ^&^& conda activate %ENV_NAME%
echo   Verify:     python -m weather info
echo ================================================================
endlocal
