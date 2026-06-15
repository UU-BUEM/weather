"""Abstract base class for weather-data downloaders.

Each weather data provider has a concrete subclass:

+----------------+--------------------------------------------+
| Provider       | Concrete subclass                          |
+================+============================================+
| COSMO-REA6     | ``cosmo_rea6.downloader.CosmoDownloader``  |
+----------------+--------------------------------------------+
| MERRA-2        | ``merra2.downloader.Merra2Downloader``     |
+----------------+--------------------------------------------+
| ERA5-Land      | ``era5_land.downloader.Era5Downloader``    |
+----------------+--------------------------------------------+

Template-method workflow (see :meth:`BaseDownloader.get`)::

    is_complete(job)?
        yes  -> return cached local_path(job)   # zero network I/O
        no   -> _fetch(job)                      # provider-specific

Subclasses must implement three abstract methods:

* :meth:`remote_size` — query file size on the remote source.
* :meth:`local_path`  — resolve the expected local destination path.
* :meth:`_fetch`      — perform the actual download.

The non-abstract :meth:`is_complete` and :meth:`get` provide the
shared skip-if-already-downloaded logic that is identical for every
provider.

``DownloadJob`` is a lightweight frozen dataclass that bundles the
three coordinates that identify a single downloadable file for
attribute-per-month providers (COSMO-REA6).  Providers with a
different granularity (e.g. MERRA-2 daily files) define their own
job type and annotate their subclass accordingly.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DownloadJob:
    """Coordinates identifying one downloadable file.

    Attributes
    ----------
    attribute : str
        Variable name (e.g. ``"SWDIRS_RAD"``).
    year : int
        Four-digit year.
    month : int
        Month (1–12).
    """

    attribute: str
    year: int
    month: int

    def __str__(self) -> str:
        return (
            f"{self.attribute} "
            f"{self.year}-{self.month:02d}"
        )


class BaseDownloader(ABC):
    """Template-method base class for provider file downloaders.

    Concrete subclasses implement the three abstract methods below.
    The public :meth:`get` method orchestrates the full
    check-then-fetch workflow and is shared by all providers.

    Examples
    --------
    Typical subclass skeleton::

        class MyDownloader(BaseDownloader):
            def remote_size(self, job):
                ...  # HEAD request or catalog lookup

            def local_path(self, job):
                ...  # provider-specific path layout

            def _fetch(self, job):
                ...  # actual download to local_path(job)
    """

    # ------------------------------------------------------------------
    # Abstract interface — subclasses must override
    # ------------------------------------------------------------------

    @abstractmethod
    def remote_size(self, job: DownloadJob) -> int | None:
        """Return the expected file size on the remote source.

        Parameters
        ----------
        job : DownloadJob
            Download coordinates.

        Returns
        -------
        int or None
            File size in bytes, or ``None`` when the remote source
            cannot report a size before the download is initiated
            (e.g. CDS API queue-based responses).
        """

    @abstractmethod
    def local_path(self, job: DownloadJob) -> Path:
        """Return the expected local destination path for *job*.

        The parent directory need not exist yet; :meth:`_fetch` is
        responsible for creating it.

        Parameters
        ----------
        job : DownloadJob
            Download coordinates.
        """

    @abstractmethod
    def _fetch(self, job: DownloadJob) -> Path:
        """Execute the provider-specific download.

        This method is called *only* when :meth:`is_complete` returns
        ``False``.  Implementations should write to a temporary file
        and atomically rename it to :meth:`local_path` on success.

        Parameters
        ----------
        job : DownloadJob
            Download coordinates.

        Returns
        -------
        Path
            Absolute path to the downloaded file.
        """

    # ------------------------------------------------------------------
    # Concrete shared logic — not normally overridden
    # ------------------------------------------------------------------

    def is_complete(self, job: DownloadJob) -> bool:
        """Return ``True`` if the local file exists and size is valid.

        A file is considered complete when:

        1. It exists at :meth:`local_path`.
        2. Its on-disk size is non-zero.
        3. Its size equals the remote size reported by
           :meth:`remote_size` — or the remote size is ``None``
           (cannot be checked), in which case existence alone is
           treated as sufficient.

        Parameters
        ----------
        job : DownloadJob
            Download coordinates.
        """
        path = self.local_path(job)
        if not path.exists():
            return False
        if path.stat().st_size == 0:
            return False
        expected = self.remote_size(job)
        if expected is None:
            return True   # remote can't report size; trust local
        return path.stat().st_size == expected

    def get(self, job: DownloadJob) -> Path:
        """Return the local file, downloading only if necessary.

        Applies the template-method check-then-fetch pattern:

        1. If :meth:`is_complete` is ``True``, return
           :meth:`local_path` immediately (no network I/O).
        2. Otherwise delegate to :meth:`_fetch` and return its result.

        Parameters
        ----------
        job : DownloadJob
            Download coordinates.

        Returns
        -------
        Path
            Absolute path to the (possibly freshly downloaded) file.
        """
        if self.is_complete(job):
            return self.local_path(job)
        return self._fetch(job)
