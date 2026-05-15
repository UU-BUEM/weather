"""ERA5-Land provider scaffold."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ...common.env import data_root, load_repo_env


class ERA5LandProvider:
    """Placeholder for ERA5-Land pipeline implementation."""

    name = "era5-land"

    def get_config_summary(self) -> dict[str, Any]:
        load_repo_env()
        default_work = data_root() / "era5_land"
        work_dir = Path(
            os.environ.get("ERA5LAND_WORK_DIR", str(default_work))
        )
        year = int(os.environ.get("ERA5LAND_YEAR", "2018"))
        months = os.environ.get(
            "ERA5LAND_MONTHS",
            "01,02,03,04,05,06,07,08,09,10,11,12",
        )
        return {
            "provider": self.name,
            "work_dir": work_dir.expanduser().resolve(),
            "year": year,
            "months": months,
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
            (
                "ERA5-Land pipeline is not implemented yet. "
                "Use --provider cosmo-rea6 for now."
            )
        )
