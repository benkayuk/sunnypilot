import json, sys, os, re, collections
sys.path.insert(0, "/private/tmp/claude-501/-Users-evanelgin-sunnypilot-1/c8e7b7ca-0e68-4fcb-b273-e015cf12d115/scratchpad")
from design import *
out = open(os.environ["TMPDIR"] + "/sA.out").read()
pins = {}  # (sheet, ref) -> {pin: (x,y)}
for block in out.split("== get_schematic_pin_locations ")[1:]:
    head, _, body = block.partition("\n")
    args = json.loads(head[:head.rfind("}") + 1]) if head.strip().endswith("}") else None
    m = re.search(r'"reference": "([^"]+)"', head); ref = m.group(1)
    m2 = re.search(r'/([a-z_]+)\.kicad_sch', head); sheet = m2.group(1)
    body = body.strip().split("\n")[0]
    try:
        d = json.loads(body)
    except Exception as e:
        print("PARSE FAIL", ref, body[:100], file=sys.stderr); continue
    pins[(sheet, ref)] = {p["number"]: (p["x"], p["y"]) for p in d["pins"]}
def call(name, **a): print(json.dumps({"name": name, "args": a}))
# ESD diodes
conn = list(CONN)
for ref, h, l in ESD:
    conn += [("can", ref, "1", "g", h), ("can", ref, "2", "g", l), ("can", ref, "3", "p", "GND")]
labels = collections.OrderedDict()  # (sheet, net, kind) -> [pins]
for sheet, ref, pin, kind, net in conn:
    if kind in ("l", "g"):
        labels.setdefault((sheet, net, kind), []).append({"reference": ref, "pin_number": pin})
    elif kind == "p":
        x, y = pins[(sheet, ref)][pin]
        call("add_power_symbol", schematic=SHEET[sheet], power_net=net, x=x, y=y, rotation=0)
    elif kind == "nc":
        x, y = pins[(sheet, ref)][pin]
        call("add_no_connect", schematic=SHEET[sheet], x=x, y=y)
for (sheet, net, kind), plist in labels.items():
    a = dict(schematic=SHEET[sheet], net=net, pins=plist)
    if kind == "g": a["label_type"] = "global_label"
    call("batch_connect_to_net", **a)
# PWR_FLAGs: +5V and +3V3 on the mcu sheet (3V3 comes out of the Teensy), VBATT/GND on connectors sheet
call("batch_place_components", schematic=SHEET["mcu"], components=[
    {"lib_id": "power:PWR_FLAG", "reference": "#FLG01", "x": 40, "y": 40}, {"lib_id": "power:PWR_FLAG", "reference": "#FLG02", "x": 60, "y": 40}])
call("add_power_symbol", schematic=SHEET["mcu"], power_net="+3V3", x=40, y=40, rotation=0)
call("add_power_symbol", schematic=SHEET["mcu"], power_net="+5V", x=60, y=40, rotation=0)
call("batch_place_components", schematic=SHEET["connectors"], components=[
    {"lib_id": "power:PWR_FLAG", "reference": "#FLG03", "x": 300, "y": 40}, {"lib_id": "power:PWR_FLAG", "reference": "#FLG04", "x": 320, "y": 40}])
call("batch_connect_to_net", schematic=SHEET["connectors"], net="VBATT", label_type="global_label", pins=[{"reference": "#FLG03", "pin_number": "1"}])
call("add_power_symbol", schematic=SHEET["connectors"], power_net="GND", x=320, y=40, rotation=0)
for s in ("connectors", "power", "can", "bypass", "mcu"):
    call("render_schematic_png", schematic=SHEET[s], output=os.environ["TMPDIR"] + f"/render_{s}.png", width_px=3000)
call("run_erc", schematic=f"{P}/icc_gateway.kicad_sch", severity="warning")
