"""Completed jobs should match the grab even when the client renames them."""

from __future__ import annotations

from romarr.app import QueueItem, ROMarr
from romarr.downloaders import (RealDebrid, RealDebridConfig, SABnzbd,
                                SabConfig, hand_off_with_id, match_queue_item)
from romarr.store import _rows


HASH = "0123456789abcdef0123456789abcdef01234567"


def test_import_sweep_matches_infohash_before_a_renamed_title(tmp_path):
    service = ROMarr({"ROMARR_DATA": str(tmp_path / "state.json")})
    item = QueueItem("Pokemon Emerald", "gba", "Pokemon Emerald Rom", 5,
                     "grabbed", release_id=f"btih:{HASH}")
    service.queue.append(item)

    class FakeClient:
        name = "fake"
        configured = True

        def completed(self):
            return [{"name": "Pokemon Emerald (U).gba", "hash": HASH.upper(),
                     "content_path": str(tmp_path / "download")}]

    service.clients = [FakeClient()]
    results = service.import_finished(retry_failed=False)
    assert results and results[0]["reason"] == "no library configured to import into"
    assert item.state == "import-failed"


def test_download_client_job_id_matches_queue_item():
    item = QueueItem("Contra", "nes", "Indexer title", 0, "grabbed",
                     download_id="SABnzbd_nzo_abc123")
    assert match_queue_item([item], {"name": "Renamed job",
                                     "id": "SABnzbd_nzo_abc123"}) is item


def test_title_remains_a_fallback_for_old_queue_rows():
    item = QueueItem("Contra", "nes", "Contra (U).nes", 1, "grabbed")
    assert match_queue_item([item], {"name": "Contra (U).nes"}) is item
    assert item.download_id == ""


def test_a_different_infohash_does_not_claim_an_unrelated_queue_row():
    item = QueueItem("A", "nes", "Some title", 1, "grabbed",
                     release_id=f"btih:{HASH}")
    assert match_queue_item([item], {"name": "Other",
                                     "hash": "f" * 40}) is None


class Reply:
    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self.body


class SabSession:
    def get(self, url, *, params, timeout):
        if params["mode"] == "addurl":
            return Reply({"status": True, "nzo_ids": ["SABnzbd_nzo_abc123"]})
        return Reply({"history": {"slots": [{
            "name": "Renamed by SAB", "storage": "/downloads/game",
            "status": "Completed", "nzo_id": "SABnzbd_nzo_abc123",
        }]}})


def test_sabnzbd_job_id_is_saved_at_handoff_and_returned_in_history():
    client = SABnzbd(SabConfig(base_url="http://sab", api_key="key"),
                     session=SabSession())
    ok, job_id = hand_off_with_id(client, "https://indexer/nzb", name="Game")
    assert ok and job_id == "SABnzbd_nzo_abc123"
    assert client.completed()[0]["id"] == job_id


def test_new_queue_identity_field_does_not_break_saved_rows():
    rows = _rows([{"game": "g", "platform": "nes", "release": "r",
                   "seeders": 1, "state": "grabbed"}], QueueItem)
    assert rows[0].download_id == ""


def test_real_debrid_passes_the_torrent_hash_to_the_importer(tmp_path):
    client = RealDebrid(RealDebridConfig(api_token="token",
                                         save_path=str(tmp_path)))
    client._ours = lambda: ["rd-id"]
    client._get = lambda path, *args, **kwargs: {
        "status": "downloaded", "hash": HASH, "filename": "Game",
        "links": ["https://download/game.gba"],
    }
    client._fetch_links = lambda links, target: True
    assert client.completed()[0]["hash"] == HASH


def test_active_identity_match_wins_over_an_old_imported_row():
    old = QueueItem("Old", "nes", "Old name", 1, "imported", release_id=f"btih:{HASH}")
    new = QueueItem("New", "nes", "New name", 1, "grabbed", release_id=f"btih:{HASH}")
    assert match_queue_item([old, new], {"hash": HASH}) is new


def test_conflicting_job_ids_cannot_fall_back_to_same_title():
    item = QueueItem("Game", "nes", "Same title", 1, "grabbed", download_id="A")
    assert match_queue_item([item], {"id": "B", "name": "Same title"}) is None


def test_conflicting_hashes_cannot_fall_back_to_same_title():
    item = QueueItem("Game", "nes", "Same title", 1, "grabbed", release_id=f"btih:{HASH}")
    assert match_queue_item([item], {"hash": "f" * 40, "name": "Same title"}) is None


def test_renamed_import_fulfils_original_request_and_keeps_translation_layout(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import romarr.app as app
    service = ROMarr({"ROMARR_DATA": str(tmp_path / "state.json")})
    queued = QueueItem("Requested title", "snes", "Requested title [T-De]", 1,
                       "grabbed", download_id="job")
    service.queue.append(queued)
    service.store.want("Requested title", "snes")
    class Client:
        configured = True
        def completed(self):
            return [{"id": "job", "name": "renamed.sfc", "content_path": str(tmp_path)}]
    service.clients = [Client()]
    target = tmp_path / "library" / "rom.sfc"
    calls = []
    def imported_file(*args, **kwargs):
        calls.append(kwargs)
        return [SimpleNamespace(ok=True, destination=target, verification=None)]
    monkeypatch.setattr(app, "import_rom", imported_file)
    monkeypatch.setattr(service, "library_for", lambda slug: ({}, SimpleNamespace(name="test")))
    monkeypatch.setattr(service, "notify", lambda message: None)
    service.store.settings["rescan_after_import"] = False
    assert service.import_finished(retry_failed=False)[0]["ok"]
    assert calls[0]["translation"] is True
    assert service.store.wanted == []
    assert queued.state == "imported"


def test_base32_magnets_match_hex_completion_and_legacy_queue_rows():
    import base64
    from romarr.profiles import release_id
    from types import SimpleNamespace
    encoded = base64.b32encode(bytes.fromhex(HASH)).decode()
    assert release_id(SimpleNamespace(download_url=f"magnet:?xt=urn:btih:{encoded}")) == f"btih:{HASH}"
    old = QueueItem("Game", "nes", "Old title", 1, "grabbed", release_id=f"btih:{encoded.lower()}")
    assert match_queue_item([old], {"name": "renamed", "hash": HASH}) is old


def test_matching_is_scoped_to_download_client():
    item = QueueItem("Game", "nes", "same", 1, "grabbed", download_id="1", download_client_id="A")
    assert match_queue_item([item], {"id": "1", "name": "same"}, client_id="B") is None
    assert match_queue_item([item], {"id": "1"}, client_id="A") is item


def test_shared_download_fails_all_requests_without_a_library(tmp_path):
    service = ROMarr({"ROMARR_DATA": str(tmp_path / "state.json")})
    from types import SimpleNamespace
    service.clients = [SimpleNamespace(configured=True, completed=lambda: [{"id": "shared"}])]
    service.queue.extend(QueueItem("Game", "snes", "release", 1, "grabbed", download_id="shared",
                                   external_request_id=f"seerr-{i}") for i in range(2))
    service.import_finished(retry_failed=False)
    assert [item.state for item in service.queue] == ["import-failed", "import-failed"]
