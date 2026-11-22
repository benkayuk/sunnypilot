"""
Turns on the car's own navigation route (carStateSP.routeTurn; the Fisker port reads them from its head unit's
ADASIS horizon).

Coming up to a turn on the route below the lane turn speed, with the blinker on in the route's direction, the
driving model is asked to take that turn (LaneTurnController), and BlinkerPauseLateral keeps steering on for it.
The blinker is the driver confirming the turn: with no blinker, or the other one, nothing changes. On a guided
Fisker drive (route 00000014) the car started turning 10 to 17 m before the turn point and was ~85 deg into a
right turn 15 m past it. The three distances are params (RouteTurnPromptDistance, RouteTurnStartDistance,
RouteTurnEndDistance), set from OceanScape's Driving > Nav; the defaults are the constants below.
"""
from dataclasses import dataclass

from openpilot.cereal import custom
from openpilot.common.constants import CV

TurnDirection = custom.ModelDataV2SP.TurnDirection

ROUTE_TURN_START = 30.0  # m before the turn point the model is asked to turn
ROUTE_TURN_END = -15.0   # m past it the request ends
ROUTE_TURN_PROMPT = 150.0  # m before the turn point the driver is asked to signal it
LANE_TURN_SPEED_MAX = 20 * CV.MPH_TO_MS


@dataclass(frozen=True)
class RouteTurnLimits:
  start: float = ROUTE_TURN_START    # m before the turn point the model is asked to turn
  end: float = ROUTE_TURN_END        # m (negative: past the turn point) the request ends
  prompt: float = ROUTE_TURN_PROMPT  # m before the turn point the driver is asked to signal it


DEFAULT_LIMITS = RouteTurnLimits()


def route_turn_limits(params) -> RouteTurnLimits:
  """The route turn distances as set, each kept to a sane range."""
  def read(key: str, default: float, low: float, high: float) -> float:
    try:
      value = params.get(key, return_default=True)
      return default if value is None else min(high, max(low, float(value)))
    except (TypeError, ValueError):
      return default
  start = read("RouteTurnStartDistance", ROUTE_TURN_START, 5.0, 100.0)
  end = -read("RouteTurnEndDistance", -ROUTE_TURN_END, 0.0, 50.0)
  prompt = max(start + 10.0, read("RouteTurnPromptDistance", ROUTE_TURN_PROMPT, 30.0, 500.0))
  return RouteTurnLimits(start, end, prompt)


def lane_turn_speed(params) -> float:
  """The speed (m/s) below which a blinker means a turn rather than a lane change."""
  return min(LANE_TURN_SPEED_MAX, float(params.get("LaneTurnValue", return_default=True)) * CV.MPH_TO_MS)


def route_turn_desire(route_turn, left_blinker: bool, right_blinker: bool, blindspot_left: bool, blindspot_right: bool,
                      v_ego: float, max_speed: float, limits: RouteTurnLimits = DEFAULT_LIMITS):
  """The turn to ask the model for at a route turn the driver is signalling, else TurnDirection.none."""
  if route_turn is None or v_ego >= max_speed or not limits.end <= route_turn.distance <= limits.start:
    return TurnDirection.none
  if route_turn.direction == TurnDirection.turnLeft and left_blinker and not right_blinker and not blindspot_left:
    return TurnDirection.turnLeft
  if route_turn.direction == TurnDirection.turnRight and right_blinker and not left_blinker and not blindspot_right:
    return TurnDirection.turnRight
  return TurnDirection.none


def route_turn_prompt(route_turn, left_blinker: bool, right_blinker: bool, limits: RouteTurnLimits = DEFAULT_LIMITS):
  """The route turn the driver should signal now (coming up, not yet signalled), else TurnDirection.none."""
  if route_turn is None or not limits.start < route_turn.distance <= limits.prompt:
    return TurnDirection.none
  if route_turn.direction == TurnDirection.turnLeft and not left_blinker:
    return TurnDirection.turnLeft
  if route_turn.direction == TurnDirection.turnRight and not right_blinker:
    return TurnDirection.turnRight
  return TurnDirection.none
