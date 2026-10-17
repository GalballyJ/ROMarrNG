# Why ROMarrNG is maintained

**Current comparison checked:** 2026-10-16. Upstream **BlizzHacker/romarr main**
is at [`4ad0ada8e72cbe0e7fcab48fab6cf17d5beb6441`](https://github.com/BlizzHacker/romarr/commit/4ad0ada8e72cbe0e7fcab48fab6cf17d5beb6441),
which bumped ROMarr to v1.6.0. ROMarrNG's last upstream merge is
`c9c2b940484a32073d46ddadee8998b69bf86336` (upstream `06378a70`).

The 48-item upstream issue/PR audit remains a separate historical snapshot from
2026-10-12 against upstream `31fefb0330e995c00350546d1470e6dcfa0fe117`.
It records the issue queue and work against that snapshot; this page compares
the current contract against upstream v1.6.0. See the
[item-by-item audit](UPSTREAM_AUDIT.md) and
[implementation report](UPSTREAM_IMPLEMENTATION_REPORT.md).

The source comparison uses upstream's pinned
[`app.py`](https://github.com/BlizzHacker/romarr/blob/4ad0ada8e72cbe0e7fcab48fab6cf17d5beb6441/romarr/app.py)
and
[`ui.py`](https://github.com/BlizzHacker/romarr/blob/4ad0ada8e72cbe0e7fcab48fab6cf17d5beb6441/romarr/ui.py),
alongside the ROMarrNG
[SeerrNG integration contract](SEERRNG-INTEGRATION.md) and
[localization notes](localization-roadmap.md).

## Why we keep a fork

ROMarr is useful as a standalone game and ROM manager. ROMarrNG is the
Snapetech-maintained distribution that SeerrNG can integrate with and that ships
fork-owned additions.

Upstream now has a generic external-request API. It accepts a game name and
platform, creates an upstream-owned request ID, and supports listing requests
and polling the latest request. Its integration info reports the app version
and basic resume and multi-platform support. Those are useful building blocks,
but SeerrNG needs a contract for catalog identity, request ownership and
lifecycle, and safe file delivery.

The source boundary matters: upstream already has a generic request API and
DAT verification during import. ROMarrNG does not claim to have invented those
base features. It adds a versioned SeerrNG contract, a fork-maintained DAT
catalog, request-scoped game-asset delivery, and DAT-verdict reporting for
delivered files. Most ordinary search, acquisition, library, and operator
behavior remains shared with upstream.

## What ROMarrNG adds

### Standalone

- Maintained ROMarrNG releases, container images, and deployment packages,
  including the Snapetech Unraid templates.
- A browser-local interface-language selector for English and twelve additional
  languages. The current catalog covers 1,314 app-owned strings across the UI.
  Arabic labels carry right-to-left metadata; full right-to-left layout support
  remains under review.
- Separate browser-local regional formatting for dates, times, counts, ratings,
  scores, and file sizes. It does not change interface language or ROM
  translation policy.
- A DAT catalog and game-asset handling maintained alongside the NG app. These
  give the integrated catalog and delivery routes their game-specific source
  data while ROMarrNG remains independently usable.
- Ongoing fixes and operational changes in the NG distribution. Consult the
  [release history](../CHANGELOG.md) for shipped changes.

### Used with SeerrNG

- A versioned capability handshake and a dedicated integration credential.
- IGDB catalog search and detail when configured, plus the fork-maintained DAT
  catalog with stable entry keys and matched platform identity.
- Caller-owned external request IDs for idempotent correlation, per-request
  status and lifecycle actions, and bounded library lookup.
- Authenticated, request-scoped asset listing and streaming. Asset IDs are
  opaque, paths stay server-side, and streams support byte ranges.
- An `assetDatVerification` capability that reports `datVerified` as `true`,
  `false`, or `null`, keeping byte verification distinct from library placement
  and indexing.

## Upstream exit matrix

At the checked upstream head, the generic external-request API is present, but
the rows below are gaps or partial matches for SeerrNG's current contract.

| Capability | ROMarrNG / SeerrNG today | Upstream at `4ad0ada` | Cutover condition |
| --- | --- | --- | --- |
| Handshake and access | Versioned capability handshake and a dedicated integration key; the main API key remains compatible. | Generic `/api/v1/integration/info` reports the product version and basic resume/multi-platform flags; it has no SeerrNG contract version or dedicated integration credential. | Provide equivalent capability negotiation and credential scope, or maintain and test an adapter with the same boundary. |
| Catalog identity | IGDB search/details when configured, plus a DAT catalog with stable keys and matched platform identity. | No integration catalog routes for these identities. | Provide equivalent catalog endpoints and stable IDs, or keep the catalog service/adapter SeerrNG needs. |
| Request ownership and lifecycle | Caller-owned `externalRequestId`, idempotent creation, per-request status, retry/cancel actions, and recovery after restart. | `POST /api/v1/integration/requests` accepts `name` and `platform`, creates an upstream-owned ID, and offers list/latest-request polling; no caller-owned ID or per-request lifecycle routes. | Support caller-owned IDs and equivalent per-request status, recovery, retry, and cancel behavior. |
| Library lookup and file delivery | Bounded library lookup; request-scoped assets use opaque IDs, stay beneath the configured library root, and stream with byte ranges without returning local paths. | Generic request status can carry imported path strings; there is no request-scoped, path-free streaming contract. | Add equivalent lookup and secure asset list/stream routes, including path containment and range requests. |
| DAT verdict on delivery | `assetDatVerification` advertises `datVerified` as `true`, `false`, or `null`; placement, indexing, and byte verification remain separate states. | DAT import verification exists, but the integration API does not expose an asset-verification verdict. | Expose an equivalent delivery verdict, or remove SeerrNG's dependency on it. |

SeerrNG must implement the selected upstream contract or a maintained adapter,
then prove request correlation, interrupted-handoff handling, library lookup,
and byte delivery against a released upstream version. Similar endpoint names
alone do not establish compatibility.

## Standalone parity to carry forward

These additions are independent of SeerrNG's integration API. If ROMarrNG is
replaced as the standalone application, decide whether upstream adopts them or
the migration accepts losing them.

| Feature | ROMarrNG today | Upstream at `4ad0ada` | Decision before cutover |
| --- | --- | --- | --- |
| Interface language | Browser-local English plus twelve translated locales; 1,314 app-owned strings cover navigation, settings, help, workflows, diagnostics, and app-owned status text. Arabic labels have RTL metadata; full RTL layout is not claimed. | The inspected single-file UI has no locale catalog or language selector. | Port equivalent localization or document and accept the user-visible loss. |
| Regional formatting | Separate browser-local choice for counts, ratings, scores, sizes, dates, and times; browser defaults are available. | Uses browser formatting in places but has no saved regional-format preference. | Port the setting or accept the behavior change. |
| Release and migration path | ROMarrNG maintains its image tags, Unraid templates, fork-specific settings, and release channel. | Upstream v1.6.0 has its own image and release channel. | Test a supported release, configuration/state migration, target architectures, permissions, authentication, and rollback before switching. |

## Retirement gate

Retire the fork only after the required integration rows have an equivalent
implementation or tested adapter; SeerrNG has switched and passed its request,
recovery, and delivery checks; standalone parity choices are accepted; and a
supported upstream release has a tested migration and rollback path.

Review this page when syncing upstream, changing the SeerrNG API contract, or
adding a new fork-owned standalone capability. Record the upstream commit
reviewed so claims stay time-bounded.
