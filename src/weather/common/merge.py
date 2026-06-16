"""NetCDF-4 / HDF5 monthly-to-annual merge utilities.

``NetCDFMerger`` concatenates monthly NetCDF-4 files along the time
dimension using h5py.  Each variable is read one time-chunk at a time
(168 timesteps ≈ 1 week) and written with the same dtype and compression
settings as the source — no xarray/dask overhead, no full-file decompression
into RAM.  Significantly faster and more memory-efficient than
``xarray.open_mfdataset`` + ``to_netcdf`` for large files on GPFS/NFS.

Typical post-processing usage (after all monthly NC files are ready)::

    from weather.common.merge import NetCDFMerger
    from pathlib import Path

    monthly = sorted(
        Path("/data/output").glob("COSMO_REA6_2005_??_all_attrs.nc")
    )
    annual = Path("/data/output/COSMO_REA6_2005_annual_all_attrs.nc")
    NetCDFMerger.merge(
        monthly_paths=[str(p) for p in monthly],
        output_path=annual,
    )

Or use the CLI convenience script::

    python -m weather.common.merge \\
        --input  /data/output/COSMO_REA6_2005_??_all_attrs.nc \\
        --output /data/output/COSMO_REA6_2005_annual_all_attrs.nc
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path


class NetCDFMerger:
    """Merge monthly NetCDF-4 files into one annual file via h5py.

    All methods are class-level; instantiation is not required::

        NetCDFMerger.merge(monthly_paths, output_path)

    Design
    ------
    Reads each monthly file with h5py (no xarray/dask graph), copies CF
    attributes and static coordinates once, then appends time-varying data
    variables month by month in ``_COPY_CHUNK``-timestep slices to keep
    peak RAM bounded (~470 MB per slice × one variable at a time).

    Algorithm
    ---------
    ::

        Upfront: validate all source files exist.

        Open destination file for writing.

        For the first monthly file:
          ├─ Copy root HDF5 attributes (CF conventions, history …)
          ├─ Create 'time' dataset: shape=(0,), maxshape=(None,)
          ├─ Detect static coords: ndim==0 OR shape[0] != n_timesteps
          │   └─ copy verbatim with src.copy()
          └─ Create each time-varying data variable:
              shape=(0, ny, nx), maxshape=(None, ny, nx)
              same compression and dtype as source

        For ALL files (including the first):
          ├─ Resize and fill 'time' dataset
          └─ For each data variable, resize then write in
             _COPY_CHUNK-timestep slices
    """

    _TIME_DIM: str = "time"
    _COPY_CHUNK: int = 168  # timesteps per read/write slice (≈ 1 week)

    # HDF5 dimension-scale attributes that store file-specific object
    # references.  These cannot be transferred across files and are not
    # needed for xarray to read the output (CF 'coordinates' attr suffices).
    _HDF5_DIM_ATTRS: frozenset = frozenset(
        {"DIMENSION_LIST", "REFERENCE_LIST", "CLASS", "NAME"}
    )

    @classmethod
    def merge(
        cls,
        monthly_paths: list[str],
        output_path: Path,
        logger: logging.Logger | None = None,
    ) -> None:
        """Concatenate monthly NetCDF-4 files along time using h5py.

        Parameters
        ----------
        monthly_paths:
            Sorted list of monthly NC file paths (Jan … Dec).
        output_path:
            Destination annual NetCDF file (created or overwritten).
        logger:
            Progress logger.  Falls back to module logger if omitted.

        Raises
        ------
        ImportError
            If h5py is not installed in the current environment.
        RuntimeError
            If any source file is missing or no time-varying variables
            are found in the first source file.
        """
        try:
            import h5py  # type: ignore
        except ImportError as exc:
            raise ImportError(
                "h5py is required for NetCDFMerger.merge(). "
                "Install via: conda install -c conda-forge h5py"
            ) from exc

        log = logger or logging.getLogger(__name__)
        time_dim = cls._TIME_DIM
        output_path = Path(output_path)

        # ── Validate all source files exist before touching the output ──
        missing = [p for p in monthly_paths if not Path(p).exists()]
        if missing:
            raise RuntimeError(
                f"Missing {len(missing)} source file(s): "
                + ", ".join(str(p) for p in missing[:5])
                + (" …" if len(missing) > 5 else "")
            )

        if output_path.exists():
            output_path.unlink()

        with h5py.File(str(output_path), "w") as dst:
            coords_written: set[str] = set()
            data_vars: list[str] = []
            time_offset = 0

            for m_idx, src_path in enumerate(monthly_paths):
                log.info(
                    "  [merge %02d/%02d] %s",
                    m_idx + 1, len(monthly_paths),
                    Path(src_path).name,
                )
                with h5py.File(src_path, "r") as src:
                    time_size = src[time_dim].shape[0]

                    if m_idx == 0:
                        # ── Root HDF5 / CF global attributes ────────────
                        for k, v in src.attrs.items():
                            dst.attrs[k] = v

                        # ── Time dataset (start empty, unified fill below)
                        src_time = src[time_dim]
                        chunk_t = (
                            src_time.chunks[0]
                            if src_time.chunks
                            else cls._COPY_CHUNK
                        )
                        dst.create_dataset(
                            time_dim,
                            shape=(0,),
                            maxshape=(None,),
                            chunks=(chunk_t,),
                            compression=src_time.compression,
                            compression_opts=src_time.compression_opts,
                            dtype=src_time.dtype,
                        )
                        for k, v in src_time.attrs.items():
                            dst[time_dim].attrs[k] = v

                        # ── Static coordinates ───────────────────────────
                        # A dataset is static when its first dimension size
                        # does NOT equal time_size, or it is 0-D (scalar).
                        # Never use item.dims.keys() — DimensionProxy in
                        # h5py 3.x has no .keys() method.
                        for name, item in src.items():
                            if name == time_dim:
                                continue
                            if not isinstance(item, h5py.Dataset):
                                continue
                            if (
                                item.ndim == 0
                                or item.shape[0] != time_size
                            ):
                                src.copy(name, dst)
                                coords_written.add(name)

                        # ── Time-varying data variables ──────────────────
                        for name, item in src.items():
                            if (
                                name in coords_written
                                or name == time_dim
                            ):
                                continue
                            if not isinstance(item, h5py.Dataset):
                                continue
                            if (
                                item.ndim >= 1
                                and item.shape[0] == time_size
                            ):
                                spatial = item.shape[1:]
                                chunks = (
                                    item.chunks
                                    or (cls._COPY_CHUNK,) + spatial
                                )
                                dst.create_dataset(
                                    name,
                                    shape=(0,) + spatial,
                                    maxshape=(None,) + spatial,
                                    chunks=chunks,
                                    compression=item.compression,
                                    compression_opts=(
                                        item.compression_opts
                                    ),
                                    dtype=item.dtype,
                                )
                                # Copy CF attrs; skip HDF5 object-reference
                                # attributes (DIMENSION_LIST etc.) which are
                                # file-specific and invalid in destination.
                                for k, v in item.attrs.items():
                                    if k in cls._HDF5_DIM_ATTRS:
                                        continue
                                    dst[name].attrs[k] = v
                                data_vars.append(name)

                        if not data_vars:
                            raise RuntimeError(
                                "No time-varying data variables found "
                                f"in {Path(src_path).name}"
                            )
                        log.info(
                            "  Static coords : %s",
                            ", ".join(sorted(coords_written)),
                        )
                        log.info(
                            "  Data variables: %s",
                            ", ".join(data_vars),
                        )

                    # ── Append time values (all months, including first) ──
                    new_offset = time_offset + time_size
                    dst[time_dim].resize((new_offset,))
                    dst[time_dim][time_offset:new_offset] = (
                        src[time_dim][:]
                    )

                    # ── Append data variables in _COPY_CHUNK slices ──────
                    # Reads 168 timesteps at a time (~470 MB per variable
                    # slice) so peak RAM is bounded regardless of file size.
                    for name in data_vars:
                        if name not in src:
                            log.warning(
                                "  Variable %r missing in %s — skipping",
                                name, Path(src_path).name,
                            )
                            continue
                        src_ds = src[name]
                        dst[name].resize(
                            (new_offset,) + src_ds.shape[1:]
                        )
                        for t0 in range(
                            0, time_size, cls._COPY_CHUNK
                        ):
                            t1 = min(t0 + cls._COPY_CHUNK, time_size)
                            dst[name][
                                time_offset + t0: time_offset + t1
                            ] = src_ds[t0:t1]

                    time_offset = new_offset

        log.info(
            "  h5py merge complete: %d timesteps → %s  (%.1f MB)",
            time_offset,
            output_path.name,
            output_path.stat().st_size / (1024 * 1024),
        )


# ---------------------------------------------------------------------------
# CLI convenience entry point
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Merge monthly COSMO-REA6 NetCDF-4 files into one annual "
            "file using h5py direct chunk copy."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--input", nargs="+", required=True, metavar="FILE",
        help=(
            "Monthly NC files to merge (glob or explicit list). "
            "Files are sorted before merging."
        ),
    )
    p.add_argument(
        "--output", required=True, metavar="FILE",
        help="Destination annual NC file path.",
    )
    return p.parse_args()


def _main() -> None:
    import glob  # noqa: PLC0415
    import sys  # noqa: PLC0415

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    args = _parse_args()

    # Expand any globs (shell may not expand on Windows)
    paths: list[str] = []
    for pattern in args.input:
        expanded = sorted(glob.glob(pattern))
        paths.extend(expanded if expanded else [pattern])
    paths = sorted(paths)

    if not paths:
        sys.exit("No input files found matching the given pattern(s).")

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    logging.getLogger(__name__).info(
        "Merging %d monthly files → %s", len(paths), output,
    )
    NetCDFMerger.merge(monthly_paths=paths, output_path=output)


if __name__ == "__main__":
    _main()
