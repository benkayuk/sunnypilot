"""Molex stAK50h 2-bay hybrid header 160013-0641, component-side footprint.

Geometry from Molex SD-160013-0001 sheets 2/3 (all mm): locator pegs 2x d3.75 spaced 29.85 (origin = midpoint),
bay pitch 19.60, tail rows at 13.30/16.30/19.30 (0.50 mm terminals, d1.10 holes, 2.00 pitch, 7 per row) and
22.30/25.30 (1.20 mm blades, d1.30 holes, 4.00 pitch, 4 per row) measured from the peg row away from the
mating face; body 40.39 wide, face edge 8.85 in front of the pegs, rear ~27.4 behind.
Circuit order per Molex's layout picture (as drawn): row 13.30 = 23..29, 16.30 = 16..22, 19.30 = 9..15,
22.30 = 5..8, 25.30 = 1..4, left to right, bay A left.  MIRROR=True flips X because that picture is read as a
solder-side view (the section view shows the top face rows landing farthest from the face, and the front view
has pin 1 top-left; both together put pin 1 on the right of a component-side view with the face up).
"""
import json, sys
MIRROR = True
P = sys.argv[1]
BAY = {"A": -9.80, "B": +9.80}
ROWS = [(13.30, list(range(23, 30)), [-6, -4, -2, 0, 2, 4, 6], 1.10, 1.45),
        (16.30, list(range(16, 23)), [-6, -4, -2, 0, 2, 4, 6], 1.10, 1.45),
        (19.30, list(range(9, 16)),  [-6, -4, -2, 0, 2, 4, 6], 1.10, 1.45),
        (22.30, [5, 6, 7, 8],        [-6, -2, 2, 6],           1.30, 1.90),
        (25.30, [1, 2, 3, 4],        [-6, -2, 2, 6],           1.30, 1.90)]
pads = []
for bay, bx in BAY.items():
    for y, ckts, cols, drill, size in ROWS:
        for ckt, cx in zip(ckts, cols):
            x = bx + cx
            if MIRROR: x = -x
            pads.append({"number": f"{bay}{ckt}", "type": "thru_hole", "shape": "rect" if ckt == 1 else "circle",
                         "x": round(x, 3), "y": round(y, 3), "width": size, "height": size, "drill": drill})
for x in (-14.925, 14.925):
    pads.append({"number": "", "type": "np_thru_hole", "shape": "circle", "x": x, "y": 0.0, "width": 3.75, "height": 3.75, "drill": 3.75})
fp = {"name": "Molex_stAK50h_160013-0641", "output": f"{P}/lib/icc_gateway.pretty/Molex_stAK50h_160013-0641.kicad_mod",
      "description": "Molex stAK50h 2-bay hybrid right-angle header 160013-0641, 2x29 circuits (A1-A29, B1-B29), component-side view, mating face toward -Y; pin map per SD-160013-0001 with X mirrored (see project notes), verify on a sample before fab",
      "package_type": "through_hole", "pads": pads, "body_width": 40.4, "body_height": 36.3}
print(json.dumps({"name": "create_footprint", "args": fp}))
print(json.dumps({"name": "get_footprint_info", "args": {"footprint_path": fp["output"], "include_pads": True}}))
