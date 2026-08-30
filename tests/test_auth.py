"""CLI authentication contract and secret-output regression tests."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import jwt
import pytest
from typer.testing import CliRunner

from identark_cli.commands import auth as auth_commands
from identark_cli.core import auth
from identark_cli.core.config import GlobalConfig


class StubResponse:
    def __init__(self, status_code: int, payload: dict[str, Any]):
        self.status_code = status_code
        self._payload = payload

    @property
    def is_success(self) -> bool:
        return 200 <= self.status_code < 300

    def json(self) -> dict[str, Any]:
        return self._payload

    def raise_for_status(self) -> None:
        if not self.is_success:
            request = httpx.Request("POST", "https://api.identark.io")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("request failed", request=request, response=response)


def test_device_flow_handles_nested_pending_then_live_token_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses: Iterator[StubResponse] = iter(
        [
            StubResponse(
                200,
                {
                    "device_code": "device-code",
                    "user_code": "ABCD-EFGH",
                    "verification_uri": "https://identark.io/auth/device",
                    "verification_uri_complete": "https://identark.io/auth/device?user_code=ABCD-EFGH",
                    "expires_in": 600,
                    "interval": 5,
                },
            ),
            StubResponse(
                400,
                {
                    "detail": {
                        "error": "authorization_pending",
                        "error_description": "Authorization pending",
                    }
                },
            ),
            StubResponse(
                200,
                {
                    "custom_token": "firebase-custom-token",
                    "firebase_api_key": "firebase-api-key",
                    "expires_in": 3600,
                    "token_type": "custom_token",
                },
            ),
        ]
    )
    monkeypatch.setattr(auth.httpx, "post", lambda *args, **kwargs: next(responses))
    monkeypatch.setattr(auth.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(auth.webbrowser, "open", lambda _url: True)
    monkeypatch.setattr(
        auth,
        "_exchange_custom_token",
        lambda token, key: {"id_token": token, "refresh_token": key},
    )

    result = auth._device_code_flow("https://api.identark.io", browser=True)

    assert result == {"id_token": "firebase-custom-token", "refresh_token": "firebase-api-key"}


def test_no_browser_does_not_open_browser(monkeypatch: pytest.MonkeyPatch) -> None:
    monotonic_values = iter([0.0, 2.0])
    response = StubResponse(
        200,
        {
            "device_code": "device-code",
            "user_code": "ABCD-EFGH",
            "verification_uri": "https://identark.io/auth/device",
            "expires_in": 1,
            "interval": 1,
        },
    )
    monkeypatch.setattr(auth.httpx, "post", lambda *args, **kwargs: response)
    monkeypatch.setattr(auth.time, "monotonic", lambda: next(monotonic_values))
    opened: list[str] = []
    monkeypatch.setattr(auth.webbrowser, "open", opened.append)

    with pytest.raises(auth.AuthError, match="expired"):
        auth._device_code_flow("https://api.identark.io", browser=False)

    assert opened == []


def test_environment_api_key_takes_precedence_without_persistence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("IDENTARK_API_KEY", "csk_environment_only")
    monkeypatch.setattr(
        auth,
        "load_global_config",
        lambda: GlobalConfig(access_token="stored-token"),
    )

    assert auth.get_access_token() == "csk_environment_only"


def test_refresh_uses_secure_token_form_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def post(url: str, **kwargs: Any) -> StubResponse:
        captured["url"] = url
        captured.update(kwargs)
        return StubResponse(200, {"id_token": "new-id", "refresh_token": "new-refresh"})

    config = GlobalConfig(access_token="old-id", refresh_token="old-refresh")
    monkeypatch.setattr(auth, "_get_firebase_api_key", lambda _config: "firebase-key")
    monkeypatch.setattr(auth.httpx, "post", post)
    monkeypatch.setattr(auth, "save_global_config", lambda _config: None)

    auth._refresh_firebase_token(config)

    assert captured["url"] == "https://securetoken.googleapis.com/v1/token?key=firebase-key"
    assert captured["data"] == {"grant_type": "refresh_token", "refresh_token": "old-refresh"}
    assert "json" not in captured
    assert config.access_token == "new-id"
    assert config.refresh_token == "new-refresh"


def test_auth_token_command_never_prints_raw_token(monkeypatch: pytest.MonkeyPatch) -> None:
    raw_token = "csk_this_must_never_appear_in_output"
    monkeypatch.setattr(
        auth,
        "get_auth_status",
        lambda: auth.AuthStatus(True, source="test", verified=False),
    )
    monkeypatch.setattr(auth, "get_access_token", lambda: raw_token)

    result = CliRunner().invoke(auth_commands.app, ["token"])

    assert result.exit_code == 0
    assert raw_token not in result.output
    assert "never displayed" in result.output


def test_custom_token_exchange_uses_firebase_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def post(url: str, **kwargs: Any) -> StubResponse:
        captured["url"] = url
        captured.update(kwargs)
        return StubResponse(
            200,
            {"idToken": "id-token", "refreshToken": "refresh-token", "expiresIn": "3600"},
        )

    monkeypatch.setattr(auth.httpx, "post", post)

    result = auth._exchange_custom_token("custom-token", "firebase-key")

    assert captured["url"].endswith("accounts:signInWithCustomToken?key=firebase-key")
    assert captured["json"] == {"token": "custom-token", "returnSecureToken": True}
    assert result["id_token"] == "id-token"
    assert result["refresh_token"] == "refresh-token"


def test_get_access_token_refreshes_expired_device_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expired = jwt.encode(
        {"exp": datetime.now(UTC) - timedelta(minutes=1)},
        "test-key-that-is-at-least-thirty-two-bytes",
        algorithm="HS256",
    )
    config = GlobalConfig(access_token=expired, refresh_token="refresh-token")

    def refresh(values: GlobalConfig) -> None:
        values.access_token = "refreshed-token"

    monkeypatch.delenv("IDENTARK_API_KEY", raising=False)
    monkeypatch.delenv("IDENTARK_SESSION_TOKEN", raising=False)
    monkeypatch.delenv("IDENTARK_TOKEN", raising=False)
    monkeypatch.setattr(auth, "load_global_config", lambda: config)
    monkeypatch.setattr(auth, "_refresh_firebase_token", refresh)

    assert auth.get_access_token() == "refreshed-token"


def test_get_api_client_honors_environment_endpoint_and_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("IDENTARK_API_URL", "https://staging.identark.io/")
    monkeypatch.setattr(auth, "load_global_config", lambda: GlobalConfig())
    monkeypatch.setattr(auth, "get_access_token", lambda: "test-token")

    with auth.get_api_client() as client:
        assert str(client.base_url) == "https://staging.identark.io"
        assert client.headers["Authorization"] == "Bearer test-token"
        assert client.headers["User-Agent"].startswith("identark-cli/")


def test_invalid_stored_session_is_not_reported_as_authenticated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("IDENTARK_API_KEY", raising=False)
    monkeypatch.delenv("IDENTARK_SESSION_TOKEN", raising=False)
    monkeypatch.delenv("IDENTARK_TOKEN", raising=False)
    monkeypatch.setattr(
        auth,
        "load_global_config",
        lambda: GlobalConfig(access_token="expired-or-invalid"),
    )

    def offline(_config: GlobalConfig) -> dict[str, Any]:
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(auth, "_get_user_info", offline)

    status = auth.get_auth_status()

    assert status.authenticated is False
    assert status.verified is False
