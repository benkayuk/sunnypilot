from types import SimpleNamespace

from openpilot.sunnypilot.selfdrive.car.nav_route_turn import NavAppRouteTurn, STALE
from openpilot.sunnypilot.selfdrive.controls.lib.route_turn import DEFAULT_LIMITS, RouteTurnLimits, route_turn_limits

DT = 0.01
S = int(1e9)


def report(distance, direction="turnRight", turn_id=1, tolerance=5.0, observed_ns=0):
  return SimpleNamespace(direction=direction, distance=distance, distanceTolerance=tolerance, observedMonoTime=observed_ns,
                         turnId=turn_id, app="com.google.android.apps.maps")


class Drive:
  """card's steps at 100 Hz, at a steady speed."""
  def __init__(self, v=5.0):
    self.turn = NavAppRouteTurn()
    self.v = v
    self.t = 10 * S

  def step(self, msg=None, limits=DEFAULT_LIMITS):
    self.t += int(DT * S)
    return self.turn.update(self.v, DT, msg, limits, now_ns=self.t)

  def run(self, seconds, every=None, make=None):
    out = None
    for i in range(round(seconds / DT)):
      msg = make(self) if every and i % round(every / DT) == 0 else None
      out = self.step(msg)
    return out


def test_nothing_until_a_report():
  d = Drive()
  assert d.run(1.0) is None


def test_counts_down_between_reports():
  d = Drive(v=5.0)
  d.step(report(100.0, observed_ns=d.t))
  direction, distance = d.run(2.0)
  assert direction == "turnRight"
  assert abs(distance - 90.0) < 0.2


def test_old_reading_is_placed_when_it_was_written():
  d = Drive(v=5.0)
  d.run(5.0)
  # written 2 s ago: 10 m have gone by since
  _, distance = d.step(report(100.0, observed_ns=d.t - 2 * S))
  assert abs(distance - 90.0) < 0.6


def test_new_reading_moves_the_turn_only_within_its_rounding():
  d = Drive(v=5.0)
  d.step(report(100.0, observed_ns=d.t))
  d.run(2.0)   # 90 m to go by our count
  _, distance = d.step(report(80.0, observed_ns=d.t))   # "80 m", give or take 5 + 3
  assert abs(distance - 88.0) < 0.2
  _, distance = d.step(report(90.0, observed_ns=d.t))   # agrees: left alone
  assert abs(distance - 88.0) < 0.2


def test_a_new_step_replaces_the_turn():
  d = Drive(v=5.0)
  d.step(report(300.0, observed_ns=d.t))
  direction, distance = d.step(report(120.0, "turnLeft", turn_id=2, observed_ns=d.t))
  assert direction == "turnLeft" and abs(distance - 120.0) < 0.1


def test_turn_held_through_the_corner_when_the_app_moves_on():
  d = Drive(v=5.0)
  d.step(report(20.0, observed_ns=d.t))   # in the turn (30 m before to 15 m past)
  written = d.t
  next_step = report(400.0, "turnLeft", turn_id=2, observed_ns=written)
  direction, distance = d.step(next_step)
  assert direction == "turnRight" and distance < 20.0
  direction, distance = d.run(6.0, every=1.0, make=lambda _: next_step)   # 30 m on: 10 m past the turn point
  assert direction == "turnRight" and abs(distance + 10.0) < 0.2
  direction, distance = d.run(1.2, every=1.0, make=lambda _: next_step)   # 16 m past: on to the next step
  assert direction == "turnLeft"
  assert abs(distance - (400.0 - 36.0)) < 1.0


def test_passed_step_not_taken_again():
  d = Drive(v=5.0)
  d.step(report(10.0, observed_ns=d.t))
  d.run(6.0)   # 20 m past
  assert d.step(report(0.0, observed_ns=d.t)) is None   # the app still on the same step


def test_stale_reports_dropped():
  d = Drive(v=1.0)
  d.step(report(200.0, observed_ns=d.t))
  assert d.run(STALE - 0.5) is not None
  assert d.run(1.0) is None


def test_stale_turn_kept_while_in_it():
  d = Drive(v=2.0)
  d.step(report(25.0, observed_ns=d.t))
  assert d.run(STALE + 1.0) is not None   # 8 m to go: the app stopped sending, but we're turning


def test_none_direction_clears():
  d = Drive()
  d.step(report(200.0, observed_ns=d.t))
  assert d.step(report(0.0, "none", turn_id=5, observed_ns=d.t)) is None


def test_limits_from_params():
  class Params:
    def __init__(self, values):
      self.values = values

    def get(self, key, return_default=False):
      return self.values.get(key)

  assert route_turn_limits(Params({})) == RouteTurnLimits()
  limits = route_turn_limits(Params({"RouteTurnStartDistance": 40.0, "RouteTurnEndDistance": 20.0, "RouteTurnPromptDistance": 200.0}))
  assert limits == RouteTurnLimits(start=40.0, end=-20.0, prompt=200.0)
  # out of range values are kept to it, and the prompt always comes before the turn starts
  limits = route_turn_limits(Params({"RouteTurnStartDistance": 1000.0, "RouteTurnEndDistance": -5.0, "RouteTurnPromptDistance": 10.0}))
  assert limits == RouteTurnLimits(start=100.0, end=-0.0, prompt=110.0)
