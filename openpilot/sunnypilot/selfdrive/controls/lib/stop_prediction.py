"""
Stop assist, the model side: whether the driving model predicts a stop ahead (a red light, a stop sign) and the
acceleration it wants for it, published as carControlSP.stopAssist for car ports where the car's own ACC drives and
the port can only lower its request (Fisker: opendbc/car/fisker/stop_assist.py, FiskerStopAssist).

A stop is predicted when the model says shouldStop (which it only does close to standstill), or when the lowest speed
in its plan, STOP_HORIZON s long, is under STOP_SPEED_FRACTION of the current speed (at least STOP_SPEED_FLOOR). It
must hold for ONSET_TIME with the model asking for at least ONSET_ACCEL of braking, and ends once it hasn't held for
RELEASE_TIME. Replayed on the Fisker's recorded drives, this flags stops from 45-60 km/h 8-13 s (40-110 m) ahead, with
one 0.2 s false slow-down in 72 min of the car's ACC driving with no stop coming. The planned speed 4 s ahead instead
flagged them only 3-6 s (10-25 m) ahead, too late to stop at -1.5 m/s^2.

FiskerStopAssistTest swaps the model for a fixed pulse, for checking how the car takes it in an empty lot: each time
ACC engages between 20 and 40 km/h, TEST_ACCEL for TEST_DURATION after TEST_DELAY.
"""
import numpy as np

from openpilot.common.constants import CV
from openpilot.common.realtime import DT_CTRL
from openpilot.selfdrive.modeld.constants import ModelConstants

STOP_HORIZON = 10.0        # s, the model's whole plan
STOP_SPEED_FRACTION = 0.15
STOP_SPEED_FLOOR = 1.5     # m/s
STOP_MIN_SPEED = 1.0       # m/s: below this the planned speed says nothing
ONSET_ACCEL = -0.3         # m/s^2
ONSET_TIME = 0.3           # s
RELEASE_TIME = 0.5         # s

TEST_PARAM = "FiskerStopAssistTest"
TEST_MIN_SPEED = 20 * CV.KPH_TO_MS
TEST_MAX_SPEED = 40 * CV.KPH_TO_MS
TEST_DELAY = 2.0           # s
TEST_DURATION = 3.0        # s
TEST_ACCEL = -1.0          # m/s^2


def model_predicts_stop(model, v_ego: float) -> bool:
  if model.action.shouldStop:
    return True
  speeds = np.asarray(model.velocity.x)
  if len(speeds) == 0 or v_ego < STOP_MIN_SPEED:
    return False
  times = np.asarray(model.velocity.t if len(model.velocity.t) == len(speeds) else ModelConstants.T_IDXS[:len(speeds)])
  return float(speeds[times <= STOP_HORIZON].min()) < max(STOP_SPEED_FLOOR, STOP_SPEED_FRACTION * v_ego)


class StopPrediction:
  def __init__(self):
    self.active = False
    self.accel = 0.0
    self.test_enabled = False
    self._on_frames = 0
    self._off_frames = 0
    self._cruise_prev = False
    self._test_frames: int | None = None   # frames since ACC engaged for a test pulse

  def update(self, model, v_ego: float, cruise_enabled: bool, model_ok: bool = True) -> tuple[bool, float]:
    """(stop predicted, model's desired acceleration) for this frame. model_ok: modelV2 is alive and valid; when it
    isn't, the last message SubMaster holds may be stale, so no stop is predicted from it."""
    cruise_engaged = cruise_enabled and not self._cruise_prev
    self._cruise_prev = cruise_enabled
    if self.test_enabled:
      return self._test_pulse(v_ego, cruise_enabled, cruise_engaged)
    self._test_frames = None

    if not model_ok:
      self.active, self.accel = False, 0.0
      self._on_frames = self._off_frames = 0
      return self.active, self.accel

    desired = float(model.action.desiredAcceleration)
    if model_predicts_stop(model, v_ego):
      self._off_frames = 0
      self._on_frames = self._on_frames + 1 if (self.active or desired < ONSET_ACCEL) else 0
      if self._on_frames * DT_CTRL >= ONSET_TIME:
        self.active = True
    else:
      self._on_frames = 0
      self._off_frames += 1
      if self._off_frames * DT_CTRL >= RELEASE_TIME:
        self.active = False
    self.accel = desired
    return self.active, self.accel

  def _test_pulse(self, v_ego: float, cruise_enabled: bool, cruise_engaged: bool) -> tuple[bool, float]:
    if cruise_engaged:
      self._test_frames = 0 if TEST_MIN_SPEED <= v_ego <= TEST_MAX_SPEED else None
    elif not cruise_enabled:
      self._test_frames = None

    self.active = False
    if self._test_frames is not None:
      self._test_frames += 1
      t = self._test_frames * DT_CTRL
      self.active = TEST_DELAY <= t < TEST_DELAY + TEST_DURATION
    self.accel = TEST_ACCEL if self.active else 0.0
    return self.active, self.accel
