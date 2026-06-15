"""Provider-agnostic per-cell percentile year selection.

Given a stack of annual scalar metrics (e.g., cumulative GHI) for *N* years
and a set of target percentile levels (e.g., P10/P50/P90), returns — for each
spatial cell — the index of the year whose metric value is closest to that
percentile of the cell's *N*-year distribution.

This module contains **only** the statistical core.  Provider-specific logic
(which variable to treat as the ranking metric, how to load annual datasets,
how to write output files) lives in concrete subclasses of
:class:`~weather.providers.base_percentile.BasePercentileAnalyzer`.

Methodology
-----------
For each cell ``(i, j)`` and each percentile ``p``:

1. Compute ``target[i,j] = np.percentile(metric_stack[:, i, j], p*100)``.
2. Find ``year_idx = argmin |metric_stack[:, i, j] − target[i,j]|``.
3. Return ``years[year_idx]`` as the representative year for that cell.

This is consistent with the ISO 15927-4 / ASHRAE TMY methodology: identify
the actual calendar year whose observed metric is closest to the desired
statistical level, then use the full hourly record from that year.

Notes
-----
- *N* = 24 for COSMO-REA6 (1995–2018).  The user's original mention of
  "33 years" refers to the intended future dataset extent; this implementation
  is parameterised and works for any *N* ≥ 2.
- When two years are equidistant from the target, ``argmin`` selects the
  earlier year (NumPy tie-breaking on the first occurrence).
- The function is fully vectorised over the spatial grid and runs in a few
  seconds even for 824 × 848 cells.
"""

from __future__ import annotations

from typing import Sequence

import numpy as np


def select_representative_years(
    metric_stack: np.ndarray,
    years: Sequence[int],
    percentiles: Sequence[float],
) -> dict[float, np.ndarray]:
    """Return the representative year at each cell for every percentile level.

    Parameters
    ----------
    metric_stack : np.ndarray
        Shape ``(n_years, ny, nx)``.  Annual scalar metric per cell
        (e.g., cumulative GHI in W·h/m²).  May contain ``np.nan`` for
        cells with missing data — those cells propagate ``NaN`` to the
        output (cast to ``int32`` as ``−9999``).
    years : sequence of int
        Year labels corresponding to axis 0 of *metric_stack*.
        Must have ``len(years) == metric_stack.shape[0]``.
    percentiles : sequence of float
        Target percentile levels expressed as fractions in ``[0, 1]``.
        Common values: ``[0.10, 0.50, 0.90]``.

    Returns
    -------
    dict[float, np.ndarray]
        Maps each percentile level to an ``(ny, nx)`` array of ``int32``
        representative years.  Fill value ``−9999`` marks cells where all
        years had ``NaN`` metric values.

    Raises
    ------
    ValueError
        If *metric_stack* is empty, has fewer than 2 years, or if
        ``len(years)`` does not match the first dimension.

    Examples
    --------
    >>> import numpy as np
    >>> from weather.common.percentile import select_representative_years
    >>> rng = np.random.default_rng(0)
    >>> stack = rng.normal(500, 50, (24, 3, 3)).astype(np.float32)
    >>> years = list(range(1995, 2019))
    >>> result = select_representative_years(stack, years, [0.10, 0.50, 0.90])
    >>> result[0.50].shape
    (3, 3)
    """
    years_arr = np.asarray(years, dtype=np.int32)
    n_years = years_arr.shape[0]

    if metric_stack.ndim != 3:
        raise ValueError(
            f"metric_stack must be 3-D (n_years, ny, nx), "
            f"got shape {metric_stack.shape}"
        )
    if metric_stack.shape[0] != n_years:
        raise ValueError(
            f"metric_stack axis-0 length ({metric_stack.shape[0]}) "
            f"does not match len(years) ({n_years})"
        )
    if n_years < 2:
        raise ValueError("Need at least 2 years to compute percentiles.")

    result: dict[float, np.ndarray] = {}
    _fill = np.int32(-9999)

    for p in percentiles:
        # Target value at each cell — shape (ny, nx)
        # np.nanpercentile handles NaN cells gracefully.
        target = np.nanpercentile(metric_stack, p * 100.0, axis=0)  # (ny, nx)

        # Absolute distance of each year from the target — (n_years, ny, nx)
        dist = np.abs(metric_stack - target[np.newaxis, ...])

        # Cells where all years are NaN → distance is all NaN → argmin fails
        all_nan = np.all(np.isnan(dist), axis=0)  # (ny, nx)

        # Replace NaN distances with +inf so argmin still returns a valid idx
        dist_safe = np.where(np.isnan(dist), np.inf, dist)
        best_idx = dist_safe.argmin(axis=0)  # (ny, nx), dtype int64

        year_map = years_arr[best_idx].copy()
        year_map[all_nan] = _fill
        result[p] = year_map

    return result


def percentile_rank_stack(
    metric_stack: np.ndarray,
) -> np.ndarray:
    """Compute the percentile rank of each year's value at every cell.

    Useful for diagnostics: shows *where* in the distribution each calendar
    year falls for each spatial cell.

    Parameters
    ----------
    metric_stack : np.ndarray
        Shape ``(n_years, ny, nx)``.

    Returns
    -------
    np.ndarray
        Shape ``(n_years, ny, nx)``, dtype ``float32``.  Values in [0, 100].
    """
    n_years = metric_stack.shape[0]
    ranks = np.empty_like(metric_stack, dtype=np.float32)
    for t in range(n_years):
        # Rank of metric_stack[t] among all years at each cell
        ranks[t] = (
            (metric_stack < metric_stack[t]).sum(axis=0)
            / (n_years - 1) * 100.0
        ).astype(np.float32)
    return ranks
