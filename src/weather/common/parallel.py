"""Shared thread-pool executor for I/O-bound parallel tasks.

Extracts the ``ThreadPoolExecutor`` boilerplate that is otherwise
duplicated across every provider's ``download_all()`` and
``decompress_all()`` functions.

Typical usage::

    from weather.common.parallel import run_parallel

    results = run_parallel(
        fn=download_one,
        jobs=[(attr, month) for attr in attrs for month in months],
        max_workers=8,
        logger=logger,
    )
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

_log = logging.getLogger(__name__)


def run_parallel(
    fn: Callable[..., Any],
    jobs: Sequence[Any],
    max_workers: int = 8,
    logger: logging.Logger | None = None,
) -> list[Any]:
    """Execute *fn* on each item in *jobs* using a thread pool.

    Parameters
    ----------
    fn : callable
        Function accepting a single positional argument (one job) and
        returning a result value.
    jobs : sequence
        Items to process.  Each is passed as the sole argument to *fn*.
    max_workers : int
        Maximum number of concurrent threads.  Defaults to 8.
    logger : logging.Logger, optional
        Logger for progress and error messages.  Defaults to the
        module-level logger.

    Returns
    -------
    list
        Results in the order that futures completed (not job order).
        If any job raises an exception it is re-raised here after the
        exception has been logged.

    Notes
    -----
    * I/O-bound work (HTTP, disk) benefits from thread concurrency even
      under the GIL.  For CPU-bound work use
      :class:`concurrent.futures.ProcessPoolExecutor` instead.
    * Exceptions are logged at ``ERROR`` level and then re-raised
      immediately, cancelling remaining futures in flight.
    """
    log = logger or _log
    if not jobs:
        log.debug("run_parallel: no jobs to process.")
        return []

    n = len(jobs)
    workers = min(n, max_workers)
    log.debug(
        "run_parallel: %d jobs, %d workers, fn=%s",
        n,
        workers,
        getattr(fn, "__name__", fn),
    )

    results: list[Any] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fn, j): j for j in jobs}
        for future in as_completed(futures):
            job = futures[future]
            try:
                results.append(future.result())
            except Exception:
                log.exception(
                    "run_parallel: task failed for job %r", job
                )
                raise

    return results
