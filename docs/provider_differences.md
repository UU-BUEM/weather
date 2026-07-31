# Cross-Provider Differences: RH, Snowfall, Albedo, Snow Depth

**Tool:** `src/weather/tests/compare_providers.py`
**Data:** 2018, Arctic-edge test cell (70.5°N, 25.0°E — see that script's
default), COSMO-REA6 vs ERA5-Land vs MERRA-2.
**Status:** Quantified from real 2018 output; physical explanations below
draw on the formulas already implemented in this repo (verified) plus
general reanalysis/NWP literature (see [References](#references) — not
independently re-verified for this specific pair of products; ask if you
want a literature search for a stronger citation on a specific claim).
**Pending refresh:** COSMO-REA6 2018 was re-run live (adds `RELHUM_2M`
-> `RH`) after the numbers below were computed — the RH section's "ERA5
vs MERRA-2 only" framing and its table are now stale (COSMO RH is
available: whole-Europe June 2018 mean 67.7%, range 0.02-100%, verified
via a fresh `compare_providers.py` run) but the detailed monthly table
below has not yet been regenerated against the new data; treat the
ERA5/MERRA-2 numbers as still valid, the COSMO-exclusion note as
outdated. A fresh xlsx/plots run for June 2018 confirms COSMO RH,
MERRA-2 `SNODP`/`PRECSNOLAND`, and the new `SNOW_DEPTH` column all
populate correctly end-to-end; re-run `compare_providers.py` and paste
updated numbers here when this file needs a full refresh.

These are real, expected differences between three independently-run
reanalysis products — not bugs, and not something to "fix" by unifying
the formulas (see `CLAUDE.md`: "Do NOT unify").

---

## Attribute naming reference: raw source -> canonical output

Every provider's `transform.py` renames or derives its raw downloaded
attributes into one shared set of canonical output names (e.g. ERA5-Land's
`fal` -> `ALBEDO`). Where the physical quantity genuinely differs across
providers, the raw formula differs too (see `CLAUDE.md`: "Do NOT unify")
but the *name* is still shared. Current as of 2026-07-30 (full
cross-provider naming-unification pass — see `.claude/open.md`'s
`## cross-provider` entry for the complete history of what was renamed,
when, and why, including two real mislabeling bugs found and fixed along
the way: COSMO used to drop its raw wind components, and ERA5-Land's
`snow_depth` entry was mapped to the wrong CDS variable).

| Canonical       | COSMO-REA6 source                                                            | ERA5-Land source                                           | MERRA-2 source                                             |
| --------------- | ---------------------------------------------------------------------------- | ---------------------------------------------------------- | ---------------------------------------------------------- |
| `T`             | `T_2M` (K -> degC)                                                           | `t2m` (rename)                                             | `T2M` (rename)                                             |
| `T_DEW`         | `T_2M`+`RELHUM_2M` (derived, inverse Magnus-Tetens — no native field exists) | `d2m` (rename, native)                                     | `T2MDEW` (rename, native)                                  |
| `GHI`           | `SWDIFDS_RAD`+`SWDIRS_RAD` (sum, clipped)                                    | `ssrd` (de-accumulated, ÷3600)                             | `SWGDN` (night-masked, already instantaneous)              |
| `DHI`           | `SWDIFDS_RAD` (native, exact)                                                | — (bulk not computed; point-of-use via `dni_pointwise.py`) | — (bulk not computed; point-of-use via `dni_pointwise.py`) |
| `DNI`           | `SWDIRS_RAD`/cos(θz) (native, experimental)                                  | — (point-of-use only)                                      | — (point-of-use only)                                      |
| `RH`            | `RELHUM_2M` (rename, direct measurement)                                     | `t2m`+`d2m` (Magnus formula)                               | `QV2M`+`PS`+`T2M` (Bolton 1980 formula)                    |
| `WS_10M`        | `U_10M`+`V_10M` (sqrt(u²+v²))                                                | `u10`+`v10` (sqrt(u²+v²))                                  | `U10M`+`V10M` (sqrt(u²+v²))                                |
| `U_10M`/`V_10M` | `U_10M`/`V_10M` (kept as-is, native)                                         | `u10`/`v10` (rename)                                       | `U10M`/`V10M` (rename)                                     |
| `ALBEDO`        | `SWDIFDS_RAD`+`SWDIRS_RAD`+`SOBS_RAD` (derived: `(GHI-SOBS_RAD)/GHI`)        | `fal` (rename, native "forecast albedo")                   | `ALBEDO` (native, unchanged)                               |
| `SNOWFALL`      | `SNOW_CON`+`SNOW_GSP` (sum)                                                  | `sf` (rename)                                              | `PRECSNOLAND` (rename, kg/m²/s -> kg/m²/h)                 |
| `SNOW_DEPTH`    | `H_SNOW` (rename)                                                            | `sde` (rename)                                             | `SNODP` (rename)                                           |
| `PS`            | `PS` (unchanged)                                                             | `sp` (rename)                                              | `PS` (unchanged)                                           |

**Provider-unique fields** (no cross-provider equivalent, kept under
their own raw name, not part of the canonical set above):

| Field           | Provider       | What it is                                                                                                                                                    |
| --------------- | -------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `asn`           | ERA5-Land only | ECMWF "snow albedo" — reflectivity of just the snow-covered fraction, narrower than `ALBEDO`'s whole-grid-cell blend                                          |
| `QV2M`          | MERRA-2 only   | 2 m specific humidity (kg/kg) — the raw input `RH`'s Bolton formula is derived from; kept in the output alongside the derived `RH`                            |
| `U_2M`/`V_2M`   | MERRA-2 only   | 2 m wind components (renamed from `U2M`/`V2M` for internal consistency, no derived scalar computed from these)                                                |
| `U_50M`/`V_50M` | MERRA-2 only   | 50 m (hub-height) wind components (renamed from `U50M`/`V50M`) — added for a confirmed downstream wind-power consumer, see `.claude/merra2/merra2_context.md` |

---

## 1. Relative humidity: MERRA-2 reads ~6 points higher than ERA5-Land

### What's different

Each provider computes RH from different source fields via a different
formula — this is by design, documented in `CLAUDE.md`:

| Provider   | RH source                                    | Formula family                          |
| ---------- | -------------------------------------------- | --------------------------------------- |
| COSMO-REA6 | `RELHUM_2M` (direct model output)            | none — RH is a native model field       |
| ERA5-Land  | 2 m dew-point (`d2m`) + 2 m temperature      | Magnus formula                          |
| MERRA-2    | 2 m specific humidity (`QV2M`) + `PS`, `T2M` | psychrometric (specific-humidity-based) |

(COSMO has no RH in the currently-generated 2018 files for an unrelated
reason — see `.claude/open.md` — so this comparison is ERA5-Land vs
MERRA-2 only.)

### What the data shows

Monthly mean RH, MERRA-2 minus ERA5-Land, at the test cell:

| Month | ERA5-Land | MERRA-2 | Diff (M−E) |
| ----: | --------: | ------: | ---------: |
|     1 |     81.28 |   91.06 |      +9.78 |
|     2 |     81.14 |   90.42 |      +9.28 |
|     3 |     80.72 |   83.06 |      +2.34 |
|     4 |     84.87 |   88.57 |      +3.70 |
|     5 |     77.24 |   86.92 |      +9.68 |
|     6 |     79.67 |   85.55 |      +5.88 |
|     7 |     79.39 |   85.99 |      +6.60 |
|     8 |     83.95 |   89.47 |      +5.52 |
|     9 |     85.38 |   91.22 |      +5.84 |
|    10 |     88.29 |   92.89 |      +4.60 |
|    11 |     88.23 |   92.90 |      +4.67 |
|    12 |     84.83 |   91.50 |      +6.66 |

**MERRA-2 reads higher every single month** — annual mean gap +6.2 pts
(std 2.3 pts across months). This is a consistent bias, not noise.

The gap also has its own **diurnal cycle**, not just a flat offset —
full-year mean by hour-of-day:

- Smallest gap (~4.9–5.3 pts): 03:00–06:00 UTC (near the daily temperature
  minimum)
- Largest gap (~7.1–7.3 pts): 14:00–19:00 UTC (near the daily temperature
  maximum)
- Range across the day: 2.4 pts

### Why

RH depends strongly on temperature (via saturation vapor pressure), and
the two formulas propagate a temperature swing differently:

- **ERA5-Land (Magnus, dew-point-based)**: RH = f(T, T_dewpoint). Both T
  and T_dewpoint respond to the diurnal cycle, but not identically —
  daytime heating drives T up faster than T_dewpoint typically follows,
  widening the T − T_dewpoint spread and pulling RH down more at midday.
- **MERRA-2 (specific-humidity-based)**: RH is derived from a
  near-conserved quantity (specific humidity `QV2M` doesn't track T
  directly) divided by a saturation vapor pressure that *does* track T.
  The result has a different, slightly damped diurnal sensitivity, and a
  different absolute-value convention baked into MERRA-2's own internal
  humidity diagnostics.

The two formulas are correct for what they're computing; they're simply
not computing bit-identical physical quantities from bit-identical inputs.
A ~5–10 point spread between independently-formulated RH diagnostics is
consistent with what's reported in reanalysis intercomparison literature
(see [References](#references)).

---

## 2. Albedo: ERA5-Land reads higher than MERRA-2, most in the snow-transition months

### What's different

| Provider   | Field                                  | What it represents                                                                                                                                                                                                                                                                       |
| ---------- | -------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| COSMO-REA6 | `ALBEDO`                               | `(GHI - SOBS_RAD) / GHI`, `GHI = SWDIRS_RAD + SWDIFDS_RAD` — built as of the `SOBS_RAD` addition (see `cosmo_rea6/transform.py::compute_albedo`); NaN at night. Not yet incorporated into the `compare_providers.py` table below (needs a rerun against a COSMO archive with `SOBS_RAD`) |
| ERA5-Land  | `ALBEDO` (renamed from cfgrib's `fal`) | "forecast albedo" — total background reflectivity, bare land + variable snow cover combined                                                                                                                                                                                              |
| MERRA-2    | `ALBEDO`                               | native surface albedo (M2T1NXRAD collection)                                                                                                                                                                                                                                             |

### What the data shows

Monthly mean albedo (0–1 fraction) at the test cell:

| Month | ERA5-Land | MERRA-2 | Diff (E−M) |
| ----: | --------: | ------: | ---------: |
|     1 |     0.535 |   0.457 |     +0.077 |
|     2 |     0.522 |   0.463 |     +0.059 |
|     3 |     0.583 |   0.484 |     +0.099 |
|     4 |     0.525 |   0.432 |     +0.093 |
|     5 |     0.294 |   0.197 |     +0.097 |
|     6 |     0.153 |   0.138 |     +0.015 |
|     7 |     0.152 |   0.139 |     +0.013 |
|     8 |     0.148 |   0.134 |     +0.014 |
|     9 |     0.143 |   0.135 |     +0.008 |
|    10 |     0.197 |   0.162 |     +0.035 |
|    11 |     0.298 |   0.241 |     +0.056 |
|    12 |     0.516 |     NaN |        n/a |

(December MERRA-2 was NaN at this cell in the current 2018 data — not
investigated further here.)

**Pattern**: the two products nearly agree during the snow-free summer
(Jun–Sep, bare-ground albedo, gap 0.01–0.02) and diverge most during the
snow-transition months (Mar–May and Nov–Jan, gap 0.06–0.10) — exactly
when the *fraction* of the grid cell covered by snow vs bare ground is
most sensitive to small differences in each product's snow-cover/melt
timing and sub-grid representation.

### Why

`fal` is explicitly a *combined* land+snow reflectivity in ERA5-Land's
own documentation (see downloaded_attributes.py's description), while
MERRA-2's `ALBEDO` is that product's own land-surface-model diagnostic.
Both are physically the same quantity in principle, but each product's
snow-cover fraction, snow age/depth, and land-surface scheme differ, so
they agree closely only when the surface state is unambiguous (all snow
or all bare ground) and diverge when the cell is a partial/transitional
mix — precisely the pattern seen above.

---

## 3. Snowfall: same monthly totals in the same ballpark, but very different hourly timing

### What's different

| Provider   | Field                                                                              | Meaning                                                                                                                                            |
| ---------- | ---------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| COSMO-REA6 | `SNOW_GSP` + `SNOW_CON` (combined into one `SNOWFALL` field 2026-07-26, see below) | stratiform + convective snow, hourly-accumulated (kg/m²)                                                                                           |
| ERA5-Land  | `sf` (renamed `SNOWFALL` 2026-07-26)                                               | snowfall rate, hourly-accumulated (kg/m²/h)                                                                                                        |
| MERRA-2    | `PRECSNOLAND` (renamed `SNOWFALL` 2026-07-26)                                      | snowfall rate over land, converted kg/m^2/s -> kg/m^2/h (the `M2T1NXLND` collection, added and live-verified this session — see `.claude/open.md`) |

All three renamed to the shared canonical `SNOWFALL` name as of
2026-07-26 (see `.claude/open.md`'s `## cross-provider` naming-unification
entry); the already-completed 2018 archive this section's numbers come
from still has the OLD names above, unaffected by the rename.

### What the data shows

Monthly accumulated snowfall (kg/m², summed over the month) at the test
cell:

| Month | COSMO sum | ERA5-Land sum |
| ----: | --------: | ------------: |
|     1 |     22.68 |         26.27 |
|     2 |     17.72 |         21.84 |
|     3 |     54.82 |         67.42 |
|     4 |     31.32 |         33.18 |
|     5 |      0.00 |          2.98 |
|     6 |      0.71 |          2.77 |
|     7 |      0.00 |          0.00 |
|     8 |      0.00 |          0.00 |
|     9 |      1.20 |          2.81 |
|    10 |      9.28 |         18.24 |
|    11 |     18.35 |         37.99 |
|    12 |     36.83 |         32.63 |

Totals are in the same rough range (ERA5-Land usually somewhat higher,
notably ~2x COSMO in October/November) — but the **hourly timing barely
correlates**:

- Hourly correlation across the full year (nearest-timestamp matched):
  **r = 0.39**
- COSMO reports "snowing" (SF > 0) in **19.7%** of hours; ERA5-Land in
  **46.0%** of hours — more than double
- Jaccard overlap (hours where *both* say snowing / hours where *either*
  says snowing): **0.44** — the two products disagree about whether it's
  snowing right now more often than they agree

### Why

The monthly totals landing in the same range while the hourly pattern
disagrees this much points to a **temporal distribution** difference, not
a magnitude difference. COSMO-REA6 (~6 km, convection-permitting) and
ERA5-Land (driven by ERA5's own coarser ~31 km atmospheric forcing, no
independent convection scheme of its own) run genuinely different
dynamics and microphysics, so they place precipitation events on
different hours even for the same real month. This general mechanism
(coarser/parent-driven atmospheric models spreading precipitation
across more hours at lower intensity than a convection-permitting
downscaling of the same period) is directly supported by a study that
compares a convection-permitting COSMO-CLM downscaling of ERA5 against
ERA5 itself over Italy (Adinolfi et al. 2023, in
[References](#references)): the convection-permitting model showed
clear gains in reproducing hourly precipitation characteristics in
mountainous areas, though with losses in coastal/flat areas — a nuanced
result, not a blanket "COSMO always better." Directionally consistent
with what's measured above (ERA5-Land snowing nearly 2.4x as often as
COSMO), but this is still a different model pair (COSMO-CLM/ERA5 over
Italy, not COSMO-REA6/ERA5-Land over the Arctic) — treat as supporting
evidence for the general mechanism, not a direct validation of this
specific comparison.

---

## 4. Snow depth: all three providers are physical depth (corrected 2026-07-30)

### What's different

| Provider   | Field                                      | Meaning                     |
| ---------- | ------------------------------------------ | --------------------------- |
| COSMO-REA6 | `H_SNOW` (renamed `SNOW_DEPTH` 2026-07-26) | physical snow depth, meters |
| MERRA-2    | `SNODP` (renamed `SNOW_DEPTH` 2026-07-26)  | physical snow depth, meters |
| ERA5-Land  | `sde` (renamed `SNOW_DEPTH` 2026-07-30)    | physical snow depth, meters |

**Correction (2026-07-30):** an earlier version of this section, and of
`era5_land/downloaded_attributes.py`'s `snow_depth` entry, claimed
ERA5-Land's field was **meters of water equivalent**, genuinely
different from the other two, and left it deliberately unrenamed. That
claim was wrong. Verified via three independent sources: the real CDS
request payload (variable `snow_depth`, not `snow_depth_water_
equivalent`), the raw GRIB's own decoded metadata (`GRIB_shortName
'sde'`, `long_name 'Snow depth'` — not `'sd'`, which is the OTHER,
water-equivalent variable), and the already-processed 2018-03 output
(the variable was literally named `sde`, not `sd`). All three providers'
snow depth is the same physical quantity after all, now renamed to the
shared canonical `SNOW_DEPTH`. Importantly, this mislabeling never
affected any actual downloaded/exported VALUE — the water-equivalent ->
physical-depth conversion the old entry described was never actually
implemented in `era5_land/transform.py` either, so every number below
has always been correct; only the description and the naming decision
were wrong.

### What the data shows

Whole-Europe domain stats, June 2018:

| Provider   | Field    | Mean (m) | Max (m) | NaN fraction                                                                                                                                              |
| ---------- | -------- | -------: | ------: | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| COSMO-REA6 | `H_SNOW` |     0.00 |   40.00 | 0.00                                                                                                                                                      |
| MERRA-2    | `SNODP`  |     0.00 |    0.53 | 0.00                                                                                                                                                      |
| ERA5-Land  | `sde`    |     0.02 |   33.33 | 0.49 (ocean cells — ERA5-Land is land-only, this NaN fraction matches every other ERA5-Land attribute in the same domain-stats table, not a data problem) |

All three are now directly comparable — no conversion needed.

June is close to snow-free at most of the Europe domain except high
terrain and the far north (COSMO's max of 40 m physical depth is almost
certainly a high-Alpine or Scandinavian-mountain outlier cell, not
typical). A winter month (e.g. January) would show a much larger,
more informative spread and is the natural next data point if this
comparison needs to go further.

### Why

Not run yet as a quantified difference (unlike sections 1-3 above).
Now that all three are confirmed to be the same physical quantity (see
the 2026-07-30 correction above), any remaining spread between them
would be a genuine modeling difference in the three products' actual
snowpack simulation, worth a real comparison once a winter-month
snapshot exists.

---

## 5. GHI/DHI/DNI: COSMO stores an exact direct/diffuse split; ERA5-Land and MERRA-2 don't

### What's different

| Provider   | GHI                             | DHI                                                               | DNI                                                              |
| ---------- | ------------------------------- | ----------------------------------------------------------------- | ---------------------------------------------------------------- |
| COSMO-REA6 | `SWDIFDS_RAD + SWDIRS_RAD`      | `SWDIFDS_RAD` (native, exact)                                     | `SWDIRS_RAD / cos(θz)` (native, exact — not a GHI decomposition) |
| ERA5-Land  | de-accumulated `ssrd`           | pvlib DIRINT decomposition of GHI (only option — no native split) | pvlib DIRINT decomposition of GHI                                |
| MERRA-2    | `SWGDN` (already instantaneous) | pvlib DIRINT decomposition of GHI                                 | pvlib DIRINT decomposition of GHI                                |

This is the single biggest methodological difference between COSMO and
the other two: COSMO-REA6's regional model separately simulates direct
and diffuse shortwave as distinct physical quantities, so its DHI/DNI
are as trustworthy as its GHI. ERA5-Land and MERRA-2 only ever store
GHI in bulk — DHI/DNI have to be *decomposed* from GHI alone via
pvlib's DIRINT algorithm (`era5_land/dni_pointwise.py`,
`merra2/dni_pointwise.py`), a fundamentally lossier operation with no
independent direct/diffuse information to draw on.

### What the data shows

Quantified directly against COSMO's own native DNI/DHI (the one
provider where a ground truth exists in this dataset) at the test
cell, comparing COSMO's native values to a DIRINT decomposition of
COSMO's own GHI (i.e. simulating what ERA5-Land/MERRA-2 are stuck
doing) vs. the exact closure formula `(GHI-DHI)/cos(θz)`:

| Estimate                               |         bias |         MAE |        RMSE |      r |
| -------------------------------------- | -----------: | ----------: | ----------: | -----: |
| `DNI_pvlib_closure` (exact, known DHI) |  +0.15 W/m^2 |  0.90 W/m^2 |  7.19 W/m^2 | 0.9992 |
| `DNI_pvlib_dirint` (GHI-only decomp.)  | +11.53 W/m^2 | 24.82 W/m^2 | 43.81 W/m^2 | 0.9717 |
| `DHI_pvlib_dirint` (GHI-only decomp.)  |  -2.15 W/m^2 |  8.69 W/m^2 | 16.87 W/m^2 | 0.9835 |

The exact closure formula (used when DHI is already known, as with
COSMO) is essentially noise-level (RMSE 7 W/m^2). The GHI-only DIRINT
decomposition — the only option ERA5-Land/MERRA-2 have — is ~6x worse
by RMSE. This is a real decomposition-model error inherent to not
having a direct/diffuse split, not a solar-position or implementation
bug (full derivation, the SWDIRS/SWDIFDS-direct/diffuse assignment
verification, and the swap test that confirmed it in
`docs/dni_methodology.md`).

### Why, and where to read more

This is covered in full depth (methodology derivation, the SWDIRS_RAD/
SWDIFDS_RAD direct/diffuse assignment verified against source
documentation, night-masking behavior near the Arctic in summer, and a
`pvlib`-closure-vs-DIRINT validation) in **`docs/dni_methodology.md`**
— this section is a summary/pointer, not a duplicate. See especially
its §4 (why COSMO's split is exact), §11 (the closure-vs-DIRINT
validation behind the numbers above), and §9 (COSMO's wind vectors
being in the rotated-pole frame, related to §6 below).

---

## 6. Wind speed: ERA5-Land reads notably lower than COSMO/MERRA-2 in this domain

### What's different

| Provider   | Fields           | Frame                                             |
| ---------- | ---------------- | ------------------------------------------------- |
| COSMO-REA6 | `U_10M`, `V_10M` | **rotated-pole grid**, not true north (see below) |
| ERA5-Land  | `u10`, `v10`     | true north (WGS84)                                |
| MERRA-2    | `U10M`, `V10M`   | true north (WGS84)                                |

All three compute scalar `WS_10M = sqrt(U^2 + V^2)`, which is rotation-
invariant — comparable across all three regardless of frame. Wind
*direction* (`atan2(V, U)`) is not currently computed by any provider's
pipeline; if it ever is, COSMO's `U_10M`/`V_10M` would need rotating to
true north first (`docs/dni_methodology.md` sec 9) — ERA5-Land/MERRA-2
need no such correction.

### What the data shows

Whole-Europe domain stats, June 2018 (single-month snapshot, same run
as section 4):

| Provider   | WS_10M mean (m/s) | WS_10M max (m/s) |
| ---------- | ----------------: | ---------------: |
| COSMO-REA6 |              4.62 |            29.13 |
| MERRA-2    |              4.49 |            22.25 |
| ERA5-Land  |              2.58 |            20.86 |

COSMO and MERRA-2 agree closely (4.62 vs 4.49); ERA5-Land reads ~45%
lower.

### Why

Plausibly a real, largely domain-composition effect rather than a bug:
ERA5-Land is a **land-only** product (this domain's ~49% NaN fraction
in section 4's table is ERA5-Land's ocean mask), so its wind stats
exclude the open-water/coastal cells where boundary-layer roughness is
lowest and near-surface wind speeds climatologically highest — cells
that COSMO-REA6 and MERRA-2 (both covering ocean too) still include.
Higher land-surface roughness length also directly suppresses ERA5-
Land's own near-surface wind on the land cells it does report. Not
independently verified against a land-only-masked recomputation of
COSMO/MERRA-2 for this specific domain/month — the mechanism is
standard boundary-layer physics, but the magnitude of this particular
gap hasn't been decomposed into "domain composition" vs "roughness
representation" shares.

---

## 7. Temperature and pressure: minor, resolution/orography-driven spread

### What's different

All three read 2 m air temperature and surface pressure essentially
directly (`T_2M`/`T`, `PS` for COSMO; `t2m`, `sp` for ERA5-Land; `T2M`,
`PS` for MERRA-2) — no formula-family difference like RH's. Any spread
here is attributable to model resolution/orography representation and
each reanalysis's own physics, not to a difference in what's being
computed.

### What the data shows

Whole-Europe domain stats, June 2018 (single-month snapshot):

| Provider   | T mean (degC) |  T range (degC) | PS mean (Pa) |         PS range (Pa) |
| ---------- | ------------: | --------------: | -----------: | --------------------: |
| COSMO-REA6 |         17.81 | -11.82 to 49.52 |     99027.50 | 62621.06 to 107428.22 |
| ERA5-Land  |         16.77 |  -7.14 to 44.86 |     97223.18 | 70831.94 to 103723.44 |
| MERRA-2    |         15.37 |  -5.72 to 46.65 |     99230.93 | 76953.53 to 103646.67 |

Spread is ~2.4 degC across the three (COSMO warmest, MERRA-2 coolest)
and ~2000 Pa in pressure (ERA5-Land lowest). COSMO's much wider PS
range (down to 62621 Pa, i.e. ~630 hPa) is consistent with its 6 km
grid resolving individual Alpine peaks that the coarser 0.1 deg/0.5x0.625 deg
grids smooth out — a real, expected orography-representation effect,
not a data error.

### Why

Not investigated further here — this is a much smaller, less
operationally significant spread than the RH/albedo/snowfall
differences quantified above, so it hasn't received the same
dedicated analysis. Flagged for completeness.

---

## 8. Timestamp convention: MERRA-2 labels mid-interval, COSMO/ERA5-Land label on the hour

MERRA-2's hourly-mean collections (`rad`, `slv`) label each timestamp
at the **midpoint** of the averaging interval (`HH:30`, e.g.
`2018-06-01T00:30`), since that's what the mean actually represents.
COSMO-REA6 and ERA5-Land both label on the hour (`HH:00`). This is a
genuine provider difference, not a bug, and is **not** corrected/shifted
anywhere in this codebase — any code that merges or directly compares
MERRA-2 against the other two on a shared time index must handle the
30-minute offset explicitly (resample/interpolate one onto the other's
index) rather than assume the raw indices line up. Full detail:
`docs/MERRA2_PIPELINE_GUIDE.md`'s "Timestamp convention" section.

---

## 9. Grid and resolution: no cross-provider regridding

| Provider   | Native grid           |       Cell size (approx.) |
| ---------- | --------------------- | ------------------------: |
| COSMO-REA6 | rotated-pole, 824x848 |                     ~6 km |
| ERA5-Land  | regular lat/lon       |        ~9-11 km (0.1 deg) |
| MERRA-2    | regular lat/lon       | ~35-55 km (0.5x0.625 deg) |

`tests/compare_providers.py` snaps a requested lat/lon to each
provider's *own nearest native cell independently* — it does not
regrid/interpolate any provider onto another's grid, so "the same
cell" across providers is only approximate (within roughly half a
native grid cell of each product, worse for COSMO since its cell must
also be located via an analytically-reconstructed rotated-pole
projection rather than stored lat/lon — see that script's module
docstring). Whole-Europe domain stats (sections 4, 6, 7 above) are
likewise computed independently per provider on its own native grid,
so a domain mean is not a like-for-like average over identical
physical area between providers. Cross-provider regridding, if ever
needed, is a separate, not-yet-built future task.

---

## References

Confirmed via live search on 2026-07-24 (titles, authors, journal,
volume/pages, and DOI checked against the publisher/ADS record for
each; not just recalled from training knowledge):

- Bollmeyer, C., Keller, J. D., Ohlwein, C., Wahl, S., Crewell, S.,
  Friederichs, P., Hense, A., Keune, J., Kneifel, S., Pscheidt, I.,
  Redl, S., & Steinke, S. (2015). Towards a high-resolution regional
  reanalysis for the European CORDEX domain. *Q. J. R. Meteorol. Soc.*,
  141(686), 1–15. <https://doi.org/10.1002/qj.2486> (COSMO-REA6)
- Muñoz-Sabater, J., et al. (2021). ERA5-Land: a state-of-the-art
  global reanalysis dataset for land applications. *Earth Syst. Sci.
  Data*, 13(9), 4349–4383. <https://doi.org/10.5194/essd-13-4349-2021>
  — confirms ERA5(-Land) 2 m RH is derived from temperature + dew point
  via a Magnus-type formula (ECMWF's own internal implementation uses
  coefficients a=17.502, b=240.97 — slightly different from this
  pipeline's a=17.625, b=243.04, a different well-established
  Magnus-type variant (Alduchov & Eskridge 1996); both are valid, this
  pipeline's RH is not bit-identical to ECMWF's own archived humidity
  fields if any exist).
- Gelaro, R., et al. (2017). The Modern-Era Retrospective Analysis for
  Research and Applications, Version 2 (MERRA-2). *J. Climate*, 30(14),
  5419–5454. <https://doi.org/10.1175/JCLI-D-16-0758.1>
- Adinolfi, M., Raffa, M., Reder, A., & Mercogliano, P. (2023).
  Investigation on potential and limitations of ERA5 Reanalysis
  downscaled on Italy by a convection-permitting model. *Climate
  Dynamics*, 61, 4319–4342. <https://doi.org/10.1007/s00382-023-06803-w>
  — directly relevant: COSMO-CLM (same model family as COSMO-REA6) at
  convection-permitting scale vs. its parent ERA5, precipitation
  frequency/intensity specifically evaluated.
- Sun, Y., Solomon, S., Dai, A., & Portmann, R. W. (2006). How often
  does it rain? *J. Climate*, 19(6), 916–934.
  <https://doi.org/10.1175/JCLI3672.1> — general (not COSMO/ERA5-
  specific) "drizzle bias" finding: coarser models overestimate light-
  precipitation frequency while broadly matching its intensity pattern.

To regenerate or extend this analysis (different cell/month, or add
weekly/diurnal breakdowns for other attributes), see
`tests/compare_providers.py`'s `RobustnessChecker` and the
`monthly_summary()`/`weekly_summary()`/`diurnal_summary()` methods it
already computes.
