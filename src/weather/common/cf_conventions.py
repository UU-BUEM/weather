"""Shared CF-Conventions metadata helpers.

Single-sourced across all three providers, since the same gap was found
independently in all three: each provider's ``transform.py`` re-attaches
``latitude``/``longitude`` as coordinates via ``xr.Dataset.assign_coords``
(either directly building the 2-D COSMO auxiliary coordinates, or, for
ERA5-Land/MERRA-2, restashing 1-D values after renaming their original
dims to ``y``/``x`` for cross-provider parity) -- ``assign_coords`` builds
a fresh coordinate variable with NO attributes, discarding whatever
``standard_name``/``units`` the source data may have carried.

This is invisible to xarray/``weather.point_query`` (both match by
variable name, not CF role), but breaks any stricter CF-aware external
tool -- confirmed via a real ``cdo sellonlatbox`` run against already-
exported COSMO and MERRA-2 files: with only ``_FillValue`` set on
``latitude``/``longitude``, cdo logged ``Coordinates variable latitude
can't be assigned!``, fell back to ``gridtype = generic`` (no lon/lat
semantics at all), and ``sellonlatbox`` aborted outright (``Unsupported
grid type: generic`` / ``No processable variable found!``). Each
provider's data variables already correctly declare their
``coordinates`` attribute (e.g. ``"latitude longitude"``) -- only the
coordinate variables' own identifying attributes were missing.
"""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    import xarray


def attach_cf_latlon_attrs(ds: xarray.Dataset) -> None:
    """Attach ``standard_name``/``units`` to *ds*'s ``latitude``/
    ``longitude`` coordinates, in place.

    Works identically for 1-D (ERA5-Land/MERRA-2, dims ``(y,)``/``(x,)``)
    and 2-D (COSMO-REA6, dims ``(y, x)``) coordinates -- attribute
    assignment doesn't depend on dimensionality, only the variable
    itself, so one implementation covers all three providers.

    Parameters
    ----------
    ds : xarray.Dataset
        Must already have ``latitude``/``longitude`` coordinates
        assigned (e.g. via ``assign_coords``) -- this only attaches
        metadata, it does not compute or assign the coordinates
        themselves.
    """
    ds["latitude"].attrs = {
        "standard_name": "latitude",
        "long_name": "latitude",
        "units": "degrees_north",
    }
    ds["longitude"].attrs = {
        "standard_name": "longitude",
        "long_name": "longitude",
        "units": "degrees_east",
    }


# ---------------------------------------------------------------------------
# CF standard names, cell methods and global attributes
# ---------------------------------------------------------------------------
#
# Both of the gaps this section closes were found while preparing a real
# COSMO-REA6 file for an external consumer (2026-08-24), and both affect
# ALL THREE providers, not just the file that surfaced them:
#
#   1. No provider's ``export.py`` ever wrote a single global attribute.
#      Every one of the 296 COSMO monthly files on ``sd26`` has an empty
#      global attribute set -- no ``Conventions``, no ``source``, no
#      provenance whatsoever.
#   2. Three ``standard_name`` values were inherited verbatim from cfgrib
#      and are actively WRONG.  All 296 files carry all three.  Each was
#      checked against the official CF standard name table rather than
#      assumed:
#        * ``time`` was ``forecast_reference_time``, whose CF definition
#          states outright "It is not the time for which the forecast is
#          valid".  This axis IS validity time.
#        * ``SNOW_DEPTH`` was ``lwe_thickness_of_surface_snow_amount``
#          (liquid water equivalent).  COSMO's ``H_SNOW`` -- like
#          ERA5-Land's ``sde`` and MERRA-2's ``SNODP`` -- is PHYSICAL
#          depth.  This is the same ``sd``-vs-``sde`` confusion already
#          corrected for ERA5-Land on 2026-07-30, in CF form.
#        * ``U_10M``/``V_10M`` were ``eastward_wind``/``northward_wind``
#          on COSMO, whose rotated-pole grid reports wind relative to the
#          GRID axes (``GRIB_uvRelativeToGrid=1``), not true east/north.
#          ERA5-Land and MERRA-2 are on regular lat/lon grids where those
#          names ARE correct, so this one is provider-specific -- see
#          ``wind_is_grid_relative`` below.
#
# Convention #2 (extensibility via DICTs): adding a variable or a
# provider is a data edit here, not a code change.

#: CF standard names for this repo's unified variable names.  Every entry
#: was validated against the official CF standard name table.  Variables
#: absent from this mapping are deliberately left without a
#: ``standard_name`` -- notably ``SNOWFALL``, an hourly accumulation
#: labelled ``kg/m^2/h``, which does not match ``snowfall_amount``'s
#: canonical ``kg m-2``; asserting it would make the file fail a strict
#: CF check rather than pass one.
CF_STANDARD_NAMES: dict[str, str] = {
    "T": "air_temperature",
    "T_DEW": "dew_point_temperature",
    "GHI": "surface_downwelling_shortwave_flux_in_air",
    "DHI": "surface_diffuse_downwelling_shortwave_flux_in_air",
    "DNI": "surface_direct_along_beam_shortwave_flux_in_air",
    "WS_10M": "wind_speed",
    "RH": "relative_humidity",
    "PS": "surface_air_pressure",
    "ALBEDO": "surface_albedo",
    "SNOW_DEPTH": "surface_snow_thickness",
    "QV2M": "specific_humidity",
    "QV_2M": "specific_humidity",
}

#: Names that are correct ONLY when the wind components are true
#: geographic components (regular lat/lon grids).
GEOGRAPHIC_WIND_NAMES: dict[str, str] = {
    "U_10M": "eastward_wind",
    "V_10M": "northward_wind",
    "U_2M": "eastward_wind",
    "V_2M": "northward_wind",
    "U_50M": "eastward_wind",
    "V_50M": "northward_wind",
}

#: GRIB attributes describing the SOURCE grid's extent.  They survive
#: cropping unchanged and then describe a grid the file no longer has --
#: e.g. ``GRIB_Nx=848``/``GRIB_Ny=824``/``GRIB_numberOfPoints=698752`` on
#: a 56x50 Netherlands crop.  The rotated-pole definition (pole location,
#: grid increments) is NOT listed here: it stays true for a subset.
STALE_GRIB_GRID_ATTRS: tuple[str, ...] = (
    "GRIB_Nx",
    "GRIB_Ny",
    "GRIB_numberOfPoints",
    "GRIB_latitudeOfFirstGridPointInDegrees",
    "GRIB_latitudeOfLastGridPointInDegrees",
    "GRIB_longitudeOfFirstGridPointInDegrees",
    "GRIB_longitudeOfLastGridPointInDegrees",
    "GRIB_iScansNegatively",
    "GRIB_jScansPositively",
    "GRIB_jPointsAreConsecutive",
    "GRIB_NV",
    "GRIB_missingValue",
)

#: ``standard_name`` values that are not in the CF table at all and so
#: make a file FAIL a CF check rather than pass one.  Real examples found
#: in the production archives on 2026-08-24: ERA5-Land wrote the literal
#: string ``"unknown"`` on six variables, and MERRA-2 carried NASA's own
#: descriptive labels (``2-meter_air_temperature``, ``surface_pressure``,
#: ``snow_depth``, ``snowfall_land``, ...).  These are stripped rather
#: than guessed at: a variable with no ``standard_name`` falls back to
#: ``long_name`` and its variable name, which is honest; one with an
#: invented name is silently wrong.
INVALID_STANDARD_NAME_MARKERS: tuple[str, ...] = (
    "unknown",
    "unspecified",
    "n/a",
    "none",
)


def is_invalid_standard_name(value: str) -> bool:
    """Return True when *value* cannot be a CF standard name.

    Only catches the two families actually observed -- placeholder words
    and free-text labels containing characters CF names never use
    (digits, spaces, hyphens, slashes).  It is deliberately conservative:
    a name it does not recognise as invalid is left alone.
    """
    text = str(value).strip().lower()
    if not text or text in INVALID_STANDARD_NAME_MARKERS:
        return True
    return any(ch.isdigit() or ch in " -/" for ch in text)


WIND_ROTATION_COMMENT = (
    "Relative to the ROTATED-POLE grid axes (GRIB_uvRelativeToGrid=1), "
    "NOT true east/north. De-rotate before using as geographic "
    "components. WS_10M (the magnitude) is rotation-invariant."
)

#: Per-provider metadata.  ``cell_methods`` is only populated where the
#: temporal semantics have actually been VERIFIED against an independent
#: measurement -- currently COSMO-REA6 only, via the KNMI pyranometer
#: comparison in ``docs/dni_methodology.md`` sec 11.3, which showed its
#: radiation fields track the instantaneous value at the stamp rather
#: than the hourly mean.  ERA5-Land's GHI derives from the ``ssrd``
#: accumulation and MERRA-2's from time-averaged ``SWGDN``, so they are
#: almost certainly period means -- but "almost certainly" is not a basis
#: for stamping a CF attribute an external consumer will trust, so they
#: are left unset until measured the same way.
PROVIDER_METADATA: dict[str, dict] = {
    "cosmo_rea6": {
        "title": "COSMO-REA6 hourly surface weather",
        "institution": "Utrecht University (UU-BUEM)",
        "source": (
            "DWD COSMO-REA6 regional reanalysis, hourly 2D fields, "
            "rotated-pole grid at 0.055 deg (~6 km); retrieved from "
            "https://opendata.dwd.de/climate_environment/REA/ and "
            "processed by the UU-BUEM 'weather' package."
        ),
        "references": (
            "Bollmeyer, C., et al. (2015). Towards a high-resolution "
            "regional reanalysis for the European CORDEX domain. "
            "Q. J. R. Meteorol. Soc., 141(686), 1-15. "
            "https://doi.org/10.1002/qj.2486"
        ),
        # DWD publishes the REA archive under CC BY 4.0, confirmed from
        # the server's own machine-readable statement (2026-08-26):
        # opendata.dwd.de/climate_environment/REA/Terms_of_use.txt --
        # "The Creative Commons BY 4.0 - Licence 'CC BY 4.0' apply.
        # For detailed information see https://www.dwd.de/copyright"
        # (status May 2024; the German Nutzungsbedingungen agree).
        "license": (
            "CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/). "
            "Source data (c) Deutscher Wetterdienst (DWD)."
        ),
        # CC BY 4.0 obliges a "Quellenvermerk". DWD's own templates page
        # (dwd.de/DE/service/rechtliche_hinweise/vorlagen_quellenangabe)
        # gives "Quelle: Deutscher Wetterdienst" for UNCHANGED data and
        # the "Datenbasis: Deutscher Wetterdienst, <what was done>" form
        # once the data has been processed. This pipeline converts units,
        # derives GHI/DHI/DNI/RH/T_DEW/ALBEDO/SNOWFALL and subsets in
        # space, so the modified form is the applicable one.
        "attribution": (
            "Datenbasis: Deutscher Wetterdienst, eigene Bearbeitung. "
            "Source: Deutscher Wetterdienst (DWD), COSMO-REA6; modified "
            "by the UU-BUEM 'weather' package (unit conversion, derived "
            "radiation and humidity fields, spatial subsetting). DWD "
            "does not warrant the correctness of this derived product."
        ),
        "wind_is_grid_relative": True,
        "time_convention": (
            "Timestamps are hour-ENDING and in UTC: the stamp "
            "2018-06-01T12:00Z labels the interval 11:00-12:00Z."
        ),
        "cell_methods": {
            "T": "time: point",
            "T_DEW": "time: point",
            "GHI": "time: point",
            "DHI": "time: point",
            "DNI": "time: point",
            "WS_10M": "time: point",
            "U_10M": "time: point",
            "V_10M": "time: point",
            "RH": "time: point",
            "PS": "time: point",
            "ALBEDO": "time: point",
            "SNOW_DEPTH": "time: point",
            "SNOWFALL": "time: sum (interval: 1 hour)",
        },
        "extra": {
            "instantaneous_note": (
                "Radiation, temperature, humidity, pressure, wind and "
                "snow depth are INSTANTANEOUS values at the timestamp "
                "(cell_methods 'time: point'), not hourly means; "
                "SNOWFALL is the accumulation over the preceding hour. "
                "Integrate sub-daily profiles trapezoidally rather than "
                "treating each value as an hour-mean. Annual totals are "
                "unaffected (both series endpoints are night). Verified "
                "against KNMI pyranometer data -- see "
                "docs/dni_methodology.md sec 11.3."
            ),
        },
    },
    "era5_land": {
        "title": "ERA5-Land hourly surface weather",
        "institution": "Utrecht University (UU-BUEM)",
        "source": (
            "Copernicus Climate Data Store ERA5-Land reanalysis, hourly, "
            "0.1 deg regular lat/lon grid; processed by the UU-BUEM "
            "'weather' package. Contains modified Copernicus Climate "
            "Change Service information."
        ),
        "references": (
            "Munoz-Sabater, J., et al. (2021). ERA5-Land: a "
            "state-of-the-art global reanalysis dataset for land "
            "applications. Earth Syst. Sci. Data, 13(9), 4349-4383. "
            "https://doi.org/10.5194/essd-13-4349-2021"
        ),
        # Licence to Use Copernicus Products, section 5.1.2: a product
        # adapted or modified from C3S information must carry the notice
        # below. The {year} placeholder is filled from the file's own
        # time coverage by attach_global_attrs.
        "license": (
            "Licence to Use Copernicus Products "
            "(https://apps.ecmwf.int/datasets/licences/copernicus/). "
            "Free to use with attribution."
        ),
        "attribution": (
            "Contains modified Copernicus Climate Change Service "
            "information {year}. Neither the European Commission nor "
            "ECMWF is responsible for any use of this derived product."
        ),
        "wind_is_grid_relative": False,
        "time_convention": "Timestamps are in UTC.",
        # MEASURED 2026-08-26 against 28 KNMI pyranometer stations
        # (weather.tests.validate_knmi): 89% of stations indicate GHI is
        # the mean over the preceding hour, not the instantaneous value
        # at the stamp -- consistent with its derivation from the
        # `ssrd` accumulation. Only GHI is declared: ERA5-Land is MIXED
        # (its 2 m temperature, wind and pressure are instantaneous
        # analysis fields), and only the radiation was measured, so
        # nothing is asserted for the rest.
        "cell_methods": {"GHI": "time: mean"},
        "extra": {
            "radiation_note": (
                "GHI is the MEAN over the preceding hour "
                "(cell_methods 'time: mean'), verified against 28 KNMI "
                "pyranometer stations. Rectangle integration is "
                "therefore correct; no trapezoidal correction is "
                "needed. Temperature, wind and pressure are "
                "instantaneous analysis fields, but that was not "
                "measured here and is deliberately not declared."
            ),
        },
    },
    "merra2": {
        "title": "MERRA-2 hourly surface weather",
        "institution": "Utrecht University (UU-BUEM)",
        "source": (
            "NASA GES DISC MERRA-2 reanalysis (M2T1NXSLV / M2T1NXRAD / "
            "M2T1NXLND), hourly, 0.5 x 0.625 deg regular lat/lon grid, "
            "retrieved via OPeNDAP; processed by the UU-BUEM 'weather' "
            "package."
        ),
        "references": (
            "Gelaro, R., et al. (2017). The Modern-Era Retrospective "
            "Analysis for Research and Applications, Version 2 "
            "(MERRA-2). J. Climate, 30(14), 5419-5454. "
            "https://doi.org/10.1175/JCLI-D-16-0758.1"
        ),
        # NASA Earth science data carry no redistribution restriction:
        # ESDIS states its content is generally not copyrighted, and
        # NASA-led mission data are released as CC0 unless individually
        # marked. Citation is requested rather than required -- the
        # Gelaro et al. (2017) reference above satisfies it.
        "license": (
            "No restrictions. NASA Earth science data are not "
            "copyrighted and are released under CC0 unless marked "
            "otherwise; citation is requested, not required."
        ),
        "attribution": (
            "Source: NASA Global Modeling and Assimilation Office "
            "(GMAO), MERRA-2, distributed by GES DISC; modified by the "
            "UU-BUEM 'weather' package."
        ),
        "wind_is_grid_relative": False,
        "time_convention": (
            "Timestamps are in UTC, centred on the half hour (HH:30): "
            "the stamp 00:30Z labels the hour 00:00-01:00Z."
        ),
        # The HH:30 stamp is an hour CENTRE, and the source collections
        # are NASA's time-averaged ones (`M2T1NX*` -- the "T1" denotes
        # time-averaged 1-hourly), so a period mean is the documented
        # semantics. The KNMI test agrees but only weakly (53% of
        # stations, barely above chance): MERRA-2's ~50 km cells make a
        # cell average differ enough from a point observation that the
        # noise swamps the sub-hourly shape difference the test relies
        # on. Declared on the collection definition, corroborated -- not
        # established -- by measurement.
        "cell_methods": {"GHI": "time: mean"},
        "extra": {
            "radiation_note": (
                "GHI is the MEAN over the hour the stamp centres on "
                "(cell_methods 'time: mean'), per NASA's time-averaged "
                "M2T1NX collections. Rectangle integration is correct."
            ),
        },
    },
}


def attach_cf_variable_attrs(ds: xarray.Dataset, provider: str) -> None:
    """Attach correct CF ``standard_name``/``cell_methods`` to *ds*, in place.

    Also REMOVES metadata that is wrong rather than merely missing:
    cfgrib's ``forecast_reference_time`` on the time axis, its
    liquid-water-equivalent snow-depth name, its geographic wind names on
    a grid-relative provider, and the source-grid extent attributes that
    a crop invalidates.

    Parameters
    ----------
    ds : xarray.Dataset
        Dataset to annotate.  Modified in place.
    provider : str
        Key into :data:`PROVIDER_METADATA` (``cosmo_rea6``,
        ``era5_land``, ``merra2``).

    Notes
    -----
    Removing a wrong ``standard_name`` is deliberately preferred over
    replacing it with a vaguer one: a CF-aware consumer that finds no
    ``standard_name`` falls back to ``long_name`` and the variable name,
    whereas one that finds ``eastward_wind`` on a rotated-grid component
    silently produces wrong wind directions.
    """
    meta = PROVIDER_METADATA[provider]
    cell_methods = meta.get("cell_methods", {})
    grid_relative = meta.get("wind_is_grid_relative", False)

    for name in list(ds.variables):
        var = ds[name]
        current = var.attrs.get("standard_name")
        if current is not None and is_invalid_standard_name(current):
            var.attrs.pop("standard_name", None)
        if name in CF_STANDARD_NAMES:
            var.attrs["standard_name"] = CF_STANDARD_NAMES[name]
        elif name in GEOGRAPHIC_WIND_NAMES:
            if grid_relative:
                var.attrs.pop("standard_name", None)
                var.attrs["comment"] = WIND_ROTATION_COMMENT
            else:
                var.attrs["standard_name"] = GEOGRAPHIC_WIND_NAMES[name]
        if name in cell_methods:
            var.attrs["cell_methods"] = cell_methods[name]
        for stale in STALE_GRIB_GRID_ATTRS:
            var.attrs.pop(stale, None)

    if "time" in ds.variables:
        ds["time"].attrs["standard_name"] = "time"
        ds["time"].attrs["axis"] = "T"


def attach_global_attrs(
    ds: xarray.Dataset,
    provider: str,
    *,
    region: str | None = None,
    extra: dict[str, str] | None = None,
) -> None:
    """Attach CF-1.8 global attributes to *ds*, in place.

    Parameters
    ----------
    ds : xarray.Dataset
        Dataset to annotate.  Modified in place.
    provider : str
        Key into :data:`PROVIDER_METADATA`.
    region : str, optional
        Human-readable crop region (e.g. ``"Netherlands (NL)"``).
        Recorded as ``crop_region`` when given.
    extra : dict, optional
        Additional global attributes, applied last so a caller can
        override anything computed here.

    Notes
    -----
    Spatial and temporal bounds are read from the dataset itself rather
    than passed in, so they cannot drift out of step with the data --
    which is exactly how the previously shipped file ended up describing
    a 698752-point grid it did not have.
    """
    meta = PROVIDER_METADATA[provider]
    attrs: dict[str, object] = {
        "Conventions": "CF-1.8",
        "title": meta["title"],
        "institution": meta["institution"],
        "source": meta["source"],
        "references": meta["references"],
    }
    # ACDD spells this attribute "license" (US), so that is the primary
    # key even though the upstream documents say "licence".
    if meta.get("license"):
        attrs["license"] = meta["license"]

    comment_parts = [meta["time_convention"]]
    comment_parts.extend(str(v) for v in meta.get("extra", {}).values())
    attrs["comment"] = " ".join(comment_parts)

    coverage_year = ""
    if "time" in ds.variables and ds["time"].size:
        times = pd.to_datetime(ds["time"].values)
        coverage_year = times[0].strftime("%Y")
        attrs["time_coverage_start"] = times[0].strftime("%Y-%m-%dT%H:%M:%SZ")
        attrs["time_coverage_end"] = times[-1].strftime("%Y-%m-%dT%H:%M:%SZ")
        if times.size > 1:
            step = pd.Timedelta(times[1] - times[0])
            attrs["time_coverage_resolution"] = (
                f"PT{int(step.total_seconds() // 3600)}H"
            )

    for coord, lo, hi in (
        ("latitude", "geospatial_lat_min", "geospatial_lat_max"),
        ("longitude", "geospatial_lon_min", "geospatial_lon_max"),
    ):
        if coord in ds.variables:
            values = np.asarray(ds[coord].values, dtype="float64")
            attrs[lo] = float(np.nanmin(values))
            attrs[hi] = float(np.nanmax(values))
    if "latitude" in ds.variables:
        attrs["geospatial_bounds_crs"] = "EPSG:4326"

    if region:
        attrs["crop_region"] = region

    # Copernicus section 5.1.2 wants the data year in the notice; the
    # other providers' templates carry no placeholder and pass through.
    if meta.get("attribution"):
        attrs["attribution"] = str(meta["attribution"]).replace(
            "{year}", coverage_year
        ).strip()

    stamp = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    attrs["history"] = f"{stamp}: created by the UU-BUEM 'weather' package."

    if extra:
        attrs.update(extra)

    ds.attrs.update(attrs)


def attach_cf_metadata(
    ds: xarray.Dataset,
    provider: str,
    *,
    region: str | None = None,
    extra: dict[str, str] | None = None,
) -> None:
    """Apply the full CF metadata pass to *ds*, in place.

    Calls :func:`attach_cf_latlon_attrs`, :func:`attach_cf_variable_attrs`
    and :func:`attach_global_attrs` in that order.  This is the single
    entry point every provider's ``export.py`` calls immediately before
    writing, so no exporter can drift onto a partial metadata pass.
    """
    if "latitude" in ds.variables and "longitude" in ds.variables:
        attach_cf_latlon_attrs(ds)
    attach_cf_variable_attrs(ds, provider)
    attach_global_attrs(ds, provider, region=region, extra=extra)
