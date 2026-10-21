# ROMarrNG documentation

Use the [project README](../README.md) for the product overview, install
choices, configuration summary, and feature tour. This index points to the
maintained operator and contributor guides.

## Install and operate

- [Installation and operations](INSTALL.md): supported deployments, data paths,
  environment configuration, upgrades, backup, and rollback.
- [OIDC authentication](oidc-authentication.md): provider setup, exact callback,
  verified-email admission, operator-session behavior, recovery, Apple, and
  troubleshooting.
- [Localization roadmap](localization-roadmap.md): supported locales and
  remaining translation work.
- [Security scanning](security-scanning.md): local and hosted scan workflows.

## Integrate and understand

- [SeerrNG integration](SEERRNG-INTEGRATION.md): request, catalog, and
  download-delivery boundaries.
- [Upstream comparison](UPSTREAM-PARITY.md): the current fork baseline,
  ROMarrNG-specific changes, and criteria for returning to upstream.
- [Proof and claims](PROOF.md): source-backed evidence for product claims.
- [Federation protocol](FEDERATION-PROTOCOL.md): current federation behavior
  and boundaries.

## Shared OIDC references

- [Provider catalog](https://github.com/snapetech-org/seerrng/blob/main/docs/maintainers/oidc-provider-catalog.md): supported IDs, official provider setup pages, issuer examples, and claim caveats.
- [Cross-project implementation contract](https://github.com/snapetech-org/seerrng/blob/main/docs/maintainers/oidc-cross-project-template.md): shared protocol/security requirements and the per-app callback/session map.
- [OIDC rollout validation](https://github.com/snapetech-org/seerrng/blob/main/docs/maintainers/oidc-rollout-validation.md): automated checks and the live-provider testing boundary.
