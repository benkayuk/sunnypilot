"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
from openpilot.cereal import custom

from openpilot.common.constants import CV
from openpilot.common.params import Params
from openpilot.sunnypilot.selfdrive.controls.lib.route_turn import DEFAULT_LIMITS, lane_turn_speed, route_turn_desire, route_turn_limits

TurnDirection = custom.ModelDataV2SP.TurnDirection

LANE_CHANGE_SPEED_MIN = 20 * CV.MPH_TO_MS


class LaneTurnController:
  def __init__(self, desire_helper):
    self.DH = desire_helper
    self.turn_direction = TurnDirection.none
    self.route_turn_direction = TurnDirection.none
    self.params = Params()
    self.lane_turn_value = float(self.params.get("LaneTurnValue", return_default=True)) * CV.MPH_TO_MS
    self.param_read_counter = 0
    self.enabled = self.params.get_bool("LaneTurnDesire")
    self.route_turn_limits = DEFAULT_LIMITS

  def read_params(self):
    self.enabled = self.params.get_bool("LaneTurnDesire")
    self.lane_turn_value = lane_turn_speed(self.params)
    self.route_turn_limits = route_turn_limits(self.params)

  def update_params(self) -> None:
    if self.param_read_counter % 50 == 0:
      self.read_params()
    self.param_read_counter += 1

  def update_lane_turn(self, blindspot_left: bool, blindspot_right: bool, left_blinker: bool, right_blinker: bool, v_ego: float,
                       route_turn=None) -> None:
    # a signalled turn on the car's navigation route, independent of the LaneTurnDesire toggle (route_turn.py)
    self.route_turn_direction = route_turn_desire(route_turn, left_blinker, right_blinker, blindspot_left, blindspot_right,
                                                  v_ego, self.lane_turn_value, self.route_turn_limits)
    if left_blinker and not right_blinker and v_ego < self.lane_turn_value and not blindspot_left:
      self.turn_direction = TurnDirection.turnLeft
    elif right_blinker and not left_blinker and v_ego < self.lane_turn_value and not blindspot_right:
      self.turn_direction = TurnDirection.turnRight
    else:
      self.turn_direction = TurnDirection.none

  def get_turn_direction(self):
    if self.route_turn_direction != TurnDirection.none:
      return self.route_turn_direction
    if not self.enabled:
      return TurnDirection.none
    return self.turn_direction
