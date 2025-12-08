"""
Manual OAuth integration tests.

These tests require real Authentik credentials and should be run manually
before deployment to verify the OAuth flow works end-to-end.

Run with:
    AUTHENTIK_CLIENT_ID=xxx AUTHENTIK_SECRET=xxx python manage.py test core.tests.test_oauth_manual

Or interactively:
    python manage.py shell
    >>> from core.tests.test_oauth_manual import *
    >>> test_oauth_config()
    >>> test_token_endpoint_reachable()

These are NOT run by pytest by default - they're helper functions for manual verification.
"""

import os

import pytest
from django.conf import settings


@pytest.mark.skip(reason="Manual test - run directly with credentials")
def test_oauth_config():
    """Verify OAuth configuration is present."""
    client_id = getattr(settings, "AUTHENTIK_CLIENT_ID", None) or os.environ.get("AUTHENTIK_CLIENT_ID")
    client_secret = getattr(settings, "AUTHENTIK_SECRET", None) or os.environ.get("AUTHENTIK_SECRET")
    server_url = getattr(settings, "AUTHENTIK_OIDC_URL", "https://auth.wccomps.org/application/o/discord-bot/")

    print(f"Client ID: {'✓ set' if client_id else '✗ MISSING'}")
    print(f"Client Secret: {'✓ set' if client_secret else '✗ MISSING'}")
    print(f"Server URL: {server_url}")

    assert client_id, "AUTHENTIK_CLIENT_ID not configured"
    assert client_secret, "AUTHENTIK_SECRET not configured"
    print("✓ OAuth configuration OK")


@pytest.mark.skip(reason="Manual test - run directly with credentials")
def test_token_endpoint_reachable():
    """Verify Authentik token endpoint is reachable."""
    import httpx

    server_url = getattr(settings, "AUTHENTIK_OIDC_URL", "https://auth.wccomps.org/application/o/discord-bot/")
    token_url = f"{server_url.rstrip('/')}/token/"

    print(f"Testing: {token_url}")

    # We expect a 400 (bad request) because we're not sending valid data
    # But this proves the endpoint is reachable
    try:
        response = httpx.post(token_url, data={}, timeout=10.0)
        print(f"Response: {response.status_code}")
        # 400 = endpoint exists and rejected our empty request (expected)
        # 401 = endpoint exists and rejected our auth (expected)
        # 405 = endpoint exists but wrong method
        assert response.status_code in [400, 401, 405], f"Unexpected status: {response.status_code}"
        print("✓ Token endpoint reachable")
    except httpx.RequestError as e:
        print(f"✗ Failed to reach token endpoint: {e}")
        raise


@pytest.mark.skip(reason="Manual test - run directly with credentials")
def test_userinfo_endpoint_reachable():
    """Verify Authentik userinfo endpoint is reachable."""
    import httpx

    server_url = getattr(settings, "AUTHENTIK_OIDC_URL", "https://auth.wccomps.org/application/o/discord-bot/")
    userinfo_url = f"{server_url.rstrip('/')}/userinfo/"

    print(f"Testing: {userinfo_url}")

    try:
        response = httpx.get(userinfo_url, timeout=10.0)
        print(f"Response: {response.status_code}")
        # 401 = endpoint exists and rejected our unauthenticated request (expected)
        assert response.status_code == 401, f"Unexpected status: {response.status_code}"
        print("✓ Userinfo endpoint reachable")
    except httpx.RequestError as e:
        print(f"✗ Failed to reach userinfo endpoint: {e}")
        raise


@pytest.mark.skip(reason="Manual test - run directly with credentials")
def test_openid_configuration():
    """Fetch and display OpenID configuration."""
    import httpx

    server_url = getattr(settings, "AUTHENTIK_OIDC_URL", "https://auth.wccomps.org/application/o/discord-bot/")
    config_url = f"{server_url.rstrip('/')}/.well-known/openid-configuration"

    print(f"Fetching: {config_url}")

    try:
        response = httpx.get(config_url, timeout=10.0)
        response.raise_for_status()
        config = response.json()

        print("\nOpenID Configuration:")
        print(f"  issuer: {config.get('issuer')}")
        print(f"  authorization_endpoint: {config.get('authorization_endpoint')}")
        print(f"  token_endpoint: {config.get('token_endpoint')}")
        print(f"  userinfo_endpoint: {config.get('userinfo_endpoint')}")
        print(f"  end_session_endpoint: {config.get('end_session_endpoint')}")
        print(f"  scopes_supported: {config.get('scopes_supported')}")
        print(f"  claims_supported: {config.get('claims_supported')}")

        # Verify 'groups' is in claims
        claims = config.get("claims_supported", [])
        if "groups" in claims:
            print("\n✓ 'groups' claim is supported")
        else:
            print("\n⚠ 'groups' claim NOT in claims_supported - groups may not be returned!")

        print("\n✓ OpenID configuration OK")
        return config
    except httpx.RequestError as e:
        print(f"✗ Failed to fetch OpenID configuration: {e}")
        raise


def run_all_checks():
    """Run all pre-deployment checks."""
    print("=" * 60)
    print("OAuth Pre-Deployment Checks")
    print("=" * 60)

    try:
        print("\n1. Configuration Check")
        print("-" * 40)
        test_oauth_config()
    except AssertionError as e:
        print(f"FAILED: {e}")
        return False

    try:
        print("\n2. OpenID Configuration")
        print("-" * 40)
        test_openid_configuration()
    except Exception as e:
        print(f"FAILED: {e}")
        return False

    try:
        print("\n3. Token Endpoint")
        print("-" * 40)
        test_token_endpoint_reachable()
    except Exception as e:
        print(f"FAILED: {e}")
        return False

    try:
        print("\n4. Userinfo Endpoint")
        print("-" * 40)
        test_userinfo_endpoint_reachable()
    except Exception as e:
        print(f"FAILED: {e}")
        return False

    print("\n" + "=" * 60)
    print("✓ All checks passed!")
    print("=" * 60)
    return True


if __name__ == "__main__":
    import django

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "wccomps.settings")
    django.setup()
    run_all_checks()
