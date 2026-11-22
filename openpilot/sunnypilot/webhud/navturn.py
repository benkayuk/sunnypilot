"""
The next turn of the head unit's nav app, from the OceanScape page over the WebSocket, published as navRouteTurnSP for
card (sunnypilot/selfdrive/car/nav_route_turn.py), which uses it when the car's own navigation has no route turn.

The page sends {"type": "routeTurn", "direction": "left" | "right" | null, "distance": m, "tolerance": m, "age": s,
"step": "...", "app": "..."} each time the nav app's notification changes and once a second besides. `age` is how long
ago the app wrote that distance, on the head unit's clock, so this device's time of it is now - age.
"""
import threading
import time
import zlib

from openpilot.common.swaglog import cloudlog

DIRECTIONS = {"left": "turnLeft", "right": "turnRight"}
MAX_DISTANCE = 8000.0   # m
MAX_AGE = 120.0         # s


def parse(data: dict, now_ns: int) -> dict | None:
  """The navRouteTurnSP fields for a page's message, or None when it doesn't make sense."""
  try:
    direction = DIRECTIONS.get(data.get("direction"), "none")
    distance = float(data.get("distance") or 0.0)
    tolerance = float(data.get("tolerance") or 0.0)
    age = float(data.get("age") or 0.0)
  except (TypeError, ValueError):
    return None
  if direction != "none" and not 0.0 <= distance <= MAX_DISTANCE:
    return None
  age = min(MAX_AGE, max(0.0, age))
  return {
    "direction": direction,
    "distance": distance if direction != "none" else 0.0,
    "distanceTolerance": min(500.0, max(0.0, tolerance)),
    "observedMonoTime": max(0, now_ns - int(age * 1e9)),
    "turnId": zlib.crc32(str(data.get("step") or "").encode()) & 0xFFFFFFFF,
    "app": str(data.get("app") or "")[:64],
  }


class NavTurnPublisher:
  def __init__(self):
    self.pm = None
    self._next_try = 0.0
    self.lock = threading.Lock()   # each WebSocket is served on a thread of its own

  def publish(self, data: dict) -> bool:
    fields = parse(data, time.monotonic_ns())
    if fields is None:
      return False
    with self.lock:
      return self._send(fields)

  def _send(self, fields: dict) -> bool:
    if self.pm is None:
      if time.monotonic() < self._next_try:
        return False
      self._next_try = time.monotonic() + 30.0
      try:
        import openpilot.cereal.messaging as messaging
        self.pm = messaging.PubMaster(["navRouteTurnSP"])
      except Exception:
        cloudlog.exception("webhud: can't publish navRouteTurnSP")
        return False
    import openpilot.cereal.messaging as messaging
    msg = messaging.new_message("navRouteTurnSP")
    for key, value in fields.items():
      setattr(msg.navRouteTurnSP, key, value)
    self.pm.send("navRouteTurnSP", msg)
    return True
