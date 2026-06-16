# from weather.providers.cosmo_rea6.config import get_config
import logging
import os

import xarray as xr

"""COSMO-REA6 percentile file generator."""

logger = logging.getLogger(__name__)


class PercentileFH:
    """Calculate percentiles based on Frankenstein Hall method."""

    def __init__(self):
        pass

    def load_data(self) -> str:
        """Load data from the given paths."""
        logger.info("Loading data from %d files")
        return os.path.join("/data", "soma", "x.nc")

    def read_data(self):
        """Read and preprocess data from the given paths."""
        xr.open_dataset(
            filename_or_object=self.load_data(),
            engine="netcdf4",
            chunks={"time": 100},
            )
        pass

    def dask_chunking(self):
        """Apply Dask chunking to the dataset both spatially and temporally."""
        pass
