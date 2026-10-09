import sys, pcbnew
from pcbnew import VECTOR2I, FromMM, ToMM
board = pcbnew.LoadBoard(sys.argv[1])
vin = board.FindNet("VIN_PROT").GetNetCode()
# a. delete the VIN_PROT detour along the top-right corner
dele = []
for t in board.GetTracks():
    if t.GetClass() == "PCB_TRACK" and t.GetNetCode() == vin:
        s, e = t.GetStart(), t.GetEnd()
        xs = [ToMM(s.x), ToMM(e.x)]; ys = [ToMM(s.y), ToMM(e.y)]
        if (max(ys) < 2.5) or (min(xs) > 103.5 and max(ys) < 13):
            dele.append(t)
for t in dele: board.Remove(t)
print("VIN_PROT detour segments removed:", len(dele))
def seg(a, b, w=1.0, layer=pcbnew.F_Cu):
    tr = pcbnew.PCB_TRACK(board); tr.SetStart(VECTOR2I(FromMM(a[0]), FromMM(a[1]))); tr.SetEnd(VECTOR2I(FromMM(b[0]), FromMM(b[1])))
    tr.SetWidth(FromMM(w)); tr.SetLayer(layer); tr.SetNetCode(vin); board.Add(tr)
pts = [(93.85, 4.5), (93.85, 6.8), (97.3, 6.8), (97.3, 13.5), (104.05, 13.5), (104.05, 17.0)]
for a, b in zip(pts, pts[1:]): seg(a, b)
print("VIN_PROT re-routed D2 -> C3 in", len(pts) - 1, "segments")
# b. widen sub-minimum neck-downs
n = 0
for t in board.GetTracks():
    if t.GetClass() == "PCB_TRACK" and t.GetWidth() < FromMM(0.09):
        t.SetWidth(FromMM(0.15)); n += 1
print("tracks widened to 0.15:", n)
# c. delete vias that touch tracks on fewer than two layers and no THT/zone net other than their own tracks
tracks = [t for t in board.GetTracks() if t.GetClass() == "PCB_TRACK"]
removed = 0
for v in [t for t in board.GetTracks() if t.GetClass() == "PCB_VIA"]:
    p = v.GetPosition(); layers = set()
    for t in tracks:
        if t.GetNetCode() == v.GetNetCode() and (t.GetStart() == p or t.GetEnd() == p):
            layers.add(t.GetLayer())
    if len(layers) < 2 and v.GetNetname() not in ("GND",):
        board.Remove(v); removed += 1
print("dangling vias removed:", removed)
pcbnew.SaveBoard(sys.argv[1], board); print("saved")
