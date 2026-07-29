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

    def run_pipeline(self, *args: Any, **kwargs: Any) -> Path:
        """Run the COSMO-REA6 pipeline from generic CLI kwargs.

        The shared CLI (`weather run`) may pass ``output_path`` (a single
        combined output file) -- COSMO now always writes one NetCDF per
        month to ``output_dir`` instead, matching
        :class:`~weather.providers.era5_land.ERA5LandProvider` /
        :class:`~weather.providers.merra2.MERRA2Provider`, so that kwarg
        is absorbed/dropped here rather than forwarded blindly.
        """
        kwargs.pop("output_path", None)  # COSMO writes one file per month

        outputs = run_cosmo_pipeline(*args, **kwargs)
        return outputs[0] if outputs else Path()
