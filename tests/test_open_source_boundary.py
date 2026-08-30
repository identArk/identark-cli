"""Regression tests for the public CLI/private control-plane boundary."""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path

CLI_ROOT = Path(__file__).parents[1]
PACKAGE_ROOT = CLI_ROOT / "identark_cli"
PRIVATE_IMPORT_ROOTS = {"app", "cloud"}


def test_cli_sources_do_not_import_private_control_plane_modules() -> None:
    violations: list[str] = []
    for path in PACKAGE_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.append(node.module)
            for module in modules:
                if module.split(".", 1)[0] in PRIVATE_IMPORT_ROOTS:
                    violations.append(f"{path.relative_to(CLI_ROOT)}:{node.lineno}: {module}")

    assert not violations, (
        "CLI must use public APIs, not private control-plane imports:\n" + "\n".join(violations)
    )


def test_build_configuration_explicitly_allowlists_public_files() -> None:
    config = tomllib.loads((CLI_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    build = config["tool"]["hatch"]["build"]["targets"]

    assert build["wheel"]["packages"] == ["identark_cli"]
    assert set(build["sdist"]["include"]) == {
        "/.gitignore",
        "/identark_cli",
        "/tests",
        "/LICENSE",
        "/README.md",
        "/SECURITY.md",
        "/CONTRIBUTING.md",
        "/pyproject.toml",
    }


def test_package_metadata_points_only_to_the_public_cli_repository() -> None:
    config = tomllib.loads((CLI_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    urls = config["project"]["urls"]

    assert urls["Repository"] == "https://github.com/identark/identark-cli"
    assert urls["Issues"] == "https://github.com/identark/identark-cli/issues"
    assert all("/backend" not in url for url in urls.values())
