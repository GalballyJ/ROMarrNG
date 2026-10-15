# Release-note fragments

For any user-facing change, add one structured fragment under `release-notes/` describing it. A
single fragment may cover related user-facing changes in the same pull request. Keep shipped fragments unchanged. Release preparation
adds these fragments to `CHANGELOG.md`; the tag workflow includes them in the
GitHub Release body and ROMarrNG announcement in the SeerrNG Discord channel.

Use a short, user-facing description rather than an implementation detail:

```md
---
category: fixed
audience: users, operators
area: library
action: none
breaking: false
---
Library scans now retain cached metadata during a short outage, so existing titles remain visible while the upstream service recovers.
```

The frontmatter captures context that can be lost from a commit message:

- `category`: `added`, `changed`, `fixed`, `security`, `removed`, or
  `deprecated`.
- `audience`: `users`, `operators`, or `users, operators`.
- `area`: a 2-32 character lowercase slug, such as `library` or
  `release-pipeline`.
- `action`: the required upgrade or operating step, or `none` when no action
  is needed.
- `breaking`: `true` or `false`; breaking changes must include an action.

Keep the body between 30 and 400 characters, start with a capitalized
sentence, and end with punctuation. Describe what changes for the person
running or using ROMarrNG. Do not paste commit messages, logs, or
implementation-only details.

Fragments are append-only after release. Before the version tag, you may refine
an upcoming fragment; after tagging, add a new file rather than editing the
shipped history. Preview a pull request's rendered notes with:

```bash
python scripts/release_notes.py preview --base origin/main --head HEAD
```

For internal-only work, no fragment is needed. In a pull request, either select the internal-only
option in the template or put `release-note: none` on its own line in the description. When a
direct push or merge check reads commit messages, put the same marker on its own line in the
commit message.

When preparing a release, update `romarr/app.py` to the release version, then
generate and prepend its changelog section from the fragments since the prior
tag:

```bash
VERSION=0.12.3
PREVIOUS_TAG=v0.12.2
python scripts/release_notes.py prepare \
  --version "$VERSION" \
  --date 2026-10-02 \
  --previous-tag "$PREVIOUS_TAG" \
  --head HEAD
python scripts/release_notes.py check-changelog-tags
```

The history check starts at `v0.10.0`, ROMarrNG's first GitHub Release; older
repository tags predate the published release history.

Use the actual next version, previous stable tag, and release date. Commit the
version and changelog preparation before creating the matching `v$VERSION`
tag. The tag workflow publishes the release and sends
the same release notes to Discord. `DISCORD_RELEASE_WEBHOOK` in the ROMarrNG
repository must point to the same webhook as SeerrNG. The release-preparation commit is internal-only and needs no fragment. Use the
internal-only template option or the PR marker, and include the commit marker when
the main-branch check reads the squash-merge commit body.
