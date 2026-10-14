# Agent instructions - ROMarrNG

## Communication and authority

- Be direct, accurate, and explicit about what is unknown.
- For material claims or estimates with meaningful uncertainty, state confidence as high, moderate, low, or unknown. Skip labels for routine facts.
- Distinguish code changes, automated checks, visual inspection, and live service evidence.
- Preserve upstream attribution and follow the repository license and pull request template.
- Do not publish, merge, deploy, or create a release without maintainer authorization.

## Required project reading

- Consult relevant sections of README.md, docs/UPSTREAM-PARITY.md, docs/SEERRNG-INTEGRATION.md, and docs/PROOF.md when changing product behavior or documenting project claims.
- Consult docs/development/validation-engine.md before selecting or reporting tests.
- Read release-notes/README.md before preparing release notes or changing user-facing, security, or operational behavior and documentation.
- ROM Hub is the plugin factory. Plugin source belongs there; do not duplicate a plugin implementation in ROMarrNG.

## ROMarrNG behavior and safety boundaries

- These describe current contracts, not a ban on requested changes. When an authorized task deliberately changes a contract, update its docs and tests together while preserving security boundaries.
- ROMarrNG is a standalone game-library and acquisition application and a maintained fork of BlizzHacker/romarr. Treat upstream as a read-only reference and preserve its attribution.
- Keep the versioned SeerrNG catalog, request lifecycle, and scoped file-delivery contract aligned. Preserve external game identity and request correlation; do not broaden a request into an unrelated library or filesystem operation.
- Search, RSS, replacement grabs, and interactive selection share the core release scorer. Profile and blocklist settings affect selection; search diagnostics show raw scores and counts. Interactive candidate responses expose readable reasons, while other flows report scores or aggregate outcomes. Preserve rejection detail wherever a caller exposes it. Keep per-title backoff conservative and replacement attempts bounded so scheduled jobs do not overwhelm indexers or trackers.
- Platform aliases must resolve deterministically. Prefer the longest known alias, refuse unknown platforms, and do not guess a platform from a partial match.
- Preserve the DAT verdicts: verified means a match, bad dump means a known-size hash mismatch, and unknown is not a bad dump. Keep upgrade ordering as verified > unknown > bad dump: a verified dump may replace an unknown copy, and a valid unknown homebrew or translation may replace a known bad dump. Do not reject unknown releases as bad dumps.
- Archive extraction and import must remain path-safe. Tests use disposable libraries and download fixtures; never let a test write to live ROM libraries, real download folders, or user databases.
- Do not use live indexer accounts, public download sources, or release publishing endpoints in tests. Network-marked tests stay excluded unless the documented controlled setup is explicitly available.
- Do not change the application version merely to edit contributor instructions. Version and changelog preparation belong to the documented release workflow.

## Validation and evidence

- Local tests use Python 3.13, the configured pytest environment, and the trusted offline Linux bubblewrap launcher described in docs/development/validation-engine.md.
- For an unreviewed candidate, copy the trusted launcher from a reviewed revision outside the checkout and run both planning and tests through it. Do not run candidate validation configuration directly on the host.
- The launcher has no network access. The local suite uses pytest's configured exclusions and reports passed, skipped, failed, and deselected cases. A plan is discovery evidence, not a test pass; the local tests-only selection is intentionally refused.
- GitHub Actions supplies receipt-backed test and image checks. Pull requests,
  version tags, and manual runs outside main use hosted runners. Trusted main may
  use the restricted organization pool only when `TRUSTED_MAIN_RUNNERS_ENABLED`
  is `true`; otherwise it stays hosted. A local pytest pass does not establish
  runner, release artifact, or live integration behavior.
- Report the actual command, test counts, skips, exclusions, and unavailable prerequisites. Do not claim live behavior without live evidence.

## Release notes

Changes to user-facing behavior, security, operations, or documentation users rely on require a validated fragment under release-notes/. Fragments are append-only after release. Preview with python scripts/release_notes.py preview --base origin/main --head HEAD. For an internal-only PR, use release-note: none in both the PR description and the squash-merge commit body.
