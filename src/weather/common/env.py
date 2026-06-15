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


def _load_dotenv_fallback(path: Path) -> None:
    """Minimal .env loader used when python-dotenv is not installed.

    Parses ``KEY=VALUE`` lines, skips blank lines and ``#`` comments,
    strips surrounding quotes from values, and sets ``os.environ``
    (always overrides, same as ``load_dotenv(..., override=True)``).
    """
    with open(path, encoding="utf-8") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            # Drop inline comments and strip surrounding quotes.
            value = value.split("#")[0].strip()
            quoted = (
                len(value) >= 2
                and value[0] in ('"', "'")
                and value[-1] == value[0]
            )
            if quoted:
                value = value[1:-1]
            if key:
                os.environ[key] = value


def load_repo_env() -> None:
    """Load ``.env`` once, preferring the repo root over the CWD.

    Search order (first file found wins):

    1. ``WEATHER_ENV_FILE`` environment variable (explicit override).
    2. ``<repo_root>/.env``  — canonical location, consistent regardless
       of the working directory when the script is launched.
    3. ``Path.cwd()/.env``  — fallback for non-standard layouts.

    The loaded values override any ambient environment variables so that
    the ``.env`` file is the authoritative configuration source.
    CLI-level overrides (e.g. ``os.environ["COSMO_WORK_DIR"] = ...``
    set *after* imports) still take precedence because they are applied
    after this function has already run.
    """
    global _ENV_LOADED
    if _ENV_LOADED:
        return

    root = repo_root()
    candidates: list[Path] = [root / ".env"]
    cwd_env = Path.cwd() / ".env"
    if cwd_env != candidates[0]:
        candidates.append(cwd_env)

    env_override = os.environ.get("WEATHER_ENV_FILE", "").strip()
    if env_override:
        candidates.insert(0, _resolve_path(env_override, base=root))

    for candidate in candidates:
        if candidate.is_file():
            try:
                from dotenv import load_dotenv  # type: ignore
                load_dotenv(candidate, override=True)
            except ImportError:
                _load_dotenv_fallback(candidate)
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
