"""Local injection when the control plane refuses to export a credential.

Credentials are non-exportable by default. ``/v1/credentials/resolve`` answers
403 unless the caller is signed in (device login) or uses a developer key
holding ``credentials:resolve``, and the credential is marked exportable. The
CLI must say which of those is missing instead of a generic failure.
"""

from __future__ import annotations

import subprocess
from typing import Any

import pytest
from typer.testing import CliRunner

from identark_cli.commands import credential
from identark_cli.commands.credential import CredentialExportDeniedError
from identark_cli.core.config import CredentialRef, ProjectConfig
from identark_cli.main import app

runner = CliRunner()


class _Response:
    def __init__(self, payload: Any, status_code: int) -> None:
        self.payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def json(self) -> Any:
        return self.payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _Client:
    def __init__(self, response: _Response) -> None:
        self.response = response
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __enter__(self) -> _Client:
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    def get(self, path: str, **kwargs: Any) -> _Response:
        self.calls.append((path, kwargs))
        return self.response


def _forbidden(error_code: str, **extra: Any) -> _Response:
    return _Response({"detail": {"error_code": error_code, "message": "refused", **extra}}, 403)


@pytest.fixture(autouse=True)
def _no_env_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("IDENTARK_API_KEY", "IDENTARK_SESSION_TOKEN", "IDENTARK_TOKEN"):
        monkeypatch.delenv(name, raising=False)


def test_non_exportable_credential_names_the_owner_fix(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _Client(_forbidden("credential_not_exportable", paths=["prod/openai"]))
    monkeypatch.setattr(credential, "get_api_client", lambda: client)

    with pytest.raises(CredentialExportDeniedError) as info:
        credential._fetch_credential_value("vault://prod/openai")

    assert "prod/openai is not exportable" in info.value.message
    assert "org owner" in info.value.explanation
    assert client.calls[0] == ("/v1/credentials/resolve", {"params": {"path": "prod/openai"}})


def test_missing_scope_points_to_device_login(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _Client(_forbidden("insufficient_scope", required_scope="credentials:resolve"))
    monkeypatch.setattr(credential, "get_api_client", lambda: client)

    with pytest.raises(CredentialExportDeniedError) as info:
        credential._fetch_credential_value("vault://dev/anthropic")

    assert "credentials:resolve" in info.value.message
    assert "org:admin" in info.value.explanation
    assert info.value.next_step == "identark auth login"


def test_environment_api_key_is_named_because_it_shadows_device_login(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("IDENTARK_API_KEY", "csk_agent_key_for_test")
    client = _Client(_forbidden("insufficient_scope", required_scope="credentials:resolve"))
    monkeypatch.setattr(credential, "get_api_client", lambda: client)

    with pytest.raises(CredentialExportDeniedError) as info:
        credential._fetch_credential_value("vault://dev/anthropic")

    assert info.value.next_step == "unset IDENTARK_API_KEY && identark auth login"
    assert "csk_agent_key_for_test" not in str(info.value)


def test_agent_bound_key_is_explained(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _Client(_forbidden("agent_key_cannot_export", required_scope="credentials:resolve"))
    monkeypatch.setattr(credential, "get_api_client", lambda: client)

    with pytest.raises(CredentialExportDeniedError) as info:
        credential._fetch_credential_value("vault://dev/anthropic")

    assert "bound to an agent" in info.value.message
    assert "credentials:resolve" in info.value.explanation


def test_unknown_403_still_gets_guidance(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _Client(_Response({"detail": "Forbidden"}, 403))
    monkeypatch.setattr(credential, "get_api_client", lambda: client)

    with pytest.raises(CredentialExportDeniedError) as info:
        credential._fetch_credential_value("vault://dev/anthropic")

    assert "refused to export" in info.value.message
    assert "credentials:resolve" in info.value.explanation


def test_inject_stops_with_the_reason_and_never_starts_the_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        credential,
        "load_config",
        lambda: ProjectConfig(
            credentials=[CredentialRef(name="OPENAI_API_KEY", ref="vault://prod/openai")]
        ),
    )
    client = _Client(_forbidden("credential_not_exportable", paths=["prod/openai"]))
    monkeypatch.setattr(credential, "get_api_client", lambda: client)
    started: list[Any] = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: started.append(a))

    result = runner.invoke(app, ["credential", "inject", "--", "python", "-c", "pass"])

    assert result.exit_code == 1
    output = " ".join(result.output.split())
    assert "OPENAI_API_KEY" in output
    assert "not exportable" in output
    assert "child process was not started" in output
    assert started == []


def test_inject_warns_and_continues_for_optional_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        credential,
        "load_config",
        lambda: ProjectConfig(
            credentials=[
                CredentialRef(name="OPTIONAL_KEY", ref="vault://dev/openai", required=False)
            ]
        ),
    )
    client = _Client(_forbidden("insufficient_scope", required_scope="credentials:resolve"))
    monkeypatch.setattr(credential, "get_api_client", lambda: client)

    class _Done:
        returncode = 0

    started: list[Any] = []

    def _run(cmd: Any, env: dict[str, str]) -> _Done:
        started.append(cmd)
        assert "OPTIONAL_KEY" not in env
        return _Done()

    monkeypatch.setattr(subprocess, "run", _run)

    result = runner.invoke(app, ["credential", "inject", "--", "python", "-c", "pass"])

    assert result.exit_code == 0, result.output
    output = " ".join(result.output.split())
    assert "OPTIONAL_KEY is unavailable" in output
    assert "identark auth login" in output
    assert started
