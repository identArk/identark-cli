"""
Authentication handling for IdentArk CLI — Firebase Auth device flow
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import httpx
import jwt
from rich.console import Console

from identark_cli.core.config import GlobalConfig, load_global_config, save_global_config

console = Console()

KEYRING_SERVICE = "identark-cli"
FIREBASE_AUTH_BASE = "https://identitytoolkit.googleapis.com/v1"


@dataclass
class AuthStatus:
    """Authentication status"""

    authenticated: bool
    email: str | None = None
    org_name: str | None = None
    user_id: str | None = None


def get_auth_status() -> AuthStatus:
    """Get current authentication status"""
    config = load_global_config()

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
        )
    except Exception:
        return AuthStatus(authenticated=False)


def login(api_url: str = "https://api.identark.io", browser: bool = True) -> None:
    """
    Authenticate with IdentArk via Firebase device code flow

    Opens browser for OAuth flow or provides device code
    """
    config = load_global_config()
    config.api_url = api_url

    # Try device code flow (no browser needed)
    try:
        token_data = _device_code_flow(api_url)
    except Exception as e:
        console.print(f"[red]Authentication failed:[/red] {e}")
        raise

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

    console.print("✓ Logged out")


def get_access_token() -> str:
    """Get current access token, refreshing if necessary"""
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

    return httpx.Client(
        base_url=config.api_url, headers={"Authorization": f"Bearer {token}"}, timeout=30.0
    )


def _device_code_flow(api_url: str) -> dict:
    """Device code OAuth flow — returns Firebase ID token after exchange"""
    # Request device code from backend
    response = httpx.post(f"{api_url}/v1/auth/device/code", json={"client_id": "identark-cli"})
    response.raise_for_status()

    device_code_data = response.json()

    console.print("\n[bold]Authentication required[/bold]")
    console.print(f"\n1. Visit: [cyan]{device_code_data['verification_uri']}[/cyan]")
    console.print(f"2. Enter code: [bold]{device_code_data['user_code']}[/bold]")
    console.print("\nWaiting for authentication...")

    # Poll for token
    interval = device_code_data.get("interval", 5)
    device_code = device_code_data["device_code"]
    firebase_api_key = device_code_data.get("firebase_api_key")

    if not firebase_api_key:
        raise AuthError("Backend did not return Firebase API key. Cannot complete authentication.")

    while True:
        time.sleep(interval)

        response = httpx.post(
            f"{api_url}/v1/auth/device/token",
            json={"device_code": device_code, "client_id": "identark-cli"},
        )

        if response.status_code == 200:
            data = response.json()
            custom_token = data.get("access_token")
            if not custom_token:
                raise AuthError("Backend did not return custom token")

            # Exchange Firebase custom token for ID token + refresh token
            return _exchange_custom_token(custom_token, firebase_api_key)

        data = response.json()
        if data.get("error") == "authorization_pending":
            continue
        elif data.get("error") == "slow_down":
            interval += 5
        else:
            raise AuthError(data.get("error_description", "Authentication failed"))


def _exchange_custom_token(custom_token: str, api_key: str) -> dict:
    """Exchange Firebase custom token for ID token and refresh token"""
    url = f"{FIREBASE_AUTH_BASE}/accounts:signInWithCustomToken?key={api_key}"

    response = httpx.post(url, json={"token": custom_token, "returnSecureToken": True})

    if not response.is_success:
        error_data = response.json()
        raise AuthError(
            f"Failed to exchange custom token: {error_data.get('error', {}).get('message', 'Unknown error')}"
        )

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

    url = f"{FIREBASE_AUTH_BASE}/token?key={api_key}"

    response = httpx.post(
        url, json={"grant_type": "refresh_token", "refresh_token": config.refresh_token}
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
        response = httpx.get(f"{config.api_url}/v1/config/public", timeout=5.0)
        if response.is_success:
            data = response.json()
            return data.get("firebase_api_key")
    except Exception:
        pass
    return None


def _get_user_info(config: GlobalConfig) -> dict:
    """Get current user info"""
    response = httpx.get(
        f"{config.api_url}/v1/auth/me", headers={"Authorization": f"Bearer {config.access_token}"}
    )
    response.raise_for_status()
    return response.json()


def _is_token_expired(config: GlobalConfig) -> bool:
    """Check if Firebase ID token is expired"""
    from datetime import datetime, timezone

    try:
        payload = jwt.decode(config.access_token, options={"verify_signature": False})
        exp = payload.get("exp")
        if exp:
            # Consider token expired 60 seconds before actual expiry
            return datetime.now(timezone.utc).timestamp() > (exp - 60)
    except Exception:
        pass

    return False


class AuthError(Exception):
    """Authentication error"""

    pass
