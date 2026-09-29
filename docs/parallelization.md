# Parallelization, Core Counts and Performance

How each provider's pipeline uses cores, what `--ncores` actually controls,
and how to size a run on `sd26` (94 cores, 1 TB RAM). COSMO-REA6 gets the
most detail because it is the only provider whose download fan-out is tied
to `--ncores`, and the only one that is CPU-heavy.

For the DNI-specific vectorization over the spatial grid using the Spencer
solar-position formula see [dni_methodology.md](dni_methodology.md) §3.

---

## 1. TL;DR — recommended settings

| Provider   | Recommended                               | Why                                                       |
| ---------- | ----------------------------------------- | --------------------------------------------------------- |
| COSMO-REA6 | `--ncores 12`, `--parallel-years 1`       | `--ncores` = simultaneous DWD connections; 90 caused 503s |
| ERA5-Land  | `--ncores 6`, `ERA5_CDS_MAX_CONCURRENT=1` | CDS queue is the bottleneck (1 active job per account)    |
| MERRA-2    | `--ncores 12 x parallel-years`            | transform is capped at 12 months per year; rest is idle   |

**Do not run COSMO-REA6 with `--ncores 80`/`90`/`94`.** Older versions of
this document and several script docstrings used those values because
`--ncores` was assumed to be a pure CPU budget. It is not — see §3.

---

## 2. What `--ncores` controls, per provider

| Provider   | Download concurrency                       | Decompress                     | Transform + export                   |
| ---------- | ------------------------------------------ | ------------------------------ | ------------------------------------ |
| COSMO-REA6 | **`min(tasks, ncores)` HTTPS threads**     | `min(tasks, ncores)` processes | dask threads — **not** `ncores` (§4) |
| ERA5-Land  | `ERA5_CDS_MAX_CONCURRENT` (CDS jobs)       | —                              | `min(ncores, months)` processes      |
| MERRA-2    | `MERRA2_OPENDAP_MAX_CONCURRENT` (per year) | —                              | `min(ncores, months)` processes      |

`tasks` for COSMO is `months x attributes` — 12 x 11 = **132** for a full
year (11 raw attributes in `downloaded_attributes.py`: `H_SNOW`, `PS`,
`RELHUM_2M`, `SNOW_CON`, `SNOW_GSP`, `SOBS_RAD`, `SWDIFDS_RAD`,
`SWDIRS_RAD`, `T_2M`, `U_10M`, `V_10M`).

Defaults when neither `--ncores` nor an env var is set: COSMO `4`
(`COSMO_NCORES` → `SLURM_CPUS_PER_TASK` → 4); ERA5-Land and MERRA-2
`os.cpu_count()` (`ERA5_NCORES`/`MERRA_NCORES` → `SLURM_CPUS_PER_TASK` →
`os.cpu_count()`).

The multi-year scripts (`test_<provider>_multi_year.py`) give each year
`ncores // parallel_years`, and run each year as its own subprocess.

---

## 3. Why high `--ncores` breaks COSMO-REA6

`providers/cosmo_rea6/pipeline.py` uses one number, `ncores`, for three
different resources:

```text
Phase 1 download         ThreadPoolExecutor(min(132, ncores))   → DWD HTTPS
Phase 1 verify           ThreadPoolExecutor(min(132, ncores))   → DWD HEAD requests
Phase 2 decompress       ProcessPoolExecutor(min(132, ncores))  → local CPU
```

At `--ncores 90` that is ~90 simultaneous connections to
`opendata.dwd.de` from one IP. In the 2026-08 production rebuild on
`sd26` this produced a storm of `503 Service Temporarily Unavailable`
responses; retries (`COSMO_MAX_RETRIES`, default 10) just re-hit the
overloaded server. The run was relaunched at `--ncores 12` and completed.

`--parallel-years` does not help: each year gets `ncores // P` download
threads, so the total number of DWD connections is still ≈ `ncores`.

Throughput is not lost at 12, because:

- the transform phase — the dominant cost — is **not** limited by
  `ncores` (§4), so it still uses every core;
- DWD is the download bottleneck, not local threads;
- 12 decompress processes x `COSMO_THREADS_PER_JOB=4` lbzip2 threads ≈ 48
  threads, which keeps decompression well fed.

There is no separate download-concurrency knob for COSMO today (ERA5-Land
and MERRA-2 have one). Until there is, keep `--ncores` ≤ ~16 for any run
that downloads from DWD. A run with `--skip-download` can use more (for
decompression), but gains little.

---

## 4. Transform: dask worker count is NOT set by `--ncores`

`run_pipeline()` transforms months sequentially with lazy dask arrays.
It never calls `dask.config.set(num_workers=...)` — the only COSMO call
that does is in `transform.build_annual_dataset()`, which the pipeline
does not use. (The old monolithic `test_cosmo_one_year.py` set it; that
was lost when the pipeline moved into the provider package.) So dask's
threaded scheduler uses its default pool: **one thread per visible CPU**
(94 on `sd26`), regardless of `--ncores`.

Consequences:

- `--ncores 12` does not slow the transform down (good, see §3).
- Lowering `--ncores` does **not** reduce transform memory.
- `--parallel-years P` runs P transforms at once, each with a 94-thread
  pool: CPU is oversubscribed P-fold and memory is P x one month's peak.

To cap dask explicitly, set its own env var (verified against
`weather_env`'s dask 2026.3):

```bash
export DASK_NUM_WORKERS=48      # dask threaded scheduler pool size
```

Use this when running `--parallel-years > 1` (e.g. `94 // P`) or on a
shared node. Tracked in `.claude/open.md` (`## parallelization`) as a
code follow-up: the pipeline should set the dask pool itself.

ERA5-Land and MERRA-2 transform months in separate processes
(`ProcessPoolExecutor`). Their exporters compute each variable before
`to_netcdf()` (the fix for MERRA-2's dask write-lock deadlock, see
`MERRA2_PIPELINE_GUIDE.md`), so the same default-dask-pool effect exists
there but is short-lived and has not caused problems.

---

## 5. COSMO-REA6 pipeline phases

`test_cosmo_one_month.py` and `test_cosmo_one_year.py` are both thin CLI
wrappers around `providers/cosmo_rea6/pipeline.py::run_pipeline(year,
months=...)`; the one-month script is just `months=[m]`. There is no
separate producer-consumer path any more.

```text
Phase 1 — Bulk download (all months x 11 attributes)
  ThreadPoolExecutor(min(tasks, ncores))
  [CHECK A] size > 0 per file, inline as each download completes
  [CHECK B] download.verify_downloads(): HEAD request per file,
            local size == DWD Content-Length
       │
       ▼
Phase 2 — Bulk decompress (all .grb.bz2 -> .grb)
  ProcessPoolExecutor(min(tasks, ncores)), lbzip2/pbzip2/python-bz2
  [CHECK C] decompress.verify_decompressed(): stat() + size expansion
            + 4-byte GRIB magic, local disk only
  CLEANUP A (only with --cleanup): delete this run's .grb.bz2
       │
       ▼
(opt.) Crop — only with a bbox (weather fetch --country/--bbox);
             crops each GRIB to the bbox's (y, x) window. No-op otherwise.
       │
       ▼
Phase 3 — Transform + Export, sequential per month
  month 01 → build_month_dataset → export_netcdf → DNI outlier report
           → CLEANUP B (only with --cleanup): this month's .grb/.idx/.lock
  month 02 → ...
  Output: COSMO_REA6_<YYYY>_<MM>_all_attrs.nc
```

**Why months are sequential in Phase 3.** Dask already saturates all
cores within one month. Running *k* months at once gives each ~1/*k* of
the cores (no gain) and multiplies peak memory by *k*.

**Where CHECK B runs.** `verify_downloads()` runs at the end of Phase 1,
after the download thread pool has shut down and before Phase 2 starts
its `ProcessPoolExecutor`, so no HTTP threads are alive when worker
processes fork (avoiding the Linux fork-after-thread deadlock). It
also runs before any bz2 cleanup, so the local files still exist to
compare. (Older builds ran it after Phase 2; the current pipeline does
not.)

### 5.1 Interrupted runs: skip-if-done and `--resume`

| Phase              | Skip condition                                   | Who checks                  |
| ------------------ | ------------------------------------------------ | --------------------------- |
| Phase 1 download   | `.grb.bz2` exists and size == DWD Content-Length | automatic                   |
| Phase 2 decompress | `.grb` exists and size > 0                       | automatic                   |
| Phase 3 transform  | output `.nc` exists                              | `--resume` (must be passed) |

With `--resume`, months whose `.nc` exists are also excluded from Phase 1
and 2, so nothing is re-downloaded for them. Exports are atomic
(`<name>.nc.tmp` → rename), so an interrupted export never leaves a
truncated `.nc` that `--resume` would mistake for a finished month.

After an interruption during Phase 3 (bz2 already cleaned up, `.grb`
still on disk):

```bash
python src/weather/tests/test_cosmo_one_year.py --year 2018 --ncores 12 \
    --skip-download --skip-decompress --resume --cleanup
```

### 5.2 Cleanup

Cleanup is **off by default** (`COSMO_CLEANUP=false`); pass `--cleanup`
or set `COSMO_CLEANUP=true`. Every deletion is gated on the preceding
integrity check passing and uses exact per-month filenames (plus a glob
for cfgrib's hashed `<grb_name>.<hash>.idx` sidecar), so partial or
`--resume` runs never delete another month's files. `--skip-download`
suppresses CLEANUP A and `--skip-decompress` suppresses CLEANUP B.

---

## 6. Transform: dask temporal chunking

GRIBs are opened with `chunks={"time": 168}` (≈ 1 week):

```text
Monthly GRIB (e.g. T_2M, January):
  time: 744 steps → 5 chunks (4 x 168 + 72)
  y:    824       → single chunk
  x:    848       → single chunk
```

- **No spatial chunking.** cfgrib reads the whole 824 x 848 field per
  GRIB message anyway; splitting `(y, x)` would multiply the task graph
  without reducing I/O.
- **Fully vectorized.** Every derived field (GHI, DHI, DNI via Spencer,
  WS_10M, RH, T_DEW, ALBEDO, SNOWFALL) is element-wise NumPy/dask over
  `(time, y, x)`. NumPy releases the GIL, so dask threads run in
  parallel. See [dni_methodology.md §3](dni_methodology.md#3-why-not-pvlib-for-gridded-data).

---

## 7. Export: compute, compress, write atomically

`export_netcdf()` (all three providers):

1. computes each variable into memory **one at a time** (bounds peak
   memory and avoids dask's multi-threaded write-lock contention);
2. attaches CF metadata (`common/cf_conventions.attach_cf_metadata`);
3. writes float32, zlib `complevel=1` to `<name>.nc.tmp`, then renames.

| Choice                        | Reason                                                              |
| ----------------------------- | ------------------------------------------------------------------- |
| `complevel=1`                 | Levels 2–9 save < 5 % more space for ~10x the CPU on large grids    |
| `float32`                     | Halves file size; 7 significant digits is far beyond model accuracy |
| `HDF5_USE_FILE_LOCKING=FALSE` | Avoids lock hangs on GPFS/Lustre/NFS; set at module level           |
| temp file → rename            | An interrupted write never leaves a truncated final file            |

---

## 8. Memory footprint (COSMO-REA6)

Rough figures for one full-domain month (824 x 848, 744 h):

| Item                                          | Size (float32) |
| --------------------------------------------- | -------------- |
| One variable, one month                       | ≈ 2.1 GB       |
| One dask chunk (168 h) of one variable        | ≈ 470 MB       |
| Output dataset once computed (~13 variables)  | ≈ 25–30 GB     |
| Observed process peak (2018 run, older build) | ≈ 45 GB        |

The peak scales with the number of dask threads (more chunks in flight)
and with `--parallel-years` (one month per active year). It does not
scale with `--ncores` (§4). On `sd26` (1 TB) even
`--parallel-years 4` is comfortable memory-wise; CPU oversubscription
(§4) is the tighter limit. For SLURM, request `--mem=0` on a dedicated
node, or ≥ 64 GB per concurrently processed year.

A country-scoped run (`weather fetch --country ...`) crops before
transform, so memory and time scale with the cropped area instead.

---

## 9. Throughput

**Current (2026-08, 11 attributes, `sd26`, `--ncores 12`):** roughly
~6 min and ~10 GB of GRIB per month end to end, ~9.3 GB NetCDF output per
month. The full 1995-01..2019-08 archive (296 months) was rebuilt this way.

**Historical (2018, 9 attributes, 96-thread build):** ~230 s per month
(download ~58 s, decompress ~23 s, transform + export ~149 s); a full year
in ~32 min with bulk download/decompress. Treat these as lower bounds —
two more raw attributes and more derived output variables have been
added since, and the 96 download threads used then are what later
triggered DWD's 503s (§3).

Download time depends on DWD's current load far more than on local
threads. Transform dominates on a fast network.

---

## 10. Configuration reference

```bash
# .env (or CLI flags)
COSMO_NCORES=12            # download threads, verify threads, decompress
                           # processes — keep low, see §3
COSMO_THREADS_PER_JOB=4    # lbzip2/pbzip2 threads per decompress job;
                           # 12 x 4 ≈ 48 threads. Use 1 if you raise
                           # COSMO_NCORES for a --skip-download run.
COSMO_MAX_RETRIES=10       # per-file download retries
COSMO_CLEANUP=false        # keep intermediates by default
DASK_NUM_WORKERS=94        # optional: cap the transform's dask pool (§4)

python src/weather/tests/test_cosmo_one_year.py --year 2018 --ncores 12 --resume
```

### 10.1 `COSMO_THREADS_PER_JOB` and oversubscription

| Decompressor        | `COSMO_THREADS_PER_JOB` | OS threads at `ncores=12` | OS threads at `ncores=94` |
| ------------------- | ----------------------- | ------------------------- | ------------------------- |
| Python `bz2`        | ignored                 | 12                        | 94                        |
| `lbzip2` / `pbzip2` | 4 (default)             | 48 — fine                 | 376 — oversubscribed      |
| `lbzip2` / `pbzip2` | 1                       | 12 — under-used           | 94 — correct              |

`lbzip2`/`pbzip2` have no win-64 conda-forge build; Windows always falls
back to Python `bz2` (see [debugging.md §2](debugging.md)).

---

## 11. Related documentation

| Topic                              | File                                                       |
| ---------------------------------- | ---------------------------------------------------------- |
| DNI formula, Spencer vectorization | [dni_methodology.md](dni_methodology.md)                   |
| ERA5-Land bulk run / CDS queue     | [BULK_RUN_GUIDE_ERA5-LAND.md](BULK_RUN_GUIDE_ERA5-LAND.md) |
| MERRA-2 bulk run / OPeNDAP         | [BULK_RUN_GUIDE_MERRA2.md](BULK_RUN_GUIDE_MERRA2.md)       |
| COSMO pipeline code                | `src/weather/providers/cosmo_rea6/pipeline.py`             |
| Environment configuration          | `.env.example`                                             |
