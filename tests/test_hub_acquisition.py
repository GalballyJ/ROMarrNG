"""ROM Hub plugins as a search source and download lane (issue #40).

The invariants: a hub release travels the same queue/import pipeline as any
other release; the lane stays silent until both halves exist (an enabled
searchable plugin AND a configured ROM Hub client); and nothing touches the
network in these tests -- the Hub bridge is stubbed at its seams.
"""

import json
from pathlib import Path

import pytest

from romarr import hub
from romarr.downloaders import HubConfig, HubDownloader, build_client


# -- the hub:// URL -----------------------------------------------------------

ROW = {"source_id": "ia:metroid", "title": "Super Metroid (USA)",
       "platform": "snes", "size_bytes": 3145728,
       "url": "https://archive.org/details/metroid",
       "extra": {}, "plugin": "archive-org"}


def test_a_result_round_trips_through_a_hub_url():
    encoded = hub.encode_result(ROW)
    assert encoded.startswith("hub://")
    assert hub.decode_result(encoded) == ROW


def test_a_hub_url_carries_no_credential_shape():
    # It is stored in the queue and the ledger; a bare base64 of a row with
    # no secrets is the point of the encoding.
    encoded = hub.encode_result(ROW)
    assert " " not in encoded and "\n" not in encoded


def test_decode_refuses_a_foreign_or_corrupt_url():
    with pytest.raises(ValueError):
        hub.decode_result("https://example.com/rom.zip")
    with pytest.raises(ValueError):
        hub.decode_result("hub://!!!!not-base64!!!!")
    with pytest.raises(ValueError):
        hub.decode_result(hub.encode_result({"title": "no source_id"}))


# -- the download lane --------------------------------------------------------

def test_the_hub_client_is_a_download_client_type():
    client = build_client({"type": "hub", "save_path": "/downloads/hub"})
    assert isinstance(client, HubDownloader)
    assert client.protocol == "hub"
    assert client.configured
    assert build_client({"type": "hub", "save_path": ""}).configured is False


def test_add_records_a_job_and_refuses_non_hub_urls(tmp_path):
    client = HubDownloader(HubConfig(save_path=str(tmp_path)))
    assert client.add("https://example.com/x.zip") is False
    assert client.add(hub.encode_result(ROW), name="Super Metroid (USA)")
    rows = json.loads((tmp_path / HubDownloader.LEDGER)
                      .read_text(encoding="utf-8"))
    assert rows[0]["state"] == "pending"
    assert rows[0]["name"] == "Super Metroid (USA)"


def test_add_refuses_an_undecodable_hub_url(tmp_path):
    client = HubDownloader(HubConfig(save_path=str(tmp_path)))
    assert client.add("hub://Z29uZQ==") is False


def test_the_sweep_fetches_through_the_plugin_and_reports_the_file(tmp_path):
    fetched = []

    def fake_fetch(row, dest):
        fetched.append((row, dest))
        dest = Path(dest)
        dest.mkdir(parents=True, exist_ok=True)
        f = dest / (row["title"] + ".sfc")
        f.write_bytes(b"\x00" * 16)
        return {"ok": True, "error": "", "files": [str(f)]}

    client = HubDownloader(HubConfig(save_path=str(tmp_path)),
                           fetch=fake_fetch)
    client.add(hub.encode_result(ROW), name="Super Metroid (USA)")
    done = client.completed()
    assert fetched and fetched[0][0] == ROW
    assert len(done) == 1
    assert done[0]["id"] == client.last_job_id
    assert done[0]["name"] == "Super Metroid (USA)"
    assert Path(done[0]["content_path"]).read_bytes() == b"\x00" * 16
    assert Path(done[0]["content_path"]).parent.parent == tmp_path
    assert done[0]["state"] == "done"
    # The ledger row moved to done and survives a restart.
    rows = json.loads((tmp_path / HubDownloader.LEDGER)
                      .read_text(encoding="utf-8"))
    assert rows[0]["state"] == "done"


def test_a_failed_fetch_is_recorded_with_its_reason(tmp_path):
    def boom(row, dest):
        return {"ok": False, "error": "DownloadError: refused host",
                "files": []}

    client = HubDownloader(HubConfig(save_path=str(tmp_path)), fetch=boom)
    client.add(hub.encode_result(ROW), name="Super Metroid (USA)")
    assert client.completed() == []
    rows = json.loads((tmp_path / HubDownloader.LEDGER)
                      .read_text(encoding="utf-8"))
    assert rows[0]["state"] == "failed"
    assert "refused host" in rows[0]["detail"]


def test_one_fetch_per_sweep(tmp_path):
    calls = []

    def fetch(row, dest):
        calls.append(row["source_id"])
        dest = Path(dest)
        dest.mkdir(parents=True, exist_ok=True)
        f = dest / f"{row['source_id']}.sfc"
        f.write_bytes(b"\x00")
        return {"ok": True, "error": "", "files": [str(f)]}

    client = HubDownloader(HubConfig(save_path=str(tmp_path), max_active=1),
                           fetch=fetch)
    client.add(hub.encode_result(dict(ROW, source_id="a")))
    client.add(hub.encode_result(dict(ROW, source_id="b")))
    client.completed()
    assert calls == ["a"]
    client.completed()
    assert calls == ["a", "b"]


def test_reachable_says_what_is_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(hub, "sandbox_state", lambda: (True, "available"))
    client = HubDownloader(HubConfig(save_path=str(tmp_path)))
    monkeypatch.setattr(hub, "available", lambda: False)
    assert client.reachable() is False
    assert "not installed" in client.detail

    monkeypatch.setattr(hub, "available", lambda: True)
    monkeypatch.setattr(hub, "searchable_plugins", lambda: [])
    assert client.reachable() is False
    assert "no enabled plugin" in client.detail

    monkeypatch.setattr(hub, "searchable_plugins", lambda: ["archive-org"])
    assert client.reachable() is True
    assert "archive-org" in client.detail


# -- the search lane ----------------------------------------------------------

class _FakePlatform:
    slug = "snes"
    name = "Super Nintendo"
    aliases = ()
    native_markers = ()
    media = "cartridge"


def _service(tmp_path, monkeypatch, rows, clients=()):
    from romarr.app import ROMarr
    svc = ROMarr(env={"ROMARR_DATA": str(tmp_path / "s.json")})
    svc.clients = list(clients)
    monkeypatch.setattr(hub, "searchable_plugins", lambda: ["archive-org"])
    monkeypatch.setattr(hub, "search",
                        lambda q, platform=None, limit=25, timeout=30.0:
                        (rows, ""))
    return svc


def _hub_client(tmp_path):
    return HubDownloader(HubConfig(save_path=str(tmp_path / "hub")))


def test_the_lane_is_quiet_without_both_halves(tmp_path, monkeypatch):
    svc = _service(tmp_path, monkeypatch, [ROW])
    assert svc._hub_enabled() is False
    assert svc._hub_releases("Super Metroid", _FakePlatform()) == []

    # A client with no searchable plugin is still not enough.
    monkeypatch.setattr(hub, "searchable_plugins", lambda: [])
    svc.clients = [_hub_client(tmp_path)]
    assert svc._hub_enabled() is False


def test_hub_results_become_releases_on_the_same_pipeline(tmp_path, monkeypatch):
    svc = _service(tmp_path, monkeypatch, [ROW], [_hub_client(tmp_path)])
    releases = svc._hub_releases("Super Metroid", _FakePlatform())
    assert len(releases) == 1
    r = releases[0]
    assert r.title == "Super Metroid (USA)"
    assert r.protocol == "hub"
    assert r.indexer == "hub:archive-org"
    assert r.size == 3145728
    assert r.download_url.startswith("hub://")
    assert hub.decode_result(r.download_url) == ROW


def test_interactive_search_shows_hub_results(tmp_path, monkeypatch):
    svc = _service(tmp_path, monkeypatch, [ROW], [_hub_client(tmp_path)])
    # The no-platform branch queries Prowlarr AND the hub lane; stub it so
    # the test drives the hub half without a live indexer.
    class _NoProwlarr:
        def search(self, term):
            return []

    monkeypatch.setattr(svc, "prowlarr", _NoProwlarr())
    out = svc.candidates("Super Metroid", "")
    items = out["items"]
    assert any(i["protocol"] == "hub" and i["indexer"] == "hub:archive-org"
               for i in items), items


def test_a_failing_hub_does_not_sink_the_search(tmp_path, monkeypatch):
    from romarr.app import ROMarr
    svc = ROMarr(env={"ROMARR_DATA": str(tmp_path / "s.json")})
    svc.clients = [_hub_client(tmp_path)]
    monkeypatch.setattr(hub, "searchable_plugins", lambda: ["archive-org"])

    def explode(*a, **k):
        raise RuntimeError("hub on fire")

    monkeypatch.setattr(hub, "search", explode)
    assert svc._hub_releases("Super Metroid", _FakePlatform()) == []


def test_sandbox_failure_requires_explicit_operator_opt_in(monkeypatch):
    monkeypatch.setattr(hub, "sandbox_state", lambda: (False, "unavailable"))
    monkeypatch.delenv("ROMARR_ALLOW_UNSANDBOXED_PLUGINS", raising=False)
    monkeypatch.setenv("ROM_HUB_ALLOW_UNSANDBOXED", "1")
    with pytest.raises(RuntimeError, match="confinement"):
        hub._unsandboxed()
    monkeypatch.setenv("ROMARR_ALLOW_UNSANDBOXED_PLUGINS", "1")
    assert hub._unsandboxed() is True
    monkeypatch.setattr(hub, "sandbox_state", lambda: (True, "available"))
    assert hub._unsandboxed() is False


def test_separate_jobs_cannot_overwrite_identically_named_files(tmp_path):
    def fetch(row, dest):
        dest.mkdir(parents=True, exist_ok=True)
        f = dest / "game.sfc"
        f.write_text(row["source_id"])
        return {"ok": True, "files": [str(f)]}
    client = HubDownloader(HubConfig(str(tmp_path), max_active=2), fetch=fetch)
    client.add(hub.encode_result(dict(ROW, source_id="one")), name="Same title")
    first_id = client.last_job_id
    client.add(hub.encode_result(dict(ROW, source_id="two")), name="Same title")
    assert client.last_job_id != first_id
    done = client.completed()
    assert {Path(d["content_path"]).read_text() for d in done} == {"one", "two"}
    assert len({d["id"] for d in done}) == 2
    assert HubDownloader(HubConfig(str(tmp_path))).completed() == done


def test_multi_file_job_reports_its_whole_isolated_directory(tmp_path):
    def fetch(row, dest):
        files = []
        for name in ("disc1/one.bin", "disc2/two.bin"):
            f = dest / name
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(b"x")
            files.append(str(f))
        return {"ok": True, "files": files}
    client = HubDownloader(HubConfig(str(tmp_path)), fetch=fetch)
    client.add(hub.encode_result(ROW))
    root = Path(client.completed()[0]["content_path"])
    assert root.parent == tmp_path
    assert len(list(root.rglob("*.bin"))) == 2


def test_persistence_failure_does_not_report_a_successful_grab(tmp_path, monkeypatch):
    client = HubDownloader(HubConfig(str(tmp_path)))
    def fail(rows):
        raise OSError("disk full")
    monkeypatch.setattr(client, "_write", fail)
    assert client.add(hub.encode_result(ROW)) is False
    assert not client.last_job_id


def test_corrupt_ledger_is_not_silently_overwritten(tmp_path):
    ledger = tmp_path / HubDownloader.LEDGER
    ledger.write_text("broken JSON")
    client = HubDownloader(HubConfig(str(tmp_path)))
    assert client.add(hub.encode_result(ROW)) is False
    assert ledger.read_text() == "broken JSON"


def test_plugin_cannot_report_a_file_outside_its_staging_job(tmp_path):
    outside = tmp_path / "unrelated.sfc"
    outside.write_bytes(b"keep")
    client = HubDownloader(HubConfig(str(tmp_path)),
                           fetch=lambda row, dest: {"ok": True, "files": [str(outside)]})
    client.add(hub.encode_result(ROW))
    assert client.completed() == []
    assert "outside" in client.failed()[0]["detail"]
    assert outside.read_bytes() == b"keep"


def test_retry_replaces_failed_attempt_and_survives_client_reload(tmp_path):
    first = HubDownloader(HubConfig(save_path=str(tmp_path)),
                          fetch=lambda *_: {"ok": False, "error": "retryable", "files": []})
    encoded = hub.encode_result(ROW)
    assert first.add(encoded)
    assert first.completed() == [] and first.failed()
    second = HubDownloader(HubConfig(save_path=str(tmp_path)))
    assert second.add(encoded)
    assert first.failed() == []
    rows = json.loads((tmp_path / first.LEDGER).read_text())
    assert len(rows) == 1 and rows[0]["state"] == "pending"


def test_client_reload_cannot_lose_jobs_added_during_fetch(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    entered, resume = threading.Event(), threading.Event()
    def fetch(row, dest):
        entered.set()
        assert resume.wait(5)
        path = Path(dest) / "game.sfc"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture")
        return {"ok": True, "files": [str(path)]}
    first = HubDownloader(HubConfig(save_path=str(tmp_path)), fetch=fetch)
    second = HubDownloader(HubConfig(save_path=str(tmp_path)), fetch=fetch)
    assert first.add(hub.encode_result(ROW))
    with ThreadPoolExecutor(1) as pool:
        completed = pool.submit(first.completed)
        assert entered.wait(5)
        try:
            assert second.add(hub.encode_result(dict(ROW, source_id="another")))
        finally:
            resume.set()
        assert len(completed.result()) == 1
    rows = json.loads((tmp_path / first.LEDGER).read_text())
    assert [row["state"] for row in rows] == ["done", "pending"]


def test_platform_mismatch_and_malformed_hub_rows_are_not_candidates(tmp_path, monkeypatch):
    svc = _service(tmp_path, monkeypatch, [dict(ROW, platform="gba"),
                   dict(ROW, size_bytes="bad"), dict(ROW, plugin="")], [_hub_client(tmp_path)])
    assert svc._hub_releases("Super Metroid", _FakePlatform()) == []


def test_prowlarr_failure_does_not_hide_hub_candidates(tmp_path, monkeypatch):
    svc = _service(tmp_path, monkeypatch, [ROW], [_hub_client(tmp_path)])
    def fail(*args):
        raise TimeoutError()
    monkeypatch.setattr(svc.prowlarr, "search", fail)
    result = svc.candidates("Super Metroid")
    assert any(row["indexer"] == "hub:archive-org" for row in result["items"])
