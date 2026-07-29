"""Shared argparse flag declarations for the provider test/CLI runners.

Every ``test_<provider>_{one_month,one_year,multi_year}.py`` script re-declared
the same handful of flags (``--cleanup``, ``--resume``, ``--skip-download``,
``--skip-decompress``) by hand, each wiring its own provider's
``EnvSettings.<provider>_cleanup()`` into ``argparse`` independently. That let
COSMO drift onto a different, negative-polarity ``--no-cleanup`` flag while
ERA5-Land/MERRA-2 kept the positive ``--cleanup`` -- these helpers are the one
place that wiring happens now, so every runner stays consistent by construction.
A flag passed on the command line always wins over the *default* value passed
in here (inherent to ``argparse``'s ``store_true`` + ``default=`` behaviour) --
the config/env default only applies when the flag is omitted.
"""

from __future__ import annotations

import argparse


def add_cleanup_flag(parser: argparse.ArgumentParser, *, default: bool) -> None:
    """Add ``--cleanup`` (store_true), pre-set from *default*.

    Parameters
    ----------
    default : bool
        The provider's own ``EnvSettings.<provider>_cleanup()`` value --
        the caller resolves which provider, this just wires it up.
    """
    parser.add_argument(
        "--cleanup", action="store_true", default=default,
        help=(
            "Delete downloaded/decompressed intermediates after a successful "
            "export (default: keep everything, unless the provider's "
            "*_CLEANUP env var is set)."
        ),
    )


def add_resume_flag(parser: argparse.ArgumentParser) -> None:
    """Add ``--resume`` (store_true, default False): skip already-complete output."""
    parser.add_argument(
        "--resume", action="store_true",
        help="Skip periods whose output file(s) already exist.",
    )


def add_skip_download_flag(parser: argparse.ArgumentParser) -> None:
    """Add ``--skip-download`` (store_true, default False)."""
    parser.add_argument(
        "--skip-download", action="store_true",
        help="Assume source file(s) are already downloaded.",
    )


def add_skip_decompress_flag(parser: argparse.ArgumentParser) -> None:
    """Add ``--skip-decompress`` (store_true, default False). COSMO-REA6 only."""
    parser.add_argument(
        "--skip-decompress", action="store_true",
        help="Assume decompressed GRIB file(s) already exist.",
    )
