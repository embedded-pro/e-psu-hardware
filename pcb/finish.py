"""After routing: ground fills on the outer layers, GND stitching, silkscreen and markings."""
import pcbnew
from shapely.geometry import Point, Polygon, box
from shapely.ops import unary_union
from shapely.prepared import prep

import copper
import place
import power
import silk


def outer_fills(board):
    """GND / GND_USB / VFORCE fills on F.Cu and B.Cu (lowest priority), split like In1."""
    edge = box(0, 0, place.BW, place.BH).buffer(-copper.EDGE_CLR, join_style=2)
    regions = [("GND_USB", power.S["usb_i1"]), ("VFORCE", power.S["island_i1"]),
               ("GND", power.S["gnd_i1"])]
    zs = []
    for layer in ("F.Cu", "B.Cu"):
        for net, shape in regions:
            g = shape.intersection(edge)
            zs += copper.make_zone(board, net, layer, g, dict(clr=0.25, connect="full"), 0)
    for z in zs:
        z.SetThermalReliefGap(copper.nm(0.3))
    return zs


def filled(board, layer, net):
    out = []
    for z in board.Zones():
        if z.GetLayer() == layer and z.GetNetname() == net and z.IsFilled():
            fp_ = z.GetFilledPolysList(layer)
            for i in range(fp_.OutlineCount()):
                ol = fp_.Outline(i)
                ext = [copper.from_abs(ol.CPoint(k)) for k in range(ol.PointCount())]
                holes = []
                for h in range(fp_.HoleCount(i)):
                    hl = fp_.Hole(i, h)
                    holes.append([copper.from_abs(hl.CPoint(k)) for k in range(hl.PointCount())])
                if len(ext) >= 3:
                    out.append(Polygon(ext, holes).buffer(0))
    return unary_union(out) if out else Polygon()


def gnd_stitch(board, pitch=4.0, log=print):
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    n = 0
    for net, region in (("GND", power.S["gnd_i1"]), ("GND_USB", power.S["usb_i1"]), ("VFORCE", power.S["island_i1"])):
        f = filled(board, pcbnew.F_Cu, net)
        b = filled(board, pcbnew.B_Cu, net)
        ok = f.intersection(b).intersection(region.buffer(-0.8)).buffer(-0.55)
        # keep away from existing vias and pads
        avoid = []
        for t in board.GetTracks():
            if isinstance(t, pcbnew.PCB_VIA):
                avoid.append(Point(copper.from_abs(t.GetPosition())).buffer(1.0))
        for fp in board.GetFootprints():
            for p in fp.Pads():
                if p.GetAttribute() in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH):
                    avoid.append(copper.pad_geom(p, 0.6))
        if avoid:
            ok = ok.difference(unary_union(avoid))
        pk = prep(ok)
        y = 1.5
        row = 0
        while y < place.BH:
            x = 1.5 + (pitch / 2 if row % 2 else 0)
            while x < place.BW:
                if pk.contains(Point(x, y)):
                    copper.add_via(board, net, x, y, locked=False)
                    n += 1
                x += pitch
            y += pitch * 0.866
            row += 1
    log(f"ground stitching vias: {n}")
    return n


def markings(board):
    T = silk.text
    T(board, "IN+", 9.5, 23.5, 1.3, bold=True)
    T(board, "IN-", 9.5, 27.0, 1.3, bold=True)
    T(board, "OUT+", 91.5, 22.75, 1.3, bold=True)
    T(board, "OUT-", 91.5, 27.25, 1.3, bold=True)
    T(board, "e-psu", 50.0, 95.0, 2.0, bold=True, layer=pcbnew.B_SilkS)
    T(board, "USB-controlled bench PSU front end  rev A", 50.0, 97.8, 1.0, layer=pcbnew.B_SilkS)
    T(board, "4-layer: F sig / In1 GND / In2 PWR / B sig", 50.0, 3.0, 0.9, layer=pcbnew.B_SilkS)
    T(board, "JLCJLCJLCJLC", 50.0, 6.0, 0.9, layer=pcbnew.B_SilkS)
    T(board, "ISOLATED USB", 10.0, 68.0, 0.9, layer=pcbnew.B_SilkS)
    T(board, "RANGING ISLAND (VFORCE)", 85.5, 75.6, 0.8, layer=pcbnew.B_SilkS)
    # isolation boundaries on the bottom silkscreen
    for shape in (power.S["usb_i1"], power.S["island_i1"]):
        pts = list(shape.buffer(0.5, join_style=2).exterior.coords)
        for a, b in zip(pts, pts[1:]):
            if not all(0.3 < v < place.BW - 0.3 for v in (a[0], b[0], a[1], b[1])):
                continue
            s = pcbnew.PCB_SHAPE(board)
            s.SetShape(pcbnew.SHAPE_T_SEGMENT)
            s.SetStart(copper.to_abs(*a)); s.SetEnd(copper.to_abs(*b))
            s.SetLayer(pcbnew.B_SilkS); s.SetWidth(copper.nm(0.15))
            board.Add(s)


def apply(board, log=print):
    cleanup(board, log)
    outer_fills(board)
    gnd_stitch(board, log=log)
    trim_stubs(board, log)
    silk.tidy(board, log)
    markings(board)
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())


CU = (pcbnew.F_Cu, pcbnew.In1_Cu, pcbnew.In2_Cu, pcbnew.B_Cu)


def cleanup(board, log=print):
    """Remove autorouter leftovers: dangling track stubs and vias connected on fewer than two layers."""
    removed_t = removed_v = 0
    for _ in range(6):
        pcbnew.ZONE_FILLER(board).Fill(board.Zones())
        board.BuildConnectivity()
        conn = board.GetConnectivity()
        tracks = [t for t in board.GetTracks() if not isinstance(t, pcbnew.PCB_VIA)]
        ends = {}
        for t in tracks:
            for p in (t.GetStart(), t.GetEnd()):
                ends.setdefault((t.GetNetCode(), p.x, p.y), set()).add(t.GetLayer())
        dead = [t for t in tracks if not t.IsLocked() and conn.TestTrackEndpointDangling(t, False)]
        zones = list(board.Zones())
        pads = [p for fp in board.GetFootprints() for p in fp.Pads()]
        for v in [t for t in board.GetTracks() if isinstance(t, pcbnew.PCB_VIA)]:
            if v.IsLocked():
                continue
            pos = v.GetPosition()
            layers = set(ends.get((v.GetNetCode(), pos.x, pos.y), set()))
            for z in zones:
                if z.GetNetCode() == v.GetNetCode():
                    for L in CU:
                        if z.IsOnLayer(L) and z.HitTestFilledArea(L, pos):
                            layers.add(L)
            for p in pads:
                if p.GetNetCode() == v.GetNetCode() and p.HitTest(pos):
                    layers.update(L for L in CU if p.IsOnLayer(L))
            if len(layers) < 2:
                dead.append(v)
                removed_v += 1
        removed_t += sum(1 for t in dead if not isinstance(t, pcbnew.PCB_VIA))
        for t in dead:
            board.Delete(t)
        if not dead:
            break
    log(f"cleanup: removed {removed_t} dangling track segments, {removed_v} vias")


def trim_stubs(board, log=print):
    """Shorten the locked escape stubs to the point where the route leaves them (no dangling tips)."""
    from shapely.geometry import LineString, Point
    tracks = list(board.GetTracks())
    n_trim = n_del = 0
    for t in tracks:
        if not t.IsLocked() or isinstance(t, pcbnew.PCB_VIA) or abs(pcbnew.ToMM(t.GetWidth()) - 0.2) > 1e-3:
            continue
        a, b = copper.from_abs(t.GetStart()), copper.from_abs(t.GetEnd())
        line = LineString([a, b])
        if line.length < 0.3:
            continue
        # attachment points of other copper of the same net along the stub
        best = None
        for u in tracks:
            if u is t or u.GetNetCode() != t.GetNetCode():
                continue
            if isinstance(u, pcbnew.PCB_VIA):
                pts = [copper.from_abs(u.GetPosition())]
                if u.GetLayerSet().Contains(t.GetLayer()) is False:
                    continue
            else:
                if u.GetLayer() != t.GetLayer():
                    continue
                pts = [copper.from_abs(u.GetStart()), copper.from_abs(u.GetEnd())]
            for p in pts:
                if line.distance(Point(p)) <= pcbnew.ToMM(t.GetWidth()) / 2 + 0.01:
                    d = line.project(Point(p))
                    best = d if best is None else max(best, d)
        if best is None:
            continue
        if best < line.length - 0.02:
            q = line.interpolate(best)
            t.SetEnd(copper.to_abs(q.x, q.y))
            n_trim += 1
    log(f"escape stubs trimmed: {n_trim}")
