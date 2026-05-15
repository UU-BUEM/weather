"""Provider contract for weather data sources."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class WeatherProvider(Protocol):
    """Minimal provider interface used by the CLI registry."""

    name: str

    def get_config_summary(self) -> dict[str, Any]:
        """Return provider-specific resolved configuration."""

    def validate_environment(self) -> list[str]:
        """Return environment issues (empty list means OK)."""

    def run_pipeline(
        self,
        year: int | None = None,
        months: list[int] | None = None,
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
        """Execute provider pipeline and return output artifact path."""
