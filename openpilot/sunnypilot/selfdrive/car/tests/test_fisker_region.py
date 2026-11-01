import json

import pytest

from openpilot.sunnypilot.selfdrive.car.fisker_region import adas_meta, auto_adas_meta, country_at, last_fix, load_borders


class FakeParams:
  def __init__(self, **values):
    self.values = dict(values)

  def get(self, key, return_default=False):
    return self.values.get(key)

  def get_bool(self, key):
    return bool(self.values.get(key, True if key == "FiskerAdasAuto" else False))

  def put(self, key, value):
    self.values[key] = value

  def remove(self, key):
    self.values.pop(key, None)


def fix(lat, lon):
  return json.dumps({"latitude": lat, "longitude": lon, "altitude": 30.0})


@pytest.mark.parametrize("lat, lon, code, name", [
  (51.5045, -0.1265, 826, "United Kingdom"),    # Whitehall
  (54.597, -5.930, 826, "United Kingdom"),      # Belfast
  (53.349, -6.260, 372, "Ireland"),             # Dublin
  (48.8566, 2.3522, 250, "France"),
  (52.52, 13.405, 276, "Germany"),
  (39.7392, -104.9903, 840, "United States of America"),  # Denver
  (45.4215, -75.6972, 124, "Canada"),
  (-33.8688, 151.2093, 36, "Australia"),
])
def test_country_at(lat, lon, code, name):
  assert country_at(lat, lon) == (code, name)


def test_sea():
  assert country_at(50.0, -20.0) is None   # the Atlantic


@pytest.mark.parametrize("code, name, unit, side, country", [
  (826, "United Kingdom", 1, 1, 826),   # mph, left
  (372, "Ireland", 2, 1, 372),          # km/h, left
  (250, "France", 2, 2, 250),           # km/h, right
  (840, "United States of America", 1, 2, 840),
  (124, "Canada", 2, 2, 124),
  (0, "N. Cyprus", 2, 1, 0),            # no ISO code: left by name, country passed through
])
def test_adas_meta(code, name, unit, side, country):
  assert adas_meta(code, name) == {"FiskerSpeedLimitUnit": unit, "FiskerTrafficSide": side, "FiskerCountryCode": country}


def test_auto_follows_last_fix():
  p = FakeParams(LastGPSPositionLLK=fix(51.5045, -0.1265))
  assert auto_adas_meta(p) == {"FiskerSpeedLimitUnit": 1, "FiskerTrafficSide": 1, "FiskerCountryCode": 826}
  assert p.values["FiskerAdasAutoCountry"] == "United Kingdom"
  p.values["LastGPSPositionLLK"] = fix(48.8566, 2.3522)
  assert auto_adas_meta(p) == {"FiskerSpeedLimitUnit": 2, "FiskerTrafficSide": 2, "FiskerCountryCode": 250}
  assert p.values["FiskerAdasAutoCountry"] == "France"


@pytest.mark.parametrize("values", [
  {"FiskerAdasAuto": False, "LastGPSPositionLLK": fix(51.5045, -0.1265)},   # off: the manual settings
  {},                                                                        # no fix yet
  {"LastGPSPositionLLK": "not json"},
  {"LastGPSPositionLLK": json.dumps({"latitude": 0.0, "longitude": 0.0})},
  {"LastGPSPositionLLK": fix(50.0, -20.0)},                                  # at sea
])
def test_auto_falls_back(values):
  p = FakeParams(**values, FiskerAdasAutoCountry="United Kingdom")
  assert auto_adas_meta(p) is None
  if values.get("FiskerAdasAuto", True) and "LastGPSPositionLLK" in values and last_fix(p):
    assert "FiskerAdasAutoCountry" not in p.values


def test_auto_never_raises():
  class Broken(FakeParams):
    def get_bool(self, key):
      raise RuntimeError("params")
  assert auto_adas_meta(Broken()) is None


def test_borders_cover_the_world():
  countries = load_borders()["countries"]
  assert len(countries) > 200
  assert any(code == "826" for code, *_ in countries)
