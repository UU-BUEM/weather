"""MERRA-2 raw downloaded-attribute definitions.

Single source of truth for which variables are fetched from the
NASA GES DISC MERRA-2 archive.  Derivation formulas (GHI, DHI, DNI)
live in :mod:`weather.common.derived_attributes`.

Typical usage::

    from weather.providers.merra2.downloaded_attributes import (
        ATTRIBUTES,
    )
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Raw attributes downloaded from NASA GES DISC MERRA-2
# ---------------------------------------------------------------------------
# Keys:
#   m2_name      – variable short name in MERRA-2 NetCDF files
#   description  – human-readable description
#   unit_raw     – unit as provided by MERRA-2
#   unit_target  – unit after our conversion (model expectations)
#   conversion   – symbolic note on applied transform

ATTRIBUTES: dict[str, dict[str, str]] = {
    "T2M": {
        "m2_name": "T2M",
        "description": "2-meter air temperature",
        "unit_raw": "K",
        "unit_target": "degC",
        "conversion": (
            "subtract 273.15 "
            "(converts Kelvin (K) to Celsius (C))"
        ),
    },
    "SWGDN": {
        "m2_name": "SWGDN",
        "description": (
            "incident shortwave radiation flux at the surface "
            "(Global Horizontal Irradiance / GHI)"
        ),
        "unit_raw": "W/m^2",
        "unit_target": "W/m^2",
        "conversion": (
            "none (already in Watts per square meter (W/m^2))"
        ),
    },
    "U2M": {
        "m2_name": "U2M",
        "description": (
            "2-meter eastward wind velocity component "
            "(zonal wind speed)"
        ),
        "unit_raw": "m/s",
        "unit_target": "m/s",
        "conversion": (
            "none (already in meters per second (m/s))"
        ),
    },
    "V2M": {
        "m2_name": "V2M",
        "description": (
            "2-meter northward wind velocity component "
            "(meridional wind speed)"
        ),
        "unit_raw": "m/s",
        "unit_target": "m/s",
        "conversion": (
            "none (already in meters per second (m/s))"
        ),
    },
    "U10M": {
        "m2_name": "U10M",
        "description": (
            "10-meter eastward wind velocity component "
            "(zonal wind speed)"
        ),
        "unit_raw": "m/s",
        "unit_target": "m/s",
        "conversion": (
            "none (already in meters per second (m/s))"
        ),
    },
    "V10M": {
        "m2_name": "V10M",
        "description": (
            "10-meter northward wind velocity component "
            "(meridional wind speed)"
        ),
        "unit_raw": "m/s",
        "unit_target": "m/s",
        "conversion": (
            "none (already in meters per second (m/s))"
        ),
    },
    "PS": {
        "m2_name": "PS",
        "description": "surface pressure",
        "unit_raw": "Pa",
        "unit_target": "Pa",
        "conversion": "none (already in Pascals (Pa))",
    },
    "SNODP": {
        "m2_name": "SNODP",
        "description": "snow depth over land",
        "unit_raw": "m",
        "unit_target": "m",
        "conversion": "none (already in meters (m))",
    },
    "PRECSNOLAND": {
        "m2_name": "PRECSNOLAND",
        "description": (
            "snowfall flux land "
            "(bias-corrected solid precipitation rate)"
        ),
        "unit_raw": "kg/m^2/s",
        "unit_target": "kg/m^2/h",
        "conversion": (
            "multiply by 3600 "
            "(converts mass flux per second to "
            "hourly accumulated total mass)"
        ),
    },
}
