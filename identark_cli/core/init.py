"""
Project initialization for IdentArk CLI
"""

from __future__ import annotations

from pathlib import Path

from identark_cli.core.config import ProjectConfig, save_config
from identark_cli.core.scanner import install_git_hook


def initialize_project(path: str, force: bool = False) -> None:
    """
    Initialize a new IdentArk project
    
    Args:
        path: Project path
        force: Overwrite existing configuration
    """
    project_path = Path(path).resolve()
    config_dir = project_path / ".identark"
    config_file = config_dir / "config.toml"
    
    # Check if already initialized
    if config_file.exists() and not force:
        raise ConfigExistsError(f"Project already initialized at {project_path}")
    
    # Create config directory
    config_dir.mkdir(parents=True, exist_ok=True)
    
    # Create default configuration
    config = ProjectConfig(
        project_name=project_path.name,
        enable_git_hooks=True,
        scan_on_commit=True
    )
    
    save_config(config, config_file)
    
    # Install git hook if in a git repo
    if (project_path / ".git").exists():
        install_git_hook(project_path)
    
    # Create .gitignore entry
    _update_gitignore(project_path)
    
    # Create sample .env.example
    _create_env_example(project_path)


def _update_gitignore(project_path: Path) -> None:
    """Add .identark/ to .gitignore"""
    gitignore = project_path / ".gitignore"
    entry = "# IdentArk credential isolation\n.identark/credentials\n"
    
    if gitignore.exists():
        content = gitignore.read_text()
        if ".identark/" not in content:
            with open(gitignore, "a") as f:
                f.write("\n" + entry)
    else:
        gitignore.write_text(entry)


def _create_env_example(project_path: Path) -> None:
    """Create .env.example file"""
    env_example = project_path / ".env.example"
    
    if env_example.exists():
        return
    
    content = """# IdentArk Environment Variables
# These are injected by 'identark agent run' - DO NOT add real values here
# Add credentials to IdentArk vault: identark credential add <name> --ref vault://...

# Example credentials (replace with your own via IdentArk CLI)
# OPENAI_API_KEY=
# SLACK_TOKEN=
# DATABASE_URL=
"""
    
    env_example.write_text(content)


class ConfigExistsError(Exception):
    """Configuration already exists"""
    pass
