"""Abstract base class for weather-data decompressors.

Mirrors the design of :mod:`.base_downloader`: subclasses implement
three abstract methods and inherit the shared skip-if-done logic.

Template-method workflow (see :meth:`BaseDecompressor.get`)::

    is_decompressed(job)?
        yes  -> return decompressed_path(job)   # already done
        no   -> _decompress_file(src, dest)     # provider-specific

Validity check
--------------
A decompressed file is considered valid when:

1. The output file exists.
2. Its size is non-zero.
3. Its size **exceeds** the compressed source file (BZIP2 for
   COSMO-REA6 gives roughly a 4–5× expansion ratio).  When the
   compressed source is no longer present (already cleaned up),
   criteria 1 and 2 are sufficient.

Concrete subclasses
-------------------
+----------------+-----------------------------------------------+
| Provider       | Concrete subclass                             |
+================+===============================================+
| COSMO-REA6     | ``cosmo_rea6.decompressor.CosmoDecompressor`` |
+----------------+-----------------------------------------------+
| MERRA-2        | N/A — files are NetCDF4 (no bz2 wrapper)      |
+----------------+-----------------------------------------------+
| ERA5-Land      | N/A — files are NetCDF4 (no bz2 wrapper)      |
+----------------+-----------------------------------------------+

MERRA-2 and ERA5-Land download NetCDF4/HDF5 files that are already in
a usable form, so neither provider needs a separate decompression step.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from .base_downloader import DownloadJob


class BaseDecompressor(ABC):
    """Template-method base class for provider file decompressors.

    Concrete subclasses implement the three abstract methods.  The
    public :meth:`get` method orchestrates the check-then-decompress
    workflow and is shared by all providers that require it.

    Examples
    --------
    Typical subclass skeleton::

        class MyDecompressor(BaseDecompressor):
            def compressed_path(self, job):
                ...  # e.g. download_dir / attr / fname.bz2

            def decompressed_path(self, job):
                ...  # e.g. decompress_dir / attr / fname

            def _decompress_file(self, src, dest):
                ...  # bz2, gzip, zstd — whatever the provider uses
    """

    # ------------------------------------------------------------------
    # Abstract interface — subclasses must override
    # ------------------------------------------------------------------

    @abstractmethod
    def compressed_path(self, job: DownloadJob) -> Path:
        """Return the path to the compressed source file for *job*.

        Parameters
        ----------
        job : DownloadJob
            Download coordinates that identify this file.
        """

    @abstractmethod
    def decompressed_path(self, job: DownloadJob) -> Path:
        """Return the expected path of the decompressed output file.

        The parent directory need not exist yet; :meth:`_decompress_file`
        is responsible for creating it.

        Parameters
        ----------
        job : DownloadJob
            Download coordinates.
        """

    @abstractmethod
    def _decompress_file(self, src: Path, dest: Path) -> Path:
        """Execute the provider-specific decompression.

        Called *only* when :meth:`is_decompressed` returns ``False``.
        Implementations should write atomically (temp-file then rename).

        Parameters
        ----------
        src : Path
            Compressed source file.
        dest : Path
            Target path for the decompressed output.

        Returns
        -------
        Path
            Absolute path to the decompressed file.
        """

    # ------------------------------------------------------------------
    # Concrete shared logic — not normally overridden
    # ------------------------------------------------------------------

    def is_decompressed(self, job: DownloadJob) -> bool:
        """Return ``True`` if the decompressed file already exists and
        appears valid.

        Validity criteria:

        1. :meth:`decompressed_path` exists.
        2. Size > 0.
        3. Size > compressed source size (confirming expansion has
           occurred).  If the compressed file has been removed, only
           criteria 1–2 are checked.

        Parameters
        ----------
        job : DownloadJob
            Download coordinates.
        """
        decompressed = self.decompressed_path(job)
        if not decompressed.exists():
            return False

        d_size = decompressed.stat().st_size
        if d_size == 0:
            return False

        compressed = self.compressed_path(job)
        if compressed.exists():
            c_size = compressed.stat().st_size
            # A valid decompressed GRIB must be larger than its
            # bz2-compressed form (typical ratio ≥ 4×).
            return c_size > 0 and d_size > c_size

        # Compressed source already cleaned up — existence is enough.
        return True

    def get(self, job: DownloadJob) -> Path:
        """Return the decompressed file, decompressing only if needed.

        Applies the template-method check-then-decompress pattern:

        1. If :meth:`is_decompressed` is ``True``, return
           :meth:`decompressed_path` immediately (no I/O).
        2. Otherwise call :meth:`_decompress_file` and return its
           result.

        Parameters
        ----------
        job : DownloadJob
            Download coordinates.

        Returns
        -------
        Path
            Absolute path to the decompressed file.
        """
        if self.is_decompressed(job):
            return self.decompressed_path(job)
        src = self.compressed_path(job)
        dest = self.decompressed_path(job)
        return self._decompress_file(src, dest)
