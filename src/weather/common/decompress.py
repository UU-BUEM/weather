"""Shared bzip2 decompression primitives for weather datasets."""

from __future__ import annotations

import bz2
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path


def detect_decompressor(preferred: str = "") -> str:
    """Return available decompressor command: lbzip2, pbzip2, or python."""
    if preferred and shutil.which(preferred):
        return preferred

    for cmd in ("lbzip2", "pbzip2"):
        if shutil.which(cmd):
            return cmd
    return "python"


def _decompress_external(
    src: Path,
    dest: Path,
    *,
    cmd: str,
    threads: int,
) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=dest.parent,
        prefix=f".{dest.name}.",
        suffix=".part",
    )

    if cmd == "pbzip2":
        args = [cmd, "-d", f"-p{threads}", "-c", str(src)]
    else:
        args = [cmd, "-d", "-n", str(threads), "-c", str(src)]

    try:
        with open(tmp_fd, "wb") as out_f:
            subprocess.run(
                args,
                stdout=out_f,
                stderr=subprocess.PIPE,
                check=True,
            )
        Path(tmp_path).replace(dest)
    except BaseException:
        Path(tmp_path).unlink(missing_ok=True)
        raise
    return dest


def _decompress_python(src: Path, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=dest.parent,
        prefix=f".{dest.name}.",
        suffix=".part",
    )

    try:
        with bz2.open(src, "rb") as f_in, open(tmp_fd, "wb") as f_out:
            shutil.copyfileobj(f_in, f_out, length=1 << 20)
        Path(tmp_path).replace(dest)
    except BaseException:
        Path(tmp_path).unlink(missing_ok=True)
        raise
    return dest


def decompress_bz2_file(
    src: Path,
    *,
    dest: Path,
    threads: int,
    preferred_decompressor: str = "",
    logger: logging.Logger | None = None,
) -> Path:
    """Decompress a .bz2 file to dest using best available strategy."""
    log = logger or logging.getLogger(__name__)
    if not src.exists():
        raise FileNotFoundError(f"Source file not found: {src}")
    if not src.name.endswith(".bz2"):
        raise ValueError(f"Expected a .bz2 file, got: {src.name}")

    if dest.exists() and dest.stat().st_size > 0:
        log.info("Already decompressed: %s", dest.name)
        return dest

    decompressor = detect_decompressor(preferred=preferred_decompressor)
    log.info("Decompressing %s with %s", src.name, decompressor)

    if decompressor == "python":
        return _decompress_python(src, dest)
    return _decompress_external(
        src,
        dest,
        cmd=decompressor,
        threads=threads,
    )
