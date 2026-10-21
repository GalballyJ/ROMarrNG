from romarr.oidc import OIDCSettings, oidc_provider_presentation, oidc_state_cookie_name
from romarr.ui import login_page


def test_provider_presentation_is_allowlisted_and_case_insensitive():
    assert oidc_provider_presentation(" Microsoft-Entra ") == (
        "Microsoft Entra ID",
        "microsoft",
        "https://learn.microsoft.com/en-us/entra/identity-platform/v2-protocols-oidc",
    )
    assert oidc_provider_presentation('<svg/onload="alert(1)">') == (
        "identity provider",
        "generic",
        "https://openid.net/developers/how-connect-works/",
    )
    assert oidc_provider_presentation("apple-sign-in") == (
        "Apple",
        "apple",
        "https://developer.apple.com/documentation/signinwithapple/configuring-your-environment-for-sign-in-with-apple",
    )


def test_major_provider_presentation_catalog():
    assert oidc_provider_presentation("fusionauth") == (
        "FusionAuth", "fusionauth", "https://fusionauth.io/docs/lifecycle/authenticate-users/oauth/",
    )
    assert oidc_provider_presentation("onelogin") == (
        "OneLogin", "onelogin", "https://developers.onelogin.com/docs/openid-connect/connect-to-onelogin/",
    )
    assert oidc_provider_presentation("pingone") == (
        "PingOne", "pingone", "https://docs.pingidentity.com/pingone/applications/p1_edit_application_oidc.html",
    )
    assert oidc_provider_presentation("jumpcloud") == (
        "JumpCloud", "jumpcloud", "https://jumpcloud.com/support/sso-with-oidc",
    )

def test_provider_hint_is_display_only_and_login_uses_local_icon():
    settings = OIDCSettings.from_env({"ROMARR_OIDC_PROVIDER": "keycloak"})
    assert settings.provider == "keycloak"
    assert settings.configured is False

    page = login_page(claimed=True, oidc_enabled=True, oidc_provider="keycloak")
    assert "Continue with Keycloak" in page
    assert "/oidc-provider-icons.svg#oidc-keycloak" in page
    assert "https://www.keycloak.org/docs/latest/server_admin/" in page


def test_oidc_state_cookies_are_isolated_per_transaction():
    first = oidc_state_cookie_name("first-flow")
    second = oidc_state_cookie_name("second-flow")

    assert first.startswith("romarr_oidc_state_")
    assert first != second
    assert len(first) == len("romarr_oidc_state_") + 32
