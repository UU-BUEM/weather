from pathlib import Path
import logging
import math
import xarray as xr
import numpy as np
import pandas as pd
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv
import pvlib
import pvlib.snow
import PySAM.Pvwattsv8 as pv
import traceback

# Load environment variables
load_dotenv()

# Define file paths using environment variables
output_path = os.environ["output_path"]

# setup logging
logger = logging.getLogger(__name__)

PROJECT_PATH = Path(__file__).parents[1]
HOURS_PER_YEAR = 24*365
KELV_CELSIUS_OFFSET = 273.15
NETCDF_FILL_VALUE = 9.83e31


class PvPowerGeneration:
    def __init__(
        self,
        start_date: str,
        end_date: str,
        merra_directory,
        output_path: Path,
        system_capacity: float = 6.0,
        azimuth: float = 180.0,
        tilt: float = 35.0,
        inv_eff: float = 0.96,
        losses: float = 0.14,
        dc_ac_ratio: float = 1.1,
        module_type: int = 0,
        mask_files=None
    ):
        self.start_date = datetime.strptime(
            start_date, "%Y-%m-%dT%H:%M:%S.%fZ"
        )
        self.end_date = datetime.strptime(end_date, "%Y-%m-%dT%H:%M:%S.%fZ")
        self.years = list(range(self.start_date.year, self.end_date.year + 1))
        self.merra_directory = merra_directory
        self.output_path = output_path
        self.system_capacity = system_capacity
        self.azimuth = azimuth
        self.tilt = tilt
        self.inv_eff = inv_eff
        self.losses = losses
        self.dc_ac_ratio = dc_ac_ratio
        self.module_type = module_type
        self.mask_files = mask_files

        self.combined_merra_file = self._select_merra_file()

        self._load_merra_data()
        self._process_merra_data()


    def _select_merra_file(self):
        files = os.listdir(self.merra_directory)
        for year in range(self.start_date.year, self.end_date.year + 1):
            for file in files:
                if f"combined_merra_{year}.nc" in file:
                    return self.merra_directory / file
        raise FileNotFoundError(
            "No suitable MERRA file found for the "
            "specified date range."
        )


    def _select_merra_file_for_year(self, year):
        """Select MERRA NetCDF file for a specific year."""
        files = os.listdir(self.merra_directory)
        for file in files:
            if f"combined_merra_{year}.nc" in file:
                return self.merra_directory / file
        raise FileNotFoundError(f"No MERRA file found for year {year}.")


    def _load_year(self, year):
        """Load and process MERRA data for a specific year."""
        self.combined_merra_file = self._select_merra_file_for_year(year)
        self._load_merra_data()
        self._process_merra_data()


    def _load_merra_data(self):
        """Open MERRA data from netCDF."""
        #logging.info(f'Loading MERRA data from {self.combined_merra_file}...')
        if (
            hasattr(self, 'combined_merra_dataset')
            and self.combined_merra_dataset is not None
        ):
            self.combined_merra_dataset.close()
        self.combined_merra_dataset = xr.open_dataset(self.combined_merra_file)
        self.year = self.combined_merra_dataset.year
        self.variables = {name : np.array(var[:])
            for name, var in self.combined_merra_dataset.variables.items()
        }
        self.combined_merra_dataset.close()
        self.combined_merra_dataset = None


    @staticmethod
    def _fill_masked_val(arr: np.ndarray, fill_val: float):
        return np.where(
            arr > NETCDF_FILL_VALUE,
            fill_val,
            arr
        )

    @staticmethod
    def _align_hourly_profile(
        values: np.ndarray,
        target_len: int,
        sim_year: int,
        location: str,
        profile_name: str
    ) -> np.ndarray:
        """Align a 1D hourly profile to the dataset hour count."""
        arr = np.asarray(values, dtype=float).reshape(-1)
        current_len = arr.size
        if current_len == target_len:
            return arr

        logging.warning(
            "Hourly output length mismatch for year %s at"
            " %s (%s): model=%d, dataset=%d. Aligning.",
            sim_year,
            location,
            profile_name,
            current_len,
            target_len,
        )

        if current_len > target_len:
            return arr[:target_len]

        missing = target_len - current_len
        if current_len >= 24 and missing % 24 == 0:
            padding = np.tile(arr[-24:], missing // 24)
        elif current_len > 0:
            padding = np.full(missing, arr[-1], dtype=float)
        else:
            padding = np.zeros(missing, dtype=float)
        return np.concatenate([arr, padding])

    def _process_merra_data(self):
        """Convert units, fill masked values and rename variables."""
        #logging.info('Converting MERRA variables...')
        # temperature in C
        self.variables['temperature_c'] = (
            self.variables['T2M'] - KELV_CELSIUS_OFFSET
        )
        self.variables['temperature_c'] = self._fill_masked_val(
            self.variables['temperature_c'],
            0.0
        )

        # global horizontal irradiance
        self.variables['ghi_w_per_m_2'] = self.variables['SWGDN']
        self.variables['ghi_w_per_m_2'] = self._fill_masked_val(
            self.variables['ghi_w_per_m_2'],
            0.0
        )

        # wind speed at 2 meters
        self.variables['wind_speed_2_m_per_s'] = np.sqrt(
            self.variables['U2M']**2 + self.variables['V2M']**2
        )
        self.variables['wind_speed_2_m_per_s'] = self._fill_masked_val(
            self.variables['wind_speed_2_m_per_s'],
            0.0
        )

        # wind speed at 10 meters (preferred for PySAM cell temperature model)
        if 'U10M' in self.variables and 'V10M' in self.variables:
            self.variables['wind_speed_10_m_per_s'] = np.sqrt(
                self.variables['U10M']**2 + self.variables['V10M']**2
            )
            self.variables['wind_speed_10_m_per_s'] = self._fill_masked_val(
                self.variables['wind_speed_10_m_per_s'],
                0.0
            )
        else:
            # Fallback: extrapolate 2m wind to 10m using
            # log wind profile (z0=0.03)
            ratio_10_2 = np.log(10 / 0.03) / np.log(2 / 0.03)
            self.variables['wind_speed_10_m_per_s'] = (
                self.variables['wind_speed_2_m_per_s'] * ratio_10_2
            )

        # surface pressure in Pa (for dirint and elevation estimation)
        self.variables['pressure_pa'] = self.variables['PS']
        self.variables['pressure_pa'] = self._fill_masked_val(
            self.variables['pressure_pa'],
            101325.0
        )

        # snow depth in cm (SNODP from MERRA-2 is in meters)
        if 'SNODP' in self.variables:
            self.variables['snow_depth_cm'] = self.variables['SNODP'] * 100.0
            self.variables['snow_depth_cm'] = self._fill_masked_val(
                self.variables['snow_depth_cm'], 0.0
            )

        # snowfall in cm/hr (PRECSNOLAND from MERRA-2 is in kg/m²/s)
        # Conversion: kg/m²/s × 3600 s/hr
        # / ρ_snow(100 kg/m³) × 100 cm/m = × 3600
        if 'PRECSNOLAND' in self.variables:
            self.variables['snowfall_cm_per_hr'] = (
                self.variables['PRECSNOLAND'] * 3600.0
            )
            self.variables['snowfall_cm_per_hr'] = self._fill_masked_val(
                self.variables['snowfall_cm_per_hr'], 0.0
            )
            self.has_snow_data = True
        else:
            self.has_snow_data = False


    @staticmethod
    def calculate_optimal_orientation(lat, lon, year):
        """Calculate optimal PV panel tilt and azimuth for a given location.

        Uses pvlib solar position on the summer/winter solstices and latitude
        to determine the best panel angles for each season and the annual
        optimum.

        Returns:
            dict with keys: summer_tilt, azimuth_summer, winter_tilt,
            azimuth_winter, annual_tilt, azimuth_annual
        """
        def _solstice_tilt(date):
            # Use solar noon (12:00 UTC) to get meaningful zenith angles
            noon = datetime(date.year, date.month, date.day, 12)
            solar_pos = pvlib.solarposition.get_solarposition(noon, lat, lon)
            zenith = solar_pos['apparent_zenith'].iloc[0]
            if zenith >= 90:
                return 0.0
            return max(0.0, min(90.0, 90.0 - zenith))

        summer_tilt = _solstice_tilt(datetime(year, 6, 21))
        winter_tilt = _solstice_tilt(datetime(year, 12, 21))
        annual_tilt = max(0.0, min(90.0, abs(lat)))

        # Azimuth: South-facing (180°) in Northern Hemisphere,
        # North-facing (0°) in Southern Hemisphere
        if lat >= 0:
            azimuth_summer = (180 - 15) % 360   # 165°
            azimuth_winter = (180 + 15) % 360   # 195°
            azimuth_annual = 180.0
        else:
            azimuth_summer = (0 + 15) % 360     # 15°
            azimuth_winter = (360 - 15) % 360   # 345°
            azimuth_annual = 0.0

        return {
            'summer_tilt': round(summer_tilt, 2),
            'azimuth_summer': round(azimuth_summer, 2),
            'winter_tilt': round(winter_tilt, 2),
            'azimuth_winter': round(azimuth_winter, 2),
            'annual_tilt': round(annual_tilt, 2),
            'azimuth_annual': round(azimuth_annual, 2),
        }

    def _initialize_solar_model(self, pv_params=None):
        """Initialize parameters for the solar model.

        Args:
            pv_params: Optional dict of per-POI overrides. Falls back to
                instance defaults when a key is absent.
        """
        self.solar_model = pv.default('PVwattsNone')

        p = pv_params or {}
        system_capacity = p.get('system_capacity', self.system_capacity)
        azimuth = p.get('azimuth', self.azimuth)
        tilt = p.get('tilt', self.tilt)
        inv_eff = p.get('inv_eff', self.inv_eff)
        losses = p.get('losses', self.losses)
        dc_ac_ratio = p.get('dc_ac_ratio', self.dc_ac_ratio)
        module_type = p.get('module_type', self.module_type)

        # ── Array configuration ────────────────────────────────────────
        # 0=fixed open rack, 1=roof mount, 2=1-axis, 3=backtracking, 4=2-axis
        self.solar_model.SystemDesign.array_type = int(p.get('array_type', 0))
        self.solar_model.SystemDesign.system_capacity = system_capacity
        self.solar_model.SystemDesign.azimuth = azimuth
        self.solar_model.SystemDesign.tilt = tilt
        self.solar_model.SystemDesign.dc_ac_ratio = dc_ac_ratio

        # ── Module type ────────────────────────────────────────────────
        # 0=Standard (19%), 1=Premium (21%), 2=Thin Film (18%)
        MODULE_TYPE_MAP = {
            'standard crystalline silicon (19%)': 0,
            'premium crystalline silicon (21%)': 1,
            'thin film (18%)': 2,
        }
        if isinstance(module_type, str):
            module_type = MODULE_TYPE_MAP.get(module_type.lower(), 0)
        self.solar_model.SystemDesign.module_type = int(module_type)

        # ── Ground coverage ratio ──────────────────────────────────────
        self.solar_model.SystemDesign.gcr = float(p.get('gcr', 0.3))

        # ── Inverter type → efficiency mapping ─────────────────────────
        # If inverter_type is provided, it overrides inv_eff
        INVERTER_TYPE_MAP = {
            'string inverter (96%)': 0.96,
            'microinverter (96.5%)': 0.965,
            'central inverter (97%)': 0.97,
        }
        inverter_type = p.get('inverter_type')
        if (
            isinstance(inverter_type, str)
            and inverter_type.lower() in INVERTER_TYPE_MAP
        ):
            inv_eff = INVERTER_TYPE_MAP[inverter_type.lower()]
        elif (
            isinstance(inverter_type, (int, float))
            and 0 <= inverter_type <= 2
        ):
            inv_eff = [0.96, 0.965, 0.97][int(inverter_type)]

        # ── Inverter efficiency ────────────────────────────────────────
        # JSON sends fraction (0-1), PySAM expects percentage (90-99.5)
        self.solar_model.SystemDesign.inv_eff = inv_eff * 100

        # ── System losses ──────────────────────────────────────────────
        # JSON sends fraction (0-1), PySAM expects percentage (-5 to 99)
        # Typical EU: ~0.14 (14%) including soiling, mismatch, wiring, etc.
        self.solar_model.SystemDesign.losses = losses * 100

        # ── No additional adjustment (losses already accounted for) ────
        self.solar_model.AdjustmentFactors.constant = 0
    
    def _initialize_dataset(self):
        """Create empty netcdf dataset with required
        dimensions and variables.
        """
        n_hours = self.variables['temperature_c'].shape[2]
        coords = {
            'lat': self.variables['lat'],
            'lon': self.variables['lon'],
            'time': pd.date_range(
                start=datetime(int(self.year), 1, 1, 0),
                freq="1h",
                periods=n_hours
            )
        }
    
        dataset = xr.Dataset(
            data_vars=dict(
                solar_capacity_factor=xr.DataArray(
                    data=np.zeros(self.variables['temperature_c'].shape),
                    coords=coords
                ),
                temperature=xr.DataArray(
                    data=self.variables['temperature_c'],
                    coords=coords
                )
            ),
            coords=coords
        )

        return dataset
    
    @staticmethod
    def _get_dni_dhi(lat, lon, year, ghi, pressure=101325.0):
        """Approximate direct normal irradiance (DNI) and
        diffuse horizontal irradiance (DHI).

        This is necessary because PySAM needs DNI and DHI,
        but MERRA only provides GHI.
        """
        date_times = pd.date_range(
            datetime(year, 1, 1, 0),
            datetime(year, 12, 31, 23),
            freq=timedelta(hours=1)
        )
        solar_position = pvlib.solarposition.get_solarposition(
            date_times,
            lat,
            lon
        )

        # https://pvlib-python.readthedocs.io/en/stable/
        # reference/generated/pvlib.irradiance.dirint.html
        dni = pvlib.irradiance.dirint(
            ghi,
            solar_position['zenith'],
            date_times,
            pressure=pressure,
        ).fillna(0).values

        # https://pvpmc.sandia.gov/modeling-steps/
        # 1-weather-design-inputs/irradiance-and-insolation-2/
        # global-horizontal-irradiance/
        dhi = ghi - dni * np.cos(solar_position['zenith'] * math.pi / 180)

        return date_times, dni, dhi
    
    def _calculate_snow_loss(
        self, lat_idx, lat, lon_idx, lon,
        tilt, azimuth, num_strings=1
    ):
        """Calculate hourly DC loss fraction from snow using pvlib NREL model.

        Uses MERRA-2 snowfall (PRECSNOLAND) and snow depth (SNODP) with
        pvlib.snow.coverage_nrel to estimate snow coverage on tilted panels,
        then pvlib.snow.dc_loss_nrel to convert to DC power loss.

        Returns:
            np.ndarray of DC loss fractions (0 = no loss, 1 = full loss).
            Returns zeros if snow data is not available in the MERRA file.
        """
        n_hours = self.variables['temperature_c'].shape[2]

        if not self.has_snow_data:
            return np.zeros(n_hours)

        snowfall = self.variables['snowfall_cm_per_hr'][lat_idx, lon_idx, :]
        temp_air = self.variables['temperature_c'][lat_idx, lon_idx, :]

        # Time index and solar position
        date_times = pd.date_range(
            datetime(int(self.year), 1, 1, 0),
            freq='1h', periods=n_hours
        )
        solar_position = pvlib.solarposition.get_solarposition(
            date_times, lat, lon
        )

        # GHI → DNI/DHI (same decomposition as _get_dni_dhi)
        ghi = self.variables['ghi_w_per_m_2'][lat_idx, lon_idx, :]
        pressure = self.variables['pressure_pa'][lat_idx, lon_idx, :]
        dni = pvlib.irradiance.dirint(
            ghi, solar_position['zenith'], date_times, pressure=pressure
        ).fillna(0).values
        dhi = ghi - dni * np.cos(
            np.radians(solar_position['zenith'].values)
        )

        # Plane-of-array irradiance (needed by snow coverage model)
        poa = pvlib.irradiance.get_total_irradiance(
            surface_tilt=tilt,
            surface_azimuth=azimuth,
            solar_zenith=solar_position['apparent_zenith'],
            solar_azimuth=solar_position['azimuth'],
            dni=dni, ghi=ghi, dhi=dhi
        )
        poa_global = poa['poa_global'].fillna(0).clip(lower=0).values

        # Snow coverage using NREL model
        # (pvlib expects pandas Series with DatetimeIndex)
        snow_kwargs = dict(
            snowfall=pd.Series(snowfall, index=date_times),
            poa_irradiance=pd.Series(poa_global, index=date_times),
            temp_air=pd.Series(temp_air, index=date_times),
            surface_tilt=tilt,
        )
        if 'snow_depth_cm' in self.variables:
            snow_kwargs['snow_depth'] = pd.Series(
                self.variables['snow_depth_cm'][lat_idx, lon_idx, :],
                index=date_times
            )

        snow_coverage = pvlib.snow.coverage_nrel(**snow_kwargs)

        # DC loss from snow coverage
        dc_loss = pvlib.snow.dc_loss_nrel(
            snow_coverage, num_strings=num_strings
        )

        return np.array(dc_loss)

    def _get_solar_resource_data(self, lat_idx, lat, lon_idx, lon):
        """Populate solar resource data for the model."""
        pressure = self.variables['pressure_pa'][lat_idx, lon_idx, :]
        mean_pressure = float(np.mean(pressure))

        # Estimate elevation from mean surface pressure using
        # barometric formula
        # h = (T0 / L) * (1 - (P / P0)^(R*L / (g*M)))
        # Simplified: h ≈ 44330 * (1 - (P/101325)^0.1903)
        elev = max(0.0, 44330.0 * (1.0 - (mean_pressure / 101325.0) ** 0.1903))

        date_times, dni, dhi = self._get_dni_dhi(
            lat,
            lon,
            self.year,
            self.variables['ghi_w_per_m_2'][lat_idx, lon_idx, :],
            pressure=pressure
        )

        # Snow-adjusted albedo: 0.6 when snow depth > 1cm, else 0.2
        if 'snow_depth_cm' in self.variables:
            snow_depth = self.variables['snow_depth_cm'][lat_idx, lon_idx, :]
            albedo = np.where(snow_depth > 1.0, 0.6, 0.2)
        else:
            albedo = np.full(len(date_times), 0.2)

        solar_resource_data = {
            'lat': lat,
            'lon': lon,
            'tz': 0,
            'elev': elev,
            'year': list(date_times.year),
            'month': list(date_times.month),
            'day': list(date_times.day),
            'hour': list(date_times.hour),
            'minute': list(date_times.minute),
            'dn': list(dni),
            'df': list(dhi),
            'tdry': list(self.variables['temperature_c'][lat_idx, lon_idx, :]),
            'wspd': list(
                self.variables['wind_speed_10_m_per_s'][
                    lat_idx, lon_idx, :
                ]
            ),
            'pres': list(pressure),
            'alb': list(albedo),
        }

        return solar_resource_data


    def simulate_solar(self, solar_resource_data):
        """Simulate solar output and return hourly capacity factors."""
        self.solar_model.SolarResource.solar_resource_data = (
            solar_resource_data
        )
        self.solar_model.execute()
        solar_generation = np.array(self.solar_model.Outputs.ac)

        cap = self.solar_model.SystemDesign.system_capacity
        return solar_generation / (cap * 1000)

    def run(self, data: dict):
        """Calculate hourly solar capacity factors and store output."""
        try:
            os.makedirs(self.output_path, exist_ok=True)
            lkr = data.get("lkr", "unknown")

            for feature in data["topology"]:
                for poi_key in ["from", "to"]:
                    poi = feature.get(poi_key, {})
                    techs = poi.get('techs', {})

                    if not techs or 'pv_supply' not in techs:
                        continue

                    pv_supply = techs['pv_supply']

                    coordinates = poi.get("geometry", {}).get("coordinates", [])
                    if len(coordinates) < 2:
                        logging.warning(f"Invalid coordinates in {poi_key} POI")
                        continue

                    lat, lon = coordinates[1], coordinates[0]

                    # ── Calculate optimal orientation for this location ────
                    optimal = self.calculate_optimal_orientation(lat, lon, int(self.year))
                    optimize = bool(pv_supply.get('optimize_orientation', False))

                    # Extract per-POI PV parameters (fall back to instance defaults)
                    pv_params = {
                        'system_capacity': float(pv_supply.get('system_capacity', self.system_capacity)),
                        'azimuth': float(optimal['azimuth_annual'] if optimize else pv_supply.get('azimuth', self.azimuth)),
                        'tilt': float(optimal['annual_tilt'] if optimize else pv_supply.get('tilt', self.tilt)),
                        'inv_eff': float(pv_supply.get('inv_eff', self.inv_eff)),
                        'losses': float(pv_supply.get('losses', self.losses)),
                        'dc_ac_ratio': float(pv_supply.get('dc_ac_ratio', self.dc_ac_ratio)),
                        'module_type': int(pv_supply.get('module_type', self.module_type)),
                    }
                    # Optional overrides — only include if present in JSON
                    for opt_key in ('array_type', 'gcr'):
                        if opt_key in pv_supply:
                            pv_params[opt_key] = float(pv_supply[opt_key])
                    if 'inverter_type' in pv_supply:
                        pv_params['inverter_type'] = pv_supply['inverter_type']

                    logging.info(f"POI ({lat}, {lon}) — country={os.path.basename(self.merra_directory)}")

                    system_capacity = pv_params['system_capacity']

                    # Simulate each year in the date range separately
                    all_dfs = []
                    for sim_year in self.years:
                        self._load_year(sim_year)
                        dataset = self._initialize_dataset()

                        # Initialize the model with per-POI params
                        self._initialize_solar_model(pv_params)

                        lat_idx = np.argmin(np.abs(self.variables['lat'] - lat))
                        lon_idx = np.argmin(np.abs(self.variables['lon'] - lon))

                        solar_resource_data = self._get_solar_resource_data(lat_idx, lat, lon_idx, lon)
                        solar_capacity_factors = self.simulate_solar(solar_resource_data)

                        # Apply snow loss if snow data is available
                        snow_dc_loss = self._calculate_snow_loss(
                            lat_idx, lat, lon_idx, lon,
                            pv_params['tilt'], pv_params['azimuth']
                        )
                        target_len = int(dataset.sizes['time'])
                        location = f"({lat}, {lon})"
                        solar_capacity_factors = self._align_hourly_profile(
                            solar_capacity_factors,
                            target_len,
                            sim_year,
                            location,
                            "solar_capacity_factor",
                        )
                        snow_dc_loss = self._align_hourly_profile(
                            snow_dc_loss,
                            target_len,
                            sim_year,
                            location,
                            "snow_dc_loss",
                        )
                        solar_capacity_factors = solar_capacity_factors * (1 - snow_dc_loss)

                        hourly_capacity_factor = solar_capacity_factors

                        dataset.variables['solar_capacity_factor'][lat_idx, lon_idx] = hourly_capacity_factor

                        df = dataset.sel(lat=lat, lon=lon, method='nearest').to_dataframe().reset_index()
                        df = df.drop(columns=['lat', 'lon', 'temperature'])
                        df = df.rename(columns={'solar_capacity_factor': 'capacity_factor'})
                        df['capacity_factor'] = df['capacity_factor'].clip(lower=0).round(2).abs()

                        # Filter to requested date range
                        df = df[(df['time'] >= self.start_date) & (df['time'] <= self.end_date)]
                        all_dfs.append(df)

                    # Combine all years and save
                    combined_df = pd.concat(all_dfs, ignore_index=True)
                    output_filename = os.path.join(self.output_path, f"pv_{lat}_{lon}.csv")
                    with open(output_filename, 'w') as f:
                        combined_df.to_csv(f, index=False)

            return {'status_code': 200, 'message': 'Photovoltaic simulation completed successfully!'}

        except Exception as e:
            traceback_str = traceback.format_exc()
            logging.error(f"Error during PV simulation: {str(e)}\n{traceback_str}")
            return {'status_code': 500, 'message': f'Error during PV simulation: {str(e)}', 'traceback': traceback_str}

if __name__ == '__main__':
    data = {
    }
