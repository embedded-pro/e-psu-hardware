"""Power copper for rev B (KiCad 10): planes on the inner layers and pours along the power paths.

    kicad10-python copper.py board.kicad_pcb

- In1.Cu: GND plane; GND_USB island under the USB side of the ADuM3160, with a gap all round.
- In2.Cu: +3V3 plane, with VIN_PROT and VPRE corridors (higher priority) and the same USB cut-out.
- F.Cu / B.Cu: solid-connected pours along each power net, as corridors through its power pads
  (minimum spanning tree of the listed pads, buffered to the corridor width).
Fill clearances come from the net classes, so other nets inside a corridor are cleared by the fill.
"""
import math
import sys

from kc import pcbnew
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union

OX, OY, BW, BH = 30.0, 59.92, 140.0, 80.0
INSET = 0.5                  # copper to board edge
USB_GAP = 1.5                # GND <-> GND_USB plane gap

PT = "/Pass-through & output switch/"
CM = "/Current measurement & auto-ranging/"
# net: (layers, width mm, [ref.pad ...], priority)
POURS = {
    "Net-(D101-A2)":            (("F.Cu", "B.Cu"), 5.0, ["J101.1", "F102.1", "F101.1", "D101.2"], 5),
    # down the outer side of R501 pad 1, so the gap between the shunt pads stays free for the Kelvin taps
    "VIN_PT":                   (("F.Cu", "B.Cu"), 4.5, ["F102.2", "@31.0,7.6", "R501.1"], 5),
    "Net-(U501-IN-)":           (("F.Cu", "B.Cu"), 5.0, ["R501.2", "K501.14"], 5),
    # relay common to the output switch through the channel between the relay's two pin rows
    PT + "SW_IN":               (("F.Cu", "B.Cu"), 4.0, ["K501.11", "@75.7,7.35", "@98.5,7.35", "@108.5,7.35", "Q502.5"], 5),
    PT + "SRC_COM":             (("F.Cu",), 3.0, ["Q502.1", "Q502.3", "Q503.1", "Q503.3"], 5),
    PT + "OUT_P":               (("F.Cu", "B.Cu"), 5.0, ["Q503.5", "J501.1", "D502.2"], 5),
    "Net-(Q101-D)":             (("F.Cu",), 3.0, ["F101.2", "Q101.2"], 5),
    "VIN_PROT":                 (("F.Cu",), 2.5, ["Q101.3", "C101.1", "C202.1", "C201.1"], 4),
    "VPRE":                     (("F.Cu",), 2.5, ["L201.2", "C211.1"], 4),
    # R301 pad 1 gets its current from Q301's source through In2 (via array at the pad's outer side)
    "Net-(D304-K)":             (("F.Cu",), 3.5, ["R301.1", "@52.4,16.5"], 5),
    "VFORCE":                   (("F.Cu",), 2.0, ["R301.2", "R401.1", "Q401.3", "D401.1"], 4),
    CM + "N_MID":               (("F.Cu",), 2.0, ["R401.2", "R402.1", "Q401.2", "Q402.3", "D401.3", "D402.1"], 4),
    "VSENSE":                   (("F.Cu",), 2.0, ["R402.2", "Q402.2", "D402.3", "K501.12"], 4),
    "/Tracking buck pre-regulator/SW_BUCK": (("F.Cu",), 2.5, ["U201.3", "L201.1"], 5),
}
# In2 corridors (pads reached through the layer; the corridor follows the same tree)
IN2 = {
    "VIN_PROT": (4.0, ["Q101.3", "C101.1", "U201.20", "U101.4"], 3),
    "VPRE":     (4.0, ["L201.2", "C211.1", "Q301.2"], 3),
    # Q301 source to the CC shunt crosses under the 10 A band on In2, beside VPRE
    "Net-(D304-K)": (3.5, ["Q301.3", "@55.9,10.0", "@52.6,13.3", "@52.6,16.5", "R301.1"], 4),
}
# Kelvin windows: no pour between a shunt's pads and in a strip across the current path, so the sense
# traces reach the inner pad edges without touching the power copper
SHUNTS = []          # not needed with flat-ended corridors that stop at the pad centres
KELVIN_SHUNTS = {"R501", "R301", "R401", "R402"}
# signal crossings through the 10 A band: gaps in its B.Cu copy (F.Cu carries the full current there)
# Q301's gate pin sits above the band at the top edge; the gate drive reaches it on B.Cu through this gap
B_CROSSINGS = [box(43.2, 4.6, 46.8, 15.5)]

# via arrays joining the layers of a power path at its SMD ends (about 1 A per 0.3 mm via)
# (net, anchor pad, count): vias go where every layer of the net's copper overlaps, nearest the anchor first
VIA_ARRAYS = [
    ("VIN_PT", "R501.1", 10), ("Net-(U501-IN-)", "R501.2", 10),
    ("/Pass-through & output switch/SW_IN", "Q502.5", 10), ("/Pass-through & output switch/OUT_P", "Q503.5", 10),
    ("VPRE", "L201.2", 6), ("VIN_PROT", "Q101.3", 6), ("VIN_PROT", "C201.1", 6), ("Net-(D304-K)", "R301.1", 6),
]
USB_SIDE = ["J701", "U701", "C701", "C702", "C703", "FB701", "R701", "R702", "R703", "R704", "R705"]


def nm(v):
    return pcbnew.FromMM(v)


def local(p):
    return pcbnew.ToMM(p.x) - OX, pcbnew.ToMM(p.y) - OY


def pad_of(board, spec):
    ref, num = spec.split(".")
    fp = board.FindFootprintByReference(ref)
    pads = [p for p in fp.Pads() if p.GetNumber() == num]
    if not pads:
        raise KeyError(spec)
    return pads


def pad_shape(p, grow=0.0):
    bb = p.GetBoundingBox()
    return box(pcbnew.ToMM(bb.GetLeft()) - OX - grow, pcbnew.ToMM(bb.GetTop()) - OY - grow,
               pcbnew.ToMM(bb.GetRight()) - OX + grow, pcbnew.ToMM(bb.GetBottom()) - OY + grow)


def mst(points):
    pts = list(points)
    if len(pts) < 2:
        return []
    inside, edges = {0}, []
    while len(inside) < len(pts):
        best = None
        for i in inside:
            for j in range(len(pts)):
                if j in inside:
                    continue
                d = math.dist(pts[i], pts[j])
                if best is None or d < best[0]:
                    best = (d, i, j)
        edges.append((pts[best[1]], pts[best[2]]))
        inside.add(best[2])
    return edges


def corridor(board, specs, width):
    path = any(s.startswith("@") for s in specs)
    pads, pts = [], []
    for s in specs:
        if s.startswith("@"):
            pts.append(tuple(float(v) for v in s[1:].split(",")))
        else:
            ps = pad_of(board, s)
            pads += ps
            pts.append(local(min(ps, key=lambda p: 0).GetPosition()) if not path else
                       min((local(p.GetPosition()) for p in ps), key=lambda c: math.dist(c, pts[-1]) if pts else 0))
    centers = [local(p.GetPosition()) for p in pads]
    # no pour skirt around shunt pads: the Kelvin taps reach their inner edges
    geo = [pad_shape(p, 0.0 if p.GetParentFootprint().GetReference() in KELVIN_SHUNTS else 0.4) for p in pads]
    if path:
        geo.append(LineString(pts).buffer(width / 2, cap_style=2, join_style=2))
        return unary_union(geo)
    for a, b in mst(centers):
        # octilinear dog-leg: straight leg then 45 degrees, so the pour edges follow the routing grid
        dx, dy = b[0] - a[0], b[1] - a[1]
        d = min(abs(dx), abs(dy))
        mid = (b[0] - math.copysign(d, dx), a[1]) if abs(dx) >= abs(dy) else (a[0], b[1] - math.copysign(d, dy))
        geo.append(LineString([a, mid, b]).buffer(width / 2, cap_style=2, join_style=2))
    return unary_union(geo)


def add_zone(board, net, layer, poly, priority, solid=True, min_w=0.25):
    if poly.is_empty:
        return 0
    polys = [poly] if poly.geom_type == "Polygon" else list(poly.geoms)
    n = 0
    for pg in polys:
        if pg.area < 1.0:
            continue
        z = pcbnew.ZONE(board)
        z.SetLayer(getattr(pcbnew, layer.replace(".", "_")))
        ni = board.FindNet(net)
        if ni is None:
            raise KeyError(net)
        z.SetNet(ni)
        ol = z.Outline()
        ol.NewOutline()
        for x, y in list(pg.exterior.coords)[:-1]:
            ol.Append(nm(OX + x), nm(OY + y))
        for hole in pg.interiors:
            ol.NewHole()
            for x, y in list(hole.coords)[:-1]:
                ol.Append(nm(OX + x), nm(OY + y), -1, 0)
        z.SetAssignedPriority(priority)
        z.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL if solid else pcbnew.ZONE_CONNECTION_THERMAL)
        z.SetMinThickness(nm(min_w))
        z.SetThermalReliefGap(nm(0.3))
        z.SetThermalReliefSpokeWidth(nm(0.4))
        z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
        board.Add(z)
        n += 1
    return n


def kelvin_windows(board):
    """net -> window geometry: each shunt clears only its own two nets."""
    out = {}
    for ref in SHUNTS:
        fp = board.FindFootprintByReference(ref)
        pads = sorted(fp.Pads(), key=lambda p: p.GetNumber())
        a, b = pad_shape(pads[0]), pad_shape(pads[1])
        ca, cb = a.centroid, b.centroid
        horiz = abs(cb.x - ca.x) >= abs(cb.y - ca.y)
        if horiz:
            x0 = min(a.bounds[2], b.bounds[2]) if ca.x < cb.x else min(a.bounds[2], b.bounds[2])
            lo, hi = sorted([a.bounds[2] if ca.x < cb.x else b.bounds[2], b.bounds[0] if ca.x < cb.x else a.bounds[0]])
            y0, y1 = min(a.bounds[1], b.bounds[1]) - 5.0, max(a.bounds[3], b.bounds[3]) + 5.0
            win = box(lo - 0.1, y0, hi + 0.1, y1)
        else:
            lo, hi = sorted([a.bounds[3] if ca.y < cb.y else b.bounds[3], b.bounds[1] if ca.y < cb.y else a.bounds[1]])
            x0, x1 = min(a.bounds[0], b.bounds[0]) - 5.0, max(a.bounds[2], b.bounds[2]) + 5.0
            win = box(x0, lo - 0.1, x1, hi + 0.1)
        for p in pads[:2]:
            out[p.GetNetname()] = unary_union([out.get(p.GetNetname(), box(0, 0, 0, 0)), win])
    return out


def filled(board, net, layer):
    lid = getattr(pcbnew, layer.replace(".", "_"))
    polys = []
    for z in board.Zones():
        if z.GetIsRuleArea() or z.GetNetname() != net or not z.IsOnLayer(lid):
            continue
        fp_ = z.GetFilledPolysList(lid)
        for i in range(fp_.OutlineCount()):
            ol = fp_.Outline(i)
            pts = [(pcbnew.ToMM(ol.CPoint(j).x) - OX, pcbnew.ToMM(ol.CPoint(j).y) - OY) for j in range(ol.PointCount())]
            if len(pts) >= 3:
                holes = [[(pcbnew.ToMM(fp_.Hole(i, h).CPoint(j).x) - OX, pcbnew.ToMM(fp_.Hole(i, h).CPoint(j).y) - OY)
                          for j in range(fp_.Hole(i, h).PointCount())] for h in range(fp_.HoleCount(i))]
                polys.append(Polygon(pts, holes).buffer(0))
    return unary_union(polys) if polys else None


def via_arrays(board, d=0.6, drill=0.3, pitch=1.0):
    """Vias where all copper layers of the net overlap (fills), next to the anchor pad, clear of SMD pads."""
    smd = unary_union([pad_shape(p, d / 2 + 0.1) for fp in board.GetFootprints() for p in fp.Pads()
                       if p.GetAttribute() == pcbnew.PAD_ATTRIB_SMD])
    others = []
    made = 0
    placed = []
    for net, anchor, count in VIA_ARRAYS:
        lay = [l for l in ("F.Cu", "In2.Cu", "B.Cu") if filled(board, net, l) is not None]
        if len(lay) < 2:
            print("  no overlap for", net)
            continue
        region = None
        for l in lay:
            f = filled(board, net, l).buffer(-(d / 2 + 0.05))
            region = f if region is None else region.intersection(f)
        region = region.difference(smd)
        if region.is_empty:
            print("  empty via region for", net)
            continue
        a = local(pad_of(board, anchor)[0].GetPosition())
        cands = []
        x0, y0, x1, y1 = region.bounds
        gx = math.floor(x0 / 0.25) * 0.25
        while gx <= x1:
            gy = math.floor(y0 / 0.25) * 0.25
            while gy <= y1:
                if region.contains(Point(gx, gy)) and math.dist((gx, gy), a) < 8.0:
                    cands.append((math.dist((gx, gy), a), gx, gy))
                gy += 0.25
            gx += 0.25
        n = 0
        for _, x, y in sorted(cands):
            if any(math.dist((x, y), q) < pitch - 1e-6 for q in placed):
                continue
            v = pcbnew.PCB_VIA(board)
            v.SetPosition(pcbnew.VECTOR2I(nm(OX + x), nm(OY + y)))
            v.SetWidth(nm(d)); v.SetDrill(nm(drill)); v.SetNet(board.FindNet(net))
            v.SetViaType(pcbnew.VIATYPE_THROUGH)
            v.SetLocked(True)
            board.Add(v)
            placed.append((x, y))
            n += 1
            if n >= count:
                break
        if n < count:
            print(f"  {net} at {anchor}: {n}/{count} vias")
        made += n
    return made


def solid_thermal_vias(board):
    """Exposed-pad thermal vias (plated holes sharing an SMD pad's number) join every plane solid:
    thermal spokes on 0.65 mm pads would starve them (KiCad starved_thermal) and add thermal resistance."""
    n = 0
    for fp in board.GetFootprints():
        smd = {p.GetNumber() for p in fp.Pads() if p.GetAttribute() == pcbnew.PAD_ATTRIB_SMD and p.GetNumber()}
        for p in fp.Pads():
            if p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH and p.GetNumber() in smd and pcbnew.ToMM(p.GetDrillSizeX()) <= 0.5:
                p.SetLocalZoneConnection(pcbnew.ZONE_CONNECTION_FULL)
                n += 1
    return n


def run(path):
    board = pcbnew.LoadBoard(path)
    for z in list(board.Zones()):
        board.Remove(z)
    print("thermal vias joined solid:", solid_thermal_vias(board))
    edge = box(INSET, INSET, BW - INSET, BH - INSET)
    usb = unary_union([pad_shape(p, 0.8) for r in USB_SIDE for p in board.FindFootprintByReference(r).Pads()])
    # USB side of the isolator: its bottom pin row joins the island
    u702 = board.FindFootprintByReference("U702")
    usb = unary_union([usb] + [pad_shape(p, 0.8) for p in u702.Pads() if p.GetNetname() in
                               ("GND_USB", "Net-(U702-VBUS1)") or "UD" in p.GetNetname() or "PDEN" in p.GetNetname()])
    island = usb.convex_hull.buffer(1.0, join_style=2).intersection(edge)
    cut = island.buffer(USB_GAP, join_style=2)
    count = 0
    count += add_zone(board, "GND", "In1.Cu", edge.difference(cut), 0, solid=False)
    count += add_zone(board, "GND_USB", "In1.Cu", island, 0, solid=False)
    count += add_zone(board, "+3V3", "In2.Cu", edge.difference(cut), 0, solid=False)
    for net, (w, specs, pri) in IN2.items():
        count += add_zone(board, net, "In2.Cu", corridor(board, specs, w).intersection(edge.difference(cut)), pri)
    windows = kelvin_windows(board)
    for net, (layers, w, specs, pri) in POURS.items():
        poly = corridor(board, specs, w).intersection(edge)
        if net in windows:
            poly = poly.difference(windows[net])
        for layer in layers:
            pl = poly.difference(unary_union(B_CROSSINGS)) if layer == "B.Cu" else poly
            count += add_zone(board, net, layer, pl, pri)
    filler = pcbnew.ZONE_FILLER(board)
    filler.Fill(board.Zones())
    print("zones:", count, "power vias:", via_arrays(board))
    filler.Fill(board.Zones())
    pcbnew.SaveBoard(path, board)


if __name__ == "__main__":
    run(sys.argv[1])
