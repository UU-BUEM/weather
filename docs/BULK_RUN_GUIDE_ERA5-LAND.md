# ERA5-Land bulk-run guidance and launch scripts

## The key insight: you are download-bound, not compute-bound

From your own run logs:

- CDS download per month: ~14-52 min queue + ~6 min transfer
- Transform per month: ~11 min (mostly I/O + zlib, already compiled C)

The CDS queue dominates and is outside your control. Making the GRIB
reader faster (wgrib2/CDO/numba) saves almost nothing because you are
waiting on CDS. The real win is OVERLAPPING download and transform so
each month's transform runs while the next month downloads.

wgrib2 is ruled out anyway: it is GRIB2-only, and your ERA5-Land files
are mostly GRIB1 (edition 1 for 9/10 variables). CDO on Windows is
awkward (WSL/Cygwin) and would replace already-working code. Skip both.

--------------------------------------------------------------------

## Recommended run mode on the Linux server

### 1. tmux (preferred — survives disconnect, lets you watch progress)

    tmux new -s era5
    conda activate weather_env
    # point work dir at the big volume, set Europe bbox:
    export ERA5_WORK_DIR=/data/soma/era5_land
    export ERA5_AREA=72,-11,34,32
    export ERA5_CDS_MAX_CONCURRENT=6

    python src/weather/tests/test_era5_multi_year.py \
        --from-year 1950 --to-year 2024 \
        --ncores 8 --resume --cleanup

    # detach: Ctrl-b then d      reattach: tmux attach -t era5

### 2. nohup (fire-and-forget)

    nohup python src/weather/tests/test_era5_multi_year.py \
        --from-year 1950 --to-year 2024 \
        --ncores 8 --resume --cleanup \
        > era5_bulk.log 2>&1 &
    tail -f era5_bulk.log

--------------------------------------------------------------------

## Parallelization strategy — what actually helps, and what does not

Your 94 cores are tempting, but the constraint is the CDS queue, not
CPU. Here is the honest hierarchy of what helps:

### Helps a LOT: CDS request concurrency (up to the account limit)

CDS processes a limited number of your requests SIMULTANEOUSLY (queued
otherwise). Raising ERA5_CDS_MAX_CONCURRENT lets more months download in
parallel. This is the single biggest lever. But CDS caps concurrent
active requests per account (historically ~ a handful). Beyond that cap,
extra requests just queue - no speed-up, and risk rejection.

### Helps: overlapping download with transform (see interleaved mode)

While month N transforms on your cores, month N+1..N+k download. This
hides the ~11 min transform behind the unavoidable download wait.

### Helps MODESTLY: transform workers

Transform is I/O+compression bound. 4-8 workers is plenty; 94 gives no
extra benefit and multiplies memory (each opens a GRIB). Keep ncores 4-8.

### Does MULTIPLE ACCOUNTS help? Yes - this is the real multiplier

Each Copernicus account has its own concurrent-request quota and queue
position. Splitting the year range across 2-3 accounts (each with its
own ~/.cdsapirc or ERA5_CDS_KEY) genuinely multiplies download
throughput, because you get N independent queue slots. This is far more
effective than any code optimization, since download is the bottleneck.

   Practical pattern: run 2-3 tmux sessions, each with a different
   ERA5_CDS_KEY and a disjoint year range:

     # session A (account 1): 1950-1974
     # session B (account 2): 1975-1999
     # session C (account 3): 2000-2024

   CAUTION: check Copernicus terms of service on multiple accounts /
   automated bulk access before doing this. Some providers restrict it.
   Stay within their fair-use policy; do not hammer the API.

### Does NOT help: faster GRIB readers (wgrib2/CDO/numba)

Compute is not the bottleneck. These add complexity for ~0 wall-clock
gain given the download wait.

--------------------------------------------------------------------

## Disk budget (Europe crop, ~1.4 GB GRIB, ~few hundred MB nc per month)

With --cleanup, each month's GRIB is deleted after its nc is written, so
transient GRIB is at most (concurrency x 1.4 GB). Final nc archive for
1950-2024 x 12 months is well under 1 TB - comfortable in 15 TB.
