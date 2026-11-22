import math

import pytest

from openpilot.sunnypilot.selfdrive.car.fisker_takeover import DEFAULT_NM, takeover_torque


class FakeParams:
  def __init__(self, value):
    self.value = value

  def get(self, key, return_default=False):
    return self.value


@pytest.mark.parametrize("value, expected", [
  (3.0, 3.0),
  (1.5, 1.5),
  (6.4, 6.4),
  (6.5, math.inf),         # the car's own: only the EPS's ~6.5 Nm bit releases
  (None, DEFAULT_NM),
  (1.0, DEFAULT_NM),       # out of range -> default
  (9.0, DEFAULT_NM),
  (float("nan"), DEFAULT_NM),
  ("x", DEFAULT_NM),
])
def test_takeover_torque(value, expected):
  assert takeover_torque(FakeParams(value)) == expected
