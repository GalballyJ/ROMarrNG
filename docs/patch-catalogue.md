# Patch catalogue

ROMarrNG can list translation, ROM-hack, and improvement projects, let a SeerrNG user pick the exact version, prepare the patched file against the right base dump, and report when a project publishes a new version.

**Nothing is bundled.** Coverage is whatever you or a community catalogue provide. ROMarrNG never infers that a translation is complete from a file name; completeness comes only from the catalogue entry.

## Where projects come from

1. JSON files in `<data directory>/patch-catalog.d/*.json` (the directory containing `ROMARR_DATA`).
2. Optionally one `https` URL in the `patch_catalog_url` setting. It is fetched at most every 12 hours, limited to 4 MB, and entries from local files win over remote ones with the same id.

## File format

```json
{
  "schema": 1,
  "projects": [
    {
      "id": "example-translation",
      "name": "Example Translation Project",
      "kind": "translation",
      "language": "en",
      "status": "complete",
      "completeness": 1.0,
      "summary": "One or two sentences about what the patch does.",
      "author": "Project authors",
      "url": "https://example.org/project",
      "coverUrl": "https://example.org/cover.jpg",
      "differences": ["Restores cut dialogue", "Fixes the item menu"],
      "game": { "title": "Example Game", "platform": "gba", "catalogKey": "dat-<sha256>" },
      "versions": [
        {
          "id": "1.1",
          "version": "1.1",
          "releasedAt": "2024-05-01",
          "notes": "Fixes a crash in chapter 3.",
          "patchUrl": "https://example.org/patch-1.1.bps",
          "patchSha256": "<64 hex characters>",
          "patchFormat": "bps",
          "base": { "region": "Japan", "revision": "Rev 1", "sha1": "<40 hex>", "crc32": "<8 hex>" }
        }
      ],
      "latestVersionId": "1.1"
    }
  ]
}
```

Rules:

- `kind` is `translation`, `hack`, or `improvement`. `status` is `complete`, `partial`, `in-progress`, `abandoned`, or `unknown` (the default). `completeness` is optional and only shown when present.
- `platform` is a ROMarrNG platform slug. `catalogKey` is optional and, when set, ties the project to one DAT title.
- Every URL must be `https`. `patchSha256` is checked after download when given.
- `base.sha1` or `base.crc32` pins the exact dump an IPS patch applies to. UPS and BPS patches carry the CRC32 of the exact source and result, so they verify the base without any catalogue hash.

## What a request does

A SeerrNG request that names a project and version:

1. Finds the base game in your library, or acquires it first through the normal ROMarrNG flow. The base game alone never marks the request available.
2. Downloads the patch over `https` from a public address only, with a 32 MB limit.
3. Applies IPS, UPS, or BPS and verifies the checksums. If the base is not the dump the patch was made for, it tries other dumps of the same game and otherwise fails with `BASE_MISMATCH` instead of producing a wrong file.
4. Writes the patched file beside the base, in `Translations/` for translations and `Hacks/` otherwise. The original is never overwritten or removed.

Failure codes reported to SeerrNG: `BASE_MISSING`, `BASE_MISMATCH`, `BASE_UNSUPPORTED` (the base is a folder or archive), `PATCH_UNREACHABLE`, `PATCH_CORRUPT`, `PATCH_FORMAT`, `PATCH_UNKNOWN`, `PATCH_FAILED`.

## Endpoints

- `GET /api/integration/seerrng/v1/patches/search?q&platform&kind&language&completeOnly&catalogKey&limit&cursor`
- `GET /api/integration/seerrng/v1/patches/projects/{projectId}`
- `POST /api/integration/seerrng/v1/requests` accepts `selection: { "kind": "patch", "projectId", "versionId", "keepOriginal" }`.

The ping handshake reports `capabilities.patchCatalog: true`.
