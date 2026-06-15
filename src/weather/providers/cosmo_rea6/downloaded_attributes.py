"""COSMO-REA6 raw downloaded-attribute definitions.

Single source of truth for which variables are fetched from the
DWD OpenData COSMO-REA6 archive.  Derivation formulas (GHI, DHI, DNI)
live in :mod:`weather.common.derived_attributes`.

Typical usage::

    from weather.providers.cosmo_rea6.downloaded_attributes import (
        ATTRIBUTES,
    )
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Raw attributes downloaded from DWD OpenData COSMO-REA6
# ---------------------------------------------------------------------------
# Keys:
#   dwd_name     – directory name on the DWD OpenData server
#   description  – human-readable description
#   unit_raw     – unit in the raw GRIB file
#   unit_target  – unit after our conversion (model expectations)
#   conversion   – symbolic note on applied transform

ATTRIBUTES: dict[str, dict[str, str]] = {
    "PS": {
        "dwd_name": "PS",
        "description": "surface pressure",
        "unit_raw": "Pa",
        "unit_target": "Pa",
        "conversion": "none (already in Pascals (Pa))",
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
    },
    "T_2M": {
        "dwd_name": "T_2M",
        "description": "Temperature at 2 m above ground",
        "unit_raw": "K",
        "unit_target": "degC",
        "conversion": "T_2M - 273.15",
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
    },
    "H_SNOW": {
        "dwd_name": "H_SNOW",
        "description": "thickness of snow",
        "unit_raw": "m",
        "unit_target": "m",
        "conversion": "none (already in meters (m))",
    },
    "SNOW_GSP": {
        "dwd_name": "SNOW_GSP",
        "description": (
            "stratiform snow "
            "(grid-scale precipitation accumulated over the hour)"
        ),
        "unit_raw": "kg/m^2",
        "unit_target": "kg/m^2",
        "conversion": (
            "none (already in kg per square meter (kg/m^2))"
        ),
    },
    "SNOW_CON": {
        "dwd_name": "SNOW_CON",
        "description": (
            "convective snow "
            "(convective precipitation accumulated over the hour)"
        ),
        "unit_raw": "kg/m^2",
        "unit_target": "kg/m^2",
        "conversion": (
            "none (already in kg per square meter (kg/m^2))"
        ),
    },
}
