# Faster downloads + server logging

## 1. Why your downloads are slow

From your 2018-02 run:

    21:38:20  status -> successful   (file ready on CDS)
    21:44:29  download complete      (1314.6 MB)

    = 369 s for 1314.6 MB = **3.56 MB/s** (28.5 Mbit/s)

`cdsapi`'s `result.download()` uses a SINGLE HTTP stream.  The CDS object
store supports HTTP Range requests, so the file can be pulled in parallel
byte-ranges instead.

Impact across the full 1950-2025 run (~900 months):

    single stream @ 3.56 MB/s  ->  ~92 hours of pure transfer
    parallel      @ ~30 MB/s   ->  ~11 hours
    SAVING                     ->  ~81 hours

Note this is NOT extra CDS *requests* — it is parallelism WITHIN one
file's transfer, so it is completely safe with
`ERA5_CDS_MAX_CONCURRENT=1` and cannot trip the per-account job limit.

---

## 2. Wire `fast_download.py` into `downloader.py`

Put `fast_download.py` in `src/weather/providers/era5_land/`.

In `downloader.py`, inside `_fetch`, replace the download line:

```python
# OLD:
result = client.retrieve(dataset, request)
result.download(str(tmp))
```

with:

```python
# NEW: submit as before, then pull the result in parallel.
result = client.retrieve(dataset, request)

from .fast_download import download_parallel
download_parallel(
    result.location,          # the CDS object-store URL
    tmp,
    connections=int(
        self._cfg.get("download_connections", 8)
    ),
)
```

`result.location` is the URL cdsapi would have fetched (the one your log
prints as `Downloading https://object-store.os-api.cci2.ecmwf.int/...`).
If a future cdsapi renames it, use `result.url` or
`result.get_results().location`.

Add to `config.py`:

```python
"download_connections": int(
    os.getenv("ERA5_DOWNLOAD_CONNECTIONS", "8")
),
```

And in `.env`:

```dotenv
ERA5_DOWNLOAD_CONNECTIONS=8
ERA5_CDS_MAX_CONCURRENT=1     # your account runs 1 job at a time
```

### Even faster on Linux: aria2c

`aria2c` is a purpose-built parallel downloader and typically beats a
Python thread pool.  On the server:

```bash
conda install -c conda-forge aria2      # or: apt install aria2
```

then set:

```dotenv
ERA5_USE_ARIA2=1
```

`fast_download.py` will use it automatically when present, and fall back
to the Python parallel path (and then to a single stream) otherwise.

### Tuning

- `ERA5_DOWNLOAD_CONNECTIONS=8` is a good default.  16 may help on a fat
  pipe; beyond that you usually hit diminishing returns or server-side
  throttling.
- Measure it: the new log line prints the achieved rate, e.g.
  `Download complete: ... (1314.6 MB in 44.2 s = 29.7 MB/s)`.

---

## 3. Server logging

Run under `tmux` and `tee` so you get BOTH a live view and a permanent,
greppable log:

```bash
tmux new -s era5
conda activate weather_env

export ERA5_WORK_DIR=/data/soma/era5_land
export ERA5_AREA=72,-11,34,32
export ERA5_CDS_MAX_CONCURRENT=1
export ERA5_DOWNLOAD_CONNECTIONS=8
export ERA5_USE_ARIA2=1

mkdir -p $ERA5_WORK_DIR/logs
LOG=$ERA5_WORK_DIR/logs/era5_$(date +%Y%m%d_%H%M%S).log

python src/weather/tests/test_era5_multi_year.py \
    --from-year 1950 --to-year 2025 \
    --ncores 6 --resume --cleanup 2>&1 | tee "$LOG"

# detach: Ctrl-b then d      reattach: tmux attach -t era5
```

Checking progress after disconnecting (VPN can be off, laptop can be
closed — the job runs on the server):

```bash
tail -f  $ERA5_WORK_DIR/logs/era5_*.log        # follow live
grep -c ': OK'   $ERA5_WORK_DIR/logs/era5_*.log   # months done
grep    'FAIL'   $ERA5_WORK_DIR/logs/era5_*.log   # failures
grep    'MB/s'   $ERA5_WORK_DIR/logs/era5_*.log | tail   # transfer rates
ls $ERA5_WORK_DIR/output/*.nc | wc -l           # ground truth progress
df -h $ERA5_WORK_DIR                            # disk
ps aux | grep test_era5                         # still alive?
```

---

## 4. Pipeline order (strict)

```text
1. transform + export each month  (test_era5_multi_year.py)
2. boundary repair                <-- MANDATORY; now automatic, runs
                                       inside run_pipeline() itself
                                       (providers/era5_land/
                                       boundary_repair.py, STEP 3/3)
3. verify_months.py                (confirm all repaired)
4. percentile / downstream
```

Until step 2 runs for a given month, its first stamp holds a raw daily
total (thousands of W/m^2) and MUST NOT be used. A month is only ever
left `UNREPAIRED` on purpose when its predecessor genuinely doesn't
exist anywhere on disk yet (a real gap, not a bug).
