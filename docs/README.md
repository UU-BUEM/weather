# docs/ — Documentation Index

Supplementary documentation for the COSMO-REA6 weather pipeline.
All files are Markdown; linting rules are in `/.markdownlint.json`
(line_length = 100, tables exempted).

---

## Files in this folder

| File | Purpose |
| --- | --- |
| [qa.md](qa.md) | Frequently asked questions — TMY methodology, night masking, file layout, disk usage |
| [debugging.md](debugging.md) | Common runtime errors and fixes |
| [parallelization.md](parallelization.md) | Architecture of the parallel pipeline, memory/disk footprint, tuning guide |
| [percentile_methodology.md](percentile_methodology.md) | Mathematical description of the P10/P50/P90 representative-year algorithm |
| [dni_methodology.md](dni_methodology.md) | Spencer formula, pvlib DIRINT, irradiance decomposition rationale |
| [git-push-workflow.md](git-push-workflow.md) | Branch and push conventions for contributors |

---

## Recommended reading order for new users

1. **[parallelization.md](parallelization.md)** — start here to understand
   the three-phase pipeline architecture before running anything.
2. **[qa.md](qa.md)** — answers the most common questions before and after
   your first run.
3. **[debugging.md](debugging.md)** — if something goes wrong, check here first.
4. **[percentile_methodology.md](percentile_methodology.md)** — background
   on the TMY selection algorithm (optional, for methodology review).
5. **[dni_methodology.md](dni_methodology.md)** — background on solar
   irradiance decomposition (optional, for methodology review).

---

## Related resources

- Root `README.md` — quick-start installation and run instructions.
- `src/weather/tests/README.md` — which test script to run and in what order.
- `src/weather/common/README.md` — what each shared utility module does.
- `src/weather/providers/README.md` — provider pattern, how to add a new provider.
