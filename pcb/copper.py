"""Apply the power copper plan (power.py) to the placed board: rules, net classes, zones, Kelvin traces,
stitching vias. Board coordinates are mm from the board's top-left corner."""
import json
import math
import os

import pcbnew
from shapely.geometry import Point, LineString, Polygon, MultiPolygon, box
from shapely.ops import unary_union, nearest_points
from shapely.prepared import prep

import place
import power

HERE = os.path.dirname(os.path.abspath(__file__))
PRO = os.path.join(HERE, "..", "kicad", "e-psu.kicad_pro")
LAYER = {"F.Cu": pcbnew.F_Cu, "In1.Cu": pcbnew.In1_Cu, "In2.Cu": pcbnew.In2_Cu, "B.Cu": pcbnew.B_Cu}
EDGE_CLR = 0.5

# ---- rules and net classes (JLCPCB 4-layer standard process) -------------------------------------------
NETCLASSES = {
    "Default": dict(track=0.2, clr=0.15, via=0.6, drill=0.3),
    "Power": dict(track=0.3, clr=0.15, via=0.6, drill=0.3),
    "HighCurrent": dict(track=0.3, clr=0.2, via=0.6, drill=0.3),
    "USB": dict(track=0.2, clr=0.15, via=0.6, drill=0.3),
}
HIGH = [power.VIN_RAW, "VIN_PT", power.PT_SW, power.SW_IN, power.SRC_COM, power.OUT_P, power.Q101_D, "VIN_PROT",
        "VPRE", power.SW_BUCK, power.D304K, "VFORCE", power.N_MID, "VSENSE"]
POWER = ["GND", "GND_USB", "+5V", "+3V3", "+3.3VA", "+5VA", "VOP", "VNEG",
         "/Current measurement & auto-ranging/ISO_5V", "/Current measurement & auto-ranging/ISO_3V3",
         "Net-(U701-VBUS)", "Net-(U702-VBUS1)", "Net-(U201-VCC)", "Net-(D103-K)", "V_GATE"]
USB = ["/Isolated USB/USB_C_DP", "/Isolated USB/USB_C_DM", "Net-(U702-UD+)", "Net-(U702-UD-)",
       "Net-(U702-DD+)", "Net-(U702-DD-)", "USB_DP", "USB_DM"]


def nm(v):
    return pcbnew.FromMM(v)


def to_abs(x, y):
    return pcbnew.VECTOR2I(nm(place.BX0 + x), nm(place.BY0 + y))


def from_abs(p):
    return pcbnew.ToMM(p.x) - place.BX0, pcbnew.ToMM(p.y) - place.BY0


def setup_rules(board):
    ds = board.GetDesignSettings()
    ds.m_MinClearance = nm(0.15)
    ds.m_TrackMinWidth = nm(0.15)
    ds.m_ViasMinSize = nm(0.5)
    ds.m_ViasMinAnnularWidth = nm(0.13)
    ds.m_MinThroughDrill = nm(0.3)
    ds.m_HoleToHoleMin = nm(0.25)
    ds.m_HoleClearance = nm(0.25)
    ds.m_CopperEdgeClearance = nm(0.4)
    ds.m_SolderMaskMinWidth = nm(0)
    ds.m_MinSilkTextHeight = nm(0.8)
    board.SetLayerType(pcbnew.In1_Cu, pcbnew.LT_POWER)
    board.SetLayerType(pcbnew.In2_Cu, pcbnew.LT_POWER)
    ns = ds.m_NetSettings
    classes = {}
    for name, c in NETCLASSES.items():
        nc = ns.m_DefaultNetClass if name == "Default" else pcbnew.NETCLASS(name)
        nc.SetTrackWidth(nm(c["track"])); nc.SetClearance(nm(c["clr"]))
        nc.SetViaDiameter(nm(c["via"])); nc.SetViaDrill(nm(c["drill"]))
        if name != "Default":
            ns.m_NetClasses[name] = nc
        classes[name] = nc
    assign = {}
    for cls, nets in (("HighCurrent", HIGH), ("Power", POWER), ("USB", USB)):
        for n in nets:
            ni = board.FindNet(n)
            if ni is None:
                raise KeyError(n)
            ni.SetNetClass(classes[cls])
            assign[n] = cls
    for ni in board.GetNetsByName().values():
        if ni.GetNetname() and ni.GetNetname() not in assign:
            ni.SetNetClass(classes["Default"])
    write_project(assign)
    return classes


def assignments():
    a = {}
    for cls, nets in (("HighCurrent", HIGH), ("Power", POWER), ("USB", USB)):
        for n in nets:
            a[n] = cls
    return a


def write_project(assign=None, pro=None):
    """KiCad overwrites the project's net-class patterns whenever a board is saved from Python,
    so call this again after every SaveBoard."""
    assign = assign or assignments()
    pro = pro or PRO
    d = json.load(open(pro))
    base = d["net_settings"]["classes"][0]
    cl = []
    for name, c in NETCLASSES.items():
        e = dict(base)
        e.update(name=name, clearance=c["clr"], track_width=c["track"], via_diameter=c["via"], via_drill=c["drill"])
        cl.append(e)
    d["net_settings"]["classes"] = cl
    d["net_settings"]["netclass_patterns"] = [{"netclass": c, "pattern": n} for n, c in sorted(assign.items())]
    r = d["board"]["design_settings"].setdefault("rules", {})
    r.update(min_clearance=0.15, min_track_width=0.15, min_via_diameter=0.5, min_via_annular_width=0.13,
             min_through_hole_diameter=0.3, min_hole_to_hole=0.25, min_hole_clearance=0.25,
             min_copper_edge_clearance=0.4, solder_mask_min_width=0.0, min_silk_clearance=0.0,
             min_text_height=0.8, allow_blind_buried_vias=False, allow_microvias=False)
    sev = d["board"]["design_settings"].setdefault("rule_severities", {})
    sev.update(lib_footprint_issues="ignore", lib_footprint_mismatch="ignore")
    json.dump(d, open(pro, "w"), indent=2)


# ---- geometry helpers ---------------------------------------------------------------------------------------
def pad_geom(p, infl=0.0):
    """Pad copper as a shapely shape (board mm), inflated."""
    bb = p.GetBoundingBox()
    x0, y0 = from_abs(pcbnew.VECTOR2I(bb.GetLeft(), bb.GetTop()))
    x1, y1 = from_abs(pcbnew.VECTOR2I(bb.GetRight(), bb.GetBottom()))
    shape = p.GetShape()
    if shape == pcbnew.PAD_SHAPE_CIRCLE:
        c = from_abs(p.GetPosition())
        return Point(c).buffer((x1 - x0) / 2 + infl, 16)
    if shape == pcbnew.PAD_SHAPE_OVAL:
        w, h = x1 - x0, y1 - y0
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        if abs(w - h) < 1e-6:
            return Point(cx, cy).buffer(w / 2 + infl, 16)
        if w > h:
            seg, r = LineString([(x0 + h / 2, cy), (x1 - h / 2, cy)]), h / 2
        else:
            seg, r = LineString([(cx, y0 + w / 2), (cx, y1 - w / 2)]), w / 2
        return seg.buffer(r + infl, 16)
    g = box(x0, y0, x1, y1)
    if shape == pcbnew.PAD_SHAPE_ROUNDRECT:
        r = min(pcbnew.ToMM(p.GetRoundRectCornerRadius()), (x1 - x0) / 2 - 1e-3, (y1 - y0) / 2 - 1e-3)
        if r > 0.01:
            g = g.buffer(-r, join_style=2).buffer(r, 8)
    return g.buffer(infl, join_style=2) if infl else g


def hole_geom(p, infl=0.0):
    c = from_abs(p.GetPosition())
    d = pcbnew.ToMM(max(p.GetDrillSize().x, p.GetDrillSize().y))
    return Point(c).buffer(d / 2 + infl, 16)


def pads_on(board, layer):
    out = []
    for fp in board.GetFootprints():
        for p in fp.Pads():
            if p.IsOnLayer(layer) or p.GetAttribute() in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH):
                out.append(p)
    return out


def polys(g):
    if g.is_empty:
        return []
    if isinstance(g, Polygon):
        return [g]
    return [q for q in getattr(g, "geoms", []) if isinstance(q, Polygon)]


def channel_holes(poly, width):
    """Open every interior hole to the outside with a straight channel."""
    for _ in range(50):
        if not poly.interiors:
            return poly
        h = Polygon(poly.interiors[0])
        c = h.representative_point()
        ext = LineString(poly.exterior.coords)
        q = nearest_points(c, ext)[1]
        dx, dy = q.x - c.x, q.y - c.y
        L = math.hypot(dx, dy) or 1.0
        far = Point(q.x + dx / L * 0.5, q.y + dy / L * 0.5)
        poly = poly.difference(LineString([c, far]).buffer(width / 2, cap_style=2))
        poly = max(polys(poly), key=lambda g: g.area) if not isinstance(poly, Polygon) else poly
    return poly


# ---- zones ------------------------------------------------------------------------------------------------
def make_zone(board, net, layer_name, geom, opts, prio):
    layer = LAYER[layer_name]
    zones = []
    for g in polys(geom):
        g = g.simplify(0.01)
        z = pcbnew.ZONE(board)
        z.SetLayer(layer)
        z.SetNetCode(board.FindNet(net).GetNetCode())
        z.SetAssignedPriority(prio)
        z.SetLocalClearance(nm(opts.get("clr", 0.3)))
        z.SetMinThickness(nm(0.25))
        z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
        if opts.get("connect") == "tht_thermal":
            z.SetPadConnection(pcbnew.ZONE_CONNECTION_THT_THERMAL)
            z.SetThermalReliefSpokeWidth(nm(opts.get("spoke", 0.8)))
            z.SetThermalReliefGap(nm(0.4))
        else:
            z.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
        ol = z.Outline()
        ol.NewOutline()
        for x, y in list(g.exterior.coords)[:-1]:
            a = to_abs(x, y)
            ol.Append(a.x, a.y)
        for ring in g.interiors:
            hi = ol.NewHole(0)
            for x, y in list(ring.coords)[:-1]:
                a = to_abs(x, y)
                ol.Append(a.x, a.y, 0, hi)
        board.Add(z)
        zones.append(z)
    return zones


def build_zones(board, log=print):
    done = {}      # layer -> list of (net, geom)
    final = {}     # (name, layer) -> geom
    kel = {}           # (net, layer) -> geometries
    ksegs, kvias = power.kelvin_segments()
    for net, w, layer, a, b in ksegs:
        kel.setdefault((net, layer), []).append(LineString([a, b]).buffer(w / 2, cap_style=2))
    for net, x, y in kvias:
        for layer in ("F.Cu", "B.Cu", "In1.Cu", "In2.Cu"):
            kel.setdefault((net, layer), []).append(Point(x, y).buffer(0.3))
    edge = box(0, 0, place.BW, place.BH).buffer(-EDGE_CLR, join_style=2)
    prio = 100
    for name, net, layer_name, shape, opts in power.ZONES:
        layer = LAYER[layer_name]
        clr = opts.get("clr", 0.3)
        inner = layer_name.startswith("In")   # plane layers: the fill clears other nets by itself
        g = shape.intersection(edge)
        cut = []
        own = []
        for p in ([] if inner else pads_on(board, layer)):
            same = p.GetNetname() == net
            if p.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH:
                cut.append(hole_geom(p, clr))
                continue
            if same:
                own.append(pad_geom(p))
                continue
            cut.append(pad_geom(p, clr))
        for n2, g2 in done.get(layer_name, []):
            if n2 != net:
                cut.append(g2.buffer(clr, join_style=2))
        for (n2, kl), gl in kel.items():
            if kl == layer_name and (not inner or n2 != net):
                for k in gl:
                    cut.append(k.buffer(0.2 if n2 == net else clr, join_style=2))
        if cut:
            g = g.difference(unary_union(cut))
        pieces = []
        ownu = unary_union(own) if own else None
        for q in polys(g):
            if not inner:
                q = channel_holes(q, 1.3)
            if q.area < 1.0:
                continue
            stitched = any(n == net and layer_name in ls for n, ls, _ in power.STITCH)
            if ownu is not None and q.intersects(ownu):
                pieces.append(q)
            elif q.area > 12 and (inner or stitched):
                pieces.append(q)
        if not pieces:
            log(f"zone {name}/{layer_name}: nothing left")
            continue
        geom = unary_union(pieces)
        done.setdefault(layer_name, []).append((net, geom))
        final[(name, layer_name)] = geom
        make_zone(board, net, layer_name, geom, opts, prio)
        prio -= 1
    return final


# ---- Kelvin traces -------------------------------------------------------------------------------------------
def add_track(board, net, layer, w, a, b, locked=True):
    t = pcbnew.PCB_TRACK(board)
    t.SetStart(to_abs(*a)); t.SetEnd(to_abs(*b))
    t.SetWidth(nm(w)); t.SetLayer(layer)
    t.SetNetCode(board.FindNet(net).GetNetCode())
    t.SetLocked(locked)
    board.Add(t)
    return t


def add_kelvin(board):
    segs, vias = power.kelvin_segments()
    for net, w, layer, a, b in segs:
        add_track(board, net, LAYER[layer], w, a, b)
    for net, x, y in vias:
        add_via(board, net, x, y)


def add_via(board, net, x, y, d=0.6, drill=0.3, locked=True):
    v = pcbnew.PCB_VIA(board)
    v.SetPosition(to_abs(x, y))
    v.SetWidth(nm(d)); v.SetDrill(nm(drill))
    v.SetViaType(pcbnew.VIATYPE_THROUGH)
    v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
    v.SetNetCode(board.FindNet(net).GetNetCode())
    v.SetLocked(locked)
    board.Add(v)
    return v


# ---- stitching ----------------------------------------------------------------------------------------------
def stitch(board, final, log=print, pitch=1.4):
    allpads = [(p.GetNetname(), pad_geom(p)) for fp in board.GetFootprints() for p in fp.Pads()]
    ksegs, kvias = power.kelvin_segments()
    kel = [LineString([a, b]).buffer(w / 2) for _, w, _, a, b in ksegs] + [Point(x, y).buffer(0.3) for _, x, y in kvias]
    vias = []
    zones_by_layer = {}
    for (name, layer), g in final.items():
        net = [z[1] for z in power.ZONES if z[0] == name and z[2] == layer][0]
        zones_by_layer.setdefault(layer, []).append((net, g))
    count = {}
    for net, layers, nmax in power.STITCH:
        own = {L: unary_union([g for n, g in zones_by_layer.get(L, []) if n == net]) for L in layers}
        own = {L: g for L, g in own.items() if not g.is_empty}
        if len(own) < 2:
            continue
        area = None
        for L, g in own.items():
            gi = g.buffer(-0.55)
            area = gi if area is None else area.intersection(gi)
        if area is None or area.is_empty:
            log(f"stitch {net}: no common area")
            continue
        # keep out of pads, Kelvin traces and other nets' F/B pours
        bad = [g.buffer(0.55) for n, g in allpads] + [k.buffer(0.6) for k in kel]
        for L in ("F.Cu", "B.Cu"):
            for n, g in zones_by_layer.get(L, []):
                if n != net:
                    bad.append(g.buffer(0.6))
        area = area.difference(unary_union(bad))
        pa = prep(area)
        x0, y0, x1, y1 = area.bounds if not area.is_empty else (0, 0, 0, 0)
        pts = []
        y = y0 + 0.2
        while y <= y1:
            x = x0 + 0.2
            while x <= x1:
                if pa.contains(Point(x, y)):
                    pts.append((x, y))
                x += pitch
            y += pitch
        # spread: pick evenly when there are more sites than wanted
        if len(pts) > nmax:
            step = len(pts) / nmax
            pts = [pts[int(i * step)] for i in range(nmax)]
        for x, y in pts:
            vias.append(add_via(board, net, x, y))
        count[net] = len(pts)
    log("stitching vias: " + ", ".join(f"{n.split('/')[-1]}={c}" for n, c in count.items()))
    return vias


def apply(board, log=print):
    setup_rules(board)
    add_kelvin(board)
    final = build_zones(board, log)
    stitch(board, final, log)
    return final
