# SnapeTech MCP

ROMarrNG does not run an MCP server inside the application. The shared
`snapetech-mcp` process uses ROMarrNG's SeerrNG catalog API over MCP stdio
transport. Its quickstart is in the sibling `snapetech-mcp/README.md`.

## Tools and API access

| MCP tool | ROMarrNG endpoint | Result |
| --- | --- | --- |
| `romarrng_status` | `GET /api/health` | Reachability only. |
| `romarrng_search_catalog` | `GET /api/integration/seerrng/v1/catalog/search-page` | Bounded IGDB search with cursor pagination and optional platform, genre, and year filters. |
| `romarrng_list_popular_catalog` | `GET /api/integration/seerrng/v1/catalog/popular-page` | Bounded popular-game page with optional filters. |
| `romarrng_list_catalog_platforms` | `GET /api/integration/seerrng/v1/catalog/platforms` | Projected IGDB platform names and IDs. |
| `romarrng_get_catalog_game` | `GET /api/integration/seerrng/v1/catalog/games/{igdbId}` | Bounded metadata for one validated IGDB ID. |
| `romarrng_list_dat_platforms` | `GET /api/v1/integration/catalog/dat/platforms` | Local DAT platform summary; no external catalog call. |
| `romarrng_search_dat_catalog` | `GET /api/v1/integration/catalog/dat/search-page` | Bounded search over the locally loaded DAT catalog. |
| `romarrng_browse_dat_catalog` | `GET /api/v1/integration/catalog/dat/browse-page` | Bounded alphabetic DAT catalog page. |
| `romarrng_get_dat_game` | `GET /api/v1/integration/catalog/dat/games/{catalogKey}` | Selected metadata for one validated DAT key. |

Use the dedicated SeerrNG integration key shown in **Settings → General**.
Configure `SNAPETECH_MCP_APPS=romarrng`,
`SNAPETECH_MCP_ROMARRNG_URL=<ROMarrNG base URL>`, and
`SNAPETECH_MCP_ROMARRNG_API_KEY=<integration key>` in the MCP host's protected
environment. The bridge sends the key in `X-Api-Key`. If
`ROMARR_SEERRNG_API_KEY` is set on ROMarrNG, use that pinned value.

## Credential and data boundaries

The integration key is limited to ROMarrNG's SeerrNG integration route family,
which also includes request creation, retry, cancel, and asset access. The MCP
adapter only calls the catalog GET route; the key is broader if used outside
this bridge. Keep it dedicated to the trusted local MCP process and rotate it
from ROMarrNG settings or the secret configuration if exposed.

IGDB search, popular pages, platform lookup, and game detail may call ROMarrNG's
configured provider. DAT tools read the app's local catalog and do not contact IGDB or
read ROM files. Results omit file paths, asset data, and acquisition actions.
Keep the process attached to a trusted local client and never expose its stdio
transport through a TCP bridge or reverse proxy.

## Competitor feature coverage

ROMarrNG focuses on game acquisition and import: catalog discovery,
indexer/download-client workflows, release scoring, post-processing, ROM library
imports, and SeerrNG request handoff. [RomM](https://github.com/rommapp/romm) is an adjacent self-hosted
library/player covering scans and metadata, platforms, collections, in-browser play,
save/state sync, ROM patching, sharing, and handheld clients. RomM's [API reference](https://docs.romm.app/5.4.0/developers/api-reference/)
includes ROM, platform, collection, save, state, device, stats, and audit surfaces;
those are not all ROMarrNG capabilities.

Snapetech MCP exposes filtered IGDB discovery/detail and the local DAT catalog. Request
status is excluded because the GET handler can reconcile and persist request state;
asset reads are also excluded. Download, retry, cancel, file delivery, import, and
filesystem access require a distinct write/data-access review.

**Confidence:** high for RomM's published library/API features; moderate for direct comparison because ROMarrNG and RomM have different product roles.

Source contract: `README.md`, `docs/SEERRNG-INTEGRATION.md`,
`romarr/auth.py`, and `romarr/openapi.py`.
