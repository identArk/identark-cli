"""
Project initialization for IdentArk CLI
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from identark_cli.core.config import CredentialRef, ProjectConfig, save_config


class FirstRunProvider(StrEnum):
    """Providers supported by the generated first-run sample."""

    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    OLLAMA = "ollama"


@dataclass(frozen=True)
class ProviderSetup:
    credential_name: str | None
    model: str
    install_command: str


PROVIDER_SETUPS: dict[FirstRunProvider, ProviderSetup] = {
    FirstRunProvider.OPENAI: ProviderSetup(
        "OPENAI_API_KEY", "gpt-4o-mini", 'pip install "identark[openai]"'
    ),
    FirstRunProvider.ANTHROPIC: ProviderSetup(
        "ANTHROPIC_API_KEY", "claude-3-5-haiku-latest", 'pip install "identark[anthropic]"'
    ),
    FirstRunProvider.OLLAMA: ProviderSetup(None, "llama3.2", 'pip install "identark[openai]"'),
}


def initialize_project(
    path: str,
    force: bool = False,
    provider: FirstRunProvider | None = None,
) -> ProviderSetup | None:
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
        project_name=project_path.name, enable_git_hooks=False, scan_on_commit=True
    )
    setup = PROVIDER_SETUPS[provider] if provider else None
    if setup and setup.credential_name:
        assert provider is not None
        config.credentials.append(
            CredentialRef(
                name=setup.credential_name,
                ref=f"env://{setup.credential_name}",
                description=f"Local {provider.value} development only",
            )
        )

    save_config(config, config_file)

    # Create .gitignore entry
    _update_gitignore(project_path)

    # Create sample .env.example
    _create_env_example(project_path)
    if provider and setup:
        _create_first_run_sample(project_path, provider, setup)
    return setup


def _update_gitignore(project_path: Path) -> None:
    """Add .identark/ to .gitignore"""
    gitignore = project_path / ".gitignore"
    entry = (
        "# IdentArk local credentials and local activity records\n"
        ".identark/credentials\n"
        ".identark/activity.jsonl\n"
    )

    if gitignore.exists():
        content = gitignore.read_text(encoding="utf-8")
        if ".identark/" not in content:
            with open(gitignore, "a", encoding="utf-8") as f:
                f.write("\n" + entry)
    else:
        gitignore.write_text(entry, encoding="utf-8")


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

    env_example.write_text(content, encoding="utf-8")


def _create_first_run_sample(
    project_path: Path, provider: FirstRunProvider, setup: ProviderSetup
) -> None:
    """Create a real, local provider call with a privacy-preserving receipt."""
    credential_check = ""
    if setup.credential_name:
        credential_check = (
            f'if not os.environ.get("{setup.credential_name}"):\n'
            "        raise RuntimeError(\n"
            '            "Set the selected provider key in your shell before running."\n'
            "        )"
        )
    if provider == FirstRunProvider.ANTHROPIC:
        client_import = "from anthropic import AsyncAnthropic"
        client_setup = "client = AsyncAnthropic()"
    elif provider == FirstRunProvider.OLLAMA:
        client_import = "from openai import AsyncOpenAI"
        client_setup = (
            'client = AsyncOpenAI(base_url="http://localhost:11434/v1", api_key="ollama")'
        )
    else:
        client_import = "from openai import AsyncOpenAI"
        client_setup = "client = AsyncOpenAI()"

    sample = f'''"""A real local IdentArk first run.

Never use this DirectGateway pattern in production.
"""
import asyncio
import os
from pathlib import Path

{client_import}
from identark import DirectGateway, Message, Role
from identark_cli.core.activity import record_local_activity

PROVIDER = "{provider.value}"
MODEL = "{setup.model}"


async def main() -> None:
    {credential_check}
    {client_setup}
    gateway = DirectGateway(llm_client=client, model=MODEL, provider=PROVIDER)
    try:
        response = await gateway.invoke_llm([
            Message(
                role=Role.USER,
                content=(
                    "In one sentence, explain why agents should receive "
                    "capabilities instead of credentials."
                ),
            )
        ])
    except Exception as exc:
        record_local_activity(
            Path.cwd(), provider=PROVIDER, model=MODEL,
            success=False, error_type=type(exc).__name__,
        )
        raise

    record_local_activity(
        Path.cwd(), provider=PROVIDER, model=MODEL,
        success=True, cost_usd=response.cost_usd,
    )
    print(response.message.content)
    print(
        f"\\nLocal activity record: .identark/activity.jsonl | "
        f"estimated cost: ${{response.cost_usd:.6f}}"
    )
    print(
        "This was a local DirectGateway run. For the governed audit trail, "
        "move this agent to Gateway Mode."
    )


if __name__ == "__main__":
    asyncio.run(main())
'''
    (project_path / "identark_sample.py").write_text(sample, encoding="utf-8")


class ConfigExistsError(Exception):
    """Configuration already exists"""

    pass
