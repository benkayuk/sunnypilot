"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
from opendbc.car.structs import car

from openpilot.cereal import custom
from openpilot.common.constants import CV
from openpilot.sunnypilot.selfdrive.controls.lib.blinker_pause_lateral import BlinkerPauseLateral
from openpilot.common.test import OpenpilotTestCase


class TestBlinkerPauseLateral(OpenpilotTestCase):

  def setup_method(self):
    self.blinker_pause_lateral = BlinkerPauseLateral()
    self._reset_states()

  def _reset_states(self):
    self.blinker_pause_lateral.enabled = True
    self.blinker_pause_lateral.is_metric = False
    self.blinker_pause_lateral.min_speed = 20  # MPH
    self.blinker_pause_lateral.reengage_delay = 0
    self.blinker_pause_lateral.blinker_off_timer = 0.0
    self.blinker_pause_lateral.lane_turn_speed = 19 * CV.MPH_TO_MS
    self.blinker_pause_lateral.route_turn_blinker = None

    self.CS = car.CarState.new_message()
    self.CS.vEgo = 0
    self.CS.leftBlinker = False
    self.CS.rightBlinker = False

  def _test_should_blinker_pause_lateral(self, expected_results) -> None:
    for left in (True, False):
      for right in (True, False):
        self.CS.leftBlinker = left
        self.CS.rightBlinker = right

        result = self.blinker_pause_lateral.update(self.CS)
        assert result == expected_results[(left, right)]

  def test_below_min_speed_blinker(self):
    self.CS.vEgo = 4.5  # ~10 MPH

    expected_results = {
      (False, False): False,
      (True, False): True,
      (False, True): True,
      (True, True): False
    }
    self._test_should_blinker_pause_lateral(expected_results)

  def test_reengage_delay(self):
    self.blinker_pause_lateral.reengage_delay = 2 # seconds
    self.CS.vEgo = 4.5 # ~10 MPH

    expected_results = {
      (False, False): True,
      (True, False): True,
      (False, True): True,
      (True, True): False
    }
    self._test_should_blinker_pause_lateral(expected_results)

  def test_above_min_speed_blinker(self):
    self.CS.vEgo = 13.4  # ~30 MPH

    expected_results = {
      (False, False): False,
      (True, False): False,
      (False, True): False,
      (True, True): False
    }
    self._test_should_blinker_pause_lateral(expected_results)

  def test_just_below_min_speed(self):
    self.CS.vEgo = (20 * CV.MPH_TO_MS) - 0.01

    expected_results = {
      (False, False): False,
      (True, False): True,
      (False, True): True,
      (True, True): False
    }
    self._test_should_blinker_pause_lateral(expected_results)

  def test_disabled(self):
    self.blinker_pause_lateral.enabled = False
    self.CS.vEgo = 4.5  # ~10 MPH

    expected_results = {
      (False, False): False,
      (True, False): False,
      (False, True): False,
      (True, True): False
    }
    self._test_should_blinker_pause_lateral(expected_results)

  def test_metric_units_below_min_speed(self):
    self.blinker_pause_lateral.is_metric = True
    self.CS.vEgo = 5.0  # ~18 km/h

    expected_results = {
      (False, False): False,
      (True, False): True,
      (False, True): True,
      (True, True): False
    }
    self._test_should_blinker_pause_lateral(expected_results)

  def test_metric_units_above_threshold(self):
    self.blinker_pause_lateral.is_metric = True
    self.CS.vEgo = 6.0  # ~21.6 km/h

    expected_results = {
      (False, False): False,
      (True, False): False,
      (False, True): False,
      (True, True): False
    }
    self._test_should_blinker_pause_lateral(expected_results)

  def test_change_min_speed_threshold(self):
    self.blinker_pause_lateral.min_speed = 30  # MPH

    # below min speed
    self.CS.vEgo = 11.2  # ~25 MPH

    expected_results = {
      (False, False): False,
      (True, False): True,
      (False, True): True,
      (True, True): False
    }
    self._test_should_blinker_pause_lateral(expected_results)

    # above min speed
    self.CS.vEgo = 15.6  # ~35 MPH

    expected_results = {
      (False, False): False,
      (True, False): False,
      (False, True): False,
      (True, True): False
    }
    self._test_should_blinker_pause_lateral(expected_results)

  def test_route_turn_keeps_steering_until_blinker_off(self):
    # signalling the route's turn near it: the model takes the turn, so no pause, through the turn and
    # past the end of the request while that blinker stays on
    self.blinker_pause_lateral.reengage_delay = 1
    self.CS.vEgo = 4.5
    self.CS.rightBlinker = True
    route_turn = custom.CarStateSP.RouteTurn.new_message(direction="turnRight", distance=20.0)
    assert not self.blinker_pause_lateral.update(self.CS, route_turn=route_turn)
    route_turn.distance = -40.0
    assert not self.blinker_pause_lateral.update(self.CS, route_turn=route_turn)
    self.CS.rightBlinker = False
    assert not self.blinker_pause_lateral.update(self.CS, route_turn=route_turn)  # no re-engage delay to sit out
    self.CS.rightBlinker = True
    assert self.blinker_pause_lateral.update(self.CS, route_turn=route_turn)  # a new blinker, away from the turn

  def test_route_turn_other_way_still_pauses(self):
    self.CS.vEgo = 4.5
    self.CS.leftBlinker = True
    route_turn = custom.CarStateSP.RouteTurn.new_message(direction="turnRight", distance=20.0)
    assert self.blinker_pause_lateral.update(self.CS, route_turn=route_turn)
