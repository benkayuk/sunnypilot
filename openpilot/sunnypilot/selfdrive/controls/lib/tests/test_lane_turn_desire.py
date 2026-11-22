from openpilot.cereal import log, custom
from openpilot.common.params import Params
from openpilot.common.parameterized import parameterized
from openpilot.common.test import OpenpilotTestCase

from openpilot.selfdrive.controls.lib.desire_helper import DesireHelper, LaneChangeState, LaneChangeDirection
from openpilot.sunnypilot.selfdrive.controls.lib.lane_turn_desire import LaneTurnController, LANE_CHANGE_SPEED_MIN
from openpilot.sunnypilot.selfdrive.controls.lib.auto_lane_change import AutoLaneChangeMode
from openpilot.sunnypilot.selfdrive.controls.lib.route_turn import ROUTE_TURN_END, ROUTE_TURN_PROMPT, ROUTE_TURN_START, route_turn_prompt


TurnDirection = custom.ModelDataV2SP.TurnDirection


class TestLaneTurnDesire(OpenpilotTestCase):
  @parameterized.expand([
    (True, False, 5, False, False, TurnDirection.turnLeft),
    (False, True, 6, False, False, TurnDirection.turnRight),
    (True, False, 9, False, False, TurnDirection.none),
    (True, False, 7, True, False, TurnDirection.none),
    (False, True, 6, False, True, TurnDirection.none),
    (False, False, 5, False, False, TurnDirection.none),
    (True, True, 5, False, False, TurnDirection.none),
  ])
  def test_lane_turn_desire_conditions(self, left_blinker, right_blinker, v_ego, blindspot_left, blindspot_right, expected):
    dh = DesireHelper()
    controller = LaneTurnController(dh)
    controller.enabled = True
    controller.lane_turn_value = LANE_CHANGE_SPEED_MIN
    controller.turn_direction = TurnDirection.none
    controller.update_lane_turn(blindspot_left, blindspot_right, left_blinker, right_blinker, v_ego)
    assert controller.get_turn_direction() == expected

  def test_lane_turn_desire_disabled(self):
    dh = DesireHelper()
    controller = LaneTurnController(dh)
    controller.enabled = False
    controller.lane_turn_value = LANE_CHANGE_SPEED_MIN
    controller.turn_direction = TurnDirection.none
    controller.update_lane_turn(False, False, True, False, 7)
    assert controller.get_turn_direction() == TurnDirection.none

  def test_lane_turn_overrides_lane_change(self):
    dh = DesireHelper()
    controller = LaneTurnController(dh)
    controller.enabled = True
    controller.lane_turn_value = LANE_CHANGE_SPEED_MIN
    controller.turn_direction = TurnDirection.none
    # left turn desire
    controller.update_lane_turn(False, False, True, False, 5)
    assert controller.get_turn_direction() == TurnDirection.turnLeft
    # right turn desire
    controller.update_lane_turn(False, False, False, True, 6)
    assert controller.get_turn_direction() == TurnDirection.turnRight
    # no turn
    controller.update_lane_turn(False, False, False, False, 7)
    assert controller.get_turn_direction() == TurnDirection.none

  @parameterized.expand([
    (8.93, TurnDirection.turnLeft),  # just below threshold
    (8.96, TurnDirection.none),  # above threshold
    (8.95, TurnDirection.none),  # just above threshold
  ])
  def test_lane_turn_desire_speed_boundary(self, v_ego, expected):
    dh = DesireHelper()
    controller = LaneTurnController(dh)
    controller.enabled = True
    controller.lane_turn_value = LANE_CHANGE_SPEED_MIN
    controller.turn_direction = TurnDirection.none
    controller.update_lane_turn(False, True, True, False, v_ego)
    assert controller.get_turn_direction() == expected

  @parameterized.expand([
    ("turnRight", 20.0, False, True, 5.0, False, TurnDirection.turnRight),
    ("turnLeft", 0.0, True, False, 5.0, False, TurnDirection.turnLeft),
    ("turnRight", ROUTE_TURN_END, False, True, 5.0, False, TurnDirection.turnRight),
    ("turnRight", 20.0, True, False, 5.0, False, TurnDirection.none),  # signalling the other way: off the route
    ("turnRight", 20.0, False, False, 5.0, False, TurnDirection.none),  # no blinker
    ("turnRight", ROUTE_TURN_START + 1, False, True, 5.0, False, TurnDirection.none),
    ("turnRight", ROUTE_TURN_END - 1, False, True, 5.0, False, TurnDirection.none),
    ("turnRight", 20.0, False, True, LANE_CHANGE_SPEED_MIN, False, TurnDirection.none),
    ("turnRight", 20.0, False, True, 5.0, True, TurnDirection.none),  # right blind spot
    ("none", 20.0, False, True, 5.0, False, TurnDirection.none),
  ])
  def test_route_turn_desire(self, direction, distance, left_blinker, right_blinker, v_ego, blindspot_right, expected):
    # a route turn needs no LaneTurnDesire toggle, only the matching blinker near the turn point
    controller = LaneTurnController(DesireHelper())
    controller.enabled = False
    controller.lane_turn_value = LANE_CHANGE_SPEED_MIN
    route_turn = custom.CarStateSP.RouteTurn.new_message(direction=direction, distance=distance)
    controller.update_lane_turn(False, blindspot_right, left_blinker, right_blinker, v_ego, route_turn=route_turn)
    assert controller.get_turn_direction() == expected

  @parameterized.expand([
    ("turnLeft", 100.0, False, False, TurnDirection.turnLeft),
    ("turnRight", ROUTE_TURN_PROMPT, False, False, TurnDirection.turnRight),
    ("turnLeft", 100.0, False, True, TurnDirection.turnLeft),  # the other blinker is not the route's turn
    ("turnLeft", 100.0, True, False, TurnDirection.none),  # signalled: nothing to ask
    ("turnLeft", ROUTE_TURN_PROMPT + 1, False, False, TurnDirection.none),
    ("turnLeft", ROUTE_TURN_START, False, False, TurnDirection.none),  # the turn request has started
    ("none", 100.0, False, False, TurnDirection.none),
  ])
  def test_route_turn_prompt(self, direction, distance, left_blinker, right_blinker, expected):
    route_turn = custom.CarStateSP.RouteTurn.new_message(direction=direction, distance=distance)
    assert route_turn_prompt(route_turn, left_blinker, right_blinker) == expected


class DummyCarState:
  def __init__(self, vEgo=0, leftBlinker=False, rightBlinker=False, leftBlindspot=False, rightBlindspot=False,
               steeringPressed=False, steeringTorque=0, brakePressed=False):
    self.vEgo = vEgo
    self.leftBlinker = leftBlinker
    self.rightBlinker = rightBlinker
    self.leftBlindspot = leftBlindspot
    self.rightBlindspot = rightBlindspot
    self.steeringPressed = steeringPressed
    self.steeringTorque = steeringTorque
    self.brakePressed = brakePressed


def set_lane_turn_params():
  params = Params()
  params.put("LaneTurnDesire", True)
  params.put("LaneTurnValue", 20.0)


class TestDesireHelperIntegration(OpenpilotTestCase):
  @parameterized.expand([
    # Lane turn desire overrides lane change desire
    (DummyCarState(vEgo=5, leftBlinker=True, rightBlinker=False, leftBlindspot=False, rightBlindspot=False), True, 1.0,
     log.Desire.turnLeft),
    (DummyCarState(vEgo=7, leftBlinker=False, rightBlinker=True, leftBlindspot=False, rightBlindspot=False), True, 1.0,
     log.Desire.turnRight),
    # Lane change desire only (no turn desires)
    (DummyCarState(vEgo=9, leftBlinker=True, rightBlinker=False, leftBlindspot=False, rightBlindspot=False,
                   steeringPressed=True, steeringTorque=1), True, 1.0, log.Desire.laneChangeLeft),
    (DummyCarState(vEgo=9, leftBlinker=False, rightBlinker=True, leftBlindspot=False, rightBlindspot=False,
                   steeringPressed=True, steeringTorque=-1), True, 1.0, log.Desire.laneChangeRight),
    # No desire (inactive)
    (DummyCarState(vEgo=9, leftBlinker=False, rightBlinker=False), False, 1.0, log.Desire.none),
    (DummyCarState(vEgo=4, leftBlinker=False, rightBlinker=False), True, 1.0, log.Desire.none),  # No blinkers? no desire!
  ], names=["carstate", "lateral_active", "lane_change_prob", "expected_desire"])
  def test_desire_helper_integration(self, carstate, lateral_active, lane_change_prob, expected_desire, set_lane_turn_params):
    dh = DesireHelper()
    dh.alc.lane_change_set_timer = AutoLaneChangeMode.NUDGE
    for _ in range(10):
      dh.update(carstate, lateral_active, lane_change_prob,
                left_edge_detected=False, right_edge_detected=False)
    assert dh.desire == expected_desire

  def test_edge_blocks_lane_change(self, set_lane_turn_params):
    dh = DesireHelper()
    dh.alc.lane_change_set_timer = AutoLaneChangeMode.NUDGE
    carstate = DummyCarState(vEgo=15, leftBlinker=True, steeringPressed=True, steeringTorque=1)
    for _ in range(10):
      dh.update(carstate, True, 1.0, left_edge_detected=True, right_edge_detected=False)
    assert dh.lane_change_state == LaneChangeState.preLaneChange
    assert dh.lane_change_direction == LaneChangeDirection.left
    assert dh.desire == log.Desire.none
