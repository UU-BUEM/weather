# docs/ — Documentation Index

Supplementary documentation for the `weather` package: COSMO-REA6,
ERA5-Land and MERRA-2 pipelines, the `weather fetch`/`geo`/`serve`
tools, and the methodology behind derived fields and percentile years.
All files are Markdown; linting rules are in `/.markdownlint.json`
(line_length = 100, tables exempted; MD060 table alignment is on by
default).

---

## Archive status (2026-08)

| Provider   | Coverage           | Monthly files | Percentile mosaics | Notes                                    |
| ---------- | ------------------ | ------------- | ------------------ | ---------------------------------------- |
| COSMO-REA6 | 1995-01 .. 2019-08 | 296           | 36                 | DWD publishes nothing after 2019-08      |
| ERA5-Land  | 1950-01 .. 2025-12 | 912           | 36                 | still on legacy variable names           |
| MERRA-2    | 1980-01 .. 2025-12 | 552           | 36                 | canonical names, real `T2MDEW` → `T_DEW` |

All three archives on `sd26` carry CF metadata (`metadata_repair.py`).

---

## Files in this folder

### Using the pipelines

| File                                                       | Purpose                                                                                          |
| ---------------------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| [WEATHER_FETCH_GUIDE.md](WEATHER_FETCH_GUIDE.md)           | `weather fetch` — the unified CLI: date ranges, concatenation, percentiles, country/bbox scoping |
| [parallelization.md](parallelization.md)                   | What `--ncores` really controls per provider, recommended core counts, memory/disk, tuning       |
| [BULK_RUN_GUIDE_ERA5-LAND.md](BULK_RUN_GUIDE_ERA5-LAND.md) | ERA5-Land multi-year run: CDS queue bottleneck, `scripts/run_era5_bulk.sh`, disk budget          |
| [BULK_RUN_GUIDE_MERRA2.md](BULK_RUN_GUIDE_MERRA2.md)       | MERRA-2 multi-year run: OPeNDAP concurrency, `scripts/run_merra2_bulk.sh`, disk budget           |
| [MERRA2_PIPELINE_GUIDE.md](MERRA2_PIPELINE_GUIDE.md)       | MERRA-2 collections/attributes, Earthdata auth, timestamp convention, derived fields             |
| [DOWNLOAD_AND_LOGGING.md](DOWNLOAD_AND_LOGGING.md)         | ERA5-Land parallel byte-range download, server logging with tmux/tee, pipeline order             |
| [WEATHER_GEO_GUIDE.md](WEATHER_GEO_GUIDE.md)               | `weather geo {list,crop}` — post-hoc country-bbox cropping of an exported NetCDF                 |
| [qa.md](qa.md)                                             | Frequently asked questions — percentile method, night masking, file layout, disk usage           |
| [debugging.md](debugging.md)                               | Common runtime errors and fixes (incl. DWD 503 storms, OOM, cfgrib quirks)                       |

### Methodology and data quality

| File                                                   | Purpose                                                                                             |
| ------------------------------------------------------ | --------------------------------------------------------------------------------------------------- |
| [percentile_methodology.md](percentile_methodology.md) | P10/P50/P90 representative-month algorithm, the fixed 2026-08 selection bug, verified results       |
| [dni_methodology.md](dni_methodology.md)               | Spencer solar position, DNI/DHI formulas, pvlib DIRINT, KNMI pyranometer validation                 |
| [provider_differences.md](provider_differences.md)     | Raw → canonical name map, quantified cross-provider differences, accuracy vs measured KNMI data     |
| [cdo_crop_cf_metadata.md](cdo_crop_cf_metadata.md)     | `weather geo crop`/CDO grid-detection bug: missing CF lat/lon attributes, fix and retroactive patch |

### Contributing

| File                                         | Purpose                                     |
| -------------------------------------------- | ------------------------------------------- |
| [git-push-workflow.md](git-push-workflow.md) | Local push helper scripts and message files |

---

## Recommended reading order for new users

1. **[WEATHER_FETCH_GUIDE.md](WEATHER_FETCH_GUIDE.md)** — the one command
   you most likely need.
2. **[parallelization.md](parallelization.md)** — read §1 before any large
   run; COSMO's `--ncores` is also its DWD connection count.
3. **[qa.md](qa.md)** — answers the most common questions.
4. **[debugging.md](debugging.md)** — if something goes wrong, check here first.
5. **[provider_differences.md](provider_differences.md)** — which provider
   to use, and why their numbers differ.
6. **[percentile_methodology.md](percentile_methodology.md)** and
   **[dni_methodology.md](dni_methodology.md)** — methodology background.

---

## Related resources

- Root `README.md` — quick-start installation and run instructions.
- `CLAUDE.md` and `.claude/open.md` — project history and open items.
- `data/validation/NL/` — KNMI validation reports (CSV + Markdown).
- `src/weather/tests/README.md` — which test script to run and in what order.
- `src/weather/common/README.md` — what each shared utility module does.
- `src/weather/providers/README.md` — provider pattern, how to add a new provider.
