"""
The country the car is in, from the comma's last GPS fix, for what panda tells the Fisker's ADAS in the head unit's
map metadata (ICC_0x362): the unit of the speed-limit signs its camera reads, the side of the road and the country.
With FiskerAdasAuto on (the default) these follow the country, instead of the three manual settings
(FiskerSpeedLimitUnit, FiskerTrafficSide, FiskerCountryCode), so a UK car's 30 mph signs stop setting ACC to 30 km/h
without anyone setting anything, and the same car abroad gets km/h and the right side.

Panda takes the values at safety init, so they're settled at car start from the fix locationd last saved
(LastGPSPositionLLK, saved once a minute with a good fix). After crossing a border it's right from the next start.
With no fix yet, or a fix at sea, the manual settings apply.

The borders are Natural Earth 1:50m (a few hundred metres), the same data and tables as the OceanScape app's
region.js, so the two agree.
"""
import gzip
import json
import os
from functools import cache

BORDERS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "country_borders.json.gz")

# ISO 3166 numeric codes. Left-hand traffic:
LEFT = {826, 372, 833, 831, 832, 36, 554, 392, 356, 710, 458, 702, 764, 360, 344, 446, 586, 50, 144, 524,
        64, 404, 800, 834, 894, 716, 72, 516, 508, 454, 426, 748, 480, 196, 470, 388, 780, 44, 52, 328, 740, 96, 598, 242,
        90, 882, 776, 626, 462, 690, 238, 28, 212, 308, 659, 662, 670, 60, 136, 92, 850, 660, 500, 796, 296, 798, 520, 570,
        184, 574, 654}
# speed limits in mph:
MPH = {826, 833, 831, 832, 840, 630, 316, 850, 16, 580, 430, 238, 44, 84, 28, 212, 308, 659, 662, 670,
       136, 92, 660, 500, 796, 882, 654}
# Natural Earth's countries without an ISO code, by name
NAMED_LEFT = {"N. Cyprus"}

# the values of the manual settings these stand in for (see opendbc's FiskerSafetyFlagsSP META_*)
UNIT_MPH, UNIT_KPH = 1, 2
SIDE_LEFT, SIDE_RIGHT = 1, 2


@cache
def load_borders(path: str = BORDERS_PATH) -> dict:
  """The file as it is (see its "format"): rings are unpacked only for countries whose box holds a point looked up."""
  with gzip.open(path, "rt", encoding="utf-8") as f:
    return json.load(f)


def _rings(d: dict, rings: list[list[int]]) -> list[list[float]]:
  (sx, sy), (ox, oy) = d["scale"], d["origin"]
  out = []
  for r in rings:
    x = y = 0
    ring = []
    for i in range(0, len(r), 2):
      x += r[i]
      y += r[i + 1]
      ring += [ox + x * sx, oy + y * sy]
    out.append(ring)
  return out


def country_at(lat: float, lon: float, borders: dict | None = None) -> tuple[int, str] | None:
  """(ISO numeric code or 0, name) of the country under the point, or None (the sea)."""
  d = borders if borders is not None else load_borders()
  (sx, sy), (ox, oy) = d["scale"], d["origin"]
  gx, gy = (lon - ox) / sx, (lat - oy) / sy
  for code, name, (x0, y0, x1, y1), *packed in d["countries"]:
    if gx < x0 or gx > x1 or gy < y0 or gy > y1:
      continue
    inside = False
    for r in _rings(d, packed):
      j = len(r) - 2
      for i in range(0, len(r), 2):
        yi, yj = r[i + 1], r[j + 1]
        if (yi > lat) != (yj > lat) and lon < (r[j] - r[i]) * (lat - yi) / (yj - yi) + r[i]:
          inside = not inside
        j = i
    if inside:
      return (int(code) if str(code).isdigit() else 0), name
  return None


def adas_meta(code: int, name: str) -> dict[str, int]:
  """The three settings a country means."""
  left = code in LEFT if code else name in NAMED_LEFT
  return {
    "FiskerSpeedLimitUnit": UNIT_MPH if code in MPH else UNIT_KPH,
    "FiskerTrafficSide": SIDE_LEFT if left else SIDE_RIGHT,
    "FiskerCountryCode": code if 0 < code < 1000 else 0,
  }


def last_fix(params) -> tuple[float, float] | None:
  try:
    pos = json.loads(params.get("LastGPSPositionLLK") or "null")
    lat, lon = float(pos["latitude"]), float(pos["longitude"])
  except (TypeError, ValueError, KeyError, json.JSONDecodeError):
    return None
  if not (-90 <= lat <= 90 and -180 <= lon <= 180) or (lat == 0 and lon == 0):
    return None
  return lat, lon


def auto_adas_meta(params, borders=None) -> dict[str, int] | None:
  """With FiskerAdasAuto on: the settings for the country of the last fix (and FiskerAdasAutoCountry says which,
  for the app), else None (the manual settings apply). Never raises: car start mustn't depend on it."""
  try:
    if not params.get_bool("FiskerAdasAuto"):
      return None
    fix = last_fix(params)
    here = country_at(*fix, borders=borders) if fix else None
    if here is None:
      params.remove("FiskerAdasAutoCountry")
      return None
    params.put("FiskerAdasAutoCountry", here[1])
    return adas_meta(*here)
  except Exception:
    return None
