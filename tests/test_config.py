"""Configuration and initialization safety regression tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from identark_cli.core.config import (
    CredentialRef,
    GlobalConfig,
    ProjectConfig,
    load_config,
    save_config,
)
from identark_cli.core.init import initialize_project
from identark_cli.core.scanner import HookInstallError, install_git_hook
from pydantic import ValidationError


@pytest.mark.parametrize(
    "name,ref",
    [
        ("not-valid!", "vault://prod/key"),
        ("VALID_NAME", "plaintext-secret"),
        ("VALID_NAME", "vault://"),
        ("VALID_NAME", "env://not-valid!"),
    ],
)
def test_credential_references_reject_unsafe_shapes(name: str, ref: str) -> None:
    with pytest.raises(ValidationError):
        CredentialRef(name=name, ref=ref)


def test_save_config_from_subdirectory_updates_project_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "project"
    nested = root / "src" / "nested"
    nested.mkdir(parents=True)
    original = ProjectConfig(project_name="before")
    save_config(original, root / ".identark" / "config.toml")

    monkeypatch.chdir(nested)
    original.project_name = "after"
    save_config(original)

    assert load_config(root / ".identark" / "config.toml").project_name == "after"
    assert not (nested / ".identark" / "config.toml").exists()


def test_global_api_url_requires_https_except_localhost() -> None:
    assert GlobalConfig(api_url="https://api.identark.io/").api_url == "https://api.identark.io"
    assert GlobalConfig(api_url="http://localhost:8000/").api_url == "http://localhost:8000"
    with pytest.raises(ValidationError):
        GlobalConfig(api_url="http://api.identark.io")


def test_init_does_not_install_or_overwrite_git_hook(tmp_path: Path) -> None:
    project = tmp_path / "project"
    hooks = project / ".git" / "hooks"
    hooks.mkdir(parents=True)
    existing = hooks / "pre-commit"
    existing.write_text("#!/bin/sh\necho existing\n", encoding="utf-8")

    initialize_project(str(project))

    assert existing.read_text(encoding="utf-8") == "#!/bin/sh\necho existing\n"
    assert load_config(project / ".identark" / "config.toml").enable_git_hooks is False


def test_hook_install_refuses_to_overwrite_existing_hook(tmp_path: Path) -> None:
    hooks = tmp_path / ".git" / "hooks"
    hooks.mkdir(parents=True)
    existing = hooks / "pre-commit"
    existing.write_text("#!/bin/sh\necho existing\n", encoding="utf-8")

    with pytest.raises(HookInstallError, match="already exists"):
        install_git_hook(tmp_path)

    assert "existing" in existing.read_text(encoding="utf-8")


def test_installed_hook_fails_closed_if_cli_is_missing(tmp_path: Path) -> None:
    (tmp_path / ".git" / "hooks").mkdir(parents=True)

    install_git_hook(tmp_path)

    hook = (tmp_path / ".git" / "hooks" / "pre-commit").read_text(encoding="utf-8")
    assert "if ! command -v identark" in hook
    assert "Commit blocked" in hook
    assert "--fix" not in hook
