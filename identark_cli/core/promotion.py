"""Safe local-to-Gateway Mode promotion helpers."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from identark_cli.core import secrets as secret_store
from identark_cli.core.config import GatewayModeConfig, load_config, load_global_config, save_config

GATEWAY_SAMPLE_FILE = "identark_gateway_sample.py"


class PromotionError(Exception):
    """Raised when a project cannot be safely promoted."""


@dataclass(frozen=True)
class PromotionResult:
    agent_id: str
    session_id: str
    sample_path: Path
    expires_at: str | None


def validate_credential_ref(credential_ref: str) -> str:
    """Accept a vault pointer but never a local environment secret."""
    normalized = credential_ref.strip()
    if normalized.startswith("env://"):
        raise PromotionError("Gateway Mode requires a vault reference, not an env:// value.")
    if not normalized.startswith(("vault://", "secret/")):
        raise PromotionError("--credential-ref must be a vault:// or secret/ reference.")
    if normalized in {"vault://", "secret/"}:
        raise PromotionError("--credential-ref must identify a stored provider credential.")
    return normalized


def capability_slot(project_root: Path) -> str:
    """Return a stable keychain slot without exposing the project path."""
    digest = hashlib.sha256(str(project_root.resolve()).encode("utf-8")).hexdigest()[:24]
    return f"gateway_capability_{digest}"


def store_project_capability(project_root: Path, capability: str) -> None:
    secret_store.set_secret(capability_slot(project_root), capability)


def load_gateway_runtime(project_root: Path) -> tuple[str, GatewayModeConfig, str]:
    """Load the short-lived capability and non-secret Gateway Mode metadata."""
    config = load_config(project_root / ".identark" / "config.toml")
    if config.gateway_mode is None:
        raise PromotionError("This project is not in Gateway Mode. Run `identark promote` first.")
    capability = secret_store.get_secret(capability_slot(project_root))
    if not capability:
        raise PromotionError(
            "No active capability token is available. Run `identark promote` "
            "to mint a new short-lived token."
        )
    return capability, config.gateway_mode, load_global_config().api_url


def gateway_sample_source() -> str:
    """Return a production sample that never reads a provider credential."""
    return '''"""A governed IdentArk Gateway Mode smoke test."""
import asyncio
from pathlib import Path

from identark import ControlPlaneGateway, Message, Role
from identark_cli.core.promotion import load_gateway_runtime


async def main() -> None:
    capability, gateway_config, api_url = load_gateway_runtime(Path.cwd())
    async with ControlPlaneGateway(
        api_key=capability,
        url=api_url,
        session_id=gateway_config.session_id,
    ) as gateway:
        response = await gateway.invoke_llm([
            Message(
                role=Role.USER,
                content=(
                    "In one sentence, explain why capability tokens are safer "
                    "than provider credentials."
                ),
            )
        ])
        print(response.message.content)
        print(f"\\nGoverned call recorded for session: {gateway_config.session_id}")
        print(f"Estimated call cost: ${response.cost_usd:.6f}")
        print("Inspect the authoritative activity trail with: identark audit list")


if __name__ == "__main__":
    asyncio.run(main())
'''


def write_gateway_sample(project_root: Path, *, force: bool = False) -> Path:
    """Write a separate production sample; never overwrite the local sample."""
    sample_path = project_root / GATEWAY_SAMPLE_FILE
    if sample_path.exists() and not force:
        raise PromotionError(
            f"{GATEWAY_SAMPLE_FILE} already exists. Use --force to replace that generated file."
        )
    sample_path.write_text(gateway_sample_source(), encoding="utf-8")
    return sample_path


def promote_project(
    project_root: Path,
    *,
    credential_ref: str,
    provider: str,
    model: str,
    agent_name: str,
    key_ttl_minutes: int,
    force: bool,
    client: Any,
) -> PromotionResult:
    """Register/reuse an agent, mint a least-privilege key, and write its sample.

    The raw capability appears only in the one-time key response and is written
    directly to protected local storage. It is never persisted in config or
    returned by this function.
    """
    credential_ref = validate_credential_ref(credential_ref)
    config_path = project_root / ".identark" / "config.toml"
    config = load_config(config_path)
    existing = config.gateway_mode
    if (
        existing
        and not force
        and (
            existing.credential_ref != credential_ref
            or existing.provider != provider
            or existing.model != model
        )
    ):
        raise PromotionError(
            "Gateway Mode is already configured differently. Use --force only "
            "after reviewing the new settings."
        )

    sample_path = project_root / GATEWAY_SAMPLE_FILE
    if sample_path.exists() and not force:
        raise PromotionError(f"{GATEWAY_SAMPLE_FILE} already exists. Use --force to replace it.")

    if existing and not force:
        agent_id = existing.agent_id
    else:
        response = client.post(
            "/v1/agents",
            json={
                "name": agent_name,
                "description": "Created by identark promote; Gateway Mode capability boundary.",
                "credential_ref": credential_ref,
                "provider": provider,
                "model": model,
            },
        )
        response.raise_for_status()
        registered = response.json()
        agent_id = _required_string(registered, "id", "agent registration")

    session_response = client.post(
        "/v1/sessions",
        json={
            "agent_id": agent_id,
            "credential_ref": credential_ref,
            "provider": provider,
            "model": model,
            "cost_cap_usd": 5.0,
        },
    )
    session_response.raise_for_status()
    session = session_response.json()
    session_id = _required_string(session, "session_id", "session creation")

    key_response = client.post(
        "/v1/keys",
        json={
            "name": f"{agent_name} Gateway Mode capability"[:255],
            "scopes": ["llm:invoke"],
            "expires_in_minutes": key_ttl_minutes,
            "agent_id": agent_id,
        },
    )
    key_response.raise_for_status()
    key = key_response.json()
    capability = _required_string(key, "api_key", "capability creation")
    if not capability.startswith("csk_"):
        raise PromotionError("The control plane did not return a valid capability token.")

    try:
        store_project_capability(project_root, capability)
        write_gateway_sample(project_root, force=force)
        config.gateway_mode = GatewayModeConfig(
            agent_id=agent_id,
            session_id=session_id,
            provider=provider,
            model=model,
            credential_ref=credential_ref,
            capability_expires_at=(
                key.get("expires_at") if isinstance(key.get("expires_at"), str) else None
            ),
        )
        save_config(config, config_path)
    except Exception as exc:
        # Do not include response bodies: a failure must never risk emitting the raw key.
        raise PromotionError(
            "Promotion could not finish writing local Gateway Mode configuration."
        ) from exc

    return PromotionResult(
        agent_id=agent_id,
        session_id=session_id,
        sample_path=sample_path,
        expires_at=config.gateway_mode.capability_expires_at,
    )


def _required_string(payload: Any, field: str, step: str) -> str:
    value = payload.get(field) if isinstance(payload, dict) else None
    if not isinstance(value, str) or not value:
        raise PromotionError(f"The control plane returned an invalid response during {step}.")
    return value
