import json, sys
sys.path.insert(0, "/private/tmp/claude-501/-Users-evanelgin-sunnypilot-1/c8e7b7ca-0e68-4fcb-b273-e015cf12d115/scratchpad")
from design import *
def call(name, **a): print(json.dumps({"name": name, "args": a}))
for s in ("power", "can", "bypass", "mcu"):
    call("set_schematic_page", schematic=SHEET[s], size="A3")
    comps = [{"lib_id": l, "reference": r, "value": v, "footprint": f, "x": x, "y": y, "rotation": rot}
             for (sh, r, l, v, f, x, y, rot) in COMPONENTS if sh == s]
    call("batch_place_components", schematic=SHEET[s], components=comps)
for (sh, r, *_rest) in COMPONENTS:
    call("get_schematic_pin_locations", schematic=SHEET[sh], reference=r)
for lib in ("Power_Protection:NUP2105L", "Device:Battery_Cell", "power:PWR_FLAG"):
    call("get_symbol_info", lib_id=lib)
# connectors sheet: GND on A5 of both connectors + PWR_FLAGs
C = SHEET["connectors"]
call("add_power_symbol", schematic=C, power_net="GND", x=43.18, y=34.29, rotation=0)
call("add_power_symbol", schematic=C, power_net="GND", x=203.2, y=34.29, rotation=0)
