# Percentile Representative-Month Methodology (all providers)

## 1. Overview

For every grid cell and every calendar month, this algorithm identifies
which year of the archive best represents the 10th-percentile (P10),
median (P50) and 90th-percentile (P90) of that month's long-term solar
radiation. The same algorithm is implemented in each provider's
`percentile_index.py` (COSMO-REA6, ERA5-Land, MERRA-2) and works over
whatever monthly files are present:

| Provider   | Archive used       | Candidate years     | Grid                       |
| ---------- | ------------------ | ------------------- | -------------------------- |
| COSMO-REA6 | 1995-01 .. 2019-08 | 25 (24 for Sep–Dec) | 824 x 848 rotated-pole     |
| ERA5-Land  | 1950-01 .. 2025-12 | 76                  | 0.1° regular, Europe crop  |
| MERRA-2    | 1980-01 .. 2025-12 | 46                  | 0.5° x 0.625°, Europe crop |

The ranking metric is GHI (Global Horizontal Irradiance), the primary
solar energy resource variable. Once the representative year is selected
per cell, month and percentile, **all variables** from that year's
monthly file are carried into the output mosaic — not just GHI.

---

## 2. Why GHI as the Ranking Metric

GHI integrates both the direct-beam and diffuse solar components and
is the single best indicator of PV/solar-thermal yield, building
cooling load from solar gain, and daylight availability.  This aligns
with IEC 61724-1 and the ASHRAE TMY3 methodology, which ranks years
by cumulative monthly global radiation.

---

## 3. Algorithm (per spatial cell)

### 3.1 Inputs

| Input                | Shape                  | Description                                   |
| -------------------- | ---------------------- | --------------------------------------------- |
| Monthly NetCDF files | one per year and month | e.g. `COSMO_REA6_YYYY_MM_all_attrs.nc`        |
| Analysis period      | see table in section 1 | every monthly file in the output folder       |
| Spatial grid         | provider's native grid | `(y, x)` for COSMO; regular lat/lon otherwise |
| Ranking metric       | daily GHI sum          | Summed per calendar day, per cell             |

Leap-year days (29 Feb) are removed before any calculation, and so is
any stamp outside the file's own calendar month. COSMO-REA6 labels hours
as ENDING (01:00 .. next month 00:00), so its last stamp falls in the
next month and is dropped: 1 h of 744, uniform across years.

### 3.2 Steps

For each cell `(i, j)` and each month `m`:

```text
1. Compute daily total GHI for every day in month m, for all N years.

2. Sum each year's daily totals into one cumulative monthly
   radiation figure:
       total[y,i,j] = sum of year y's daily GHI totals for month m

3. Take the target radiation level for each percentile ACROSS years:
       tgt_P10[i,j] = 10th percentile of total[:,i,j]
       tgt_P50[i,j] = 50th percentile (median)
       tgt_P90[i,j] = 90th percentile

4. Select the year sitting nearest each target level:
       best_P10[i,j] = year  with  min |total[y,i,j] - tgt_P10[i,j]|
       best_P50[i,j] = year  with  min |total[y,i,j] - tgt_P50[i,j]|
       best_P90[i,j] = year  with  min |total[y,i,j] - tgt_P90[i,j]|
```

This ranks candidate years by cumulative monthly global radiation, as
in ASHRAE TMY3 (see section 2).  Because `total` is a real-valued sum
rather than a day count, the selection is effectively tie-free and the
chosen year's brightness rank comes out at approximately the requested
percentile.

### 3.2.1 Superseded selection rule (fixed 2026-08-19)

Until 2026-08-19 steps 2-4 instead pooled every year's daily values
together, took the pooled P10/P50/P90 as **thresholds**, and picked the
year minimising `|fraction of that year's days below the threshold - q|`.

That rule cannot produce the levels section 3.3 promises.  A *typical*
year has ~10% of its days below the pooled P10 — that is what the 10th
percentile means — so `min |cdf_P10 - 0.10|` selected the typical year
and actively rejected genuinely cloudy ones; `min |cdf_P90 - 0.90|`
rejected sunny ones the same way.  All three levels therefore chased
the same target.  Measured against the real 76-year ERA5-Land archive,
the selected years' brightness ranks were 0.273 / 0.240 / 0.268 for
P10 / P50 / P90 instead of 0.10 / 0.50 / 0.90 — P90 was returning
years *cloudier* than the median.

The statistic was also a day count divided by `max_days`, so it could
only take `max_days + 1` distinct values.  With 31-day months and 76
candidate years every cell had ties (median 12-20 years, mean ~42), and
`np.argmin` awarded each tie to whichever year sorted first — handing
the earliest year in the archive 52-59% of all cells at every level.

All three providers shared the defect; all three were fixed together,
so any percentile output generated before 2026-08-19 should be
regenerated.

### 3.3 Physical Interpretation

| Output  | GHI level       | Interpretation                    |
| ------- | --------------- | --------------------------------- |
| **P10** | 10th percentile | Extreme cloudy / low-solar year   |
| **P50** | Median          | Typical Meteorological Year (TMY) |
| **P90** | 90th percentile | Extreme sunny / high-solar year   |

Adjacent cells can and do select **different years** — each cell
optimises independently.

### 3.4 Mosaic Output

Because each cell independently selects its representative year,
the output files are spatial mosaics:

```text
P50 output for July (744 h × 824 × 848):
  cell(0,0)     → all variables from year 2007
  cell(0,1)     → all variables from year 2003
  cell(823,847) → all variables from year 2011
  ...
```

The `source_year(y, x)` variable in each output file records the origin
year for every cell. It is `-1` (`NO_SOURCE_YEAR`) where **no** year has
data for the cell — e.g. ERA5-Land ocean cells under its land-sea mask.
A cell with data in only some years is ranked over those years.

### 3.5 Verified results (runs of 2026-08-19/20)

| Provider   | Distinct winning years | Max single-year share | P10 < P50 < P90 | Flagged cells           |
| ---------- | ---------------------- | --------------------- | --------------- | ----------------------- |
| ERA5-Land  | 73–75 of 76            | 3.5–9.2 %             | 12/12 months    | 80361 (= land-sea mask) |
| MERRA-2    | 44–46 of 46            | 4.7–18.3 %            | 12/12 months    | 0                       |
| COSMO-REA6 | 23–25 of 25            | 5.1–10.5 %            | 12/12 months    | 0                       |

Domain-mean GHI P10 / P50 / P90 (W/m²): ERA5-Land 120.16 / 135.80 /
151.21; MERRA-2 129.89 / 143.85 / 157.26; COSMO-REA6 129.82 / 144.50 /
157.95. "Max single-year share" is the check that exposed the old bug:
counting *distinct* years alone stays high even when one year wins most
cells.

---

## 4. Time Axis

Each output file covers one calendar month. Its time axis is that
month's hours with 29 Feb removed (so February never exceeds 672 h) and any
out-of-month stamp dropped (see 3.1). Source months do not always share
one axis — ERA5-Land's 1950-01 starts at 01:00, COSMO always starts at
01:00 — so the mosaic is sized from the longest axis among the winning
years and each year is written at its own hour offset.

---

## 5. Output Files

36 files total: 12 months × 3 percentile levels.

| Pattern                          | Percentile | Content                |
| -------------------------------- | ---------- | ---------------------- |
| `<provider>_p10_MM_all_attrs.nc` | P10        | Low-GHI (cloudy) month |
| `<provider>_p50_MM_all_attrs.nc` | P50        | Median / typical month |
| `<provider>_p90_MM_all_attrs.nc` | P90        | High-GHI (sunny) month |

`<provider>` is `cosmo_rea6`, `era5_land` or `merra2`; files are written
to `<output_dir>/percentile/` by `weather fetch --percentile` or the
provider's own `percentile_index.py`.

**Format:** NetCDF-4 / HDF5, zlib compression level 1, float32.
**Dimensions:** `time` (one month, see section 4) and the provider's
spatial dims (`y`, `x` for COSMO-REA6).
**Variables:** every data variable of the source monthly files — i.e.
whatever schema the archive carries (COSMO: `T`, `GHI`, `DHI`, `DNI`,
`RH`, `T_DEW`, `WS_10M`, `U_10M`, `V_10M`, `PS`, `SNOW_DEPTH`,
`SNOWFALL`, `ALBEDO`) — plus `source_year`.

---

## 6. Practical Notes

- **Re-runs:** Existing valid output files are skipped automatically.
  Run with `--clean` to remove all output and force a full re-run.
- **Sample size:** N = 25 years (COSMO) gives moderate percentile uncertainty,
  particularly at P10/P90, where the target level is interpolated from
  only two or three bracketing years.  Interpret the tails with
  caution; ERA5-Land's 76-year archive is correspondingly tighter.
- **Read parallelism on network storage:** the load phase reads every
  monthly file in parallel, and on NFS more readers is not faster.
  The ERA5-Land production run on `sd26` used `ERA5_NCORES=32`, which
  ran far better than the default of one worker per CPU (96) without
  overloading the mount. ERA5-Land and MERRA-2 take the worker count
  from `ERA5_NCORES` / `MERRA_NCORES`; COSMO-REA6's script entry point
  is fixed at 94 read workers (`n_cpu_cores`), and its mosaic phase
  runs only 2 workers (`n_mosaic_workers`), each pulling up to 24
  source files of ~4 GB from NFS; the 2026-08 run held ~460 GB
  resident and took 11.5 h for all 36 files.
- **GHI-only ranking:** Cells with uniformly low GHI (heavily clouded)
  may show inconsistent temperature or wind rankings relative to the
  selected P-level.  Multi-variable ranking is a planned extension.
