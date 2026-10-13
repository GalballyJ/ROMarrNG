"""Packaged Hub -> DAT request -> import -> authenticated SeerrNG asset proof.

Run inside either image (requires its pinned rom-hub dependency):
  docker run --rm -e PYTHONPATH=/app --entrypoint python -v "$PWD/scripts:/proof:ro" IMAGE /proof/prove_upstream_acquisition.py
Uses only generated fixture bytes and loopback HTTPS; no external ROM source.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
import ssl
from pathlib import Path
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen


def main():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        os.environ["ROM_HUB_HOME"] = str(root / "hub")
        os.environ["ROMARR_API_KEY"] = "host-only-proof-key"
        os.environ.pop("ROMARR_ALLOW_UNSANDBOXED_PLUGINS", None)
        from romarr import hub
        from romarr.app import ROMarr, make_handler
        from romarr.dat import parse_dat
        from rom_hub.cli import secret_store

        app_state = root / "romarr.json"
        service = ROMarr({"ROMARR_DATA": str(app_state),
                          "ROMARR_API_KEY": "proof-api-key", "LIBRARY_KIND": "folder",
                          "LIBRARY_PATH": str(root / "library")})
        service.store.settings["_host_only_proof"] = "host-only-proof-key"
        service.store.save()
        protected_state_mode = stat.S_IMODE(app_state.stat().st_mode)

        payload = b"ROMarrNG acquisition fixture\n" * 1024
        class Source(BaseHTTPRequestHandler):
            def do_GET(self):
                body = b'{"ok":true}' if self.path == "/catalog" else payload
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *args):
                pass
        source = ThreadingHTTPServer(("127.0.0.1", 0), Source)
        fixtures = Path(__file__).parent / "fixtures"
        cert = fixtures / "hub-proof.crt"
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(cert, fixtures / "hub-proof.key")
        source.socket = context.wrap_socket(source.socket, server_side=True)
        os.environ["SSL_CERT_FILE"] = str(cert)
        threading.Thread(target=source.serve_forever, daemon=True).start()
        url = f"https://127.0.0.1:{source.server_port}"
        shadow_hits = []
        class ShadowProbe(BaseHTTPRequestHandler):
            def do_GET(self):
                shadow_hits.append(self.path)
                self.send_response(204)
                self.end_headers()
            def log_message(self, *args):
                pass
        shadow_probe = ThreadingHTTPServer(("127.0.0.1", 0), ShadowProbe)
        threading.Thread(target=shadow_probe.serve_forever, daemon=True).start()
        shadow_probe_url = f"http://127.0.0.1:{shadow_probe.server_port}"
        plugin = hub.HOME / "plugins" / "proof"
        plugin.mkdir(parents=True)
        (plugin / "manifest.toml").write_text('''[plugin]
slug="proof"
name="Acquisition proof"
version="1.0.0"
rpp_version="1"
[capabilities]
search="proof:Provider"
importer="proof:Provider"
[permissions]
network=["127.0.0.1"]
[config.token]
type="secret"
[config.state_path]
type="str"
[config.hub_state_path]
type="str"
[config.secrets_path]
type="str"
[config.secret_key_path]
type="str"
[config.shadow_probe_url]
type="str"
''' + f'''[[data_assets]]
name="fixture"
url="{url}/asset"
sha256="{hashlib.sha256(payload).hexdigest()}"
size_bytes={len(payload)}
''')
        (plugin / "proof.py").write_text('''import ctypes, errno, os, socket, threading
from rom_hub.types import SearchResult, FetchPlan, FetchFile
class Provider:
    def __init__(self, ctx):
        self.ctx = ctx
        assert "ROMARR_API_KEY" not in os.environ
        assert ctx.config["token"] == "plugin-proof-secret"
        for key in ("state_path", "hub_state_path", "secrets_path", "secret_key_path"):
            try:
                with open(ctx.config[key], "rb") as stream:
                    stream.read()
            except PermissionError:
                pass
            else:
                raise AssertionError("plugin read host state: " + key)
        for path in (ctx.config["state_path"], os.environ["TMPDIR"]):
            try:
                os.chmod(path, 0)
            except PermissionError as exc:
                assert exc.errno == errno.EPERM
            else:
                raise AssertionError("plugin changed host or scratch permissions: " + path)
        libc = ctypes.CDLL(None, use_errno=True)
        libc.syscall.restype = ctypes.c_long
        ctypes.set_errno(0)
        result = libc.syscall(452, -100, os.fsencode(ctx.config["state_path"]), 0o644, 0)
        if result == 0:
            raise AssertionError("plugin changed host permissions with fchmodat2")
        assert ctypes.get_errno() in (errno.EPERM, errno.ENOSYS), \
            f"fchmodat2 returned unexpected errno {ctypes.get_errno()}"
        params = ctypes.create_string_buffer(120)
        for number, args in (
            (425, (1, ctypes.byref(params))),
            (426, (-1, 0, 0, 0, ctypes.c_void_p(), 0)),
            (427, (-1, 0, ctypes.c_void_p(), 0)),
        ):
            ctypes.set_errno(0)
            result = libc.syscall(number, *args)
            if result >= 0:
                if number == 425:
                    os.close(result)
                raise AssertionError(f"plugin used io_uring syscall {number}")
            assert ctypes.get_errno() in (errno.EPERM, errno.ENOSYS), \
                f"io_uring syscall {number} returned unexpected errno {ctypes.get_errno()}"
        try:
            child_pid = os.fork()
        except OSError as exc:
            assert exc.errno == errno.EPERM
        else:
            if child_pid == 0:
                os._exit(0)
            os.waitpid(child_pid, 0)
            raise AssertionError("plugin created a child process")
        finished = []
        worker = threading.Thread(target=lambda: finished.append(True))
        worker.start()
        worker.join(timeout=2)
        assert finished == [True], "ordinary threads must remain available"
        for path in ("/proc/self/environ", f"/proc/{os.getppid()}/environ"):
            try:
                with open(path, "rb") as stream:
                    stream.read()
            except PermissionError:
                pass
            else:
                raise AssertionError("plugin read process environment: " + path)
        with open(ctx.data_asset("fixture"), "rb") as stream:
            assert stream.read().startswith(b"ROMarrNG acquisition fixture")
        try:
            sock = socket.socket()
        except PermissionError:
            pass
        else:
            sock.close()
            raise AssertionError("plugin sockets were not blocked")
    def search(self, query, platform=None, limit=25):
        assert self.ctx.http.get(self.ctx.config["url"] + "/catalog").json()["ok"]
        return [SearchResult(source_id="fixture", title="Proof Game (USA)",
            platform="snes", size_bytes=self.ctx.config["size"],
            url=self.ctx.config["url"] + "/rom")]
    def plan(self, result):
        return FetchPlan(platform="snes", files=[FetchFile(url=result.url,
            filename="Proof Game (USA).sfc", size_bytes=result.size_bytes)])
''')
        shadow_package = plugin / "rom_hub_sdk"
        shadow_package.mkdir()
        (shadow_package / "__init__.py").write_text("", encoding="utf-8")
        (shadow_package / "runner.py").write_text('''import json, sys, urllib.request
message = json.loads(sys.stdin.readline())
config = message["params"]["config"]
urllib.request.urlopen(
    config["shadow_probe_url"] + "/" + config["token"], timeout=3
).read()
''', encoding="utf-8")
        (plugin / "sitecustomize.py").write_text(
            "from pathlib import Path\n"
            f"state = Path({str(app_state)!r})\n"
            "try:\n"
            "    state.read_bytes()\n"
            "except PermissionError:\n"
            "    pass\n"
            "else:\n"
            f"    Path({str(root / 'sitecustomize-ran.txt')!r}).write_text('read')\n"
        )
        (hub.HOME / "state.json").write_text(json.dumps({"proof": {
            "enabled": True, "config": {
                "url": url, "size": len(payload),
                "state_path": str(app_state),
                "hub_state_path": str(hub.HOME / "state.json"),
                "secrets_path": str(hub.HOME / "secrets.json"),
                "secret_key_path": str(hub.HOME / "secret.key"),
                "shadow_probe_url": shadow_probe_url,
            }}}))
        secret_store(hub.HOME).set("proof", "token", "plugin-proof-secret")
        assert hub.sandbox_state()[0], hub.sandbox_state()
        import rom_hub.dispatcher as dispatcher
        original_search = dispatcher.search_all
        def traced_search(*args, **kwargs):
            outcome = original_search(*args, **kwargs)
            for status in outcome.statuses:
                if not status.ok:
                    print(status, flush=True)
            return outcome
        dispatcher.search_all = traced_search
        rows, error = hub.search("Proof Game", "snes")
        assert not shadow_hits, \
            f"plugin-supplied SDK runner exfiltrated configuration: {shadow_hits}"
        assert not error and len(rows) == 1, (error, rows)
        assert stat.S_IMODE(app_state.stat().st_mode) == protected_state_mode
        assert not (root / "sitecustomize-ran.txt").exists(), \
            "plugin-controlled sitecustomize ran before the filesystem boundary"

        service.store.settings["rescan_after_import"] = False
        service.store.settings["preferred_regions"] = ["usa"]
        service.store.settings["region_mode"] = "strict"
        service.store.put_item("download_clients", {"type": "hub", "enable": True,
                              "save_path": str(root / "downloads"), "name": "Proof Hub"})
        service.reload_clients()
        digest = hashlib.sha1(payload).hexdigest()
        service.dats.add(parse_dat(f'''<datafile><header><name>Nintendo - Super Nintendo Entertainment System</name></header>
<game name="Proof Game (USA)"><rom name="Proof Game (USA).sfc" size="{len(payload)}" sha1="{digest}"/></game>
<game name="Excluded Game (Japan)"/></datafile>'''))
        api = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(service))
        threading.Thread(target=api.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{api.server_port}/api/integration/seerrng/v1"
        def call(path, body=None, raw=False):
            req = Request(base + path, data=json.dumps(body).encode() if body is not None else None,
                          headers={"X-Api-Key": service.auth.integration_key,
                                   "Content-Type": "application/json"})
            with urlopen(req, timeout=30) as response:
                data = response.read()
                return data if raw else json.loads(data)
        try:
            [game] = call("/catalog/dat/browse-page?platformSlugs=snes")["results"]
            assert game["title"] == "Proof Game"
            for number in (1, 2):
                call("/requests", {"externalRequestId": f"proof-{number}",
                    "game": game["title"], "platform": "snes", "identity": {
                        "catalogProvider": "dat", "catalogKey": game["catalogId"], "platformSlug": "snes"}})
                deadline = time.monotonic() + 30
                while call(f"/requests/proof-{number}")["status"] in ("accepted", "searching"):
                    assert time.monotonic() < deadline, "dispatch timed out"
                    time.sleep(.05)
                assert call(f"/requests/proof-{number}")["status"] == "downloading"
            assert len(service.queue) == 2
            assert service.queue[0].download_id == service.queue[1].download_id
            outcomes = service.import_finished(retry_failed=False)
            assert outcomes and all(row["ok"] for row in outcomes), outcomes
            for number in (1, 2):
                result = call(f"/requests/proof-{number}")
                assert result["status"] == "available" and result["deliverable"], result
                assert str(root) not in json.dumps(result)
                [asset] = call(f"/requests/proof-{number}/assets")["assets"]
                assert call(f"/requests/proof-{number}/assets/{asset['id']}", raw=True) == payload
            print("PASS: sandbox sockets, io_uring, metadata changes and process forks blocked; bounded tmpfs scratch; host credentials isolated; plugin secret and verified asset resolved; broker HTTPS; shared Hub download; strict DAT catalog; two SeerrNG requests imported and streamed exact bytes")
        finally:
            api.shutdown()
            api.server_close()
            source.shutdown()
            source.server_close()
            shadow_probe.shutdown()
            shadow_probe.server_close()


if __name__ == "__main__":
    main()
