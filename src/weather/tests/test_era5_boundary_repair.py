"""Unit tests for weather.providers.era5_land.boundary_repair.

Exercises ``repair_boundaries()`` against small synthetic monthly NetCDFs
(a 2x2 spatial grid, a handful of hourly stamps) rather than real ERA5-Land
archives -- this validates the repair ARITHMETIC and control flow
(predecessor lookup, archive-start blanking, idempotent skip, grid-mismatch
detection), not real GRIB decoding.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

xr = pytest.importorskip("xarray")
pytest.importorskip("netCDF4")

from weather.providers.era5_land.boundary_repair import (  # noqa: E402
    repair_boundaries,
)

_UNREPAIRED_STATUS = (
    "UNREPAIRED: first timestamp holds the raw accumulated daily "
    "total / 3600, not an hourly flux."
)


def _write_month(
    out_dir, year, month, times, ghi_values, *, shape=(2, 2), status=_UNREPAIRED_STATUS
):
    """Write a synthetic monthly file: GHI[t] = ghi_values[t] on every cell."""
    data = np.array(ghi_values, dtype="float32").reshape(-1, 1, 1) * np.ones(
        (1, *shape), dtype="float32"
    )
    ds = xr.Dataset(
        {"GHI": (("time", "y", "x"), data)},
        coords={"time": pd.DatetimeIndex(times)},
    )
    ds.attrs["boundary_status"] = status
    path = out_dir / f"ERA5_LAND_{year}_{month:02d}_all_attrs.nc"
    ds.to_netcdf(path)
    ds.close()
    return path


class TestRepairBoundaries:
    def test_repairs_first_stamp_from_predecessor(self, tmp_path) -> None:
        # Dec 2017: 2 days, so the last day (Dec 2) has hours 1..23 present.
        prev_times = pd.date_range("2017-12-01", periods=48, freq="h")
        prev_values = [0.0] * 24 + [10.0] * 24  # last day: 10.0 every hour
        _write_month(
            tmp_path, 2017, 12, prev_times, prev_values, status="BOUNDARY_REPAIRED: n/a"
        )

        # Jan 2018: first stamp holds the raw (unrepaired) daily total.
        cur_times = pd.date_range("2018-01-01", periods=3, freq="h")
        raw_first = 300.0
        cur_path = _write_month(tmp_path, 2018, 1, cur_times, [raw_first, 5.0, 6.0])

        counts = repair_boundaries(tmp_path, months={(2018, 1)})
        assert counts == {"repaired": 1, "skipped": 0, "gaps": 0, "errors": 0}

        repaired = xr.open_dataset(cur_path)
        # prev's last-day hours 01:00..23:00 sum to 23 * 10.0 = 230.0.
        expected = raw_first - 230.0
        assert float(repaired["GHI"].isel(time=0, y=0, x=0)) == pytest.approx(expected)
        assert float(repaired["GHI_boundary_raw"].isel(y=0, x=0)) == pytest.approx(
            raw_first
        )
        assert repaired.attrs["boundary_status"].startswith("BOUNDARY_REPAIRED")
        repaired.close()

    def test_already_repaired_is_idempotent_noop(self, tmp_path) -> None:
        prev_times = pd.date_range("2017-12-01", periods=48, freq="h")
        _write_month(
            tmp_path, 2017, 12, prev_times, [0.0] * 24 + [10.0] * 24,
            status="BOUNDARY_REPAIRED: n/a",
        )
        cur_times = pd.date_range("2018-01-01", periods=3, freq="h")
        cur_path = _write_month(tmp_path, 2018, 1, cur_times, [300.0, 5.0, 6.0])

        first = repair_boundaries(tmp_path, months={(2018, 1)})
        assert first["repaired"] == 1

        before = xr.open_dataset(cur_path)["GHI"].isel(time=0, y=0, x=0).item()

        second = repair_boundaries(tmp_path, months={(2018, 1)})
        assert second == {"repaired": 0, "skipped": 1, "gaps": 0, "errors": 0}

        after = xr.open_dataset(cur_path)["GHI"].isel(time=0, y=0, x=0).item()
        assert before == after

    def test_archive_start_blanks_first_stamp(self, tmp_path) -> None:
        # Only file in the folder -> genuinely the earliest, no predecessor
        # exists anywhere, so its first stamp gets blanked, not repaired.
        cur_times = pd.date_range("1950-01-01", periods=3, freq="h")
        cur_path = _write_month(tmp_path, 1950, 1, cur_times, [999.0, 5.0, 6.0])

        counts = repair_boundaries(tmp_path, months={(1950, 1)})
        assert counts == {"repaired": 1, "skipped": 0, "gaps": 0, "errors": 0}

        ds = xr.open_dataset(cur_path)
        assert np.isnan(float(ds["GHI"].isel(time=0, y=0, x=0)))
        assert float(ds["GHI_boundary_raw"].isel(y=0, x=0)) == pytest.approx(999.0)
        assert "archive start" in ds.attrs["boundary_status"]
        ds.close()

    def test_real_gap_left_unrepaired(self, tmp_path) -> None:
        # Jan 2018 exists, but Feb 2018 (its own predecessor month, Jan) IS
        # present -- however Mar 2018's predecessor (Feb) is MISSING, and
        # Mar is not the archive's earliest file (Jan is) -> a genuine gap.
        jan_times = pd.date_range("2018-01-01", periods=3, freq="h")
        _write_month(tmp_path, 2018, 1, jan_times, [1.0, 2.0, 3.0])

        mar_times = pd.date_range("2018-03-01", periods=3, freq="h")
        mar_path = _write_month(tmp_path, 2018, 3, mar_times, [999.0, 5.0, 6.0])

        counts = repair_boundaries(tmp_path, months={(2018, 3)})
        assert counts == {"repaired": 0, "skipped": 0, "gaps": 1, "errors": 0}

        ds = xr.open_dataset(mar_path)
        assert ds.attrs["boundary_status"] == _UNREPAIRED_STATUS
        assert float(ds["GHI"].isel(time=0, y=0, x=0)) == pytest.approx(999.0)
        ds.close()

    def test_grid_mismatch_reports_error_and_skips(self, tmp_path) -> None:
        prev_times = pd.date_range("2017-12-01", periods=48, freq="h")
        _write_month(
            tmp_path, 2017, 12, prev_times, [0.0] * 24 + [10.0] * 24,
            shape=(2, 2), status="BOUNDARY_REPAIRED: n/a",
        )
        cur_times = pd.date_range("2018-01-01", periods=3, freq="h")
        # Different spatial shape than its predecessor -> grid mismatch.
        cur_path = _write_month(
            tmp_path, 2018, 1, cur_times, [300.0, 5.0, 6.0], shape=(3, 3)
        )

        counts = repair_boundaries(tmp_path, months={(2018, 1)})
        assert counts == {"repaired": 0, "skipped": 0, "gaps": 0, "errors": 1}

        # Never written to -- still the raw, unrepaired value.
        ds = xr.open_dataset(cur_path)
        assert ds.attrs["boundary_status"] == _UNREPAIRED_STATUS
        assert "GHI_boundary_raw" not in ds
        ds.close()

    def test_missing_months_raises(self, tmp_path) -> None:
        cur_times = pd.date_range("2018-01-01", periods=3, freq="h")
        _write_month(tmp_path, 2018, 1, cur_times, [1.0, 2.0, 3.0])

        with pytest.raises(FileNotFoundError):
            repair_boundaries(tmp_path, months={(2019, 6)})

    def test_empty_directory_returns_zero_counts(self, tmp_path) -> None:
        counts = repair_boundaries(tmp_path)
        assert counts == {"repaired": 0, "skipped": 0, "gaps": 0, "errors": 0}
