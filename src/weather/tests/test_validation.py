"""Test suite for validation and cleanup utilities."""

from __future__ import annotations

import tempfile
from pathlib import Path

from weather.common import cleanup, validate


class TestValidation:
    """Test validate module."""

    def test_validate_file_integrity_missing(self):
        """Test detection of missing file."""
        result, msg = validate.validate_file_integrity(Path("/nonexistent"))
        assert not result
        assert "not found" in msg.lower()

    def test_validate_file_integrity_empty(self):
        """Test detection of empty file."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            empty_path = Path(f.name)

        try:
            result, msg = validate.validate_file_integrity(empty_path)
            assert not result
            assert "empty" in msg.lower()
        finally:
            empty_path.unlink()

    def test_validate_file_integrity_size(self):
        """Test file size validation."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"test content")
            fp = Path(f.name)

        try:
            # Correct size
            result, msg = validate.validate_file_integrity(
                fp,
                expected_size=12,
            )
            assert result and "OK" in msg

            # Incorrect size
            result, msg = validate.validate_file_integrity(
                fp,
                expected_size=999,
            )
            assert not result
            assert "mismatch" in msg.lower()
        finally:
            fp.unlink()

    def test_compute_file_hash(self):
        """Test hash computation."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"test data")
            fp = Path(f.name)

        try:
            h = validate.compute_file_hash(fp, algo="sha256")
            assert len(h) == 64  # SHA256 hex is 64 chars
            assert isinstance(h, str)
        finally:
            fp.unlink()

    def test_detect_corrupt_files(self):
        """Test corrupt file detection."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            # Create small (corrupt) file
            small_file = tmpdir_path / "small.grb"
            small_file.write_bytes(b"x" * 100)

            # Create normal file
            normal_file = tmpdir_path / "normal.grb"
            normal_file.write_bytes(b"x" * 10000)

            corrupt = validate.detect_corrupt_files(
                tmpdir_path,
                pattern="*.grb",
                min_size=1024,
            )
            assert small_file in corrupt
            assert normal_file not in corrupt


class TestCleanup:
    """Test cleanup module."""

    def test_cleanup_directory(self):
        """Test file cleanup."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            # Create files
            (tmpdir_path / "file1.grb").write_text("test")
            (tmpdir_path / "file2.grb").write_text("test")
            (tmpdir_path / "keep.txt").write_text("keep")

            # Dry run
            count = validate.cleanup_directory(
                tmpdir_path,
                pattern="*.grb",
                dry_run=True,
            )
            assert count == 2
            assert (tmpdir_path / "file1.grb").exists()

            # Actually cleanup
            count = validate.cleanup_directory(
                tmpdir_path,
                pattern="*.grb",
                dry_run=False,
            )
            assert count == 2
            assert not (tmpdir_path / "file1.grb").exists()
            assert (tmpdir_path / "keep.txt").exists()

    def test_detect_and_remove_corrupt(self):
        """Test corrupt file removal."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            # Create corrupt file
            corrupt_file = tmpdir_path / "corrupt.grb.bz2"
            corrupt_file.write_bytes(b"x" * 100)

            # Create normal file
            normal_file = tmpdir_path / "normal.grb.bz2"
            normal_file.write_bytes(b"x" * 10000)

            # Detect and remove
            corrupt = cleanup.detect_and_remove_corrupt_files(
                tmpdir_path,
                pattern="*.grb.bz2",
                min_size=1024,
                remove=True,
            )
            assert len(corrupt) == 1
            assert corrupt_file not in corrupt_file.parent.iterdir()
            assert normal_file.exists()
