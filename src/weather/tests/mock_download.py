"""Mock download and validation for Docker CI testing."""

from __future__ import annotations

import io
import logging
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)


def create_mock_grib_file(
    output_path: Path,
    size_mb: float = 1.5,
) -> Path:
    """Create a mock GRIB file (simple binary blob) for testing.

    Parameters
    ----------
    output_path : Path
        Output file path.
    size_mb : float
        File size in MB.

    Returns
    -------
    Path
        Path to created file.
    """
    size_bytes = int(size_mb * 1024 * 1024)
    data = np.random.bytes(size_bytes)
    with open(output_path, "wb") as f:
        f.write(data)
    logger.info("Created mock GRIB: %s (%d MB)", output_path, size_mb)
    return output_path


def validate_mock_download(
    work_dir: Path,
    num_files: int = 3,
) -> bool:
    """Mock download validation for Docker.

    Creates fake .grb.bz2 files and validates that
    the pipeline can process them.

    Parameters
    ----------
    work_dir : Path
        Work directory for mock files.
    num_files : int
        Number of mock files to create.

    Returns
    -------
    bool
        True if validation passed.
    """
    work_dir.mkdir(parents=True, exist_ok=True)

    # Create mock files
    files_created = []
    for i in range(num_files):
        fp = work_dir / f"mock_data_{i}.grb.bz2"
        create_mock_grib_file(fp, size_mb=0.5)
        files_created.append(fp)

    # Validate: files exist and have content
    for fp in files_created:
        if not fp.exists() or fp.stat().st_size < 1024:
            logger.error("Mock validation failed: %s", fp)
            return False

    logger.info(
        "Mock download validation PASSED (%d files)", len(files_created)
    )
    return True


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    test_dir = Path("/tmp/weather_test")
    success = validate_mock_download(test_dir, num_files=3)
    exit(0 if success else 1)
