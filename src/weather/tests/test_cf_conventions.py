"""Tests for the shared CF metadata pass (``common/cf_conventions.py``).

Covers the two gaps closed on 2026-08-24 -- absent global attributes and
three actively wrong ``standard_name`` values inherited from cfgrib --
plus the provider-specific wind handling, which is the one rule that
must NOT be applied uniformly across providers.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from weather.common.cf_conventions import (
    CF_STANDARD_NAMES,
    PROVIDER_METADATA,
    STALE_GRIB_GRID_ATTRS,
    attach_cf_metadata,
    attach_cf_variable_attrs,
    attach_global_attrs,
)

PROVIDERS = ("cosmo_rea6", "era5_land", "merra2")


def _dataset() -> xr.Dataset:
    """Build a small dataset shaped like real COSMO output.

    Deliberately seeded with the exact wrong metadata cfgrib produces, so
    the tests assert on correction, not merely on addition.
    """
    times = pd.date_range("2018-01-01 01:00", periods=4, freq="h")
    ny, nx = 3, 4
    lat = np.linspace(50.0, 53.0, ny)[:, None] * np.ones((1, nx))
    lon = np.ones((ny, 1)) * np.linspace(3.0, 7.0, nx)[None, :]
    names = (
        "T", "T_DEW", "GHI", "DHI", "DNI", "WS_10M", "U_10M", "V_10M",
        "RH", "PS", "ALBEDO", "SNOW_DEPTH", "SNOWFALL",
    )
    ds = xr.Dataset(
        {n: (("time", "y", "x"), np.zeros((4, ny, nx), dtype="f4")) for n in names},
        coords={
            "time": times,
            "latitude": (("y", "x"), lat),
            "longitude": (("y", "x"), lon),
        },
    )
    ds["time"].attrs["standard_name"] = "forecast_reference_time"
    ds["SNOW_DEPTH"].attrs["standard_name"] = "lwe_thickness_of_surface_snow_amount"
    ds["U_10M"].attrs["standard_name"] = "eastward_wind"
    ds["V_10M"].attrs["standard_name"] = "northward_wind"
    ds["T"].attrs.update(
        {
            "GRIB_Nx": 848,
            "GRIB_Ny": 824,
            "GRIB_numberOfPoints": 698752,
            "GRIB_shortName": "2t",
            "GRIB_latitudeOfSouthernPoleInDegrees": -39.25,
        }
    )
    return ds


@pytest.mark.parametrize("provider", PROVIDERS)
def test_global_attrs_written(provider: str) -> None:
    """Every provider gets a populated CF-1.8 global attribute set."""
    ds = _dataset()
    assert ds.attrs == {}
    attach_global_attrs(ds, provider, region="Netherlands (NL)")

    assert ds.attrs["Conventions"] == "CF-1.8"
    for key in ("title", "institution", "source", "references", "comment",
                "history", "crop_region"):
        assert ds.attrs[key], f"{provider}: {key} empty"
    assert ds.attrs["time_coverage_start"] == "2018-01-01T01:00:00Z"
    assert ds.attrs["time_coverage_end"] == "2018-01-01T04:00:00Z"
    assert ds.attrs["time_coverage_resolution"] == "PT1H"


@pytest.mark.parametrize("provider", PROVIDERS)
def test_bounds_derived_from_data(provider: str) -> None:
    """Spatial bounds come from the array, so they cannot drift from it.

    The shipped-file bug this guards against was metadata describing a
    698752-point grid on a 2800-point file.
    """
    ds = _dataset()
    attach_global_attrs(ds, provider)
    assert ds.attrs["geospatial_lat_min"] == pytest.approx(50.0)
    assert ds.attrs["geospatial_lat_max"] == pytest.approx(53.0)
    assert ds.attrs["geospatial_lon_min"] == pytest.approx(3.0)
    assert ds.attrs["geospatial_lon_max"] == pytest.approx(7.0)
    assert ds.attrs["geospatial_bounds_crs"] == "EPSG:4326"


@pytest.mark.parametrize("provider", PROVIDERS)
def test_wrong_cfgrib_labels_corrected(provider: str) -> None:
    """The three wrong cfgrib ``standard_name`` values are fixed."""
    ds = _dataset()
    attach_cf_variable_attrs(ds, provider)

    # forecast_reference_time is explicitly NOT the validity time.
    assert ds["time"].attrs["standard_name"] == "time"
    assert ds["time"].attrs["axis"] == "T"
    # COSMO H_SNOW / ERA5-Land sde / MERRA-2 SNODP are physical depth.
    assert ds["SNOW_DEPTH"].attrs["standard_name"] == "surface_snow_thickness"


def test_rotated_wind_names_removed_for_cosmo() -> None:
    """COSMO wind is grid-relative, so geographic names must be removed."""
    ds = _dataset()
    attach_cf_variable_attrs(ds, "cosmo_rea6")

    for comp in ("U_10M", "V_10M"):
        assert "standard_name" not in ds[comp].attrs, (
            f"{comp} kept a geographic standard_name on a rotated grid"
        )
        assert "rotat" in ds[comp].attrs["comment"].lower()
    # The magnitude is rotation-invariant and stays labelled.
    assert ds["WS_10M"].attrs["standard_name"] == "wind_speed"


@pytest.mark.parametrize("provider", ("era5_land", "merra2"))
def test_geographic_wind_names_kept_for_regular_grids(provider: str) -> None:
    """ERA5-Land/MERRA-2 winds ARE true east/north -- keep the names."""
    ds = _dataset()
    attach_cf_variable_attrs(ds, provider)
    assert ds["U_10M"].attrs["standard_name"] == "eastward_wind"
    assert ds["V_10M"].attrs["standard_name"] == "northward_wind"
    assert "comment" not in ds["U_10M"].attrs


@pytest.mark.parametrize("provider", PROVIDERS)
def test_stale_grid_attrs_dropped_provenance_kept(provider: str) -> None:
    """Source-grid extent is dropped; parameter provenance survives."""
    ds = _dataset()
    attach_cf_variable_attrs(ds, provider)

    for stale in STALE_GRIB_GRID_ATTRS:
        assert stale not in ds["T"].attrs
    assert ds["T"].attrs["GRIB_shortName"] == "2t"
    # The rotated-pole definition stays true for a subset of the grid.
    assert ds["T"].attrs["GRIB_latitudeOfSouthernPoleInDegrees"] == -39.25


def test_snowfall_left_without_standard_name() -> None:
    """SNOWFALL's kg/m^2/h does not match snowfall_amount's kg m-2.

    Leaving it unset keeps the file passing a strict CF check; asserting
    the name would make it fail one.
    """
    ds = _dataset()
    attach_cf_variable_attrs(ds, "cosmo_rea6")
    assert "standard_name" not in ds["SNOWFALL"].attrs
    assert ds["SNOWFALL"].attrs["cell_methods"] == "time: sum (interval: 1 hour)"


def test_cell_methods_reflect_what_was_measured() -> None:
    """Each provider's GHI semantics were established, not guessed.

    Measured 2026-08-26 against KNMI (weather.tests.validate_knmi):
    COSMO 100% of stations instantaneous, ERA5-Land 89% hourly mean.
    MERRA-2 is declared from NASA's time-averaged M2T1NX collection
    definition (the KNMI test agreed only weakly, 53%).
    """
    cosmo = _dataset()
    attach_cf_variable_attrs(cosmo, "cosmo_rea6")
    assert cosmo["GHI"].attrs["cell_methods"] == "time: point"

    for provider in ("era5_land", "merra2"):
        ds = _dataset()
        attach_cf_variable_attrs(ds, provider)
        assert ds["GHI"].attrs["cell_methods"] == "time: mean"


def test_unmeasured_variables_get_no_cell_methods() -> None:
    """ERA5-Land/MERRA-2 are MIXED and only radiation was measured.

    Their 2 m temperature and wind are almost certainly instantaneous
    analysis fields, but "almost certainly" is not a basis for a CF
    attribute an external consumer will trust.
    """
    for provider in ("era5_land", "merra2"):
        ds = _dataset()
        attach_cf_variable_attrs(ds, provider)
        for name in ("T", "WS_10M", "RH"):
            assert "cell_methods" not in ds[name].attrs, (provider, name)

    # COSMO was measured across the board and does declare them.
    cosmo = _dataset()
    attach_cf_variable_attrs(cosmo, "cosmo_rea6")
    assert cosmo["T"].attrs["cell_methods"] == "time: point"


@pytest.mark.parametrize("provider", PROVIDERS)
def test_attach_cf_metadata_is_idempotent(provider: str) -> None:
    """Re-running the pass changes nothing except the history stamp."""
    ds = _dataset()
    attach_cf_metadata(ds, provider, region="Netherlands (NL)")
    first = {k: dict(ds[k].attrs) for k in ds.variables}
    attrs_first = {k: v for k, v in ds.attrs.items() if k != "history"}

    attach_cf_metadata(ds, provider, region="Netherlands (NL)")
    second = {k: dict(ds[k].attrs) for k in ds.variables}
    attrs_second = {k: v for k, v in ds.attrs.items() if k != "history"}

    assert first == second
    assert attrs_first == attrs_second


@pytest.mark.parametrize("provider", PROVIDERS)
def test_latlon_attrs_attached(provider: str) -> None:
    """The full pass also restores the CF lat/lon identity attributes."""
    ds = _dataset()
    attach_cf_metadata(ds, provider)
    assert ds["latitude"].attrs["standard_name"] == "latitude"
    assert ds["latitude"].attrs["units"] == "degrees_north"
    assert ds["longitude"].attrs["units"] == "degrees_east"


def test_extra_overrides_computed_attrs() -> None:
    """Caller-supplied extras win, so a caller can always correct us."""
    ds = _dataset()
    attach_global_attrs(ds, "cosmo_rea6", extra={"institution": "Enerplanet"})
    assert ds.attrs["institution"] == "Enerplanet"


def test_every_provider_declares_required_keys() -> None:
    """Guards against a new provider being added half-configured."""
    for provider, meta in PROVIDER_METADATA.items():
        for key in ("title", "institution", "source", "references",
                    "wind_is_grid_relative", "time_convention"):
            assert key in meta, f"{provider} missing {key}"
        assert isinstance(meta["wind_is_grid_relative"], bool)


def test_standard_names_are_not_empty() -> None:
    """A typo'd empty mapping would silently disable the whole pass."""
    assert CF_STANDARD_NAMES
    assert all(v and isinstance(v, str) for v in CF_STANDARD_NAMES.values())


def test_invalid_standard_names_are_stripped() -> None:
    """Placeholder and free-text labels make a CF check FAIL; drop them.

    Real values found in production on 2026-08-24: ERA5-Land wrote the
    literal ``"unknown"``, MERRA-2 carried NASA's own descriptive labels.
    """
    ds = _dataset()
    ds["GHI"].attrs["standard_name"] = "unknown"
    ds["PS"].attrs["standard_name"] = "surface_pressure"
    ds["T"].attrs["standard_name"] = "2-meter_air_temperature"
    attach_cf_variable_attrs(ds, "merra2")

    # All three are in the mapping, so they get the CORRECT name.
    assert ds["GHI"].attrs["standard_name"] == CF_STANDARD_NAMES["GHI"]
    assert ds["PS"].attrs["standard_name"] == "surface_air_pressure"
    assert ds["T"].attrs["standard_name"] == "air_temperature"


def test_unmapped_variable_with_invalid_name_loses_it() -> None:
    """A variable we have no CF name for must not keep a bogus one."""
    ds = _dataset()
    ds["mystery"] = ds["T"].copy()
    ds["mystery"].attrs["standard_name"] = "unknown"
    attach_cf_variable_attrs(ds, "era5_land")
    assert "standard_name" not in ds["mystery"].attrs


def test_valid_unmapped_name_is_preserved() -> None:
    """The stripper is conservative: real CF names survive untouched."""
    ds = _dataset()
    ds["other"] = ds["T"].copy()
    ds["other"].attrs["standard_name"] = "lwe_thickness_of_snowfall_amount"
    attach_cf_variable_attrs(ds, "era5_land")
    assert (
        ds["other"].attrs["standard_name"]
        == "lwe_thickness_of_snowfall_amount"
    )


@pytest.mark.parametrize("provider", PROVIDERS)
def test_license_and_attribution_written(provider: str) -> None:
    """Every provider declares a licence and an attribution notice.

    Verified against each upstream's own statement on 2026-08-26:
    DWD's ``REA/Terms_of_use.txt`` (CC BY 4.0), the Licence to Use
    Copernicus Products sec 5.1.2, and NASA ESDIS's open-data policy.
    """
    ds = _dataset()
    attach_global_attrs(ds, provider)

    assert ds.attrs["license"]
    assert ds.attrs["attribution"]


def test_dwd_attribution_uses_the_modified_data_template() -> None:
    """CC BY 4.0 obliges a Quellenvermerk.

    DWD's templates page gives "Quelle: Deutscher Wetterdienst" for
    UNCHANGED data and the "Datenbasis: ..." form once it is processed.
    This pipeline derives fields and subsets, so it must use the latter.
    """
    ds = _dataset()
    attach_global_attrs(ds, "cosmo_rea6")

    assert ds.attrs["attribution"].startswith("Datenbasis: Deutscher Wetterdienst")
    assert "CC BY 4.0" in ds.attrs["license"]


def test_copernicus_notice_carries_the_data_year() -> None:
    """Licence sec 5.1.2 wants the year inside the notice itself."""
    ds = _dataset()  # time axis starts 2018-01-01
    attach_global_attrs(ds, "era5_land")

    assert (
        ds.attrs["attribution"].startswith(
            "Contains modified Copernicus Climate Change Service "
            "information 2018"
        )
    ), ds.attrs["attribution"]
    assert "{year}" not in ds.attrs["attribution"]


def test_year_placeholder_resolves_for_every_provider() -> None:
    """An unresolved {year} would ship a literal placeholder to users."""
    for provider in PROVIDERS:
        ds = _dataset()
        attach_global_attrs(ds, provider)
        assert "{year}" not in ds.attrs["attribution"], provider


def test_repair_preserves_a_per_file_title(tmp_path) -> None:
    """An archive sweep must not flatten a customised title.

    The first licence sweep overwrote the shipped Netherlands file's
    "... , Netherlands, 2018" title with the generic provider one.
    """
    import netCDF4

    from weather.common.metadata_repair import repair_metadata

    path = tmp_path / "custom.nc"
    ds = netCDF4.Dataset(path, "w", format="NETCDF4")
    ds.createDimension("time", 2)
    tv = ds.createVariable("time", "f8", ("time",))
    tv.units = "seconds since 1970-01-01"
    tv[:] = [0.0, 3600.0]
    ds.setncattr("title", "COSMO-REA6 hourly surface weather, Netherlands, 2018")
    ds.setncattr("summary", "A specific summary.")
    ds.close()

    repair_metadata(path, "cosmo_rea6")

    ds = netCDF4.Dataset(path)
    assert ds.title == "COSMO-REA6 hourly surface weather, Netherlands, 2018"
    assert ds.summary == "A specific summary."
    assert "CC BY 4.0" in ds.license  # the sweep still did its job
    ds.close()


def test_repair_sets_title_when_absent(tmp_path) -> None:
    """Preservation must not stop a missing title from being filled."""
    import netCDF4

    from weather.common.metadata_repair import repair_metadata

    path = tmp_path / "bare.nc"
    ds = netCDF4.Dataset(path, "w", format="NETCDF4")
    ds.createDimension("time", 1)
    tv = ds.createVariable("time", "f8", ("time",))
    tv.units = "seconds since 1970-01-01"
    tv[:] = [0.0]
    ds.close()

    repair_metadata(path, "merra2")

    ds = netCDF4.Dataset(path)
    assert ds.title == PROVIDER_METADATA["merra2"]["title"]
    ds.close()
