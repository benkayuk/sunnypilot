import sys, pcbnew
from pcbnew import VECTOR2I, FromMM, ToMM
board = pcbnew.LoadBoard(sys.argv[1])
vin = board.FindNet("VIN_PROT").GetNetCode(); gcode = board.FindNet("GND").GetNetCode()
# a. clear every VIN_PROT track in the top-right corner region and lay a clean route
dele = [t for t in board.GetTracks() if t.GetClass() == "PCB_TRACK" and t.GetNetCode() == vin
        and all(ToMM(p.x) >= 92 and ToMM(p.y) <= 14.5 for p in (t.GetStart(), t.GetEnd()))]
for t in dele: board.Remove(t)
print("VIN_PROT corner segments removed:", len(dele))
def seg(a, b, w=1.0):
    tr = pcbnew.PCB_TRACK(board); tr.SetStart(VECTOR2I(FromMM(a[0]), FromMM(a[1]))); tr.SetEnd(VECTOR2I(FromMM(b[0]), FromMM(b[1])))
    tr.SetWidth(FromMM(w)); tr.SetLayer(pcbnew.F_Cu); tr.SetNetCode(vin); board.Add(tr)
for pts in ([(93.85, 4.5), (93.85, 2.2), (103.6, 2.2), (103.6, 10.0)], [(103.6, 10.0), (103.6, 13.5), (104.05, 13.5), (104.05, 17.0)]):
    for a, b in zip(pts, pts[1:]): seg(a, b)
# b. report GND outer-pour fragments without a through connection
filler = pcbnew.ZONE_FILLER(board); filler.Fill(board.Zones())
thr = []
for fp in board.GetFootprints():
    for pad in fp.Pads():
        if pad.GetNetCode() == gcode and pad.GetAttribute() == pcbnew.PAD_ATTRIB_PTH: thr.append(pad.GetPosition())
thr += [t.GetPosition() for t in board.GetTracks() if t.GetClass() == "PCB_VIA" and t.GetNetCode() == gcode]
smd = [(fp.GetReference(), pad.GetNumber(), pad.GetPosition()) for fp in board.GetFootprints() for pad in fp.Pads()
       if pad.GetNetCode() == gcode and pad.GetAttribute() != pcbnew.PAD_ATTRIB_PTH]
for z in board.Zones():
    if z.GetNetCode() != gcode: continue
    for layer in (pcbnew.F_Cu, pcbnew.B_Cu):
        if not z.IsOnLayer(layer): continue
        polys = z.GetFilledPolysList(layer)
        for i in range(polys.OutlineCount()):
            if any(polys.Contains(p, i) for p in thr): continue
            ol = polys.Outline(i); bb = ol.BBox()
            pads = [f"{r}-{n}" for (r, n, p) in smd if polys.Contains(p, i)]
            print("  fragment", board.GetLayerName(layer), "bbox", round(ToMM(bb.GetX()),1), round(ToMM(bb.GetY()),1), round(ToMM(bb.GetWidth()),1), "x", round(ToMM(bb.GetHeight()),1), "pads", pads)
pcbnew.SaveBoard(sys.argv[1], board); print("saved")
