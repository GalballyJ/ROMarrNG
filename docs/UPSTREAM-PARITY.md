# Why ROMarrNG is maintained

**Comparison checked:** 2026-10-12. The upstream baseline is
[BlizzHacker/romarr `main` at `31fefb0330e995c00350546d1470e6dcfa0fe117`](https://github.com/BlizzHacker/romarr/commit/31fefb0330e995c00350546d1470e6dcfa0fe117),
which reports ROMarr v1.1.0. ROMarrNG's last upstream merge before this review
is `c9c2b940484a32073d46ddadee8998b69bf86336` (merging upstream `06378a70`).
Recheck these references as either project changes. The detailed
[implementation report](UPSTREAM_IMPLEMENTATION_REPORT.md) and
[item-by-item audit](UPSTREAM_AUDIT.md) record the work against this snapshot.

## Why we keep a fork

ROMarr is useful as a standalone game and ROM manager. ROMarrNG is the
Snapetech-maintained distribution that SeerrNG can integrate with and that
ships fork-owned additions. We forked instead of pointing SeerrNG at the
existing upstream because the generic external-request API in the inspected
upstream accepts a name and platform, assigns its own request ID, and supports
listing/current-request polling. SeerrNG needs a stable contract across
catalog, request ownership, lifecycle, and delivery so it can correlate its
own request records and safely give requesters access to acquired files.

The source boundary matters: upstream already has a generic request API and
DAT-related processing. ROMarrNG does not claim to have invented those base
features. It adds the SeerrNG-specific contract and a fork-maintained DAT
catalog and game-asset delivery path. Most of the ordinary search, acquisition,
library, and operator experience is shared with ROMarr upstream.

## What ROMarrNG adds

### Standalone

- Maintained ROMarrNG releases, container images, and deployment packages,
  including the Snapetech Unraid templates.
- A DAT catalog and game-asset handling maintained alongside the NG app. These
  give the integrated catalog and delivery routes their game-specific source
  data and artwork while ROMarrNG remains independently usable.
- Ongoing fixes and operational changes in the NG distribution. Consult the
  [release history](../CHANGELOG.md) for shipped changes; this guide describes
  the current maintained boundary, not every fork commit.

### Used with SeerrNG

- A versioned capability handshake and dedicated authenticated integration.
- Game catalog search and detail using stable IGDB identities, plus the
  fork-maintained DAT catalog.
- Caller-owned external request IDs for idempotent correlation with SeerrNG,
  request status and lifecycle actions, and library lookup.
- Authenticated, request-scoped asset streaming for the acquired game files.

The current route and payload details live in the
[SeerrNG integration guide](SEERRNG-INTEGRATION.md). The parent project already
offers basic generic request submission and polling, so the differentiator is
the stable SeerrNG contract and its delivery boundary, not the existence of
any external-request endpoint.

## What would let us stop maintaining ROMarrNG

SeerrNG could use upstream ROMarr directly when upstream provides an
equivalent versioned contract for capability negotiation, stable caller-owned
request identity, catalog lookup, request status and actions, library state,
and authenticated request-scoped asset delivery. SeerrNG must support that
upstream contract or an adapter, and the current DAT catalog / asset behavior
and any other ROMarrNG-only capability it depends on must be upstream or no
longer required. We should then confirm the upstream release and migration
path, security maintenance, and the supported deployment targets before
changing the dependency.

Review this page when syncing upstream, changing the SeerrNG API contract, or
adding a new fork-owned standalone capability. Record the upstream commit
reviewed so claims stay time-bounded.
