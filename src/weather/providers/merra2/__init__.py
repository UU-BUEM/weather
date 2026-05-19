"""MERRA-2 provider scaffold."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ...common.env import data_root, load_repo_env


class MERRA2Provider:
    """Placeholder for MERRA-2 pipeline implementation."""

    name = "merra-2"

    def get_config_summary(self) -> dict[str, Any]:
        load_repo_env()
        default_work = data_root() / "merra2"
        work_dir = Path(
            os.environ.get("MERRA2_WORK_DIR", str(default_work))
        )
        year = int(os.environ.get("MERRA2_YEAR", "2018"))
        months = os.environ.get(
            "MERRA2_MONTHS",
            "01,02,03,04,05,06,07,08,09,10,11,12",
        )
        return {
            "provider": self.name,
            "work_dir": work_dir.expanduser().resolve(),
            "year": year,
            "months": months,
            "example_dataset": "M2T1NXLND",
            "example_temperature_var": "T2M",
            "example_temperature_unit": "K",
            "status": "scaffold",
        }

    def validate_environment(self) -> list[str]:
        return [
            "MERRA-2 provider is scaffolded but not implemented yet.",
            (
                "Implement download, decompress, transform, and final "
                "processing modules before production use."
            ),
        ]

    def run_pipeline(self, *args: Any, **kwargs: Any) -> Path:
        raise NotImplementedError(

                "MERRA-2 pipeline is not implemented yet. "
                "Use --provider cosmo-rea6 for now."

        )
