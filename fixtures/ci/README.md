# CI test fixtures

Small, **real** (not synthetic) subsets of already-processed provider archives,
committed to this public repo so downstream consumers' CI can call
`weather.get_point_weather()` without a full processed archive
(~1-2 GB/year/provider — never meant to be committed under `data/`, see
`.gitignore`).

**Scope: CI testing only, not scientific or production use.** Each fixture is
spatially cropped to a small bounding box around a handful of test locations —
it is not representative of the full archive and should never be used for
analysis.

Directory layout mirrors each provider's real `<data_dir>/<provider>/output/`
structure exactly, because `weather.get_point_weather(..., data_dir=...)` /
`WEATHER_DATA_DIR` resolve against that same layout
(`src/weather/point_query.py::_output_dir`). Point `WEATHER_DATA_DIR` (or
`data_dir=`) at this `fixtures/ci` directory and lookups resolve identically
to a real archive.

## merra2/

Source: `data/merra2/output/MERRA2_2018_{01..12}_all_attrs.nc` (12 monthly
files, full 2018 archive, verified free of the NaN-`T` bug fixed in commit
`db1e1b4`).

Crop: latitude 51.5-52.5°N, longitude 4.5-5.5°E — covers every location
`buem`'s test suite queries as of 2026-08-04: `(52.0, 5.0)`,
`(52.0907, 5.1214)`, `(52.08, 5.13)` (all near Utrecht, NL).

At MERRA-2's native 0.5°(lat) x 0.625°(lon) resolution this box actually
resolves to **3 latitude points (51.5, 52.0, 52.5) x 1 longitude point
(5.0)** — the window doesn't happen to straddle a second longitude grid
line (the nearest points outside the box are 4.375°E and 5.625°E). All
three current test locations' nearest-neighbor lookup lands on the same
single longitude column regardless, so this doesn't affect correctness
today, but it means there's less margin than intended for a *future* test
location whose nearest longitude column differs — widen the box in
`make_fixture.py` if one is added.

Reproduce with (Linux, where `cdo` is installed — e.g. `sd26`):

```python
from pathlib import Path
from weather.geo.bbox import BBox
from weather.geo.crop import crop_netcdf

bbox = BBox(north=52.5, west=4.5, south=51.5, east=5.5)
for month in range(1, 13):
    name = f"MERRA2_2018_{month:02d}_all_attrs.nc"
    crop_netcdf(
        Path("data/merra2/output") / name,
        Path("fixtures/ci/merra2/output") / name,
        bbox,
    )
```

This particular fixture was generated with `merra2/make_fixture.py` instead —
an `xarray`-based equivalent of the snippet above, used only because `cdo` has
no `win-64` build on conda-forge (confirmed via
`conda search -c conda-forge cdo`) and this repo's dev machine is Windows.
Prefer the `cdo`-based snippet above on a Linux box if regenerating.

Verified with `WEATHER_DATA_DIR=<repo>/fixtures/ci` set (matching how `buem`'s
CI is expected to consume this — see `src/weather/common/env.py::data_root`),
via `get_point_weather(52.0, 5.0, 2018, provider="merra-2")`, and the two other
`buem` test locations above: 8760 rows, 0 nulls in `T`/`GHI`/`DHI`/`DNI`,
`T` in [-8.7, 33.5] degC, `GHI` max 915.5 W/m^2, `DNI` max 971.3 W/m^2,
`DHI` max 430.8 W/m^2 — matching the uncropped archive's known values for
this cell/year closely.

Total size: ~1.9 MB for all 12 months.

Not yet cropped: `cosmo-rea6`, `era5-land` — add under `fixtures/ci/<provider>/
output/` the same way if a downstream consumer needs them; `merra2/
make_fixture.py` is the template.
