---
category: fixed
audience: operators
area: containers
action: none
breaking: false
---
The standard `:latest`, `:main`, `:master`, and `:stable` tags now track the latest versioned release in `ghcr.io/snapetech-org/romarrng`. Browser aliases track the matching browser release. Main-branch builds keep commit-specific `sha-*` tags, and CI checks that each rolling alias matches the stable release manifest.
