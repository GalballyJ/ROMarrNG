"""SECURITY.md makes claims. These check they are still true.

A security document that drifts from the code is worse than none: it is read
as a guarantee and believed. Every claim in SECURITY.md that can be checked
mechanically is checked here, so the document fails the build rather than
quietly becoming fiction.
"""

from __future__ import annotations

import pathlib
import re

import pytest

from romarr import auth as auth_module
from romarr.app import ROMarr, make_handler

SECURITY = pathlib.Path(__file__).resolve().parents[1] / "SECURITY.md"


@pytest.fixture(scope="module")
def doc() -> str:
    return SECURITY.read_text(encoding="utf-8")


def test_the_document_exists_and_says_how_to_report(doc):
    assert "security/advisories" in doc
    assert "Reporting a vulnerability" in doc


def test_the_documented_open_paths_are_the_actual_open_paths(doc, tmp_path):
    """The list in SECURITY.md is the one readers rely on."""
    handler = make_handler(ROMarr({"ROMARR_DATA": str(tmp_path / "s.json")}))
    actual = set(handler.OPEN_PATHS)
    # `/link` was added with invitation links: the person opening one is
    # somebody else's operator with no account here. It is on this list
    # because it is a CONSTANT -- see the guarantee asserted just below.
    assert actual == {"/", "/login", "/link", "/api/health", "/api/v1/login",
                      "/auth/oidc/login", "/auth/oidc/callback",
                      "/oidc-provider-icons.svg",
                      "/api/v1/setup",
                      "/api/v1/connect/steam/return",
                      "/api/v1/peer/accept", "/api/v1/peer/shelf",
                      "/api/v1/peer/netplay"}, (
        "the set of unauthenticated routes changed; SECURITY.md lists them")
    for path in actual:
        assert path in doc, f"{path} answers without a credential and is undocumented"
    # The prose counts them, and read "five" while the table listed nine for
    # long enough that nobody noticed. A number in a security document is a
    # claim like any other.
    spelled = {5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine",
               10: "ten", 11: "eleven", 12: "twelve", 13: "thirteen"}[len(actual)]
    assert f"Exactly {spelled} routes answer without a credential" in doc


def test_the_invitation_landing_page_is_a_constant(doc):
    """SECURITY.md's argument for `/link` being open is that there is nothing
    behind it to ask. If it ever grows a parameter, that argument is void."""
    from romarr.ui import link_page
    assert link_page() == link_page()
    import inspect
    assert not inspect.signature(link_page).parameters, (
        "/link is on the open-path list because it answers with a constant; "
        "a parameter makes it something that can be asked a question")
    assert "constant page" in doc


def test_scrypt_parameters_match_what_is_documented(doc):
    assert (auth_module._SCRYPT_N, auth_module._SCRYPT_R,
            auth_module._SCRYPT_P) == (2 ** 14, 8, 1)
    assert "N=2^14, r=8, p=1" in doc


def test_the_session_cookie_flags_match(doc):
    app = pathlib.Path(auth_module.__file__).with_name("app.py")
    source = app.read_text(encoding="utf-8")
    cookie = re.search(r"SESSION_COOKIE\}=\{token\};([^\"]*)", source)
    assert cookie, "the session cookie is no longer set where expected"
    flags = cookie.group(1)
    assert "HttpOnly" in flags and "SameSite={same_site}" in flags
    assert 'same_site = "Lax" if redirect_to else "Strict"' in source
    assert "secure_cookie = secure_cookie or force_secure" in source
    assert "HttpOnly" in doc and "SameSite=Strict" in doc


def test_a_plugin_still_does_not_inherit_romarr_credentials(doc):
    """Holds whether or not seccomp is available -- the environment
    allowlist and the sandbox are separate boundaries."""
    from romarr import hub
    assert "ROMARR_API_KEY" not in hub._ENV_PASSTHROUGH
    assert "confinement is real but partial" in doc.lower()
    assert "ROM_HUB_ALLOW_UNSANDBOXED" in doc, (
        "the sandbox is disabled; the document must keep saying so")


def test_the_unauthenticated_health_response_is_one_bit(tmp_path):
    """It used to hand out library paths and client URLs for free."""
    service = ROMarr({"ROMARR_DATA": str(tmp_path / "s.json"), "ROMARR_API_KEY": "k"})
    report = service.health_report() if hasattr(service, "health_report") else None
    if report is None:
        pytest.skip("no health_report to inspect directly")
    assert set(report) <= {"ok"}


def test_the_document_admits_what_is_not_protected(doc):
    """The section that makes the rest credible."""
    assert "What is not protected" in doc
    for admission in ("No protection from a compromised shared kernel",
                      "No encryption at rest",
                      "No multi-user model", "not a security control"):
        assert admission in doc
    assert "Landlock restricts" in doc


def test_workflow_checkouts_do_not_persist_credentials():
    workflow = pathlib.Path(__file__).resolve().parents[1] / ".github/workflows/docker.yml"
    lines = workflow.read_text(encoding="utf-8").splitlines()
    checkout_lines = [
        index for index, line in enumerate(lines)
        if "uses: actions/checkout@" in line
    ]
    assert checkout_lines
    for index in checkout_lines:
        step = lines[index:index + 7]
        assert any("persist-credentials: false" in line for line in step), (
            "candidate-controlled workflow code could read the checkout token "
            "from .git/config"
        )


def test_versions_at_or_below_v0_7_0_are_called_out(doc):
    """They have no authentication at all. Anyone reading this needs to know."""
    assert "v0.7.0" in doc
    assert "no authentication" in doc.lower()
