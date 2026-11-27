import json
import uuid

import httpx
import pytest
from typer.testing import CliRunner

from identark_cli.main import app

runner = CliRunner()
EXECUTION = str(uuid.uuid4())


def client_stub(monkeypatch, responses):
    calls = []

    def handler(request):
        calls.append(request)
        status, body = responses.pop(0)
        return httpx.Response(status, json=body)

    monkeypatch.setattr(
        "identark_cli.commands.execute.get_api_client",
        lambda: httpx.Client(
            base_url="https://example.test", transport=httpx.MockTransport(handler)
        ),
    )
    return calls


def test_exec_success_uses_gateway_not_credential_resolution(monkeypatch):
    calls = client_stub(
        monkeypatch, [(202, {"id": EXECUTION, "status": "succeeded", "result": {"issues": []}})]
    )
    result = runner.invoke(
        app, ["exec", "source_control.issues.read", "--resource", "identark/demo", "--json"]
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["decision"] == "allowed"
    assert calls[0].url.path == "/v1/gateway/requests"
    body = json.loads(calls[0].content)
    assert body["payload"] == {"repository": "identark/demo"}
    assert "agent_id" not in body


@pytest.mark.parametrize(
    "status,body,code,decision",
    [
        (403, {"detail": "SECRET_CANARY"}, 3, "denied"),
        (401, {"detail": "SECRET_CANARY"}, 3, "denied"),
        (500, {"detail": "SECRET_CANARY"}, 5, "error"),
        (409, {"detail": "SECRET_CANARY"}, 2, "error"),
        (202, {"request_id": EXECUTION, "status": "pending_approval"}, 4, "pending"),
        (
            202,
            {
                "request_id": EXECUTION,
                "status": "reconciliation_required",
                "error_code": "SECRET_CANARY",
            },
            5,
            "error",
        ),
    ],
)
def test_structured_exit_codes_and_safe_errors(monkeypatch, status, body, code, decision):
    client_stub(monkeypatch, [(status, body)])
    result = runner.invoke(
        app, ["exec", "source_control.issues.read", "--resource", "identark/demo", "--json"]
    )
    assert result.exit_code == code, result.output
    assert json.loads(result.stdout)["decision"] == decision
    assert "SECRET_CANARY" not in result.output


def test_wait_polls_without_resubmitting(monkeypatch):
    calls = client_stub(
        monkeypatch,
        [
            (202, {"request_id": EXECUTION, "status": "pending_approval"}),
            (200, {"id": EXECUTION, "status": "succeeded"}),
        ],
    )
    monkeypatch.setattr("identark_cli.commands.execute.time.sleep", lambda _: None)
    result = runner.invoke(
        app, ["exec", "source_control.issues.read", "--resource", "identark/demo", "--wait", "5"]
    )
    assert result.exit_code == 0
    assert [r.method for r in calls] == ["POST", "GET"]


@pytest.mark.parametrize(
    "arguments",
    [
        ["--input", "[]"],
        ["--input", "not json"],
        ["--resource", "a/b", "--input", '{"repository":"c/d"}'],
        ["--idempotency-key", "short"],
    ],
)
def test_bad_input_never_calls_server(monkeypatch, arguments):
    calls = client_stub(monkeypatch, [])
    result = runner.invoke(app, ["exec", "source_control.issues.read", *arguments])
    assert result.exit_code == 2
    assert not calls
