"""
The next turn of a nav app on the head unit, for carStateSP.routeTurn when the car's own navigation has none.

OceanScape reads the turn-by-turn notification of the head unit's nav app (Google Maps) and sends its next turn to
webhud, which publishes it as navRouteTurnSP about once a second: the direction, the distance as the app wrote it
("50 m", so give or take 5 m) and when it wrote it. The app only rewrites the distance every so often, so card
carries the turn point along with the distance driven (vEgo): a new reading moves it only as far as needed to agree
with the written distance and its rounding, as OceanScape's own road arrow does (navarrow.js).

The car's own route turn (Fisker: the ICC's ADASIS horizon) always wins; card only uses this one when that is none.
Once the car is in a turn (between the start and end distances of route_turn.py), that turn is held until it is
behind the car, even if the app has already moved on to its next step or stopped sending.
"""
import bisect
import math
import time

from openpilot.sunnypilot.selfdrive.controls.lib.route_turn import DEFAULT_LIMITS, RouteTurnLimits

NONE = "none"   # directions as ModelDataV2SP.TurnDirection names: none, turnLeft, turnRight

STALE = 3.0          # s without a report before the app's turn is dropped (webhud passes one on every second)
HISTORY_NS = 60e9    # odometer history kept, to place a reading at the moment the app wrote it
SAMPLE_NS = 100e6    # odometer history step
MARGIN = 3.0         # m added to the written distance's rounding: the app's own position error


class NavAppRouteTurn:
  def __init__(self):
    self.odo = 0.0                       # m driven since start
    self.hist_t: list[int] = []          # monotonic ns
    self.hist_odo: list[float] = []
    self.report = None                   # the latest navRouteTurnSP, as a tuple
    self.report_t = -math.inf            # monotonic s it came
    self.turn_id: int | None = None
    self.direction = NONE
    self.at = 0.0                        # odometer at the turn point
    self.passed_id: int | None = None    # the step just driven through, not to be taken again

  def _odo_at(self, t_ns: int) -> float:
    i = bisect.bisect_right(self.hist_t, t_ns)
    if i == 0:
      return self.hist_odo[0] if self.hist_odo else self.odo
    return self.hist_odo[i - 1] if i < len(self.hist_t) else self.odo

  def _in_turn(self, limits: RouteTurnLimits) -> bool:
    return self.direction != NONE and limits.end <= self.at - self.odo <= limits.start

  def _apply(self) -> None:
    turn_id, direction, distance, tolerance, observed_ns = self.report
    if turn_id == self.passed_id:
      return
    obs_odo = self._odo_at(observed_ns)
    if direction == NONE:
      self.turn_id, self.direction = turn_id, direction
    elif turn_id != self.turn_id or self.direction != direction:
      self.turn_id, self.direction, self.at = turn_id, direction, obs_odo + distance
    else:
      tol = tolerance + MARGIN
      self.at = obs_odo + min(distance + tol, max(distance - tol, self.at - obs_odo))

  def update(self, v_ego: float, dt: float, msg=None, limits: RouteTurnLimits = DEFAULT_LIMITS, now_ns: int | None = None):
    """Each card step, with a new navRouteTurnSP if one came. Returns (direction, distance) or None."""
    now_ns = time.monotonic_ns() if now_ns is None else now_ns
    self.odo += max(0.0, v_ego) * dt
    if not self.hist_t or now_ns - self.hist_t[-1] >= SAMPLE_NS:
      self.hist_t.append(now_ns)
      self.hist_odo.append(self.odo)
      while self.hist_t and now_ns - self.hist_t[0] > HISTORY_NS:
        self.hist_t.pop(0)
        self.hist_odo.pop(0)

    in_turn = self._in_turn(limits)
    if self.direction != NONE and self.at - self.odo < limits.end:
      # driven through it: done with this step, whatever the app still says
      self.passed_id, self.direction, in_turn = self.turn_id, NONE, False

    if msg is not None:
      self.report = (int(msg.turnId), str(msg.direction), float(msg.distance), max(0.0, float(msg.distanceTolerance)),
                     int(msg.observedMonoTime))
      self.report_t = now_ns / 1e9
      if not in_turn:
        self._apply()
    elif not in_turn and self.report is not None and self.report[0] != self.turn_id:
      self._apply()   # the app moved on while we were in the last turn

    if not in_turn and now_ns / 1e9 - self.report_t > STALE:
      self.direction = NONE
    if self.direction == NONE:
      return None
    return self.direction, self.at - self.odo
