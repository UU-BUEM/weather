"""Thin HTTP interface over weather.get_point_weather().

Scaffold (2026-08-04) -- not wired into this repo's CI, not deployed. See
app.py's module docstring for scope and rationale, and README.md in this
directory for deployment notes.
"""

from __future__ import annotations

from .app import create_app

__all__ = ["create_app"]
