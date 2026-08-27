"""Retroactive CF-metadata repair for already-exported NetCDF files.

``cf_conventions.attach_cf_metadata`` fixes every FUTURE export, but the
production archives predate it: as of 2026-08-24 all 296 COSMO-REA6
monthly files on ``sd26`` carried zero global attributes and three wrong
``standard_name`` values apiece.  Re-running the pipelines to fix
metadata would cost days of compute and re-read terabytes of GRIB for a
change that touches no data at all, so this module edits the attributes
of finished files in place instead.

Why this lives in ``common/`` and not in ``tests/``: it mutates real
output files, which is pipeline logic, not validation -- the same
principle that moved ``repair_month_boundaries.py`` into
``providers/era5_land/boundary_repair.py``.

The repair is **metadata-only and idempotent**.  Variable data is never
read, decoded, recomputed or rewritten -- only ``ncattrs`` are touched --
so a per-variable checksum is identical before and after.  This was
verified byte-for-byte on the real 529 MB Netherlands file before the
tool was used on the archive.

Standalone usage::

    python -m weather.common.metadata_repair \\
        /data/soma/cosmo_rea6/output --provider cosmo_rea6
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import os
from pathlib import Path
from typing import Any

import netCDF4
import numpy as np

from .cf_conventions import (
    CF_STANDARD_NAMES,
    GEOGRAPHIC_WIND_NAMES,
    PROVIDER_METADATA,
    STALE_GRIB_GRID_ATTRS,
    WIND_ROTATION_COMMENT,
    is_invalid_standard_name,
)

logger = logging.getLogger(__name__)

os.environ.setdefault("HDF5_USE_FILE_LOCKING", "FALSE")

#: Marker written into ``history`` so a re-run can recognise its own work
#: and report it as a no-op rather than appending a second stamp.
REPAIR_MARKER = "cf-metadata-repair-v3"

#: Global attributes kept as-is when the file already sets them, so an
#: archive-wide sweep cannot overwrite per-file customisation.  Pass
#: ``extra`` to override any of these deliberately.
PRESERVE_IF_SET: tuple[str, ...] = ("title", "summary")


def repair_metadata(
    path: Path,
    provider: str,
    *,
    region: str | None = None,
    extra: dict[str, str] | None = None,
    dry_run: bool = False,
) -> dict[str, int]:
    """Repair one finished NetCDF file's metadata in place.

    Parameters
    ----------
    path : Path
        NetCDF file to repair.  Opened ``r+`` unless *dry_run*.
    provider : str
        Key into :data:`~weather.common.cf_conventions.PROVIDER_METADATA`.
    region : str, optional
        Crop region recorded as ``crop_region``.
    extra : dict, optional
        Extra global attributes, applied last.
    dry_run : bool
        Report what would change without writing.

    Returns
    -------
    dict
        Counts: ``stale_attrs``, ``standard_names``, ``cell_methods``,
        ``globals``, and ``already`` (1 if the file was already repaired).
    """
    meta = PROVIDER_METADATA[provider]
    cell_methods = meta.get("cell_methods", {})
    grid_relative = meta.get("wind_is_grid_relative", False)
    counts = {
        "stale_attrs": 0,
        "standard_names": 0,
        "cell_methods": 0,
        "globals": 0,
        "already": 0,
    }

    ds = netCDF4.Dataset(path, "r" if dry_run else "r+")
    try:
        if REPAIR_MARKER in str(getattr(ds, "history", "")):
            counts["already"] = 1
            return counts

        for name, var in ds.variables.items():
            present = set(var.ncattrs())

            for stale in STALE_GRIB_GRID_ATTRS:
                if stale in present:
                    counts["stale_attrs"] += 1
                    if not dry_run:
                        var.delncattr(stale)

            current = (
                var.getncattr("standard_name")
                if "standard_name" in present
                else None
            )
            if (
                current is not None
                and is_invalid_standard_name(current)
                and name not in CF_STANDARD_NAMES
                and name not in GEOGRAPHIC_WIND_NAMES
            ):
                # Not in any mapping, and the value it carries is not a
                # CF name -- strip it rather than invent a replacement.
                counts["standard_names"] += 1
                if not dry_run:
                    var.delncattr("standard_name")

            if name in CF_STANDARD_NAMES:
                if current != CF_STANDARD_NAMES[name]:
                    counts["standard_names"] += 1
                    if not dry_run:
                        var.setncattr("standard_name", CF_STANDARD_NAMES[name])
            elif name in GEOGRAPHIC_WIND_NAMES:
                if grid_relative:
                    if "standard_name" in present:
                        counts["standard_names"] += 1
                        if not dry_run:
                            var.delncattr("standard_name")
                    if not dry_run:
                        var.setncattr("comment", WIND_ROTATION_COMMENT)
                else:
                    counts["standard_names"] += 1
                    if not dry_run:
                        var.setncattr(
                            "standard_name", GEOGRAPHIC_WIND_NAMES[name]
                        )

            if name in cell_methods:
                counts["cell_methods"] += 1
                if not dry_run:
                    var.setncattr("cell_methods", cell_methods[name])

        if "time" in ds.variables:
            counts["standard_names"] += 1
            if not dry_run:
                ds.variables["time"].setncattr("standard_name", "time")
                ds.variables["time"].setncattr("axis", "T")

        attrs = _global_attrs(ds, provider, region=region)
        # A per-file title is legitimate customisation (e.g. the shipped
        # "... , Netherlands, 2018" file) and an archive-wide sweep must
        # not silently flatten it back to the generic provider title.
        # Found the hard way: the first licence sweep did exactly that.
        for key in PRESERVE_IF_SET:
            if key in ds.ncattrs() and str(getattr(ds, key)).strip():
                attrs[key] = getattr(ds, key)
        if extra:
            attrs.update(extra)
        counts["globals"] = len(attrs)
        if not dry_run:
            ds.setncatts(attrs)
    finally:
        ds.close()

    return counts


def _global_attrs(
    ds: netCDF4.Dataset, provider: str, *, region: str | None
) -> dict:
    """Build the CF global attribute set from an open netCDF4 dataset.

    Bounds are read from the file's own arrays rather than supplied by
    the caller, so they cannot describe a grid the file does not have --
    the exact failure mode this repair exists to fix.
    """
    meta = PROVIDER_METADATA[provider]
    attrs: dict = {
        "Conventions": "CF-1.8",
        "title": meta["title"],
        "institution": meta["institution"],
        "source": meta["source"],
        "references": meta["references"],
    }
    if meta.get("license"):
        attrs["license"] = meta["license"]

    parts = [meta["time_convention"]]
    parts.extend(str(v) for v in meta.get("extra", {}).values())
    attrs["comment"] = " ".join(parts)

    coverage_year = ""
    if "time" in ds.variables and ds.variables["time"].size:
        tvar = ds.variables["time"]
        edges: Any = np.atleast_1d(
            netCDF4.num2date(  # type: ignore[arg-type]
                tvar[[0, -1]],
                tvar.units,
                only_use_cftime_datetimes=False,
                only_use_python_datetimes=True,
            )
        )
        coverage_year = edges[0].strftime("%Y")
        attrs["time_coverage_start"] = edges[0].strftime("%Y-%m-%dT%H:%M:%SZ")
        attrs["time_coverage_end"] = edges[-1].strftime("%Y-%m-%dT%H:%M:%SZ")
        if tvar.size > 1:
            step: Any = np.atleast_1d(
                netCDF4.num2date(  # type: ignore[arg-type]
                    tvar[:2], tvar.units,
                    only_use_cftime_datetimes=False,
                    only_use_python_datetimes=True,
                )
            )
            hours = int(round((step[1] - step[0]).total_seconds() / 3600))
            attrs["time_coverage_resolution"] = f"PT{hours}H"

    for coord, lo, hi in (
        ("latitude", "geospatial_lat_min", "geospatial_lat_max"),
        ("longitude", "geospatial_lon_min", "geospatial_lon_max"),
    ):
        if coord in ds.variables:
            values = np.asarray(ds.variables[coord][:], dtype="float64")
            attrs[lo] = float(np.nanmin(values))
            attrs[hi] = float(np.nanmax(values))
    if "latitude" in ds.variables:
        attrs["geospatial_bounds_crs"] = "EPSG:4326"

    if region:
        attrs["crop_region"] = region

    if meta.get("attribution"):
        attrs["attribution"] = str(meta["attribution"]).replace(
            "{year}", coverage_year
        ).strip()

    stamp = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    attrs["history"] = (
        f"{stamp}: {REPAIR_MARKER} -- CF global attributes added, stale "
        f"source-grid GRIB attributes removed, standard_name corrections "
        f"applied. Metadata only; no variable data altered."
    )
    return attrs


def repair_archive(
    directory: Path,
    provider: str,
    *,
    pattern: str = "*.nc",
    region: str | None = None,
    dry_run: bool = False,
) -> dict[str, int]:
    """Repair every matching NetCDF file in *directory*.

    Returns
    -------
    dict
        Aggregate counts plus ``files`` and ``skipped`` (already
        repaired).
    """
    files = sorted(directory.glob(pattern))
    total = {
        "files": 0,
        "skipped": 0,
        "stale_attrs": 0,
        "standard_names": 0,
        "cell_methods": 0,
    }
    for path in files:
        try:
            counts = repair_metadata(
                path, provider, region=region, dry_run=dry_run
            )
        except Exception:  # noqa: BLE001
            logger.exception("failed to repair %s", path.name)
            continue
        if counts["already"]:
            total["skipped"] += 1
            continue
        total["files"] += 1
        for key in ("stale_attrs", "standard_names", "cell_methods"):
            total[key] += counts[key]
        logger.info("repaired %s", path.name)
    return total


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Repair CF metadata of already-exported NetCDF files."
    )
    parser.add_argument("directory", type=Path, help="Directory of .nc files.")
    parser.add_argument(
        "--provider", required=True, choices=sorted(PROVIDER_METADATA),
        help="Which provider wrote these files.",
    )
    parser.add_argument(
        "--pattern", default="*.nc", help="Glob within the directory."
    )
    parser.add_argument(
        "--region", default=None, help="Crop region for crop_region."
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Report without writing."
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    total = repair_archive(
        args.directory,
        args.provider,
        pattern=args.pattern,
        region=args.region,
        dry_run=args.dry_run,
    )
    logger.info(
        "done: %d repaired, %d already repaired, %d stale attrs removed, "
        "%d standard_names set, %d cell_methods set",
        total["files"], total["skipped"], total["stale_attrs"],
        total["standard_names"], total["cell_methods"],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
