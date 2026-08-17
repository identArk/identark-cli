"""Regression tests for CLI token storage.

The invariant: an IdentArk auth token is never written into
~/.identark/config.toml. Until 2026-08-17 both the Firebase ID token and the
long-lived refresh token were toml.dump()'d into that file in plaintext, while
`keyring` sat in pyproject.toml unused. These tests exist so that cannot
silently come back.

Each test runs under an isolated HOME, so your real config is untouched.
"""

from __future__ import annotations

import importlib
import stat
import sys

import pytest
import toml


@pytest.fixture()
def cli_env(tmp_path, monkeypatch):
    """Re-import config/secrets with HOME pointed at a temp dir.

    Module-level paths are computed from Path.home() at import time, so the
    modules must be reloaded after HOME changes.
    """

    def _build(*, keyring_enabled: bool):
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))  # Windows
        if keyring_enabled:
            monkeypatch.delenv("IDENTARK_DISABLE_KEYRING", raising=False)
        else:
            monkeypatch.setenv("IDENTARK_DISABLE_KEYRING", "1")

        for mod in ("identark_cli.core.config", "identark_cli.core.secrets"):
            sys.modules.pop(mod, None)

        secrets = importlib.import_module("identark_cli.core.secrets")
        config = importlib.import_module("identark_cli.core.config")
        return secrets, config

    yield _build

    for mod in ("identark_cli.core.config", "identark_cli.core.secrets"):
        sys.modules.pop(mod, None)


def test_config_module_imports(cli_env):
    """PROJECT_CONFIG_FILE was `str / str`, a TypeError at import time.

    That single line took down every command that touches config.
    """
    _, config = cli_env(keyring_enabled=False)
    from pathlib import Path

    assert isinstance(config.PROJECT_CONFIG_FILE, Path)


def test_tokens_never_written_to_config_toml(cli_env, tmp_path):
    _, config = cli_env(keyring_enabled=False)

    cfg = config.GlobalConfig(
        api_url="https://api.identark.io",
        access_token="ID_TOKEN_SENTINEL",
        refresh_token="REFRESH_TOKEN_SENTINEL",
        user_email="dev@example.com",
    )
    config.save_global_config(cfg)

    raw = (tmp_path / ".identark" / "config.toml").read_text()
    assert "ID_TOKEN_SENTINEL" not in raw
    assert "REFRESH_TOKEN_SENTINEL" not in raw
    # non-secret config must still round-trip
    assert "dev@example.com" in raw


def test_tokens_round_trip(cli_env):
    _, config = cli_env(keyring_enabled=False)

    config.save_global_config(
        config.GlobalConfig(access_token="AAA", refresh_token="BBB")
    )
    loaded = config.load_global_config()

    assert loaded.access_token == "AAA"
    assert loaded.refresh_token == "BBB"
    assert loaded.is_authenticated is True


def test_fallback_file_is_0600(cli_env, tmp_path):
    _, config = cli_env(keyring_enabled=False)
    config.save_global_config(config.GlobalConfig(access_token="AAA"))

    fallback = tmp_path / ".identark" / "credentials.toml"
    assert fallback.exists()
    assert stat.S_IMODE(fallback.stat().st_mode) == 0o600


def test_legacy_plaintext_tokens_are_migrated(cli_env, tmp_path):
    """Anyone upgrading has plaintext tokens on disk right now."""
    _, config = cli_env(keyring_enabled=False)

    cfg_dir = tmp_path / ".identark"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.toml").write_text(
        toml.dumps(
            {
                "version": "1",
                "api_url": "https://api.identark.io",
                "access_token": "LEGACY_ACCESS",
                "refresh_token": "LEGACY_REFRESH",
                "auto_approve_threshold": 30,
                "color_output": True,
            }
        )
    )

    loaded = config.load_global_config()
    after = (cfg_dir / "config.toml").read_text()

    assert "LEGACY_ACCESS" not in after, "plaintext token survived the migration"
    assert "LEGACY_REFRESH" not in after
    assert loaded.access_token == "LEGACY_ACCESS"
    assert loaded.refresh_token == "LEGACY_REFRESH"


def test_clear_all_removes_every_token(cli_env, tmp_path):
    secrets, config = cli_env(keyring_enabled=False)

    config.save_global_config(
        config.GlobalConfig(access_token="TOK", refresh_token="REF")
    )
    secrets.clear_all()

    assert secrets.get_secret(secrets.ACCESS_TOKEN) is None
    assert secrets.get_secret(secrets.REFRESH_TOKEN) is None

    fallback = tmp_path / ".identark" / "credentials.toml"
    residue = fallback.read_text() if fallback.exists() else ""
    assert "TOK" not in residue and "REF" not in residue


def test_keyring_is_preferred_when_available(cli_env, tmp_path):
    secrets, config = cli_env(keyring_enabled=True)

    keyring = pytest.importorskip("keyring")

    class MemoryKeyring(keyring.backend.KeyringBackend):
        priority = 10

        def __init__(self):
            super().__init__()
            self.store = {}

        def get_password(self, service, username):
            return self.store.get((service, username))

        def set_password(self, service, username, password):
            self.store[(service, username)] = password

        def delete_password(self, service, username):
            self.store.pop((service, username), None)

    previous = keyring.get_keyring()
    mem = MemoryKeyring()
    keyring.set_keyring(mem)
    try:
        assert secrets._keyring_available() is True

        config.save_global_config(config.GlobalConfig(access_token="KEYCHAIN_TOK"))

        raw = (tmp_path / ".identark" / "config.toml").read_text()
        assert "KEYCHAIN_TOK" not in raw
        assert mem.store[("identark-cli", "access_token")] == "KEYCHAIN_TOK"
        # no plaintext fallback should be created when the keychain works
        assert not (tmp_path / ".identark" / "credentials.toml").exists()
    finally:
        keyring.set_keyring(previous)


def test_fail_backend_is_treated_as_unavailable(cli_env):
    secrets, _ = cli_env(keyring_enabled=True)

    keyring = pytest.importorskip("keyring")
    from keyring.backends import fail as fail_backend

    previous = keyring.get_keyring()
    keyring.set_keyring(fail_backend.Keyring())
    try:
        assert secrets._keyring_available() is False
    finally:
        keyring.set_keyring(previous)
