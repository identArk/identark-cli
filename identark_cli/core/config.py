"""
Configuration management for IdentArk CLI
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import toml
from pydantic import BaseModel, Field

# Default config locations
CONFIG_DIR = Path.home() / ".identark"
GLOBAL_CONFIG_FILE = CONFIG_DIR / "config.toml"
PROJECT_CONFIG_FILE = ".identark" / "config.toml"


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
    """Global IdentArk configuration"""
    version: str = "1"
    
    # API settings
    api_url: str = "https://identark-cloud.fly.dev"
    
    # Auth
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
    """Load global configuration"""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    
    if not GLOBAL_CONFIG_FILE.exists():
        config = GlobalConfig()
        save_global_config(config)
        return config
    
    with open(GLOBAL_CONFIG_FILE) as f:
        data = toml.load(f)
    
    return GlobalConfig(**data)


def save_global_config(config: GlobalConfig) -> None:
    """Save global configuration"""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    
    with open(GLOBAL_CONFIG_FILE, "w") as f:
        toml.dump(config.model_dump(), f)
    
    # Secure permissions
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
