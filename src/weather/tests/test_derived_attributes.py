"""Unit tests for cross-provider irradiance derivation.

Tests cover:
  1. Night masking   -- all irradiance = 0 when zenith >= 90 deg
  2. No negatives    -- all outputs >= 0.0
  3. Energy balance  -- GHI ~ DHI + DNI * cos(zenith) within 5 W/m2
  4. Dimensionality  -- all three providers produce same-length output
  5. DIRINT tests are skipped if pvlib is not installed

Run with::

    conda run -n weather_env pytest src/weather/tests/
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from weather.common.derived_attributes import (
    NIGHT_ZENITH_DEG,
    apply_derived_fields,
    mask_night,
)

# ---------------------------------------------------------------------------
# Shared synthetic fixtures
# ---------------------------------------------------------------------------

#: Number of hourly time steps (one full day).
N = 24


@pytest.fixture(scope="module")
def times() -> pd.DatetimeIndex:
    """Hourly timestamps for 2018-06-21 UTC (summer solstice)."""
    return pd.date_range(
        "2018-06-21",
        periods=N,
        freq="h",
        tz="UTC",
    )


@pytest.fixture(scope="module")
def zenith_degrees() -> np.ndarray:
    """Solar zenith: 120 deg at midnight -> 0 deg at noon -> 120 deg.

    Indices 0-5 and 18-23 are night (zenith >= 90 deg).
    Indices 6-17 are daylight (zenith < 90 deg).
    """
    return np.abs(np.linspace(120.0, -120.0, N))


@pytest.fixture(scope="module")
def sol_pos(zenith_degrees) -> dict:
    return {"zenith": zenith_degrees}


def _daytime_mask(zenith: np.ndarray) -> np.ndarray:
    """Boolean mask: True where zenith < NIGHT_ZENITH_DEG."""
    return zenith < NIGHT_ZENITH_DEG


# ---------------------------------------------------------------------------
# Synthetic provider datasets
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def cosmo_ds(zenith_degrees) -> dict:
    """Synthetic COSMO-REA6 dataset with realistic daylight values."""
    cos_z = np.cos(np.radians(zenith_degrees)).clip(0.0)
    ghi = (900.0 * cos_z).clip(0.0)   # peak ~900 W/m2 at noon
    return {
        "SWDIFDS_RAD": ghi * 0.2,
        "SWDIRS_RAD": ghi * 0.8,
        "PS": np.full(N, 101_325.0),
        "U_10M": np.full(N, 3.0),
        "V_10M": np.full(N, 4.0),
    }


@pytest.fixture(scope="module")
def merra2_ds(zenith_degrees) -> dict:
    """Synthetic MERRA-2 dataset with realistic daylight values."""
    cos_z = np.cos(np.radians(zenith_degrees)).clip(0.0)
    ghi = (900.0 * cos_z).clip(0.0)
    return {
        "SWGDN": ghi,
        "PS": np.full(N, 101_325.0),
        "QV2M": np.full(N, 0.005),  # kg/kg
        "T2M": np.full(N, 15.0),  # already degC (unlike ERA5-Land's raw Kelvin)
        "U10M": np.full(N, 3.0),
        "V10M": np.full(N, 4.0),
    }


@pytest.fixture(scope="module")
def era5_ds(zenith_degrees) -> dict:
    """Synthetic ERA5-Land dataset with realistic daylight values."""
    cos_z = np.cos(np.radians(zenith_degrees)).clip(0.0)
    ghi_wm2 = (900.0 * cos_z).clip(0.0)
    return {
        "ssrd": ghi_wm2 * 3600.0,  # J/m2 (hourly accumulation)
        "sp": np.full(N, 101_325.0),
        "t2m": np.full(N, 288.15),  # 15 degC
        "d2m": np.full(N, 283.15),  # 10 degC
        "u10": np.full(N, 3.0),
        "v10": np.full(N, 4.0),
    }


# ---------------------------------------------------------------------------
# Class: mask_night utility
# ---------------------------------------------------------------------------

class TestMaskNight:
    """Tests for the shared ``mask_night`` helper."""

    def test_night_values_are_zero(self, zenith_degrees):
        arr = np.ones(N) * 500.0
        result = mask_night(arr, zenith_degrees)
        night = zenith_degrees >= NIGHT_ZENITH_DEG
        assert np.all(result[night] == 0.0), (
            "Night-time indices must be exactly 0.0"
        )

    def test_daylight_values_unchanged_if_positive(
        self, zenith_degrees
    ):
        arr = np.ones(N) * 500.0
        result = mask_night(arr, zenith_degrees)
        day = ~(zenith_degrees >= NIGHT_ZENITH_DEG)
        assert np.allclose(result[day], 500.0)

    def test_negative_values_clipped(self, zenith_degrees):
        arr = np.full(N, -100.0)
        result = mask_night(arr, zenith_degrees)
        assert np.all(result >= 0.0)


# ---------------------------------------------------------------------------
# Class: COSMO-REA6 derivations
# ---------------------------------------------------------------------------

class TestCosmoREA6Derivations:
    """Tests for COSMO-REA6 GHI, DHI, DNI, WS_10M formula functions."""

    @pytest.fixture(autouse=True)
    def _compute(self, cosmo_ds, sol_pos, times):
        self.results = apply_derived_fields(
            ds=cosmo_ds,
            provider="COSMO_REA6",
            sol_pos=sol_pos,
            times=times,
        )
        self.zen = sol_pos["zenith"]

    def test_keys_present(self):
        assert {"GHI", "DHI", "DNI", "WS_10M"} <= self.results.keys()

    def test_wind_speed(self):
        """WS_10M = sqrt(U_10M**2 + V_10M**2) = sqrt(3**2 + 4**2) = 5."""
        assert np.allclose(self.results["WS_10M"], 5.0)

    def test_no_negative_values(self):
        for name, arr in self.results.items():
            assert np.all(arr >= 0.0), (
                f"COSMO-REA6 {name} has negative values"
            )

    def test_night_is_zero(self):
        """Only GHI/DHI/DNI are irradiance (night-masked to 0); WS_10M
        is a plain meteorological quantity that doesn't stop at night."""
        night = self.zen >= NIGHT_ZENITH_DEG
        for name in ("GHI", "DHI", "DNI"):
            assert np.all(self.results[name][night] == 0.0), (
                f"COSMO-REA6 {name}: night values must be 0"
            )

    def test_energy_balance(self):
        """GHI == DHI + DNI * cos(zenith) for COSMO-REA6.

        Near-horizon points (zenith > 85 deg) are excluded because
        the DNI cos-guard (cos_z <= 0.087) intentionally sets DNI=0
        there to prevent divergence, which breaks the strict energy
        balance between 85 deg and 90 deg.
        """
        # 85 deg = arccos(0.087) — the cos-guard threshold
        strict = self.zen < 85.0
        cos_z = np.cos(np.radians(self.zen[strict]))
        ghi = self.results["GHI"][strict]
        dhi = self.results["DHI"][strict]
        dni = self.results["DNI"][strict]
        residual = np.abs(ghi - (dhi + dni * cos_z))
        assert np.all(residual < 5.0), (
            f"COSMO-REA6 balance failed: max residual "
            f"{residual.max():.2f} W/m2"
        )

    def test_output_length(self):
        for arr in self.results.values():
            assert len(arr) == N


# ---------------------------------------------------------------------------
# Class: MERRA-2 derivations (pvlib required)
# ---------------------------------------------------------------------------

pvlib = pytest.importorskip(
    "pvlib",
    reason="pvlib not installed — skipping DIRINT tests",
)


class TestMERRA2Derivations:
    """Tests for MERRA-2 GHI, DHI, DNI (via DIRINT), RH, WS_10M."""

    @pytest.fixture(autouse=True)
    def _compute(self, merra2_ds, sol_pos, times):
        self.results = apply_derived_fields(
            ds=merra2_ds,
            provider="MERRA2",
            sol_pos=sol_pos,
            times=times,
        )
        self.zen = sol_pos["zenith"]

    def test_keys_present(self):
        assert {"GHI", "DHI", "DNI", "RH", "WS_10M"} <= self.results.keys()

    def test_wind_speed(self):
        """WS_10M = sqrt(U10M**2 + V10M**2) = sqrt(3**2 + 4**2) = 5."""
        assert np.allclose(self.results["WS_10M"], 5.0)

    def test_rh_in_range(self):
        assert np.all((self.results["RH"] >= 0.0) & (self.results["RH"] <= 100.0))

    def test_no_negative_values(self):
        for name, arr in self.results.items():
            assert np.all(arr >= 0.0), (
                f"MERRA-2 {name} has negative values"
            )

    def test_night_is_zero(self):
        """Only GHI/DHI/DNI are irradiance (night-masked to 0); RH and
        WS_10M are plain meteorological quantities that don't stop at
        night."""
        night = self.zen >= NIGHT_ZENITH_DEG
        for name in ("GHI", "DHI", "DNI"):
            assert np.all(self.results[name][night] == 0.0), (
                f"MERRA-2 {name}: night values must be 0"
            )

    def test_energy_balance(self):
        """GHI ~ DHI + DNI * cos(zenith) within 5 W/m2."""
        day = self.zen < NIGHT_ZENITH_DEG
        cos_z = np.cos(np.radians(self.zen[day]))
        ghi = self.results["GHI"][day]
        dhi = self.results["DHI"][day]
        dni = self.results["DNI"][day]
        residual = np.abs(ghi - (dhi + dni * cos_z))
        assert np.all(residual < 5.0), (
            f"MERRA-2 balance failed: max residual "
            f"{residual.max():.2f} W/m2"
        )

    def test_output_length(self):
        for arr in self.results.values():
            assert len(arr) == N


# ---------------------------------------------------------------------------
# Class: ERA5-Land derivations (pvlib required)
# ---------------------------------------------------------------------------

class TestERA5LandDerivations:
    """Tests for ERA5-Land GHI, RH, WS_10M.

    DHI/DNI are not registered for ERA5-Land (see
    ``dni_pointwise.py`` for the opt-in point/region decomposition),
    so only GHI is night-masked/clipped here; RH and WS_10M are plain
    meteorological quantities, not irradiance.
    """

    @pytest.fixture(autouse=True)
    def _compute(self, era5_ds, sol_pos, times):
        self.results = apply_derived_fields(
            ds=era5_ds,
            provider="ERA5_LAND",
            sol_pos=sol_pos,
            times=times,
        )
        self.zen = sol_pos["zenith"]

    def test_keys_present(self):
        assert {"GHI", "RH", "WS_10M"} <= self.results.keys()

    def test_no_negative_values(self):
        for name, arr in self.results.items():
            assert np.all(arr >= 0.0), (
                f"ERA5-Land {name} has negative values"
            )

    def test_night_is_zero(self):
        night = self.zen >= NIGHT_ZENITH_DEG
        assert np.all(self.results["GHI"][night] == 0.0), (
            "ERA5-Land GHI: night values must be 0"
        )

    def test_output_length(self):
        for arr in self.results.values():
            assert len(arr) == N


# ---------------------------------------------------------------------------
# Class: Cross-provider dimensional alignment
# ---------------------------------------------------------------------------

class TestDimensionalAlignment:
    """All three providers must produce same-length outputs."""

    @pytest.fixture(autouse=True)
    def _compute_all(
        self, cosmo_ds, merra2_ds, era5_ds, sol_pos, times
    ):
        self.cosmo = apply_derived_fields(
            ds=cosmo_ds,
            provider="COSMO_REA6",
            sol_pos=sol_pos,
            times=times,
        )
        self.m2 = apply_derived_fields(
            ds=merra2_ds,
            provider="MERRA2",
            sol_pos=sol_pos,
            times=times,
        )
        self.e5 = apply_derived_fields(
            ds=era5_ds,
            provider="ERA5_LAND",
            sol_pos=sol_pos,
            times=times,
            fields=["GHI"],
        )

    def test_all_providers_same_length(self):
        lengths = {
            "COSMO_REA6": len(self.cosmo["GHI"]),
            "MERRA2": len(self.m2["GHI"]),
            "ERA5_LAND": len(self.e5["GHI"]),
        }
        assert len(set(lengths.values())) == 1, (
            f"GHI length mismatch across providers: {lengths}"
        )

    def test_all_providers_equal_n(self):
        assert len(self.cosmo["GHI"]) == N
        assert len(self.m2["GHI"]) == N
        assert len(self.e5["GHI"]) == N


# ---------------------------------------------------------------------------
# Class: apply_derived_fields error handling
# ---------------------------------------------------------------------------

class TestApplyDerivedFieldsErrors:
    """Verify that invalid inputs raise ValueError."""

    def test_unknown_provider(self, cosmo_ds, sol_pos, times):
        with pytest.raises(ValueError, match="Unknown provider"):
            apply_derived_fields(
                ds=cosmo_ds,
                provider="UNKNOWN",
                sol_pos=sol_pos,
                times=times,
            )

    def test_unknown_field(self, cosmo_ds, sol_pos, times):
        with pytest.raises(ValueError, match="not registered"):
            apply_derived_fields(
                ds=cosmo_ds,
                provider="COSMO_REA6",
                sol_pos=sol_pos,
                times=times,
                fields=["GHI", "INVALID"],
            )
