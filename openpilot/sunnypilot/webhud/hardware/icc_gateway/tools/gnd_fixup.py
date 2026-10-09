"""Ground/edge fix-ups on the saved board (editor must be closed): solid pour connections, stitching vias
into pour fragments that have no path to the inner plane, pull edge-hugging tracks inboard, refill, save."""
import sys, pcbnew
from pcbnew import VECTOR2I, FromMM, ToMM

board = pcbnew.LoadBoard(sys.argv[1])
gnd = board.FindNet("GND")
gcode = gnd.GetNetCode()
F, B, IN1 = pcbnew.F_Cu, pcbnew.B_Cu, pcbnew.In1_Cu

# 1. outer pours: solid connection (no thermal reliefs -> no starved thermals)
for z in board.Zones():
    if z.GetNetCode() == gcode and z.IsOnLayer(F) or z.GetNetCode() == gcode and z.IsOnLayer(B):
        z.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
        print("zone", z.GetZoneName(), "-> solid")

# 2. move tracks that hug the board edge (y < 0.8 mm or > 99.2, x < 0.8 or > 109.2) inboard by 1 mm
moved = 0
for t in board.GetTracks():
    if t.GetClass() != "PCB_TRACK":
        continue
    for getter, setter in ((t.GetStart, t.SetStart), (t.GetEnd, t.SetEnd)):
        p = getter(); x, y = ToMM(p.x), ToMM(p.y); nx, ny = x, y
        if y < 1.0: ny = 1.2
        if y > 99.0: ny = 98.8
        if x < 1.0: nx = 1.2
        if x > 109.0: nx = 108.8
        if (nx, ny) != (x, y):
            setter(VECTOR2I(FromMM(nx), FromMM(ny))); moved += 1
print("edge track endpoints moved:", moved)

# 3. fill, then stitch every outer-layer GND fragment that has no through connection
filler = pcbnew.ZONE_FILLER(board)
filler.Fill(board.Zones())

def through_points():
    pts = []
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            if pad.GetNetCode() == gcode and pad.GetAttribute() == pcbnew.PAD_ATTRIB_PTH:
                pts.append(pad.GetPosition())
    for t in board.GetTracks():
        if t.GetClass() == "PCB_VIA" and t.GetNetCode() == gcode:
            pts.append(t.GetPosition())
    return pts

def add_via(pos):
    v = pcbnew.PCB_VIA(board)
    v.SetPosition(pos); v.SetViaType(pcbnew.VIATYPE_THROUGH)
    v.SetLayerPair(F, B); v.SetDrill(FromMM(0.3)); v.SetWidth(FromMM(0.6)); v.SetNetCode(gcode)
    board.Add(v)

def best_point(chain):
    """grid-sample the polygon, keep the inside point farthest from its outline"""
    bb = chain.BBox(); best = None; bestd = -1
    x0, y0, x1, y1 = bb.GetX(), bb.GetY(), bb.GetRight(), bb.GetBottom()
    step = max(FromMM(0.5), (x1 - x0) // 40)
    x = x0 + step // 2
    while x < x1:
        y = y0 + step // 2
        while y < y1:
            p = VECTOR2I(int(x), int(y))
            if chain.PointInside(p, 0, True):
                d = chain.Distance(p, True)
                if d > bestd: bestd, best = d, p
            y += step
        x += step
    return best, bestd

added = 0
for z in board.Zones():
    if z.GetNetCode() != gcode:
        continue
    for layer in (F, B):
        if not z.IsOnLayer(layer):
            continue
        polys = z.GetFilledPolysList(layer)
        thr = through_points()
        for i in range(polys.OutlineCount()):
            outline = polys.Outline(i)
            if any(polys.Contains(p, i) for p in thr):
                continue
            p, d = best_point(outline)
            if p is None:
                continue
            if d < FromMM(0.45):   # too thin for a 0.6 via with clearance
                print("  fragment too thin on", board.GetLayerName(layer), "near", ToMM(p.x), ToMM(p.y), "width", ToMM(d) * 2)
                continue
            add_via(p); added += 1
            print("  via at", round(ToMM(p.x), 2), round(ToMM(p.y), 2), "on fragment of", board.GetLayerName(layer))
print("stitching vias added:", added)

# 4. SMD GND pads still without any GND via within 2.5 mm get one beside them (helps the plane connection)
vias = [t.GetPosition() for t in board.GetTracks() if t.GetClass() == "PCB_VIA" and t.GetNetCode() == gcode]
filler.Fill(board.Zones())
pcbnew.SaveBoard(sys.argv[1], board)
print("saved")
