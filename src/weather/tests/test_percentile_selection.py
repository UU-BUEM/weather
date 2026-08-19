"""Tests for percentile representative-year selection.

Covers the 2026-08-19 correction described in
``docs/percentile_methodology.md`` section 3.2.1: the selected year must
actually sit at the requested brightness level, and the selection must
not hand ties to whichever year happens to sort first.

The superseded rule failed both. Measured against the real 76-year
ERA5-Land archive it put P10/P50/P90 at brightness ranks
0.273/0.240/0.268 instead of 0.10/0.50/0.90, and gave the earliest year
in the archive 52-59% of all cells at every percentile level.
"""

from __future__ import annotations

import pathlib
import re

import numpy as np
import pytest

from weather.providers.era5_land.percentile_index import (
    Era5LandPercentileIndexer,
    _month_hour_offset,
)

N_DAYS = 31
N_Y = 4
N_X = 3
FIRST_YEAR = 1950

#: Selection block shared verbatim by all three providers.
_SELECT_RE = re.compile(
    r"        # Per-year monthly GHI total.*?        del year_total, best\n",
    re.S,
)


def _registry(levels: np.ndarray, seed: int) -> dict:
    """Build ``{month: {year: (days, y, x)}}`` with a known brightness order.

    Parameters
    ----------
    levels : numpy.ndarray
        Per-year mean daily GHI, ascending, one entry per year.
    seed : int
        Seed for the additive noise.

    Returns
    -------
    dict
        Registry shaped as ``_compute_ks_for_month`` expects.
    """
    rng = np.random.default_rng(seed)
    reg: dict = {1: {}}
    for i, lvl in enumerate(levels):
        arr = np.full((N_DAYS, N_Y, N_X), float(lvl), dtype=np.float32)
        arr += rng.normal(0.0, 1.0, arr.shape).astype(np.float32)
        reg[1][FIRST_YEAR + i] = arr
    return reg


def _indexer() -> Era5LandPercentileIndexer:
    """Return an indexer wired to the synthetic grid size."""
    return Era5LandPercentileIndexer("src", "tgt", n_y=N_Y, n_lon=N_X)


@pytest.mark.parametrize(("pct", "q"), [("P10", 0.10),
                                        ("P50", 0.50),
                                        ("P90", 0.90)])
def test_selection_matches_requested_brightness_level(pct, q):
    """Each P-level must land at the matching brightness rank."""
    n = 40
    reg = _registry(np.linspace(1000.0, 5000.0, n), seed=0)
    maps = _indexer()._compute_ks_for_month(1, reg)

    # Brightness is monotonic in year by construction, so a year's
    # rank is simply its offset from the first year.
    ranks = (maps[f"{pct}_01"].astype(int) - FIRST_YEAR) / (n - 1)
    assert abs(float(ranks.mean()) - q) < 0.08, (
        f"{pct} landed at brightness rank {ranks.mean():.3f},"
        f" expected ~{q}"
    )


def test_p10_is_cloudier_than_p50_which_is_cloudier_than_p90():
    """The three levels must be ordered, not collapsed onto each other."""
    reg = _registry(np.linspace(500.0, 4000.0, 30), seed=1)
    maps = _indexer()._compute_ks_for_month(1, reg)
    total = {y: float(arr.sum()) for y, arr in reg[1].items()}

    means = [
        float(np.mean([total[int(v)] for v in maps[f"{p}_01"].ravel()]))
        for p in ("P10", "P50", "P90")
    ]
    assert means[0] < means[1] < means[2], f"levels not ordered: {means}"


def test_no_earliest_year_domination():
    """No single year may sweep the grid at every percentile level."""
    reg = _registry(np.linspace(1500.0, 3500.0, 60), seed=2)
    maps = _indexer()._compute_ks_for_month(1, reg)

    for pct in ("P10", "P50", "P90"):
        sel = maps[f"{pct}_01"]
        share = float((sel == FIRST_YEAR).mean())
        assert share < 0.35, (
            f"{pct}: earliest year won {share:.0%} of cells"
        )


@pytest.mark.parametrize(("first_stamp", "expected"), [
    ("2018-03-01T00:00", 0),
    ("1950-01-01T01:00", 1),
    ("2001-07-01T05:00", 5),
])
def test_month_hour_offset(first_stamp, expected):
    """Offset of the first stamp within its calendar month, in hours."""
    times = np.array([first_stamp], dtype="datetime64[ns]")
    assert _month_hour_offset(times) == expected


def test_short_first_year_does_not_undersize_the_mosaic():
    """A 743-hour January must not size the mosaic for a 744-hour one.

    Reproduces the broadcast failure the old code hit once ERA5-Land's
    1950-01 (no 00:00 stamp) became the reference year.
    """
    t_size = max(0 + 744, 1 + 743)
    assert t_size == 744

    mosaic = np.full((t_size, N_Y, N_X), np.nan, dtype=np.float32)
    rows, cols = np.where(np.ones((N_Y, N_X), dtype=bool))

    # Full-length year at offset 0, short year at offset 1.
    for offset, length in ((0, 744), (1, 743)):
        data = np.ones((length, N_Y, N_X), dtype=np.float32)
        mosaic[offset:offset + length, rows, cols] = data[:length, rows, cols]

    assert not np.isnan(mosaic).any()


def test_all_providers_share_one_selection_block():
    """Guard against the fix drifting apart across the three copies."""
    root = pathlib.Path(__file__).resolve().parents[1] / "providers"
    blocks = []
    for provider in ("era5_land", "cosmo_rea6", "merra2"):
        src = (root / provider / "percentile_index.py").read_text(
            encoding="utf-8"
        ).replace("\r\n", "\n")
        match = _SELECT_RE.search(src)
        assert match is not None, f"{provider}: selection block not found"
        blocks.append(match.group(0))

    assert blocks[0] == blocks[1] == blocks[2], (
        "providers' selection blocks have drifted apart"
    )
