"""Tests for the KNMI validation tool.

All offline: the KNMI response format is exercised against a captured
sample rather than the live API, so the suite stays deterministic and
runnable without network access.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from weather.tests.validate_knmi import (
    VARIABLE_MAP,
    _md_table,
    _parse,
    _post_checked,
    lag_correlation,
    nearest_cell,
    paired_stats,
    sky_condition_bias,
    temporal_semantics,
)

# A faithful excerpt of a real response, including the station block and
# the '#'-prefixed column header the parser has to find.
SAMPLE = """\
# Opmerking: ...
#
# STN         LON(east)   LAT(north)  ALT(m)      NAME
# 240         4.790       52.318      -3.30       Schiphol Airport
# 260         5.180       52.100      1.90        De Bilt
# YYYYMMDD  : datum
# HH        : tijd
# STN,YYYYMMDD,HH,    Q,    T
  240,20180601,    1,    0,  157
  240,20180601,    2,   12,  150
  240,20180601,   24,   40,  162
  260,20180601,    1,    3,  147
  260,20180601,    2,   15,  140
"""


def test_parse_extracts_stations_and_coordinates() -> None:
    """Station coordinates come from the header, not a hardcoded table."""
    frame, stations = _parse(SAMPLE)

    assert set(stations) == {"240", "260"}
    assert stations["240"]["lat"] == pytest.approx(52.318)
    assert stations["240"]["lon"] == pytest.approx(4.790)
    assert stations["240"]["name"] == "Schiphol Airport"
    assert not frame.empty


def test_parse_uses_hour_ending_timestamps() -> None:
    """KNMI division HH covers (HH-1):00..HH:00, so stamp = date + HH.

    Getting this wrong shifts every irradiance value by an hour, which is
    the single most consequential mistake in the whole comparison.
    """
    frame, _ = _parse(SAMPLE)
    stamps = frame[frame["station"] == "240"].index

    assert stamps[0] == pd.Timestamp("2018-06-01 01:00")
    # HH=24 belongs to the following midnight, not to hour 0 of the day.
    assert pd.Timestamp("2018-06-02 00:00") in stamps


def test_parse_returns_empty_frame_without_header() -> None:
    """A body with no column header must not raise."""
    frame, stations = _parse("# just a comment\n")
    assert frame.empty
    assert stations == {}


def test_post_checked_rejects_html(monkeypatch: pytest.MonkeyPatch) -> None:
    """KNMI answers an over-large query with HTML and a 200 status.

    Unchecked, that parses to zero rows and fails much later with an
    unrelated dtype error -- so it must fail here, where the cause is
    visible.
    """
    monkeypatch.setattr(
        "weather.tests.validate_knmi._post",
        lambda payload, timeout=300: "<!DOCTYPE html>\n<html>oops</html>",
    )
    with pytest.raises(RuntimeError, match="HTML page instead of data"):
        _post_checked({"start": "a", "end": "b", "stns": "ALL"})


def test_pressure_is_excluded_from_the_variable_map() -> None:
    """KNMI's P is reduced to mean sea level; PS is surface pressure.

    Comparing them would report a large bias that means nothing.
    """
    assert "PS" not in VARIABLE_MAP


def test_relative_humidity_maps_to_u_not_rh() -> None:
    """KNMI's RH code is PRECIPITATION. Humidity is U."""
    assert VARIABLE_MAP["RH"][0] == "U"


def test_paired_stats_on_a_known_offset() -> None:
    """Bias/MAE/RMSE are exact for a constant offset."""
    index = pd.date_range("2018-01-01", periods=100, freq="h")
    observed = pd.Series(np.linspace(0, 99, 100), index=index)
    model = observed + 5.0

    stats = paired_stats(model, observed)

    assert stats["bias"] == pytest.approx(5.0)
    assert stats["mae"] == pytest.approx(5.0)
    assert stats["rmse"] == pytest.approx(5.0)
    assert stats["r"] == pytest.approx(1.0)
    assert stats["n"] == 100


def test_paired_stats_needs_enough_overlap() -> None:
    """Too few paired hours yields a count only, not fake statistics."""
    index = pd.date_range("2018-01-01", periods=5, freq="h")
    series = pd.Series(np.arange(5.0), index=index)
    assert set(paired_stats(series, series)) == {"n"}


def test_lag_correlation_finds_a_planted_shift() -> None:
    """A one-hour labelling error must show up as an off-zero peak.

    ``lag_correlation`` compares ``model[t]`` with ``observed[t - lag]``.
    A model series running one hour LATE therefore peaks at ``+1``.
    """
    index = pd.date_range("2018-06-01", periods=500, freq="h")
    signal = pd.Series(
        np.sin(np.arange(500) * 2 * np.pi / 24) + 1.0, index=index
    )
    late = signal.shift(1)

    correlations = lag_correlation(late, signal)
    assert max(correlations, key=lambda k: correlations[k]) == 1

    early = signal.shift(-1)
    correlations = lag_correlation(early, signal)
    assert max(correlations, key=lambda k: correlations[k]) == -1

    aligned = lag_correlation(signal, signal)
    assert max(aligned, key=lambda k: aligned[k]) == 0


def test_sky_condition_bias_separates_bins() -> None:
    """Binning must report distinct sky conditions with counts."""
    rng = np.random.default_rng(0)
    index = pd.date_range("2018-01-01", periods=24 * 200, freq="h")
    hour = index.hour.to_numpy()
    clear = np.clip(np.sin((hour - 6) * np.pi / 12), 0, None) * 800
    observed = pd.Series(clear * rng.uniform(0.1, 1.0, len(index)), index=index)
    model = observed * 0.9

    table = sky_condition_bias(model, observed)
    assert not table.empty
    assert set(table["sky"]) <= {"overcast", "broken", "hazy", "clear"}
    assert (table["n"] > 0).all()


def test_temporal_semantics_detects_instantaneous_series() -> None:
    """A series sampled at the stamp must not be read as a period mean."""
    index = pd.date_range("2018-06-01", periods=24 * 120, freq="h")
    hour = index.hour.to_numpy()
    instantaneous = pd.Series(
        np.clip(np.sin((hour - 6) * np.pi / 12), 0, None) * 700.0, index=index
    )
    # An hourly-mean observation is the average over (t-1h, t].
    hourly_mean = (instantaneous + instantaneous.shift(1)) / 2.0

    result = temporal_semantics(instantaneous, hourly_mean.dropna())
    assert result["verdict_instantaneous"] == 1.0


def test_nearest_cell_handles_curvilinear_and_regular_grids() -> None:
    """COSMO is 2-D curvilinear; ERA5-Land/MERRA-2 are 1-D regular."""
    lat2d = np.linspace(50, 53, 4)[:, None] * np.ones((1, 5))
    lon2d = np.ones((4, 1)) * np.linspace(3, 7, 5)[None, :]
    curvilinear = xr.Dataset(
        coords={
            "latitude": (("y", "x"), lat2d),
            "longitude": (("y", "x"), lon2d),
        }
    )
    iy, ix, distance = nearest_cell(curvilinear, 53.0, 7.0)
    assert (iy, ix) == (3, 4)
    assert distance == pytest.approx(0.0, abs=1e-6)

    regular = xr.Dataset(
        coords={
            "latitude": ("y", np.linspace(50, 53, 4)),
            "longitude": ("x", np.linspace(3, 7, 5)),
        }
    )
    iy, ix, _ = nearest_cell(regular, 50.0, 3.0)
    assert (iy, ix) == (0, 0)


def test_md_table_columns_align() -> None:
    """markdownlint MD060 requires every '|' to line up across rows."""
    frame = pd.DataFrame(
        {"variable": ["GHI", "T"], "bias": [-12.875, 0.1]}
    )
    lines = _md_table(frame).splitlines()

    positions = [
        [i for i, ch in enumerate(line) if ch == "|"] for line in lines
    ]
    assert all(p == positions[0] for p in positions), lines
    assert len(lines) == 4  # header, separator, two rows


def test_provider_output_dir_accepts_both_spellings() -> None:
    """The --provider path was broken until 2026-08-26.

    ``registry.get_provider()`` returns a provider OBJECT, not the
    module, so the original ``module.get_config()`` raised
    AttributeError for every provider -- only the ``--file`` path had
    ever been exercised.
    """
    from weather.tests.validate_knmi import (
        PROVIDER_OUTPUT_DIR_GETTERS,
        provider_output_dir,
    )

    assert set(PROVIDER_OUTPUT_DIR_GETTERS) == {
        "cosmo-rea6", "era5-land", "merra-2",
    }
    for name in ("era5-land", "era5_land", "ERA5-Land"):
        assert provider_output_dir(name) == provider_output_dir("era5-land")


def test_provider_output_dir_rejects_unknown() -> None:
    """An unknown provider must name the valid options."""
    from weather.tests.validate_knmi import provider_output_dir

    with pytest.raises(ValueError, match="unknown provider"):
        provider_output_dir("not-a-provider")


def test_match_distance_scales_with_grid_spacing() -> None:
    """A fixed tolerance excluded EVERY station on MERRA-2.

    Its 0.5 x 0.625 deg cells are ~55 x 43 km at Dutch latitudes, so no
    station centre can be within the old hardcoded 15 km and the tool
    wrongly reported "no station in domain" for a good archive.
    """
    from weather.tests.validate_knmi import (
        default_match_distance_km,
        grid_spacing_km,
    )

    fine = xr.Dataset(
        coords={
            "latitude": ("y", np.arange(50.0, 54.0, 0.055)),
            "longitude": ("x", np.arange(3.0, 8.0, 0.055)),
        }
    )
    coarse = xr.Dataset(
        coords={
            "latitude": ("y", np.arange(50.0, 54.0, 0.5)),
            "longitude": ("x", np.arange(3.0, 8.0, 0.625)),
        }
    )

    assert grid_spacing_km(fine) < grid_spacing_km(coarse)
    # COSMO-scale ~6 km cells stay a tight match...
    assert default_match_distance_km(fine) < 15
    # ...while MERRA-2-scale cells admit the stations they must.
    assert default_match_distance_km(coarse) > 25


def test_half_hour_stamps_are_snapped_to_hour_ending() -> None:
    """MERRA-2 stamps at HH:30; KNMI on the hour. Unaligned, NO pair matches.

    The first MERRA-2 run failed exactly this way and misreported it as
    "no station in domain".
    """
    from weather.tests.validate_knmi import align_to_hour_ending

    index = pd.DatetimeIndex(
        pd.date_range("2018-01-01 00:30", periods=5, freq="h")
    )
    aligned, shift = align_to_hour_ending(index)

    assert shift == 30
    assert aligned[0] == pd.Timestamp("2018-01-01 01:00")
    assert (aligned.minute == 0).all()


def test_on_the_hour_stamps_are_left_alone() -> None:
    """COSMO/ERA5-Land already sit on the hour and must not be shifted."""
    from weather.tests.validate_knmi import align_to_hour_ending

    index = pd.DatetimeIndex(
        pd.date_range("2018-01-01 01:00", periods=5, freq="h")
    )
    aligned, shift = align_to_hour_ending(index)

    assert shift == 0
    assert aligned.equals(index)


def test_mixed_minute_offsets_are_not_shifted() -> None:
    """An irregular axis is left untouched rather than guessed at."""
    from weather.tests.validate_knmi import align_to_hour_ending

    index = pd.DatetimeIndex(
        ["2018-01-01 00:30", "2018-01-01 01:15", "2018-01-01 02:00"]
    )
    aligned, shift = align_to_hour_ending(index)

    assert shift == 0
    assert aligned.equals(index)
