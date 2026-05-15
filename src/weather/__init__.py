"""Weather data pipeline package (UU-BUEM).

Provider-based architecture:
  - cosmo-rea6  : DWD OpenData  (implemented)
  - merra-2     : NASA GES DISC (scaffold)
  - era5-land   : Copernicus CDS (scaffold)
"""

from ._version import __version__

__all__ = ["__version__"]
