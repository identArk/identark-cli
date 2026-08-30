#!/usr/bin/env python3
"""Fail closed when a CLI archive crosses the public/private release boundary."""

from __future__ import annotations

import argparse
import ast
import re
import sys
import tarfile
import zipfile
from collections.abc import Iterable
from pathlib import Path, PurePosixPath

PRIVATE_IMPORT_ROOTS = {"app", "cloud"}
FORBIDDEN_PARTS = {
    ".env",
    ".git",
    ".github",
    ".idea",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "alembic",
    "app",
    "demos",
    "infrastructure",
    "migrations",
    "node_modules",
    "operations",
}
FORBIDDEN_SUFFIXES = {
    ".crt",
    ".db",
    ".der",
    ".env",
    ".jks",
    ".key",
    ".log",
    ".p12",
    ".pem",
    ".pfx",
    ".pyc",
    ".sqlite",
}
PRIVATE_KEY_HEADER = re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")
SDIST_ROOT_FILES = {
    ".gitignore",
    "CONTRIBUTING.md",
    "LICENSE",
    "PKG-INFO",
    "README.md",
    "SECURITY.md",
    "pyproject.toml",
}
SDIST_ROOT_DIRS = {"identark_cli", "tests"}


class BoundaryViolationError(Exception):
    """A built artifact contains content outside the public CLI boundary."""


def _safe_relative_path(name: str, *, strip_sdist_root: bool) -> PurePosixPath:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts:
        raise BoundaryViolationError(f"unsafe archive path: {name}")
    parts = list(path.parts)
    if strip_sdist_root:
        if len(parts) < 2:
            raise BoundaryViolationError(f"source archive entry has no package root: {name}")
        parts = parts[1:]
    if not parts:
        raise BoundaryViolationError(f"empty archive path: {name}")
    return PurePosixPath(*parts)


def _check_path(path: PurePosixPath) -> None:
    lowered_parts = {part.lower() for part in path.parts}
    forbidden = lowered_parts & FORBIDDEN_PARTS
    if forbidden:
        raise BoundaryViolationError(f"forbidden path component {sorted(forbidden)!r}: {path}")
    if path.suffix.lower() in FORBIDDEN_SUFFIXES:
        raise BoundaryViolationError(f"forbidden file type: {path}")
    if any(part.lower().endswith(".internal.md") for part in path.parts):
        raise BoundaryViolationError(f"internal document in public artifact: {path}")


def _check_python_imports(path: PurePosixPath, data: bytes) -> None:
    if path.suffix != ".py":
        return
    try:
        tree = ast.parse(data.decode("utf-8"), filename=str(path))
    except (SyntaxError, UnicodeDecodeError) as exc:
        raise BoundaryViolationError(f"cannot parse packaged Python source {path}: {exc}") from exc

    for node in ast.walk(tree):
        modules: Iterable[str]
        if isinstance(node, ast.Import):
            modules = (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules = (node.module,)
        else:
            continue
        for module in modules:
            if module.split(".", 1)[0] in PRIVATE_IMPORT_ROOTS:
                raise BoundaryViolationError(
                    f"private control-plane import {module!r} in packaged source {path}"
                )


def _check_content(path: PurePosixPath, data: bytes) -> None:
    if PRIVATE_KEY_HEADER.search(data):
        raise BoundaryViolationError(f"private key material in public artifact: {path}")
    _check_python_imports(path, data)


def check_wheel(path: Path) -> None:
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            relative = _safe_relative_path(info.filename, strip_sdist_root=False)
            _check_path(relative)
            top = relative.parts[0]
            if top != "identark_cli" and not top.endswith(".dist-info"):
                raise BoundaryViolationError(f"wheel entry is outside the CLI package: {relative}")
            if info.is_dir():
                continue
            _check_content(relative, archive.read(info))


def check_sdist(path: Path) -> None:
    with tarfile.open(path, mode="r:gz") as archive:
        for member in archive.getmembers():
            if member.issym() or member.islnk():
                raise BoundaryViolationError(
                    f"links are not allowed in source archives: {member.name}"
                )
            relative = _safe_relative_path(member.name, strip_sdist_root=True)
            _check_path(relative)
            top = relative.parts[0]
            if top not in SDIST_ROOT_FILES and top not in SDIST_ROOT_DIRS:
                raise BoundaryViolationError(
                    f"source entry is outside the CLI allowlist: {relative}"
                )
            if not member.isfile():
                continue
            extracted = archive.extractfile(member)
            if extracted is None:
                raise BoundaryViolationError(f"could not inspect source archive member: {relative}")
            _check_content(relative, extracted.read())


def check_archive(path: Path) -> None:
    if path.suffix == ".whl":
        check_wheel(path)
    elif path.name.endswith(".tar.gz"):
        check_sdist(path)
    else:
        raise BoundaryViolationError(f"unsupported release artifact: {path}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archives", nargs="+", type=Path)
    args = parser.parse_args()

    failed = False
    for archive in args.archives:
        try:
            if not archive.is_file():
                raise BoundaryViolationError(f"artifact is not a file: {archive}")
            check_archive(archive)
        except (BoundaryViolationError, tarfile.TarError, zipfile.BadZipFile) as exc:
            failed = True
            print(f"ERROR {archive}: {exc}", file=sys.stderr)
        else:
            print(f"OK {archive}: public CLI boundary verified")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
