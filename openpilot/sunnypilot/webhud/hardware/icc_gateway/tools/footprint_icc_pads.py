"""Solder-wire field for the ICC pigtail: 2 bays x 29 holes, grouped like the stAK50h (circuits 1-8 big, 9-29 small)."""
import json, sys
P = sys.argv[1]
pads = []
for bay, bx in (("B", -12.0), ("A", 12.0)):
    for y, ckts, step, drill, size in ((-7.62, [4, 3, 2, 1], 5.08, 2.0, 2.8), (-2.54, [8, 7, 6, 5], 5.08, 2.0, 2.8),
                                       (2.54, [15, 14, 13, 12, 11, 10, 9], 2.54, 1.3, 1.75), (5.08, [22, 21, 20, 19, 18, 17, 16], 2.54, 1.3, 1.75),
                                       (7.62, [29, 28, 27, 26, 25, 24, 23], 2.54, 1.3, 1.75)):
        n = len(ckts); x0 = -(n - 1) * step / 2
        for i, ckt in enumerate(ckts):
            pads.append({"number": f"{bay}{ckt}", "type": "thru_hole", "shape": "rect" if ckt == 1 else "circle",
                         "x": round(bx + x0 + i * step, 3), "y": y, "width": size, "height": size, "drill": drill})
fp = {"name": "ICC_wire_pads_2x29", "output": f"{P}/lib/icc_gateway.pretty/ICC_wire_pads_2x29.kicad_mod",
      "description": "Solder field for the ICC-side pigtail: bay B left, bay A right; circuits 1-8 on 2.0 mm holes (power/speakers), 9-29 on 1.3 mm holes; numbering runs right-to-left like the header's mirrored layout; square pad = circuit 1",
      "package_type": "through_hole", "pads": pads, "body_width": 44, "body_height": 20}
print(json.dumps({"name": "create_footprint", "args": fp}))
