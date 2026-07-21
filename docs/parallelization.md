# COSMO-REA6 Pipeline Parallelization and Performance

This document describes the parallelization strategy used by both the
monthly (`test_cosmo_one_month.py`) and annual (`test_cosmo_one_year.py`) pipeline
scripts for processing COSMO-REA6 data on a multi-core HPC node.

For the DNI-specific vectorization over the spatial grid using the Spencer
solar-position formula see [dni_methodology.md](dni_methodology.md) §3.

---

## 1. Pipeline stages and their parallelism type

Each run processes 9 attributes per month through four stages:

```text
  ┌─────────────┐   ThreadPoolExecutor   ┌──────────────────┐
  │  Download   │ ──── 9 threads ──────► │  .grb.bz2 files  │
  │  (I/O-bound)│       per month        │  (on disk)       │
  └─────────────┘                        └────────┬─────────┘
                                                  │
  ┌─────────────┐   ProcessPoolExecutor           │
  │ Decompress  │ ◄─── 9 processes ──────────────┘
  │  (CPU-bound)│    submitted as each            │
  └─────────────┘    download completes           │
                     (producer-consumer)           │
                                                   ▼
  ┌─────────────┐   Dask threaded scheduler   ┌──────────────┐
  │  Transform  │ ──── ncores workers ──────► │  in-memory   │
  │  (CPU-bound)│    (80 on HPC node)         │  xr.Dataset  │
  └─────────────┘                             └──────┬───────┘
                                                     │
  ┌─────────────┐   Dask threaded + zlib             │
  │   Export    │ ◄────────────────────────────────┘
  │  (I/O+CPU)  │    same thread pool, float32
  └─────────────┘    compression level 1
```

### Worker counts — monthly script (9 attributes, 80 cores)

| Stage | Workers | Type | Hard ceiling | Reason |
| --- | --- | --- | --- | --- |
| Download | 9 | `ThreadPoolExecutor` | # attributes | Network I/O-bound |
| Decompress | 9 | `ProcessPoolExecutor` | # attributes | One bz2 per attribute |
| Transform | 80 | Dask threaded | `ncores` | CPU-bound arithmetic |
| Export | 80 | Dask threaded | `ncores` | Dask `.compute()` + zlib |

Download and decompress are hard-limited to 9 workers (one per attribute)
regardless of how many cores are allocated. Since they complete before
transform begins, all `ncores` (80 in this example) are devoted to the
dask transform and export stages.

### Worker counts — annual script (108 tasks, 96 cores)

The annual script treats all 12 months × 9 attributes = **108 tasks** as
independent, removing the per-month ceiling:

| Phase | Workers | Type | Hard ceiling | Reason |
| --- | --- | --- | --- | --- |
| Phase 1 — Download | 96 | `ThreadPoolExecutor` | min(108, ncores) | All month-attr pairs independent |
| DWD size check | 94 | `ThreadPoolExecutor` (sequential, after Phase 2) | min(108, ncores) | Network I/O; runs after ProcessPoolExecutor exits to avoid fork+thread deadlock |
| Phase 2 — Decompress | 96 | `ProcessPoolExecutor` | min(108, ncores) | All month-attr pairs independent |
| Phase 2 verify | — | Sequential | — | Local stat() + 4-byte GRIB magic; < 100 ms |
| Phase 3 — Transform | 96 | Dask threaded | `ncores` | Per-month, CPU-bound |
| Phase 3 — Export | 96 | Dask threaded | `ncores` | Per-month, I/O + CPU |

The DWD size check and Phase 2 decompression use completely different
resources (network I/O threads vs CPU-bound processes) and therefore run
simultaneously at no cost to either.

---

## 2. Download + Decompress: producer-consumer pattern (monthly script)

The monthly script (`test_cosmo_one_month.py`) uses a **producer-consumer** pattern
that overlaps downloading and decompression so the process pool is never idle:

```python
with ProcessPoolExecutor(max_workers=dc_workers) as dc_pool:   # outer
    with ThreadPoolExecutor(max_workers=dl_workers) as dl_pool: # inner
        for attr in attrs:
            dl_futures[dl_pool.submit(download, attr)] = attr

        for dl_fut in as_completed(dl_futures):
            bz2_path = dl_fut.result()          # blocks only for this attr
            dc_pool.submit(decompress, bz2_path) # starts immediately
```

Worker budget allocation (`ncores = 80`, `n = 9`):

```text
dl_workers = min(n, max(1, ncores // 2))   = min(9, 40) = 9
dc_workers = min(n, max(1, ncores - dl_workers)) = min(9, 71) = 9
```

The `ncores // 2` heuristic reserves half the budget for each pool; both
are capped at `n` so the split only matters when `ncores < 2 * n_attrs`.

---

## 3. Annual pipeline: bulk parallel phases

The annual script (`test_cosmo_one_year.py`) exploits a key fact: **all
12 months × 9 attributes = 108 download tasks are completely independent**,
and so are all 108 decompress tasks. The script therefore processes them in
two bulk phases before any transform work begins.

Full execution flow with integrity checks:

```text
Phase 1 — Bulk download (all 108 bz2 files)
  ┌─────────────────────────────────────────────────────────────────────┐
  │  ThreadPoolExecutor(min(108, ncores))                               │
  │  month 01 × 9 attrs ──────────────────────────────────────────────►│
  │  month 02 × 9 attrs ──────────────────────────────────────────────►│
  │  ...                                                               │
  │  month 12 × 9 attrs ──────────────────────────────────────────────►│
  │  [CHECK A] size > 0 per file, inline as each future completes      │
  └─────────────────────────────────────────────────────────────────────┘
  Wall time ≈ 3–4 min (observed on HPC with 94 threads)
       │
       ▼
Phase 2 — Bulk decompress (all 108 .grb files)
  ┌─────────────────────────────────────────────────────────────────────┐
  │  ProcessPoolExecutor(min(108, ncores))                               │
  │  Round 1: 94 tasks in parallel ───────────────────────────────────►│
  │  Round 2: 14 remaining tasks ─────────────────────────────────────►│
  │  Each task logs start AND completion at INFO level                   │
  └─────────────────────────────────────────────────────────────────────┘
       │
       ▼
  [CHECK C] _verify_decompressed — sequential, all local disk
            stat() + size-expansion check + 4-byte GRIB magic
            108 files; expected wall time: < 100 ms
       │
       ▼
  [CHECK B] _verify_downloads — sequential, after ProcessPoolExecutor exits
            94 parallel HEAD requests to DWD (I/O-bound)
            compares local bz2 size to Content-Length header
            Must run BEFORE bz2 cleanup so local files still exist
            Expected wall time: 1–5 s (2 batches × 94 requests @ <150 ms RTT)
            Worst case (30 s timeout per request): 2 × 30 s = 60 s
       │
       ▼
  bz2 cleanup (gated on CHECK B + CHECK C both passing)
       │
       ▼
Phase 3 — Transform + Export (sequential per month)
  month 01 → [Open GRIBs] → [Transform] → [Export NetCDF] → [cleanup grb]
  month 02 → [Open GRIBs] → [Transform] → [Export NetCDF] → [cleanup grb]
  ...
  month 12 → [Open GRIBs] → [Transform] → [Export NetCDF] → [cleanup grb]
  Wall time ≈ 12 × 149 s = 1788 s
       │
       ▼
  Output: 12 monthly files per year
  COSMO_REA6_YYYY_01_all_attrs.nc … COSMO_REA6_YYYY_12_all_attrs.nc
  No annual merge step required — test_percentile.py reads monthly files
  directly via xr.open_mfdataset.
```

### 3.1 Why each check is placed where it is

| Check | Where | What | Why there |
| --- | --- | --- | --- |
| A — `size > 0` | Inline in Phase 1 future loop | Each `.grb.bz2 > 0 B` immediately on thread completion | `download_https_atomic` uses atomic rename; a non-empty file was fully written |
| B — DWD `Content-Length` | Sequential, after Phase 2 `ProcessPoolExecutor` exits | 94 parallel HEAD requests: local size == server `Content-Length` | Must run **after** the `ProcessPoolExecutor` exits to avoid the Linux fork-after-thread deadlock; must run **before** bz2 cleanup so local files still exist to be stat()'d |
| C — GRIB magic | Sequential, after Phase 2 | `stat()` + size expansion + `b"GRIB"` header bytes | Local disk only, < 100 ms; gates bz2 deletion so corrupt decompression is caught before source files are removed |

**Why sequential in Phase 3?**  The bottleneck is CPU, not RAM.
Dask already saturates all `ncores` threads *within* one month's transform.
Running *k* months in parallel would give each month only `ncores/k` dask
workers — each month would take *k*× longer, so total wall time is unchanged
(or worse, due to dask-scheduler contention across concurrent graphs).
Months are therefore kept sequential so each month benefits from the full
core budget.

---

### 3.2 Interrupted runs: skip-if-done and `--resume`

Each phase has an independent skip-if-done check, so a re-run after an
interrupted pipeline is always faster than a cold start:

| Phase | Skip condition | Who checks |
| --- | --- | --- |
| Phase 1 download | `.grb.bz2` exists **and** local size == DWD `Content-Length` | `download_https_atomic` — automatic, no flag needed |
| Phase 2 decompress | `.grb` exists **and** size > 0 | `decompress_bz2_file` — automatic, no flag needed |
| Phase 3 transform | output `.nc` exists | `--resume` flag — **must be passed explicitly** |

**What `--resume` does** (and does not do):

- Skips the transform + export step for any month whose
  `COSMO_REA6_YYYY_MM_all_attrs.nc` already exists in the output directory.
- Phase 1 and Phase 2 still run their skip-if-done checks regardless.
  If the `.grb` files for skipped months are still on disk,
  Phase 2 returns instantly for those months.

**Recommended command after an interruption** (e.g. stopped during month 5,
months 1–4 have `.nc` files, months 5–12 still have `.grb` files on disk,
but all `.grb.bz2` were already cleaned up after Phase 2):

```bash
python src/weather/tests/test_cosmo_one_year.py --year 2018 --ncores 94 \
    --skip-download --skip-decompress --resume
```

- `--skip-download` : bypass Phase 1 entirely (bz2 files already cleaned up)
- `--skip-decompress`: bypass Phase 2 entirely (grb files still on disk)
- `--resume`        : skip Phase 3 for months whose `.nc` already exists

This jumps straight to Phase 3 starting at the first unfinished month.

### 3.3 Cleanup sequence and disk management

Cleanup is split across Phase 2 and the per-month Phase 3 loop.
All cleanup is **gated on the preceding integrity check passing** —
a failed check raises `RuntimeError` before any files are deleted,
keeping source files available for diagnosis or re-run.

```text
Phase 2 — Bulk decompress completes + CHECK C passes
  └─► CLEANUP A  remove each month's .grb.bz2 from dl_dir  (frees ~12 GB)
      Scoped to months_to_process × _ALL_ATTRS (exact filenames,
      never a glob — safe with --resume partial runs)
      Condition: do_dl and not args.no_cleanup

Phase 3 — per month, after export:
  [3/3] Export NetCDF (export_netcdf raises on any write failure)
        │
        ├─► close all xr.Dataset handles
        └─► CLEANUP B  remove THIS month's .grb + .idx + .lock from dc_dir
            Exact filenames only — never touches other months' .grb files
            (frees ~7 GB per month as each month completes)
            Condition: do_dc and not args.no_cleanup

After all months complete:
  CLEANUP C  rmdir per-attribute subfolders in dl_dir and dc_dir
             (rmdir silently fails if non-empty — safe with
             --parallel-years: other years may still hold their files)
             Condition: not args.no_cleanup
```

**Peak disk usage** (during Phase 3, just after Phase 2 cleanup):

| Data | Size | Location |
| --- | --- | --- |
| All decompressed GRIBs (12 months × 9 attrs) | ~84 GB | `dc_dir` |
| NetCDF output being written (1 month at a time) | ~2 GB | `out_dir` |
| **Peak total** | **~86 GB** | |

Once Phase 3 starts consuming months, `dc_dir` shrinks by ~7 GB per month.
By the time month 12 completes, `dc_dir` is empty and `out_dir` holds the
12 final NetCDF files (~24 GB).

Both cleanups are gated on the `do_dl` / `do_dc` flags and `--no-cleanup`,
so `--skip-download`, `--skip-decompress`, and `--no-cleanup` suppress the
relevant call.

---

## 4. Transform stage: dask temporal chunking

`open_grib_month()` opens GRIB files with:

```python
xr.open_dataset(grb_path, engine="cfgrib", chunks={"time": 168})
```

### Temporal chunking — `chunks={"time": 168}` (≈ 1 week)

A monthly GRIB file has 672–744 hourly timesteps. With chunk size 168,
each attribute has 4–5 independent dask chunks. Combined with 9 attributes,
the task graph contains dozens of independent tasks per variable, giving the
80-thread dask scheduler real parallelism to exploit.

```text
Monthly GRIB  (e.g. T_2M, January 2018):
  time: 744 steps  →  ⌈744/168⌉ = 5 chunks  (4 full × 168 = 672, + 1 partial of 72)
  y:    824                                  (single chunk)
  x:    848                                  (single chunk)
```

### Why spatial chunking is NOT applied

- cfgrib reads the full COSMO-REA6 rotated-pole grid (824 × 848) as one
  spatial tile per timestep. Sub-dividing `(y, x)` would increase the
  dask task graph quadratically without reducing I/O (cfgrib still reads
  the full GRIB record).
- The spatial grid at float32 per time-chunk is only ~470 MB — it fits
  comfortably in memory and processing it as a single spatial tile avoids
  chunk-boundary effects in operations like wind speed `√(u² + v²)`.

### Why the Spencer formula is fully parallel

All transform operations (`convert_temperature`, `compute_ghi`, `compute_dhi`,
`compute_wind_speed`, `compute_dni`) are pure NumPy/Dask element-wise
operations that broadcast naturally over `(time, y, x)` arrays. No Python
loops, no GIL contention (NumPy releases the GIL for C-extension arithmetic),
so all 80 dask threads run simultaneously on different chunks.

See [dni_methodology.md §3](dni_methodology.md#3-why-not-pvlib-for-gridded-data)
for a detailed comparison with the pvlib loop-based approach.

### Explicit dask worker count

```python
dask.config.set(num_workers=ncores)   # set once before the month loop
```

Without this, dask defaults to `os.cpu_count()`. On an HPC node running
inside a SLURM allocation, `os.cpu_count()` returns the total machine CPUs
(not the allocated ones), so explicit configuration ensures the right count.
`settings.cosmo_ncores()` already reads `SLURM_CPUS_PER_TASK` as a fallback,
so passing `--ncores 80` or setting `COSMO_NCORES=80` is equivalent.

---

## 5. Export stage: compression and float32

`export_netcdf()` encodes all data variables as float32 with zlib
compression level 1:

```python
encoding[var] = {"zlib": True, "complevel": 1, "dtype": "float32"}
```

| Choice | Reason |
| --- | --- |
| `complevel=1` (fastest) | Levels 2–9 give diminishing file-size reduction (< 5%) for 10× more CPU time on large grids |
| `dtype=float32` | Halves output file size vs float64; instruments have ≈ 0.1 W/m² precision — float32 (7 significant digits) is more than adequate |
| `HDF5_USE_FILE_LOCKING=FALSE` | Prevents deadlocks on GPFS/Lustre network file systems used on HPC; set at module level in `test_cosmo_one_year.py` and `export.py` |

Dask triggers `.compute()` during `to_netcdf()`, writing chunks concurrently
with the same 80-thread scheduler used for transform.

---

## 6. Memory footprint

| Item | Size (float32) |
| --- | --- |
| One chunk, one attribute: 168 × 824 × 848 | ≈ 470 MB |
| All 9 attributes, one chunk each | ≈ 4.2 GB |
| Peak active (4 concurrent chunks × 9 attrs) | ≈ 17 GB |
| Intermediate operations (add, divide, sqrt) | ≈ 1.5× peak = **25 GB** |
| Dask task graph overhead | ≤ 5 GB |
| **Total peak per month (80 workers)** | **≈ 30 GB** |
| **Total peak per month (94 workers)** | **≈ 45 GB** |

The per-month peak scales with `ncores` because dask runs more chunks
concurrently:

$$\text{Peak RAM} \approx
  \underbrace{n_{\text{workers}} \times 470\,\text{MB}}_{\text{active chunks}}
  \times 1.5 + 5\,\text{GB overhead}$$

At 94 workers: 94 × 470 MB × 1.5 + 5 GB ≈ 45 GB per month,
which matches observed usage.  This is the expected and correct value — it means
dask is fully utilising all allocated workers.

Only one month is held in memory at a time (Phase 3 is sequential), so
**45 GB is also the total process peak**, regardless of how many months
are being processed in the year run.

### SLURM memory allocation

When submitting via SLURM, request at least `ncores × 0.7 GB` to give a
comfortable margin:

```bash
# 94 cores × 0.7 GB/core = 66 GB headroom; round up to next SLURM unit
  #SBATCH --mem=70G
# Or, to use the full node's RAM without an explicit limit:
  #SBATCH --mem=0
```

On a dedicated 782 GB node the margin is ~17× and `--mem=0` (use all
available) is safe.

---

## 7. Monthly vs annual comparison

| Feature | `test_cosmo_one_month.py` | `test_cosmo_one_year.py` |
| --- | --- | --- |
| Download+decompress | Producer-consumer (9+9 workers) | Bulk parallel: min(108, ncores) |
| Inline download check | `size > 0` per future | `size > 0` per future |
| DWD size verification | — | ✓ sequential after Phase 2; 108 HEAD requests |
| GRIB magic check | — | ✓ sequential after Phase 2; local disk only |
| Transform | Dask threaded, 80 workers | Same (per-month, sequential months) |
| Export | zlib level 1, float32 | Same |
| Annual merge (post-process) | — | Separate: `python -m weather.common.merge` |
| Resume support | — | ✓ `--resume` flag |
| Per-month error isolation | — | ✓ try/except, continues |
| Peak disk usage | ~8 GB (1 month) | ~84 GB (all grb after Phase 2; shrinks per month in Phase 3) |
| Annual log file | — | `COSMO_REA6_YYYY_annual_<timestamp>.log` |

---

## 8. Effective throughput on the HPC node

Measured on HPC (96 cores, `/data/soma`, 2018 dataset, all 9 attributes):
**one month ≈ 230 s** end-to-end including download, decompress, transform,
and export.

Estimated phase breakdown (230 s = 100 %):

| Phase | Parallelism | Share | Time |
| --- | --- | --- | --- |
| Download (9 attrs, `ThreadPoolExecutor`) | 9 threads | ~25 % | ~58 s |
| Decompress (9 attrs, `ProcessPoolExecutor`) | 9 processes | ~10 % | ~23 s |
| Transform + Export (dask, 96 threads) | 96 threads | ~65 % | ~149 s |
| **Total per month** | | **100 %** | **~230 s** |

Times vary with network speed to DWD OpenData, disk I/O speed on `/data/soma`,
and system load. Transform dominates on fast networks; download dominates on
slow networks.

---

### 8.1 Annual timing estimate and bulk-parallel savings

With the measured 230 s/month baseline, the annual run over 12 months
proceeds in three bulk phases:

**Phase 1 — Bulk download** (all 108 bz2 files, 96 concurrent threads):

Network I/O for all months runs in parallel. Observed wall time on the
HPC node with 96 threads is **3–4 min** (180–240 s). The theoretical
minimum equals one month's download time; the difference reflects DWD
server response variability and retry overhead from transient 503 errors.

$$T_{\text{Phase1}} \approx 180\text{–}240\,\text{s}$$

**DWD size check** (background thread, concurrent with Phase 2):

108 HEAD requests fired with up to `n_workers` (96) threads. With
~50–150 ms RTT to DWD from the HPC network, ⌈108/96⌉ = 2 batches
complete in well under 5 s — negligible, and free since it overlaps
Phase 2.

$$T_{\text{DWD check}} \approx 2 \times 150\,\text{ms} \approx 1\text{–}5\,\text{s}$$

**Phase 2 — Bulk decompress** (all 108 grb files, 96 processes):

With 96 processes and 108 tasks there are ⌈108/96⌉ = 2 rounds.
Each bzip2 task takes ~23 s, so:

$$T_{\text{Phase2}} \approx 2 \times 23\,\text{s} = 46\,\text{s}$$

**Phase 3 — Transform + Export** (sequential months, dask saturates 96 cores):

$$T_{\text{Phase3}} = 12 \times 149\,\text{s} = 1788\,\text{s}$$

#### Annual total

$$58 + 46 + 1788 = 1892\,\text{s} \approx \mathbf{32\,\text{min}}$$

Summary (comparison with older approaches):

| Mode | Phase 1 (dl) | Phase 2 (dc) | Phase 3 (tx+ex) | Total | Wall clock |
| --- | --- | --- | --- | --- | --- |
| Sequential | 12 × 58 s = 696 s | 12 × 23 s = 276 s | 12 × 149 s = 1788 s | 2760 s | ~46 min |
| Old pre-fetch | ~58 s (M1 only) | 12 × 23 s = 276 s | 1788 s | ~2122 s | ~35 min |
| **Bulk parallel (current)** | **~58 s** | **~46 s** | **1788 s** | **~1892 s** | **~32 min** |

The key win over the old pre-fetch approach is **Phase 2**: the per-month
sequential decompress (12 × 23 s = 276 s) is replaced by a single bulk
pass with 96 processes (2 rounds × 23 s = 46 s), saving ~230 s.

#### Sensitivity to download speed

| Download time per month | Phase 1 wall time | Annual total |
| --- | --- | --- |
| 30 s (fast HPC network) | ~30 s | ~30 + 46 + 1788 = ~1864 s ≈ 31 min |
| 58 s (measured baseline, 1-month test) | ~58 s | ~1892 s ≈ 32 min |
| 180–240 s (observed, full-year with 96 threads) | ~180–240 s | ~2014–2074 s ≈ 34–35 min |
| 90 s (moderate WAN) | ~90 s | ~1924 s ≈ 32 min |
| 120 s (slow WAN) | ~120 s | ~120 + 46 + 1788 = ~1954 s ≈ 33 min |

On a slow WAN connection the saving vs sequential processing can exceed
20 minutes — Phase 1 wall time is bounded by a single-month's connection
speed while the sequential baseline scales as 12× that speed.

---

## 9. Configuration reference

```bash
# .env  (or CLI flags)
COSMO_NCORES=94          # worker budget for all pools (download / decompress / dask)
                          # On a 96-core node use 94–95, not 96:
                          #   - leaves 1–2 cores for OS scheduler, SSH daemon,
                          #     monitoring agents and any residual background work
                          #   - avoids starving other users' processes if the
                          #     node is shared or lightly used by others
COSMO_WORK_DIR=/data/soma/cosmo_rea6

# SLURM job script — allocate all 96 but tell the script to use 94
#SBATCH --cpus-per-task=96
# SLURM_CPUS_PER_TASK is read automatically but --ncores overrides it

# Run  (explicit --ncores recommended on shared nodes)
python src/weather/tests/test_cosmo_one_year.py --year 2018 --ncores 94 --resume
```

### Choosing `--ncores`

| Node situation | Recommended value | Reason |
| --- | --- | --- |
| Exclusively allocated SLURM job | `ncores - 1` (e.g. 95) | One core free for OS; no other users |
| Shared node, no other-user jobs | `ncores - 2` (e.g. 94) | OS daemon safety margin |
| Shared node, other jobs running | `ncores / 2` or `ncores - 4` | Avoid starving other workloads |

All three executor pools (`ThreadPoolExecutor` for download and DWD checks,
`ProcessPoolExecutor` for decompression, and dask for transform/export) are
hard-capped at `min(n_tasks, ncores)`, so a single `--ncores 94` flag is
sufficient to control the entire pipeline's core budget.

### 9.1 COSMO_THREADS_PER_JOB — avoiding thread oversubscription

`COSMO_THREADS_PER_JOB` controls how many threads each individual bzip2
worker uses (default: 4). This interacts critically with `COSMO_NCORES`:

| Decompressor | `COSMO_THREADS_PER_JOB` | Total OS threads | Effect |
| --- | --- | --- | --- |
| Python `bz2` stdlib | any | `ncores × 1` | **Ignored** — Python bz2 is always single-threaded |
| `lbzip2` / `pbzip2` | 4 (default) | `94 × 4 = 376` | **Oversubscribed** — 376 threads / 94 cores |
| `lbzip2` / `pbzip2` | **1** | `94 × 1 = 94` | **Correct** — one thread per core; max throughput |

**Rule**: when running `test_cosmo_one_year.py` with bulk parallel decompression
(`ProcessPoolExecutor`, `ncores` workers), always set:

```bash
COSMO_THREADS_PER_JOB=1   # in .env, or export before running
```

`lbzip2` at 1 thread is still faster than Python bz2 at 1 thread because
it is a compiled C binary with lower per-byte overhead and no Python
interpreter cost. The multi-thread benefit of lbzip2/pbzip2 only applies
when decompressing **one file at a time** (e.g. the monthly script with
`n = 9` workers on a 96-core node); for the annual bulk pass the
process-level parallelism already saturates all cores.

---

## 10. Related documentation

| Topic | File |
| --- | --- |
| DNI formula and Spencer vectorization | [dni_methodology.md](dni_methodology.md) |
| Monthly pipeline script | `src/weather/tests/test_cosmo_one_month.py` |
| Annual pipeline script | `src/weather/tests/test_cosmo_one_year.py` |
| Environment configuration | `.env.example` |
