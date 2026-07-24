# MERRA-2 bulk-run guidance and launch scripts

## The key insight: OPeNDAP has no per-account queue, so this is a different bottleneck than ERA5

MERRA-2 is fetched via **OPeNDAP** (server-side spatial subsetting — no
global file is ever downloaded, only the configured Europe box) from NASA
GES DISC, not via a CDS-style request/queue system. That changes the whole
tuning story relative to ERA5-Land:

- No per-account concurrent-job cap to route around — `MERRA2_OPENDAP_MAX_CONCURRENT`
  (default 8) can simply be raised, no "queue position" to fight over.
- Files are per-**day**, not per-month (3 collections x ~30 days/month),
  so a year is ~1095 small OPeNDAP requests rather than ERA5-Land's 12
  large GRIB downloads — many more requests, each individually much
  cheaper.
- Measured this session (2018, `lnd` collection only — `rad`/`slv` already
  cached): 372 daily files downloaded in 134.5 s; transform+export for
  all 12 months took 20.4 s. Even a **fresh** year (all 3 collections,
  ~1095 files) is expected to be on the order of minutes, not the
  CDS-queue-dominated tens-of-minutes-per-month ERA5-Land sees.
- Net effect: MERRA-2's bulk run is much less dominated by a single
  external bottleneck than ERA5-Land's CDS queue is. The main levers are
  ordinary I/O concurrency (`MERRA2_OPENDAP_MAX_CONCURRENT`) and how many
  years you run at once (`--parallel-years`), not "how many accounts can
  I split this across."

--------------------------------------------------------------------

## Recommended run mode on the Linux server

### 1. tmux via the wrapper script (preferred)

`scripts/run_merra2_bulk.sh` wraps `test_merra2_multi_year.py` with conda
activation, `PYTHONPATH`, a timestamped log file, and an automatic
`verify_merra2_months.py` QA pass over the whole archive afterward
(mirrors `scripts/run_era5_bulk.sh` — see that script's header for the
one real structural difference: MERRA-2 has no boundary-repair step,
since `SWGDN` is already instantaneous, not accumulated):

```bash
tmux new -s merra2
conda activate weather_env
export MERRA_WORK_DIR=/data/soma/merra2
export MERRA2_AREA=72,-11,34,32
export MERRA2_OPENDAP_MAX_CONCURRENT=12   # no per-account queue -- raise freely

bash scripts/run_merra2_bulk.sh \
    --from-year 1980 --to-year 2025 \
    --ncores 80 --parallel-years 6 \
    --resume

# detach: Ctrl-b then d      reattach: tmux attach -t merra2
```

Before your first bulk run, read the pre-flight checklist in
`docs/MERRA2_PIPELINE_GUIDE.md`'s "Bulk multi-year run" section — in
particular, **sync your code first**: this session's `export_netcdf`
skip-if-exists bug fix must be on the server before a fresh run,
otherwise any month whose output already exists (e.g. from a prior
partial attempt) will silently fail to update.

### 2. nohup (fire-and-forget, no wrapper script)

```bash
nohup python src/weather/tests/test_merra2_multi_year.py \
    --from-year 1980 --to-year 2025 \
    --ncores 80 --parallel-years 6 --resume \
    > merra2_bulk.log 2>&1 &
tail -f merra2_bulk.log
```

This skips the wrapper's automatic `verify_merra2_months.py` pass — run
that manually afterward if you use this mode.

--------------------------------------------------------------------

## Parallelization strategy — what actually helps, and what does not

### Helps: `MERRA2_OPENDAP_MAX_CONCURRENT`

Directly controls per-year download concurrency. No CDS-style
per-account cap exists server-side, so this can be raised more freely
than ERA5-Land's `ERA5_CDS_MAX_CONCURRENT` — but it is still real load
against a shared NASA server; be a considerate user, and watch the first
hour of logs for repeated timeouts/retries before pushing it much past
the default of 8-12.

### Helps: `--parallel-years`

Each parallel year runs its own `download_all()` (up to
`MERRA2_OPENDAP_MAX_CONCURRENT` requests) and its own transform
`ProcessPoolExecutor`. Running N years at once multiplies *total*
concurrent OPeNDAP requests by N — e.g. `--parallel-years 6` at the
default `MERRA2_OPENDAP_MAX_CONCURRENT=8` means up to 48 concurrent
requests server-wide. Not tested at that scale in this codebase; start
with a small trial range (e.g. `--from-year 2015 --to-year 2018`)
before committing to the full multi-decade range unattended.

### Helps only up to a point: `--ncores`

The transform phase parallelizes across months within a year
(`ProcessPoolExecutor`, capped at 12 workers/year — one per month).
Cores beyond `12 x parallel-years` are wasted, not harmful. MERRA-2's
own transform step is fast (20.4 s for 12 months in this session's
test) — this pipeline is I/O-bound, not compute-bound, so don't
over-provision cores at the expense of `--parallel-years`.

### Does NOT apply here: "split across multiple accounts"

ERA5-Land's biggest lever (multiple CDS accounts, each with its own
queue slot) doesn't have a MERRA-2 analog — there is no per-account
queue to route around via a second Earthdata login. One account, one
`MERRA2_OPENDAP_MAX_CONCURRENT` setting, is the whole story.

--------------------------------------------------------------------

## Disk budget

MERRA-2's Europe-cropped 0.5 deg x 0.625 deg grid is far smaller than
ERA5-Land's 0.1 deg crop of the same box. Measured this session: a full
2018 (12 months, 3 collections) output totaled well under 1.2 GB
(individual monthly files 85-100 MB). Scaling to the full 1980-2025
range (46 years) puts the final NetCDF archive at roughly 40-50 GB --
trivial against `sd26`'s 15 TB, and smaller than even a single year of
COSMO-REA6's raw downloads. With `MERRA_CLEANUP=false` (the default --
see `.claude/open.md`'s cleanup-centralization entry), daily source
files are kept too; still a modest total given each daily file is a
small Europe-cropped NetCDF4, not a global grid.
