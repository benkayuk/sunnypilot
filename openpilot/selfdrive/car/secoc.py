"""Load or provision a SecOC key before card publishes its initial CarParams."""
from opendbc.car.fisker.secoc_key import recover_secoc_key


def configure_secoc_key(CI, params, can_recv, can_send, *, controller_available: bool, replay: bool):
  CI.CP.secOcKeyAvailable = False
  saved_secoc_key = None
  # Prefer the current param, then the user-provided cache. Malformed hex
  # must leave controls blocked, rather than crashing card.
  stored_keys = [params.get("SecOCKey")]
  try:
    with open("/cache/params/SecOCKey") as f:
      stored_keys.append(f.readline().strip())
  except OSError:
    pass
  for stored in stored_keys:
    try:
      key = bytes.fromhex(stored.strip()) if stored is not None else b""
    except (ValueError, TypeError):
      continue
    if len(key) == 16:
      saved_secoc_key = key
      break

  if saved_secoc_key is None and CI.CP.brand == "fisker" and not CI.CP.passive and not replay:
    saved_secoc_key = recover_secoc_key(can_recv, can_send)

  if saved_secoc_key is not None:
    CI.CS.secoc_key = saved_secoc_key
    if controller_available:
      CI.CC.secoc_key = saved_secoc_key
    CI.CP.secOcKeyAvailable = True
    params.put("SecOCKey", saved_secoc_key.hex(), block=True)
