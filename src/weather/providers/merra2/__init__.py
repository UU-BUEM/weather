"""MERRA-2 provider scaffold."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ...settings import EnvSettings


class MERRA2Provider:
    """Placeholder for MERRA-2 pipeline implementation."""

    name = "merra-2"

    def get_config_summary(self) -> dict[str, Any]:
        return {
            "provider": self.name,
            "work_dir": EnvSettings.merra2_work_dir(),
            "year": EnvSettings.merra2_year(),
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
