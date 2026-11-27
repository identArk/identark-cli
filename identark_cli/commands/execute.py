"""Runtime-neutral governed execution. Provider credentials never enter this client."""

from __future__ import annotations

import json
import re
import time
import uuid
from typing import Any

import httpx
import typer

from identark_cli.core.auth import get_api_client


def _emit(value: dict[str, Any], code: int) -> None:
    # JSON escapes terminal controls; never render provider text through Rich.
    typer.echo(json.dumps(value, ensure_ascii=True, separators=(",", ":")))
    raise typer.Exit(code)


def execute(
    capability: str = typer.Argument(
        ..., help="Canonical capability, e.g. source_control.issues.read"
    ),
    provider: str = typer.Option("github", "--provider"),
    resource: str | None = typer.Option(None, "--resource", help="Exact repository owner/name"),
    input_json: str = typer.Option("{}", "--input", help="JSON object of provider arguments"),
    json_output: bool = typer.Option(
        False, "--json", help="Emit structured JSON (also the default)"
    ),
    idempotency_key: str | None = typer.Option(
        None, "--idempotency-key", help="Reuse on an uncertain retry"
    ),
    wait: float = typer.Option(
        0, "--wait", min=0, max=300, help="Seconds to poll pending execution"
    ),
) -> None:
    """Request a governed action using the configured agent-bound IdentArk identity.

    Exit codes: 0 succeeded, 2 invalid input, 3 denied, 4 pending, 5 failed/unknown.
    An admin login is not an agent identity; the server enforces that binding.
    """
    del json_output
    key = idempotency_key or str(uuid.uuid4())
    try:
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{8,128}", key):
            raise ValueError
        if not re.fullmatch(r"[a-z][a-z0-9_.]{0,159}", capability) or provider not in {
            "github",
            "stripe",
            "aws",
        }:
            raise ValueError
        if len(input_json) > 32_768:
            raise ValueError
        payload = json.loads(input_json)
        if not isinstance(payload, dict):
            raise ValueError
        if resource is not None:
            if provider != "github" or (
                "repository" in payload and payload["repository"] != resource
            ):
                raise ValueError
            payload["repository"] = resource
    except (ValueError, TypeError):
        _emit({"decision": "error", "reason": "INVALID_INPUT"}, 2)
    context = {"capability": capability, "idempotency_key": key}
    try:
        with get_api_client() as client:
            # Never transmit authority over cleartext except explicit loopback development.
            if client.base_url.scheme != "https" and client.base_url.host not in {
                "127.0.0.1",
                "localhost",
                "::1",
            }:
                _emit({**context, "decision": "error", "reason": "HTTPS_REQUIRED"}, 2)
            response = client.post(
                "/v1/gateway/requests",
                json={
                    "capability_id": capability,
                    "provider": provider,
                    "payload": payload,
                    "idempotency_key": key,
                },
            )
            deadline = time.monotonic() + wait
            while True:
                if response.status_code in {401, 403}:
                    _emit({**context, "decision": "denied", "reason": "AUTHORIZATION_DENIED"}, 3)
                if response.status_code in {400, 409, 422}:
                    reason = (
                        "IDEMPOTENCY_CONFLICT" if response.status_code == 409 else "INVALID_REQUEST"
                    )
                    _emit({**context, "decision": "error", "reason": reason}, 2)
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, dict):
                    raise ValueError
                status = data.get("status")
                request_id = str(uuid.UUID(data.get("request_id") or data.get("id")))
                context["request_id"] = request_id
                if status == "succeeded":
                    output = {**context, "decision": "allowed", "status": "succeeded"}
                    if "result" in data:
                        output["result"] = data["result"]
                    if data.get("provider_reference"):
                        output["provider_reference"] = data["provider_reference"]
                    _emit(output, 0)
                if status in {"rejected", "cancelled", "timeout", "denied"}:
                    _emit({**context, "decision": "denied", "status": status}, 3)
                if status in {"failed", "reconciliation_required"}:
                    _emit(
                        {
                            **context,
                            "decision": "error",
                            "status": status,
                            "reason": "EXECUTION_FAILED",
                        },
                        5,
                    )
                if status not in {"pending_approval", "approved", "executing"}:
                    raise ValueError
                if time.monotonic() >= deadline:
                    _emit({**context, "decision": "pending", "status": status}, 4)
                time.sleep(min(1, max(0, deadline - time.monotonic())))
                response = client.get(f"/v1/gateway/executions/{request_id}")
    except typer.Exit:
        raise
    except (httpx.HTTPError, ValueError, TypeError, KeyError):
        _emit({**context, "decision": "error", "reason": "EXECUTION_UNAVAILABLE"}, 5)
    except Exception:
        # Includes local auth/keychain failures; no raw exception or response body.
        _emit({**context, "decision": "error", "reason": "CLIENT_UNAVAILABLE"}, 5)
