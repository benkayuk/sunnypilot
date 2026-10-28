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
          {type: hud, ...}  what the comma 4's onroad screen shows besides the model (hud_state): the status that
                                         colours it, set speed, steering wheel, torque bar, alert, driver
                                         monitoring, blind spots and the confidence ball, about 20 times a second
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
HUD_SERVICES = ["carState", "controlsState", "carControl", "carOutput", "vehicleParameters", "selfdriveStateSP",
                "onroadEvents", "driverMonitoringState"]
HUD_PERIOD_S = 0.05     # the HUD's state goes out this often (the screen's filters smooth it to 60 Hz)
HUD_PARAMS = ("IsMetric", "AlwaysOnDM", "BlindSpot")
DEFAULT_MAX_LAT_ACCEL = 3.0  # m/s^2, selfdrive/ui/mici/onroad/torque_bar.py
GRAVITY = 9.81
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
    entry = {"width": width, "height": height, "K": _round(k),
             # the sensor's own frame, which the comma's screen frames (the stream is that, resized)
             "fullWidth": cc.width, "fullHeight": cc.height, "Kfull": _round(cc.intrinsics)}
    if calibrated:
      entry["M"] = _round(k @ view_from_calib[cam], 6)
      entry["Mfull"] = _round(cc.intrinsics @ view_from_calib[cam], 6)
    cameras[cam] = entry
  return {"type": "calib", "calibrated": calibrated, "cameras": cameras}


def _xyz(line, y_offset: float = 0.0) -> list[list[float]]:
  xs, ys, zs = line.x, line.y, line.z
  return [[round(xs[i], 2), round(ys[i] + y_offset, 3), round(zs[i], 3)] for i in range(min(len(xs), len(ys), len(zs)))]


def model_overlay(model, radar, selfdrive, plan, long_control: bool, path_z: float, camera_offset: float) -> dict:
  """What the model renderer draws, in the car frame (x forward, y right, z down)."""
  leads = []
  if radar is not None:
    for i, lead in enumerate((radar.leadOne, radar.leadTwo)):
      if lead.present:
        leads.append({"d": round(lead.dRel, 2), "y": round(-lead.yRel + camera_offset, 2), "v": round(lead.vRel, 2), "i": i})
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


def ui_status(ss, ss_sp, events) -> str:
  """selfdrive/ui's status (the colour of the lane lines, the torque bar, the confidence ball): the same as
  UIStateSP.update_status, with MADS."""
  state = str(ss.state)
  mads = getattr(ss_sp, "mads", None) if ss_sp is not None else None
  if state == "preEnabled":
    return "override"
  if state == "overriding":
    if mads is None or not mads.available:
      return "override"
    if any(getattr(e, "overrideLongitudinal", False) for e in events):
      return "override"
  if mads is not None and str(mads.state) in ("paused", "overriding"):
    return "override"
  if mads is None or not mads.available:
    return "engaged" if ss.enabled else "disengaged"
  if not mads.enabled and not ss.enabled:
    return "disengaged"
  if mads.enabled and ss.enabled:
    return "engaged"
  if mads.enabled:
    return "lat_only"
  if ss.enabled:
    return "long_only"
  return "disengaged"


def torque_target(cs, car_state, vp, car_control, car_output, max_lat_accel: float) -> float:
  """The torque bar's target, -1..1, before the screen's filter (selfdrive/ui/mici/onroad/torque_bar.py)."""
  if cs.lateralControlState.which() in ("angleState", "curvatureState"):
    v2 = car_state.vEgo ** 2
    actual = cs.curvature * v2
    desired = cs.desiredCurvature * v2
    # road roll counts too, less near standstill where it's less accurate
    roll = vp.roll * GRAVITY * min(1.0, max(0.0, (car_state.vEgo - 5) / 10))
    if not car_control.latActive:
      return 0.0
    return max(-1.0, min(1.0, ((actual - roll) + (desired - actual)) / (max_lat_accel or DEFAULT_MAX_LAT_ACCEL)))
  return -float(car_output.actuatorsOutput.torque)


HUD_EVENTS = ("preLaneChangeLeft", "preLaneChangeRight", "laneChange")


def hud_state(sm, started: bool, status: str, params: dict, max_lat_accel: float) -> dict:
  """What the comma 4's onroad screen draws besides the model (selfdrive/ui/mici/onroad): raw values, the
  page filters and lays them out the way the screen does."""
  cs, car_state, ss = sm["controlsState"], sm["carState"], sm["selfdriveState"]
  set_speed = car_state.vCruiseCluster or cs.deprecated.vCruise          # km/h, 255 when unset
  dm = sm["driverMonitoringState"]
  vps = dm.visionPolicyState
  model = sm["modelV2"]
  preds = model.meta.disengagePredictions
  events = [str(e.name) for e in sm["onroadEvents"]]
  alert = None
  if ss.alertSize.raw != 0:
    alert = {"text1": ss.alertText1, "text2": ss.alertText2, "size": ss.alertSize.raw, "status": ss.alertStatus.raw,
             "visual": str(ss.alertHudVisual), "type": ss.alertType}
  return {
    "type": "hud",
    "started": started,
    "status": status,
    "experimental": bool(ss.experimentalMode),
    "enabled": bool(ss.enabled),
    "vEgo": round(car_state.vEgo, 2),
    "vEgoCluster": round(car_state.vEgoCluster, 2),
    "setSpeed": round(set_speed, 1),
    "metric": params.get("IsMetric", False),
    "steeringAngle": round(car_state.steeringAngleDeg, 1),
    "torque": round(torque_target(cs, car_state, sm["vehicleParameters"], sm["carControl"], sm["carOutput"], max_lat_accel), 3),
    "torqueOut": round(-float(sm["carOutput"].actuatorsOutput.torque), 3),
    "blindspot": params.get("BlindSpot", False),
    "leftBlindspot": bool(car_state.leftBlindspot),
    "rightBlindspot": bool(car_state.rightBlindspot),
    "leftBlinker": bool(car_state.leftBlinker),
    "rightBlinker": bool(car_state.rightBlinker),
    "events": [e for e in events if e in HUD_EVENTS],
    "alert": alert,
    "dm": {
      "seen": sm.recv_frame["driverMonitoringState"] > 0,
      "active": str(dm.activePolicy) == "vision",
      "rhd": bool(dm.isRHD),
      "face": bool(vps.faceDetected),
      "awareness": round(vps.awarenessPercent, 1),
      "pitch": round(vps.pose.pitch, 3),
      "yaw": round(vps.pose.yaw, 3),
      "alwaysOn": params.get("AlwaysOnDM", False),
    },
    "brakeProb": round(max(preds.brakeDisengageProbs or [1]), 3),
    "steerProb": round(max(preds.steerOverrideProbs or [1]), 3),
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
    self._hud_t = 0.0
    self._hud_params: dict = {}
    self._hud_params_t = 0.0
    self._max_lat_accel = DEFAULT_MAX_LAT_ACCEL
    self._status = "disengaged"
    self._hud_failed = False

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
    self._sm = messaging.SubMaster(OVERLAY_SERVICES + HUD_SERVICES)
    self.error = None
    try:   # carParams is published rarely; the UI reads the param too
      from opendbc.car.structs import car
      if cp := self.params.get("CarParams"):
        car_params = messaging.log_from_bytes(cp, car.CarParams)
        self._long_control = bool(car_params.openpilotLongitudinalControl)
        self._max_lat_accel = float(car_params.maxLateralAccel) or DEFAULT_MAX_LAT_ACCEL
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
    if now - self._hud_t >= HUD_PERIOD_S:
      self._hud_t = now
      try:
        self._update_hud(now)
      except Exception:   # the mirror of the screen is extra: never let it take the video down
        if not self._hud_failed:
          cloudlog.exception("webhud: video hud")
          self._hud_failed = True

  def _update_hud(self, now: float) -> None:
    sm = self._sm
    if now - self._hud_params_t > 3.0:
      self._hud_params_t = now
      for key in HUD_PARAMS:
        try:
          self._hud_params[key] = bool(self.params.get_bool(key))
        except Exception:
          self._hud_params[key] = False
    started = bool(sm["deviceState"].started) if sm.recv_frame["deviceState"] > 0 else False
    if not started:
      self._status = "disengaged"
    elif sm.updated["selfdriveState"]:
      self._status = ui_status(sm["selfdriveState"], sm["selfdriveStateSP"], sm["onroadEvents"])
    if sm.updated["carParams"]:
      self._max_lat_accel = float(sm["carParams"].maxLateralAccel) or DEFAULT_MAX_LAT_ACCEL
    msg = hud_state(sm, started, self._status, self._hud_params, self._max_lat_accel)
    self._broadcast(json.dumps(msg, separators=(",", ":")))

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
