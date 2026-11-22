from types import SimpleNamespace

import numpy as np

from openpilot.common.constants import CV
from openpilot.selfdrive.modeld.constants import ModelConstants
from openpilot.sunnypilot.selfdrive.controls.lib.stop_prediction import (ONSET_TIME, RELEASE_TIME, TEST_ACCEL, TEST_DELAY,
                                                                          TEST_DURATION, StopPrediction, model_predicts_stop)

V = 50 * CV.KPH_TO_MS


def model(should_stop=False, desired=0.0, v_low=V, t_low=4.0):
  """A plan slowing from V to v_low over t_low s, then holding it."""
  t = ModelConstants.T_IDXS
  speeds = np.interp(t, [0.0, t_low, 10.0], [V, v_low, v_low]).tolist()
  return SimpleNamespace(action=SimpleNamespace(shouldStop=should_stop, desiredAcceleration=desired),
                         velocity=SimpleNamespace(x=speeds, t=t))


def frames(sp, n, md, v=V, cruise=True):
  return [sp.update(md, v, cruise) for _ in range(n)]


class TestStopPrediction:
  def test_stop_anywhere_in_the_plan(self):
    assert model_predicts_stop(model(v_low=0.0, t_low=9.0), V)
    assert model_predicts_stop(model(v_low=0.1 * V), V)
    assert not model_predicts_stop(model(v_low=0.3 * V), V), "slowing down, not stopping"
    assert model_predicts_stop(model(should_stop=True), V)
    assert not model_predicts_stop(model(v_low=0.0), 0.5), "standing still says nothing"

  def test_no_stop(self):
    sp = StopPrediction()
    assert not any(a for a, _ in frames(sp, 200, model(desired=-1.0, v_low=0.5 * V)))

  def test_onset_after_hold(self):
    for md in (model(should_stop=True, desired=-1.0), model(desired=-1.0, v_low=0.0, t_low=8.0)):
      sp = StopPrediction()
      out = frames(sp, 100, md)
      first = [a for a, _ in out].index(True)
      assert abs(first + 1 - ONSET_TIME * 100) <= 1
      assert out[-1] == (True, -1.0)

  def test_gentle_slowdown_does_not_start(self):
    sp = StopPrediction()
    assert not any(a for a, _ in frames(sp, 200, model(desired=-0.2, v_low=0.0, t_low=8.0)))

  def test_release_after_hold(self):
    sp = StopPrediction()
    frames(sp, 100, model(desired=-1.0, v_low=0.0))
    assert all(a for a, _ in frames(sp, int(RELEASE_TIME * 100) - 5, model(desired=0.5)))
    assert all(a for a, _ in frames(sp, 100, model(desired=-0.1, v_low=0.0))), "a short gap doesn't end it"
    out = frames(sp, int(RELEASE_TIME * 100) + 1, model(desired=0.5))
    assert out[-1][0] is False

  def test_stale_model_ends_it(self):
    sp = StopPrediction()
    md = model(desired=-1.0, v_low=0.0)
    frames(sp, 100, md)
    assert sp.update(md, V, True, model_ok=False) == (False, 0.0)
    assert sp.update(md, V, True)[0] is False, "the hold starts over once the model is back"

  def test_pulse(self):
    sp = StopPrediction()
    sp.test_enabled = True
    frames(sp, 10, model(), v=30 * CV.KPH_TO_MS, cruise=False)
    out = frames(sp, 600, model(), v=30 * CV.KPH_TO_MS)
    active = [i for i, (a, _) in enumerate(out) if a]
    assert abs(active[0] - TEST_DELAY * 100) <= 1 and abs(len(active) - TEST_DURATION * 100) <= 1
    assert all(out[i][1] == TEST_ACCEL for i in active)
    assert active == list(range(active[0], active[0] + len(active)))

  def test_pulse_only_on_engage_in_speed_window(self):
    for v, start_engaged in ((60 * CV.KPH_TO_MS, False), (30 * CV.KPH_TO_MS, True)):
      sp = StopPrediction()
      frames(sp, 10, model(), v=v, cruise=start_engaged)
      sp.test_enabled = True
      assert not any(a for a, _ in frames(sp, 600, model(), v=v))

  def test_pulse_ends_with_cruise(self):
    sp = StopPrediction()
    sp.test_enabled = True
    frames(sp, 1, model(), cruise=False)
    frames(sp, int(TEST_DELAY * 100) + 50, model(), v=30 * CV.KPH_TO_MS)
    assert frames(sp, 1, model(), v=30 * CV.KPH_TO_MS, cruise=False)[0][0] is False
    assert not any(a for a, _ in frames(sp, 400, model(), v=30 * CV.KPH_TO_MS, cruise=False))
