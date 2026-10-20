#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

configured="$(git config --get core.hooksPath || true)"
if [[ -n "$configured" && "$configured" != ".githooks" ]]; then
  echo "core.hooksPath is already set to '$configured'; leaving it unchanged." >&2
  exit 2
fi

git config --local core.hooksPath .githooks
echo "Installed repository hooks from .githooks (pre-push checks stable GHCR aliases)."
