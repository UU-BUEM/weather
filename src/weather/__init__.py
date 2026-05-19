"""Weather data pipeline package (UU-BUEM).

Provider-based architecture:
  - cosmo-rea6  : DWD OpenData  (implemented)
  - merra-2     : NASA GES DISC (scaffold)
  - era5-land   : Copernicus CDS (scaffold)
"""

try:
    from ._version import __version__
except ImportError:
    __version__ = "1.1.0"

__all__ = ["__version__"]
