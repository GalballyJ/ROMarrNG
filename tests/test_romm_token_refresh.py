"""RomM 5.3.1 reports an expired password-grant token as HTTP 500."""

from __future__ import annotations

import base64
import json
import time

from romarr.clients import Romm, RommConfig


class Response:
    def __init__(self, status, body=None):
        self.status_code = status
        self._body = body or {}
        self.ok = status < 400

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(response=self)


def jwt(expiry):
    encode = lambda value: base64.urlsafe_b64encode(
        json.dumps(value).encode()).rstrip(b"=").decode()
    return f"{encode({'alg': 'HS256'})}.{encode({'exp': expiry})}.sig"


class Romm531Session:
    def __init__(self, *, broken=False, reject_tokens=False, lifetimes=None):
        self.broken = broken
        self.reject_tokens = reject_tokens
        self.lifetimes = list(lifetimes or [])
        self.valid = set()
        self.issued = 0
        self.gets = []

    def post(self, url, **kwargs):
        assert url.endswith("/api/token")
        self.issued += 1
        expiry = (self.lifetimes.pop(0) if self.lifetimes
                  else time.time() + 1800)
        token = jwt(expiry)
        if not self.reject_tokens:
            self.valid.add(token)
        return Response(200, {"access_token": token})

    def get(self, url, **kwargs):
        auth = (kwargs.get("headers") or {}).get("Authorization", "")
        self.gets.append((url, bool(auth)))
        if self.broken:
            return Response(500)
        if url.endswith("/api/heartbeat"):
            if auth and auth.split(" ", 1)[1] not in self.valid:
                return Response(500)
            return Response(200)
        if auth and auth.split(" ", 1)[1] not in self.valid:
            return Response(500)
        if not auth:
            return Response(401)
        return Response(200, {"total": 3, "items": []})


def client(session, **config):
    return Romm(RommConfig(base_url="http://romm", username="user",
                           password="password", **config), session)


def test_expired_token_that_returns_500_is_replaced_and_retried():
    session = Romm531Session()
    romm = client(session)
    assert romm.count() == 3

    # RomM starts returning 500 for the old bearer token instead of 401.
    session.valid.clear()
    assert romm.count() == 3
    assert session.issued == 2


def test_password_token_is_refreshed_before_its_jwt_expiry():
    session = Romm531Session(lifetimes=[time.time() + 10, time.time() + 1800])
    romm = client(session)
    romm.token()
    romm.token()
    assert session.issued == 2


def test_real_server_500_does_not_trigger_a_login_retry():
    session = Romm531Session(broken=True)
    romm = client(session)
    romm.token()
    response = romm._get("http://romm/api/roms", {}, 5)
    assert response.status_code == 500
    assert session.issued == 1


def test_fixed_operator_token_is_not_replaced_after_a_500():
    session = Romm531Session(broken=True)
    romm = Romm(RommConfig(base_url="http://romm", api_token="rmm_fixed"),
                session)
    response = romm._get("http://romm/api/roms", {}, 5)
    assert response.status_code == 500
    assert session.issued == 0
    assert len(session.gets) == 1


def test_a_refused_replacement_token_is_retried_only_once():
    session = Romm531Session(reject_tokens=True)
    romm = client(session)
    response = romm._get("http://romm/api/roms", {}, 5)
    assert response.status_code == 500
    assert session.issued == 2
    assert sum(url.endswith("/api/roms") for url, _ in session.gets) == 2
