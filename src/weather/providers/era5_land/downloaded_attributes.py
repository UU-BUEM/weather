"""ERA5-Land raw downloaded-attribute definitions.

Single source of truth for which variables are fetched from the
Copernicus Climate Data Store (CDS) ERA5-Land archive.  Derivation
formulas (GHI, DHI, DNI) live in
:mod:`weather.common.derived_attributes`.

Typical usage::

    from weather.providers.era5_land.downloaded_attributes import (
        ATTRIBUTES,
    )
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Raw attributes downloaded from Copernicus CDS ERA5-Land
# ---------------------------------------------------------------------------
# Keys:
#   e5l_name     – short name used in ERA5-Land NetCDF/GRIB output
#   description  – human-readable description
#   unit_raw     – unit as provided by CDS
#   unit_target  – unit after our conversion (model expectations)
#   conversion   – symbolic note on applied transform

ATTRIBUTES: dict[str, dict[str, str]] = {
    "2m_temperature": {
        "e5l_name": "t2m",
        "description": "2-meter air temperature",
        "unit_raw": "K",
        "unit_target": "degC",
        "conversion": (
            "subtract 273.15 "
            "(converts Kelvin (K) to Celsius (C))"
        ),
    },
    "2m_dewpoint_temperature": {
        "e5l_name": "d2m",
        "description": "2-meter dew point temperature",
        "unit_raw": "K",
        "unit_target": "degC",
        "conversion": (
            "subtract 273.15 "
            "(converts Kelvin (K) to Celsius (C))"
        ),
    },
    "10m_u_component_of_wind": {
        "e5l_name": "u10",
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
    "10m_v_component_of_wind": {
        "e5l_name": "v10",
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
    "surface_pressure": {
        "e5l_name": "sp",
        "description": "surface pressure",
        "unit_raw": "Pa",
        "unit_target": "Pa",
        "conversion": "none (already in Pascals (Pa))",
    },
    "snow_depth": {
        "e5l_name": "sd",
        "description": (
            "snow depth "
            "(water equivalent height of the snow pack)"
        ),
        "unit_raw": "m of water equivalent",
        "unit_target": "m of physical snow depth",
        "conversion": (
            "divide by (snow_density / 1000.0) or assume fallback "
            "density (e.g. ~250 kg/m^3) to convert water equivalent "
            "thickness to physical thickness"
        ),
    },
    "snowfall": {
        "e5l_name": "sf",
        "description": (
            "snowfall (accumulated mass of water equivalent "
            "from solid precipitation over the hour)"
        ),
        "unit_raw": "m of water equivalent",
        "unit_target": "kg/m^2/h",
        "conversion": (
            "multiply by 1000.0 "
            "(converts meters of water depth to accumulated "
            "mass in kilograms per square meter)"
        ),
    },
    "snow_albedo": {
        "e5l_name": "asn",
        "description": (
            "snow albedo (fraction of shortwave radiation "
            "reflected by the snow pack, ranges 0.0 to 1.0)"
        ),
        "unit_raw": "dimensionless",
        "unit_target": "dimensionless",
        "conversion": "none (already a ratio decimal)",
    },
    "forecast_albedo": {
        "e5l_name": "fal",
        "description": (
            "forecast albedo (total background surface grid "
            "reflectivity, combining bare land and "
            "variable snow cover)"
        ),
        "unit_raw": "dimensionless",
        "unit_target": "dimensionless",
        "conversion": "none (already a ratio decimal)",
    },
    "surface_solar_radiation_downwards": {
        "e5l_name": "ssrd",
        "description": (
            "surface solar radiation downwards "
            "(Global Horizontal Irradiance / GHI "
            "integrated over the hour)"
        ),
        "unit_raw": "J/m^2",
        "unit_target": "W/m^2",
        "conversion": (
            "divide by 3600 "
            "(converts hourly energy accumulation in Joules "
            "to average power flux in Watts)"
        ),
    },
}
