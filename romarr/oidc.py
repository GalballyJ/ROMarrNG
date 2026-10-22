"""Server-side OpenID Connect sign-in for ROMarr's operator session."""

from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import logging
import re
import secrets
import socket
import threading
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests
from authlib.jose import JsonWebToken
from authlib.oidc.core import CodeIDToken

log = logging.getLogger(__name__)

_MAX_TRANSACTIONS = 16
_TRANSACTION_TTL = 10 * 60
_MAX_RESPONSE_BYTES = 1 << 20
_ALLOWED_ID_TOKEN_ALGORITHMS = (
    "RS256", "RS384", "RS512", "PS256", "PS384", "PS512",
    "ES256", "ES384", "ES512",
)

_PROVIDER_PRESENTATION = {
    "google": ("Google", "google", "https://developers.google.com/identity/openid-connect/openid-connect"),
    "microsoft-entra": ("Microsoft Entra ID", "microsoft", "https://learn.microsoft.com/en-us/entra/identity-platform/v2-protocols-oidc"),
    "okta": ("Okta", "okta", "https://developer.okta.com/docs/guides/implement-grant-type/authcodepkce/main/"),
    "auth0": ("Auth0", "auth0", "https://auth0.com/docs/get-started/authentication-and-authorization-flow/authorization-code-flow"),
    "keycloak": ("Keycloak", "keycloak", "https://www.keycloak.org/docs/latest/server_admin/"),
    "authentik": ("authentik", "authentik", "https://docs.goauthentik.io/add-secure-apps/providers/oauth2/create-oauth2-provider/"),
    "zitadel": ("ZITADEL", "zitadel", "https://zitadel.com/docs/guides/integrate/login/oidc/oauth-recommended-flows"),
    "amazon-cognito": ("Amazon Cognito", "amazon-cognito", "https://docs.aws.amazon.com/cognito/latest/developerguide/federation-endpoints.html"),
    "apple-sign-in": ("Apple", "apple", "https://developer.apple.com/documentation/signinwithapple/configuring-your-environment-for-sign-in-with-apple"),
    "gitlab": ("GitLab", "gitlab", "https://docs.gitlab.com/integration/openid_connect_provider/"),
    "fusionauth": ("FusionAuth", "fusionauth", "https://fusionauth.io/docs/lifecycle/authenticate-users/oauth/"),
    "onelogin": ("OneLogin", "onelogin", "https://developers.onelogin.com/docs/openid-connect/connect-to-onelogin/"),
    "pingone": ("PingOne", "pingone", "https://docs.pingidentity.com/pingone/applications/p1_edit_application_oidc.html"),
    "jumpcloud": ("JumpCloud", "jumpcloud", "https://jumpcloud.com/support/sso-with-oidc"),
}


def oidc_provider_presentation(provider: str):
    """Return a safe label, local icon ID, and official setup URL."""
    key = str(provider or "").strip().lower()
    return _PROVIDER_PRESENTATION.get(
        key,
        ("identity provider", "generic", "https://openid.net/developers/how-connect-works/"),
    )


def oidc_state_cookie_name(state: str) -> str:
    """Bind each browser cookie to one short-lived authorization transaction."""
    suffix = hashlib.sha256(state.encode("utf-8")).hexdigest()[:32]
    return f"romarr_oidc_state_{suffix}"


@dataclass(frozen=True)
class OIDCSettings:
    provider: str = "generic"
    issuer_url: str = ""
    client_id: str = ""
    client_secret: str = ""
    redirect_uri: str = ""
    allowed_emails: str = ""
    allowed_email_domains: str = ""
    allow_any_verified_user: bool = False
    allow_private_issuer: bool = False

    @classmethod
    def from_env(cls, env: dict[str, str]) -> "OIDCSettings":
        return cls(
            provider=env.get("ROMARR_OIDC_PROVIDER", "generic").strip() or "generic",
            issuer_url=env.get("ROMARR_OIDC_ISSUER_URL", "").strip(),
            client_id=env.get("ROMARR_OIDC_CLIENT_ID", "").strip(),
            client_secret=env.get("ROMARR_OIDC_CLIENT_SECRET", ""),
            redirect_uri=env.get("ROMARR_OIDC_REDIRECT_URI", "").strip(),
            allowed_emails=env.get("ROMARR_OIDC_ALLOWED_EMAILS", ""),
            allowed_email_domains=env.get("ROMARR_OIDC_ALLOWED_EMAIL_DOMAINS", ""),
            allow_any_verified_user=env.get(
                "ROMARR_OIDC_ALLOW_ANY_VERIFIED_USER", ""
            ).strip().lower() in ("1", "true", "yes"),
            allow_private_issuer=env.get(
                "ROMARR_OIDC_ALLOW_PRIVATE_ISSUER", ""
            ).strip().lower() in ("1", "true", "yes"),
        )

    @property
    def configured(self) -> bool:
        return bool(
            self.issuer_url and self.client_id and self.client_secret
            and self.redirect_uri
        )


@dataclass(frozen=True)
class _Transaction:
    state: str
    nonce: str
    code_verifier: str | None
    return_to: str
    expires_at: float


class OIDCAuthError(Exception):
    """Safe OIDC flow error; ``code`` is suitable for operator logs."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class OIDCAuth:
    """OIDC client that exchanges verified identities for ROMarr sessions."""

    def __init__(self, settings: OIDCSettings):
        self.settings = settings
        supplied = (
            settings.issuer_url, settings.client_id, settings.client_secret,
            settings.redirect_uri,
        )
        if any(supplied) and not settings.configured:
            raise ValueError("ROMARR_OIDC_* settings must be configured together")
        self._lock = threading.Lock()
        self._transactions: dict[str, _Transaction] = {}
        self._metadata: dict | None = None
        self._metadata_expires_at = 0.0
        self._metadata_lock = threading.Lock()
        self._http = requests.Session()
        self._http.trust_env = False
        self._jwt = JsonWebToken(list(_ALLOWED_ID_TOKEN_ALGORITHMS))

    @property
    def enabled(self) -> bool:
        return self.settings.configured

    @property
    def apple_issuer(self) -> bool:
        return self.settings.issuer_url.strip() == "https://appleid.apple.com"

    def validate(self) -> None:
        settings = self.settings
        if not settings.configured:
            raise OIDCAuthError("configuration_incomplete")
        issuer = _validate_endpoint(
            settings.issuer_url, settings.allow_private_issuer, issuer=True
        )
        redirect = _parse_https_url(settings.redirect_uri)
        if redirect.path != "/auth/oidc/callback":
            raise OIDCAuthError("callback_path_invalid")
        if len(settings.client_id) > 512 or len(settings.client_secret) > 2048:
            raise OIDCAuthError("configuration_invalid")
        _check_network_target(issuer.hostname, settings.allow_private_issuer)
        _check_network_target(redirect.hostname, settings.allow_private_issuer)

    def begin(self, return_to: str = "/") -> tuple[str, str, int]:
        self.validate()
        metadata = self._get_metadata()
        authorize_endpoint = _validate_endpoint(
            metadata.get("authorization_endpoint", ""),
            self.settings.allow_private_issuer,
            allow_query=True,
        )
        _check_network_target(
            authorize_endpoint.hostname, self.settings.allow_private_issuer
        )
        state = secrets.token_urlsafe(32)
        code_verifier = None if self.apple_issuer else secrets.token_urlsafe(48)
        transaction = _Transaction(
            state=state,
            nonce=secrets.token_urlsafe(32),
            code_verifier=code_verifier,
            return_to=safe_return_to(return_to),
            expires_at=time.time() + _TRANSACTION_TTL,
        )
        query = {
            "response_type": "code",
            "client_id": self.settings.client_id,
            "redirect_uri": self.settings.redirect_uri,
            "scope": "openid email" if self.apple_issuer else "openid profile email",
            "state": state,
            "nonce": transaction.nonce,
        }
        if self.apple_issuer:
            query["response_mode"] = "form_post"
        else:
            challenge = base64.urlsafe_b64encode(
                hashlib.sha256(transaction.code_verifier.encode("ascii")).digest()
            ).rstrip(b"=").decode("ascii")
            query["code_challenge"] = challenge
            query["code_challenge_method"] = "S256"
        parts = urlsplit(authorize_endpoint.geturl())
        existing = parse_qsl(parts.query, keep_blank_values=True)
        if {key for key, _ in existing} & query.keys():
            raise OIDCAuthError("authorization_endpoint_invalid")
        authorize_url = urlunsplit((
            parts.scheme, parts.netloc, parts.path,
            urlencode(existing + list(query.items())), parts.fragment,
        ))
        with self._lock:
            now = time.time()
            self._transactions = {
                key: value for key, value in self._transactions.items()
                if value.expires_at > now
            }
            if len(self._transactions) >= _MAX_TRANSACTIONS:
                raise OIDCAuthError("too_many_transactions")
            self._transactions[state] = transaction
        return authorize_url, state, _TRANSACTION_TTL

    def finish(self, state: str, cookie_state: str, code: str) -> tuple[str, str, str]:
        if (not state or len(state) > 256 or not cookie_state
                or not hmac.compare_digest(state, cookie_state)):
            raise OIDCAuthError("invalid_transaction")
        with self._lock:
            transaction = self._transactions.pop(state, None)
        if transaction is None or transaction.expires_at <= time.time():
            raise OIDCAuthError("expired_transaction")
        if not code or len(code) > 8192:
            raise OIDCAuthError("invalid_authorization_code")

        metadata = self._get_metadata()
        token_endpoint = _validate_endpoint(
            metadata.get("token_endpoint", ""),
            self.settings.allow_private_issuer,
        )
        jwks_endpoint = _validate_endpoint(
            metadata.get("jwks_uri", ""), self.settings.allow_private_issuer
        )
        _check_network_target(token_endpoint.hostname, self.settings.allow_private_issuer)
        _check_network_target(jwks_endpoint.hostname, self.settings.allow_private_issuer)

        token_form = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.settings.redirect_uri,
            "client_id": self.settings.client_id,
        }
        token_auth = (self.settings.client_id, self.settings.client_secret)
        if transaction.code_verifier is not None:
            token_form["code_verifier"] = transaction.code_verifier
        if self.apple_issuer:
            token_form["client_secret"] = self.settings.client_secret
            token_auth = None
        token_data = self._request_json(
            token_endpoint.geturl(),
            method="POST",
            data=token_form,
            auth=token_auth,
        )
        id_token = token_data.get("id_token")
        access_token = token_data.get("access_token")
        if not isinstance(id_token, str) or not id_token or len(id_token) > 32768:
            raise OIDCAuthError("missing_id_token")

        jwks = self._request_json(jwks_endpoint.geturl())
        claims = self._verify_id_token(
            id_token,
            jwks,
            transaction.nonce,
            metadata.get("id_token_signing_alg_values_supported"),
        )
        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject or len(subject) > 1024:
            raise OIDCAuthError("invalid_subject")

        email = claims.get("email")
        email_verified = claims.get("email_verified")
        email_is_verified = email_verified is True or email_verified == "true"
        if email_verified is False or email_verified == "false":
            raise OIDCAuthError("email_unverified")
        if not email_is_verified or not isinstance(email, str) or not email.strip():
            userinfo_endpoint = metadata.get("userinfo_endpoint")
            if not isinstance(userinfo_endpoint, str) or not access_token:
                raise OIDCAuthError("verified_email_unavailable")
            userinfo_url = _validate_endpoint(
                userinfo_endpoint, self.settings.allow_private_issuer
            )
            _check_network_target(
                userinfo_url.hostname, self.settings.allow_private_issuer
            )
            userinfo = self._request_json(
                userinfo_url.geturl(),
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if (userinfo.get("sub") != subject
                    or not (userinfo.get("email_verified") is True
                            or userinfo.get("email_verified") == "true")
                    or not isinstance(userinfo.get("email"), str)):
                raise OIDCAuthError("verified_email_unavailable")
            email = userinfo["email"]

        normalized_email = email.strip().lower()
        if not normalized_email or not self.email_allowed(normalized_email):
            raise OIDCAuthError("identity_not_admitted")
        return normalized_email, subject, transaction.return_to

    def email_allowed(self, email: str) -> bool:
        normalized = email.strip().lower()
        addresses = _parse_set(self.settings.allowed_emails)
        domains = _parse_set(self.settings.allowed_email_domains)
        domain = normalized.rpartition("@")[2]
        return (
            normalized in addresses
            or domain in domains
            or self.settings.allow_any_verified_user
        )

    def _verify_id_token(
        self, token: str, jwks: dict, nonce: str, advertised_algorithms,
    ) -> dict:
        if not isinstance(jwks, dict) or not isinstance(jwks.get("keys"), list):
            raise OIDCAuthError("invalid_key_set")
        if (not isinstance(advertised_algorithms, list)
                or not set(advertised_algorithms).intersection(
                    _ALLOWED_ID_TOKEN_ALGORITHMS
                )):
            raise OIDCAuthError("no_supported_signing_algorithm")
        try:
            parts = token.split(".")
            if len(parts) != 3:
                raise ValueError("invalid compact JWT")
            header_raw = parts[0].encode("ascii")
            header_raw += b"=" * (-len(header_raw) % 4)
            header = json.loads(base64.urlsafe_b64decode(header_raw))
            algorithm = header.get("alg")
            if (algorithm not in _ALLOWED_ID_TOKEN_ALGORITHMS
                    or algorithm not in advertised_algorithms):
                raise ValueError("unsupported signing algorithm")
        except Exception:
            raise OIDCAuthError("unsupported_signing_algorithm") from None
        try:
            claims = self._jwt.decode(
                token,
                jwks,
                claims_cls=CodeIDToken,
                claims_options={
                    "iss": {"essential": True, "value": self.settings.issuer_url},
                    "sub": {"essential": True},
                    "aud": {"essential": True},
                    "exp": {"essential": True},
                    "iat": {"essential": True},
                    "nonce": {"essential": True, "value": nonce},
                },
                claims_params={"client_id": self.settings.client_id, "nonce": nonce},
            )
            claims.validate(leeway=60)
            payload = dict(claims)
        except Exception as error:
            log.debug("OIDC ID token validation failed (%s)", type(error).__name__)
            raise OIDCAuthError("invalid_id_token") from None

        audiences = payload.get("aud")
        audiences = audiences if isinstance(audiences, list) else [audiences]
        if self.settings.client_id not in audiences:
            raise OIDCAuthError("invalid_audience")
        authorized_party = payload.get("azp")
        if ((authorized_party is not None
             and authorized_party != self.settings.client_id)
                or (len(audiences) > 1 and authorized_party is None)):
            raise OIDCAuthError("invalid_authorized_party")
        if payload.get("iss") != self.settings.issuer_url:
            raise OIDCAuthError("invalid_issuer")
        if not isinstance(payload.get("nonce"), str) or not hmac.compare_digest(
            payload["nonce"], nonce
        ):
            raise OIDCAuthError("invalid_nonce")
        return payload

    def _get_metadata(self) -> dict:
        with self._metadata_lock:
            if self._metadata is not None and self._metadata_expires_at > time.time():
                return self._metadata
            issuer = _validate_endpoint(
                self.settings.issuer_url,
                self.settings.allow_private_issuer,
                issuer=True,
            )
            metadata_url = urlunsplit((
                issuer.scheme, issuer.netloc,
                issuer.path.rstrip("/") + "/.well-known/openid-configuration",
                "", "",
            ))
            metadata = self._request_json(metadata_url)
            if metadata.get("issuer") != self.settings.issuer_url:
                raise OIDCAuthError("issuer_mismatch")
            for endpoint_name in (
                "authorization_endpoint", "token_endpoint", "jwks_uri"
            ):
                endpoint = _validate_endpoint(
                    metadata.get(endpoint_name, ""),
                    self.settings.allow_private_issuer,
                    allow_query=endpoint_name == "authorization_endpoint",
                )
                _check_network_target(
                    endpoint.hostname, self.settings.allow_private_issuer
                )
            algorithms = metadata.get("id_token_signing_alg_values_supported")
            if (not isinstance(algorithms, list)
                    or not set(algorithms).intersection(
                        _ALLOWED_ID_TOKEN_ALGORITHMS
                    )):
                raise OIDCAuthError("no_supported_signing_algorithm")
            self._metadata = metadata
            self._metadata_expires_at = time.time() + 300
            return metadata

    def _request_json(
        self,
        url: str,
        *,
        method: str = "GET",
        data: dict | None = None,
        headers: dict | None = None,
        auth: tuple[str, str] | None = None,
    ) -> dict:
        try:
            response = self._http.request(
                method,
                url,
                data=data,
                headers=headers,
                auth=auth,
                timeout=(3, 15),
                allow_redirects=False,
                stream=True,
            )
            with response:
                if 300 <= response.status_code < 400 or not response.ok:
                    raise OIDCAuthError("provider_request_failed")
                content_type = response.headers.get("Content-Type", "").lower()
                if "json" not in content_type:
                    raise OIDCAuthError("provider_response_invalid")
                body = bytearray()
                for chunk in response.iter_content(8192):
                    body.extend(chunk)
                    if len(body) > _MAX_RESPONSE_BYTES:
                        raise OIDCAuthError("provider_response_too_large")
                value = json.loads(body)
                if not isinstance(value, dict):
                    raise OIDCAuthError("provider_response_invalid")
                return value
        except OIDCAuthError:
            raise
        except Exception as error:
            log.debug("OIDC provider request failed (%s)", type(error).__name__)
            raise OIDCAuthError("provider_unavailable") from None


def safe_return_to(raw: str | None) -> str:
    value = str(raw or "")
    if (not value or len(value) > 2048 or not value.startswith("/")
            or value.startswith("//") or "\\" in value
            or any(ord(char) < 32 for char in value)):
        return "/"
    parts = urlsplit(value)
    if parts.scheme or parts.netloc or not parts.path.startswith("/"):
        return "/"
    return urlunsplit(("", "", parts.path, parts.query, parts.fragment))


def _parse_set(raw: str) -> set[str]:
    return {
        item.lower()
        for item in re.split(r"[,;\s]+", raw.strip())
        if item
    }


def _parse_https_url(raw: str):
    try:
        parsed = urlsplit(raw)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username
                or parsed.password or parsed.query or parsed.fragment):
            raise ValueError("not an HTTPS URL")
        return parsed
    except Exception:
        raise OIDCAuthError("url_invalid") from None


def _validate_endpoint(
    raw: str,
    allow_private: bool,
    issuer: bool = False,
    allow_query: bool = False,
):
    try:
        parsed = urlsplit(str(raw))
        valid_http = allow_private and parsed.scheme == "http"
        if ((parsed.scheme != "https" and not valid_http) or not parsed.hostname
                or parsed.username or parsed.password or parsed.fragment):
            raise ValueError("unsafe URL")
        if issuer and parsed.query:
            raise ValueError("issuer query")
        if not issuer and parsed.query and not allow_query:
            raise ValueError("endpoint query")
        return parsed
    except Exception:
        raise OIDCAuthError("endpoint_invalid") from None


def _check_network_target(host: str, allow_private: bool) -> None:
    try:
        addresses = {
            ipaddress.ip_address(result[4][0].split("%", 1)[0])
            for result in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        }
    except Exception:
        raise OIDCAuthError("provider_host_unavailable") from None
    if not addresses:
        raise OIDCAuthError("provider_host_unavailable")
    if not allow_private and any(not address.is_global for address in addresses):
        raise OIDCAuthError("provider_private_address_blocked")
