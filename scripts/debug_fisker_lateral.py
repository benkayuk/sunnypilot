#!/usr/bin/env python3
"""
debug_fisker_lateral.py — live debug logger for lateral-engagement failures.

Runs ALONGSIDE sunnypilot (does not touch pandad, carcontroller, or anything
in the control path — just subscribes to the cereal 'can' topic that pandad
publishes, plus a few state topics). You can leave sunnypilot engaged / driving
while this runs.

Usage (on the comma 3X):
    scp this file to /data/openpilot/scripts/debug_fisker_lateral.py
    cd /data/openpilot
    PYTHONPATH=. python3 scripts/debug_fisker_lateral.py

Logs every state transition on the signals that matter for engaging lateral,
with microsecond-ish wall-clock timestamps:

  * MFS_0x514 button inputs (right/left stalk, roll wheel)
  * ADAS_0x313 cruise state (ADAS_Sts_ACC_ICC)
  * ADAS_0x1C0 our lateral-request fields (Req / Sts / Typ)
  * ADAS_0x1D0 our commanded steering angle (SteerAnReq)
  * EPS_0x1C2 EPS's reply (EPS_AdasLatCtrlSts) and abort reason (EPS_AbortFb)
  * EPS_0x1C4 driver-intervention bit (EPS_DrvrIntvSteerWhlDetd) + torque
  * VCU_0x358 basic CC state (VCU_Sts_CC_ICC)

Plus the sunnypilot/openpilot internal state as reported on cereal:
  * carState.cruiseState.{enabled, available, nonAdaptive}, steeringPressed
  * carControl.{enabled, latActive}
  * controlsState.{state, enabled}
  * selfdriveStateSP.mads.{state, enabled, active, available}
  * Params: FiskerMadsArmed, RemoteControlEnabled

Writes to /data/fisker_lateral_debug.log (append) AND stdout. Rotate / move
/data/fisker_lateral_debug.log before a session if you want a clean file.

Press Ctrl-C to stop.
"""

from __future__ import annotations

import datetime
import time
from pathlib import Path

import cereal.messaging as messaging
from opendbc.can.parser import CANParser


ADAS_DBC = "fisker_ocean_adas"
ADAS_BUS = 0  # ADASBUS lives on bus 0 in the fisker port (see fisker-ocean-bus-scope memory)

# (signal_name, message_name) — CANParser will pick these out of the ADAS DBC.
SIGNALS = [
  # MFSS buttons — WHICH button the user actually pressed. See
  # fisker-ocean-mfss-buttons memory for the vehicle-verified mapping.
  ("MFS_RiBtnNorth",            "MFS_0x514"),  # ADAS on/off
  ("MFS_RiBtnSouth",            "MFS_0x514"),  # long-press MADS (per user report)
  ("MFS_RiBtnEast",             "MFS_0x514"),  # MADS toggle
  ("MFS_RiBtnWest",             "MFS_0x514"),
  ("MFS_LeRollPress",           "MFS_0x514"),  # SET (engage cruise at current speed)
  ("MFS_LeRollUp",              "MFS_0x514"),
  ("MFS_LeRollDwn",             "MFS_0x514"),
  # ADAS cruise state
  ("ADAS_Sts_ACC_ICC",          "ADAS_0x313"),  # 0=Off 1=Standby 3=Active 5/6=standstill 9/10/11=fault
  # Our own lateral TX (what sunnypilot is asking EPS to do)
  ("ADAS_LatCtrl_Req",          "ADAS_0x1C0"),
  ("ADAS_LatCtrl_Sts",          "ADAS_0x1C0"),
  ("ADAS_LatCtrl_Typ",          "ADAS_0x1C0"),  # 1=LKA (only one Ocean honours), 3=TJA (DTC)
  ("ADAS_LatCtrl_SteerAnReq",   "ADAS_0x1D0"),  # commanded angle (deg)
  # EPS reply — the ground truth on whether lateral engaged
  ("EPS_AdasLatCtrlSts",        "EPS_0x1C2"),   # 0=Off 1=Available 2=Active 3=Fault
  ("EPS_AbortFb",               "EPS_0x1C2"),   # 0=none, 8=CAN abort (see secoc/alive-counter memories)
  ("EPS_DrvrIntvSteerWhlDetd",  "EPS_0x1C4"),   # conservative driver-overpower bit
  ("EPS_DrvrSteerTq",           "EPS_0x1C4"),
  # VCU basic CC state (test car runs CC not ACC per fisker-ocean-port-status)
  ("VCU_Sts_CC_ICC",            "VCU_0x358"),
]


def fmt_ts() -> str:
  return datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]


def pretty_val(v):
  """Floats to 2dp (angles), ints raw, everything else as-is."""
  if isinstance(v, float):
    return f"{v:.2f}"
  return str(v)


def main():
  log_path = Path("/data/fisker_lateral_debug.log")
  log_f = open(log_path, "a", buffering=1)  # line-buffered — tail -f works live

  def say(s: str, *, loud: bool = False) -> None:
    prefix = "***" if loud else "   "
    line = f"[{fmt_ts()}] {prefix} {s}"
    print(line, flush=True)
    log_f.write(line + "\n")

  say(f"=== fisker lateral debug — writing to {log_path} ===", loud=True)
  say("Subscribing to CAN bus 0 (ADASBUS) via cereal, plus cereal state topics...")

  cp = CANParser(ADAS_DBC, SIGNALS, ADAS_BUS)
  can_sock = messaging.sub_sock("can", conflate=False, timeout=50)

  sm = messaging.SubMaster([
    "carState", "carControl", "controlsState",
    "selfdriveState", "selfdriveStateSP", "carStateSP", "carControlSP",
  ])

  # Params for sunnypilot-side flags that gate engagement
  try:
    from openpilot.common.params import Params
    params = Params()
  except Exception as e:  # noqa: BLE001
    say(f"warning: couldn't open Params ({e}); FiskerMadsArmed/RemoteControlEnabled won't be logged")
    params = None

  last_can = {name: None for name, _ in SIGNALS}
  last_mads_state = None
  last_mads_active = None
  last_mads_available = None
  last_cs_cruise_enabled = None
  last_cc_enabled = None
  last_cc_lat_active = None
  last_cs_steer_pressed = None
  last_ctrls_state = None
  last_params = {}
  last_snapshot = 0.0
  SNAPSHOT_PERIOD = 10.0  # s — print a full state dump this often even without transitions

  mads_state_names = ["disabled", "paused", "enabled", "softDisabling", "overriding"]

  try:
    while True:
      # Drain CAN
      can_msgs = messaging.drain_sock_raw(can_sock, wait_for_one=False)
      if can_msgs:
        cp.update_strings(can_msgs)
        for name, msg in SIGNALS:
          v = cp.vl.get(msg, {}).get(name)
          if v is None:
            continue
          prev = last_can[name]
          if prev is None:
            last_can[name] = v
            continue
          # For floats (angle, torque) only log transitions that cross a
          # meaningful delta — otherwise we drown in noise.
          if isinstance(v, float):
            if abs(v - prev) < 0.5:
              continue
          elif v == prev:
            continue
          loud = name in (
            "MFS_RiBtnNorth", "MFS_RiBtnSouth", "MFS_RiBtnEast", "MFS_LeRollPress",
            "ADAS_LatCtrl_Req", "ADAS_LatCtrl_Typ",
            "EPS_AdasLatCtrlSts", "EPS_AbortFb",
            "EPS_DrvrIntvSteerWhlDetd",
            "ADAS_Sts_ACC_ICC", "VCU_Sts_CC_ICC",
          )
          say(f"CAN {name:28s}  {pretty_val(prev):>8} -> {pretty_val(v)}", loud=loud)
          last_can[name] = v

      # Cereal state transitions
      sm.update(0)

      if sm.updated["carState"]:
        cs = sm["carState"]
        if cs.cruiseState.enabled != last_cs_cruise_enabled:
          last_cs_cruise_enabled = cs.cruiseState.enabled
          say(f"carState.cruiseState.enabled -> {cs.cruiseState.enabled}", loud=True)
        if cs.steeringPressed != last_cs_steer_pressed:
          last_cs_steer_pressed = cs.steeringPressed
          say(f"carState.steeringPressed -> {cs.steeringPressed}  (steeringTorque={cs.steeringTorque:.2f})")

      if sm.updated["carControl"]:
        cc = sm["carControl"]
        if cc.enabled != last_cc_enabled:
          last_cc_enabled = cc.enabled
          say(f"carControl.enabled -> {cc.enabled}", loud=True)
        if cc.latActive != last_cc_lat_active:
          last_cc_lat_active = cc.latActive
          say(f"carControl.latActive -> {cc.latActive}", loud=True)

      if sm.updated["controlsState"]:
        try:
          ctrls_state_str = str(sm["controlsState"].state)
        except Exception:  # noqa: BLE001
          ctrls_state_str = "<unavailable>"
        if ctrls_state_str != last_ctrls_state:
          last_ctrls_state = ctrls_state_str
          say(f"controlsState.state -> {ctrls_state_str}")

      if sm.updated["selfdriveStateSP"]:
        mads = sm["selfdriveStateSP"].mads
        try:
          st_name = mads_state_names[int(mads.state)] if 0 <= int(mads.state) < len(mads_state_names) else str(mads.state)
        except Exception:  # noqa: BLE001
          st_name = str(mads.state)
        if (mads.state, mads.active, mads.available) != (last_mads_state, last_mads_active, last_mads_available):
          say(f"MADS state={st_name:<14s} enabled={mads.enabled} active={mads.active} available={mads.available}", loud=True)
          last_mads_state = mads.state
          last_mads_active = mads.active
          last_mads_available = mads.available

      # Params (polled; they don't publish on cereal)
      if params is not None:
        for key in ("FiskerMadsArmed", "RemoteControlEnabled"):
          cur = params.get_bool(key)
          if last_params.get(key) != cur:
            last_params[key] = cur
            say(f"param {key} -> {cur}")

      # Periodic full snapshot — useful as a baseline when scrolling through
      # a long log; also catches signals that are set from startup and never
      # change again (so we'd otherwise see them nowhere).
      if time.monotonic() - last_snapshot > SNAPSHOT_PERIOD:
        last_snapshot = time.monotonic()
        snap_bits = []
        for name, _ in SIGNALS:
          v = last_can.get(name)
          if v is None:
            continue
          snap_bits.append(f"{name}={pretty_val(v)}")
        if snap_bits:
          say("snapshot CAN  " + "  ".join(snap_bits))
        if last_cs_cruise_enabled is not None:
          say(f"snapshot CS   cruise.enabled={last_cs_cruise_enabled}  cc.enabled={last_cc_enabled}  cc.latActive={last_cc_lat_active}")
        if last_mads_state is not None:
          try:
            st_name = mads_state_names[int(last_mads_state)] if 0 <= int(last_mads_state) < len(mads_state_names) else str(last_mads_state)
          except Exception:  # noqa: BLE001
            st_name = str(last_mads_state)
          say(f"snapshot MADS state={st_name}  active={last_mads_active}  available={last_mads_available}")

      time.sleep(0.005)  # tight loop but don't peg a CPU core

  except KeyboardInterrupt:
    say("=== stopped by user ===", loud=True)
  finally:
    log_f.close()


if __name__ == "__main__":
  main()
