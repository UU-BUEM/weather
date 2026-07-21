"""ERA5-Land provider package.

Public entry points:

* :func:`~weather.providers.era5_land.pipeline.run_pipeline` — process
  one year (download → transform → export monthly NetCDF).
* :func:`~weather.providers.era5_land.download.download_all` — fetch
  monthly all-variables GRIB files from the Copernicus CDS API.
* :func:`~weather.providers.era5_land.transform.build_monthly_dataset`
  — GRIB → analysis-ready dataset with derived GHI.
* :mod:`~weather.providers.era5_land.dni_pointwise` — opt-in DNI/DHI
  decomposition for selected locations.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ...settings import EnvSettings
from .config import get_config
from .pipeline import run_pipeline


class ERA5LandProvider:
    """Thin façade over the ERA5-Land pipeline functions."""

    name = "era5-land"

    def get_config_summary(self) -> dict[str, Any]:
        cfg = get_config()
        return {
            "provider": self.name,
            "work_dir": cfg["work_dir"],
            "year": cfg["year"],
            "attributes": cfg["attributes"],
            "dataset": cfg["dataset"],
            "data_format": cfg["data_format"],
            "status": "implemented",
        }

    def validate_environment(self) -> list[str]:
        """Check that required libraries are importable."""
        issues: list[str] = []
        for pkg in ("xarray", "cfgrib", "cdsapi", "netCDF4", "eccodes"):
            try:
                __import__(pkg)
            except ImportError:
                issues.append(
                    f"Python package '{pkg}' not installed "
                    f"(conda install -c conda-forge {pkg})"
                )
        # CDS credentials: either ~/.cdsapirc or env overrides.
        cdsapirc = Path.home() / ".cdsapirc"
        if not cdsapirc.exists() and not (
            EnvSettings.era5_cds_url() and EnvSettings.era5_cds_key()
        ):
            issues.append(
                "No CDS credentials found: create ~/.cdsapirc or set "
                "ERA5_CDS_URL and ERA5_CDS_KEY."
            )
        return issues

    def run_pipeline(self, *args: Any, **kwargs: Any) -> Path:
        """Run the ERA5-Land pipeline from generic CLI kwargs.

        The shared CLI (`weather run`) passes COSMO-flavoured kwargs
        (``output_path``, ``include_wind_components``,
        ``skip_decompress``).  ERA5-Land has no decompress step and a
        single-folder monthly output, so those are absorbed/translated
        here rather than forwarded blindly.
        """
        # Translate / drop COSMO-only kwargs.
        kwargs.pop("output_path", None)            # ERA5 writes to output_dir
        kwargs.pop("include_wind_components", None)  # ERA5 always keeps u10/v10
        kwargs.pop("skip_decompress", None)        # no decompress phase

        # Map an explicit night-mask flag if the CLI provided one.
        if "no_night_mask" in kwargs:
            kwargs["night_mask"] = not kwargs.pop("no_night_mask")

        outputs = run_pipeline(*args, **kwargs)
        return outputs[0] if outputs else Path()
