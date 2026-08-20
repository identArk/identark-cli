"""Public CLI surface and command behavior regression tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from identark_cli.commands import agent, approvals, credential, mcp
from identark_cli.commands.approvals import _redact_sensitive
from identark_cli.core.config import CredentialRef, ProjectConfig, load_config, save_config
from identark_cli.main import app
from typer.testing import CliRunner

runner = CliRunner()


class FakeResponse:
    def __init__(self, payload: Any, status_code: int = 200):
        self.payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def json(self) -> Any:
        return self.payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeClient:
    def __init__(self, responses: list[FakeResponse]):
        self.responses = iter(responses)
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def __enter__(self) -> FakeClient:
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    def _call(self, method: str, path: str, **kwargs: Any) -> FakeResponse:
        self.calls.append((method, path, kwargs))
        return next(self.responses)

    def get(self, path: str, **kwargs: Any) -> FakeResponse:
        return self._call("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> FakeResponse:
        return self._call("POST", path, **kwargs)

    def delete(self, path: str, **kwargs: Any) -> FakeResponse:
        return self._call("DELETE", path, **kwargs)


@pytest.mark.parametrize(
    "arguments,missing",
    [
        (["agent", "--help"], ("logs", "inspect")),
        (["mcp", "server", "--help"], ("discover",)),
        (["mcp", "server", "add", "--help"], ("--auth-type", "--token", "--api-key")),
        (["credential", "scan", "--help"], ("--fix",)),
        (["credential", "inject", "--help"], ("--env-file",)),
        (["approvals", "list", "--help"], ("--status",)),
        (["approvals", "watch", "--help"], ("--auto-approve",)),
    ],
)
def test_unimplemented_or_unsafe_options_are_not_advertised(
    arguments: list[str], missing: tuple[str, ...]
) -> None:
    result = runner.invoke(app, arguments)
    assert result.exit_code == 0, result.output
    for value in missing:
        assert value not in result.output


def test_agent_init_output_runs_from_generated_src_entrypoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = runner.invoke(app, ["agent", "init", "--name", "demo", "--path", str(tmp_path)])
    assert created.exit_code == 0, created.output
    project = tmp_path / "demo"
    assert (project / "src" / "main.py").exists()

    monkeypatch.chdir(project)
    executed = runner.invoke(app, ["agent", "run"])

    assert executed.exit_code == 0, executed.output
    assert "credential injection" in executed.output


def test_agent_run_rejects_missing_explicit_entrypoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    initialized = runner.invoke(app, ["init", "--path", str(tmp_path)])
    assert initialized.exit_code == 0, initialized.output
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["agent", "run", "missing.py"])

    assert result.exit_code == 1
    assert "Entry point not found" in result.output


def test_credential_add_rejects_ref_and_env_together(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    initialized = runner.invoke(app, ["init", "--path", str(tmp_path)])
    assert initialized.exit_code == 0, initialized.output
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(
        app,
        ["credential", "add", "API_KEY", "--ref", "vault://prod/key", "--env"],
    )

    assert result.exit_code == 2
    assert "exactly one" in result.output


def test_config_get_does_not_expose_token_fields() -> None:
    result = runner.invoke(app, ["config", "get", "--global", "access_token"])

    assert result.exit_code == 2
    assert "protected" in result.output


def test_mcp_add_rejects_non_https_endpoint_before_network() -> None:
    result = runner.invoke(
        app,
        [
            "mcp",
            "server",
            "add",
            "--name",
            "unsafe",
            "--endpoint",
            "http://example.com/mcp",
            "--transport",
            "streamable_http",
        ],
    )

    assert result.exit_code == 2
    assert "must use an absolute HTTPS URL" in result.output


def test_approval_argument_redaction_is_recursive() -> None:
    arguments: dict[str, Any] = {
        "query": "select 1",
        "nested": {"password": "do-not-print", "safe": [1, {"api_key": "hidden"}]},
    }

    redacted = _redact_sensitive(arguments)

    assert redacted["query"] == "select 1"
    assert redacted["nested"]["password"] == "*** REDACTED ***"
    assert redacted["nested"]["safe"][1]["api_key"] == "*** REDACTED ***"


def test_agent_register_uses_live_api_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeClient(
        [FakeResponse({"id": "agent-id", "name": "demo", "agent_key": "agent_12345678"})]
    )
    monkeypatch.setattr(agent, "get_api_client", lambda: client)

    result = runner.invoke(
        app,
        [
            "agent",
            "register",
            "--name",
            "demo",
            "--credential-ref",
            "vault://prod/anthropic",
            "--provider",
            "anthropic",
            "--model",
            "claude-sonnet-4-5",
        ],
    )

    assert result.exit_code == 0, result.output
    method, path, kwargs = client.calls[0]
    assert (method, path) == ("POST", "/v1/agents")
    assert kwargs["json"]["credential_ref"] == "vault://prod/anthropic"
    assert kwargs["json"]["provider"] == "anthropic"


def test_mcp_add_never_sends_auth_values(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeClient([FakeResponse({"id": "server-id"})])
    monkeypatch.setattr(mcp, "get_api_client", lambda: client)

    result = runner.invoke(
        app,
        [
            "mcp",
            "server",
            "add",
            "--name",
            "public-mcp",
            "--endpoint",
            "https://mcp.example.com/rpc",
            "--transport",
            "streamable_http",
        ],
    )

    assert result.exit_code == 0, result.output
    assert client.calls[0][2]["json"]["auth_config"] == {}


def test_approval_inspect_redacts_secrets_from_output(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeClient(
        [
            FakeResponse(
                {
                    "id": "approval-id",
                    "tool_name": "query",
                    "status": "pending",
                    "risk_score": 80,
                    "risk_level": "high",
                    "tool_arguments": {"password": "never-print-this", "query": "select 1"},
                }
            )
        ]
    )
    monkeypatch.setattr(approvals, "get_api_client", lambda: client)

    result = runner.invoke(app, ["approvals", "inspect", "approval-id"])

    assert result.exit_code == 0, result.output
    assert "never-print-this" not in result.output
    assert "REDACTED" in result.output
    assert "select 1" in result.output


def test_structured_credential_cannot_be_injected_as_environment_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeClient([FakeResponse({"fields": {"host": "db", "password": "hidden"}})])
    monkeypatch.setattr(credential, "get_api_client", lambda: client)

    with pytest.raises(ValueError, match="managed connector"):
        credential._fetch_credential_value("vault://prod/neon")

    assert client.calls[0][2]["params"] == {"path": "prod/neon"}


def test_agent_list_and_delete_use_registered_agent_endpoints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeClient(
        [
            FakeResponse(
                [
                    {
                        "id": "agent-id",
                        "name": "demo",
                        "agent_key": "agent_12345678",
                        "provider": "anthropic",
                        "model": "claude-sonnet-4-5",
                        "is_active": True,
                    }
                ]
            ),
            FakeResponse({}, status_code=204),
        ]
    )
    monkeypatch.setattr(agent, "get_api_client", lambda: client)

    listed = runner.invoke(app, ["agent", "list"])
    deleted = runner.invoke(app, ["agent", "delete", "agent-id", "--force"])

    assert listed.exit_code == 0, listed.output
    assert "demo" in listed.output
    assert deleted.exit_code == 0, deleted.output
    assert client.calls[0][:2] == ("GET", "/v1/agents")
    assert client.calls[1][:2] == ("DELETE", "/v1/agents/agent-id")


def test_approvals_list_limits_locally_and_approve_posts_decision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pending = [
        {
            "id": "first-approval-id",
            "tool_name": "read",
            "risk_score": 20,
            "requested_by": "agent-a",
            "created_at": "2026-08-20T12:00:00Z",
        },
        {
            "id": "second-approval-id",
            "tool_name": "write",
            "risk_score": 40,
            "requested_by": "agent-b",
            "created_at": "2026-08-20T12:00:00Z",
        },
    ]
    client = FakeClient(
        [
            FakeResponse(pending),
            FakeResponse({"id": "first-approval-id", "risk_score": 20, "tool_name": "read"}),
            FakeResponse({"decision": "approved"}),
        ]
    )
    monkeypatch.setattr(approvals, "get_api_client", lambda: client)

    listed = runner.invoke(app, ["approvals", "list", "--limit", "1"])
    approved = runner.invoke(app, ["approvals", "approve", "first-approval-id"])

    assert listed.exit_code == 0, listed.output
    assert "first-ap" in listed.output
    assert "second-a" not in listed.output
    assert approved.exit_code == 0, approved.output
    assert client.calls[-1][2]["json"]["decision"] == "approved"


def test_credential_list_and_remove_round_trip_project_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / ".identark" / "config.toml"
    save_config(
        ProjectConfig(
            project_name="demo",
            credentials=[CredentialRef(name="API_KEY", ref="vault://prod/key")],
        ),
        config_path,
    )
    monkeypatch.chdir(tmp_path)

    listed = runner.invoke(app, ["credential", "list"])
    removed = runner.invoke(app, ["credential", "remove", "API_KEY", "--force"])

    assert listed.exit_code == 0, listed.output
    assert "vault://prod/key" in listed.output
    assert removed.exit_code == 0, removed.output
    assert load_config(config_path).credentials == []


def test_mcp_server_list_uses_server_collection(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeClient(
        [
            FakeResponse(
                {
                    "servers": [
                        {
                            "id": "server-12345678",
                            "name": "database",
                            "transport_type": "streamable_http",
                            "status": "active",
                            "tools": [{"name": "query"}],
                        }
                    ]
                }
            )
        ]
    )
    monkeypatch.setattr(mcp, "get_api_client", lambda: client)

    result = runner.invoke(app, ["mcp", "server", "list"])

    assert result.exit_code == 0, result.output
    assert "database" in result.output
    assert "streamable_http" in result.output
