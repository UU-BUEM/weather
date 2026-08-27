"""Tests for COSMO-REA6's spurious ``step``-dimension guard.

Regression cover for a real archive defect found on 2026-08-24: of the
296 monthly files on ``sd26``, exactly one -- ``COSMO_REA6_2005_11`` --
was written with ``SNOWFALL`` shaped ``(time, step, y, x)`` because
cfgrib decoded that month with two forecast steps.  ``step=0`` was
entirely NaN; ``step=1`` held the real 1-hour accumulation.

``_strip_scalar_coords`` could not catch it: it drops non-dimension
coordinates, and here ``step`` was a genuine dimension of size 2.
"""

from __future__ import annotations

import logging

import numpy as np
import pytest
import xarray as xr

from weather.providers.cosmo_rea6.transform import _collapse_step_dim


def _with_step(n_steps: int = 2) -> xr.Dataset:
    """Dataset shaped like the 2005-11 defect: step 0 NaN, step 1 real."""
    data = np.zeros((3, n_steps, 2, 2), dtype="f4")
    data[:, 0] = np.nan
    data[:, 1:] = np.arange(3 * (n_steps - 1) * 4, dtype="f4").reshape(
        3, n_steps - 1, 2, 2
    )
    return xr.Dataset(
        {"SNOWFALL": (("time", "step", "y", "x"), data)},
        coords={"step": np.arange(n_steps)},
    )


def test_step_dimension_is_collapsed() -> None:
    """A size-2 step dimension is removed, restoring (time, y, x)."""
    ds = _with_step()
    out = _collapse_step_dim(ds, "SNOW_CON.2D.200511.grb")

    assert out["SNOWFALL"].dims == ("time", "y", "x")
    assert "step" not in out.dims
    assert "step" not in out.variables


def test_last_step_is_the_one_kept() -> None:
    """The accumulation is carried at the END of the interval.

    Selecting step 0 would silently ship an all-NaN SNOWFALL month.
    """
    ds = _with_step()
    out = _collapse_step_dim(ds, "SNOW_CON.2D.200511.grb")

    np.testing.assert_array_equal(
        out["SNOWFALL"].values, ds["SNOWFALL"].isel(step=-1).values
    )
    assert np.isfinite(out["SNOWFALL"].values).all()


def test_dataset_without_step_is_untouched() -> None:
    """The 295 well-formed months must pass through unchanged."""
    ds = xr.Dataset(
        {"T": (("time", "y", "x"), np.zeros((3, 2, 2), dtype="f4"))}
    )
    assert _collapse_step_dim(ds, "T_2M.2D.201801.grb") is ds


def test_collapse_warns_with_the_file_name(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A silent fix would hide a recurrence; the file must be named."""
    with caplog.at_level(logging.WARNING):
        _collapse_step_dim(_with_step(), "SNOW_GSP.2D.200511.grb")

    assert "SNOW_GSP.2D.200511.grb" in caplog.text
    assert "step" in caplog.text.lower()


def test_more_than_two_steps_also_collapses() -> None:
    """The guard is not hard-coded to the size-2 case that was observed."""
    out = _collapse_step_dim(_with_step(n_steps=4), "x.grb")
    assert out["SNOWFALL"].dims == ("time", "y", "x")
