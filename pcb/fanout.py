"""Plane fan-out: give each SMD pad of a plane net a short trace and a via into its plane
(GND / GND_USB / VFORCE island on In1, +3V3 / +5V / VIN_PROT / VPRE / VSENSE on In2).
Freerouting 2.1 does not do this reliably in batch mode, so it is done here before autorouting."""
import math

import pcbnew
from shapely.geometry import Point, LineString, box
from shapely.strtree import STRtree
from shapely.ops import unary_union, nearest_points
from shapely.prepared import prep

import copper
import place
import power

VIA_R = 0.3
CLR = 0.2

# net -> plane region (shapely) for fan-out
PLANES = {
    "GND": power.S["gnd_i1"],
    "GND_USB": power.S["usb_i1"],
    "VFORCE": power.S["island_i1"],
    "+3V3": power.S["p3v3_i2"],
    "+5V": power.S["p5v_i2"],
    "VIN_PROT": power.S["vin_prot_i2"],
    "VPRE": power.S["vpre_i2"],
    "VSENSE": power.S["vsense_i2"],
}


class Obs:
    """Copper obstacles per layer with nets."""

    def __init__(self):
        self.items = {"F": [], "B": []}
        self.tree = {}

    def add(self, layer, net, geom):
        self.items[layer].append((net, geom))
        self.tree.pop(layer, None)

    def hits(self, layer, net, geom):
        if layer not in self.tree:
            self.tree[layer] = STRtree([g for _, g in self.items[layer]])
        for i in self.tree[layer].query(geom):
            n, g = self.items[layer][i]
            if n != net and g.intersects(geom):
                return True
        return False


ESCAPE_ICS = {"U601": 0.7, "U201": 0.6, "U304": 0.6}     # ref -> stub length beyond the pad tip (mm)


def escapes(board, final, log=print):
    """Short straight stubs from the signal pins of the fine-pitch ICs, centred on the pad axis. They make
    the tight first step out of the pin row exact, which the grid router cannot guarantee."""
    fz = {}
    for (name, layer), g in final.items():
        if layer == "F.Cu":
            net = [z[1] for z in power.ZONES if z[0] == name and z[2] == layer][0]
            fz.setdefault(net, []).append(g)
    n = 0
    for ref, L in ESCAPE_ICS.items():
        fp = board.FindFootprintByReference(ref)
        fc = copper.from_abs(fp.GetPosition())
        for p in fp.Pads():
            net = p.GetNetname()
            if not net or net.startswith("unconnected") or net in PLANES:
                continue
            g = copper.pad_geom(p)
            if net in fz and unary_union(fz[net]).intersects(g):
                continue
            x0, y0, x1, y1 = g.bounds
            if (x1 - x0) > 2 and (y1 - y0) > 2:
                continue
            c = copper.from_abs(p.GetPosition())
            if (x1 - x0) >= (y1 - y0):            # pad axis along x
                s = 1 if c[0] > fc[0] else -1
                a = (c[0], c[1]); b = (c[0] + s * ((x1 - x0) / 2 + L), c[1])
            else:
                s = 1 if c[1] > fc[1] else -1
                a = (c[0], c[1]); b = (c[0], c[1] + s * ((y1 - y0) / 2 + L))
            copper.add_track(board, net, pcbnew.F_Cu, 0.2, a, b, locked=True)
            n += 1
    log(f"escape stubs: {n}")


def run(board, final, log=print):
    obs = Obs()
    pads = []
    for fp in board.GetFootprints():
        for p in fp.Pads():
            g = copper.pad_geom(p)
            n = p.GetNetname()
            tht = p.GetAttribute() in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH)
            if p.IsOnLayer(pcbnew.F_Cu) or tht:
                obs.add("F", n, g)
            if p.IsOnLayer(pcbnew.B_Cu) or tht:
                obs.add("B", n, g)
            pads.append((fp, p, g))
    for (name, layer), g in final.items():
        net = [z[1] for z in power.ZONES if z[0] == name and z[2] == layer][0]
        if layer in ("F.Cu", "B.Cu"):
            obs.add(layer[0], net, g)
    vias = []
    for t in board.GetTracks():
        if isinstance(t, pcbnew.PCB_VIA):
            c = Point(copper.from_abs(t.GetPosition()))
            vias.append((t.GetNetname(), c))
            obs.add("F", t.GetNetname(), c.buffer(VIA_R)); obs.add("B", t.GetNetname(), c.buffer(VIA_R))
        else:
            a, b = copper.from_abs(t.GetStart()), copper.from_abs(t.GetEnd())
            g = LineString([a, b]).buffer(pcbnew.ToMM(t.GetWidth()) / 2)
            obs.add("F" if t.GetLayer() == pcbnew.F_Cu else "B", t.GetNetname(), g)
    allpads = [g for _, _, g in pads]
    padtree = STRtree(allpads)
    fzone = {}
    for (name, layer), g in final.items():
        if layer == "F.Cu":
            net = [z[1] for z in power.ZONES if z[0] == name and z[2] == layer][0]
            fzone.setdefault(net, []).append(g)
    fzone = {n: prep(unary_union(v)) for n, v in fzone.items()}
    plane = {n: prep(g.buffer(-0.5)) for n, g in PLANES.items()}
    edge = prep(box(0, 0, place.BW, place.BH).buffer(-0.6))
    done = fail = 0
    failed = []
    # QFN ground pins: a short stub into the exposed pad (which reaches In1 through its thermal vias)
    # keeps vias out of the pin field
    ep_done = set()
    for fp in board.GetFootprints():
        eps = [p for p in fp.Pads() if p.GetNetname() == "GND" and p.GetAttribute() == pcbnew.PAD_ATTRIB_SMD
               and copper.pad_geom(p).area > 4.0]
        if not eps:
            continue
        ep = copper.pad_geom(eps[0]).buffer(-0.25)
        for p in fp.Pads():
            g = copper.pad_geom(p)
            if p.GetNetname() != "GND" or g.area > 4.0 or not p.IsOnLayer(pcbnew.F_Cu):
                continue
            c = Point(copper.from_abs(p.GetPosition()))
            q = nearest_points(c, ep)[1]
            if c.distance(q) > 1.6:
                continue
            w = 0.2 if min(g.bounds[2] - g.bounds[0], g.bounds[3] - g.bounds[1]) < 0.4 else 0.25
            copper.add_track(board, "GND", pcbnew.F_Cu, w, (c.x, c.y), (q.x, q.y), locked=True)
            obs.add("F", "GND", LineString([(c.x, c.y), (q.x, q.y)]).buffer(w / 2))
            ep_done.add((fp.GetReference(), p.GetNumber()))
    for fp, p, g in pads:
        n = p.GetNetname()
        if n not in PLANES or not p.IsOnLayer(pcbnew.F_Cu) or p.GetAttribute() != pcbnew.PAD_ATTRIB_SMD:
            continue
        if (fp.GetReference(), p.GetNumber()) in ep_done:
            continue
        if n in fzone and fzone[n].intersects(g):
            continue
        c = Point(copper.from_abs(p.GetPosition()))
        if not plane[n].contains(c):
            continue
        x0, y0, x1, y1 = g.bounds
        hx, hy = (x1 - x0) / 2, (y1 - y0) / 2
        w = 0.3 if min(hx, hy) >= 0.2 else 0.2
        fc = Point(copper.from_abs(fp.GetPosition()))
        # outward direction first
        dx, dy = c.x - fc.x, c.y - fc.y
        dirs = []
        for ang in range(0, 360, 30):
            ux, uy = math.cos(math.radians(ang)), math.sin(math.radians(ang))
            dirs.append((-(ux * dx + uy * dy), ux, uy))
        # pins of fine-pitch multi-pin packages fan out inward (under the body), so the ring
        # around the pins stays free for signal escapes; everything else fans out outward
        if len(list(fp.Pads())) >= 16 and not fp.GetReference().startswith("J"):
            dirs = [(-a, ux, uy) for a, ux, uy in dirs]
        dirs.sort()
        best = None
        for _, ux, uy in dirs:
            # distance from centre to pad edge along (ux,uy)
            e = min(hx / abs(ux) if abs(ux) > 1e-6 else 1e9, hy / abs(uy) if abs(uy) > 1e-6 else 1e9)
            for gap in (0.12, 0.3, 0.55, 0.9, 1.4):
                d = e + VIA_R + gap
                v = Point(c.x + ux * d, c.y + uy * d)
                if not plane[n].contains(v) or not edge.contains(v):
                    continue
                disk = v.buffer(VIA_R + CLR)
                if obs.hits("F", n, disk) or obs.hits("B", n, disk):
                    continue
                # no via-in-pad, including pads of the same net
                vd = v.buffer(VIA_R + 0.05)
                if any(allpads[i].intersects(vd) for i in padtree.query(vd)):
                    continue
                ok = True
                for vn, vc in vias:
                    dd = v.distance(vc)
                    if dd < (0.6 if vn == n else 0.75):
                        ok = False
                        break
                if not ok:
                    continue
                tr = LineString([(c.x, c.y), (v.x, v.y)]).buffer(w / 2 + CLR)
                if obs.hits("F", n, tr):
                    continue
                best = (v, d)
                break
            if best:
                break
        if not best:
            fail += 1
            failed.append(f"{fp.GetReference()}.{p.GetNumber()}")
            continue
        v, _ = best
        copper.add_track(board, n, pcbnew.F_Cu, w, (c.x, c.y), (v.x, v.y), locked=True)
        copper.add_via(board, n, v.x, v.y, locked=True)
        vias.append((n, v))
        obs.add("F", n, v.buffer(VIA_R)); obs.add("B", n, v.buffer(VIA_R))
        obs.add("F", n, LineString([(c.x, c.y), (v.x, v.y)]).buffer(w / 2))
        done += 1
    log(f"fan-out: {done} pads, {fail} left to the router: {' '.join(failed[:40])}")
    return done, failed
