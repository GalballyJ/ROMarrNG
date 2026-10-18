# Setup experience contract

Apply this contract to ROMarrNG's existing first-run claim screen, Settings
pages, status reporting, and [install guide](../INSTALL.md). ROMarrNG already
states what is missing in Settings instead of failing blank: an indexer is
needed to search, a compatible download client is needed to grab, and a game
library destination is optional when using a plain folder. The first-run
screen only claims the install and sets a password. Preserve that simple,
secure start.

## Product-specific flow

After the install is claimed, guide operators from the task they want to do:

1. **Find releases:** configure an existing Prowlarr, Torznab/Newznab source,
   or torrent RSS feed through the current indexer settings.
2. **Fetch releases:** select a supported download client or an existing
   direct/browser lane, then validate it through its current connection test.
3. **File the ROM:** choose a plain folder or an existing RomM, Gaseous, or
   Retrom library. Confirm the actual library root and the completed-download
   path reported by the client; explain that these paths must resolve inside
   the ROMarr container.
4. **Improve matching (optional):** introduce DAT verification, import lists,
   plugins, and streaming hosts only when the operator chooses those features.

Known environment and saved values may prefill the current settings forms, but
show their source and let the operator confirm paths. Never create a library
mount, move ROMs, start an import, or choose a remote-path mapping from a guess.
If no indexer or client is ready, keep browsing the UI possible and say which
task is blocked. Use the existing Settings status and setup-health surfaces to
resume later.

## Contract

- Reuse the claim endpoint, Settings pages, status diagnostics, and provider
  tests; do not create another settings model or acquisition wizard.
- Ask only for values required by the action the operator selected.
- Treat mount paths as deployment-specific data; require confirmation before
  saving or importing against them.
- Keep download and library paths distinct and explain the client's reported
  path rule in context.
- Make optional features opt-in and identify unsupported or unverified
  integrations honestly.
- Keep a failed check beside the field that needs repair and preserve all
  entered non-secret values.

The contract is for ROM discovery and filing. PC game acquisition and request
workflows belong to QuestarrNG and SeerrNG respectively.

## Implementation tasks

These tasks use ROMarrNG's existing Settings, status endpoints, and install
guide; they do not add another onboarding route.

- [x] **R1 — P1: Turn blocked search and grab empty states into direct next
  actions.** In `romarr/ui.py`, update the existing indexer and download-client
  empty states (including the messages around the indexer and download-client
  lists) to identify the specific blocked action and link to its existing
  Settings form. Use the current `/api/v1/indexer`,
  `/api/v1/downloadclient`, and system-status results.
  **Done when:** “no indexer” explains that release search is unavailable and
  opens indexer settings; “no compatible client” explains that grabbing is
  unavailable and opens client settings; browsing and local-library features
  remain usable.

- [x] **R2 — P1: Put the two required path values beside the action that uses
  them.** In the existing download-client and library forms in
  `romarr/ui.py`, show the completed-download path reported by the client
  next to the destination library root, using the path rules already enforced
  by `romarr/app.py` and documented in `docs/INSTALL.md`.
  **Done when:** the operator can compare the exact container paths before
  grabbing or importing; mismatches show the existing actionable path error;
  no mount, mapping, or library root is guessed or created.

- [x] **R3 — P2: Keep matching and network extensions out of the core path.**
  In the current Settings descriptions and `docs/INSTALL.md`, identify DAT
  verification, import lists, plugins, streaming hosts, and other enrichment
  features as optional follow-up tasks, each linked from its existing page.
  **Done when:** a new operator can search, grab, and file a ROM without
  configuring those optional features, and unsupported integrations are still
  labeled accurately.
