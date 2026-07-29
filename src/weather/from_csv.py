import os
from pathlib import Path

import pandas as pd


class CsvWeatherData:
    def __init__(self, csv_relative_path=None, cache_path=None):
        _csv = Path(csv_relative_path)
        if not _csv.is_absolute():
            raise ValueError(
                "csv_relative_path must be an absolute path. "
                "Relative paths are not supported to ensure "
                "portable behaviour when the package is installed."
            )
        self.csv_path = _csv
        if cache_path:
            _cp = Path(cache_path)
            self.cache_path = (
                _cp if _cp.is_absolute()
                else self.csv_path.parent / cache_path
            )
        else:
            self.cache_path = None
        self.df = self._load_and_prepare()

    def _load_and_prepare(self):
        if self.cache_path and os.path.exists(self.cache_path):
            return pd.read_feather(self.cache_path)
        df = pd.read_csv(self.csv_path)
        df.set_index(df.columns[0], inplace=True)
        df.index = pd.to_datetime(df.index, utc=True)
        df.index.name = 'datetime'
        if self.cache_path:
            try:
                import pyarrow  # noqa: F401
                df.reset_index().to_feather(self.cache_path)
            except ImportError:
                import warnings
                warnings.warn(
                    "pyarrow is not installed; skipping Feather cache. "
                    "Install with: pip install pyarrow",
                    stacklevel=2,
                )
        return df

    def extract_weather_columns(self):
        """Extracts required weather columns and renames them."""
        if self.df is None:
            raise ValueError("CSV data not loaded. Call read_csv() first.")
        # Map CSV columns to desired names
        columns_map = {
            "T": "T",
            "GHI": "GHI",
            "DNI": "DNI",
            "DHI": "DHI"
        }
        self.df = self.df[list(columns_map.keys())]
        self.df.rename(columns=columns_map, inplace=True)
        return self.df

    def get_hourly(self, method='mean'):
        """Return hourly resampled data."""
        if method == 'mean':
            return self.df.resample('h').mean()
        elif method == 'interpolate':
            return self.df.resample('h').interpolate()
        else:
            raise ValueError("Unknown method")

    def get_daily(self, method='mean'):
        """Return daily resampled data."""
        if method == 'mean':
            return self.df.resample('D').mean()
        else:
            raise ValueError("Unknown method")

    def reconstruct_dni_from_ghi(
        self, latitude: float, longitude: float
    ) -> pd.DataFrame:
        """Reconstruct DNI and DHI from GHI using pvlib DISC model.

        COSMO-REA6 (and most NWP models) store DNI computed as
        ``(GHI - DHI) / cos(zenith)``.  Near the horizon
        cos(zenith) -> 0, so the stored DNI diverges wildly
        (>4000 W/m2 observed).

        pvlib's DISC decomposition model estimates DNI directly
        from GHI without this singularity, giving physically
        bounded values (0..~1000 W/m2 for NL).  DHI is then
        back-computed as ``DHI = GHI - DNI * cos(zenith)``.

        The GHI column is **not modified** — only DNI and DHI
        are replaced.

        Parameters
        ----------
        latitude, longitude : float
            Site coordinates in decimal degrees
            (positive North / East).

        Returns
        -------
        pd.DataFrame
            Copy of self.df with DNI and DHI columns replaced
            by DISC-derived values.
        """
        from .common.dni_reconstruction import reconstruct_dni_dhi

        if self.df is None:
            raise ValueError("Data not loaded. Call _load_and_prepare first.")
        if "GHI" not in self.df.columns:
            raise ValueError("GHI column required for DNI reconstruction.")

        result = reconstruct_dni_dhi(
            self.df["GHI"],
            latitude,
            longitude,
            method="disc",
            zenith_kind="apparent",
            clip_to_extraterrestrial=True,
            clip_dhi_to_ghi=True,
        )

        df_out = self.df.copy()
        df_out["DNI"] = result["DNI"].reindex(df_out.index).fillna(0)
        df_out["DHI"] = result["DHI"].reindex(df_out.index).fillna(0)
        return df_out
