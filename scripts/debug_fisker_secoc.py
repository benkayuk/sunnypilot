#!/usr/bin/env python3
"""
debug_fisker_secoc.py — SecOC MAC / freshness-counter forensics for the Ocean lateral abort.

Runs ALONGSIDE sunnypilot (read-only: subscribes to cereal 'can' + 'sendcan', touches
nothing in the control path). Run it together with debug_fisker_lateral.py — that one logs
the signal transitions / CMP / TX cadence; THIS one answers the one question those can't:

    does our SecOC MAC match what the EPS actually accepts?

Ground truth
------------
A SecOC MAC is computed over the FULL freshness (Trip ‖ Reset ‖ full-16-bit MsgCounter) but
only the low 6 bits of MsgCounter are on the wire — so a frame whose wire counter matches
OEM can still fail the MAC if the HIGH bits differ. We can't see those high bits directly,
so we recompute the MAC with our stored key + our per-window counter reconstruction and
compare to the MAC actually on the wire:

  * OEM bus-2 frames: OEM's own ADAS_0x1D0/0x1C0. When OEM is actively steering these carry
    a real MAC the EPS accepts — ground truth. When idle OEM sends an UNSIGNED placeholder
    (MAC = ff ff ff); we skip + count those (and report the count, so we learn whether OEM
    signs while idle).
  * our frames (sendcan): always carry a real MAC we computed. Self-consistency check, and
    captured in the ring buffer so the abort dump shows exactly what we were sending.

On any REAL mismatch (signed frame, after a verified GW sync) we brute-force only the
high-bit multiples (wire + 64*k) — the low 6 bits already match — so it's fast and can't
freeze the loop. The matching msg_counter reveals the value the EPS expects → the fix.

Nothing is verified until we've seen a GW_Syn_All (0x20) whose MAC verifies with our key:
before that we don't know trip/reset and any comparison is meaningless.

Usage (on the comma 3X):
    cd /data/openpilot && PYTHONPATH=. python3 scripts/debug_fisker_secoc.py

Writes /data/fisker_secoc_debug.log (append) AND stdout. Ctrl-C to stop.
"""

from __future__ import annotations

import datetime
import time
from collections import deque
from pathlib import Path

from openpilot.cereal import messaging
from opendbc.can.parser import CANParser
from opendbc.car.fisker.secoc import secoc_mac, sync_mac

ADAS_DBC = "fisker_ocean_adas"
ADDR_1D0 = 0x1D0
ADDR_1C0 = 0x1C0
OEM_BUS = 2        # OEM ADAS's own frames (ground truth, when signed)
OUR_BUS = 0        # ADASBUS — where our injected frames go out
PLACEHOLDER_MAC = b"\xff\xff\xff"

MAX_K = 1024       # high-bit search depth (wire + 64*k); windows are ~100 frames so this is plenty
MAX_BRUTES = 6     # cap brute-forces so a persistent mismatch can't spam


def fmt_ts() -> str:
  return datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]


def hexb(b: bytes | None) -> str:
  return b.hex() if b else "--"


class FullCtr:
  """Reconstruct the full per-window SecOC msg_counter from the 6-bit on-wire value,
  mirroring carstate: the high bits are a PER-GW-RESET-WINDOW count — zero them at each
  reset, +1 on every 63->0 wrap within the window."""
  def __init__(self):
    self.reset_tracked = None
    self.wire_last = None
    self.wraps = 0

  def update(self, wire: int, reset: int) -> int:
    if reset != self.reset_tracked:
      self.reset_tracked = reset
      self.wraps = 0
    elif self.wire_last is not None and wire < self.wire_last:
      self.wraps += 1
    self.wire_last = wire
    return self.wraps * 64 + wire


def search_highbits(key, can_id, pdu, mac_wire, trip, reset, wire):
  """The low 6 bits (wire) already match, so only the high bits can be wrong: search
  msg_counter = wire + 64*k. Then try neighbour reset windows. Fast (<~0.5 s)."""
  for k in range(MAX_K):
    m = wire + 64 * k
    if secoc_mac(key, can_id, pdu, trip, reset, m) == mac_wire:
      return {"kind": "msg_counter", "msg": m, "trip": trip, "reset": reset}
  for dr in (1, -1, 2, -2, 3, -3):
    r = reset + dr
    for k in range(MAX_K):
      m = wire + 64 * k
      if secoc_mac(key, can_id, pdu, trip, r, m) == mac_wire:
        return {"kind": "reset_off", "msg": m, "trip": trip, "reset": r, "reset_delta": dr}
  return None


def main():
  log_path = Path("/data/fisker_secoc_debug.log")
  log_f = open(log_path, "a", buffering=1)

  def say(s: str, *, loud: bool = False) -> None:
    line = f"[{fmt_ts()}] {'***' if loud else '   '} {s}"
    print(line, flush=True)
    log_f.write(line + "\n")

  say("=== fisker SecOC forensics ===", loud=True)

  # ---- key: hex string in params 'SecOCKey', same as card.py ----
  key = None
  try:
    from openpilot.common.params import Params
    raw = Params().get("SecOCKey")
    if raw is not None:
      txt = raw.decode() if isinstance(raw, (bytes, bytearray)) else raw
      key = bytes.fromhex(txt.strip())
  except Exception as e:  # noqa: BLE001
    say(f"ERROR reading SecOCKey: {e}", loud=True)
  if not key or len(key) != 16:
    say(f"ERROR: need a 16-byte SecOCKey in params (got {len(key) if key else 0}). Cannot verify MACs.", loud=True)
    return
  say(f"SecOCKey loaded ({len(key)} bytes). Waiting for a GW sync (0x20) to verify the key...")

  can_sock = messaging.sub_sock("can", conflate=False, timeout=50)
  sendcan_sock = messaging.sub_sock("sendcan", conflate=False, timeout=50)
  # GW sync (trip/reset/mac) and EPS reply via the DBC — correct byte layout, no guessing.
  cp_gw = CANParser(ADAS_DBC, [("GW_Syn_All", 0)], 0)
  cp_eps = CANParser(ADAS_DBC, [("EPS_0x1C2", 0)], 0)

  trip = reset = 0
  sync_ok = False          # key verified against the latest GW sync
  have_sync = False        # have we EVER verified a sync (gate for frame checks)

  trackers = {("oem", ADDR_1D0): FullCtr(), ("oem", ADDR_1C0): FullCtr(),
              ("our", ADDR_1D0): FullCtr(), ("our", ADDR_1C0): FullCtr()}
  # [ok, bad, placeholder]
  stats = {k: [0, 0, 0] for k in trackers}
  brutes_done = 0
  first_mismatch = set()

  ring = deque(maxlen=120)
  last_sts = None
  last_abort = 0
  last_summary = time.monotonic()
  sync_fail_warned = False

  def verify_frame(tag, addr, data, log_mono):
    nonlocal brutes_done
    if len(data) < 8:
      return
    wire = (data[4] >> 2) & 0x3F
    rflag = data[4] & 0x3
    pdu = bytes(data[0:4])
    mac_wire = bytes(data[5:8])
    full = trackers[(tag, addr)].update(wire, reset)

    if mac_wire == PLACEHOLDER_MAC:
      stats[(tag, addr)][2] += 1            # unsigned placeholder (idle) — nothing to check
      ring.append((log_mono, tag, addr, wire, rflag, full, mac_wire, None, None))
      return

    mac_calc = secoc_mac(key, addr, pdu, trip, reset, full)
    match = (mac_calc == mac_wire)
    stats[(tag, addr)][0 if match else 1] += 1
    ring.append((log_mono, tag, addr, wire, rflag, full, mac_wire, mac_calc, match))

    if not match:
      kn = f"{tag}_{addr:03x}"
      if kn not in first_mismatch:
        first_mismatch.add(kn)
        rflag_ok = (rflag == (reset & 0x3))
        say(f"MISMATCH {tag} 0x{addr:03X}: wire_mac={hexb(mac_wire)} calc_mac={hexb(mac_calc)} "
            f"wire_ctr={wire} full_ctr={full} rflag={rflag}(reset&3={reset & 0x3},ok={rflag_ok}) "
            f"trip={trip} reset={reset} pdu={hexb(pdu)}", loud=True)
        if brutes_done < MAX_BRUTES:
          brutes_done += 1
          t0 = time.monotonic()
          found = search_highbits(key, addr, pdu, mac_wire, trip, reset, wire)
          dt = time.monotonic() - t0
          if found is None:
            say(f"  no high-bit match in {dt:.2f}s — key/DataId/algorithm differ for 0x{addr:03X}, "
                f"or trip/reset wrong", loud=True)
          else:
            off = found["msg"] - full
            extra = f" reset_delta={found.get('reset_delta')}" if found["kind"] == "reset_off" else ""
            say(f"  FOUND in {dt:.2f}s: {found['kind']} msg_counter={found['msg']} "
                f"(we use {full}, offset {off:+d}){extra}", loud=True)
            say(f"  => EPS expects full msg_counter {found['msg']}; we reconstruct {full}. "
                f"FIX: add {off:+d} to our seed.", loud=True)

  def dump_ring(reason):
    say(f"---- RING DUMP ({reason}): last {len(ring)} lateral frames ----", loud=True)
    now_ns = time.monotonic_ns()
    for (lm, tag, addr, wire, rflag, full, mw, mc, match) in ring:
      age = (now_ns - lm) / 1e6
      flag = "PLACEHOLDER(ff)" if mc is None else ("OK " if match else "BAD")
      say(f"    -{age:7.1f}ms {tag:3s} 0x{addr:03X} wire={wire:2d} full={full:5d} rflag={rflag} "
          f"mac_wire={hexb(mw)} mac_calc={hexb(mc)} [{flag}]")
    say("---- end ring dump ----", loud=True)

  try:
    while True:
      can_batch = []
      raw = []  # (log_mono, direction, addr, data, src)
      for evt in messaging.drain_sock(can_sock, wait_for_one=False):
        can_batch.append((evt.logMonoTime, [(c.address, c.dat, c.src) for c in evt.can]))
        for c in evt.can:
          raw.append((evt.logMonoTime, "rx", c.address, bytes(c.dat), c.src))
      for evt in messaging.drain_sock(sendcan_sock, wait_for_one=False):
        for c in evt.sendcan:
          raw.append((evt.logMonoTime, "tx", c.address, bytes(c.dat), c.src))

      # update GW sync (trip/reset) + EPS state from this batch
      if can_batch:
        cp_gw.update(can_batch)
        cp_eps.update(can_batch)
        gw = cp_gw.vl["GW_Syn_All"]
        trip = (int(gw["Syn_TripCntrVal_Byte0_All"]) << 8) | int(gw["Syn_TripCntrVal_Byte1_All"])
        reset = ((int(gw["Syn_RstCntrVal_Byte0_All"]) << 16) | (int(gw["Syn_RstCntrVal_Byte1_All"]) << 8)
                 | int(gw["Syn_RstCntrVal_Byte2_All"]))
        mac = bytes([int(gw["Syn_MACInfo_Byte0_All"]), int(gw["Syn_MACInfo_Byte1_All"]), int(gw["Syn_MACInfo_Byte2_All"])])
        new_sync_ok = (sync_mac(key, trip, reset) == mac)
        if new_sync_ok and not have_sync:
          say(f"GW sync VERIFIED: key OK, trip={trip} reset={reset}. Now checking lateral MACs.", loud=True)
        if (not new_sync_ok) and (trip or reset) and not sync_fail_warned:
          say(f"GW sync key verify FAIL (trip={trip} reset={reset} wire_mac={hexb(mac)}). "
              f"Key or sync layout wrong — lateral MAC checks would be meaningless.", loud=True)
          sync_fail_warned = True
        sync_ok = new_sync_ok
        have_sync = have_sync or new_sync_ok

      # verify lateral frames only once we trust trip/reset
      if have_sync and sync_ok:
        raw.sort(key=lambda e: e[0])
        for (log_mono, direction, addr, data, src) in raw:
          if addr in (ADDR_1D0, ADDR_1C0):
            if direction == "rx" and src == OEM_BUS:
              verify_frame("oem", addr, data, log_mono)
            elif direction == "tx" and src == OUR_BUS:
              verify_frame("our", addr, data, log_mono)

      # EPS reject -> dump ring
      if can_batch:
        sts = int(cp_eps.vl["EPS_0x1C2"]["EPS_AdasLatCtrlSts"])
        abort = int(cp_eps.vl["EPS_0x1C2"]["EPS_AbortFb"])
        if (abort not in (0, 1) and last_abort in (0, 1)) or (sts == 3 and last_sts != 3):
          say(f"EPS REJECT: AdasLatCtrlSts {last_sts}->{sts}  AbortFb {last_abort}->{abort}", loud=True)
          dump_ring(f"abort={abort} sts={sts}")
        elif sts != last_sts or abort != last_abort:
          say(f"EPS: AdasLatCtrlSts {last_sts}->{sts}  AbortFb {last_abort}->{abort}")
        last_sts, last_abort = sts, abort

      now = time.monotonic()
      if now - last_summary > 2.0:
        last_summary = now
        parts = []
        for (tag, addr), (ok, bad, ph) in stats.items():
          if ok or bad or ph:
            parts.append(f"{tag}0x{addr:03X}:{ok}ok/{bad}bad/{ph}ff")
        say(f"summary sync={'OK' if sync_ok else ('waiting' if not have_sync else 'FAIL-now')} "
            f"trip={trip} reset={reset} | {'  '.join(parts) if parts else 'no lateral frames yet'}")

      time.sleep(0.003)

  except KeyboardInterrupt:
    say("=== stopped by user ===", loud=True)
  finally:
    say("final: " + "  ".join(f"{t}0x{a:03X}:{ok}ok/{bad}bad/{ph}ff" for (t, a), (ok, bad, ph) in stats.items()))
    log_f.close()


if __name__ == "__main__":
  main()
