#!/usr/bin/env python3
"""Check that rolling GHCR aliases match the latest published stable image."""

from __future__ import annotations

import argparse
import http.client
import json
import re
import ssl
import sys
from urllib.parse import quote, urlencode

IMAGE = "snapetech-org/romarrng"
RELEASES_PATH = "/repos/snapetech-org/ROMarrNG/releases/latest"
REGISTRY_TOKEN_PATH = "/token"
ACCEPT = ", ".join(
    (
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    )
)
STANDARD_ALIASES = ("latest", "main", "master", "stable")
BROWSER_ALIASES = (
    "browser",
    "main-browser",
    "master-browser",
    "latest-browser",
    "stable-browser",
)


def https_request(
    host: str,
    path: str,
    headers: dict[str, str],
    *,
    method: str = "GET",
) -> tuple[int, http.client.HTTPMessage, bytes]:
    # Callers use fixed GitHub/GHCR hosts and this context verifies certificates.
    # nosemgrep: python.lang.security.audit.httpsconnection-detected.httpsconnection-detected
    connection = http.client.HTTPSConnection(
        host, timeout=30, context=ssl.create_default_context()
    )
    try:
        connection.request(method, path, headers=headers)
        response = connection.getresponse()
        return response.status, response.headers, response.read()
    finally:
        connection.close()


def latest_release_version() -> str:
    status, _, body = https_request(
        "api.github.com",
        RELEASES_PATH,
        {
            "Accept": "application/vnd.github+json",
            "User-Agent": "ROMarrNG-stable-image-tag-check",
        },
    )
    if status != 200:
        raise RuntimeError(f"GitHub returned HTTP {status} for the latest release")
    release = json.loads(body)
    tag = release.get("tag_name", "")
    if not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", tag):
        raise RuntimeError(f"GitHub latest release has an invalid stable version tag: {tag!r}")
    return tag[1:]


def registry_token() -> str:
    query = urlencode(
        {
            "service": "ghcr.io",
            "scope": f"repository:{IMAGE}:pull",
        }
    )
    status, _, body = https_request(
        "ghcr.io",
        f"{REGISTRY_TOKEN_PATH}?{query}",
        {"User-Agent": "ROMarrNG-stable-image-tag-check"},
    )
    if status != 200:
        raise RuntimeError(f"GHCR returned HTTP {status} while issuing a pull token")
    payload = json.loads(body)
    token = payload.get("token") or payload.get("access_token")
    if not token:
        raise RuntimeError("GHCR did not return an anonymous pull token")
    return token


def manifest_digest(tag: str, token: str) -> tuple[str | None, str | None]:
    path = f"/v2/{IMAGE}/manifests/{quote(tag, safe='.-_')}"
    try:
        status, headers, _ = https_request(
            "ghcr.io",
            path,
            {
                "Accept": ACCEPT,
                "Authorization": f"Bearer {token}",
                "User-Agent": "ROMarrNG-stable-image-tag-check",
            },
            method="HEAD",
        )
    except OSError as error:
        return None, f"registry request failed: {error}"
    if status == 404:
        return None, "tag is missing"
    if status != 200:
        return None, f"registry returned HTTP {status}"
    digest = headers.get("Docker-Content-Digest")
    if not digest:
        return None, "registry response omitted Docker-Content-Digest"
    return digest, None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--version",
        help="stable release version (without v); defaults to GitHub's latest release",
    )
    args = parser.parse_args()

    version = args.version[1:] if args.version and args.version.startswith("v") else args.version
    if version is None:
        try:
            version = latest_release_version()
        except (OSError, TimeoutError, json.JSONDecodeError, RuntimeError) as error:
            print(f"Could not read the latest GitHub release: {error}", file=sys.stderr)
            return 2
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        print(f"Invalid version: {version!r}; expected MAJOR.MINOR.PATCH", file=sys.stderr)
        return 2

    try:
        token = registry_token()
    except (OSError, TimeoutError, json.JSONDecodeError, RuntimeError) as error:
        print(f"Could not obtain an anonymous GHCR pull token: {error}", file=sys.stderr)
        return 2

    pairs = [(tag, version) for tag in STANDARD_ALIASES]
    pairs.extend((tag, f"{version}-browser") for tag in BROWSER_ALIASES)
    problems: list[str] = []
    expected_tags = (version, f"{version}-browser")
    expected: dict[str, str | None] = {}
    for tag in expected_tags:
        digest, error = manifest_digest(tag, token)
        expected[tag] = digest
        if error:
            problems.append(f"{tag}: {error}")
        else:
            print(f"{tag}: {digest} (stable release)")

    for alias, release_tag in pairs:
        digest, error = manifest_digest(alias, token)
        if error:
            print(f"{alias}: MISMATCH ({error})")
            problems.append(f"{alias}: {error}")
        elif digest != expected[release_tag]:
            print(f"{alias}: {digest} != {release_tag} ({expected[release_tag] or 'missing'})")
            problems.append(f"{alias}: manifest differs from {release_tag}")
        else:
            print(f"{alias}: {digest} (matches {release_tag})")

    if problems:
        print(f"Stable image aliases do not all match v{version}:", file=sys.stderr)
        for problem in problems:
            print(f"- {problem}", file=sys.stderr)
        return 1
    print(f"All rolling aliases match the stable v{version} image in ghcr.io/{IMAGE}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
