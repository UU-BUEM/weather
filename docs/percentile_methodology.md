# COSMO-REA6 Percentile Representative Year Methodology

## 1. Overview

For each of the 824 × 848 spatial cells, this algorithm identifies
which calendar year from the 1995–2018 COSMO-REA6 archive best
represents the 10th-percentile (P10), median (P50), and
90th-percentile (P90) of the long-term solar radiation climate.

The ranking metric is GHI (Global Horizontal Irradiance), the primary
solar energy resource variable.  Once the representative year is
selected per cell per percentile, **all variables** from that year's
file are carried into the output mosaic — not just GHI.

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

| Input | Shape | Description |
| --- | --- | --- |
| Monthly NetCDF files | 12 per year × 24 years = 288 | `COSMO_REA6_YYYY_MM_all_attrs.nc` |
| Analysis period | 1995–2018 | 24 years |
| Spatial grid | 824 × 848 | COSMO-REA6 rotated-pole |
| Ranking metric | daily GHI sum | Summed per calendar day, per cell |

Leap-year days (29 Feb) are removed before any calculation.

### 3.2 Steps

For each cell `(i, j)` and each month `m`:

```text
1. Compute daily total GHI for every day in month m, for all 24 years.

2. Pool all years together into one long daily series (length ~ 24*31).
   Sort this series and extract the threshold values:
       val_P10[i,j] = value at the 10th percentile of the pooled series
       val_P50[i,j] = value at the 50th percentile (median)
       val_P90[i,j] = value at the 90th percentile

3. For each individual year y, compute its empirical CDF fraction:
       cdf_P10[y,i,j] = fraction of year y's days with GHI ≤ val_P10
       cdf_P50[y,i,j] = fraction of year y's days with GHI ≤ val_P50
       cdf_P90[y,i,j] = fraction of year y's days with GHI ≤ val_P90

4. Select the year that minimises the absolute KS distance to the target:
       best_P10[i,j] = year  with  min |cdf_P10[y,i,j] - 0.10|
       best_P50[i,j] = year  with  min |cdf_P50[y,i,j] - 0.50|
       best_P90[i,j] = year  with  min |cdf_P90[y,i,j] - 0.90|
```

This is the Finkelstein-Schafer (FS) statistic applied at the
target percentile level.

### 3.3 Physical Interpretation

| Output | GHI level | Interpretation |
| --- | --- | --- |
| **P10** | 10th percentile | Extreme cloudy / low-solar year |
| **P50** | Median | Typical Meteorological Year (TMY) |
| **P90** | 90th percentile | Extreme sunny / high-solar year |

Adjacent cells can and do select **different years** — each cell
optimises independently.

### 3.4 Mosaic Output

Because each cell independently selects its representative year,
the output files are spatial mosaics:

```text
P50 output (8760 h × 824 × 848):
  cell(0,0)     → all variables from year 2007
  cell(0,1)     → all variables from year 2003
  cell(823,847) → all variables from year 2011
  ...
```

The `source_year(rlat, rlon)` variable in each output file records
the origin year for every cell.

---

## 4. Time Axis

All output files use a standard **8760-hour axis** (365 days × 24 h).
Leap-year files (8784 h) have their last 24 h (31 Dec hours 00–23)
truncated to match.

---

## 5. Output Files

36 files total: 12 months × 3 percentile levels.

| Pattern | Percentile | Content |
| --- | --- | --- |
| `cosmo_rea6_p10_MM_all_attrs.nc` | P10 | Extreme low-GHI (cloudy) year |
| `cosmo_rea6_p50_MM_all_attrs.nc` | P50 | Median / typical year |
| `cosmo_rea6_p90_MM_all_attrs.nc` | P90 | Extreme high-GHI (sunny) year |

**Format:** NetCDF-4 / HDF5, zlib compression level 1, float32.  
**Dimensions:** `time=8760, rlat=824, rlon=848`.  
**Variables:** `T`, `GHI`, `DHI`, `WS_10M`, `PS`, `H_SNOW`,
`SNOW_GSP`, `SNOW_CON` (+ `DNI` if present), `source_year`.

---

## 6. Practical Notes

- **Re-runs:** Existing valid output files are skipped automatically.
  Run with `--clean` to remove all output and force a full re-run.
- **Sample size:** N = 24 years gives moderate percentile uncertainty,
  particularly at P10/P90.  The FS method is robust to small N but
  the tails should be interpreted with caution.
- **GHI-only ranking:** Cells with uniformly low GHI (heavily clouded)
  may show inconsistent temperature or wind rankings relative to the
  selected P-level.  Multi-variable ranking is a planned extension.
