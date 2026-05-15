"""Environment and path helpers for the weather package.

Loads a project-level ``.env`` file (if present) and provides normalized
path helpers used by providers.
"""

from __future__ import annotations

import os
from pathlib import Path

_ENV_LOADED = False


def repo_root() -> Path:
    """Return repository root inferred from package location."""
    # src/weather/common/env.py -> repo root is parents[3]
    return Path(__file__).resolve().parents[3]


def _resolve_path(raw: str, *, base: Path) -> Path:
    p = Path(raw).expanduser()
    if not p.is_absolute():
        p = base / p
    return p.resolve()


def load_repo_env() -> None:
    """Load .env once from current working directory or repo root."""
    global _ENV_LOADED
    if _ENV_LOADED:
        return

    try:
        from dotenv import load_dotenv  # type: ignore
    except ImportError:
        _ENV_LOADED = True
        return

    root = repo_root()
    candidates = [
        Path.cwd() / ".env",
        root / ".env",
    ]

    env_override = os.environ.get("WEATHER_ENV_FILE", "").strip()
    if env_override:
        candidates.insert(0, _resolve_path(env_override, base=root))

    for candidate in candidates:
        if candidate.is_file():
            load_dotenv(candidate, override=False)
            break

    _ENV_LOADED = True


def data_root() -> Path:
    """Return normalized data root for provider outputs.

    Priority:
    1. ``WEATHER_DATA_DIR`` environment variable / .env
    2. ``<repo>/data``
    """
    load_repo_env()
    root = repo_root()
    raw = os.environ.get("WEATHER_DATA_DIR", "").strip()
    if raw:
        return _resolve_path(raw, base=root)
    return (root / "data").resolve()
