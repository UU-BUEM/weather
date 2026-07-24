"""MERRA-2 provider package.

Public entry points:

* :func:`~weather.providers.merra2.pipeline.run_pipeline` — process one
  year (download -> transform -> export monthly NetCDF).
* :func:`~weather.providers.merra2.download.download_all` — fetch daily
  rad/slv/lnd NetCDF4 files from NASA GES DISC via OPeNDAP.
* :func:`~weather.providers.merra2.transform.build_monthly_dataset` —
  daily files -> analysis-ready monthly dataset with derived GHI.
* :mod:`~weather.providers.merra2.percentile_index` — P10/P50/P90
  representative-year mosaics from historical monthly output.
* :mod:`~weather.providers.merra2.dni_pointwise` — opt-in DNI/DHI
  decomposition for selected locations.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ...common.net import earthdata_auth
from .config import get_config
from .pipeline import run_pipeline


class MERRA2Provider:
    """Thin façade over the MERRA-2 pipeline functions."""

    name = "merra-2"

    def get_config_summary(self) -> dict[str, Any]:
        cfg = get_config()
        return {
            "provider": self.name,
            "work_dir": cfg["work_dir"],
            "year": cfg["year"],
            "attributes": cfg["attributes"],
            "area": cfg["area"],
            "status": "implemented",
        }

    def validate_environment(self) -> list[str]:
        """Check that required libraries and credentials are available."""
        issues: list[str] = []
        for pkg in ("xarray", "netCDF4", "requests"):
            try:
                __import__(pkg)
            except ImportError:
                issues.append(
                    f"Python package '{pkg}' not installed "
                    f"(conda install -c conda-forge {pkg})"
                )
        try:
            earthdata_auth()
        except OSError as exc:
            issues.append(str(exc))
        return issues

    def run_pipeline(self, *args: Any, **kwargs: Any) -> Path:
        """Run the MERRA-2 pipeline from generic CLI kwargs.

        The shared CLI (`weather run`) passes COSMO-flavoured kwargs
        (``output_path``, ``include_wind_components``,
        ``skip_decompress``).  MERRA-2 has no decompress step and a
        single-folder monthly output, so those are absorbed/translated
        here rather than forwarded blindly — matching
        :class:`~weather.providers.era5_land.ERA5LandProvider`.
        """
        # Translate / drop COSMO-only kwargs.
        kwargs.pop("output_path", None)             # writes to output_dir
        kwargs.pop("include_wind_components", None)  # always keeps u/v
        kwargs.pop("skip_decompress", None)          # no decompress phase

        outputs = run_pipeline(*args, **kwargs)
        return outputs[0] if outputs else Path()
