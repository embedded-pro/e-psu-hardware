"""Octilinear grid router for KiCad 10 boards that meets the pcb-design-rules gates by construction.

    kicad10-python octoroute.py board.kicad_pcb [--nets regex] [--only-planes] [--rip]

- 0.1 mm grid on F.Cu and B.Cu; moves in 8 directions, turns of 45 degrees only, and a minimum straight
  run between turns: no any-angle segments, no 90-degree or acute corners, no jogs.
- Every track starts and ends on copper that is not a track: a pad, a pour (zone fill), or a via into
  the net's inner-layer plane. Tracks never branch off other tracks: no tees or Y-junctions.
- Obstacles: other nets' pads, tracks, vias and zone fills, inflated by clearance + half the track width;
  board edge; keep-outs. Vias need room on both outer layers and stay out of other nets' inner corridors.
"""
import heapq
import math
import re
import sys
from collections import defaultdict

import numpy as np
import shapely
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union

from kc import pcbnew

G = 0.1                         # grid pitch, mm
K = 3                           # minimum straight run (cells) before the next turn
TURN = 0.6                      # cost of a 45-degree turn, mm
VIA_COST = 2.5                  # cost of a via, mm
WRONG_WAY = 1.25                # cost factor against the layer's preferred direction
DIAG = 1.12                     # cost factor for 45-degree runs (keeps them to short transitions)
HW = 1.3                        # heuristic weight (weighted A*: much faster, paths within a few % of optimal)
VIA_D, VIA_DRILL = 0.6, 0.3
EDGE = 0.5
LAYERS = ("F.Cu", "B.Cu")
LID = {"F.Cu": pcbnew.F_Cu, "B.Cu": pcbnew.B_Cu, "In1.Cu": pcbnew.In1_Cu, "In2.Cu": pcbnew.In2_Cu}
DIRS = [(1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1)]
PREF = {0: (0, 4), 1: (2, 6)}   # preferred directions per layer index: F horizontal, B vertical
CLASS = {"Default": (0.2, 0.15), "Power": (0.3, 0.15), "HighCurrent": (0.3, 0.2), "USB": (0.2, 0.15)}
PLANES = {"GND": "In1.Cu", "GND_USB": "In1.Cu", "+3V3": "In2.Cu"}
FREE, BLOCK = -1, -2


def mm(v):
    return pcbnew.ToMM(v)


class Router:
    def __init__(self, board):
        self.b = board
        bb = board.GetBoardEdgesBoundingBox()
        self.x0, self.y0 = mm(bb.GetLeft()), mm(bb.GetTop())
        self.W = int(round(mm(bb.GetWidth()) / G)) + 1
        self.H = int(round(mm(bb.GetHeight()) / G)) + 1
        self.bw, self.bh = mm(bb.GetWidth()), mm(bb.GetHeight())
        self.netid = {}
        self.netname = []
        self.netclass = {}
        for name, ni in board.GetNetsByName().items():
            name = str(name)
            if not name:
                continue
            self.netid[name] = len(self.netname)
            self.netname.append(name)
            nc = ni.GetNetClassName() if hasattr(ni, "GetNetClassName") else "Default"
            self.netclass[name] = nc if nc in CLASS else "Default"
        # owner grids per routing class width: classes share grids by (w, c)
        self.cls_key = {k: v for k, v in CLASS.items()}
        self.grids = {}          # (w, c) -> array [2, H, W] of owner ids
        self.via = None          # array [2, H, W] owner ids at via radius
        self.objs = []           # (layers, geometry, net, clearance, dyn)
        self.dyn_uuids = set()   # tracks/vias made by this router (rip-up candidates)
        self.locked_uuids = set()  # router-made but never ripped (Kelvin traces)
        self.xs = self.x0 + np.arange(self.W) * G
        self.ys = self.y0 + np.arange(self.H) * G

    # ---------------------------------------------------------------- geometry collection
    def pad_geom(self, p):
        sh = p.GetEffectivePolygon(pcbnew.F_Cu) if hasattr(p, "GetEffectivePolygon") else None
        poly = None
        try:
            spoly = pcbnew.SHAPE_POLY_SET()
            p.TransformShapeToPolygon(spoly, pcbnew.F_Cu if p.IsOnLayer(pcbnew.F_Cu) else pcbnew.B_Cu, 0,
                                      pcbnew.FromMM(0.005), pcbnew.ERROR_INSIDE)
            polys = []
            for i in range(spoly.OutlineCount()):
                ol = spoly.Outline(i)
                pts = [(mm(ol.CPoint(j).x), mm(ol.CPoint(j).y)) for j in range(ol.PointCount())]
                if len(pts) >= 3:
                    polys.append(Polygon(pts))
            poly = unary_union(polys)
        except Exception:
            bb = p.GetBoundingBox()
            poly = box(mm(bb.GetLeft()), mm(bb.GetTop()), mm(bb.GetRight()), mm(bb.GetBottom()))
        return poly

    def pad_layers(self, p):
        out = []
        for i, l in enumerate(LAYERS):
            if p.IsOnLayer(LID[l]):
                out.append(i)
        return out

    def collect(self):
        """All copper as (layers, geometry, net id, clearance)."""
        objs = []
        self.pads = []
        for fp in self.b.GetFootprints():
            for p in fp.Pads():
                if p.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH:
                    g = Point(mm(p.GetPosition().x), mm(p.GetPosition().y)).buffer(mm(p.GetDrillSizeX()) / 2)
                    objs.append(((0, 1), g, BLOCK, 0.3, False))
                    continue
                n = p.GetNetname()
                nid = self.netid.get(n, BLOCK) if n else BLOCK
                g = self.pad_geom(p)
                ls = self.pad_layers(p)
                c = CLASS[self.netclass.get(n, "Default")][1] if n else 0.15
                if p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH:
                    c = max(c, 0.3048)        # plated pad hole to copper (fab rule)
                objs.append((tuple(ls), g, nid, c, False))
                self.pads.append((p, fp.GetReference(), n, nid, g, ls))
        for t in self.b.GetTracks():
            n = t.GetNetname()
            nid = self.netid.get(n, BLOCK)
            c = CLASS[self.netclass.get(n, "Default")][1]
            dyn = t.m_Uuid.AsString() in self.dyn_uuids
            if t.GetClass() == "PCB_VIA":
                g = Point(mm(t.GetPosition().x), mm(t.GetPosition().y)).buffer(mm(t.GetWidth(pcbnew.F_Cu)) / 2)
                objs.append(((0, 1), g, nid, c, dyn))
            else:
                l = t.GetLayerName()
                if l not in LAYERS:
                    continue
                g = LineString([(mm(t.GetStart().x), mm(t.GetStart().y)), (mm(t.GetEnd().x), mm(t.GetEnd().y))]).buffer(mm(t.GetWidth()) / 2)
                objs.append(((LAYERS.index(l),), g, nid, c, dyn))
        self.fills = defaultdict(list)          # (net, layer name) -> filled geometry
        for z in self.b.Zones():
            if z.GetIsRuleArea():
                continue
            n = z.GetNetname()
            for lname in ("F.Cu", "B.Cu", "In1.Cu", "In2.Cu"):
                if not z.IsOnLayer(LID[lname]):
                    continue
                fp_ = z.GetFilledPolysList(LID[lname])
                polys = []
                for i in range(fp_.OutlineCount()):
                    ol = fp_.Outline(i)
                    pts = [(mm(ol.CPoint(j).x), mm(ol.CPoint(j).y)) for j in range(ol.PointCount())]
                    if len(pts) >= 3:
                        holes = []
                        for h in range(fp_.HoleCount(i)):
                            hl = fp_.Hole(i, h)
                            holes.append([(mm(hl.CPoint(j).x), mm(hl.CPoint(j).y)) for j in range(hl.PointCount())])
                        polys.append(Polygon(pts, holes).buffer(0))
                if not polys:
                    continue
                g = unary_union(polys)
                self.fills[(n, lname)].append(g)
                if lname in LAYERS:
                    objs.append(((LAYERS.index(lname),), g, self.netid.get(n, BLOCK), CLASS[self.netclass.get(n, "Default")][1], False))
        self.objs = objs

    # ---------------------------------------------------------------- rasterisation
    def raster(self, arr, layers, geom, nid, radius):
        g = geom.buffer(radius) if radius > 0 else geom
        x0, y0, x1, y1 = g.bounds
        i0 = max(0, int((x0 - self.x0) / G)); i1 = min(self.W - 1, int((x1 - self.x0) / G) + 1)
        j0 = max(0, int((y0 - self.y0) / G)); j1 = min(self.H - 1, int((y1 - self.y0) / G) + 1)
        if i1 < i0 or j1 < j0:
            return
        X, Y = np.meshgrid(self.xs[i0:i1 + 1], self.ys[j0:j1 + 1])
        inside = shapely.contains_xy(g, X, Y)
        if not inside.any():
            return
        for l in layers:
            sub = arr[l, j0:j1 + 1, i0:i1 + 1]
            cur = sub[inside]
            new = np.where(cur == FREE, nid, np.where(cur == nid, nid, BLOCK))
            sub[inside] = new

    def grid_for(self, net, fixed_only=False):
        w, c = CLASS[self.netclass.get(net, "Default")]
        key = (w, c, fixed_only)
        if key not in self.grids:
            arr = np.full((2, self.H, self.W), FREE, dtype=np.int32)
            self._edge(arr, w / 2 + EDGE)
            for ls, g, nid, oc, dyn in self.objs:
                if fixed_only and dyn:
                    continue
                self.raster(arr, ls, g, nid, max(c, oc) + w / 2 + 0.02)
            for ko in self.keepouts:
                self.raster(arr, (0, 1), ko, BLOCK, w / 2)
            self.grids[key] = arr
        return self.grids[key], w, c

    def _edge(self, arr, m):
        k = int(math.ceil(m / G))
        arr[:, :k, :] = BLOCK; arr[:, -k:, :] = BLOCK; arr[:, :, :k] = BLOCK; arr[:, :, -k:] = BLOCK

    def build(self, keepouts=()):
        self.keepouts = list(keepouts)
        self.collect()
        self.grids = {}
        via = np.full((2, self.H, self.W), FREE, dtype=np.int32)
        self._edge(via, VIA_D / 2 + EDGE)
        for ls, g, nid, oc, dyn in self.objs:
            self.raster(via, ls, g, nid, max(0.15, oc) + VIA_D / 2 + 0.02)
        # no via in or touching an SMD pad, whatever its net (solder would wick into an open via)
        for p, ref, n, nid, g, ls in self.pads:
            if p.GetAttribute() == pcbnew.PAD_ATTRIB_SMD:
                self.raster(via, (0, 1), g, BLOCK, VIA_D / 2 + 0.05)
        # vias stay out of other nets' inner-layer corridors (they would neck them)
        for (n, lname), gs in self.fills.items():
            if lname in ("In1.Cu", "In2.Cu") and n not in PLANES:
                for g in gs:
                    self.raster(via, (0, 1), g, self.netid.get(n, BLOCK), VIA_D / 2 + 0.25)
        for ko in self.keepouts:
            self.raster(via, (0, 1), ko, BLOCK, VIA_D / 2)
        self.via = via

    def add_copper(self, layers, geom, nid, c, dyn=True):
        self.objs.append((layers, geom, nid, c, dyn))
        for (w, cc, fixed_only), arr in self.grids.items():
            if fixed_only and dyn:
                continue
            self.raster(arr, layers, geom, nid, max(cc, c) + w / 2 + 0.02)
        self.raster(self.via, layers, geom, nid, max(0.15, c) + VIA_D / 2 + 0.02)

    # ---------------------------------------------------------------- cells of copper
    def cells_in(self, geom, shrink=0.0):
        g = geom.buffer(-shrink) if shrink else geom
        if g.is_empty:
            g = geom.representative_point().buffer(G * 0.8)
        x0, y0, x1, y1 = g.bounds
        i0 = max(0, int(math.floor((x0 - self.x0) / G))); i1 = min(self.W - 1, int(math.ceil((x1 - self.x0) / G)))
        j0 = max(0, int(math.floor((y0 - self.y0) / G))); j1 = min(self.H - 1, int(math.ceil((y1 - self.y0) / G)))
        X, Y = np.meshgrid(self.xs[i0:i1 + 1], self.ys[j0:j1 + 1])
        inside = shapely.contains_xy(g, X, Y)
        jj, ii = np.nonzero(inside)
        return list(zip((ii + i0).tolist(), (jj + j0).tolist()))

    # ---------------------------------------------------------------- search
    def route(self, net, starts, goals, plane_goal=None, margin=6.0, max_exp=400000, avoid=None, soft=False):
        """starts/goals: sets of (layer, i, j). plane_goal: array mask [H, W] where a via reaches the net's plane.
        Returns list of (layer, i, j) cells and the via cells, or None."""
        arr, w, c = self.grid_for(net)
        fixed = self.grid_for(net, fixed_only=True)[0] if soft else None
        nid = self.netid[net]
        if not goals and plane_goal is None:
            return None
        pts = [(i, j) for _, i, j in starts] + [(i, j) for _, i, j in goals]
        if plane_goal is not None and not goals:
            # plane: search near the start only
            i0 = min(p[0] for p in pts); i1 = max(p[0] for p in pts); j0 = min(p[1] for p in pts); j1 = max(p[1] for p in pts)
            m = int(4.0 / G)
        else:
            i0 = min(p[0] for p in pts); i1 = max(p[0] for p in pts); j0 = min(p[1] for p in pts); j1 = max(p[1] for p in pts)
            m = int(margin / G)
        bi0, bi1, bj0, bj1 = max(0, i0 - m), min(self.W - 1, i1 + m), max(0, j0 - m), min(self.H - 1, j1 + m)
        goalset = set(goals)
        gl = [(l, i, j) for l, i, j in goals]
        if gl:
            gx = np.array([g[1] for g in gl]); gy = np.array([g[2] for g in gl])
            gcx, gcy = float(gx.mean()), float(gy.mean())
            grad = max(float(np.max(np.hypot(gx - gcx, gy - gcy))), 0.0)
        else:
            gcx = gcy = None

        def h(i, j):
            if gcx is None:
                return 0.0
            dx, dy = abs(i - gcx), abs(j - gcy)
            d = (max(dx, dy) - min(dx, dy)) + 1.41421356 * min(dx, dy)
            return max(0.0, d - grad) * G

        def ok(l, i, j):
            if i < bi0 or i > bi1 or j < bj0 or j > bj1:
                return False
            if avoid is not None and avoid[l, j, i]:
                return False
            if soft:
                o = fixed[l, j, i]
                return o == FREE or o == nid
            o = arr[l, j, i]
            return o == FREE or o == nid

        def penalty(l, i, j):
            if not soft:
                return 0.0
            o = arr[l, j, i]
            return 0.0 if (o == FREE or o == nid) else 0.8

        def via_ok(i, j):
            o0, o1 = self.via[0, j, i], self.via[1, j, i]
            return (o0 == FREE or o0 == nid) and (o1 == FREE or o1 == nid)

        best = {}
        parent = {}
        heap = []
        cnt = 0
        for (l, i, j) in starts:
            if not ok(l, i, j):
                continue
            for d in range(8):
                s = (l, i, j, d, K)
                best[s] = 0.0
                parent[s] = None
                heapq.heappush(heap, (h(i, j), cnt, 0.0, s)); cnt += 1
        exp = 0
        while heap:
            f, _, gcost, s = heapq.heappop(heap)
            if best.get(s, 1e18) < gcost - 1e-9:
                continue
            l, i, j, d, r = s
            exp += 1
            if exp > max_exp:
                return None
            if (l, i, j) in goalset and parent[s] is not None:
                return self._unwind(parent, s, None)
            if plane_goal is not None and r >= K and plane_goal[j, i] and via_ok(i, j) and parent[s] is not None:
                return self._unwind(parent, s, (i, j))
            nbrs = []
            dx, dy = DIRS[d]
            cand = [(d, 0.0)]
            if r >= K:
                cand += [((d + 1) % 8, TURN), ((d - 1) % 8, TURN)]
            for nd, extra in cand:
                ddx, ddy = DIRS[nd]
                ni, nj = i + ddx, j + ddy
                if not ok(l, ni, nj):
                    continue
                if ddx and ddy and not (ok(l, i + ddx, j) and ok(l, i, j + ddy)):
                    continue            # no diagonal squeezing between two blocked cells
                step = (1.41421356 * DIAG if ddx and ddy else 1.0) * G
                if nd not in PREF[l] and not (ddx and ddy):
                    step *= WRONG_WAY
                nr = min(r + 1, K) if nd == d else 1
                nbrs.append(((l, ni, nj, nd, nr), step + extra + penalty(l, ni, nj)))
            if r >= K and via_ok(i, j):
                ol = 1 - l
                if ok(ol, i, j):
                    for nd in range(8):
                        nbrs.append(((ol, i, j, nd, K), VIA_COST))
            for ns, c_ in nbrs:
                ng = gcost + c_
                if ng < best.get(ns, 1e18) - 1e-9:
                    best[ns] = ng
                    parent[ns] = s
                    heapq.heappush(heap, (ng + HW * h(ns[1], ns[2]), cnt, ng, ns)); cnt += 1
        return None

    def _unwind(self, parent, s, plane_via):
        path = []
        while s is not None:
            path.append(s)
            s = parent[s]
        path.reverse()
        return path, plane_via

    # ---------------------------------------------------------------- commit
    def commit(self, net, path, plane_via):
        """Turn a cell path into tracks and vias on the board; returns (tracks, vias)."""
        arr, w, c = self.grid_for(net)
        nid = self.netid[net]
        ni = self.b.FindNet(net)
        cells = [(s[0], s[1], s[2]) for s in path]
        segs, vias = [], []
        run = [cells[0]]
        for a, b_ in zip(cells, cells[1:]):
            if b_[0] != a[0]:
                segs.append(run); run = [b_]; vias.append((a[1], a[2]))
                continue
            if len(run) >= 2:
                d0 = (run[-1][1] - run[-2][1], run[-1][2] - run[-2][2])
                d1 = (b_[1] - a[1], b_[2] - a[2])
                if d0 != d1:
                    segs.append(run); run = [a]
            run.append(b_)
        segs.append(run)
        made = []
        for run in segs:
            if len(run) < 2:
                continue
            l = run[0][0]
            p0 = (self.x0 + run[0][1] * G, self.y0 + run[0][2] * G)
            p1 = (self.x0 + run[-1][1] * G, self.y0 + run[-1][2] * G)
            t = pcbnew.PCB_TRACK(self.b)
            t.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM(p0[0]), pcbnew.FromMM(p0[1])))
            t.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(p1[0]), pcbnew.FromMM(p1[1])))
            t.SetWidth(pcbnew.FromMM(w)); t.SetLayer(LID[LAYERS[l]]); t.SetNet(ni)
            self.b.Add(t)
            made.append(t)
            self.dyn_uuids.add(t.m_Uuid.AsString())
            self.add_copper((l,), LineString([p0, p1]).buffer(w / 2), nid, c)
        if plane_via:
            vias.append(plane_via)
        for (i, j) in vias:
            x, y = self.x0 + i * G, self.y0 + j * G
            v = pcbnew.PCB_VIA(self.b)
            v.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y)))
            v.SetWidth(pcbnew.FromMM(VIA_D)); v.SetDrill(pcbnew.FromMM(VIA_DRILL)); v.SetNet(ni)
            v.SetViaType(pcbnew.VIATYPE_THROUGH)
            self.b.Add(v)
            made.append(v)
            self.dyn_uuids.add(v.m_Uuid.AsString())
            self.add_copper((0, 1), Point(x, y).buffer(VIA_D / 2), nid, c)
        return made, vias


# -------------------------------------------------------------------- connectivity driver
def islands(r, net):
    """Copper islands of a net: list of dicts with 'cells' {(l,i,j)} usable as start/goal, 'pads', 'plane'."""
    nid = r.netid[net]
    items = []      # (geometry per layer dict, cells, pad refs)
    for p, ref, n, pid, g, ls in r.pads:
        if n != net:
            continue
        tht = p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH
        items.append(dict(geo={l: g for l in (list(ls) + ([2, 3] if tht else []))}, pads=[f"{ref}.{p.GetNumber()}"],
                          tht=tht, plane=False))
    for (n, lname), gs in r.fills.items():
        if n != net:
            continue
        li = {"F.Cu": 0, "B.Cu": 1, "In1.Cu": 2, "In2.Cu": 3}[lname]
        for g in gs:
            for part in (g.geoms if g.geom_type == "MultiPolygon" else [g]):
                items.append(dict(geo={li: part}, pads=[], tht=False, plane=False))
    for t in r.b.GetTracks():
        if t.GetNetname() != net or t.GetClass() != "PCB_VIA":
            continue
        g = Point(mm(t.GetPosition().x), mm(t.GetPosition().y)).buffer(mm(t.GetWidth(pcbnew.F_Cu)) / 2)
        items.append(dict(geo={0: g, 1: g, 2: g, 3: g}, pads=[], tht=True, plane=False))
    # union items that touch on a shared layer; THT pads join the inner plane of their net
    parent = list(range(len(items)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    for a in range(len(items)):
        for b in range(a + 1, len(items)):
            for l, ga in items[a]["geo"].items():
                gb = items[b]["geo"].get(l)
                if gb is not None and ga.distance(gb) < 0.01:
                    parent[find(a)] = find(b)
                    break
    plane = PLANES.get(net)
    plane_geo = unary_union(r.fills.get((net, plane), [])) if plane else None
    if plane_geo is not None and plane_geo.geom_type == "MultiPolygon":
        plane_geo = max(plane_geo.geoms, key=lambda q: q.area)
    groups = defaultdict(list)
    for k in range(len(items)):
        groups[find(k)].append(items[k])
    out = []
    for grp in groups.values():
        on_plane = plane_geo is not None and not plane_geo.is_empty and any(
            it["tht"] and any(plane_geo.distance(g) < 0.01 for g in it["geo"].values()) for it in grp)
        out.append(dict(items=grp, pads=[p for it in grp for p in it["pads"]], plane=on_plane))
    # tracks already on the board join islands at their ends (handled by re-reading copper between runs)
    return out


def cells_of(r, island):
    cells = set()
    for it in island["items"]:
        for l, g in it["geo"].items():
            if l not in (0, 1) or it.get("tht") and not it["pads"]:
                continue                    # inner layers are reached by vias; never start on a via
            for i, j in r.cells_in(g, shrink=0.05):
                cells.add((l, i, j))
    return cells


def plane_mask(r, net):
    plane = PLANES.get(net)
    if not plane:
        return None
    gs = r.fills.get((net, plane), [])
    if not gs:
        return None
    g = unary_union(gs)
    if g.geom_type == "MultiPolygon":            # corridors can split a plane: use its main body only
        g = max(g.geoms, key=lambda q: q.area)
    g = g.buffer(-0.45)
    if g.is_empty:
        return None
    X, Y = np.meshgrid(r.xs, r.ys)
    return shapely.contains_xy(g, X, Y)


# Kelvin sense connections: sense pad -> shunt pad (routed first, to the inner half of the shunt pad,
# kept out of the net's own pour; a no-fill strip along the trace keeps the pour from merging into it)
KELVIN = [("U501.3", "R501.1", "R501.2"), ("U501.4", "R501.2", "R501.1"),
          ("U301.3", "R301.1", "R301.2"), ("U301.4", "R301.2", "R301.1"),
          ("R407.1", "R401.1", "R401.2"), ("R408.1", "R401.2", "R401.1"),
          ("R409.1", "R402.1", "R402.2"), ("R410.1", "R402.2", "R402.1")]


def find_pad(r, spec):
    ref, num = spec.split(".")
    for p, rr, n, nid, g, ls in r.pads:
        if rr == ref and p.GetNumber() == num:
            return p, n, g, ls
    raise KeyError(spec)


def kelvin(r):
    """Route the Kelvin pairs; returns the set of sense pads handled and the list of traces made."""
    done, strips = set(), []
    for sense, shunt, other in KELVIN:
        try:
            sp, net, sg, sls = find_pad(r, sense)
            hp, hnet, hg, hls = find_pad(r, shunt)
            op, _, og, _ = find_pad(r, other)
        except KeyError:
            continue
        assert net == hnet, (sense, shunt, net, hnet)
        c = hg.centroid; o = og.centroid
        vx, vy = o.x - c.x, o.y - c.y
        goals = set()
        for l in hls:
            for i, j in r.cells_in(hg, shrink=0.05):
                x, y = r.x0 + i * G, r.y0 + j * G
                if (x - c.x) * vx + (y - c.y) * vy > 0:          # inner half, towards the other pad
                    goals.add((l, i, j))
        starts = {(l, i, j) for l in sls for i, j in r.cells_in(sg, shrink=0.05)}
        # keep the trace out of its own net's pour except right at the shunt pad
        avoid = np.zeros((2, r.H, r.W), dtype=bool)
        for (n, lname), gs in r.fills.items():
            if n == net and lname in LAYERS:
                for g in gs:
                    g2 = g.buffer(0.25).difference(hg.buffer(0.7)).difference(sg.buffer(0.3))
                    if g2.is_empty:
                        continue
                    tmp = np.full((2, r.H, r.W), FREE, dtype=np.int32)
                    r.raster(tmp, (LAYERS.index(lname),), g2, 1, 0.0)
                    avoid |= tmp == 1
        res = r.route(net, starts, goals, margin=6.0, avoid=avoid)
        if res is None:
            res = r.route(net, starts, goals, margin=15.0, max_exp=1500000, avoid=avoid)
        if res is None:
            print("  KELVIN FAIL", sense, shunt)
            continue
        made, _ = r.commit(net, res[0], res[1])
        for t in made:
            r.dyn_uuids.discard(t.m_Uuid.AsString())
        done.add(sense)
        strips += [t for t in made if t.GetClass() != "PCB_VIA"]
    return done, strips


def add_fill_keepouts(board, tracks, shunt_pads=()):
    """No-fill rule areas along the Kelvin traces so the pours keep clear of them."""
    for t in tracks:
        a, b = t.GetStart(), t.GetEnd()
        g = LineString([(mm(a.x), mm(a.y)), (mm(b.x), mm(b.y))]).buffer(mm(t.GetWidth()) / 2 + 0.3, cap_style=2, join_style=2)
        z = pcbnew.ZONE(board)
        z.SetIsRuleArea(True)
        z.SetDoNotAllowZoneFills(True)
        z.SetDoNotAllowTracks(False); z.SetDoNotAllowVias(False); z.SetDoNotAllowPads(False)
        z.SetDoNotAllowFootprints(False)
        z.SetLayer(t.GetLayer())
        ol = z.Outline(); ol.NewOutline()
        for x, y in list(g.exterior.coords)[:-1]:
            ol.Append(pcbnew.FromMM(x), pcbnew.FromMM(y))
        board.Add(z)


_BODY = {}


def under_body(r, island):
    """Mask of the area under the body of the IC an island's single pad belongs to (minus its pads), or None."""
    if len(island["pads"]) != 1 or not island["pads"][0].startswith("U"):
        return None
    ref = island["pads"][0].split(".")[0]
    if ref in _BODY:
        return _BODY[ref]
    fp = r.b.FindFootprintByReference(ref)
    cy = fp.GetCourtyard(pcbnew.F_CrtYd)
    if not cy.OutlineCount():
        _BODY[ref] = None
        return None
    bb = cy.BBox()
    body = box(mm(bb.GetLeft()), mm(bb.GetTop()), mm(bb.GetRight()), mm(bb.GetBottom())).buffer(-0.3)
    pads = unary_union([g for p, rr, n, nid, g, ls in r.pads if rr == ref]).buffer(VIA_D / 2 + 0.2)
    body = body.difference(pads)
    if body.is_empty or body.area < 1.0:
        _BODY[ref] = None
        return None
    X, Y = np.meshgrid(r.xs, r.ys)
    _BODY[ref] = shapely.contains_xy(body, X, Y)
    return _BODY[ref]


def island_geom(isl):
    return unary_union([g for it in isl["items"] for g in it["geo"].values()])


def plan(r, net_re, skip_re, skip_pads=()):
    jobs = []
    for net in sorted(r.netname):
        if not re.search(net_re, net) or re.search(skip_re, net):
            continue
        isl = islands(r, net)
        # Kelvin sense pads are already connected to their shunt
        isl = [k for k in isl if not (len(k["items"]) == 1 and set(k["pads"]) <= set(skip_pads) and k["pads"])]
        if not isl:
            continue
        if net in PLANES:
            for k in isl:
                if not k["plane"] and k["pads"]:      # fill fragments without pads need nothing
                    jobs.append((0.0, "plane", net, k, None))
            continue
        if len(isl) < 2:
            continue
        geos = [island_geom(k) for k in isl]
        inside, n = {0}, len(isl)
        while len(inside) < n:
            best = None
            for a in inside:
                for b in range(n):
                    if b in inside:
                        continue
                    d = geos[a].distance(geos[b])
                    if best is None or d < best[0]:
                        best = (d, a, b)
            jobs.append((best[0], "pair", net, isl[best[1]], isl[best[2]]))
            inside.add(best[2])
    return jobs


def run(path, out, net_re=".*", skip_re="^$", keepouts=(), first=()):
    board = pcbnew.LoadBoard(path)
    r = Router(board)
    r.build(keepouts)
    kdone, ktracks = kelvin(r) if net_re == ".*" else (set(), [])
    print("kelvin", len(kdone), "of", len(KELVIN), flush=True)
    jobs = plan(r, net_re, skip_re, kdone)
    # plane fan-out first (short stubs next to the pads), then signal connections, shortest first
    # nets that failed in an earlier run go first; then plane fan-out; then the rest, shortest first
    jobs.sort(key=lambda j: (j[2] not in first, j[1] != "plane", j[0]))
    print("jobs", len(jobs), "planes", sum(j[1] == "plane" for j in jobs), flush=True)
    masks = {}
    made = {}           # job index -> board items
    failed = []

    def attempt(k, soft=False):
        d, kind, net, a, b = jobs[k]
        starts = cells_of(r, a)
        if not starts:
            return None
        if kind == "plane":
            if net not in masks or masks[net] is None:
                masks[net] = plane_mask(r, net)
            res = None
            if masks[net] is not None:
                # IC pins: try a via under the package body first, out of the signal escape paths
                body = under_body(r, a)
                if body is not None:
                    res = r.route(net, starts, set(), plane_goal=masks[net] & body, soft=soft, max_exp=60000)
                if res is None:
                    res = r.route(net, starts, set(), plane_goal=masks[net], soft=soft)
            if res is None:
                # fall back to the nearest pad of the net that already reaches the plane
                ga = island_geom(a)
                cand = [k2 for k2 in islands(r, net) if k2["plane"] and k2["pads"] and not set(k2["pads"]) & set(a["pads"])]
                cand.sort(key=lambda k2: island_geom(k2).distance(ga))
                for k2 in cand[:3]:
                    goals = cells_of(r, k2)
                    res = r.route(net, starts, goals, margin=8.0, soft=soft)
                    if res is not None:
                        break
            return res
        goals = cells_of(r, b)
        if not goals and not any(l in (2, 3) for it in b["items"] for l in it["geo"]):
            return None
        inner = [g for it in b["items"] for l, g in it["geo"].items() if l in (2, 3) and not it["tht"]]
        pg = None
        if inner:
            m = unary_union(inner).buffer(-0.45)
            if not m.is_empty:
                X, Y = np.meshgrid(r.xs, r.ys)
                pg = shapely.contains_xy(m, X, Y)
        res = r.route(net, starts, goals, plane_goal=pg, margin=6.0, soft=soft)
        if res is None:
            res = r.route(net, starts, goals, plane_goal=pg, margin=20.0, max_exp=1500000, soft=soft)
        return res

    for k in range(len(jobs)):
        res = attempt(k)
        if res is None:
            failed.append(k)
            continue
        made[k] = r.commit(jobs[k][2], res[0], res[1])[0]
        if k % 50 == 0:
            print(k, "/", len(jobs), "failed", len(failed), flush=True)
    print("first pass failed", len(failed), flush=True)

    # rip-up and reroute: search through the router's own tracks at a cost, rip the connections in the way,
    # route the failed one, then route the ripped ones again
    owner_of = {}
    for k, items in made.items():
        for it in items:
            owner_of[it.m_Uuid.AsString()] = k
    ripcount = defaultdict(int)
    for it_ in range(4):
        if not failed:
            break
        nxt = []
        for k in failed:
            res = attempt(k, soft=True)
            if res is None:
                nxt.append(k)
                continue
            net = jobs[k][2]
            pts = [(r.x0 + s_[1] * G, r.y0 + s_[2] * G) for s_ in res[0]]
            line = LineString(pts) if len(pts) > 1 else Point(pts[0])
            zone = line.buffer(0.7)
            victims = set()
            for t in list(r.b.GetTracks()):
                u = t.m_Uuid.AsString()
                if u not in r.dyn_uuids or t.GetNetname() == net:
                    continue
                if t.GetClass() == "PCB_VIA":
                    g = Point(mm(t.GetPosition().x), mm(t.GetPosition().y))
                else:
                    g = LineString([(mm(t.GetStart().x), mm(t.GetStart().y)), (mm(t.GetEnd().x), mm(t.GetEnd().y))])
                if g.distance(line) < 0.7 and u in owner_of:
                    victims.add(owner_of[u])
            victims = {v for v in victims if ripcount[v] < 3}
            for v in victims:
                ripcount[v] += 1
                for itm in made.pop(v, []):
                    r.dyn_uuids.discard(itm.m_Uuid.AsString())
                    r.b.Remove(itm)
            r.build(r.keepouts)
            masks.clear()
            res = attempt(k)
            if res is None:
                nxt.append(k)
            else:
                made[k] = r.commit(net, res[0], res[1])[0]
                for itm in made[k]:
                    owner_of[itm.m_Uuid.AsString()] = k
            for v in sorted(victims, key=lambda v: jobs[v][0]):
                res = attempt(v)
                if res is None:
                    nxt.append(v)
                else:
                    made[v] = r.commit(jobs[v][2], res[0], res[1])[0]
                    for itm in made[v]:
                        owner_of[itm.m_Uuid.AsString()] = v
        failed = nxt
        print("rip-up round", it_ + 1, "failed", len(failed), flush=True)
    failed = [(jobs[k][2], jobs[k][3]["pads"], jobs[k][4]["pads"] if jobs[k][4] else "plane") for k in failed]
    add_fill_keepouts(board, ktracks)
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    pcbnew.SaveBoard(out or path, board)
    print("done; failed", len(failed))
    for f in failed:
        print("  FAIL", f)
    return failed


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("board")
    ap.add_argument("--nets", default=".*")
    ap.add_argument("--skip", default="^$")
    ap.add_argument("--out")
    ap.add_argument("--first", default="", help="comma-separated nets to route before everything else")
    a = ap.parse_args()
    run(a.board, a.out, a.nets, a.skip, first=set(n for n in a.first.split(",") if n))
