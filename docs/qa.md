# Weather Pipeline — User Q&A

Frequently asked questions from users of this pipeline. Most answers are
about COSMO-REA6 (the largest and most CPU-heavy provider); where
ERA5-Land or MERRA-2 behave differently it is said explicitly. For
methodology deep-dives see the linked companion documents.

---

## 1. What method is used for collecting a typical weather year?

### What does the pipeline do?

Each provider's `percentile_index.py` builds P10 / P50 / P90
representative mosaics **per calendar month**. For every grid cell and
every month `m`:

1. Sum each candidate year's daily GHI over month `m` → one cumulative
   monthly GHI value per year.
2. Take the 10th / 50th / 90th percentile of those values across years.
3. Select the year whose total is nearest each target.
4. Copy **all variables** for that cell and month from the selected year
   into the output mosaic.

The result is 36 files per provider (12 months x 3 levels), e.g.
`cosmo_rea6_p50_07_all_attrs.nc`. A different cell — and a different
month of the same cell — may come from a different year; the
`source_year(y, x)` variable in each file records the origin year per
cell (`-1` where no year has data, e.g. ERA5-Land ocean cells).

Run it with `weather fetch ... --percentile`, or directly:

```bash
python -m weather.providers.cosmo_rea6.percentile_index   # --clean / --month M
```

### How does it compare to the classic TMY method?

| Property                  | Classic TMY (Finkelstein-Schafer)         | This pipeline (monthly GHI rank)                |
| ------------------------- | ----------------------------------------- | ----------------------------------------------- |
| Selection unit            | Calendar **month**                        | Calendar **month**, per grid cell               |
| How selected              | CDF closeness to long-term CDF (FS stat.) | Nearest cumulative monthly GHI to a percentile  |
| Levels                    | Typical (median-like) only                | P10 / P50 / P90                                 |
| Variables used in ranking | T, irradiance, humidity, wind (weighted)  | GHI only                                        |
| Within-month consistency  | ✅ All variables from one year             | ✅ All variables from one year                   |
| Across month boundaries   | ❌ Stitched from different years           | ❌ Stitched from different years                 |
| Standard reference        | ISO 15927-4, ASHRAE TMY3                  | ASHRAE TMY3 monthly-radiation ranking principle |

Within a month, every variable for a cell comes from the same physical
year, so hourly T–GHI–wind correlations are preserved. Across month
boundaries (and between neighbouring cells) the source year can change,
exactly as in a classic TMY.

### Pros and cons

| Pros                                               | Cons                                                           |
| -------------------------------------------------- | -------------------------------------------------------------- |
| Delivers genuine P10/P90 extremes, not only median | Single ranking metric (GHI); a P10 month need not be cold      |
| Real-valued ranking → effectively tie-free         | Small pools (COSMO 25 years) make P10/P90 coarse               |
| Cheap: under a second per month for selection      | Month boundaries and neighbouring cells may jump between years |

See [percentile_methodology.md](percentile_methodology.md) for the full
algorithm, the superseded (buggy) pre-2026-08-19 rule, and the verified
results for all three providers.

---

## 2. Is night masking required or helpful?

### What is night masking?

Night masking forces GHI, DHI, and DNI to exactly **0.0 W/m²** when the
sun is below the horizon (solar zenith θ ≥ 90°). Separately, DNI is only
reconstructed above 5° elevation (`DNI_ELEVATION_THRESHOLD_DEG`); below
that the `1/cos θ` factor amplifies noise (see
[dni_methodology.md §6](dni_methodology.md)).

### Why is it needed at all?

Reanalysis radiation fields can carry tiny non-zero values around sunrise
and sunset from numerical noise in the radiation scheme and from the
coarse time step. COSMO-REA6 radiation (`SWDIRS_RAD`, `SWDIFDS_RAD`) is
**instantaneous at the timestamp** — verified against KNMI pyranometers,
see [dni_methodology.md §11.3](dni_methodology.md) — so values at a
stamp where the sun is geometrically below the horizon are artefacts.
Masking sets them to exactly zero.

### Could masking accidentally remove real diffuse radiation (twilight)?

Civil twilight (θ between 90° and 96°) carries a little skylight. It is
well below 0.05 % of the annual GHI total — negligible for any energy
application, and no standard TMY or energy-simulation workflow uses it.

### "There is no fixed timing of night across Europe — how is this handled?"

The solar zenith angle `θ(t, y, x)` is computed per cell from each cell's
own geographic latitude/longitude (COSMO's 2-D WGS84 coordinates decoded
by cfgrib from the rotated-pole GRIB metadata; ERA5-Land and MERRA-2 are
regular lat/lon grids). So a cell in northern Finland correctly gets
24-hour daylight in June and 24-hour night in December, and Madrid and
Stockholm get different sunrise times. The Spencer (1971) formula
(`common/solar_position.spencer_zenith`, and COSMO's dask-chunked version
in `transform.compute_dni`) runs over the full `(time, y, x)` array in one
vectorized pass.

### What if a cell shows high GHI during night hours?

That points to a data-quality issue in the source files, not a code bug.
The night mask suppresses it, but investigate that month's inputs.
`providers/cosmo_rea6/transform.report_dni_outliers()` runs after every
COSMO export and logs any cell with DNI ≥ 1400 W/m² (above the solar
constant), which catches the most severe artefacts. For ERA5-Land,
`boundary_repair.py` detects the known accumulation-step spikes and
`spike_repair.py` recomputes them from the raw GRIB.

### Is night masking standard practice?

Yes. pvlib, NREL SAM, SolarAnywhere, EnergyPlus TMY3 generation tools and
ASHRAE-compliant post-processing all apply θ ≥ 90° masking.

---

## 3. Why is `derived_attributes.py` in `common/` rather than `providers/cosmo_rea6/`?

It holds the **shared formulas** (`wind_speed`, `magnus_rh`, `bolton_rh`,
`dewpoint_from_rh`, `ghi_from_diffuse_direct`, `dni_from_direct`) that
every provider's `transform.py` imports, plus the `apply_derived_fields`
registry used by tests. Putting it inside `cosmo_rea6/` would make
ERA5-Land and MERRA-2 import from a sibling provider. `common/` is the
place for code shared across providers.

Provider-specific work (opening GRIBs, COSMO's dask-chunked Spencer
implementation, unit conversions) stays in each provider's
`transform.py`, which calls the shared formulas at full grid resolution.

---

## 4. Why is the annual merge step separate from the pipeline?

The pipeline writes **monthly** files. Nothing inside the repo needs an
annual file: `percentile_index.py` and `get_point_weather` both read the
monthly files directly. An annual merge (12 monthly NCs → one annual NC,
~112 GB for a full-domain COSMO year) is only for consumers who want one
file per year. Keeping it separate means:

- the per-year pipeline finishes sooner and needs less disk;
- a single regenerated month doesn't force a full re-merge until you
  choose to;
- `weather fetch --concatenate {per-year,all}` does the merge for you
  when you want it (preferably together with `--country`/`--bbox`, which
  makes the result far smaller).

Manual merge:

```bash
python -m weather.common.merge \
    --input  /data/output/COSMO_REA6_2005_??_all_attrs.nc \
    --output /data/output/COSMO_REA6_2005_annual_all_attrs.nc
```

---

## 5. Which `.nc` file naming convention is used and why?

| File                                       | Description                                  |
| ------------------------------------------ | -------------------------------------------- |
| `COSMO_REA6_<YYYY>_<MM>_all_attrs.nc`      | Monthly pipeline output                      |
| `COSMO_REA6_<YYYY>_annual_all_attrs.nc`    | Annual merge (`weather.common.merge`)        |
| `cosmo_rea6_p{10,50,90}_<MM>_all_attrs.nc` | Percentile mosaic, one per level and month   |
| `ERA5_LAND_<YYYY>_<MM>_all_attrs.nc`       | ERA5-Land monthly output                     |
| `MERRA2_<YYYY>_<MM>_all_attrs.nc`          | MERRA-2 monthly output                       |
| `..._<ISO>_...` (e.g. `NL`)                | `weather fetch --country` region-tagged file |

The `all_attrs` suffix distinguishes these from single-attribute
intermediates that may appear while debugging.

---

## 6. Why does the pipeline store all attributes together in one file?

COSMO-REA6 is downloaded as 11 separate raw attributes, each its own
monthly GRIB. Writing all derived output variables (`T`, `GHI`, `DHI`,
`DNI`, `RH`, `T_DEW`, `WS_10M`, `U_10M`, `V_10M`, `PS`, `SNOW_DEPTH`,
`SNOWFALL`, `ALBEDO`) into one monthly NetCDF:

- reduces 132 GRIBs per year (12 months x 11 attributes) to 12 files;
- keeps every variable on the same time axis and grid;
- lets downstream tools (BuEM, EnergyPlus converters, CDO/NCO) read one
  file per month.

---

## 7. Can I process a subset of years or months?

Yes:

```bash
# Years 2010–2015
python src/weather/tests/test_cosmo_multi_year.py \
    --from-year 2010 --to-year 2015 --ncores 12

# One year, selected months
python src/weather/tests/test_cosmo_one_year.py --year 2005 --months 2 3 --ncores 12

# Or the unified CLI (any provider)
weather fetch --provider cosmo-rea6 --range single-year --year 2005
```

Keep COSMO's `--ncores` around 12: it sets the number of simultaneous DWD
connections, and ~90 triggered a 503 storm (see
[parallelization.md §3](parallelization.md)).

`percentile_index.py` always uses every monthly file in the provider's
output folder. Its tails get coarse with few years; use at least ~10.

---

## 8. What happens if the run is interrupted?

Use `--resume` to restart without reprocessing completed months:

```bash
python src/weather/tests/test_cosmo_one_year.py \
    --year 2018 --ncores 12 \
    --skip-download --skip-decompress --resume
```

- `--resume`: skip months whose output `.nc` already exists.
- `--skip-download`: bypass Phase 1 (bz2 files already cleaned up).
- `--skip-decompress`: bypass Phase 2 (`.grb` files still on disk).

Exports are atomic (`.nc.tmp` → rename), so an interrupted export never
leaves a truncated `.nc` that `--resume` would treat as done. See
[parallelization.md §5.1](parallelization.md) for the full logic.

---

## 9. How much disk space does a full run require?

The COSMO-REA6 archive covers **1995-01 to 2019-08** — 296 monthly files;
DWD publishes nothing after 2019-08.

Monthly and annual sizes are measured on `sd26` (average of the twelve
1995 monthly files; one full 2018 annual merge). The bz2/GRIB rows are
from an earlier 9-attribute build and have not been re-measured since
`RELHUM_2M` and `SOBS_RAD` were added — expect somewhat more.

| Stage                                 | Per month / year | Full archive (296 months)       |
| ------------------------------------- | ---------------- | ------------------------------- |
| Downloaded bz2 (9-attribute estimate) | ~12 GB/year      | ~290 GB (not re-measured)       |
| Decompressed GRIB (9-attribute est.)  | ~84 GB/year peak | one year at a time with cleanup |
| Monthly NetCDF output                 | ~9.3 GB/month    | ~2.7 TB                         |
| Annual merged NetCDF (optional)       | ~112 GB/year     | ~2.7 TB (additional)            |
| Percentile mosaics (36 files)         | —                | not re-measured                 |

Keeping both monthly and annual files: **~5.4+ TB**. Cleanup is **off**
by default (`COSMO_CLEANUP=false`), so raw bz2 and GRIB intermediates are
kept too unless you pass `--cleanup`. A `--country`/`--bbox` run crops
before transform, so its output scales with the cropped area.

ERA5-Land (Europe crop, 1950–2025) and MERRA-2 (1980–2025) are far
smaller; see the two bulk-run guides.

---

## 10. Why NetCDF-4 (`.nc`) and not Zarr?

### What is Zarr?

Zarr is a cloud-native chunked array format for object storage (S3,
Azure Blob, GCS). It stores chunks as individual objects, enabling highly
parallel reads from distributed storage.

### Why does this pipeline use NetCDF-4?

| Criterion                   | NetCDF-4 (`.nc`)                                  | Zarr                                       |
| --------------------------- | ------------------------------------------------- | ------------------------------------------ |
| Single-file portability     | ✅ One `.nc` per month                             | ❌ Directory tree or object prefix          |
| Interoperability            | ✅ CDO, NCO, MATLAB, R, ArcGIS, QGIS, Panoply      | ⚠️ Python/Dask-centric                     |
| HPC GPFS performance        | ✅ No small-file overhead                          | ❌ Many small chunk files → metadata storms |
| CF metadata                 | ✅ CF-1.x attributes written by `export.py`        | ⚠️ Requires explicit attribute mapping     |
| Compression                 | ✅ zlib per-variable (complevel=1, float32)        | ✅ Any codec (Blosc, Zstd …)                |
| Cloud-native parallel reads | ⚠️ Sequential time-slice reads preferred          | ✅ Designed for parallel chunk reads        |
| External hand-off           | ✅ One file (e.g. the NL 2018 file for Enerplanet) | ⚠️ Needs zipping or a zarr-aware consumer  |

### How does BuEM consume the data?

BuEM does not open the archive files itself. It asks for one location at
a time via `weather.get_point_weather(lat, lon, year, provider=...)`
(locally) or the `weather serve` HTTP API (remotely), both of which read
the monthly NetCDFs and return hourly `T`/`GHI`/`DHI`/`DNI` for the
nearest cell. The access pattern — one cell, all hours — works well on
NetCDF-4 chunked by time.

### When would Zarr be a better choice?

If the archive moved to cloud object storage with many concurrent
readers each touching different spatial chunks. For the current
`sd26`-local workflow, NetCDF-4 is the better fit.

---

## 11. Why are `.grb` and `.idx` files not cleaned up after `--skip-decompress`?

### Symptom

After

```bash
python src/weather/tests/test_cosmo_one_year.py \
    --year 2005 --months 2 \
    --skip-download --skip-decompress --cleanup --ncores 12
```

the decompressed `.grb` files remain on disk, and new `.idx` files have
appeared alongside them.

### Why the `.grb` files are not removed

Per-month GRIB cleanup (CLEANUP B) requires both `--cleanup` **and** that
this run did the decompression. `--skip-decompress` means the run did not
create those files, so it does not delete them. `--resume` only controls
whether the transform is skipped; it has no effect on cleanup.

### Why `.idx` files appear

cfgrib writes an index cache next to every GRIB it opens, named
`<grb_name>.<hash>.idx`. They are harmless and speed up re-reads. Delete
them manually if you want:

```bash
find /data/soma/cosmo_rea6/decompress -name '*.idx' -delete
```

### How to clean up `.grb` files manually after a skip-decompress run

Once the month's `.nc` has been written successfully:

```bash
# Example: remove 2005-02 GRIB files and their index sidecars
for attr in H_SNOW PS RELHUM_2M SNOW_CON SNOW_GSP SOBS_RAD \
            SWDIFDS_RAD SWDIRS_RAD T_2M U_10M V_10M; do
    rm -f /data/soma/cosmo_rea6/decompress/${attr}/${attr}.2D.200502.grb*
done
```
