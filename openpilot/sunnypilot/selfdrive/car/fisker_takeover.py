"""
The driver-takeover torque for the Fisker's steering, set live from FiskerOverrideTorque (OceanScape's slider).

openpilot lets go of the wheel once the driver has held more than this torque for ~0.1 s (opendbc carstate). The EPS's
own intervention cut-out is ~6.5 Nm, so the slider runs 1.5-6.4 Nm and its top step, 6.5, means "the car's own": only
the EPS bit releases. card reads it with its other params at 10 Hz and sets it on the CarState, so a change applies
within ~0.1 s, even while driving.
"""
import math

PARAM = "FiskerOverrideTorque"
MIN_NM = 1.5
EPS_NM = 6.5     # the EPS's own intervention torque: at or above this, leave the takeover to it
DEFAULT_NM = 3.0


def valid(nm: float) -> bool:
  return math.isfinite(nm) and MIN_NM <= nm <= EPS_NM


def takeover_torque(params) -> float:
  """The CarState threshold for the current setting: Nm, or inf for the EPS's own; the default if unset or bad."""
  try:
    nm = float(params.get(PARAM, return_default=True))
  except (TypeError, ValueError):
    return DEFAULT_NM
  if not valid(nm):
    return DEFAULT_NM
  return math.inf if nm >= EPS_NM else nm
