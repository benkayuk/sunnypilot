#!/usr/bin/env python3
"""
debug_fisker_secoc.py — SecOC counter forensics for the Ocean lateral abort (0x1D0).

Runs ALONGSIDE sunnypilot (read-only). Earlier runs established:
  * our SecOCKey + MAC algorithm + DataId reproduce OEM's own accepted 0x1D0 MACs
    exactly (GW sync verifies, and many OEM frames verify) -> the crypto is correct;
  * 0x1C0 is NOT SecOC (OEM sends ff placeholder) -> ignored here;
  * the abort is a FULL-COUNTER problem: only 6 bits of msg_counter are on the wire,
    the MAC covers the full 16 bits, and the high bits (per-window wrap count) + the
    reset window must match what the EPS expects.

So instead of reconstructing the counter (which drifts if you start mid-window), this
tool DECODES the true (reset, full msg_counter) straight from each frame's MAC — it's
ground truth. We pin the reset with the wire reset-flag (rflag = reset & 3) and search
only the high-bit multiples (wire + 64*k), so it's fast.

The money shot — SEED CHECK at engage:
    When our TX of 0x1D0 starts (first frame after an idle gap), we decode OEM's last
    bus-2 counter and our first transmitted counter. The EPS expects a continuous stream,
    so our first TX should be OEM_last + 1. Any other offset is the seed bug, printed as
    e.g. "SEED CHECK: OEM_last=163 our_first=99 diff=-64  <-- OFF, EPS will reject".
Plus a steady continuity check and an abort ring dump, both in true decoded counters.

Usage:  cd /data/openpilot && PYTHONPATH=. python3 scripts/debug_fisker_secoc.py
Writes /data/fisker_secoc_debug.log + stdout. Ctrl-C to stop.
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
OEM_BUS = 2
OUR_BUS = 0
MAX_K = 64                 # full counter per ~1 s window is <~130, so k<=2; 64 is plenty
ENGAGE_GAP_NS = 50_000_000  # >50 ms with no TX = an engage edge


def fmt_ts() -> str:
  return datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]


def hexb(b):
  return b.hex() if b else "--"


def decode_true(key, pdu, mac_wire, wire, rflag, trip, gw_reset):
  """Decode the true (reset, full msg_counter) from a 0x1D0 frame's MAC. The wire rflag
  pins reset mod 4; try the few reset windows around the GW value, then the high-bit
  multiples of the counter (low 6 bits already == wire). Returns (reset, full) or None."""
  for r in (gw_reset, gw_reset - 1, gw_reset + 1, gw_reset - 2, gw_reset + 2):
    if r < 0 or (r & 3) != rflag:
      continue
    for k in range(MAX_K):
      m = wire + 64 * k
      if secoc_mac(key, ADDR_1D0, pdu, trip, r, m) == mac_wire:
        return r, m
  return None


def parts(data):
  """(wire, rflag, pdu, mac) from a raw 0x1D0 frame."""
  return (data[4] >> 2) & 0x3F, data[4] & 0x3, bytes(data[0:4]), bytes(data[5:8])


def main():
  log_f = open(Path("/data/fisker_secoc_debug.log"), "a", buffering=1)

  def say(s, *, loud=False):
    line = f"[{fmt_ts()}] {'***' if loud else '   '} {s}"
    print(line, flush=True)
    log_f.write(line + "\n")

  say("=== fisker SecOC counter forensics (0x1D0) ===", loud=True)

  key = None
  try:
    from openpilot.common.params import Params
    raw = Params().get("SecOCKey")
    if raw is not None:
      key = bytes.fromhex((raw.decode() if isinstance(raw, (bytes, bytearray)) else raw).strip())
  except Exception as e:  # noqa: BLE001
    say(f"ERROR reading SecOCKey: {e}", loud=True)
  if not key or len(key) != 16:
    say("ERROR: need a 16-byte SecOCKey in params. Cannot verify MACs.", loud=True)
    return
  say(f"SecOCKey loaded ({len(key)} bytes). Waiting for GW sync (0x20)...")

  can_sock = messaging.sub_sock("can", conflate=False, timeout=50)
  sendcan_sock = messaging.sub_sock("sendcan", conflate=False, timeout=50)
  cp_gw = CANParser(ADAS_DBC, [("GW_Syn_All", 0)], 0)
  cp_eps = CANParser(ADAS_DBC, [("EPS_0x1C2", 0)], 0)

  trip = reset = 0
  have_sync = sync_ok = False
  sync_fail_warned = False

  # steady-state continuity: last decoded true counter per source
  last_true = {"oem": None, "our": None}
  cont = {"oem": [0, 0], "our": [0, 0]}  # [+1 steps, non-+1 steps] within a window
  last_oem_frame = None                  # (wire, rflag, pdu, mac) of most recent OEM bus-2 0x1D0
  last_our_tx_ns = 0
  ring = deque(maxlen=120)               # (ns, tag, wire, rflag, pdu, mac)
  last_sts = None
  last_abort = 0
  last_summary = time.monotonic()
  dropped = {"oem": 0, "our": 0}         # couldn't decode (no MAC match) — alarming if >0 for oem

  def decode(tag, data):
    wire, rflag, pdu, mac = parts(data)
    dec = decode_true(key, pdu, mac, wire, rflag, trip, reset)
    if dec is None:
      dropped[tag] += 1
      return None
    r, full = dec
    # continuity (within a window): did it advance by exactly 1?
    prev = last_true[tag]
    if prev is not None:
      step = full - prev
      if step == 1:
        cont[tag][0] += 1
      elif step != 0:
        cont[tag][1] += 1
    last_true[tag] = full
    return r, full, wire

  try:
    while True:
      can_batch = []
      raw = []
      for evt in messaging.drain_sock(can_sock, wait_for_one=False):
        can_batch.append((evt.logMonoTime, [(c.address, c.dat, c.src) for c in evt.can]))
        for c in evt.can:
          raw.append((evt.logMonoTime, "rx", c.address, bytes(c.dat), c.src))
      for evt in messaging.drain_sock(sendcan_sock, wait_for_one=False):
        for c in evt.sendcan:
          raw.append((evt.logMonoTime, "tx", c.address, bytes(c.dat), c.src))

      if can_batch:
        cp_gw.update(can_batch)
        cp_eps.update(can_batch)
        gw = cp_gw.vl["GW_Syn_All"]
        trip = (int(gw["Syn_TripCntrVal_Byte0_All"]) << 8) | int(gw["Syn_TripCntrVal_Byte1_All"])
        reset = ((int(gw["Syn_RstCntrVal_Byte0_All"]) << 16) | (int(gw["Syn_RstCntrVal_Byte1_All"]) << 8)
                 | int(gw["Syn_RstCntrVal_Byte2_All"]))
        mac = bytes([int(gw["Syn_MACInfo_Byte0_All"]), int(gw["Syn_MACInfo_Byte1_All"]), int(gw["Syn_MACInfo_Byte2_All"])])
        now_ok = (sync_mac(key, trip, reset) == mac)
        if now_ok and not have_sync:
          say(f"GW sync VERIFIED: key OK, trip={trip} reset={reset}. Decoding 0x1D0 counters.", loud=True)
        if (not now_ok) and (trip or reset) and not sync_fail_warned:
          say(f"GW sync key verify FAIL (trip={trip} reset={reset}). Key/layout wrong.", loud=True)
          sync_fail_warned = True
        sync_ok = now_ok
        have_sync = have_sync or now_ok

      if have_sync and sync_ok:
        raw.sort(key=lambda e: e[0])
        for (ns, direction, addr, data, src) in raw:
          if addr != ADDR_1D0 or len(data) < 8:
            continue
          if direction == "rx" and src == OEM_BUS:
            last_oem_frame = parts(data)
            d = decode("oem", data)
            ring.append((ns, "oem", data[4], d))
          elif direction == "tx" and src == OUR_BUS:
            # engage edge: first TX after an idle gap -> SEED CHECK vs OEM's last frame
            if ns - last_our_tx_ns > ENGAGE_GAP_NS:
              oem_dec = None
              if last_oem_frame is not None:
                ow, orf, opdu, om = last_oem_frame
                oem_dec = decode_true(key, opdu, om, ow, orf, trip, reset)
              uw, urf, updu, um = parts(data)
              our_dec = decode_true(key, updu, um, uw, urf, trip, reset)
              if oem_dec and our_dec:
                diff = our_dec[1] - (oem_dec[1] + 1)
                verdict = "continuous (OK)" if diff == 0 else f"OFF by {diff:+d}  <-- EPS will reject"
                say(f"SEED CHECK @engage: OEM_last_full={oem_dec[1]} our_first_full={our_dec[1]} "
                    f"(expect OEM_last+1={oem_dec[1] + 1}) -> {verdict}", loud=True)
              else:
                say(f"SEED CHECK @engage: could not decode (oem={oem_dec} our={our_dec})", loud=True)
              last_true["our"] = None  # restart our continuity for this engagement
            last_our_tx_ns = ns
            d = decode("our", data)
            ring.append((ns, "our", data[4], d))

      if can_batch:
        sts = int(cp_eps.vl["EPS_0x1C2"]["EPS_AdasLatCtrlSts"])
        abort = int(cp_eps.vl["EPS_0x1C2"]["EPS_AbortFb"])
        if (abort not in (0, 1) and last_abort in (0, 1)) or (sts == 3 and last_sts != 3):
          say(f"EPS REJECT: sts {last_sts}->{sts}  abort {last_abort}->{abort}", loud=True)
          say(f"---- RING DUMP: last {len(ring)} 0x1D0 frames (decoded true full counter) ----", loud=True)
          now_ns = time.monotonic_ns()
          for (ns, tag, b4, dec) in ring:
            age = (now_ns - ns) / 1e6
            if dec is None:
              say(f"    -{age:7.1f}ms {tag:3s} wire={(b4 >> 2) & 0x3F:2d} rflag={b4 & 3} full=UNDECODABLE")
            else:
              say(f"    -{age:7.1f}ms {tag:3s} wire={(b4 >> 2) & 0x3F:2d} rflag={b4 & 3} reset={dec[0]} full={dec[1]}")
          say("---- end ring dump ----", loud=True)
        elif sts != last_sts or abort != last_abort:
          say(f"EPS: sts {last_sts}->{sts}  abort {last_abort}->{abort}")
        last_sts, last_abort = sts, abort

      now = time.monotonic()
      if now - last_summary > 2.0:
        last_summary = now
        say(f"summary sync={'OK' if sync_ok else ('waiting' if not have_sync else 'FAIL')} "
            f"trip={trip} reset={reset} | oem +1:{cont['oem'][0]}/jump:{cont['oem'][1]}/undec:{dropped['oem']} "
            f"last={last_true['oem']} || our +1:{cont['our'][0]}/jump:{cont['our'][1]}/undec:{dropped['our']} "
            f"last={last_true['our']}")

      time.sleep(0.003)

  except KeyboardInterrupt:
    say("=== stopped by user ===", loud=True)
  finally:
    say(f"final: oem +1:{cont['oem'][0]}/jump:{cont['oem'][1]}/undec:{dropped['oem']}  "
        f"our +1:{cont['our'][0]}/jump:{cont['our'][1]}/undec:{dropped['our']}")
    log_f.close()


if __name__ == "__main__":
  main()
