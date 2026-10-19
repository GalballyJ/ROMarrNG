"""Translation, hack, and improvement patches as first-class, versioned things.

A fan translation is not a ROM. It is a *patch* made against one exact dump of
a game, published by a project that has versions, a completeness status and
sometimes a successor. Filenames cannot tell you any of that -- a file called
"... (T-En).gba" is not evidence that the translation is finished -- so this
module keeps the project, version and base-dump identity as data and prepares
the patched file itself, refusing when the base is not the dump the patch was
made for.

Three things live here, deliberately apart from the request plumbing:

  * `PatchCatalog`  reads project metadata from local JSON files and, if an
    operator opts in, one remote JSON catalogue. Nothing is bundled: coverage
    is whatever the operator or a community catalogue provides, and ROMarrNG
    says so rather than implying a complete index.
  * `apply_patch`   IPS, UPS and BPS appliers. UPS and BPS carry the CRC32 of
    the exact source and target, so they verify the base dump and the result
    without needing any hash from the catalogue.
  * `fetch_patch`   the one place a patch URL is downloaded: https only, public
    addresses only, size capped, and checked against the catalogue's SHA-256
    when one is given.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import logging
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger("romarr.patches")

CATALOG_SCHEMA = 1
KINDS = ("translation", "hack", "improvement")
STATUSES = ("complete", "partial", "in-progress", "abandoned", "unknown")
PATCH_FORMATS = ("ips", "bps", "ups")
MAX_PATCH_BYTES = 32 * 1024 * 1024
MAX_ROM_BYTES = 512 * 1024 * 1024
MAX_CATALOG_BYTES = 4 * 1024 * 1024
REMOTE_REFRESH_SECONDS = 12 * 3600
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:_.-]{0,127}$")
_HEX = re.compile(r"^[0-9a-fA-F]+$")


class PatchError(Exception):
    """A patch could not be fetched, matched or applied. The message is safe
    to show to the person who requested it."""

    def __init__(self, message: str, code: str = "PATCH_FAILED"):
        super().__init__(message)
        self.code = code


# --------------------------------------------------------------- catalogue --

def _text(value: Any, limit: int) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ""


def _https_url(value: Any) -> str:
    text = _text(value, 2048)
    parsed = urllib.parse.urlparse(text)
    return text if parsed.scheme == "https" and parsed.hostname else ""


def _normalise_version(raw: Any) -> dict | None:
    if not isinstance(raw, dict):
        return None
    version_id = _text(raw.get("id") or raw.get("version"), 128)
    if not _ID.match(version_id):
        return None
    base = raw.get("base") if isinstance(raw.get("base"), dict) else {}
    fmt = _text(raw.get("patchFormat"), 8).lower()
    sha1 = _text(base.get("sha1"), 40).lower()
    crc32 = _text(base.get("crc32"), 8).lower()
    sha256 = _text(raw.get("patchSha256"), 64).lower()
    return {
        "id": version_id,
        "version": _text(raw.get("version") or version_id, 64),
        "releasedAt": _text(raw.get("releasedAt"), 32),
        "notes": _text(raw.get("notes"), 600),
        "patchUrl": _https_url(raw.get("patchUrl")),
        "patchSha256": sha256 if len(sha256) == 64 and _HEX.match(sha256) else "",
        "patchFormat": fmt if fmt in PATCH_FORMATS else "",
        "base": {
            "region": _text(base.get("region"), 32),
            "revision": _text(base.get("revision"), 32),
            "sha1": sha1 if len(sha1) == 40 and _HEX.match(sha1) else "",
            "crc32": crc32 if len(crc32) == 8 and _HEX.match(crc32) else "",
        },
    }


def normalise_project(raw: Any) -> dict | None:
    """One catalogue entry in the shape SeerrNG reads, or None if unusable.

    Completeness is taken only from what the project states. A missing value
    stays missing -- it is never inferred from a file name or a version count.
    """
    if not isinstance(raw, dict):
        return None
    project_id = _text(raw.get("id"), 128)
    kind = _text(raw.get("kind"), 16).lower()
    game = raw.get("game") if isinstance(raw.get("game"), dict) else {}
    if not _ID.match(project_id) or kind not in KINDS or not _text(raw.get("name"), 200):
        return None
    if not _text(game.get("title"), 300):
        return None
    versions = [v for v in (_normalise_version(v) for v in (raw.get("versions") or [])[:100]) if v]
    status = _text(raw.get("status"), 16).lower()
    completeness = raw.get("completeness")
    if isinstance(completeness, bool) or not isinstance(completeness, (int, float)) \
            or not 0 <= float(completeness) <= 1:
        completeness = None
    language = _text(raw.get("language"), 8).lower()
    return {
        "id": project_id,
        "name": _text(raw.get("name"), 200),
        "kind": kind,
        "language": language,
        "status": status if status in STATUSES else "unknown",
        "completeness": float(completeness) if completeness is not None else None,
        "summary": _text(raw.get("summary"), 800),
        "author": _text(raw.get("author"), 200),
        "url": _https_url(raw.get("url")),
        "coverUrl": _https_url(raw.get("coverUrl")),
        "differences": [d for d in (_text(x, 200) for x in (raw.get("differences") or [])[:20]) if d],
        "game": {
            "title": _text(game.get("title"), 300),
            "platformSlug": _text(game.get("platform"), 64).lower(),
            "catalogKey": _text(game.get("catalogKey"), 128),
        },
        "versions": versions,
        "latestVersionId": _text(raw.get("latestVersionId"), 128)
        or (versions[-1]["id"] if versions else ""),
    }


def public_project(project: dict, base_available: Callable[[dict, dict], bool]) -> dict:
    """The SeerrNG view: no download URLs, with base availability filled in."""
    view = {k: v for k, v in project.items()
            if k != "versions" and v not in (None, "", [])}
    view["versions"] = [
        {
            "id": v["id"],
            "version": v["version"],
            **({"releasedAt": v["releasedAt"]} if v["releasedAt"] else {}),
            **({"notes": v["notes"]} if v["notes"] else {}),
            **({"patchFormat": v["patchFormat"]} if v["patchFormat"] else {}),
            "base": {
                **{k: x for k, x in v["base"].items() if x},
                "available": bool(base_available(project, v)),
            },
        }
        for v in project["versions"]
    ]
    return view


class PatchCatalog:
    """Projects from `<dir>/patch-catalog.d/*.json` and an optional remote."""

    def __init__(self, directory: Path, remote_url: Callable[[], str] = lambda: ""):
        self.directory = Path(directory)
        self._remote_url = remote_url
        self._projects: dict[str, dict] = {}
        self._loaded_at = 0.0
        self._remote_at = 0.0
        self._remote: list[dict] = []

    # Local files are cheap to re-read; do it when the directory changes.
    def _files(self) -> list[Path]:
        folder = self.directory / "patch-catalog.d"
        try:
            return sorted(p for p in folder.glob("*.json") if p.is_file())[:200]
        except OSError:
            return []

    def reload(self, force: bool = False) -> None:
        if not force and time.time() - self._loaded_at < 30:
            return
        projects: dict[str, dict] = {}
        for path in self._files():
            try:
                if path.stat().st_size > MAX_CATALOG_BYTES:
                    log.warning("patch catalogue %s is too large; skipped", path.name)
                    continue
                doc = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as err:
                log.warning("patch catalogue %s unreadable (%s)", path.name, err.__class__.__name__)
                continue
            for raw in (doc.get("projects") if isinstance(doc, dict) else []) or []:
                project = normalise_project(raw)
                if project:
                    projects[project["id"]] = project
        self._refresh_remote()
        for project in self._remote:
            projects.setdefault(project["id"], project)
        self._projects = projects
        self._loaded_at = time.time()

    def _refresh_remote(self) -> None:
        url = _https_url(self._remote_url())
        if not url or time.time() - self._remote_at < REMOTE_REFRESH_SECONDS:
            return
        self._remote_at = time.time()
        try:
            body = fetch_public_https(url, MAX_CATALOG_BYTES, accept="application/json")
            doc = json.loads(body.decode("utf-8"))
            self._remote = [p for p in (normalise_project(r) for r in doc.get("projects", [])[:5000]) if p]
        except (PatchError, ValueError, UnicodeDecodeError) as err:
            log.warning("remote patch catalogue unavailable (%s)", err.__class__.__name__)

    def get(self, project_id: str) -> dict | None:
        self.reload()
        return self._projects.get(project_id)

    def search(self, *, q: str = "", platform: str = "", kind: str = "",
               language: str = "", complete_only: bool = False,
               catalog_key: str = "", limit: int = 24, offset: int = 0) -> tuple[list[dict], int | None]:
        self.reload()
        needle = q.strip().lower()
        rows = []
        for project in self._projects.values():
            if platform and project["game"]["platformSlug"] != platform.lower():
                continue
            if kind and project["kind"] != kind:
                continue
            if language and project["language"] != language.lower():
                continue
            if complete_only and project["status"] != "complete":
                continue
            if catalog_key and project["game"]["catalogKey"] != catalog_key:
                continue
            if needle and needle not in project["name"].lower() \
                    and needle not in project["game"]["title"].lower():
                continue
            rows.append(project)
        rows.sort(key=lambda p: (p["game"]["title"].lower(), p["name"].lower()))
        page = rows[offset:offset + limit]
        nxt = offset + limit if offset + limit < len(rows) else None
        return page, nxt


# ------------------------------------------------------------------- fetch --

def _is_public(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return not (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_multicast or ip.is_reserved or ip.is_unspecified)


class _PublicHttpsRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urllib.parse.urlparse(newurl)
        if parsed.scheme != "https":
            raise PatchError("A patch download redirected to an insecure address.", "PATCH_UNREACHABLE")
        _assert_public_host(parsed.hostname or "")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _assert_public_host(host: str) -> None:
    try:
        infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError as err:
        raise PatchError("The patch host could not be resolved.", "PATCH_UNREACHABLE") from err
    if not infos or not all(_is_public(info[4][0]) for info in infos):
        raise PatchError("The patch host is not a public address.", "PATCH_UNREACHABLE")


def fetch_public_https(url: str, limit: int, accept: str = "*/*", timeout: int = 20) -> bytes:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise PatchError("Patches are only downloaded over https.", "PATCH_UNREACHABLE")
    _assert_public_host(parsed.hostname)
    opener = urllib.request.build_opener(_PublicHttpsRedirects())
    request = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": "ROMarrNG-Patches/1"})
    try:
        with opener.open(request, timeout=timeout) as response:
            declared = int(response.headers.get("Content-Length") or 0)
            if declared > limit:
                raise PatchError("The patch file is larger than allowed.", "PATCH_UNREACHABLE")
            body = response.read(limit + 1)
    except PatchError:
        raise
    except (urllib.error.URLError, OSError, ValueError) as err:
        raise PatchError("The patch could not be downloaded.", "PATCH_UNREACHABLE") from err
    if len(body) > limit:
        raise PatchError("The patch file is larger than allowed.", "PATCH_UNREACHABLE")
    return body


def fetch_patch(version: dict) -> bytes:
    if not version.get("patchUrl"):
        raise PatchError("This version has no download address.", "PATCH_UNREACHABLE")
    body = fetch_public_https(version["patchUrl"], MAX_PATCH_BYTES)
    expected = version.get("patchSha256")
    if expected and hashlib.sha256(body).hexdigest() != expected:
        raise PatchError("The downloaded patch does not match the catalogue's checksum.", "PATCH_CORRUPT")
    return body


# ---------------------------------------------------------------- appliers --

def _crc(data: bytes) -> int:
    return zlib.crc32(data) & 0xFFFFFFFF


def detect_format(patch: bytes) -> str:
    if patch.startswith(b"PATCH"):
        return "ips"
    if patch.startswith(b"UPS1"):
        return "ups"
    if patch.startswith(b"BPS1"):
        return "bps"
    raise PatchError("This patch is not an IPS, UPS or BPS file.", "PATCH_FORMAT")


def apply_ips(rom: bytes, patch: bytes) -> bytes:
    out = bytearray(rom)
    pos = 5
    while True:
        if pos + 3 > len(patch):
            raise PatchError("The IPS patch is truncated.", "PATCH_CORRUPT")
        if patch[pos:pos + 3] == b"EOF":
            pos += 3
            if pos + 3 <= len(patch):
                size = int.from_bytes(patch[pos:pos + 3], "big")
                del out[size:]
            return bytes(out)
        offset = int.from_bytes(patch[pos:pos + 3], "big")
        pos += 3
        if pos + 2 > len(patch):
            raise PatchError("The IPS patch is truncated.", "PATCH_CORRUPT")
        size = int.from_bytes(patch[pos:pos + 2], "big")
        pos += 2
        if size == 0:
            if pos + 3 > len(patch):
                raise PatchError("The IPS patch is truncated.", "PATCH_CORRUPT")
            run = int.from_bytes(patch[pos:pos + 2], "big")
            value = patch[pos + 2]
            pos += 3
            chunk = bytes([value]) * run
        else:
            chunk = patch[pos:pos + size]
            if len(chunk) != size:
                raise PatchError("The IPS patch is truncated.", "PATCH_CORRUPT")
            pos += size
        if offset + len(chunk) > MAX_ROM_BYTES:
            raise PatchError("The patch would make the file too large.", "PATCH_CORRUPT")
        if offset > len(out):
            out.extend(b"\x00" * (offset - len(out)))
        out[offset:offset + len(chunk)] = chunk


def _vlq(data: bytes, pos: int) -> tuple[int, int]:
    value, shift = 0, 1
    while True:
        if pos >= len(data):
            raise PatchError("The patch is truncated.", "PATCH_CORRUPT")
        byte = data[pos]
        pos += 1
        value += (byte & 0x7F) * shift
        if byte & 0x80:
            return value, pos
        shift <<= 7
        value += shift


def apply_ups(rom: bytes, patch: bytes) -> bytes:
    if len(patch) < 18:
        raise PatchError("The UPS patch is truncated.", "PATCH_CORRUPT")
    if _crc(patch[:-4]) != int.from_bytes(patch[-4:], "little"):
        raise PatchError("The UPS patch is damaged (checksum mismatch).", "PATCH_CORRUPT")
    pos = 4
    in_size, pos = _vlq(patch, pos)
    out_size, pos = _vlq(patch, pos)
    source_crc = int.from_bytes(patch[-12:-8], "little")
    target_crc = int.from_bytes(patch[-8:-4], "little")
    if out_size > MAX_ROM_BYTES:
        raise PatchError("The patch would make the file too large.", "PATCH_CORRUPT")
    swapped = False
    if len(rom) == out_size and _crc(rom) == target_crc:
        # UPS is symmetric: applying to the patched file restores the original.
        swapped = True
    elif len(rom) != in_size or _crc(rom) != source_crc:
        raise PatchError("This is not the game dump the patch was made for.", "BASE_MISMATCH")
    size = out_size if not swapped else in_size
    out = bytearray(rom[:size] + b"\x00" * max(0, size - len(rom)))
    cursor = 0
    end = len(patch) - 12
    while pos < end:
        skip, pos = _vlq(patch, pos)
        cursor += skip
        while pos < end:
            byte = patch[pos]
            pos += 1
            if byte == 0:
                cursor += 1
                break
            if cursor < len(out):
                out[cursor] ^= byte
            cursor += 1
    expected = source_crc if swapped else target_crc
    if _crc(bytes(out)) != expected:
        raise PatchError("The patched file failed its checksum.", "PATCH_CORRUPT")
    return bytes(out)


def apply_bps(rom: bytes, patch: bytes) -> bytes:
    if len(patch) < 19:
        raise PatchError("The BPS patch is truncated.", "PATCH_CORRUPT")
    if _crc(patch[:-4]) != int.from_bytes(patch[-4:], "little"):
        raise PatchError("The BPS patch is damaged (checksum mismatch).", "PATCH_CORRUPT")
    pos = 4
    source_size, pos = _vlq(patch, pos)
    target_size, pos = _vlq(patch, pos)
    meta_size, pos = _vlq(patch, pos)
    pos += meta_size
    source_crc = int.from_bytes(patch[-12:-8], "little")
    target_crc = int.from_bytes(patch[-8:-4], "little")
    if len(rom) != source_size or _crc(rom) != source_crc:
        raise PatchError("This is not the game dump the patch was made for.", "BASE_MISMATCH")
    if target_size > MAX_ROM_BYTES:
        raise PatchError("The patch would make the file too large.", "PATCH_CORRUPT")
    out = bytearray(target_size)
    out_pos = source_rel = target_rel = 0
    end = len(patch) - 12
    while pos < end:
        command, pos = _vlq(patch, pos)
        action, length = command & 3, (command >> 2) + 1
        if out_pos + length > target_size:
            raise PatchError("The BPS patch writes past the end of the file.", "PATCH_CORRUPT")
        if action == 0:
            out[out_pos:out_pos + length] = rom[out_pos:out_pos + length]
            out_pos += length
        elif action == 1:
            out[out_pos:out_pos + length] = patch[pos:pos + length]
            pos += length
            out_pos += length
        else:
            raw, pos = _vlq(patch, pos)
            delta = -(raw >> 1) if raw & 1 else (raw >> 1)
            if action == 2:
                source_rel += delta
                if source_rel < 0 or source_rel + length > len(rom):
                    raise PatchError("The BPS patch reads outside the game.", "PATCH_CORRUPT")
                out[out_pos:out_pos + length] = rom[source_rel:source_rel + length]
                source_rel += length
                out_pos += length
            else:
                target_rel += delta
                if target_rel < 0 or target_rel >= out_pos:
                    raise PatchError("The BPS patch copies from the future.", "PATCH_CORRUPT")
                for _ in range(length):
                    out[out_pos] = out[target_rel]
                    out_pos += 1
                    target_rel += 1
    if _crc(bytes(out)) != target_crc:
        raise PatchError("The patched file failed its checksum.", "PATCH_CORRUPT")
    return bytes(out)


def apply_patch(rom: bytes, patch: bytes, version: dict | None = None) -> tuple[bytes, str]:
    """Apply a patch, returning the new file and the format used.

    IPS carries no checksum, so the catalogue's pinned base hash is the only
    guard; without one the result is flagged by the caller as unverified.
    """
    fmt = detect_format(patch)
    if len(rom) > MAX_ROM_BYTES:
        raise PatchError("The game file is larger than allowed.", "PATCH_FAILED")
    if fmt == "ips":
        base = (version or {}).get("base") or {}
        if base.get("sha1") and hashlib.sha1(rom).hexdigest() != base["sha1"]:
            raise PatchError("This is not the game dump the patch was made for.", "BASE_MISMATCH")
        if base.get("crc32") and f"{_crc(rom):08x}" != base["crc32"]:
            raise PatchError("This is not the game dump the patch was made for.", "BASE_MISMATCH")
        return apply_ips(rom, patch), fmt
    return (apply_ups(rom, patch) if fmt == "ups" else apply_bps(rom, patch)), fmt


@dataclass
class Prepared:
    path: Path
    patch_format: str
    verified: bool
    sha1: str


def _filename(base_name: str, project: dict, version: dict, suffix: str) -> str:
    tag = re.sub(r"[^A-Za-z0-9._ -]+", "", f"{project['name']} {version['version']}").strip()
    stem = re.sub(r"[\\/:*?\"<>|]+", "", Path(base_name).stem).strip() or "game"
    return f"{stem} [{tag}]{suffix}"[:240]


def prepare_patched_file(
    base_path: Path, library_root: Path, project: dict, version: dict,
    destination: Path, patch_bytes: bytes | None = None,
) -> Prepared:
    """Write the patched file next to (never over) the base dump."""
    try:
        resolved = base_path.resolve(strict=True)
        resolved.relative_to(library_root.resolve(strict=True))
    except (OSError, ValueError) as err:
        raise PatchError("The base game is not in the library.", "BASE_MISSING") from err
    if not resolved.is_file():
        raise PatchError(
            "The base game is stored as a folder or archive; extract a single ROM file first.",
            "BASE_UNSUPPORTED")
    if resolved.stat().st_size > MAX_ROM_BYTES:
        raise PatchError("The game file is larger than allowed.", "PATCH_FAILED")
    patch = patch_bytes if patch_bytes is not None else fetch_patch(version)
    patched, fmt = apply_patch(resolved.read_bytes(), patch, version)
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / _filename(resolved.name, project, version, resolved.suffix)
    if target.resolve(strict=False).parent != destination.resolve(strict=False):
        raise PatchError("The patched file name is not allowed.", "PATCH_FAILED")
    temporary = target.with_suffix(target.suffix + ".part")
    temporary.write_bytes(patched)
    temporary.replace(target)
    return Prepared(target, fmt, verified=fmt != "ips" or bool(
        version.get("base", {}).get("sha1") or version.get("base", {}).get("crc32")),
        sha1=hashlib.sha1(patched).hexdigest())
