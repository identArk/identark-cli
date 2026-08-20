"""
Authentication handling for IdentArk CLI — Firebase Auth device flow
"""

from __future__ import annotations

import os
import time
import webbrowser
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
import jwt
from rich.console import Console

from identark_cli import __version__
from identark_cli.core import secrets as secret_store
from identark_cli.core.config import GlobalConfig, load_global_config, save_global_config

console = Console()

FIREBASE_AUTH_BASE = "https://identitytoolkit.googleapis.com/v1"
FIREBASE_SECURE_TOKEN_BASE = "https://securetoken.googleapis.com/v1"
DEFAULT_API_URL = "https://api.identark.io"
HTTP_TIMEOUT_SECONDS = 30.0
ENV_TOKEN_NAMES = ("IDENTARK_API_KEY", "IDENTARK_SESSION_TOKEN", "IDENTARK_TOKEN")


@dataclass
class AuthStatus:
    """Authentication status"""

    authenticated: bool
    email: str | None = None
    org_name: str | None = None
    user_id: str | None = None
    source: str = "none"
    verified: bool = False


def get_auth_status() -> AuthStatus:
    """Get current authentication status"""
    config = load_global_config()
    environment_token = _get_environment_token()

    if environment_token is not None:
        env_name, token = environment_token
        # Scoped API keys intentionally cannot call /auth/me. Their presence is
        # still useful status information, but do not claim they were verified.
        if token.startswith("csk_"):
            return AuthStatus(authenticated=True, source=env_name, verified=False)
        config.access_token = token

    if not config.access_token:
        return AuthStatus(authenticated=False)

    # Validate token by making a lightweight API call
    try:
        user_info = _get_user_info(config)
        return AuthStatus(
            authenticated=True,
            email=user_info.get("email"),
            org_name=user_info.get("org_name"),
            user_id=user_info.get("id"),
            source=environment_token[0] if environment_token else "device-login",
            verified=True,
        )
    except (httpx.HTTPError, KeyError, ValueError):
        return AuthStatus(
            authenticated=environment_token is not None,
            source=environment_token[0] if environment_token else "device-login",
            verified=False,
        )


def login(api_url: str = DEFAULT_API_URL, browser: bool = True) -> None:
    """
    Authenticate with IdentArk via Firebase device code flow

    Opens browser for OAuth flow or provides device code
    """
    config = load_global_config()
    api_url = api_url.rstrip("/")
    config.api_url = api_url

    token_data = _device_code_flow(api_url, browser=browser)

    # Save tokens
    config.access_token = token_data["id_token"]
    config.refresh_token = token_data.get("refresh_token")

    # Get user info
    user_info = _get_user_info(config)
    config.user_email = user_info.get("email")
    config.user_id = user_info.get("id")
    config.default_org_id = user_info.get("default_org_id")

    save_global_config(config)

    console.print(f"✓ Logged in as [green]{config.user_email}[/green]")


def logout() -> None:
    """Log out and clear credentials"""
    config = load_global_config()

    # Clear config
    config.access_token = None
    config.refresh_token = None
    config.user_email = None
    config.user_id = None

    save_global_config(config)

    # Belt and braces: drop anything left in the keychain or file fallback.
    secret_store.clear_all()

    console.print("✓ Logged out")


def get_access_token() -> str:
    """Get current access token, refreshing if necessary"""
    environment_token = _get_environment_token()
    if environment_token is not None:
        return environment_token[1]

    config = load_global_config()

    if not config.access_token:
        raise AuthError("Not authenticated. Run 'identark auth login'")

    # Check if token needs refresh
    if _is_token_expired(config):
        if config.refresh_token:
            _refresh_firebase_token(config)
        else:
            raise AuthError("Session expired. Run 'identark auth login'")

    return config.access_token


def get_api_client() -> httpx.Client:
    """Get authenticated HTTP client"""
    config = load_global_config()
    token = get_access_token()

    api_url = os.environ.get("IDENTARK_API_URL", config.api_url).rstrip("/")
    return httpx.Client(
        base_url=api_url,
        headers={"Authorization": f"Bearer {token}", "User-Agent": f"identark-cli/{__version__}"},
        timeout=HTTP_TIMEOUT_SECONDS,
    )


def _device_code_flow(api_url: str, *, browser: bool = True) -> dict[str, str]:
    """Device code OAuth flow — returns Firebase ID token after exchange"""
    # Request device code from backend
    response = httpx.post(
        f"{api_url}/v1/auth/device/code",
        json={"client_id": "identark-cli"},
        timeout=HTTP_TIMEOUT_SECONDS,
    )
    response.raise_for_status()

    device_code_data: dict[str, Any] = response.json()
    verification_uri = str(device_code_data["verification_uri"])
    verification_uri_complete = str(
        device_code_data.get("verification_uri_complete") or verification_uri
    )

    console.print("\n[bold]Authentication required[/bold]")
    console.print(f"\n1. Visit: [cyan]{verification_uri_complete}[/cyan]")
    console.print(f"2. Enter code: [bold]{device_code_data['user_code']}[/bold]")
    console.print("\nWaiting for authentication...")

    if browser:
        try:
            if not webbrowser.open(verification_uri_complete):
                console.print(
                    "[dim]Could not open a browser automatically; use the URL above.[/dim]"
                )
        except webbrowser.Error:
            console.print("[dim]Could not open a browser automatically; use the URL above.[/dim]")

    # Poll for token
    interval = max(1, min(int(device_code_data.get("interval", 5)), 30))
    expires_in = max(1, int(device_code_data.get("expires_in", 600)))
    deadline = time.monotonic() + expires_in
    device_code = str(device_code_data["device_code"])

    while time.monotonic() < deadline:
        time.sleep(interval)

        response = httpx.post(
            f"{api_url}/v1/auth/device/token",
            json={"device_code": device_code, "client_id": "identark-cli"},
            timeout=HTTP_TIMEOUT_SECONDS,
        )

        if response.status_code == 200:
            data: dict[str, Any] = response.json()
            custom_token = data.get("custom_token") or data.get("access_token")
            firebase_api_key = data.get("firebase_api_key")
            if not custom_token:
                raise AuthError("Backend did not return custom token")
            if not firebase_api_key:
                raise AuthError("Backend did not return Firebase API key")

            # Exchange Firebase custom token for ID token + refresh token
            return _exchange_custom_token(str(custom_token), str(firebase_api_key))

        try:
            data = response.json()
        except ValueError:
            raise AuthError(f"Device authorization returned HTTP {response.status_code}") from None
        error_data = data.get("detail", data) if isinstance(data, dict) else {}
        error_code = error_data.get("error") if isinstance(error_data, dict) else None
        if error_code == "authorization_pending":
            continue
        if error_code == "slow_down":
            interval = min(interval + 5, 30)
        else:
            description = (
                error_data.get("error_description", "Authentication failed")
                if isinstance(error_data, dict)
                else "Authentication failed"
            )
            raise AuthError(str(description))

    raise AuthError("Device code expired before authentication completed")


def _exchange_custom_token(custom_token: str, api_key: str) -> dict[str, str]:
    """Exchange Firebase custom token for ID token and refresh token"""
    url = f"{FIREBASE_AUTH_BASE}/accounts:signInWithCustomToken?key={api_key}"

    response = httpx.post(
        url,
        json={"token": custom_token, "returnSecureToken": True},
        timeout=HTTP_TIMEOUT_SECONDS,
    )

    if not response.is_success:
        error_data = response.json()
        message = error_data.get("error", {}).get("message", "Unknown error")
        raise AuthError(f"Failed to exchange custom token: {message}")

    data = response.json()
    return {
        "id_token": data["idToken"],
        "refresh_token": data.get("refreshToken"),
        "expires_in": data.get("expiresIn", "3600"),
    }


def _refresh_firebase_token(config: GlobalConfig) -> None:
    """Refresh Firebase ID token using refresh token"""
    if not config.refresh_token:
        raise AuthError("No refresh token available")

    # We need the Firebase API key to refresh. Try to get it from the backend.
    # For now, we'll make a request to the backend's public config endpoint.
    # If that's not available, we fall back to redirecting to login.
    api_key = _get_firebase_api_key(config)
    if not api_key:
        raise AuthError("Cannot refresh token. Please run 'identark auth login' again.")

    url = f"{FIREBASE_SECURE_TOKEN_BASE}/token?key={api_key}"

    response = httpx.post(
        url,
        data={"grant_type": "refresh_token", "refresh_token": config.refresh_token},
        timeout=HTTP_TIMEOUT_SECONDS,
    )

    if not response.is_success:
        raise AuthError("Token refresh failed. Please run 'identark auth login' again.")

    data = response.json()
    config.access_token = data["id_token"]
    if "refresh_token" in data:
        config.refresh_token = data["refresh_token"]

    save_global_config(config)


def _get_firebase_api_key(config: GlobalConfig) -> str | None:
    """Fetch Firebase API key from backend public config"""
    try:
        response = httpx.get(f"{config.api_url.rstrip('/')}/v1/config/public", timeout=5.0)
        if response.is_success:
            data = response.json()
            value = data.get("firebase_api_key")
            return str(value) if value else None
    except (httpx.HTTPError, KeyError, ValueError):
        return None
    return None


def _get_user_info(config: GlobalConfig) -> dict[str, Any]:
    """Get current user info"""
    response = httpx.get(
        f"{config.api_url.rstrip('/')}/v1/auth/me",
        headers={"Authorization": f"Bearer {config.access_token}"},
        timeout=HTTP_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise AuthError("IdentArk returned an invalid user profile")
    return data


def _is_token_expired(config: GlobalConfig) -> bool:
    """Check if Firebase ID token is expired"""
    if not config.access_token:
        return True
    try:
        payload = jwt.decode(config.access_token, options={"verify_signature": False})
        exp = payload.get("exp")
        if exp:
            # Consider token expired 60 seconds before actual expiry
            return datetime.now(UTC).timestamp() > (float(exp) - 60)
    except (jwt.PyJWTError, TypeError, ValueError):
        return True

    return False


def _get_environment_token() -> tuple[str, str] | None:
    """Return a non-persisted token configured for CI or automation."""
    for name in ENV_TOKEN_NAMES:
        value = os.environ.get(name)
        if value:
            return name, value
    return None


class AuthError(Exception):
    """Authentication error"""

    pass
