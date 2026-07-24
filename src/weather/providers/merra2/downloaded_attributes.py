"""MERRA-2 raw downloaded-attribute definitions.

Single source of truth for which variables are fetched from the
NASA GES DISC MERRA-2 archive.  Derivation formulas (GHI, RH, wind
speed) live in :mod:`weather.providers.merra2.transform` (GHI via
:mod:`weather.common.derived_attributes`).

Typical usage::

    from weather.providers.merra2.downloaded_attributes import (
        ATTRIBUTES,
        attrs_by_collection,
    )
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# GES DISC collections used by this pipeline
# ---------------------------------------------------------------------------
# 3 collections, one OPeNDAP request per (collection, day). "lnd" (land
# diagnostics: SNODP/PRECSNOLAND) added because a confirmed downstream
# consumer (github.com/THD-Spatial-AI/merra2-energy-pipeline,
# src/data_pipeline/config.py) needs both for its PV snow-loss model.
COLLECTIONS: dict[str, str] = {
    "rad": "M2T1NXRAD.5.12.4",
    "slv": "M2T1NXSLV.5.12.4",
    "lnd": "M2T1NXLND.5.12.4",
}

# ---------------------------------------------------------------------------
# Raw attributes downloaded from NASA GES DISC MERRA-2
# ---------------------------------------------------------------------------
# Keys:
#   m2_name      – variable short name in MERRA-2 NetCDF files
#   collection   – short collection key (see COLLECTIONS above)
#   description  – human-readable description
#   unit_raw     – unit as provided by MERRA-2
#   unit_target  – unit after our conversion (model expectations)
#   conversion   – symbolic note on applied transform

ATTRIBUTES: dict[str, dict[str, str]] = {
    "T2M": {
        "m2_name": "T2M",
        "collection": "slv",
        "description": "2-meter air temperature",
        "unit_raw": "K",
        "unit_target": "degC",
        "conversion": (
            "subtract 273.15 "
            "(converts Kelvin (K) to Celsius (C))"
        ),
    },
    "QV2M": {
        "m2_name": "QV2M",
        "collection": "slv",
        "description": "2-meter specific humidity",
        "unit_raw": "kg/kg",
        "unit_target": "kg/kg",
        "conversion": (
            "none — consumed directly by the RH formula "
            "(see transform._compute_rh / docs/MERRA2_PIPELINE_GUIDE.md)"
        ),
    },
    "U2M": {
        "m2_name": "U2M",
        "collection": "slv",
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
        "collection": "slv",
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
        "collection": "slv",
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
        "collection": "slv",
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
        "collection": "slv",
        "description": "surface pressure",
        "unit_raw": "Pa",
        "unit_target": "Pa",
        "conversion": "none (already in Pascals (Pa))",
    },
    "SWGDN": {
        "m2_name": "SWGDN",
        "collection": "rad",
        "description": (
            "incident shortwave radiation flux at the surface "
            "(Global Horizontal Irradiance / GHI)"
        ),
        "unit_raw": "W/m^2",
        "unit_target": "W/m^2",
        "conversion": (
            "none (already in Watts per square meter (W/m^2); "
            "instantaneous, unlike ERA5-Land's accumulated ssrd — "
            "no de-accumulation needed)"
        ),
    },
    "ALBEDO": {
        "m2_name": "ALBEDO",
        "collection": "rad",
        "description": "surface albedo (fraction of reflected shortwave)",
        "unit_raw": "1",
        "unit_target": "1",
        "conversion": "none (already a dimensionless fraction 0-1)",
    },
    "U50M": {
        "m2_name": "U50M",
        "collection": "slv",
        "description": (
            "50-meter eastward wind velocity component "
            "(zonal wind speed; hub-height-relevant for wind power, "
            "unlike U10M/U2M)"
        ),
        "unit_raw": "m/s",
        "unit_target": "m/s",
        "conversion": (
            "none (already in meters per second (m/s))"
        ),
    },
    "V50M": {
        "m2_name": "V50M",
        "collection": "slv",
        "description": (
            "50-meter northward wind velocity component "
            "(meridional wind speed; hub-height-relevant for wind power, "
            "unlike V10M/V2M)"
        ),
        "unit_raw": "m/s",
        "unit_target": "m/s",
        "conversion": (
            "none (already in meters per second (m/s))"
        ),
    },
    "SNODP": {
        "m2_name": "SNODP",
        "collection": "lnd",
        "description": "snow depth (within the snow-covered tile fraction only)",
        "unit_raw": "m",
        "unit_target": "m",
        "conversion": "none (already in meters (m))",
    },
    "PRECSNOLAND": {
        "m2_name": "PRECSNOLAND",
        "collection": "lnd",
        "description": "snowfall rate over land",
        "unit_raw": "kg/m^2/s",
        "unit_target": "kg/m^2/h",
        "conversion": (
            "multiply by 3600 "
            "(converts kg/m^2/s to kg/m^2/h, matching COSMO's "
            "SNOW_GSP+SNOW_CON and ERA5-Land's sf convention)"
        ),
    },
}


def attrs_by_collection() -> dict[str, list[str]]:
    """Group :data:`ATTRIBUTES` keys by their ``collection`` field.

    Returns
    -------
    dict[str, list[str]]
        Mapping ``{"rad": [...], "slv": [...]}`` — used by the downloader
        to build one OPeNDAP request per (collection, day) that lists
        every attribute of that collection in a single query.
    """
    out: dict[str, list[str]] = {c: [] for c in COLLECTIONS}
    for name, meta in ATTRIBUTES.items():
        out[meta["collection"]].append(name)
    return out
