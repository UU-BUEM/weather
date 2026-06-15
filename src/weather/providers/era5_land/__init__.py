"""ERA5-Land provider scaffold."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ...settings import EnvSettings


class ERA5LandProvider:
    """Placeholder for ERA5-Land pipeline implementation."""

    name = "era5-land"

    def get_config_summary(self) -> dict[str, Any]:
        return {
            "provider": self.name,
            "work_dir": EnvSettings.era5_work_dir(),
            "year": EnvSettings.era5_year(),
            "status": "scaffold",
        }

    def validate_environment(self) -> list[str]:
        return [
            "ERA5-Land provider is scaffolded but not implemented yet.",
            (
                "Implement download, decompress, transform, and final "
                "processing modules before production use."
            ),
        ]

    def run_pipeline(self, *args: Any, **kwargs: Any) -> Path:
        raise NotImplementedError(
            "ERA5-Land pipeline is not implemented yet. "
            "Use --provider cosmo-rea6 for now."
        )
