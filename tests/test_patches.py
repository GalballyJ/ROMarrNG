"""Patch catalogue, appliers, and the SeerrNG patch-request overlay."""

import json
import zlib
from pathlib import Path

import pytest

from romarr import patches


def vlq(n):
    out = bytearray()
    while True:
        x = n & 0x7F
        n >>= 7
        if n == 0:
            out.append(0x80 | x)
            return bytes(out)
        out.append(x)
        n -= 1


def bps(src: bytes, tgt: bytes) -> bytes:
    body = b"BPS1" + vlq(len(src)) + vlq(len(tgt)) + vlq(0)
    body += vlq(((len(tgt) - 1) << 2) | 1) + tgt
    body += zlib.crc32(src).to_bytes(4, "little") + zlib.crc32(tgt).to_bytes(4, "little")
    return body + zlib.crc32(body).to_bytes(4, "little")


def test_ips_applies_literal_and_rle_records():
    rom = bytes(range(16))
    ips = (b"PATCH" + (2).to_bytes(3, "big") + (3).to_bytes(2, "big") + b"abc"
           + (10).to_bytes(3, "big") + (0).to_bytes(2, "big") + (4).to_bytes(2, "big") + b"Z"
           + b"EOF")
    assert patches.apply_ips(rom, ips)[2:5] == b"abc"
    assert patches.apply_ips(rom, ips)[10:14] == b"ZZZZ"


def test_bps_verifies_base_and_result():
    src, tgt = b"hello world", b"jello world"
    patch = bps(src, tgt)
    assert patches.apply_bps(src, patch) == tgt
    with pytest.raises(patches.PatchError) as err:
        patches.apply_bps(b"other bytes", patch)
    assert err.value.code == "BASE_MISMATCH"


def test_damaged_bps_is_refused():
    patch = bytearray(bps(b"abc", b"abd"))
    patch[6] ^= 0xFF
    with pytest.raises(patches.PatchError) as err:
        patches.apply_bps(b"abc", bytes(patch))
    assert err.value.code == "PATCH_CORRUPT"


def test_unknown_patch_format_is_refused():
    with pytest.raises(patches.PatchError) as err:
        patches.apply_patch(b"rom", b"NOTAPATCH")
    assert err.value.code == "PATCH_FORMAT"


def test_ips_requires_the_pinned_base():
    ips = b"PATCH" + (0).to_bytes(3, "big") + (1).to_bytes(2, "big") + b"x" + b"EOF"
    version = {"base": {"sha1": "0" * 40, "crc32": ""}}
    with pytest.raises(patches.PatchError) as err:
        patches.apply_patch(b"abc", ips, version)
    assert err.value.code == "BASE_MISMATCH"


def test_catalogue_never_infers_completeness(tmp_path: Path):
    folder = tmp_path / "patch-catalog.d"
    folder.mkdir()
    (folder / "a.json").write_text(json.dumps({"schema": 1, "projects": [
        {"id": "p1", "name": "Fan Translation (T-En)", "kind": "translation", "language": "en",
         "game": {"title": "Game", "platform": "gba"},
         "versions": [{"id": "1", "version": "1", "patchUrl": "http://insecure.example/p.ips"}]},
        {"id": "bad id", "name": "x", "kind": "translation", "game": {"title": "G"}},
    ]}))
    catalogue = patches.PatchCatalog(tmp_path)
    project = catalogue.get("p1")
    assert project["status"] == "unknown"
    assert project["completeness"] is None
    # Plain http download addresses are dropped, not trusted.
    assert project["versions"][0]["patchUrl"] == ""
    assert catalogue.get("bad id") is None
    results, nxt = catalogue.search(complete_only=True)
    assert results == [] and nxt is None


def test_public_view_hides_download_addresses(tmp_path: Path):
    project = patches.normalise_project({
        "id": "p2", "name": "N", "kind": "hack", "game": {"title": "G", "platform": "snes"},
        "versions": [{"id": "1", "version": "1", "patchUrl": "https://example.org/p.bps"}]})
    view = patches.public_project(project, lambda *_: False)
    assert "patchUrl" not in json.dumps(view)
    assert view["versions"][0]["base"]["available"] is False


def test_private_hosts_are_refused():
    with pytest.raises(patches.PatchError):
        patches.fetch_public_https("https://127.0.0.1/p.ips", 1024)
    with pytest.raises(patches.PatchError):
        patches.fetch_public_https("http://example.org/p.ips", 1024)
