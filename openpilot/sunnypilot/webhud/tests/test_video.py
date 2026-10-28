"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
import json
import socket
from types import SimpleNamespace as NS

from openpilot.common.test import OpenpilotTestCase
from openpilot.sunnypilot.webhud.video import (FLAG_KEY, FRAME_HEADER, MAX_QUEUED_FRAMES, V4L2_BUF_FLAG_KEYFRAME,
                                               VideoViewer, camera_transforms, frame_message, model_overlay)
from openpilot.sunnypilot.webhud.websocket import OP_BINARY, OP_TEXT, WebSocket, read_frame


def project(m, p):
  u = [sum(m[r][c] * p[c] for c in range(3)) for r in range(3)]
  return u[0] / u[2], u[1] / u[2]


class TestGeometry(OpenpilotTestCase):
  def test_uncalibrated_sends_only_intrinsics(self):
    msg = camera_transforms("mici", "os04c10", {"road": (1280, 720)}, None, None)
    road = msg["cameras"]["road"]
    assert not msg["calibrated"] and "M" not in road
    # the whole 1344x760 frame is resized to 1280x720: the principal point lands in the middle
    assert road["K"][0][2] == 640.0 and road["K"][1][2] == 360.0

  def test_straight_ahead_projects_to_the_centre(self):
    msg = camera_transforms("mici", "os04c10", {"road": (1280, 720), "wide": (1280, 720)}, [0, 0, 0], [0, 0, 0])
    assert msg["calibrated"]
    for cam in ("road", "wide"):
      m = msg["cameras"][cam]["M"]
      x, y = project(m, [1000.0, 0.0, 0.0])          # far ahead on the camera's axis: the vanishing point
      assert abs(x - 640) < 1 and abs(y - 360) < 1
      x, y = project(m, [20.0, 0.0, 1.22])           # the road under the path: below the horizon
      assert abs(x - 640) < 1 and y > 380
      x, _ = project(m, [20.0, 2.0, 1.22])           # y is right in the car frame
      assert x > 640

  def test_pitch_moves_the_horizon(self):
    flat = camera_transforms("tici", "ox03c10", {"road": (1152, 720)}, [0, 0, 0], None)["cameras"]["road"]["M"]
    down = camera_transforms("tici", "ox03c10", {"road": (1152, 720)}, [0, 0.05, 0], None)["cameras"]["road"]["M"]
    assert project(down, [1000.0, 0, 0])[1] != project(flat, [1000.0, 0, 0])[1]


def _line(xs, ys, zs):
  return NS(x=xs, y=ys, z=zs)


class TestOverlay(OpenpilotTestCase):
  def test_model_overlay(self):
    model = NS(frameId=42, frameIdExtra=43, position=_line([0, 10], [0.1, 0.2], [0, 0.1]),
               laneLines=[_line([0, 10], [-1.8, -1.8], [0, 0])] * 4, laneLineProbs=[0.9, 0.8, 0.7, 0.1],
               roadEdges=[_line([0, 10], [-5, -5], [0, 0])] * 2, roadEdgeStds=[0.2, 0.3],
               acceleration=NS(x=[0.5, 0.25]))
    lead = NS(present=True, dRel=30.0, yRel=1.0, vRel=-2.0)
    radar = NS(leadOne=lead, leadTwo=NS(present=False))
    out = model_overlay(model, radar, NS(enabled=True, experimentalMode=False), NS(allowThrottle=True), True, 1.3, 0.04)
    assert out["frameId"] == 42 and out["frameIdExtra"] == 43
    assert out["path"] == [[0, 0.14, 0], [10, 0.24, 0.1]]       # camera offset added, as the UI does
    assert out["leads"] == [{"d": 30.0, "y": -0.96, "v": -2.0}]  # radar's y is left
    assert out["engaged"] and out["longControl"] and out["pathZ"] == 1.3
    json.dumps(out)

  def test_frame_message(self):
    idx = NS(flags=V4L2_BUF_FLAG_KEYFRAME, frameId=7, timestampEof=123456789)
    payload, key = frame_message("wide", NS(idx=idx, header=b"\x00\x00\x00\x01\x67", data=b"\x00\x00\x00\x01\x65"))
    kind, flags, cam, frame_id, ts = FRAME_HEADER.unpack_from(payload)
    assert key and flags == FLAG_KEY and cam == 1 and frame_id == 7 and ts == 123456789
    assert payload[FRAME_HEADER.size:] == b"\x00\x00\x00\x01\x67\x00\x00\x00\x01\x65"


class TestViewer(OpenpilotTestCase):
  def setUp(self):
    super().setUp()
    self.server_sock, self.client_sock = socket.socketpair()
    self.rfile = self.client_sock.makefile("rb")

  def tearDown(self):
    self.server_sock.close()
    self.client_sock.close()
    super().tearDown()

  def test_waits_for_a_keyframe_and_skips_a_backlog(self):
    # a viewer whose sender is held up: frames pile up in its queue
    viewer = VideoViewer(WebSocket(self.server_sock, self.server_sock.makefile("rb")))
    viewer.alive = False   # stop its sender so the queue can be inspected
    viewer.push_frame("road", b"delta", False)
    assert viewer._frames == 0                 # nothing before the first keyframe
    viewer.push_frame("wide", b"key", True)
    assert viewer._frames == 0                 # not the camera it watches
    viewer.push_frame("road", b"key", True)
    for _ in range(MAX_QUEUED_FRAMES - 1):
      viewer.push_frame("road", b"delta", False)
    assert viewer._frames == MAX_QUEUED_FRAMES
    viewer.push_text("model")
    viewer.push_frame("road", b"delta", False)  # too far behind: the backlog goes, wait for a keyframe
    assert viewer._frames == 0 and viewer.waiting_key and list(viewer._queue) == ["model"]
    viewer.push_frame("road", b"key2", True)
    assert list(viewer._queue) == ["model", b"key2"]

  def test_sends_binary_frames_and_text(self):
    viewer = VideoViewer(WebSocket(self.server_sock, self.server_sock.makefile("rb")))
    viewer.push_text('{"type":"hello"}')
    viewer.push_frame("road", b"\x01key", True)
    assert read_frame(self.rfile) == (True, OP_TEXT, b'{"type":"hello"}')
    assert read_frame(self.rfile) == (True, OP_BINARY, b"\x01key")
    viewer.set_camera("wide")
    assert viewer.camera == "wide" and viewer.waiting_key
    viewer.close()
