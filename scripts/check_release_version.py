#!/usr/bin/env python3
"""Verify that an annotated release tag matches the package version."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

VERSION_FILE = Path(__file__).parents[1] / "identark_cli" / "__init__.py"
VERSION_PATTERN = re.compile(r'^__version__\s*=\s*"(?P<version>[^"]+)"\s*$', re.MULTILINE)


def package_version() -> str:
    match = VERSION_PATTERN.search(VERSION_FILE.read_text(encoding="utf-8"))
    if match is None:
        raise ValueError(f"could not read __version__ from {VERSION_FILE}")
    return match.group("version")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tag", help="expected vX.Y.Z release tag")
    args = parser.parse_args()

    expected_tag = f"v{package_version()}"
    if args.tag != expected_tag:
        print(
            f"ERROR: tag {args.tag!r} does not match package version {expected_tag!r}",
            file=sys.stderr,
        )
        return 1

    print(f"Release tag {args.tag} matches identark-cli {package_version()}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
