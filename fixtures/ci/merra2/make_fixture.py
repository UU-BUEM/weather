"""Regenerate the MERRA-2 CI fixture in ``fixtures/ci/merra2/output/``.

This fixture exists so downstream consumers (currently ``buem``, see
``fixtures/ci/README.md``) can call ``weather.get_point_weather()`` in CI
without a full ~1-2 GB/year processed archive committed to the repo.

Canonical, reproducible crop command (Linux, where ``cdo`` is installed —
e.g. ``sd26``)::

    from pathlib import Path
    from weather.geo.bbox import BBox
    from weather.geo.crop import crop_netcdf

    bbox = BBox(north=52.5, west=4.5, south=51.5, east=5.5)
    for month in range(1, 13):
        name = f"MERRA2_2018_{month:02d}_all_attrs.nc"
        crop_netcdf(
            Path("data/merra2/output") / name,
            Path("fixtures/ci/merra2/output") / name,
            bbox,
        )

This script is a **Windows-compatible equivalent** of the above: ``cdo``
has no ``win-64`` build on conda-forge (confirmed via
``conda search -c conda-forge cdo`` — only the unrelated ``python-cdo``
wrapper package exists), so it can't run on the Windows dev machine this
fixture was actually generated on. ``crop_netcdf`` itself is just
``cdo sellonlatbox,west,east,south,north`` around a regular lat/lon grid;
on MERRA-2's regular grid that is exactly equivalent to an inclusive
``xarray`` coordinate slice, which is what this script does instead. If
regenerating on a Linux box with ``cdo`` available, prefer the snippet
above (via ``weather geo crop`` or ``crop_netcdf`` directly) so the
fixture is produced by the same code path downstream users rely on.

Usage::

    python fixtures/ci/merra2/make_fixture.py
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import xarray as xr

from weather.geo.bbox import BBox

REPO_ROOT = Path(__file__).resolve().parents[3]
SOURCE_DIR = REPO_ROOT / "data" / "merra2" / "output"
DEST_DIR = REPO_ROOT / "fixtures" / "ci" / "merra2" / "output"
YEAR = 2018
BBOX = BBox(north=52.5, west=4.5, south=51.5, east=5.5)


def _crop_one(src: Path, dest: Path, bbox: BBox) -> None:
    with xr.open_dataset(src) as ds:
        cropped = ds.sel(
            latitude=slice(bbox.south, bbox.north),
            longitude=slice(bbox.west, bbox.east),
        ).load()

        encoding = {
            name: {"zlib": True, "complevel": 1, "dtype": "float32"}
            for name in cropped.data_vars
        }

        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=dest.parent, prefix=f".{dest.name}.", suffix=".part"
        )
        os.close(tmp_fd)
        try:
            cropped.to_netcdf(tmp_path, encoding=encoding)
            Path(tmp_path).replace(dest)
        except BaseException:
            Path(tmp_path).unlink(missing_ok=True)
            raise


def main() -> None:
    for month in range(1, 13):
        name = f"MERRA2_{YEAR}_{month:02d}_all_attrs.nc"
        src = SOURCE_DIR / name
        dest = DEST_DIR / name
        _crop_one(src, dest, BBOX)
        print(f"Cropped: {dest}")


if __name__ == "__main__":
    main()
