# DNI Computation Methodology

**Module:** `src/weather/providers/cosmo_rea6/transform.py` — `compute_dni()`  
**Status:** Experimental diagnostic. Use for exploration and validation only.

---

## 1. What is DNI and why compute it from COSMO-REA6?

**Direct Normal Irradiance (DNI)** is the solar irradiance received per unit
area on a surface held perpendicular to the sun's rays. It is the key input
for concentrating solar power (CSP) systems and parabolic trough models.

COSMO-REA6 provides two radiation components directly on its 824 × 848
rotated-pole grid at 1-hour intervals:

| CR6 variable  | Meaning                               | Units |
|---------------|---------------------------------------|-------|
| `SWDIRS_RAD`  | Direct horizontal irradiance          | W/m²  |
| `SWDIFDS_RAD` | Diffuse horizontal irradiance         | W/m²  |

`SWDIRS_RAD` is the **direct beam projected onto a horizontal surface**,
i.e. `SWDIRS_RAD = DNI × cos(θ_z)` where `θ_z` is the solar zenith angle.
Inverting this identity gives:

$$\text{DNI} = \frac{\text{SWDIRS\_RAD}}{\cos(\theta_z)}$$

This formula is **exact** for COSMO-REA6 data — no decomposition model is
needed because the direct component is already available separately.

---

## 2. Solar zenith angle: algorithm comparison

Computing DNI requires the solar zenith angle `θ_z` at every grid cell and
every timestep. Three algorithms were considered:

### 2.1 Spencer (1971) — **chosen approach**

Spencer (1971) expresses the sun's position as a Fourier series in the day
angle `B = (d - 1) × 2π / 365` (radians, where `d` is the day of year 1–365):

**Equation of time** (minutes):

$$E_t = 229.18 \, (0.000075 + 0.001868 \cos B - 0.032077 \sin B
        - 0.014615 \cos 2B - 0.04089 \sin 2B)$$

**Solar declination** (radians):

$$\delta = 0.006918 - 0.399912 \cos B + 0.070257 \sin B
          - 0.006758 \cos 2B + 0.000907 \sin 2B
          - 0.002697 \cos 3B + 0.00148 \sin 3B$$

**Hour angle** (radians), where `UTC_h` is the UTC hour of day and
`lon` is geographic longitude in degrees:

$$\omega = \frac{\pi}{12} \left( \text{UTC\_h} - 12 + \frac{\text{lon}}{15}
           + \frac{E_t}{60} \right)$$

**Cosine of solar zenith angle:**

$$\cos \theta_z = \sin \phi \sin \delta + \cos \phi \cos \delta \cos \omega$$

where `φ` is geographic latitude.

**Accuracy:** Spencer (1971) has a typical error of ±0.1–0.3° in solar
position. COSMO-REA6 itself has spatial resolution uncertainty on the order
of 5–10° in effective sun angle (due to cloud/aerosol parameterisation).
Spencer's error is therefore negligible relative to the input data.

**Implementation note:** The formula is fully vectorised over the 3-D array
`(time, y, x)` using NumPy/Dask broadcasting. Latitude and longitude
coordinates come from cfgrib's 2-D auxiliary coordinate arrays (geographic,
not rotated-pole), which cfgrib writes automatically for COSMO-REA6 GRIBs.

---

### 2.2 Meeus astronomical algorithm

Jean Meeus' *Astronomical Algorithms* (2nd ed., 1998) provides a more
elaborate polynomial correction for solar declination and the equation of time,
including terms for orbital eccentricity variation, nutation, and aberration.

| Property           | Meeus               | Spencer (1971)     |
|--------------------|---------------------|--------------------|
| Accuracy           | ±0.01°              | ±0.1–0.3°          |
| Implementation     | ~30 polynomial terms | 7 Fourier terms    |
| Leap-year handling | Yes                 | Approximate        |
| External dependency| None (pure math)    | None (pure math)   |

**Why not used here:** The 30× higher accuracy is irrelevant for COSMO-REA6
because the reanalysis grid uncertainty already dominates. The added
complexity provides no practical benefit.

---

### 2.3 NREL Solar Position Algorithm (SPA)

The NREL SPA (Reda & Andreas, 2004) is the gold standard for solar position
calculations, with accuracy better than ±0.0003°. It is the algorithm used
inside pvlib (`pvlib.solarposition.spa_python`).

| Property           | NREL SPA            | Spencer (1971)     |
|--------------------|---------------------|--------------------|
| Accuracy           | < 0.0003°           | ±0.1–0.3°          |
| Valid date range   | −2000 to +6000 CE   | ±1 year accurate   |
| Vectorisation      | Requires pvlib      | Native NumPy/Dask  |
| Speed (gridded)    | Very slow (see §3)  | Fast               |

**Why not used here:** See §3 (pvlib vectorisation limitation).

---

## 3. Why not pvlib for gridded data?

pvlib's `get_solarposition()` is the standard tool for single-site solar
analysis. Its signature is:

```python
pvlib.solarposition.get_solarposition(
    time: DatetimeIndex,      # N timesteps
    latitude: float,          # ONE location
    longitude: float,         # ONE location
)
```

For a COSMO-REA6 grid (824 rows × 848 columns = **698,752 cells**), the
only pvlib-compatible approach is a loop over grid cells:

```python
# Slow — 698 k serial calls, no parallelism across spatial dimension
for y in range(824):
    for x in range(848):
        sol = pvlib.solarposition.get_solarposition(time, lat[y,x], lon[y,x])
```

On a single core this takes hours. On 16 cores with a `ProcessPoolExecutor`
it still requires chunking the spatial loop and carrying GIL overhead.

The Spencer formula, by contrast, is expressed as **pure NumPy/Dask
element-wise operations** that broadcast naturally over `(T, Y, X)` arrays.
The full month (744 timesteps × 824 × 848 = 519 M elements) is processed in
a single vectorised pass, parallelised automatically by dask across ~80
independent tasks.

**pvlib is the right tool for:**
- Single-site time-series analysis
- DISC / Erbs GHI decomposition at a point
- Detailed irradiance plane-of-array modelling
- Production-quality DNI estimates from GHI-only inputs

**Spencer vectorisation is the right tool for:**
- Full-grid SZA computation with native dask chunking
- Any operation requiring `cos(θ_z)` at every `(t, y, x)` cell

---

## 4. DNI formula and why Erbs / DISC was not used

### 4.1 The exact formula

$$\text{DNI} = \frac{\text{SWDIRS\_RAD}}{\cos(\theta_z)}$$

This is exact because COSMO-REA6 provides the **direct horizontal component**
`SWDIRS_RAD` as a model output. No decomposition is needed or appropriate.

### 4.2 Decomposition models (Erbs, DISC) — not applicable here

Decomposition models (Erbs et al., 1982; Maxwell, 1987 DISC) estimate DNI
from GHI alone, using the clearness index `k_t = GHI / GHI_extraterrestrial`.
They are used when only GHI is measured and the direct component is unknown.

For COSMO-REA6, **we already have `SWDIRS_RAD`** (the direct component).
Using a decomposition model would introduce unnecessary estimation error
(RMSE ≈ 80–120 W/m²) compared to the exact inversion above.

Use decomposition only if `SWDIRS_RAD` is unavailable or suspected corrupt.

---

## 5. cos_sza clipping and numerical safety

### 5.1 Lower bound: 1 × 10⁻³ (preventing division by zero)

Near solar noon on the horizon, `cos(θ_z)` approaches zero as the sun sets.
At exactly `θ_z = 90°`, `cos(θ_z) = 0` and `DNI = SWDIRS / 0 = ∞`.

Dask evaluates **both branches** of an `xr.where` expression before masking,
so a NaN or ∞ in the un-masked branch propagates into the result even for
cells that are ultimately set to zero. To prevent this:

```python
cos_sza_safe = clip(cos_sza_raw, 1e-3, 1.0)
dni_raw = swdirs / cos_sza_safe          # finite everywhere
dni = xr.where(elevation >= threshold, dni_raw, 0.0)
```

The clipped value `1e-3` is never used in the final output because all
cells with `θ_z ≈ 90°` have solar elevation < 5° and are masked to zero
by the elevation threshold.

### 5.2 Upper bound: 1.0 (preventing float32 rounding artefacts)

The Spencer dot-product `sin φ sin δ + cos φ cos δ cos ω` can produce values
marginally above 1.0 due to float32 rounding (e.g. `1.0000001`). A value
above 1.0 would make `cos_sza_safe > 1`, which means `DNI = SWDIRS / (>1) < SWDIRS`.
This violates the physical identity `DNI ≥ SWDIRS_RAD` for all cells above
the elevation threshold (since `cos(θ_z) ≤ 1` always). Clamping to 1.0
corrects this artefact.

```python
cos_sza_safe = clip(cos_sza_raw, 1e-3, 1.0)   # [1e-3, 1.0]
```

---

## 6. Elevation threshold (default: 5°)

DNI is physically meaningful only when the sun is above the horizon. At very
low sun angles (0°–5°), two problems occur:

1. `cos(θ_z)` is small, so the division amplifies any noise in `SWDIRS_RAD`.
2. COSMO-REA6 assigns small but non-zero values to `SWDIRS_RAD` at grazing
   incidence (shadow effects in the reanalysis model), which would produce
   unrealistically large DNI values.

**Implementation:** cells where solar elevation < 5° are set to `DNI = 0`:

```python
elevation = arcsin(clip(cos_sza_raw, -1.0, 1.0)) * (180 / π)
dni = xr.where(elevation >= elevation_threshold, dni_raw, 0.0)
```

**Side effect on diagnostic checks:** `SWDIRS_RAD` can be 1–5 W/m² for cells
just below the 5° threshold (grazing incidence). For those cells `DNI = 0`
but `SWDIRS_RAD > 0`. Any diagnostic that checks `DNI ≥ SWDIRS_RAD` must
exclude zero-DNI cells:

```python
mask_active = (swdirs > 1.0) & (dni > 0.0)   # above threshold only
assert (dni[mask_active] >= swdirs[mask_active] * 0.99).all()
```

---

## 7. The 1400 W/m² outlier threshold

The solar constant (irradiance at the top of the atmosphere at mean Earth–Sun
distance) is **1361 W/m²**. After atmospheric attenuation, surface DNI cannot
physically exceed ≈ 1000–1200 W/m² in any real location.

The `_report_dni_outliers()` diagnostic function uses **1400 W/m²** as a
conservative reporting threshold:

- Any cell with peak DNI ≥ 1400 W/m² indicates either unphysical
  COSMO-REA6 radiation values or a formula error in `compute_dni`.
- Values between 1200–1400 W/m² are physically marginal but possible in
  extremely dry, high-altitude desert conditions; they are logged as
  warnings but not errors.
- Values above 1361 W/m² (solar constant) are unphysical and should be
  investigated.

The threshold is not applied to clip the data; it is only used for reporting.

---

## 8. cfgrib eccodes variable name mapping

COSMO-REA6 uses its own canonical short names for GRIB attributes. cfgrib
decodes GRIB files using the ECMWF eccodes short-name table, which assigns
different names for some variables:

| COSMO-REA6 name | cfgrib / eccodes name | Description              |
|-----------------|-----------------------|--------------------------|
| `PS`            | `sp`                  | Surface pressure         |
| `H_SNOW`        | `sde`                 | Snow depth equivalent    |
| `SNOW_GSP`      | `lssf`                | Large-scale snowfall     |
| `SNOW_CON`      | `snoc`                | Convective snowfall      |
| `T_2M`          | `2t` or `t2m`         | 2-m air temperature      |
| `U_10M`         | `10u` or `u10`        | U wind component at 10 m |
| `V_10M`         | `10v` or `v10`        | V wind component at 10 m |

Each COSMO-REA6 GRIB file contains **exactly one variable**, so there is no
ambiguity about which data are returned regardless of name. The alias
mapping in `_CFGRIB_ALIASES` (in `transform.py`) handles this transparently.
No user action is required; the mapping is automatic and silent (DEBUG level).

---

## 9. Coordinate system note

cfgrib provides `latitude` and `longitude` as **2-D auxiliary coordinates**
in WGS84 (geographic) projection, derived from the COSMO-REA6 rotated-pole
grid definition embedded in each GRIB file. The Spencer formula uses these
geographic coordinates directly — no coordinate transformation is needed.

Wind vectors (`U_10M`, `V_10M`) are in the rotated-pole frame. Scalar wind
speed `WS_10M = √(U² + V²)` is invariant under rotation and is correct as-is.

---

## 11. Point-wise validation: pvlib closure vs Spencer (`tests/compare_providers.py`)

Section 3 explains why the gridded `compute_dni()` uses Spencer (1971)
instead of pvlib: pvlib's `get_solarposition()` doesn't vectorise across
698,752 cells. That constraint doesn't apply to a **single cell**, so
`tests/compare_providers.py`'s `dni_method_comparison()` cross-checks
COSMO's native DNI/DHI against two independent pvlib-based estimates at
one grid cell for one month:

1. **`DNI_pvlib_closure`** — the same exact closure equation
   `DNI = (GHI - DHI) / cos(θ_z)` from §4.1, using COSMO's own known GHI
   and DHI, but with pvlib's NREL SPA solar position (`pvlib.
   irradiance.complete_irradiance`) instead of Spencer. This isolates
   *only* the solar-position algorithm's contribution — per §2.1, that
   difference should be negligible (Spencer ±0.1–0.3° vs SPA <0.0003°,
   both dwarfed by COSMO's own ~5–10° effective radiation uncertainty).
2. **`DNI_pvlib_dirint`** / **`DHI_pvlib_dirint`** — a DIRINT
   decomposition of GHI *alone* (`pvlib.irradiance.dirint`), blind to
   COSMO's already-known DHI. Per §4.2 this is **not** the right tool
   for COSMO (real DHI is available), so it is *not* used as COSMO's
   alternative DNI — it's included purely as a reference point for the
   error ERA5-Land and MERRA-2 are stuck with, since neither ever stores
   a direct/diffuse split and must decompose GHI to get DNI/DHI at all
   (`providers/era5_land/dni_pointwise.py`,
   `providers/merra2/dni_pointwise.py`).

A live run at an Arctic-edge cell (70.5°N, 25°E, June 2018) measured, at
matched hourly resolution against COSMO's native DNI/DHI:

| Estimate                             | bias (est−native) | MAE   | RMSE  | r      |
| ------------------------------------- | -----------------: | ----: | ----: | -----: |
| `DNI_pvlib_closure` (exact, SPA zenith) |             +0.15 W/m² | 0.90 W/m² |  7.19 W/m² | 0.9992 |
| `DNI_pvlib_dirint` (GHI-only decomp.)  |            +11.53 W/m² | 24.82 W/m² | 43.81 W/m² | 0.9717 |
| `DHI_pvlib_dirint` (GHI-only decomp.)  |             −2.15 W/m² |  8.69 W/m² | 16.87 W/m² | 0.9835 |

This confirms both predictions exactly: the closure formula (same
known GHI/DHI, only the solar-position algorithm differs) reproduces
COSMO's native DNI almost exactly — RMSE 7.19 W/m² is noise-level
against a ~206 W/m² mean DNI at this cell, and r=0.999 leaves essentially
nothing unexplained. DIRINT, forced to guess without the known DHI, is
~6x worse by RMSE — real decomposition-model error, not solar-position
error, exactly as §4.2 predicts. This is also indirect confirmation that
DHI is correctly the diffuse component and DNI the direct one (see the
module docstring's SWDIRS_RAD/SWDIFDS_RAD note): if the two were
swapped, the exact closure formula would not reproduce COSMO's native
DNI this closely.

Both `compute_dni()`'s 5° elevation threshold and its `[1e-3, 1.0]`
`cos(θ_z)` clipping (§5–6) apply equally to the closure-formula
division, since it is the same equation — near-horizon numerical
sensitivity is a property of `1/cos(θ_z)` itself, not of which solar
position feeds it. This matters more at high latitude, where the sun
lingers near the horizon for hours rather than minutes, so more
timesteps sit near the masking threshold than at mid-latitudes.
`dni_method_comparison()` applies the same 5° threshold for a fair,
apples-to-apples comparison against COSMO's native (already-masked) DNI.

### 11.1 Swap test — empirical confirmation of SWDIRS_RAD/SWDIFDS_RAD

Everything above compares two *derivations* against each other — it
never checks either against an independent ground truth. As a targeted
check on one specific claim (that `SWDIRS_RAD` really is the direct
component, not `SWDIFDS_RAD`), the labels were deliberately swapped and
the same exact closure formula re-run: `ds_dhi_swapped = SWDIRS_RAD`
(pretending the direct field is diffuse), `swapped_DNI = (GHI -
ds_dhi_swapped) / cos(θ_z)`. Result, same cell/month as above:

| Labeling | bias | MAE | RMSE | r |
| --- | ---: | ---: | ---: | ---: |
| Correct (SWDIRS_RAD = direct) | +0.15 W/m² | 0.90 W/m² | 7.19 W/m² | 0.9992 |
| Swapped | +174.19 W/m² | 227.32 W/m² | 268.24 W/m² | 0.2201 |

RMSE increases 37x and correlation collapses to near-noise under the
swap — strong empirical confirmation, independent of any documentation
or naming convention, that the current labeling is correct.

### 11.2 Physical plausibility — independent of any cross-method comparison

Two checks against physical law / astronomy rather than another
derivation, at the same cell:

- **Clear-sky / extraterrestrial bound.** COSMO's native DNI never
  exceeded the top-of-atmosphere extraterrestrial irradiance (0/720
  hours in June 2018 — a hard physical impossibility if violated), and
  never exceeded a clear-sky model (pvlib's Ineichen, plus a 50 W/m²
  tolerance) either (also 0/720 hours) — every deviation from clear-sky
  was DNI sitting *below* it, i.e. real cloud attenuation, never above.
- **Seasonal cycle at 70.5°N.** Monthly mean DNI is ~0 W/m² in
  Nov/Dec/Jan (near-total polar night, 0–2.2 daylight hours/day) and
  peaks at 218–231 W/m² in May/July (22–24 daylight hours/day,
  near-continuous midnight sun) — the expected Arctic-latitude
  signature, not a mid-latitude seasonal curve.

Both are consistency-with-physical-law checks, not comparisons against
an independent measured/satellite product.

### 11.3 Pyranometer validation against KNMI (2026-08-24)

The gap noted above is now partly closed. COSMO-REA6 GHI for 2018 was
compared against four KNMI stations, using the free KNMI open-data
hourly API (`https://www.daggegevens.knmi.nl/klimatologie/uurgegevens`,
`vars=Q:T:U`; no key required). KNMI's `Q` is J/cm2 per hour division,
and its hour divisions are hour-ending in UT — the same convention
COSMO uses — so the two series align with no time shift.

| station          | dist   | COSMO | KNMI | GHI bias | r      |
|------------------|--------|-------|------|----------|--------|
| 240 Schiphol     | 1.9 km | 1058  | 1153 | -8.23 %  | 0.9248 |
| 260 De Bilt      | 2.6 km | 1049  | 1137 | -7.75 %  | 0.9319 |
| 344 Rotterdam    | 3.3 km | 1072  | 1156 | -7.29 %  | 0.9252 |
| 280 Eelde        | 2.2 km |  999  | 1114 | -10.33 % | 0.9267 |

(annual GHI, kWh/m2/yr.) Temperature validates far better than
radiation: bias -0.22 to +0.06 degC, r 0.978-0.989.

The GHI deficit is a genuine model bias, not a pipeline defect. Binning
by clear-sky index shows it reverses sign with cloud cover — overcast
+10.5 %, broken -6.5 %, hazy -13.7 %, clear -14.2 % — which a units or
scaling error could not produce. Rectangle and trapezoidal annual sums
agree to the printed digit (both series endpoints are night), so it is
not an integration artefact either.

The same comparison confirms that `SWDIRS_RAD`/`SWDIFDS_RAD`, and hence
`GHI`/`DHI`/`DNI`, are **instantaneous values at the timestamp, not
hourly means** — matching `downloaded_attributes.py`'s declaration.
Compared against the KNMI hour-mean the correlation is 0.8767 with a
debiased RMSE of 113.8 W/m2; compared against the instantaneous value at
the stamp (estimated as the mean of the two adjacent KNMI hour-means) it
is 0.9026 and 99.7 W/m2, and the normalised diurnal shape error halves
(0.0164 vs 0.0328). Consumers integrating sub-daily profiles should use
the trapezoidal rule rather than treating each value as an hour-mean;
annual totals are unaffected.

## 12. References

- Spencer, J. W. (1971). Fourier series representation of the position of
  the sun. *Search*, 2(5), 172.
- Meeus, J. (1998). *Astronomical Algorithms* (2nd ed.). Willmann-Bell.
- Reda, I., & Andreas, A. (2004). Solar position algorithm for solar
  radiation applications. *Solar Energy*, 76(5), 577–589.
  https://doi.org/10.1016/j.solener.2003.12.003
- Maxwell, E. L. (1987). *A quasi-physical model for converting hourly global
  horizontal to direct normal insolation*. SERI/TR-215-3087.
  Solar Energy Research Institute.
- Erbs, D. G., Klein, S. A., & Duffie, J. A. (1982). Estimation of the
  diffuse radiation fraction for hourly, daily, and monthly-average global
  radiation. *Solar Energy*, 28(4), 293–302.
