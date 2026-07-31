"""COSMO-REA6 raw downloaded-attribute definitions.

Single source of truth for which variables are fetched from the
DWD OpenData COSMO-REA6 archive.  Derivation formulas (GHI, DHI, DNI)
live in :mod:`weather.common.derived_attributes`; ALBEDO and SNOWFALL
(SNOW_CON + SNOW_GSP combined, matching ERA5-Land/MERRA-2's canonical
snowfall field) are COSMO-only math in
:mod:`weather.providers.cosmo_rea6.transform` (ALBEDO has no equivalent
raw field to derive it from on the other providers; SNOWFALL's
two-raw-fields-summed shape doesn't fit the shared registry either).

Adding or removing an attribute here is a **data edit, not a code
change** for the download/decompress/open steps (``config.py``'s
``attributes`` and every runner's attribute list both derive from
``ATTRIBUTES.keys()``) and, for ``role: "passthrough"`` attributes, for
the final output too -- :func:`weather.providers.cosmo_rea6.transform.
build_month_dataset` assembles those generically from ``unit_target``/
``description`` alone. Only a ``role: "formula"`` attribute (one that
needs real math -- unit conversion, combining two raw fields, a
vector magnitude, ...) still needs a hand-written formula in
``transform.py``; that's unavoidable, but it only has to be written
once, in one place.

Typical usage::

    from weather.providers.cosmo_rea6.downloaded_attributes import (
        ATTRIBUTES,
        canonical_name,
        passthrough_attrs,
    )
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Raw attributes downloaded from DWD OpenData COSMO-REA6
# ---------------------------------------------------------------------------
# Keys:
#   dwd_name        – directory name on the DWD OpenData server
#   description      – human-readable description; used verbatim as
#                       long_name for role="passthrough" output variables
#   unit_raw          – unit in the raw GRIB file
#   unit_target        – unit after our conversion (model expectations);
#                       used verbatim as units for role="passthrough"
#                       output variables
#   conversion        – symbolic note on applied transform
#   role              – "passthrough" (assembled generically, no code
#                       needed beyond this entry) or "formula" (feeds a
#                       hand-written derivation in transform.py: T_2M ->
#                       T, SWDIFDS_RAD/SWDIRS_RAD -> GHI/DHI/DNI, U_10M/
#                       V_10M -> WS_10M)
#   canonical_name    – output variable name, only when it differs from
#                       the attribute key (e.g. RELHUM_2M -> RH, to match
#                       ERA5-Land/MERRA-2's naming); omitted = same as key

ATTRIBUTES: dict[str, dict[str, str]] = {
    "H_SNOW": {
        "dwd_name": "H_SNOW",
        "description": "thickness of snow",
        "unit_raw": "m",
        "unit_target": "m",
        "conversion": "none (already in meters (m))",
        "role": "passthrough",
        "canonical_name": "SNOW_DEPTH",
    },
    "PS": {
        "dwd_name": "PS",
        "description": "surface pressure",
        "unit_raw": "Pa",
        "unit_target": "Pa",
        "conversion": "none (already in Pascals (Pa))",
        "role": "passthrough",
    },
    "RELHUM_2M": {
        "dwd_name": "RELHUM_2M",
        "description": "relative humidity at 2 m above ground",
        "unit_raw": "%",
        "unit_target": "%",
        "conversion": "none (already in percent (%))",
        "role": "passthrough",
        "canonical_name": "RH",
    },
    "SNOW_CON": {
        "dwd_name": "SNOW_CON",
        "description": (
            "convective snow "
            "(convective precipitation accumulated over the hour) -- "
            "feeds derived SNOWFALL with SNOW_GSP, not stored raw "
            "itself (see transform.compute_snowfall)"
        ),
        "unit_raw": "kg/m^2",
        "unit_target": "kg/m^2",
        "conversion": (
            "none (already in kg per square meter (kg/m^2))"
        ),
        "role": "formula",
    },
    "SNOW_GSP": {
        "dwd_name": "SNOW_GSP",
        "description": (
            "stratiform snow "
            "(grid-scale precipitation accumulated over the hour) -- "
            "feeds derived SNOWFALL with SNOW_CON, not stored raw "
            "itself (see transform.compute_snowfall)"
        ),
        "unit_raw": "kg/m^2",
        "unit_target": "kg/m^2",
        "conversion": (
            "none (already in kg per square meter (kg/m^2))"
        ),
        "role": "formula",
    },
    "SOBS_RAD": {
        "dwd_name": "SOBS_RAD",
        "description": (
            "net shortwave radiation at surface (instantaneous) -- "
            "feeds derived ALBEDO, not stored raw itself (see "
            "transform.compute_albedo); NOT ASOB_S, its average-type "
            "sibling"
        ),
        "unit_raw": "W/m2",
        "unit_target": "W/m2",
        "conversion": "none (already instantaneous W/m2)",
        "role": "formula",
    },
    "SWDIFDS_RAD": {
        "dwd_name": "SWDIFDS_RAD",
        "description": (
            "Downward diffuse shortwave radiation at surface "
            "(instantaneous)"
        ),
        "unit_raw": "W/m2",
        "unit_target": "W/m2",
        "conversion": "none (already instantaneous W/m2)",
        "role": "formula",
    },
    "SWDIRS_RAD": {
        "dwd_name": "SWDIRS_RAD",
        "description": (
            "Downward direct shortwave radiation at surface "
            "(instantaneous)"
        ),
        "unit_raw": "W/m2",
        "unit_target": "W/m2",
        "conversion": "none (already instantaneous W/m2)",
        "role": "formula",
    },
    "T_2M": {
        "dwd_name": "T_2M",
        "description": "Temperature at 2 m above ground",
        "unit_raw": "K",
        "unit_target": "degC",
        "conversion": "T_2M - 273.15",
        "role": "formula",
    },
    "U_10M": {
        "dwd_name": "U_10M",
        "description": (
            "U-component of wind at 10 m "
            "(rotated-pole grid north)"
        ),
        "unit_raw": "m/s",
        "unit_target": "m/s",
        "conversion": "kept as-is in rotated-pole coordinates",
        "role": "formula",
    },
    "V_10M": {
        "dwd_name": "V_10M",
        "description": (
            "V-component of wind at 10 m "
            "(rotated-pole grid north)"
        ),
        "unit_raw": "m/s",
        "unit_target": "m/s",
        "conversion": "kept as-is in rotated-pole coordinates",
        "role": "formula",
    },
}


def passthrough_attrs() -> list[str]:
    """Attribute keys with ``role == "passthrough"``.

    These are assembled generically by
    :func:`weather.providers.cosmo_rea6.transform.build_month_dataset`
    from ``unit_target``/``description`` alone -- no per-variable code.
    Everything else in :data:`ATTRIBUTES` has ``role == "formula"`` and
    feeds a hand-written derivation instead (T, GHI, DHI, WS_10M,
    ALBEDO, SNOWFALL).
    """
    return [k for k, v in ATTRIBUTES.items() if v.get("role") == "passthrough"]


def canonical_name(attr: str) -> str:
    """Output variable name for *attr*.

    Defaults to the attribute's own key (e.g. ``"PS"`` -> ``"PS"``);
    overridden via ``canonical_name`` in :data:`ATTRIBUTES` where
    cross-provider naming differs (e.g. ``"RELHUM_2M"`` -> ``"RH"``,
    ``"H_SNOW"`` -> ``"SNOW_DEPTH"``, to match ERA5-Land/MERRA-2).
    """
    return ATTRIBUTES[attr].get("canonical_name", attr)
