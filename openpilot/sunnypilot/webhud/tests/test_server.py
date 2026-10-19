"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
import base64
import gzip
import http.client
import json
import os
import socket
import tempfile
import threading
import time
from unittest import mock

from opendbc.car.fisker import values

from openpilot.common.test import OpenpilotTestCase
from openpilot.sunnypilot.selfdrive.car.can_overrides import PARAM
import openpilot.sunnypilot.webhud.server as webhud_server
from openpilot.sunnypilot.webhud.paths import page_roots
from openpilot.sunnypilot.webhud.server import Engine, OverridesApi, _DevParams, make_server
from openpilot.sunnypilot.webhud.websocket import OP_TEXT, encode_frame, read_frame


class TestServer(OpenpilotTestCase):
  def setUp(self):
    super().setUp()
    self.tmp = tempfile.TemporaryDirectory()
    os.environ["LOG_ROOT"] = os.path.join(self.tmp.name, "realdata")
    self.saved = dict(values.ICC_0x35B_OVERRIDES)
    self.params = _DevParams(os.path.join(self.tmp.name, "params.json"))
    self.engine = Engine(self.params)
    api = OverridesApi(self.params, self.engine.builder, self.engine.monitor)
    self.server = make_server("127.0.0.1", 0, self.engine, self.params, api, "sunnypilot-test")
    self.port = self.server.server_address[1]
    threading.Thread(target=self.server.serve_forever, daemon=True).start()
    self.engine_thread = threading.Thread(target=self.engine.run, daemon=True)
    self.engine_thread.start()

  def tearDown(self):
    self.engine.stop_event.set()
    self.server.shutdown()
    self.server.server_close()
    self.engine_thread.join(timeout=5)
    values.ICC_0x35B_OVERRIDES.clear()
    values.ICC_0x35B_OVERRIDES.update(self.saved)
    self.tmp.cleanup()
    super().tearDown()

  def request(self, method, path, body=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
    data = json.dumps(body).encode() if isinstance(body, (dict, list)) else body
    conn.request(method, path, body=data, headers={"Content-Type": "application/json", **(headers or {})})
    res = conn.getresponse()
    raw = res.read()
    if res.getheader("Content-Encoding") == "gzip":
      raw = gzip.decompress(raw)
    conn.close()
    return res.status, raw, res

  def test_static_and_status(self):
    # the page isn't here (it's the Oceanfront View app): "/" says where it is, its files are 404s
    status, body, res = self.request("GET", "/")
    assert status == 200 and b"Oceanfront View" in body and res.getheader("Cache-Control") == "no-cache"
    for path in ("/js/main.js", "/vendor/OrbitControls.js", "/models/pulse_ocean_v0.10_parts.glb", "/api/dbc",
                 "/../../server.py", "/dbc/../server.py", "/dbc/../../../sunnypilot/webhud/server.py"):
      assert self.request("GET", path)[0] == 404, path
    status, body, _ = self.request("GET", "/api/status")
    st = json.loads(body)
    assert status == 200 and st["hostname"] == "sunnypilot-test.local" and st["overrides"]
    # the page decodes the buses itself, with the DBCs served as files (the radar's lives in opendbc)
    status, body, res = self.request("GET", "/dbc/fisker_ocean_adas_world.dbc")
    assert status == 200 and body.count(b"\nBO_ ") > 80 and "max-age" in res.getheader("Cache-Control")
    status, body, _ = self.request("GET", "/dbc/fisker_ocean_mrr.dbc")
    assert status == 200 and b"MRR_" in body

  def test_static_validators(self):
    # every file can be checked with a 304 instead of sent again
    path = "/dbc/fisker_ocean_adas_world.dbc"
    status, body, res = self.request("GET", path)
    etag, modified = res.getheader("ETag"), res.getheader("Last-Modified")
    assert status == 200 and etag and modified and len(body) > 100_000
    status, body, res = self.request("GET", path, headers={"If-None-Match": etag})
    assert status == 304 and body == b"" and res.getheader("ETag") == etag
    assert self.request("GET", path, headers={"If-Modified-Since": modified})[0] == 304
    assert self.request("GET", path, headers={"If-None-Match": '"0-0"'})[0] == 200
    # gzip is its own entity; either tag matches the same file
    status, _, res = self.request("GET", path, headers={"Accept-Encoding": "gzip"})
    gz_tag = res.getheader("ETag")
    assert status == 200 and gz_tag.endswith('-gz"') and res.getheader("Vary") == "Accept-Encoding"
    assert self.request("GET", path, headers={"If-None-Match": gz_tag})[0] == 304

  def test_page_dir(self):
    # WEBHUD_PAGE_DIR names an Oceanfront View checkout: the page, three.js and the model are served from it
    page = os.path.join(self.tmp.name, "oceanfront-view")
    for rel, text in (("static/index.html", "<title>Oceanfront View</title><script src=/js/main.js></script>"),
                      ("static/js/main.js", "class CarScene {}"), ("static/sw.js", "// worker"),
                      ("third_party/three/OrbitControls.js", "class OrbitControls {}"), ("third_party/models/car.glb", "glTF"),
                      ("dbc/fisker_ocean_adas_world.dbc", "BO_ 1 X: 8 ADAS")):
      os.makedirs(os.path.dirname(os.path.join(page, rel)), exist_ok=True)
      with open(os.path.join(page, rel), "w") as f:
        f.write(text)
    roots = page_roots(page)
    with mock.patch.object(webhud_server, "STATIC_ROOTS", roots), mock.patch.object(webhud_server, "STATIC_DIR", roots[""]):
      status, body, res = self.request("GET", "/")
      assert status == 200 and b"Oceanfront View" in body and res.getheader("Cache-Control") == "no-cache"
      status, body, res = self.request("GET", "/js/main.js", headers={"Accept-Encoding": "gzip"})
      assert status == 200 and res.getheader("Content-Encoding") == "gzip" and b"CarScene" in body
      status, body, res = self.request("GET", "/vendor/OrbitControls.js")
      assert status == 200 and b"OrbitControls" in body and "max-age" in res.getheader("Cache-Control")
      status, body, res = self.request("GET", "/models/car.glb")
      assert status == 200 and body == b"glTF" and res.getheader("Content-Type") == "model/gltf-binary"
      assert self.request("GET", "/sw.js")[2].getheader("Cache-Control") == "no-cache"
      for path in ("/settings", "/../../server.py", "/vendor/../../../sunnypilot/webhud/server.py"):
        status, body, _ = self.request("GET", path)
        assert status == 200 and b"Oceanfront View" in body       # deep links and traversal fall back to the app shell
      assert b"MRR_" in self.request("GET", "/dbc/fisker_ocean_mrr.dbc")[1]   # the radar DBC still comes from opendbc

  def test_overrides_api(self):
    status, body, _ = self.request("GET", "/api/overrides")
    data = json.loads(body)
    assert status == 200 and data["supported"] and [t["message"] for t in data["tables"]] == ["ICC_0x35B"]
    table = data["tables"][0]
    assert table["address"] == 0x35B and not table["customized"]
    sig = next(s for s in table["signals"] if s["name"] == "ICC_BSDSetting")
    assert sig["default"] == self.saved["ICC_BSDSetting"] and sig["values"]["2"] and not sig["locked"]
    assert next(s for s in table["signals"] if s["name"] == "ICC_ViewReq")["locked"]   # camera-view requests always pass through

    status, body, _ = self.request("PUT", "/api/overrides", {"ICC_0x35B": {"ICC_BSDSetting": 9}})
    assert status == 400 and b"outside" in body
    status, body, _ = self.request("PUT", "/api/overrides", {"ICC_0x52A": {"ICC_ACCSwt": 1}})
    assert status == 400 and b"not an overridable message" in body
    status, body, _ = self.request("PUT", "/api/overrides", {"ICC_0x35B": {"ICC_BSDSetting": 2}})
    assert status == 200 and self.params.get(PARAM) == {"ICC_0x35B": {"ICC_BSDSetting": 2}}
    assert json.loads(body)["tables"][0]["customized"]

    status, _, _ = self.request("PUT", "/api/overrides", {"ICC_0x35B": {}}, headers={"Origin": "http://evil.example"})
    assert status == 403

    status, body, _ = self.request("DELETE", "/api/overrides?message=ICC_0x35B")
    assert status == 200 and self.params.get(PARAM) is None

  def test_params_allowlist(self):
    status, body, _ = self.request("PUT", "/api/params", {"ExperimentalMode": True, "LongitudinalPersonality": 2})
    assert status == 200 and json.loads(body)["ExperimentalMode"] is True
    assert self.request("PUT", "/api/params", {"LongitudinalPersonality": 7})[0] == 400
    assert self.request("PUT", "/api/params", {"DisableUpdates": True})[0] == 400

  def test_websocket_streams_demo_ticks(self):
    sock = socket.create_connection(("127.0.0.1", self.port), timeout=10)
    key = base64.b64encode(os.urandom(16)).decode()
    headers = ["GET /ws HTTP/1.1", f"Host: 127.0.0.1:{self.port}", "Upgrade: websocket", "Connection: Upgrade",
               f"Sec-WebSocket-Key: {key}", "Sec-WebSocket-Version: 13"]
    sock.sendall(("\r\n".join(headers) + "\r\n\r\n").encode())
    reader = sock.makefile("rb")
    assert b"101" in reader.readline()
    while reader.readline() not in (b"\r\n", b""):
      pass
    sock.sendall(encode_frame(json.dumps({"type": "replay", "action": "demo"}).encode(), OP_TEXT, mask=b"abcd"))

    # the first tick is a snapshot (reset) of the current state; then the demo's frames and services flow
    seen, ticks = {}, []
    acc = self.engine.builder.dbc.by_name["ADAS_0x31C"]
    end = time.monotonic() + 10

    def acc_frames(tick):
      return [f for _, batch in tick["can"] for f in batch if f[0] == acc.address]
    while time.monotonic() < end and not any(acc_frames(t) and t["mode"] == "replay" for t in ticks):
      _, op, payload = read_frame(reader)
      msg = json.loads(payload)
      seen[msg["type"]] = msg["data"]
      if msg["type"] == "tick":
        ticks.append(msg["data"])
    sock.close()
    assert seen["hello"]["version"]
    assert ticks[0]["reset"]
    tick = next(t for t in ticks if acc_frames(t) and t["mode"] == "replay")
    assert tick["replay"]["route"] == "demo" and tick["brand"] == "fisker"
    frame = acc_frames(tick)[-1]
    assert frame[1] == 2 and acc.decode(bytes.fromhex(frame[2]))["ADAS_AccTrgSpdDisp"] == 60
    cs = next(d for w, _, d in tick["op"] if w == "carState")
    assert cs["vEgo"] > 0
