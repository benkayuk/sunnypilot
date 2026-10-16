#!/usr/bin/env python3
"""
Remote-control server for the fisker port.

Runs as a sunnypilot daemon, binds to 0.0.0.0:8899 on the Comma 3X. A phone on
the same wifi network opens http://<comma-ip>:8899/ in Chrome and uses the
served webapp to send steering commands. The commands are written to Params;
the fisker carcontroller reads them each tick and (when the safety gates pass)
substitutes the remote angle for its lateral planner's output.

Safety / design notes:
  * Pure local-network HTTP. No TLS, no auth. Trusted-wifi only.
  * Default-off at boot: RemoteControlEnabled is CLEAR_ON_MANAGER_START.
  * Hard angle cap (±MAX_ANGLE_DEG) enforced on EVERY command, server-side.
  * Freshness watchdog is enforced in the carcontroller — carstate reads the
    last-updated timestamp and treats commands older than ~300 ms as stale.
  * The actual lateral-control safety gates (MADS engaged, low speed,
    driver intervention) live in fisker/carcontroller.py and run every tick.
"""

from __future__ import annotations

import http.server
import json
import os
import socketserver
import time
from pathlib import Path

from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog


PORT = int(os.environ.get("REMOTE_CONTROL_PORT", "8899"))
STATIC_DIR = Path(__file__).parent / "static"

# Hard angle cap (deg). The fisker ANGLE_LIMITS.max_angle is 600°, but allowing
# the phone to request anywhere near that from a touchscreen slider is reckless
# — hands aren't precise enough. 90° covers a full quarter-turn (sharp parking
# maneuvers) without letting a stray finger put the wheel at lock.
MAX_ANGLE_DEG = 90.0


class Handler(http.server.BaseHTTPRequestHandler):
  # Populated in main() before the server starts.
  params: Params = None  # type: ignore[assignment]

  # Silence the default access-log spam (BaseHTTPRequestHandler prints every
  # request to stderr by default, which fills journald during active steering).
  def log_message(self, fmt, *args):  # noqa: A003
    pass

  def _send(self, status: int, body: bytes | str = b"", ctype: str = "application/json") -> None:
    self.send_response(status)
    self.send_header("Content-Type", ctype)
    # CORS: trusted-wifi only, but keeping this open avoids a confusing
    # preflight failure if someone opens the UI from a different origin.
    self.send_header("Access-Control-Allow-Origin", "*")
    self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    self.send_header("Access-Control-Allow-Headers", "Content-Type")
    self.send_header("Cache-Control", "no-store")
    self.end_headers()
    if isinstance(body, str):
      body = body.encode()
    if body:
      self.wfile.write(body)

  def do_OPTIONS(self):  # noqa: N802
    self._send(204)

  def do_GET(self):  # noqa: N802
    if self.path in ("/", "/index.html"):
      self._serve_static("index.html", "text/html; charset=utf-8")
    elif self.path == "/style.css":
      self._serve_static("style.css", "text/css; charset=utf-8")
    elif self.path == "/app.js":
      self._serve_static("app.js", "application/javascript; charset=utf-8")
    elif self.path == "/status":
      self._send(200, self._status_json())
    else:
      self._send(404, json.dumps({"error": "not found"}))

  def do_POST(self):  # noqa: N802
    length = int(self.headers.get("Content-Length", 0))
    body = self.rfile.read(length) if length else b""
    try:
      data = json.loads(body) if body else {}
    except json.JSONDecodeError:
      self._send(400, json.dumps({"error": "bad json"}))
      return

    if self.path == "/steer":
      try:
        angle = float(data.get("angle", 0.0))
      except (TypeError, ValueError):
        self._send(400, json.dumps({"error": "bad angle"}))
        return
      # Hard safety cap — clamp before writing anywhere.
      if angle > MAX_ANGLE_DEG:
        angle = MAX_ANGLE_DEG
      elif angle < -MAX_ANGLE_DEG:
        angle = -MAX_ANGLE_DEG
      # Convention flip: the webapp sends "drag-right = positive" because
      # that's what a human expects from a steering input. openpilot's
      # internal frame is left-positive (CCW = +), matching OEM EPS_SteerWhlAgSig
      # and ADAS_LatCtrl_SteerAnReq (see fisker-ocean-port-status memory).
      # Negate here so the stored param lands in openpilot's convention and
      # the carcontroller can use it directly, without having to carry a
      # magic "remote-is-reversed" flag through the control path.
      stored_angle = -angle
      self.params.put("RemoteSteerAngle", str(stored_angle))
      self.params.put("RemoteSteerLastUpdate", str(time.time_ns()))
      self._send(200, json.dumps({"ok": True, "angle": angle}))

    elif self.path == "/arm":
      # Arming also seeds a fresh zero angle + timestamp so the first few
      # ticks after enabling don't see a stale "last angle" from a previous
      # session.
      self.params.put("RemoteSteerAngle", "0")
      self.params.put("RemoteSteerLastUpdate", str(time.time_ns()))
      self.params.put_bool("RemoteControlEnabled", True)
      self._send(200, json.dumps({"ok": True}))

    elif self.path == "/disarm":
      self.params.put_bool("RemoteControlEnabled", False)
      self.params.put("RemoteSteerAngle", "0")
      self._send(200, json.dumps({"ok": True}))

    else:
      self._send(404, json.dumps({"error": "not found"}))

  # ------------------------------------------------------------------- helpers

  def _status_json(self) -> str:
    now_ns = time.time_ns()
    try:
      last_ns = int((self.params.get("RemoteSteerLastUpdate") or b"0").decode())
    except (ValueError, AttributeError):
      last_ns = 0
    try:
      angle = float((self.params.get("RemoteSteerAngle") or b"0").decode())
    except (ValueError, AttributeError):
      angle = 0.0
    return json.dumps({
      "armed": self.params.get_bool("RemoteControlEnabled"),
      "angle": angle,
      "ageMs": (now_ns - last_ns) / 1_000_000.0 if last_ns > 0 else None,
      "maxAngleDeg": MAX_ANGLE_DEG,
      "serverTimeNs": now_ns,
    })

  def _serve_static(self, name: str, ctype: str) -> None:
    p = STATIC_DIR / name
    if not p.exists():
      self._send(404, json.dumps({"error": "static missing: " + name}))
      return
    try:
      self._send(200, p.read_bytes(), ctype)
    except OSError as e:
      self._send(500, json.dumps({"error": str(e)}))


class ThreadingServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
  """One thread per request. Phone + optional desktop-browser debug client at
  the same time is well within budget."""
  daemon_threads = True
  allow_reuse_address = True


def main():
  Handler.params = Params()
  # Sanity-reset state at daemon start, in case manager restarted us mid-drive
  # or a param write got half-committed.
  Handler.params.put_bool("RemoteControlEnabled", False)
  Handler.params.put("RemoteSteerAngle", "0")
  Handler.params.put("RemoteSteerLastUpdate", "0")

  cloudlog.info(f"remote_control_server: binding 0.0.0.0:{PORT}")
  with ThreadingServer(("0.0.0.0", PORT), Handler) as httpd:
    httpd.serve_forever()


if __name__ == "__main__":
  main()
