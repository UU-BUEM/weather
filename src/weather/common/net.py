"""HTTP networking utilities: auth helpers, retry logic, and rate limiting.

Shared by all providers that fetch data over HTTP/HTTPS.  Providers should
import individual helpers as needed rather than depending on this module as
a whole.

Public API
----------
build_session(auth, ...)        Build a ``requests.Session`` with auth/retry.
exponential_backoff(...)        Decorator — retry a function with back-off.
RateLimiter                     Context-manager / callable rate limiter.
netrc_auth(host)                Look up credentials from ``~/.netrc``.
earthdata_auth()                Return NASA Earthdata credentials.
"""

from __future__ import annotations

# pyright: reportMissingImports=false, reportMissingModuleSource=false

import logging
import netrc
import os
import random
import time
from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar

import requests  # type: ignore[import-untyped]
from requests.adapters import HTTPAdapter  # type: ignore[import-untyped]
from urllib3.util.retry import Retry

log = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_RETRIES = 5
_DEFAULT_BACKOFF_FACTOR = 1.0          # seconds; doubles on each retry
_DEFAULT_STATUS_FORCELIST = (429, 500, 502, 503, 504)
_DEFAULT_TIMEOUT = (10, 300)           # (connect, read) seconds


# ---------------------------------------------------------------------------
# Session / adapter
# ---------------------------------------------------------------------------

def build_session(
    auth: tuple[str, str] | None = None,
    *,
    retries: int = _DEFAULT_RETRIES,
    backoff_factor: float = _DEFAULT_BACKOFF_FACTOR,
    status_forcelist: tuple[int, ...] = _DEFAULT_STATUS_FORCELIST,
    timeout: tuple[int, int] = _DEFAULT_TIMEOUT,
) -> requests.Session:
    """Return a ``requests.Session`` pre-configured with retry and
    optional auth.

    Parameters
    ----------
    auth:
        ``(username, password)`` tuple.  ``None`` for unauthenticated requests.
    retries:
        Total number of retries on transient failures.
    backoff_factor:
        Base back-off multiplier (seconds).  Actual wait = ``backoff_factor *
        2 ** (attempt - 1)`` plus a small random jitter.
    status_forcelist:
        HTTP status codes that trigger an automatic retry.
    timeout:
        ``(connect_timeout, read_timeout)`` in seconds stored on the session
        so callers can pass ``timeout=session._default_timeout``.
    """
    retry_strategy = Retry(
        total=retries,
        backoff_factor=backoff_factor,
        status_forcelist=status_forcelist,
        allowed_methods={"GET", "HEAD"},
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)

    session = requests.Session()
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    if auth is not None:
        session.auth = auth

    # Stash for callers that want to forward it
    session._default_timeout = timeout  # type: ignore[attr-defined]

    return session


# ---------------------------------------------------------------------------
# Retry decorator
# ---------------------------------------------------------------------------

def exponential_backoff(
    max_attempts: int = _DEFAULT_RETRIES,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exceptions: tuple[type[Exception], ...] = (Exception,),
) -> Callable[[F], F]:
    """Decorator: retry *func* up to *max_attempts* times with
    exponential back-off.

    Parameters
    ----------
    max_attempts:
        Maximum number of call attempts (including the first try).
    base_delay:
        Initial wait in seconds before the first retry.
    max_delay:
        Upper cap for the computed wait interval.
    exceptions:
        Exception types that should trigger a retry.  All other exceptions
        propagate immediately.
    """

    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:
                    if attempt == max_attempts:
                        raise
                    jitter = random.uniform(0, base_delay)
                    delay = min(
                        base_delay * (2 ** (attempt - 1)) + jitter,
                        max_delay,
                    )
                    log.warning(
                        "%s failed (attempt %d/%d): %s — retrying in %.1fs",
                        func.__qualname__,
                        attempt,
                        max_attempts,
                        exc,
                        delay,
                    )
                    time.sleep(delay)

        return wrapper  # type: ignore[return-value]

    return decorator


# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------

class RateLimiter:
    """Simple token-bucket rate limiter.

    Ensures at most *calls_per_second* calls pass through per wall-clock
    second.  Safe for single-threaded use; not thread-safe.

    Usage::

        limiter = RateLimiter(calls_per_second=2)

        for url in urls:
            limiter()               # block until slot is available
            response = session.get(url)

        # Or as a context manager:
        with RateLimiter(calls_per_second=2) as limiter:
            ...
    """

    def __init__(self, calls_per_second: float = 1.0) -> None:
        if calls_per_second <= 0:
            raise ValueError("calls_per_second must be positive")
        self._min_interval = 1.0 / calls_per_second
        self._last_call: float = 0.0

    def __call__(self) -> None:
        now = time.monotonic()
        wait = self._min_interval - (now - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    def __enter__(self) -> "RateLimiter":
        return self

    def __exit__(self, *_: Any) -> None:
        pass


# ---------------------------------------------------------------------------
# Credential helpers
# ---------------------------------------------------------------------------

def netrc_auth(host: str) -> tuple[str, str] | None:
    """Return ``(login, password)`` from ``~/.netrc`` for *host*, or ``None``.

    Silently returns ``None`` if the file does not exist or the host is not
    listed — callers should fall back to environment variables.
    """
    try:
        rc = netrc.netrc()
        entry = rc.authenticators(host)
        if entry:
            login, _, password = entry
            return login, password or ""
    except (OSError, netrc.NetrcParseError):
        pass
    return None


def earthdata_auth() -> tuple[str, str]:
    """Return NASA Earthdata ``(username, password)``.

    Resolution order:
    1. ``EARTHDATA_USERNAME`` / ``EARTHDATA_PASSWORD`` environment variables.
    2. ``~/.netrc`` entry for ``urs.earthdata.nasa.gov``.

    Raises
    ------
    EnvironmentError
        If credentials cannot be resolved from either source.
    """
    username = os.environ.get("EARTHDATA_USERNAME")
    password = os.environ.get("EARTHDATA_PASSWORD")

    if username and password:
        return username, password

    creds = netrc_auth("urs.earthdata.nasa.gov")
    if creds:
        return creds

    raise EnvironmentError(
        "NASA Earthdata credentials not found.\n"
        "Set EARTHDATA_USERNAME and EARTHDATA_PASSWORD "
        "environment variables,\n"
        "or add an entry for 'urs.earthdata.nasa.gov' to ~/.netrc:\n\n"
        "  machine urs.earthdata.nasa.gov login <user> password <pass>\n"
    )
