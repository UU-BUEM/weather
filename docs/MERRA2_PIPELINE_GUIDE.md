# MERRA-2 pipeline guide

## What this pipeline does

Downloads MERRA-2 reanalysis data from NASA GES DISC via **OPeNDAP**
(server-side subsetting — no global file is ever downloaded), cropped to
a fixed Europe bounding box (same footprint as ERA5-Land:
`N,W,S,E = 72,-11,34,32`), and produces one monthly NetCDF-4 file per
year (`MERRA2_<YYYY>_<MM>_all_attrs.nc`), matching ERA5-Land's output
convention.

MERRA-2 coverage: **1980 to present**.

## Collections and attributes

Two GES DISC collections cover the 9 downloaded attributes — no 3rd
collection is needed:

| Collection             | Short key | Attributes                                             |
|-------------------------|-----------|----------------------------------------------------------|
| `M2T1NXRAD.5.12.4`      | `rad`     | `SWGDN` (-> GHI), `ALBEDO`                                |
| `M2T1NXSLV.5.12.4`      | `slv`     | `T2M`, `QV2M`, `U2M`, `V2M`, `U10M`, `V10M`, `PS`          |

**Why not `M2T1NXLND` (SNODP/PRECSNOLAND)?** Adding a 3rd collection
means one more OPeNDAP request per day. `ALBEDO` is available for free
within the `rad` request already being made for `SWGDN`, and is more
immediately useful for solar-PV work than snow depth/snowfall — so this
pipeline downloads `ALBEDO` instead. Snow variables are a documented
future extension (add `"lnd": "M2T1NXLND.5.12.4"` to
`downloaded_attributes.COLLECTIONS` and the corresponding `SNODP`/
`PRECSNOLAND` entries, plus a 3rd collection loop in `download.py`).

## Authentication (NASA Earthdata)

1. Register at <https://urs.earthdata.nasa.gov/> (free).
2. In *Applications > Authorized Apps*, add **"NASA GESDISC DATA
   ARCHIVE"** to your approved list.
3. Either set in `.env`:

   ```text
   EARTHDATA_USERNAME=<your_username>
   EARTHDATA_PASSWORD=<your_password>
   ```

   or create `~/.netrc`:

   ```text
   machine urs.earthdata.nasa.gov
       login  <your_username>
       password <your_password>
   ```

   (`chmod 600 ~/.netrc`). Resolution order is env vars first, then
   `~/.netrc` — see `weather.common.net.earthdata_auth`.

### Why a custom session is needed

NASA's login flow redirects across hosts (`urs.earthdata.nasa.gov` <->
the GES DISC data host `goldsmr4.gesdisc.eosdis.nasa.gov`). `requests`
strips the `Authorization` header on cross-host redirects by default (a
security precaution), which breaks this specific flow. `weather.common
.net.build_session(..., preserve_auth_hosts={...})` re-attaches the
header for exactly these two trusted hosts — see
`Merra2Downloader._get_session`.

## Spatial cropping (OPeNDAP constraint expressions)

MERRA-2's native grid is fixed: 0.5° latitude x 0.625° longitude, global
origin at -90/-180. `Merra2Downloader._bbox_indices` converts the
configured `[N, W, S, E]` box (`MERRA2_AREA` env var, default the Europe
box above) to inclusive grid-index ranges via:

```text
lat_idx = round((lat_deg - (-90)) / 0.5)
lon_idx = round((lon_deg - (-180)) / 0.625)
```

Those indices are embedded directly in the OPeNDAP request URL, e.g.:

```text
.../MERRA2_400.tavg1_2d_rad_Nx.20180101.nc4.nc4
    ?SWGDN[0:1:23][248:1:324][270:1:340],ALBEDO[0:1:23][248:1:324][270:1:340],time,lat[...],lon[...]
```

**Known limitation — no cross-provider regridding.** MERRA-2's native
grid (0.5°x0.625°) is coarser than and not cell-aligned with
ERA5-Land's (0.1°x0.1°). This pipeline crops to the *same geographic*
box on MERRA-2's *own* grid — it does not interpolate/regrid onto
ERA5-Land's grid. Cross-provider regridding, if ever needed, is a
separate future task.

## Derived fields: GHI, wind speed, relative humidity

### GHI = SWGDN directly (no de-accumulation)

Unlike ERA5-Land's accumulated `ssrd` (which needs de-accumulation and
month-boundary repair — see `repair_month_boundaries.py`), MERRA-2's
`SWGDN` is an **instantaneous** flux. GHI is simply `SWGDN`,
night-masked via `weather.common.derived_attributes.apply_derived_fields
(ds, "MERRA2", sol_pos, times, fields=["GHI"])`. No boundary bookkeeping
is needed at all.

### DNI/DHI are NOT computed in bulk

`common/derived_attributes.py`'s `DERIVED_FIELDS["MERRA2"]` registry
also defines `DHI`/`DNI` formulas via pvlib's DIRINT algorithm — but
DIRINT operates on a 1-D time series per site and cannot broadcast over
a full `(time, y, x)` grid. This is the same limitation that made
ERA5-Land defer DNI/DHI to an opt-in point-wise helper
(`era5_land/dni_pointwise.py`) rather than compute it in bulk. MERRA-2's
`transform.py` therefore only requests `fields=["GHI"]` from the
registry. A `merra2/dni_pointwise.py` mirroring ERA5-Land's is a
documented future extension, not built in this phase.

### Wind speed

`WS_10M = sqrt(U10M**2 + V10M**2)`, same convention as COSMO/ERA5-Land.

### Relative humidity — specific-humidity-based (new formula)

Unlike COSMO (direct `RELHUM_2M`) or ERA5-Land (dew-point Magnus
formula), MERRA-2 has no direct RH or dew-point field — only `QV2M`
(specific humidity at 2 m). RH is derived from `QV2M` + `T2M` + `PS`
using the standard specific-humidity -> vapor-pressure conversion,
combined with the Bolton (1980) saturation-vapor-pressure curve:

```text
e  = QV2M * PS / (0.622 + 0.378 * QV2M)          # vapor pressure, Pa
es = 611.2 * exp(17.67 * T / (T + 243.5))        # Bolton 1980, Pa (T in degC)
RH = 100 * e / es, clipped to [0, 100]
```

Implemented in `weather.providers.merra2.transform._compute_rh`.

**Important ordering note:** unlike ERA5-Land's Magnus RH (which needs
*pre-conversion* Kelvin inputs, computed before the K->degC step), this
Bolton formula needs `T2M` in **Celsius** — so `_compute_rh` runs
**after** the unit-conversion step, the reverse of ERA5-Land's ordering.
This is called out explicitly in the `transform.py` docstring so a
future maintainer doesn't copy ERA5-Land's ordering blindly.

## Running the pipeline

```bash
# Single month smoke test
python src/weather/tests/test_merra2_one_month.py --year 2018 --month 1

# Single year, all 12 months
python src/weather/tests/test_merra2_one_year.py --year 2018 --ncores 8

# Bulk multi-year run (tmux recommended for a long unattended run)
tmux new -s merra2
conda activate weather_env
export MERRA_WORK_DIR=/data/soma/merra2
export MERRA2_AREA=72,-11,34,32
python src/weather/tests/test_merra2_multi_year.py \
    --from-year 1980 --to-year 2025 --ncores 8 --resume --cleanup
# detach: Ctrl-b then d      reattach: tmux attach -t merra2
```

Unlike ERA5-Land's CDS queue (effectively 1 job/account), GES DISC's
OPeNDAP server has no per-account job queue — `MERRA2_OPENDAP_MAX_CONCURRENT`
(default 8) can be raised more freely than ERA5's `ERA5_CDS_MAX_CONCURRENT`,
though `--parallel-years` still divides transform cores the same way.
