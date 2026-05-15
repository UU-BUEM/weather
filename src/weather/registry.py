"""Provider registry for weather data pipelines.

Providers are instantiated lazily on first access to avoid importing
heavy provider modules (cfgrib, xarray, etc.) until they are actually needed.
"""

from __future__ import annotations

import os
from typing import Any


def _normalize(name: str) -> str:
    return name.strip().lower().replace("_", "-")


# Canonical name → factory callable (imported only when first accessed)
_REGISTRY: dict[str, str] = {
    "cosmo-rea6": "weather.providers.cosmo_rea6:CosmoREA6Provider",
    "merra-2":    "weather.providers.merra2:MERRA2Provider",
    "era5-land":  "weather.providers.era5_land:ERA5LandProvider",
}

_ALIASES: dict[str, str] = {
    "cosmo":      "cosmo-rea6",
    "cosmo-rea6": "cosmo-rea6",
    "merra2":     "merra-2",
    "merra-2":    "merra-2",
    "era5":       "era5-land",
    "era5-land":  "era5-land",
}

# Cache of instantiated providers
_cache: dict[str, Any] = {}


def _load_provider(canonical: str) -> Any:
    """Import and instantiate a provider by canonical name."""
    if canonical in _cache:
        return _cache[canonical]

    module_path, class_name = _REGISTRY[canonical].split(":")
    import importlib
    module = importlib.import_module(module_path)
    provider = getattr(module, class_name)()
    _cache[canonical] = provider
    return provider


def list_providers() -> list[str]:
    """Return all supported provider canonical names."""
    return sorted(_REGISTRY.keys())


def get_provider(name: str | None) -> Any:
    """Return a provider instance by canonical name or alias.

    Parameters
    ----------
    name:
        Provider name or alias (case-insensitive, hyphens/underscores
        interchangeable).  ``None`` falls back to the default provider.
    """
    if not name:
        return get_default_provider()

    normalized = _normalize(name)
    canonical = _ALIASES.get(normalized)
    if not canonical:
        available = ", ".join(list_providers())
        raise ValueError(
            f"Unknown provider '{name}'. Available: {available}"
        )
    return _load_provider(canonical)


def get_default_provider() -> Any:
    """Resolve the default provider from the WEATHER_PROVIDER env var."""
    env_name = os.environ.get("WEATHER_PROVIDER", "cosmo-rea6")
    return get_provider(env_name)
