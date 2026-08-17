"""
Secret storage for the IdentArk CLI.

Auth tokens are credentials. They belong in the OS keychain, not in a config
file — a CLI that ships credential isolation should not be the thing on the box
leaking a long-lived refresh token to anything that can read $HOME.

Resolution order:

1. OS keychain via `keyring` (macOS Keychain, Windows Credential Locker,
   Secret Service / kwallet on Linux). Preferred, and the default everywhere a
   backend is available.
2. File fallback at ~/.identark/credentials.toml, 0600, used only when no
   keychain backend exists (headless Linux, containers, CI). This is a real
   downgrade, so it warns once per process.

Nothing here ever writes a token into ~/.identark/config.toml, which is user
config and is routinely pasted into issue reports.
"""

from __future__ import annotations

import os
import stat
import warnings
from pathlib import Path
from typing import Final, Optional

import toml

KEYRING_SERVICE: Final[str] = "identark-cli"

CONFIG_DIR: Final[Path] = Path.home() / ".identark"
FALLBACK_FILE: Final[Path] = CONFIG_DIR / "credentials.toml"

# Keys we manage. Explicit so a typo cannot silently create a new slot.
ACCESS_TOKEN: Final[str] = "access_token"
REFRESH_TOKEN: Final[str] = "refresh_token"
_MANAGED_KEYS: Final[tuple] = (ACCESS_TOKEN, REFRESH_TOKEN)

_warned_about_fallback = False


class SecretStoreError(Exception):
    """Raised when a secret cannot be persisted at all."""


def _keyring_available() -> bool:
    """True if a real keyring backend is usable.

    `keyring` always imports; the failure mode is a null/fail backend that
    raises only when used. So probe the backend, not the import.
    """
    if os.environ.get("IDENTARK_DISABLE_KEYRING"):
        return False
    try:
        import keyring
        from keyring.backends import fail as _fail

        backend = keyring.get_keyring()
        if isinstance(backend, _fail.Keyring):
            return False
        if getattr(backend, "priority", 1) <= 0:
            return False
        return True
    except Exception:
        return False


def _warn_fallback_once() -> None:
    global _warned_about_fallback
    if _warned_about_fallback:
        return
    _warned_about_fallback = True
    warnings.warn(
        "No OS keychain backend available - storing IdentArk tokens in "
        f"{FALLBACK_FILE} with 0600 permissions instead. Any process running as "
        "this user can read them. Install a keyring backend, or prefer "
        "IDENTARK_API_KEY / IDENTARK_SESSION_TOKEN in CI.",
        RuntimeWarning,
        stacklevel=3,
    )


def _read_fallback() -> dict:
    if not FALLBACK_FILE.exists():
        return {}
    try:
        with open(FALLBACK_FILE) as fh:
            return toml.load(fh)
    except Exception:
        return {}


def _write_fallback(data: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    # Create with 0600 from the start - do not widen-then-narrow, which leaves
    # a window where the token is readable.
    fd = os.open(
        FALLBACK_FILE,
        os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
        stat.S_IRUSR | stat.S_IWUSR,
    )
    try:
        with os.fdopen(fd, "w") as fh:
            toml.dump(data, fh)
    finally:
        try:
            os.chmod(FALLBACK_FILE, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass


def set_secret(key: str, value: Optional[str]) -> None:
    """Store (or clear, when value is None) a secret."""
    if value is None:
        delete_secret(key)
        return

    if _keyring_available():
        try:
            import keyring

            keyring.set_password(KEYRING_SERVICE, key, value)
            # Drop any stale plaintext copy left by an older CLI.
            data = _read_fallback()
            if key in data:
                data.pop(key, None)
                _write_fallback(data)
            return
        except Exception:
            pass  # fall through to file

    _warn_fallback_once()
    data = _read_fallback()
    data[key] = value
    try:
        _write_fallback(data)
    except OSError as exc:
        raise SecretStoreError(f"Could not persist {key}: {exc}") from exc


def get_secret(key: str) -> Optional[str]:
    """Retrieve a secret, or None."""
    if _keyring_available():
        try:
            import keyring

            value = keyring.get_password(KEYRING_SERVICE, key)
            if value:
                return value
        except Exception:
            pass

    return _read_fallback().get(key)


def delete_secret(key: str) -> None:
    """Remove a secret from every backend it might be in."""
    if _keyring_available():
        try:
            import keyring

            keyring.delete_password(KEYRING_SERVICE, key)
        except Exception:
            pass  # not present is fine

    data = _read_fallback()
    if key in data:
        data.pop(key, None)
        _write_fallback(data)


def clear_all() -> None:
    """Clear every token the CLI manages. Used by `identark auth logout`."""
    for key in _MANAGED_KEYS:
        delete_secret(key)


def migrate_plaintext_tokens(config_data: dict) -> bool:
    """Move tokens found in a legacy config.toml into secure storage.

    CLI <= 0.1.0 wrote access_token and refresh_token straight into
    ~/.identark/config.toml. Anyone upgrading has one on disk right now, so
    move it rather than ignore it, and mutate the caller's dict so the next
    write drops the plaintext copy.

    Returns True if anything was migrated.
    """
    migrated = False
    for key in _MANAGED_KEYS:
        value = config_data.get(key)
        if value:
            try:
                set_secret(key, value)
            except SecretStoreError:
                continue
            config_data[key] = None
            migrated = True
    return migrated


def storage_backend_name() -> str:
    """Human-readable description of where tokens go. For `identark status`."""
    if _keyring_available():
        try:
            import keyring

            return f"OS keychain ({type(keyring.get_keyring()).__name__})"
        except Exception:
            pass
    return f"file fallback ({FALLBACK_FILE}, 0600)"
