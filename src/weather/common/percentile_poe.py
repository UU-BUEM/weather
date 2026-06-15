"""Probability-of-Exceedance (PoE) representative-month selection.

Convention
----------
In solar bankability assessments (IEC 61724-1, ASTM E2848) ``P_X`` denotes
the probability that the monthly or annual GHI resource will **equal or
exceed** a given value.  This is the industry standard for solar asset
bankability and project financing.

+----------+----------------------------+---------------------------------+
| PoE name | Ascending percentile (eCDF) | Interpretation                  |
+==========+============================+=================================+
| P10      | 90th (high GHI)            | Optimistic / 10 % exceedance    |
+----------+----------------------------+---------------------------------+
| P50      | 50th (median)              | Typical / 50 % exceedance       |
+----------+----------------------------+---------------------------------+
| P90      | 10th (low GHI)             | Conservative / 90 % exceedance  |
+----------+----------------------------+---------------------------------+

Algorithm
---------
For each calendar month ``m`` and each spatial cell ``(i, j)``:

1. Collect the monthly GHI total from all N analysis years →
   vector ``v`` of length N.
2. Compute the ascending-percentile target using the empirical CDF
   (numpy linear interpolation — no parametric distribution assumed).
   With N = 24 years, fitting Weibull or Beta per cell would be
   computationally prohibitive (~699 k cells × 12 months).  The eCDF is
   the accepted non-parametric estimator for N ≥ 20.
3. Select the year whose monthly GHI is closest to the target
   (argmin absolute distance).

Different cells in the same output month may be drawn from different
source years.  The ``source_year(rlat, rlon)`` variable in each output
file records the provenance.

Note: this module implements GHI-only eCDF ranking.  A full
Finkelstein-Schafer (1981) TMY would additionally weight temperature,
humidity, and wind CDFs; that extension is straightforward to add by
replacing the ``metric_stack`` with a composite statistic.

References
----------
Finkelstein, J. M. & Schafer, R. E. (1981). Improved goodness-of-fit
tests. *Biometrika*, 68(1), 255–260.

IEC 61724-1:2021 — Photovoltaic system performance monitoring.
"""

from __future__ import annotations

import numpy as np


def poe_to_ascending_pct(poe_level: float) -> float:
    """Convert a PoE level (0–1) to an ascending percentile (0–100).

    Parameters
    ----------
    poe_level : float
        PoE level as a fraction in (0, 1).  E.g. ``0.90`` for P90.

    Returns
    -------
    float
        Ascending percentile in [0, 100].

    Examples
    --------
    >>> poe_to_ascending_pct(0.90)  # P90 PoE → low GHI (conservative)
    10.0
    >>> poe_to_ascending_pct(0.50)  # P50 PoE → median
    50.0
    >>> poe_to_ascending_pct(0.10)  # P10 PoE → high GHI (optimistic)
    90.0
    """
    return (1.0 - poe_level) * 100.0


def select_representative_years_poe(
    metric_stack: np.ndarray,
    years: list[int] | np.ndarray,
    poe_levels: list[float],
) -> dict[float, np.ndarray]:
    """Select the representative year per cell for each PoE level.

    Uses an empirical CDF with linear interpolation (numpy default).
    No parametric distribution is fitted.

    Parameters
    ----------
    metric_stack : np.ndarray
        Shape ``(n_years, ny, nx)``, dtype float32.
        Monthly GHI total (W·h/m²) per year and cell.
    years : list[int] or np.ndarray
        Year labels corresponding to axis 0 of ``metric_stack``.
    poe_levels : list[float]
        PoE levels as fractions in (0, 1).
        Use ``[0.10, 0.50, 0.90]`` for P10/P50/P90.

    Returns
    -------
    dict[float, np.ndarray]
        Maps each PoE level to an ``(ny, nx)`` int32 array of
        representative years.
    """
    years_arr = np.asarray(years, dtype=np.int32)
    result: dict[float, np.ndarray] = {}

    for poe in poe_levels:
        asc_pct = poe_to_ascending_pct(poe)
        # eCDF target value per cell: shape (ny, nx)
        target = np.percentile(
            metric_stack, asc_pct, axis=0
        ).astype(np.float32)
        # Absolute distance of each year's metric from target
        dist = np.abs(metric_stack - target[np.newaxis, :, :])
        # Year index with minimum distance per cell: (ny, nx)
        best_idx = np.argmin(dist, axis=0)
        result[poe] = years_arr[best_idx]

    return result
