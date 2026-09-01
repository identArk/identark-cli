"""Regression tests for the public CLI/private control-plane boundary."""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path

CLI_ROOT = Path(__file__).parents[1]
PACKAGE_ROOT = CLI_ROOT / "identark_cli"
PRIVATE_IMPORT_ROOTS = {"app", "cloud"}
REQUIRED_PUBLIC_FILES = {
    "CHANGELOG.md",
    "CODE_OF_CONDUCT.md",
    "CONTRIBUTING.md",
    "GOVERNANCE.md",
    "LICENSE",
    "MAINTAINERS.md",
    "README.md",
    "RELEASING.md",
    "SECURITY.md",
    "SUPPORT.md",
}
REQUIRED_GITHUB_FILES = {
    ".github/CODEOWNERS",
    ".github/PULL_REQUEST_TEMPLATE.md",
    ".github/dependabot.yml",
    ".github/ISSUE_TEMPLATE/bug_report.yml",
    ".github/ISSUE_TEMPLATE/config.yml",
    ".github/ISSUE_TEMPLATE/feature_request.yml",
    ".github/workflows/ci.yml",
    ".github/workflows/codeql.yml",
    ".github/workflows/publish.yml",
}
FORBIDDEN_REPOSITORY_REFERENCES = {
    "cloud/cli",
    "github.com/identark/backend",
    "github.com/identark/cloud",
}


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
        "/CHANGELOG.md",
        "/CODE_OF_CONDUCT.md",
        "/identark_cli",
        "/tests",
        "/GOVERNANCE.md",
        "/LICENSE",
        "/MAINTAINERS.md",
        "/README.md",
        "/RELEASING.md",
        "/SECURITY.md",
        "/scripts",
        "/SUPPORT.md",
        "/CONTRIBUTING.md",
        "/pyproject.toml",
    }


def test_package_metadata_points_only_to_the_public_cli_repository() -> None:
    config = tomllib.loads((CLI_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    urls = config["project"]["urls"]

    assert urls["Repository"] == "https://github.com/identark/identark-cli"
    assert urls["Issues"] == "https://github.com/identark/identark-cli/issues"
    assert all("/backend" not in url for url in urls.values())


def test_standard_public_repository_documents_are_present() -> None:
    missing = sorted(path for path in REQUIRED_PUBLIC_FILES if not (CLI_ROOT / path).is_file())

    assert not missing, f"missing required public repository documents: {', '.join(missing)}"


def test_standard_github_contribution_and_supply_chain_files_are_present() -> None:
    missing = sorted(path for path in REQUIRED_GITHUB_FILES if not (CLI_ROOT / path).is_file())

    assert not missing, f"missing required GitHub repository files: {', '.join(missing)}"


def test_public_docs_do_not_point_contributors_at_private_repositories() -> None:
    public_docs = [
        CLI_ROOT / "README.md",
        CLI_ROOT / "CONTRIBUTING.md",
        CLI_ROOT / "RELEASING.md",
        CLI_ROOT / "SUPPORT.md",
    ]
    violations: list[str] = []
    for path in public_docs:
        text = path.read_text(encoding="utf-8").lower()
        for reference in FORBIDDEN_REPOSITORY_REFERENCES:
            if reference in text:
                violations.append(f"{path.name}: {reference}")

    assert not violations, "public files reference private repositories:\n" + "\n".join(violations)
