"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
from dataclasses import replace

from opendbc.car.fisker import carcontroller, fiskercan, values

from openpilot.common.test import OpenpilotTestCase
from openpilot.sunnypilot.selfdrive.car.can_overrides import PARAM, CanOverrides


class FakeParams:
  def __init__(self):
    self.store = {}

  def get(self, key, return_default=False):
    return self.store.get(key)


class TestCanOverrides(OpenpilotTestCase):
  def setUp(self):
    super().setUp()
    self.saved = dict(values.ICC_0x35B_OVERRIDES)
    self.ov = CanOverrides.for_brand("fisker")

  def tearDown(self):
    values.ICC_0x35B_OVERRIDES.clear()
    values.ICC_0x35B_OVERRIDES.update(self.saved)
    super().tearDown()

  def test_unsupported_brand(self):
    assert CanOverrides.for_brand("toyota") is None
    assert CanOverrides.for_brand(None) is None

  def test_only_0x35b_is_editable(self):
    # the 0x52A table is gone: ACC settings are a fixed spoof with on-device toggles, not a CAN override
    assert [t.message for t in self.ov.tables] == ["ICC_0x35B"]
    assert self.ov.passthrough(self.ov.tables[0]) == values.ICC_0x35B_PASSTHROUGH

  def test_defaults_are_the_code_values(self):
    assert self.ov.defaults == {"ICC_0x35B": self.saved}
    assert self.ov.live() == {"ICC_0x35B": self.saved}

  def test_validate(self):
    clean, errors = self.ov.validate({
      "ICC_0x35B": {"ICC_BSDSetting": 2, "ICC_APA_Setting": 99, "ICC_BSD_Sensitivity": 1.5, "ICC_ViewReq": 2,
                    "ICC_DOW_Setting": True, "NotASignal": 1},
      "ICC_0x52A": {"ICC_ACCSwt": 1},
      "ADAS_0x31C": {"ADAS_TiGapSet_ACC": 1},
    })
    assert clean == {"ICC_0x35B": {"ICC_BSDSetting": 2}}
    text = " | ".join(errors)
    for needle in ("ICC_APA_Setting: 99 outside", "ICC_BSD_Sensitivity: 1.5 outside", "ICC_ViewReq: always passed through",
                   "ICC_DOW_Setting: value must be a number", "NotASignal: unknown signal",
                   "ICC_0x52A: not an overridable message", "ADAS_0x31C: not an overridable message"):
      assert needle in text, needle

  def test_protected_suffixes_are_locked(self):
    # 0x35B carries no E2E, so graft a counter and a checksum onto this instance's parsed copy of the
    # message: the rule has to hold for the next table that does have them
    msg = self.ov.dbc.by_name["ICC_0x35B"]
    grafted = ("ICC_0x35B_AliveCounter", "ICC_0x35B_CheckSum")
    for name in grafted:
      msg.signals[name] = replace(msg.signals["ICC_BSDSetting"], name=name)
    try:
      clean, errors = self.ov.validate({"ICC_0x35B": {"ICC_0x35B_AliveCounter": 1, "ICC_0x35B_CheckSum": 1, "ICC_BSDSetting": 1}})
    finally:
      for name in grafted:
        msg.signals.pop(name)
    assert clean == {"ICC_0x35B": {"ICC_BSDSetting": 1}}
    text = " | ".join(errors)
    for name in grafted:
      assert f"{name}: always passed through" in text, name

  def test_resolve_replaces_per_message(self):
    assert self.ov.resolve({"ICC_0x35B": {"ICC_BSDSetting": 3}}) == {"ICC_0x35B": {"ICC_BSDSetting": 3}}  # stored message fully replaces defaults
    assert self.ov.resolve({"ICC_0x35B": {}}) == {"ICC_0x35B": {}}                                       # ... down to nothing: frame left alone
    assert self.ov.resolve(None) == {"ICC_0x35B": self.saved}                                           # missing message keeps code defaults
    assert self.ov.resolve({"ICC_0x52A": {"ICC_ACCSwt": 1}}) == {"ICC_0x35B": self.saved}               # unknown message is ignored

  def test_apply_mutates_the_dict_carcontroller_reads(self):
    target = values.ICC_0x35B_OVERRIDES
    assert fiskercan.ICC_0x35B_OVERRIDES is target and carcontroller.ICC_0x35B_OVERRIDES is target
    self.ov.apply({"ICC_0x35B": {"ICC_BSDSetting": 2, "ICC_DOW_Setting": 2}})
    assert fiskercan.ICC_0x35B_OVERRIDES is target
    assert target == {"ICC_BSDSetting": 2, "ICC_DOW_Setting": 2}
    self.ov.apply({"ICC_0x35B": {}})
    assert target == {} and not carcontroller.ICC_0x35B_OVERRIDES   # empty: carcontroller stops relaying 0x35B

  def test_poll_applies_only_on_change(self):
    params = FakeParams()
    assert self.ov.poll(params)              # first poll applies defaults
    assert not self.ov.poll(params)
    params.store[PARAM] = {"ICC_0x35B": {"ICC_BSDSetting": 3}}
    assert self.ov.poll(params)
    assert values.ICC_0x35B_OVERRIDES == {"ICC_BSDSetting": 3}
    assert not self.ov.poll(params)
    del params.store[PARAM]
    assert self.ov.poll(params)
    assert values.ICC_0x35B_OVERRIDES == self.saved

  def test_bad_param_falls_back_to_defaults(self):
    params = FakeParams()
    params.store[PARAM] = {"ICC_0x35B": {"ICC_BSDSetting": 3}}
    self.ov.poll(params)
    params.store[PARAM] = {"ICC_0x35B": "garbage"}   # malformed entry is dropped -> code defaults
    self.ov.poll(params)
    assert values.ICC_0x35B_OVERRIDES == self.saved
    params.store[PARAM] = {"ICC_0x35B": {"ICC_BSDSetting": 3}}
    self.ov.poll(params)
    params.store[PARAM] = ["not", "a", "dict"]
    self.ov.poll(params)
    assert values.ICC_0x35B_OVERRIDES == self.saved

  def test_overridden_frame_packs(self):
    from opendbc.can import CANPacker
    from opendbc.car import Bus
    from opendbc.car.fisker.values import CAR, DBC
    self.ov.apply(self.ov.resolve({"ICC_0x35B": {"ICC_BSDSetting": 3, "ICC_EnbLnChgAsst": 0}}))
    can = fiskercan.FiskerCAN(None, CANPacker(DBC[CAR.FISKER_OCEAN][Bus.pt]))
    msg = self.ov.dbc.by_name["ICC_0x35B"]
    # one decoded ICC frame off bus 0: a live camera-view request, undocumented bits set, our two signals at other values
    icc = dict.fromkeys(msg.signals, 0)
    icc.update({"ICC_0x35B_Undoc_Byte0": 0xA5, "ICC_ViewReq": 4, "ICC_BSDSetting": 0, "ICC_EnbLnChgAsst": 1, "ICC_APA_Setting": 1})
    addr, data, bus = can.create_icc_0x35b(icc)
    assert addr == 0x35B and bus == values.CANBUS.cam == 2 and len(data) == 8
    out = msg.decode(data)
    assert out["ICC_BSDSetting"] == 3 and out["ICC_EnbLnChgAsst"] == 0                                   # overrides win
    assert out["ICC_ViewReq"] == 4 and out["ICC_0x35B_Undoc_Byte0"] == 0xA5 and out["ICC_APA_Setting"] == 1   # the rest is the ICC's
