from urllib.parse import parse_qs, urlsplit

import pytest

import romarr.oidc as oidc_module
from romarr.oidc import OIDCAuth, OIDCSettings, _Transaction


def apple_auth():
    return OIDCAuth(OIDCSettings(
        issuer_url="https://appleid.apple.com",
        client_id="com.example.romarr",
        client_secret="signed-client-secret-jwt",
        redirect_uri="https://romarr.example.test/auth/oidc/callback",
        allowed_emails="operator@example.test",
        allow_private_issuer=True,
    ))


def test_apple_authorization_uses_form_post_email_only_and_no_pkce(monkeypatch):
    monkeypatch.setattr(oidc_module, "_check_network_target", lambda *_args: None)
    auth = apple_auth()
    auth._get_metadata = lambda: {
        "authorization_endpoint": "https://appleid.apple.com/auth/authorize",
    }

    authorize_url, state, _ttl = auth.begin("/settings")
    query = parse_qs(urlsplit(authorize_url).query)

    assert query["response_type"] == ["code"]
    assert query["scope"] == ["openid email"]
    assert query["response_mode"] == ["form_post"]
    assert query["state"] == [state]
    assert "code_challenge" not in query
    assert "code_challenge_method" not in query


@pytest.mark.parametrize("verified", [True, "true"])
def test_apple_token_exchange_posts_signed_secret_and_accepts_verified_claim(monkeypatch, verified):
    monkeypatch.setattr(oidc_module, "_check_network_target", lambda *_args: None)
    auth = apple_auth()
    state = "apple-state"
    nonce = "apple-nonce"
    auth._transactions[state] = _Transaction(
        state=state,
        nonce=nonce,
        code_verifier=None,
        return_to="/settings",
        expires_at=oidc_module.time.time() + 60,
    )
    auth._get_metadata = lambda: {
        "token_endpoint": "https://appleid.apple.com/auth/token",
        "jwks_uri": "https://appleid.apple.com/auth/keys",
        "id_token_signing_alg_values_supported": ["RS256"],
    }
    token_requests = []

    def request_json(url, **kwargs):
        if url.endswith("/auth/token"):
            token_requests.append(kwargs)
            return {"id_token": "test-id-token", "access_token": "access-token"}
        if url.endswith("/auth/keys"):
            return {"keys": []}
        raise AssertionError(f"unexpected provider request: {url}")

    auth._request_json = request_json
    auth._verify_id_token = lambda *_args: {
        "sub": "apple-subject",
        "email": "operator@example.test",
        "email_verified": verified,
    }

    assert auth.finish(state, state, "authorization-code") == (
        "operator@example.test",
        "apple-subject",
        "/settings",
    )
    assert len(token_requests) == 1
    token_request = token_requests[0]
    assert token_request["method"] == "POST"
    assert token_request["auth"] is None
    assert token_request["data"]["client_secret"] == "signed-client-secret-jwt"
    assert "code_verifier" not in token_request["data"]


def test_apple_rejects_unverified_claim_even_when_email_is_allowlisted(monkeypatch):
    monkeypatch.setattr(oidc_module, "_check_network_target", lambda *_args: None)
    auth = apple_auth()
    state = "apple-state"
    auth._transactions[state] = _Transaction(
        state=state,
        nonce="apple-nonce",
        code_verifier=None,
        return_to="/",
        expires_at=oidc_module.time.time() + 60,
    )
    auth._get_metadata = lambda: {
        "token_endpoint": "https://appleid.apple.com/auth/token",
        "jwks_uri": "https://appleid.apple.com/auth/keys",
        "id_token_signing_alg_values_supported": ["RS256"],
    }
    auth._request_json = lambda url, **_kwargs: (
        {"id_token": "test-id-token", "access_token": "access-token"}
        if url.endswith("/auth/token") else {"keys": []}
    )
    auth._verify_id_token = lambda *_args: {
        "sub": "apple-subject",
        "email": "operator@example.test",
        "email_verified": "false",
    }

    with pytest.raises(oidc_module.OIDCAuthError, match="email_unverified"):
        auth.finish(state, state, "authorization-code")
