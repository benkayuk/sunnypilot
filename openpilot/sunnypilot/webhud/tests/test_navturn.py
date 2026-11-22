from openpilot.sunnypilot.webhud.navturn import parse

NOW = 500 * 10**9


def test_turn():
  f = parse({"type": "routeTurn", "direction": "left", "distance": 120, "tolerance": 5, "age": 1.5, "step": "Turn left onto A61",
             "app": "com.google.android.apps.maps"}, NOW)
  assert f["direction"] == "turnLeft"
  assert f["distance"] == 120.0 and f["distanceTolerance"] == 5.0
  assert f["observedMonoTime"] == NOW - int(1.5e9)
  assert f["turnId"] == parse({"direction": "right", "distance": 3, "step": "Turn left onto A61"}, NOW)["turnId"]
  assert f["turnId"] != parse({"direction": "left", "distance": 3, "step": "Turn left onto B6161"}, NOW)["turnId"]


def test_no_turn():
  for direction in (None, "straight", "uturn"):
    f = parse({"direction": direction, "distance": 400}, NOW)
    assert f["direction"] == "none" and f["distance"] == 0.0


def test_nonsense_refused():
  assert parse({"direction": "left", "distance": "far"}, NOW) is None
  assert parse({"direction": "left", "distance": -5}, NOW) is None
  assert parse({"direction": "left", "distance": 1e6}, NOW) is None


def test_age_kept_sane():
  assert parse({"direction": "left", "distance": 50, "age": -3}, NOW)["observedMonoTime"] == NOW
  assert parse({"direction": "left", "distance": 50, "age": 1e9}, NOW)["observedMonoTime"] == NOW - 120 * 10**9
