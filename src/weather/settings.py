"""Centralised environment settings for the weather pipeline.

All runtime configuration — paths, parallelism, authentication
endpoints, Slurm options — is exposed through :class:`EnvSettings`.
Values are read from environment variables at call time, so a change
to ``.env`` or ``os.environ`` takes effect immediately without
reimporting.

Configuration priority
----------------------
1. Environment variable (highest).
2. ``.env`` file loaded once at import time.
3. Sensible defaults coded here.

Typical usage::

    from weather.settings import EnvSettings

    print(EnvSettings.cosmo_work_dir())
    print(EnvSettings.cosmo_year())

To override for a single run without touching ``.env``::

    import os
    os.environ["COSMO_WORK_DIR"] = "/scratch/my_run"
    from weather.settings import EnvSettings
    print(EnvSettings.cosmo_work_dir())  # /scratch/my_run

``.env`` file keys (copy ``.env.example`` to ``.env`` and adjust)::

    WEATHER_DATA_DIR   # root for all provider data
    COSMO_WORK_DIR     # COSMO-REA6 working directory
    COSMO_YEAR         # four-digit year to process
    COSMO_BASE_URL     # DWD OpenData HTTPS base URL
    COSMO_NCORES       # parallel worker count
    MERRA_WORK_DIR     # MERRA-2 working directory
    MERRA_YEAR         # MERRA-2 year
    ERA5_WORK_DIR      # ERA5-Land working directory
    ERA5_YEAR          # ERA5-Land year
"""

from __future__ import annotations

import os
from pathlib import Path

from .common.env import data_root, load_repo_env

# Load .env exactly once at import time.
load_repo_env()


class EnvSettings:
    """Central access point for all weather-pipeline configuration.

    Every method is a ``@staticmethod`` that reads from
    ``os.environ`` (populated by ``.env``) with a fallback default.
    Paths are returned as resolved :class:`pathlib.Path` objects.
    Scalar values are returned as their natural Python type.
    """

    # ------------------------------------------------------------------
    # Shared
    # ------------------------------------------------------------------

    @staticmethod
    def data_dir() -> Path:
        """Root directory for all provider data (WEATHER_DATA_DIR)."""
        return data_root()

    # ------------------------------------------------------------------
    # COSMO-REA6
    # ------------------------------------------------------------------

    @staticmethod
    def cosmo_work_dir() -> Path:
        """COSMO-REA6 working root (COSMO_WORK_DIR)."""
        raw = os.getenv(
            "COSMO_WORK_DIR",
            str(data_root() / "cosmo_rea6"),
        )
        return Path(raw).expanduser().resolve()

    @staticmethod
    def cosmo_download_dir() -> Path:
        """``<cosmo_work_dir>/download``."""
        return EnvSettings.cosmo_work_dir() / "download"

    @staticmethod
    def cosmo_decompress_dir() -> Path:
        """``<cosmo_work_dir>/decompress``."""
        return EnvSettings.cosmo_work_dir() / "decompress"

    @staticmethod
    def cosmo_processed_dir() -> Path:
        """``<cosmo_work_dir>/processed``."""
        return EnvSettings.cosmo_work_dir() / "processed"

    @staticmethod
    def cosmo_output_dir() -> Path:
        """``<cosmo_work_dir>/output``."""
        return EnvSettings.cosmo_work_dir() / "output"

    @staticmethod
    def cosmo_year() -> int:
        """Processing year (COSMO_YEAR, default 2018)."""
        return int(os.getenv("COSMO_YEAR", "2018"))

    @staticmethod
    def cosmo_base_url() -> str:
        """DWD OpenData HTTPS base URL (COSMO_BASE_URL)."""
        return os.getenv(
            "COSMO_BASE_URL",
            (
                "https://opendata.dwd.de/climate_environment"
                "/REA/COSMO_REA6/hourly/2D"
            ),
        )

    @staticmethod
    def cosmo_const_url() -> str:
        """DWD OpenData constant-field URL (COSMO_CONST_URL)."""
        return os.getenv(
            "COSMO_CONST_URL",
            (
                "https://opendata.dwd.de/climate_environment"
                "/REA/COSMO_REA6/constant"
            ),
        )

    @staticmethod
    def cosmo_ncores() -> int:
        """
        Parallel worker count (COSMO_NCORES or SLURM_CPUS_PER_TASK, default 4).
        """
        return int(
            os.getenv(
                "COSMO_NCORES",
                os.getenv("SLURM_CPUS_PER_TASK", "4"),
            )
        )

    @staticmethod
    def cosmo_threads_per_job() -> int:
        """bzip2 threads per decompression job (COSMO_THREADS_PER_JOB)."""
        return int(os.getenv("COSMO_THREADS_PER_JOB", "4"))

    @staticmethod
    def cosmo_decompressor() -> str:
        """Preferred decompressor command (COSMO_DECOMPRESSOR).

        One of ``"lbzip2"``, ``"pbzip2"``, ``""`` (auto-detect).
        """
        return os.getenv("COSMO_DECOMPRESSOR", "")

    @staticmethod
    def cosmo_conda_env() -> str:
        """Conda environment name for scripts (COSMO_CONDA_ENV)."""
        return os.getenv("COSMO_CONDA_ENV", "weather_env")

    @staticmethod
    def cosmo_log_dir() -> Path:
        """Directory for pipeline run logs (COSMO_LOG_DIR).

        Defaults to ``<cosmo_work_dir>/logs``.  On shared HPC systems you
        may want per-user log directories; set ``COSMO_LOG_DIR`` explicitly
        in ``.env`` or the environment to override.
        """
        raw = os.getenv("COSMO_LOG_DIR", "").strip()
        if raw:
            return Path(raw).expanduser().resolve()
        return EnvSettings.cosmo_work_dir() / "logs"

    @staticmethod
    def cosmo_slurm_partition() -> str:
        """SLURM partition for job submission (COSMO_SLURM_PARTITION)."""
        return os.getenv("COSMO_SLURM_PARTITION", "rome")

    @staticmethod
    def cosmo_slurm_email() -> str:
        """SLURM notification e-mail (COSMO_SLURM_EMAIL)."""
        return os.getenv("COSMO_SLURM_EMAIL", "")

    # ------------------------------------------------------------------
    # MERRA-2
    # ------------------------------------------------------------------

    @staticmethod
    def merra2_work_dir() -> Path:
        """MERRA-2 working root (MERRA_WORK_DIR)."""
        raw = os.getenv(
            "MERRA_WORK_DIR",
            str(data_root() / "merra2"),
        )
        return Path(raw).expanduser().resolve()

    @staticmethod
    def merra2_download_dir() -> Path:
        """``<merra2_work_dir>/download``."""
        return EnvSettings.merra2_work_dir() / "download"

    @staticmethod
    def merra2_processed_dir() -> Path:
        """``<merra2_work_dir>/processed``."""
        return EnvSettings.merra2_work_dir() / "processed"

    @staticmethod
    def merra2_output_dir() -> Path:
        """``<merra2_work_dir>/output``."""
        return EnvSettings.merra2_work_dir() / "output"

    @staticmethod
    def merra2_year() -> int:
        """Processing year (MERRA_YEAR, default 2018)."""
        return int(os.getenv("MERRA_YEAR", "2018"))

    @staticmethod
    def merra2_ncores() -> int:
        """Parallel worker count (MERRA_NCORES or SLURM_CPUS_PER_TASK)."""
        return int(
            os.getenv(
                "MERRA_NCORES",
                os.getenv(
                    "SLURM_CPUS_PER_TASK",
                    str(os.cpu_count() or 4),
                ),
            )
        )

    @staticmethod
    def merra2_threads_per_job() -> int:
        """Threads per job (MERRA_THREADS_PER_JOB)."""
        return int(os.getenv("MERRA_THREADS_PER_JOB", "4"))

    @staticmethod
    def merra2_conda_env() -> str:
        """Conda environment name (MERRA_CONDA_ENV)."""
        return os.getenv("MERRA_CONDA_ENV", "weather_env")

    @staticmethod
    def merra2_slurm_partition() -> str:
        """SLURM partition (MERRA_SLURM_PARTITION)."""
        return os.getenv("MERRA_SLURM_PARTITION", "rome")

    @staticmethod
    def merra2_slurm_email() -> str:
        """SLURM notification e-mail (MERRA_SLURM_EMAIL)."""
        return os.getenv("MERRA_SLURM_EMAIL", "")

    # ------------------------------------------------------------------
    # ERA5-Land
    # ------------------------------------------------------------------

    @staticmethod
    def era5_work_dir() -> Path:
        """ERA5-Land working root (ERA5_WORK_DIR)."""
        raw = os.getenv(
            "ERA5_WORK_DIR",
            str(data_root() / "era5_land"),
        )
        return Path(raw).expanduser().resolve()

    @staticmethod
    def era5_download_dir() -> Path:
        """``<era5_work_dir>/download``."""
        return EnvSettings.era5_work_dir() / "download"

    @staticmethod
    def era5_processed_dir() -> Path:
        """``<era5_work_dir>/processed``."""
        return EnvSettings.era5_work_dir() / "processed"

    @staticmethod
    def era5_output_dir() -> Path:
        """``<era5_work_dir>/output``."""
        return EnvSettings.era5_work_dir() / "output"

    @staticmethod
    def era5_year() -> int:
        """Processing year (ERA5_YEAR, default 2018)."""
        return int(os.getenv("ERA5_YEAR", "2018"))

    @staticmethod
    def era5_ncores() -> int:
        """Parallel worker count (ERA5_NCORES or SLURM_CPUS_PER_TASK)."""
        return int(
            os.getenv(
                "ERA5_NCORES",
                os.getenv(
                    "SLURM_CPUS_PER_TASK",
                    str(os.cpu_count() or 4),
                ),
            )
        )

    @staticmethod
    def era5_threads_per_job() -> int:
        """Threads per job (ERA5_THREADS_PER_JOB)."""
        return int(os.getenv("ERA5_THREADS_PER_JOB", "4"))

    @staticmethod
    def era5_conda_env() -> str:
        """Conda environment name (ERA5_CONDA_ENV)."""
        return os.getenv("ERA5_CONDA_ENV", "weather_env")

    @staticmethod
    def era5_cds_dataset() -> str:
        """CDS dataset id for ERA5-Land (ERA5_CDS_DATASET)."""
        return os.getenv("ERA5_CDS_DATASET", "reanalysis-era5-land")

    @staticmethod
    def era5_data_format() -> str:
        """CDS response data format (ERA5_DATA_FORMAT).

        Typical values: ``"grib"`` (recommended), ``"netcdf"``.
        """
        return os.getenv("ERA5_DATA_FORMAT", "grib")

    @staticmethod
    def era5_download_format() -> str:
        """CDS download packaging format (ERA5_DOWNLOAD_FORMAT)."""
        return os.getenv("ERA5_DOWNLOAD_FORMAT", "unarchived")

    @staticmethod
    def era5_cds_url() -> str:
        """CDS API URL override (ERA5_CDS_URL)."""
        return os.getenv("ERA5_CDS_URL", "").strip()

    @staticmethod
    def era5_cds_key() -> str:
        """CDS API key override (ERA5_CDS_KEY).

        Prefer ``~/.cdsapirc``.  Use this only in controlled
        environments such as CI secrets or scheduler exports.
        """
        return os.getenv("ERA5_CDS_KEY", "").strip()

    @staticmethod
    def era5_slurm_partition() -> str:
        """SLURM partition (ERA5_SLURM_PARTITION)."""
        return os.getenv("ERA5_SLURM_PARTITION", "rome")

    @staticmethod
    def era5_slurm_email() -> str:
        """SLURM notification e-mail (ERA5_SLURM_EMAIL)."""
        return os.getenv("ERA5_SLURM_EMAIL", "")
