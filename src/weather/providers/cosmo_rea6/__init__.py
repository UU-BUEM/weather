"""COSMO-REA6 provider adapter."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import get_config
from .pipeline import run_pipeline as run_cosmo_pipeline
from .pipeline import validate_environment as validate_cosmo_environment


class CosmoREA6Provider:
    """Provider implementation backed by existing COSMO-REA6 modules."""

    name = "cosmo-rea6"

    def get_config_summary(self) -> dict[str, Any]:
        return get_config()

    def validate_environment(self) -> list[str]:
        return validate_cosmo_environment()

    def run_pipeline(
        self,
        year: int | None = None,
        attributes: list[str] | None = None,
        *,
        work_dir: Path | None = None,
        output_path: Path | None = None,
        include_wind_components: bool = True,
        complevel: int = 1,
        skip_download: bool = False,
        skip_decompress: bool = False,
        cleanup: bool = False,
    ) -> Path:
        return run_cosmo_pipeline(
            year=year,
            attributes=attributes,
            work_dir=work_dir,
            output_path=output_path,
            include_wind_components=include_wind_components,
            complevel=complevel,
            skip_download=skip_download,
            skip_decompress=skip_decompress,
            cleanup=cleanup,
        )
