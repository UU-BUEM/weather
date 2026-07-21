"""Interleaved ERA5-Land pipeline: overlap download with transform.

The standard :func:`~weather.providers.era5_land.pipeline.run_pipeline`
runs all downloads, then all transforms.  Because ERA5-Land is
**download-bound** (the CDS queue dominates wall-clock time), a better
pattern overlaps the two: while month *N* transforms on local cores,
months *N+1..N+k* download from CDS.  This hides the transform time
behind the unavoidable CDS wait.

Architecture (producer/consumer)
--------------------------------
::

    Downloader threads (k = cds_max_concurrent)
        pull months from a queue, fetch each GRIB from CDS,
        push the finished GRIB path to a 'ready' queue.

    Transform workers (process pool, n = ncores)
        pull ready GRIB paths, transform+export to nc,
        optionally delete the GRIB (cleanup).

Downloads and transforms run concurrently, so total time ≈
max(total_download_time, total_transform_time) rather than their sum.

Usage::

    from weather.providers.era5_land.pipeline_interleaved import (
        run_interleaved,
    )
    run_interleaved(year=2018, cleanup=True)
"""

from __future__ import annotations

import logging
import multiprocessing
import os
import queue
import threading
import time
from concurrent.futures import Future, ProcessPoolExecutor
from pathlib import Path

from ..base_downloader import DownloadJob
from .config import get_config
from .downloader import ALL_ATTRS, Era5Downloader
from .export import output_filename
from .pipeline import _transform_export_one

logger = logging.getLogger(__name__)

os.environ.setdefault("HDF5_USE_FILE_LOCKING", "FALSE")

# Sentinel signalling no more work on a queue.
_DONE = object()


def run_interleaved(
    year: int | None = None,
    months: list[int] | None = None,
    *,
    work_dir: Path | None = None,
    ncores: int | None = None,
    night_mask: bool = False,
    complevel: int = 1,
    cleanup: bool = True,
    resume: bool = True,
) -> list[str]:
    """Download and transform a year's months with overlap.

    Parameters mirror :func:`run_pipeline`, but downloads and transforms
    run concurrently.  ``cleanup`` defaults to ``True`` here because the
    interleaved mode is intended for the bulk historical run where disk
    is the constraint.

    Returns
    -------
    list[str]
        Per-month status strings.
    """
    if work_dir:
        os.environ["ERA5_WORK_DIR"] = str(work_dir)

    cfg = get_config()
    year = year or cfg["year"]
    months = months or list(range(1, 13))
    ncores = ncores or cfg["ncores"]
    dl_concurrency = cfg.get("cds_max_concurrent", 4)
    out_dir = cfg["output_dir"]
    out_dir.mkdir(parents=True, exist_ok=True)

    downloader = Era5Downloader(cfg)

    # Skip months already done when resuming.
    todo = []
    for m in months:
        op = out_dir / output_filename(year, m)
        if resume and op.exists() and op.stat().st_size > 0:
            logger.info("SKIP %d-%02d (nc exists)", year, m)
        else:
            todo.append(m)
    if not todo:
        return [f"{year}: all months already complete"]

    logger.info(
        "Interleaved run: year %d, %d months, %d downloaders, %d transformers",
        year, len(todo), dl_concurrency, ncores,
    )

    ready_q: queue.Queue = queue.Queue()
    month_q: queue.Queue = queue.Queue()
    for m in todo:
        month_q.put(m)
    for _ in range(dl_concurrency):
        month_q.put(_DONE)

    results: list[str] = []
    results_lock = threading.Lock()

    def _download_worker() -> None:
        while True:
            m = month_q.get()
            if m is _DONE:
                ready_q.put(_DONE)
                return
            try:
                job = DownloadJob(attribute=ALL_ATTRS, year=year, month=m)
                path = downloader.get(job)  # blocks on CDS queue
                ready_q.put((m, str(path)))
            except Exception as exc:  # noqa: BLE001
                logger.error("download failed %d-%02d: %s", year, m, exc)
                with results_lock:
                    results.append(f"{year}-{m:02d}: FAIL (download {exc})")

    # Launch downloader threads (I/O-bound; threads are ideal).
    dl_threads = [
        threading.Thread(target=_download_worker, daemon=True)
        for _ in range(dl_concurrency)
    ]
    for t in dl_threads:
        t.start()

    # Consume ready GRIBs and transform them in a process pool.
    ctx = multiprocessing.get_context("spawn")
    done_signals = 0
    t0 = time.perf_counter()
    with ProcessPoolExecutor(max_workers=ncores, mp_context=ctx) as pool:
        futures: dict[Future[str], int] = {}
        while done_signals < dl_concurrency or futures:
            # Drain ready queue, submitting transforms.
            try:
                item = ready_q.get(timeout=0.5)
                if item is _DONE:
                    done_signals += 1
                else:
                    m, path = item
                    fut = pool.submit(
                        _transform_export_one,
                        path, year, m, str(out_dir),
                        night_mask, complevel,
                        skip_existing=True,
                        cleanup=cleanup,
                    )
                    futures[fut] = m
            except queue.Empty:
                pass

            # Reap any finished transforms.
            done = [f for f in futures if f.done()]
            for f in done:
                msg = f.result()
                with results_lock:
                    results.append(msg)
                logger.info("  %s", msg)
                del futures[f]

    for t in dl_threads:
        t.join(timeout=1)

    logger.info(
        "Interleaved year %d done in %.1f s", year,
        time.perf_counter() - t0,
    )
    return results
