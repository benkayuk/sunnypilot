"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
from opendbc.car.structs import car

from openpilot.common.constants import CV
from openpilot.common.params import Params
from openpilot.sunnypilot.selfdrive.controls.lib.route_turn import DEFAULT_LIMITS, TurnDirection, lane_turn_speed, route_turn_desire, \
  route_turn_limits


class BlinkerPauseLateral:
  def __init__(self):
    self.params = Params()

    self.enabled = self.params.get_bool("BlinkerPauseLateralControl")
    self.is_metric = self.params.get_bool("IsMetric")
    self.min_speed = 0
    self.reengage_delay = 0
    self.blinker_off_timer = 0.0
    self.lane_turn_speed = lane_turn_speed(self.params)
    self.route_turn_blinker = None  # the blinker of the route turn the model is taking (route_turn.py)
    self.route_turn_limits = DEFAULT_LIMITS

  def get_params(self) -> None:
    self.enabled = self.params.get_bool("BlinkerPauseLateralControl")
    self.is_metric = self.params.get_bool("IsMetric")
    self.min_speed = self.params.get("BlinkerMinLateralControlSpeed", return_default=True)
    self.reengage_delay = self.params.get("BlinkerLateralReengageDelay", return_default=True)
    self.lane_turn_speed = lane_turn_speed(self.params)
    self.route_turn_limits = route_turn_limits(self.params)

  def update(self, CS: car.CarState, DT_CTRL: float = 0.01, route_turn=None) -> bool:
    if not self.enabled:
      return False

    one_blinker = CS.leftBlinker != CS.rightBlinker

    # At a signalled turn on the navigation route the model is asked to take the turn, so keep steering on,
    # until that blinker goes off rather than when the request ends mid-turn
    turn = route_turn_desire(route_turn, CS.leftBlinker, CS.rightBlinker, CS.leftBlindspot, CS.rightBlindspot,
                             CS.vEgo, self.lane_turn_speed, self.route_turn_limits)
    if turn != TurnDirection.none:
      self.route_turn_blinker = "left" if turn == TurnDirection.turnLeft else "right"
    elif self.route_turn_blinker != ("left" if CS.leftBlinker else "right") or not one_blinker:
      self.route_turn_blinker = None
    if self.route_turn_blinker is not None:
      self.blinker_off_timer = 0.0
      return False

    speed_factor = CV.KPH_TO_MS if self.is_metric else CV.MPH_TO_MS
    min_speed_ms = self.min_speed * speed_factor

    below_speed = CS.vEgo < min_speed_ms

    if one_blinker and below_speed:
      self.blinker_off_timer = self.reengage_delay
    elif self.blinker_off_timer > 0:
      self.blinker_off_timer -= DT_CTRL

    return bool((one_blinker and below_speed) or self.blinker_off_timer > 0)
