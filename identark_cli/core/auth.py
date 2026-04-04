"""
Authentication handling for IdentArk CLI
"""

from __future__ import annotations

import webbrowser
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlencode, urlparse

import httpx
import keyring
from rich.console import Console

from identark_cli.core.config import load_global_config, save_global_config, GlobalConfig

console = Console()

KEYRING_SERVICE = "identark-cli"


@dataclass
class AuthStatus:
    """Authentication status"""
    authenticated: bool
    email: Optional[str] = None
    org_name: Optional[str] = None
    user_id: Optional[str] = None


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
            user_id=user_info.get("id")
        )
    except:
        return AuthStatus(authenticated=False)


def login(
    api_url: str = "https://identark-cloud.fly.dev",
    browser: bool = True
) -> None:
    """
    Authenticate with IdentArk
    
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
    config.access_token = token_data["access_token"]
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
    
    # Revoke token if possible
    if config.access_token:
        try:
            _revoke_token(config)
        except:
            pass  # Ignore errors on logout
    
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
            _refresh_token(config)
        else:
            raise AuthError("Session expired. Run 'identark auth login'")
    
    return config.access_token


def get_api_client() -> httpx.Client:
    """Get authenticated HTTP client"""
    config = load_global_config()
    token = get_access_token()
    
    return httpx.Client(
        base_url=config.api_url,
        headers={"Authorization": f"Bearer {token}"},
        timeout=30.0
    )


def _device_code_flow(api_url: str) -> dict:
    """Device code OAuth flow"""
    # Request device code
    response = httpx.post(
        f"{api_url}/v1/auth/device/code",
        json={"client_id": "identark-cli"}
    )
    response.raise_for_status()
    
    device_code_data = response.json()
    
    console.print(f"\n[bold]Authentication required[/bold]")
    console.print(f"\n1. Visit: [cyan]{device_code_data['verification_uri']}[/cyan]")
    console.print(f"2. Enter code: [bold]{device_code_data['user_code']}[/bold]")
    console.print("\nWaiting for authentication...")
    
    # Poll for token
    interval = device_code_data.get("interval", 5)
    device_code = device_code_data["device_code"]
    
    import time
    
    while True:
        time.sleep(interval)
        
        response = httpx.post(
            f"{api_url}/v1/auth/device/token",
            json={
                "device_code": device_code,
                "client_id": "identark-cli"
            }
        )
        
        if response.status_code == 200:
            return response.json()
        
        data = response.json()
        if data.get("error") == "authorization_pending":
            continue
        elif data.get("error") == "slow_down":
            interval += 5
        else:
            raise AuthError(data.get("error_description", "Authentication failed"))


def _get_user_info(config: GlobalConfig) -> dict:
    """Get current user info"""
    response = httpx.get(
        f"{config.api_url}/v1/auth/me",
        headers={"Authorization": f"Bearer {config.access_token}"}
    )
    response.raise_for_status()
    return response.json()


def _is_token_expired(config: GlobalConfig) -> bool:
    """Check if access token is expired"""
    import jwt
    from datetime import datetime
    
    try:
        payload = jwt.decode(
            config.access_token,
            options={"verify_signature": False}
        )
        exp = payload.get("exp")
        if exp:
            return datetime.utcnow().timestamp() > exp
    except:
        pass
    
    return False


def _refresh_token(config: GlobalConfig) -> None:
    """Refresh access token"""
    response = httpx.post(
        f"{config.api_url}/v1/auth/refresh",
        json={"refresh_token": config.refresh_token}
    )
    response.raise_for_status()
    
    data = response.json()
    config.access_token = data["access_token"]
    if "refresh_token" in data:
        config.refresh_token = data["refresh_token"]
    
    save_global_config(config)


def _revoke_token(config: GlobalConfig) -> None:
    """Revoke access token"""
    httpx.post(
        f"{config.api_url}/v1/auth/revoke",
        headers={"Authorization": f"Bearer {config.access_token}"}
    )


class AuthError(Exception):
    """Authentication error"""
    pass
