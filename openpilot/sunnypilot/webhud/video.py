"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.

The HUD's camera view: the road camera as H.264, and what the comma's own driving screen draws over it,
on a WebSocket of its own (`/video`).

The video is the livestream encoder's output (encoderd --stream: 1280x720 H.264, a keyframe every 5
frames), passed through as it is. While a viewer is watching, `WebHudVideo` is set and the manager runs
camerad and stream_encoderd (process_config.py), onroad too; once the last viewer has been gone for
LINGER_S it is cleared again. Nothing is drawn here: the page decodes the frames (WebCodecs) and draws
the model's path, lane lines, road edges and leads over them, matched by frame id, with the projection
sent here (`calib`), the way selfdrive/ui's augmented road view and model renderer do it.

Server -> page:
  binary  FRAME_HEADER (kind=1, flags bit0 = keyframe, camera index, frameId, timestampEof ns)
          followed by the Annex B access unit (SPS/PPS included on keyframes)
  text    {type: hello, cameras: [...]}
          {type: calib, calibrated, cameras: {road|wide: {width, height, K, M}}}    M = K . view_from_calib:
                                         car frame (x forward, y right, z down) to stream pixels
          {type: model, frameId, frameIdExtra, path, lanes, laneProbs, edges, edgeStds, accel, leads,
           pathZ, engaged, experimental, allowThrottle, longControl}               points are [x, y, z]
          {type: error, message}
Page -> server:
  {type: camera, camera: road|wide}, {type: ping, t}
"""
import json
import struct
import threading
import time
from collections import deque

from openpilot.common.swaglog import cloudlog
from openpilot.sunnypilot.webhud.websocket import WebSocket

PARAM = "WebHudVideo"
FRAME_HEADER = struct.Struct("<BBHIQ")   # kind, flags, camera, frameId, timestampEof (ns)
KIND_FRAME = 1
FLAG_KEY = 1
V4L2_BUF_FLAG_KEYFRAME = 0x8
CAMERAS = ("road", "wide")
# camera -> (encoder service, camera state service, DeviceCameraConfig field)
CAMERA_SOURCES = {
  "road": ("livestreamNarrowRoadEncodeData", "narrowRoadCameraState", "narrow_road"),
  "wide": ("livestreamWideRoadEncodeData", "wideRoadCameraState", "wide_road"),
}
OVERLAY_SERVICES = ["modelV2", "radarState", "extrinsicsCalibration", "selfdriveState", "longitudinalPlan",
                    "carParams", "deviceState", "narrowRoadCameraState", "wideRoadCameraState"]
LINGER_S = 10.0         # keep the encoder up this long after the last viewer leaves (a camera switch, a reconnect)
PARAM_REFRESH_S = 2.0   # re-assert the param (the manager clears it when it restarts)
MAX_QUEUED_FRAMES = 6   # a viewer this far behind skips to the next keyframe (at most 5 frames away)
MAX_QUEUED_TEXT = 40
CALIBRATED = 1          # log.ExtrinsicsCalibration.Status.calibrated
HEIGHT_INIT = 1.22      # selfdrive/locationd/calibrationd.py HEIGHT_INIT


# ---- geometry (the same as selfdrive/ui/onroad/augmented_road_view.py) ------------------------------

def _round(m, nd: int = 4) -> list:
  return [[round(float(v), nd) for v in row] for row in m]


def camera_transforms(device_type: str, sensor: str, sizes: dict[str, tuple[int, int]],
                      rpy: list[float] | None, wide_euler: list[float] | None) -> dict:
  """K (camera intrinsics scaled to the stream: the encoder resizes the whole frame, so x and y scale
  apart) and M = K . view_from_calib for each camera, or only K before calibration has converged."""
  import numpy as np
  from openpilot.common.transformations.camera import DEVICE_CAMERAS, view_frame_from_device_frame
  from openpilot.common.transformations.orientation import rot_from_euler

  config = DEVICE_CAMERAS.get((device_type, sensor)) or DEVICE_CAMERAS[("tici", "ar0231")]
  calibrated = rpy is not None and len(rpy) == 3
  view_from_calib = {}
  if calibrated:
    device_from_calib = rot_from_euler(rpy)
    view_from_calib["road"] = view_frame_from_device_frame @ device_from_calib
    wide_from_device = rot_from_euler(wide_euler) if wide_euler is not None and len(wide_euler) == 3 else np.eye(3)
    view_from_calib["wide"] = view_frame_from_device_frame @ wide_from_device @ device_from_calib

  cameras = {}
  for cam, (width, height) in sizes.items():
    cc = getattr(config, CAMERA_SOURCES[cam][2])
    if not cc.width or not width:
      continue
    k = np.diag([width / cc.width, height / cc.height, 1.0]) @ cc.intrinsics
    entry = {"width": width, "height": height, "K": _round(k)}
    if calibrated:
      entry["M"] = _round(k @ view_from_calib[cam], 6)
    cameras[cam] = entry
  return {"type": "calib", "calibrated": calibrated, "cameras": cameras}


def _xyz(line, y_offset: float = 0.0) -> list[list[float]]:
  xs, ys, zs = line.x, line.y, line.z
  return [[round(xs[i], 2), round(ys[i] + y_offset, 3), round(zs[i], 3)] for i in range(min(len(xs), len(ys), len(zs)))]


def model_overlay(model, radar, selfdrive, plan, long_control: bool, path_z: float, camera_offset: float) -> dict:
  """What the model renderer draws, in the car frame (x forward, y right, z down)."""
  leads = []
  if radar is not None:
    for lead in (radar.leadOne, radar.leadTwo):
      if lead.present:
        leads.append({"d": round(lead.dRel, 2), "y": round(-lead.yRel + camera_offset, 2), "v": round(lead.vRel, 2)})
  return {
    "type": "model",
    "frameId": model.frameId,
    "frameIdExtra": model.frameIdExtra,
    "path": _xyz(model.position, camera_offset),
    "lanes": [_xyz(ln, camera_offset) for ln in model.laneLines],
    "laneProbs": [round(p, 3) for p in model.laneLineProbs],
    "edges": [_xyz(e, camera_offset) for e in model.roadEdges],
    "edgeStds": [round(s, 3) for s in model.roadEdgeStds],
    "accel": [round(a, 2) for a in model.acceleration.x],
    "leads": leads,
    "pathZ": round(path_z, 3),
    "engaged": bool(selfdrive.enabled) if selfdrive is not None else False,
    "experimental": bool(selfdrive.experimentalMode) if selfdrive is not None else False,
    "allowThrottle": bool(plan.allowThrottle) if plan is not None else True,
    "longControl": long_control,
  }


def frame_message(camera: str, encode_data) -> tuple[bytes, bool]:
  idx = encode_data.idx
  key = bool(idx.flags & V4L2_BUF_FLAG_KEYFRAME)
  head = FRAME_HEADER.pack(KIND_FRAME, FLAG_KEY if key else 0, CAMERAS.index(camera), idx.frameId, idx.timestampEof)
  return head + bytes(encode_data.header) + bytes(encode_data.data), key


# ---- viewers -------------------------------------------------------------------------------------

class VideoViewer:
  """One /video socket. Frames queue up to MAX_QUEUED_FRAMES; past that the backlog goes and the viewer
  waits for the next keyframe, so a slow link drops a fraction of a second, never piles up latency."""

  def __init__(self, ws: WebSocket, camera: str = "road"):
    self.ws = ws
    self.camera = camera if camera in CAMERAS else "road"
    self.alive = True
    self.waiting_key = True
    self._queue: deque[bytes | str] = deque()
    self._frames = 0
    self._texts = 0
    self._cv = threading.Condition()
    threading.Thread(target=self._sender, name="webhud-video-send", daemon=True).start()

  def set_camera(self, camera: str) -> None:
    if camera in CAMERAS and camera != self.camera:
      with self._cv:
        self.camera = camera
        self.waiting_key = True
        self._drop_frames()

  def _drop_frames(self) -> None:
    self._queue = deque(m for m in self._queue if isinstance(m, str))
    self._frames = 0

  def push_frame(self, camera: str, payload: bytes, key: bool) -> None:
    with self._cv:
      if camera != self.camera:
        return
      if self._frames >= MAX_QUEUED_FRAMES:
        self._drop_frames()
        self.waiting_key = True
      if self.waiting_key:
        if not key:
          return
        self.waiting_key = False
      self._queue.append(payload)
      self._frames += 1
      self._cv.notify()

  def push_text(self, text: str) -> None:
    with self._cv:
      if self._texts >= MAX_QUEUED_TEXT:
        for i, m in enumerate(self._queue):
          if isinstance(m, str):
            del self._queue[i]
            self._texts -= 1
            break
      self._queue.append(text)
      self._texts += 1
      self._cv.notify()

  def _sender(self) -> None:
    while self.alive:
      with self._cv:
        while self.alive and not self._queue:
          self._cv.wait(1.0)
        if not self.alive:
          break
        msg = self._queue.popleft()
        if isinstance(msg, str):
          self._texts -= 1
        else:
          self._frames -= 1
      try:
        if isinstance(msg, str):
          self.ws.send_text(msg)
        else:
          self.ws.send_binary(msg)
      except Exception:
        self.close()

  def close(self) -> None:
    self.alive = False
    with self._cv:
      self._cv.notify()
    self.ws.close()


class VideoHub:
  """Turns the livestream encoder on while anyone watches, and fans its frames and the overlay out."""

  def __init__(self, params):
    self.params = params
    self.viewers: set[VideoViewer] = set()
    self.lock = threading.Lock()
    self.error: str | None = None
    self.stop_event = threading.Event()
    self._thread: threading.Thread | None = None
    self._last_viewer_t = 0.0
    self._param_on = False
    self._param_t = 0.0
    self._calib: str | None = None
    self._calib_t = 0.0
    self._long_control: bool | None = None
    self._model: str | None = None
    self._socks: dict = {}
    self._poller = None
    self._sm = None
    self._sizes: dict[str, tuple[int, int]] = {}
    self._camera_offset = 0.0
    self._offset_t = 0.0

  # viewers ------------------------------------------------------------------
  def add(self, viewer: VideoViewer) -> None:
    viewer.push_text(json.dumps({"type": "hello", "cameras": list(CAMERAS)}))
    if self.error:
      viewer.push_text(json.dumps({"type": "error", "message": self.error}))
    for cached in (self._calib, self._model):
      if cached:
        viewer.push_text(cached)
    with self.lock:
      self.viewers.add(viewer)
      self._last_viewer_t = time.monotonic()
      if self._thread is None or not self._thread.is_alive():
        self._thread = threading.Thread(target=self.run, name="webhud-video", daemon=True)
        self._thread.start()

  def remove(self, viewer: VideoViewer) -> None:
    with self.lock:
      self.viewers.discard(viewer)
      self._last_viewer_t = time.monotonic()

  def _broadcast(self, text: str) -> None:
    for v in self._alive():
      v.push_text(text)

  def _alive(self) -> list[VideoViewer]:
    with self.lock:
      return [v for v in self.viewers if v.alive]

  def _set_param(self, on: bool) -> None:
    now = time.monotonic()
    if on == self._param_on and (not on or now - self._param_t < PARAM_REFRESH_S):
      return
    try:
      self.params.put_bool(PARAM, on)
    except Exception:
      cloudlog.exception("webhud: video param")
    self._param_on, self._param_t = on, now

  # main loop ------------------------------------------------------------------
  def run(self) -> None:
    try:
      while not self.stop_event.is_set():
        viewers = self._alive()
        now = time.monotonic()
        if viewers:
          self._last_viewer_t = now
        elif now - self._last_viewer_t > LINGER_S:
          with self.lock:
            if not self.viewers:
              self._thread = None   # add() starts another
              break
          continue
        self._set_param(True)
        if not viewers:
          time.sleep(0.25)
          continue
        try:
          self._open()
          self._step({v.camera for v in viewers})
        except Exception as e:
          msg = f"{type(e).__name__}: {e}"
          if msg != self.error:
            cloudlog.exception("webhud: video")
            self.error = msg
            self._broadcast(json.dumps({"type": "error", "message": msg}))
          time.sleep(1.0)
    finally:
      self._set_param(False)
      self._close_socks()

  def _open(self) -> None:
    if self._sm is not None:
      return
    import openpilot.cereal.messaging as messaging
    self._poller = messaging.Poller()
    self._socks = {cam: messaging.sub_sock(CAMERA_SOURCES[cam][0], poller=self._poller, conflate=False) for cam in CAMERAS}
    self._sm = messaging.SubMaster(OVERLAY_SERVICES)
    self.error = None
    try:   # carParams is published rarely; the UI reads the param too
      from opendbc.car.structs import car
      if cp := self.params.get("CarParams"):
        self._long_control = bool(messaging.log_from_bytes(cp, car.CarParams).openpilotLongitudinalControl)
    except Exception:
      pass

  def _close_socks(self) -> None:
    self._socks, self._poller, self._sm = {}, None, None

  def _step(self, wanted: set[str]) -> None:
    import openpilot.cereal.messaging as messaging
    self._poller.poll(25)
    for cam, sock in self._socks.items():
      for msg in messaging.drain_sock(sock):
        if cam not in wanted:
          continue
        data = getattr(msg, msg.which())
        if data.width and (data.width, data.height) != self._sizes.get(cam):
          self._sizes[cam] = (data.width, data.height)
          self._calib = None   # recompute for the new size
        payload, key = frame_message(cam, data)
        for v in self._alive():
          v.push_frame(cam, payload, key)

    sm = self._sm
    sm.update(0)
    now = time.monotonic()
    if self._calib is None or sm.updated["extrinsicsCalibration"] or now - self._calib_t > 2.0:
      self._calib_t = now
      self._update_calib()
    if sm.updated["modelV2"]:
      self._update_model()

  def _update_calib(self) -> None:
    sm = self._sm
    if not self._sizes:
      return
    calib = sm["extrinsicsCalibration"]
    calibrated = sm.recv_frame["extrinsicsCalibration"] > 0 and calib.calStatus == CALIBRATED and len(calib.rpyCalib) == 3
    device_type = str(sm["deviceState"].deviceType) if sm.recv_frame["deviceState"] > 0 else "tici"
    sensor = str(sm["narrowRoadCameraState"].sensor) if sm.recv_frame["narrowRoadCameraState"] > 0 else "ar0231"
    msg = camera_transforms(device_type, sensor, self._sizes,
                            list(calib.rpyCalib) if calibrated else None,
                            list(calib.wideFromDeviceEuler) if calibrated else None)
    text = json.dumps(msg, separators=(",", ":"))
    if text != self._calib:
      self._calib = text
      self._broadcast(text)

  def _update_model(self) -> None:
    sm = self._sm
    now = time.monotonic()
    if now - self._offset_t > 3.0:
      self._offset_t = now
      try:
        self._camera_offset = float(self.params.get("CameraOffset", return_default=True) or 0.0)
      except Exception:
        self._camera_offset = 0.0
    calib = sm["extrinsicsCalibration"]
    path_z = calib.height[0] if sm.recv_frame["extrinsicsCalibration"] > 0 and len(calib.height) else HEIGHT_INIT
    radar = sm["radarState"] if sm.valid["radarState"] else None
    if sm.updated["carParams"]:
      self._long_control = bool(sm["carParams"].openpilotLongitudinalControl)
    long_control = bool(self._long_control)
    msg = model_overlay(sm["modelV2"], radar, sm["selfdriveState"], sm["longitudinalPlan"], long_control, path_z, self._camera_offset)
    self._model = json.dumps(msg, separators=(",", ":"))
    self._broadcast(self._model)

  def stop(self) -> None:
    self.stop_event.set()
    with self.lock:
      viewers = list(self.viewers)
    for v in viewers:
      v.close()
