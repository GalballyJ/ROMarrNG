#!/usr/bin/env python3
"""Guard the canonical GHCR namespace and stable alias publishing policy."""

from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
LEGACY_IMAGE = "ghcr.io/snapetech/romarrng"
CANONICAL_IMAGE = "ghcr.io/snapetech-org/romarrng"
INSTALL_SURFACES = (
    "README.md",
    "docker-compose.yml",
    "SECURITY.md",
    "docs/INSTALL.md",
    "docs/PROOF.md",
    "homeassistant/romarr/config.yaml",
    "packaging/unraid/romarrng.xml",
    "packaging/unraid/romarrng-browser.xml",
    "romarr/browser.py",
    "romarr/ecosystem.py",
    "tests/test_fork_image.py",
    "tests/test_browser_musl.py",
    "tests/test_brand.py",
)
STANDARD_ALIASES = ("latest", "main", "master", "stable")
BROWSER_ALIASES = (
    "browser",
    "main-browser",
    "master-browser",
    "latest-browser",
    "stable-browser",
)


def main() -> int:
    problems: list[str] = []
    workflow_path = ROOT / ".github/workflows/docker.yml"
    workflow = workflow_path.read_text()

    if 'tags: ["v*"]' not in workflow:
        problems.append("Docker workflow must publish version-tag builds for v* tags")
    for alias in STANDARD_ALIASES + BROWSER_ALIASES:
        expected = (
            "type=raw,value="
            + alias
            + ",enable=${{ github.ref_type == 'tag' }}"
        )
        configured = [
            line.strip()
            for line in workflow.splitlines()
            if line.strip().startswith(f"type=raw,value={alias},")
        ]
        if configured != [expected]:
            problems.append(f"Docker workflow must set {alias} only on version-tag builds")
    for obsolete in ("DOCKERHUB_", "docker.io/snapetech/romarrng"):
        if obsolete in workflow:
            problems.append(f"Docker workflow still contains obsolete publisher reference: {obsolete}")
    if "name=ghcr.io/${GITHUB_REPOSITORY,,}" not in workflow:
        problems.append("Docker workflow must publish to the current repository's GHCR package")
    if "group: docker-${{ startsWith(github.ref, 'refs/tags/v') && 'stable-releases' || github.run_id }}" not in workflow:
        problems.append("Version-tag builds must share a serialized stable-release queue")
    if "queue: max" not in workflow:
        problems.append("Docker workflow must preserve queued builds instead of replacing them")
    if "cancel-in-progress: false" not in workflow:
        problems.append("Docker workflow must not cancel earlier builds")
    if "python scripts/check_stable_image_tags.py" not in workflow:
        problems.append("Docker workflow must verify published aliases against the stable release")

    for name in INSTALL_SURFACES:
        path = ROOT / name
        content = path.read_text()
        if LEGACY_IMAGE in content:
            problems.append(f"{name} still refers to the retired GHCR namespace")
        if CANONICAL_IMAGE not in content:
            problems.append(f"{name} does not point to {CANONICAL_IMAGE}")

    if problems:
        print("Stable image alias policy failed:", file=sys.stderr)
        for problem in problems:
            print(f"- {problem}", file=sys.stderr)
        return 1

    print("Stable image alias policy is consistent with snapetech-org/romarrng.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
