"""
Configuration management for IdentArk CLI
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import toml
from pydantic import BaseModel, Field

from identark_cli.core import secrets as secret_store

# Default config locations
CONFIG_DIR = Path.home() / ".identark"
GLOBAL_CONFIG_FILE = CONFIG_DIR / "config.toml"
# NB: must be a Path. `".identark" / "config.toml"` is str/str and raises
# TypeError at import time, which took the whole CLI down.
PROJECT_CONFIG_FILE = Path(".identark") / "config.toml"

# Fields that are credentials, not configuration. These never touch
# config.toml; they live in the OS keychain (see core/secrets.py).
_SECRET_FIELDS = (secret_store.ACCESS_TOKEN, secret_store.REFRESH_TOKEN)


class CredentialRef(BaseModel):
    """Reference to a credential in IdentArk vault"""

    name: str
    ref: str  # vault://prod/openai, env://OPENAI_API_KEY, etc.
    required: bool = True
    description: Optional[str] = None


class ProjectConfig(BaseModel):
    """Project-level IdentArk configuration"""

    version: str = "1"
    project_name: Optional[str] = None
    organization_id: Optional[str] = None

    # Credential references
    credentials: list[CredentialRef] = Field(default_factory=list)

    # Agent settings
    default_agent_template: Optional[str] = None

    # Security settings
    enable_git_hooks: bool = True
    scan_on_commit: bool = True

    # MCP settings
    mcp_servers: list[dict] = Field(default_factory=list)


class GlobalConfig(BaseModel):
    """Global IdentArk configuration.

    `access_token` and `refresh_token` are held in memory here for convenience,
    but they are persisted to the OS keychain - never to config.toml. See
    core/secrets.py.
    """

    version: str = "1"

    # API settings
    api_url: str = "https://api.identark.io"

    # Auth - persisted via the secret store, not this file
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    user_email: Optional[str] = None
    user_id: Optional[str] = None

    # Preferences
    default_org_id: Optional[str] = None
    auto_approve_threshold: int = 30  # Auto-approve below this risk score

    # UI
    color_output: bool = True

    @property
    def is_authenticated(self) -> bool:
        return self.access_token is not None


def get_project_root(path: Optional[Path] = None) -> Optional[Path]:
    """Find the project root by looking for .identark/config.toml"""
    if path is None:
        path = Path.cwd()

    # Search up the directory tree
    current = path.resolve()
    while current != current.parent:
        config_file = current / PROJECT_CONFIG_FILE
        if config_file.exists():
            return current
        current = current.parent

    return None


def load_config(path: Optional[Path] = None) -> ProjectConfig:
    """Load project configuration"""
    if path is None:
        root = get_project_root()
        if root is None:
            raise ConfigError("No IdentArk project found. Run 'identark init' first.")
        path = root / PROJECT_CONFIG_FILE
    else:
        path = Path(path)

    if not path.exists():
        raise ConfigError(f"Configuration not found: {path}")

    with open(path) as f:
        data = toml.load(f)

    return ProjectConfig(**data)


def save_config(config: ProjectConfig, path: Optional[Path] = None) -> None:
    """Save project configuration"""
    if path is None:
        path = Path(PROJECT_CONFIG_FILE)

    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w") as f:
        toml.dump(config.model_dump(), f)


def load_global_config() -> GlobalConfig:
    """Load global configuration.

    Tokens are read from the OS keychain. If a legacy config.toml still carries
    plaintext tokens (CLI <= 0.1.0), they are migrated into the keychain and
    stripped from the file on this read.
    """
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    if not GLOBAL_CONFIG_FILE.exists():
        config = GlobalConfig()
        save_global_config(config)
        return config

    with open(GLOBAL_CONFIG_FILE) as f:
        data = toml.load(f)

    # Upgrade path: pull any plaintext tokens out of config.toml.
    migrated = secret_store.migrate_plaintext_tokens(data)

    config = GlobalConfig(**data)

    # Authoritative source for tokens is the secret store.
    config.access_token = secret_store.get_secret(secret_store.ACCESS_TOKEN)
    config.refresh_token = secret_store.get_secret(secret_store.REFRESH_TOKEN)

    if migrated:
        # Rewrite now so the plaintext copy does not survive this run.
        save_global_config(config)

    return config


def save_global_config(config: GlobalConfig) -> None:
    """Save global configuration.

    Tokens are routed to the secret store; everything else goes to config.toml.
    """
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    data = config.model_dump()

    # Route credentials to the keychain and keep them out of the file entirely.
    for field in _SECRET_FIELDS:
        secret_store.set_secret(field, data.pop(field, None))

    with open(GLOBAL_CONFIG_FILE, "w") as f:
        toml.dump(data, f)

    # Secure permissions (config.toml still carries email / org id)
    os.chmod(GLOBAL_CONFIG_FILE, 0o600)


class ConfigError(Exception):
    """Configuration error"""

    pass


# Backwards compatibility with older config formats
def migrate_config(data: dict) -> dict:
    """Migrate old config formats to current version"""
    version = data.get("version", "1")

    if version == "1":
        # Current version, no migration needed
        return data

    # Future migrations go here
    return data
