"""Weather data pipeline package (UU-BUEM).

Provider-based architecture:
  - cosmo-rea6  : DWD OpenData  (implemented)
  - merra-2     : NASA GES DISC (implemented)
  - era5-land   : Copernicus CDS (implemented)

``get_point_weather`` is the lightweight, downstream-facing entry point:
given a location/year, it extracts T/GHI/DHI/DNI from already-processed
provider archives (the `pointquery` extra) without needing the full
GRIB/download/transform pipeline (the `pipeline` extra).
"""

from .point_query import get_point_weather

try:
    from ._version import __version__
except ImportError:
    __version__ = "1.1.0"

__all__ = ["__version__", "get_point_weather"]
