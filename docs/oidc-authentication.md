# OIDC authentication

ROMarr supports server-side OpenID Connect sign-in using the authorization
code flow with PKCE for ordinary providers. Apple uses its documented form-post
flow without PKCE. A successful login creates ROMarr's existing signed,
HttpOnly session cookie. Provider access and ID tokens are not stored in the
browser or in ROMarr's state file. Password, API-key, and configured
ForwardAuth login remain available.
This adapter follows the [shared cross-project OIDC contract](https://github.com/snapetech-org/seerrng/blob/main/docs/maintainers/oidc-cross-project-template.md).
The shared [provider catalog](https://github.com/snapetech-org/seerrng/blob/main/docs/maintainers/oidc-provider-catalog.md)
lists the branded IDs, official setup pages, issuer examples, and scope/claim
notes. The provider hint affects only the login button and its local setup
link; the configured issuer remains authoritative.

## Configure the provider

Register a confidential web client with the identity provider and set the
following variables. The callback URI must exactly match the value registered
at the provider and must use HTTPS:

```ini
ROMARR_OIDC_ISSUER_URL=https://auth.example.lan/application/o/romarr/
ROMARR_OIDC_CLIENT_ID=romarr
ROMARR_OIDC_CLIENT_SECRET=replace-me
ROMARR_OIDC_REDIRECT_URI=https://romarr.example.lan/auth/oidc/callback
ROMARR_OIDC_ALLOWED_EMAILS=operator@example.com
ROMARR_OIDC_ALLOWED_EMAIL_DOMAINS=
ROMARR_OIDC_ALLOW_ANY_VERIFIED_USER=0
ROMARR_OIDC_ALLOW_PRIVATE_ISSUER=0
ROMARR_OIDC_PROVIDER=authentik
```

`ROMARR_OIDC_PROVIDER` is an optional display hint. The branded presets are
`google`, `microsoft-entra`, `okta`, `auth0`, `keycloak`, `authentik`,
`zitadel`, `amazon-cognito`, `gitlab`, `fusionauth`, `onelogin`, `pingone`,
`jumpcloud`, and `apple-sign-in`. The hint changes only the local
login button label, icon, and provider setup link. Discovery and issuer checks
still use the configured issuer URL. Unknown values use generic OIDC branding.

## Sign in with Apple

Set `ROMARR_OIDC_ISSUER_URL` to exactly `https://appleid.apple.com`, use the
Apple Services ID as `ROMARR_OIDC_CLIENT_ID`, and set
`ROMARR_OIDC_CLIENT_SECRET` to the signed client-secret JWT. Register the exact
HTTPS callback `https://<public-host>/auth/oidc/callback`. ROMarr requests only
`openid email`, uses `response_mode=form_post`, and omits PKCE for Apple's
documented web flow. Apple may encode `email_verified` as a boolean or string;
only `true` is admitted. Rotate the JWT before its six-month maximum expiry.
See Apple's [environment setup](https://developer.apple.com/documentation/signinwithapple/configuring-your-environment-for-sign-in-with-apple)
and [web authorization flow](https://developer.apple.com/documentation/signinwithapple/incorporating-sign-in-with-apple-into-other-platforms).

All four core settings (issuer, client ID, secret, and redirect URI) must be
provided together. The issuer is compared exactly with the issuer in discovery
metadata. ROMarr requires a verified email, then admits the identity when its
normalized address is in `ROMARR_OIDC_ALLOWED_EMAILS`, its exact domain is in
`ROMARR_OIDC_ALLOWED_EMAIL_DOMAINS`, or `ROMARR_OIDC_ALLOW_ANY_VERIFIED_USER`
is explicitly enabled. Address and domain entries are comma, semicolon, or
whitespace separated. An empty allowlist denies all users by default.

ROMarr currently has one operator account and no per-user role model. Each
admitted OIDC identity therefore receives that existing full operator session.
Provider group claims do not change privileges, and ROMarr does not associate
an OIDC identity with a password account by email. The local password and API
key remain recovery paths.

For an identity provider hosted on a private network, set
`ROMARR_OIDC_ALLOW_PRIVATE_ISSUER=1`. This also permits a private callback host;
the callback itself must still be HTTPS. Without that opt-in, provider
discovery, token, key, and user-info endpoints resolving to non-public
addresses are rejected. Provider requests do not follow redirects and have
bounded time and response size.

## Provider flow

The login button starts a one-time state and nonce transaction, binds it to a
distinct HttpOnly browser cookie, and sends an S256 PKCE challenge for ordinary
providers. Up to 16 attempts can be pending; another start is rejected until
one completes or expires. Apple uses a cross-site form callback without PKCE.
The callback checks the state, exchanges the authorization code server-side,
validates the ID token signature and required issuer, audience, lifetime, and nonce claims,
then confirms the verified email and issues the local ROMarr session. The
return path is restricted to a local path. A failed sign-in returns to the
login screen without exposing provider errors or tokens.

The state transaction is held in process memory for ten minutes. Restarting
ROMarr invalidates pending OIDC callbacks; start a fresh login after a restart.
The callback accepts ordinary GET responses and Apple's URL-encoded POST
response, so reverse proxies must preserve the request method and form body.

## Enable, verify, and recover

All four core settings—issuer, client ID, client secret, and redirect URI—must
be present together. Store the secret in the protected service environment or
deployment secret source, not in the browser, repository, or an issue. Register
only the exact public HTTPS URI ending `/auth/oidc/callback`; the value in
`ROMARR_OIDC_REDIRECT_URI` and the provider's callback entry must match.

An exact email or domain admission grants the existing full ROMarr operator
session. `ROMARR_OIDC_ALLOW_ANY_VERIFIED_USER=1` does the same for every
verified provider identity, so use it only when the provider itself limits
client access to the intended operators. ROMarr has no per-user role boundary
for OIDC; provider groups do not add one. Keep password/API-key or configured
ForwardAuth recovery working while testing.

After applying a provider or secret change, begin a new login. Pending
transactions live in process memory for ten minutes and a restart invalidates
them. Verify the expected operator session with an admitted account, verify an
unadmitted verified account is rejected, and exercise a non-OIDC recovery
method. To disable OIDC, remove the four core settings from the service
environment and redeploy; verify the local login route still works.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Redirect URI is rejected | Match the public HTTPS URL, port, path, and proxy prefix exactly against `ROMARR_OIDC_REDIRECT_URI`. |
| Issuer discovery or token exchange fails | Compare the configured issuer with discovery metadata exactly; check DNS, CA trust, endpoint reachability, and the explicit private-issuer opt-in if the IdP is internal. |
| Callback has missing/invalid state | Start a new login in the same browser and hostname. Check Secure cookie delivery, forwarded HTTPS/host headers, ten-minute expiry, and whether ROMarr restarted. |
| Verified user is denied | Confirm the provider returns an email and affirmative `email_verified`, then check normalized addresses/domains and separators. No configured admission list means deny-by-default. |
| Too many people receive operator access | Set `ROMARR_OIDC_ALLOW_ANY_VERIFIED_USER=0` and use exact address/domain admissions; inspect provider client assignment as a second boundary. |
| Apple fails on its return POST | Verify the Services ID, exact Apple issuer, callback, form-post cookie behavior, `openid email`, and unexpired signed client-secret JWT. |

For support, provide the ROMarr version, provider ID, redacted issuer host,
callback path, and timestamp. Remove secrets, codes, tokens, raw claims, and
complete callback query strings.
