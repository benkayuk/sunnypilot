"""
Turns on the car's own navigation route (carStateSP.routeTurn; the Fisker port reads them from its head unit's
ADASIS horizon).

Coming up to a turn on the route below the lane turn speed, with the blinker on in the route's direction, the
driving model is asked to take that turn (LaneTurnController), and BlinkerPauseLateral keeps steering on for it.
The blinker is the driver confirming the turn: with no blinker, or the other one, nothing changes. On a guided
Fisker drive (route 00000014) the car started turning 10 to 17 m before the turn point and was ~85 deg into a
right turn 15 m past it.
"""
from openpilot.cereal import custom
from openpilot.common.constants import CV

TurnDirection = custom.ModelDataV2SP.TurnDirection

ROUTE_TURN_START = 30.0  # m before the turn point the model is asked to turn
ROUTE_TURN_END = -15.0   # m past it the request ends
ROUTE_TURN_PROMPT = 150.0  # m before the turn point the driver is asked to signal it
LANE_TURN_SPEED_MAX = 20 * CV.MPH_TO_MS


def lane_turn_speed(params) -> float:
  """The speed (m/s) below which a blinker means a turn rather than a lane change."""
  return min(LANE_TURN_SPEED_MAX, float(params.get("LaneTurnValue", return_default=True)) * CV.MPH_TO_MS)


def route_turn_desire(route_turn, left_blinker: bool, right_blinker: bool, blindspot_left: bool, blindspot_right: bool,
                      v_ego: float, max_speed: float):
  """The turn to ask the model for at a route turn the driver is signalling, else TurnDirection.none."""
  if route_turn is None or v_ego >= max_speed or not ROUTE_TURN_END <= route_turn.distance <= ROUTE_TURN_START:
    return TurnDirection.none
  if route_turn.direction == TurnDirection.turnLeft and left_blinker and not right_blinker and not blindspot_left:
    return TurnDirection.turnLeft
  if route_turn.direction == TurnDirection.turnRight and right_blinker and not left_blinker and not blindspot_right:
    return TurnDirection.turnRight
  return TurnDirection.none


def route_turn_prompt(route_turn, left_blinker: bool, right_blinker: bool):
  """The route turn the driver should signal now (coming up, not yet signalled), else TurnDirection.none."""
  if route_turn is None or not ROUTE_TURN_START < route_turn.distance <= ROUTE_TURN_PROMPT:
    return TurnDirection.none
  if route_turn.direction == TurnDirection.turnLeft and not left_blinker:
    return TurnDirection.turnLeft
  if route_turn.direction == TurnDirection.turnRight and not right_blinker:
    return TurnDirection.turnRight
  return TurnDirection.none
