"""Country bounding boxes and NetCDF cropping (provider-agnostic).

Public entry points:

* :func:`~weather.geo.countries.get_bbox` — look up a country's
  :class:`~weather.geo.bbox.BBox`.
* :func:`~weather.geo.countries.list_countries` — all recognised country
  keys.
* :func:`~weather.geo.crop.crop_to_country` /
  :func:`~weather.geo.crop.crop_netcdf` — crop an already-exported output
  NetCDF (ERA5-Land / MERRA-2 today; see :mod:`weather.geo.crop` for the
  COSMO-REA6 limitation) via CDO.

Also reachable from the CLI: ``weather geo crop --input ... --output ...
--country ...``.
"""

from __future__ import annotations

from .bbox import BBox
from .countries import get_bbox, list_countries, normalize_country
from .crop import crop_netcdf, crop_to_country

__all__ = [
    "BBox",
    "get_bbox",
    "list_countries",
    "normalize_country",
    "crop_netcdf",
    "crop_to_country",
]
