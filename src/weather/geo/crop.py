"""NetCDF bounding-box cropping via CDO.

Actually crops output NetCDFs to a country's extent (not just a lookup),
so that downstream consumers — currently
``THD-Spatial-AI/merra2-energy-pipeline`` — receive already-cropped data
and don't need their own geo-cropping logic.

Scope
-----
Works today for ERA5-Land and MERRA-2 output NetCDFs: both carry a
regular, CF-compliant lat/lon grid. COSMO-REA6's current production
export carries **no** lat/lon coordinates at all (only rotated-pole
``rlat``/``rlon`` dims — see ``providers/cosmo_rea6/transform.py`` and
``export.py``), so there is nothing for CDO to crop against yet; that
needs a separate COSMO export change (tracked in ``.claude/open.md``),
not attempted here. :func:`crop_netcdf` does not special-case this — it
lets CDO's own error surface.

Not wired into any provider's ``pipeline.py``. This is a standalone
post-processing step, run against an already-exported output file (see
the ``weather geo crop`` CLI subcommand).

Typical usage::

    from weather.geo.crop import crop_to_country

    crop_to_country(
        Path("ERA5_Land_2020_06.nc"),
        Path("ERA5_Land_2020_06_netherlands.nc"),
        "netherlands",
    )
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from .bbox import BBox
from .countries import get_bbox


def _cdo_available() -> bool:
    return shutil.which("cdo") is not None


def crop_netcdf(
    input_path: Path,
    output_path: Path,
    bbox: BBox,
    *,
    logger: logging.Logger | None = None,
) -> Path:
    """Crop *input_path* to *bbox* via ``cdo sellonlatbox``.

    Parameters
    ----------
    input_path : Path
        Source NetCDF with a regular (or CDO-recognised curvilinear)
        lat/lon grid.
    output_path : Path
        Destination path for the cropped NetCDF.
    bbox : BBox
        Crop extent.
    logger : logging.Logger, optional
        Logger for progress messages; defaults to this module's logger.

    Returns
    -------
    Path
        *output_path*, once the crop has completed successfully.

    Raises
    ------
    RuntimeError
        If the ``cdo`` binary is not on ``PATH`` (see
        ``infrastructure/env/weather_env.yml``).
    FileNotFoundError
        If *input_path* does not exist.
    subprocess.CalledProcessError
        If ``cdo`` itself fails (e.g. no lat/lon grid to crop against).
    """
    log = logger or logging.getLogger(__name__)
    if not input_path.exists():
        raise FileNotFoundError(f"Input NetCDF not found: {input_path}")
    if not _cdo_available():
        raise RuntimeError(
            "cdo is not installed or not on PATH. Install it via "
            "'conda install -c conda-forge cdo' — see "
            "infrastructure/env/weather_env.yml."
        )

    west, east, south, north = bbox.to_cdo_lonlatbox()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=output_path.parent,
        prefix=f".{output_path.name}.",
        suffix=".part",
    )
    os.close(tmp_fd)

    args = [
        "cdo",
        "-O",  # tmp_path already exists (mkstemp reserved it) -- force overwrite
        "-L",
        f"sellonlatbox,{west},{east},{south},{north}",
        str(input_path),
        tmp_path,
    ]
    log.info(
        "Cropping %s to [W=%s,E=%s,S=%s,N=%s]",
        input_path.name, west, east, south, north,
    )
    try:
        result = subprocess.run(args, capture_output=True, text=True)
        if result.returncode != 0:
            log.error("cdo failed (exit %d): %s", result.returncode, result.stderr.strip())
            raise subprocess.CalledProcessError(
                result.returncode, args, output=result.stdout, stderr=result.stderr
            )
        Path(tmp_path).replace(output_path)
    except BaseException:
        Path(tmp_path).unlink(missing_ok=True)
        raise
    log.info("Cropped NetCDF written: %s", output_path.name)
    return output_path


def crop_to_country(
    input_path: Path,
    output_path: Path,
    country: str,
    *,
    logger: logging.Logger | None = None,
) -> Path:
    """Crop *input_path* to *country*'s bounding box (see :mod:`.countries`)."""
    return crop_netcdf(
        input_path, output_path, get_bbox(country), logger=logger
    )
