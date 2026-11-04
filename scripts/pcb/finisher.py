"""Grid maze router with rip-up that completes the connections Freerouting leaves open.

Two routing layers (F.Cu, B.Cu) on a 0.05 mm grid, 8-direction moves, through vias. Pads, pours, locked
items and plane-net fan-outs are hard obstacles; other autorouted traces are soft: a path may cross them at
a cost, and the traces it crosses are ripped up and re-queued (negotiated congestion with a history cost).
The open connections come from KiCad's own DRC report, so the router works on what KiCad considers open."""
import heapq
import math
import re

import numpy as np
import pcbnew
import shapely
from scipy import ndimage
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union

import copper
import fanout
import place

G = 0.05
N = int(round(place.BW / G))
LAYERS = (pcbnew.F_Cu, pcbnew.B_Cu)
VIA_D, VIA_DRILL = 0.6, 0.3
VIA_COST = 25.0
SOFT_COST = 15.0
BAND_COST = 3.0
H_WEIGHT = 1.15
CLASS = {"Default": (0.2, 0.15), "Power": (0.3, 0.15), "HighCurrent": (0.3, 0.2), "USB": (0.2, 0.15)}
HARD_NETS = set(fanout.PLANES)          # never rip the plane fan-outs
HIST = None
LAST = {}
USE_LANES = False
HC = None


def disk(r_cells):
    r = int(math.ceil(r_cells))
    y, x = np.ogrid[-r:r + 1, -r:r + 1]
    return (x * x + y * y) <= r_cells * r_cells


def raster(geom, arr, val, grow=G * 0.75):
    g = geom.buffer(grow) if grow else geom
    if g.is_empty:
        return
    x0, y0, x1, y1 = g.bounds
    i0, j0 = max(0, int(x0 / G) - 1), max(0, int(y0 / G) - 1)
    i1, j1 = min(N, int(x1 / G) + 2), min(N, int(y1 / G) + 2)
    if i1 <= i0 or j1 <= j0:
        return
    X, Y = np.meshgrid(np.arange(i0, i1) * G, np.arange(j0, j1) * G)      # cell centres on the 0.05 mm grid, like the pads
    m = shapely.contains_xy(g, X, Y)
    arr[j0:j1, i0:i1][m] = val


def zone_polys(z, layer):
    out = []
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
    return out


def track_geom(t):
    if isinstance(t, pcbnew.PCB_VIA):
        return Point(copper.from_abs(t.GetPosition())).buffer(pcbnew.ToMM(t.GetWidth()) / 2)
    return LineString([copper.from_abs(t.GetStart()), copper.from_abs(t.GetEnd())]).buffer(pcbnew.ToMM(t.GetWidth()) / 2)


def soft(t):
    return not t.IsLocked() and t.GetNetname() not in HARD_NETS


class Grid:
    def __init__(self, board):
        self.board = board
        self.hard = {L: np.zeros((N, N), np.int32) for L in LAYERS}
        self.hole = np.zeros((N, N), bool)
        self.pads = np.zeros((N, N), bool)
        global HIST
        if HIST is None:
            HIST = np.zeros((N, N), np.float32)
        self.hist = HIST              # congestion history survives between rounds
        e = int(round(0.45 / G))
        for L in LAYERS:
            a = self.hard[L]
            a[:e, :] = -2; a[-e:, :] = -2; a[:, :e] = -2; a[:, -e:] = -2
        for z in board.Zones():
            if z.GetAssignedPriority() == 0:      # ground fills flow around whatever is routed
                continue
            for L in LAYERS:
                if z.IsOnLayer(L) and z.IsFilled():
                    for q in zone_polys(z, L):
                        raster(q, self.hard[L], z.GetNetCode())
        for fp in board.GetFootprints():
            for p in fp.Pads():
                g = copper.pad_geom(p)
                raster(g, self.pads, True, grow=0)
                npth = p.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH
                tht = p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH or npth
                nc = -2 if npth or not p.GetNetCode() else p.GetNetCode()
                for L in LAYERS:
                    if tht or p.IsOnLayer(L):
                        # bare holes need the larger hole clearance (0.25 mm)
                        raster(g, self.hard[L], nc, grow=G * 0.75 + (0.12 if npth else 0.0))
                if tht:
                    raster(copper.hole_geom(p), self.hole, True)
        for t in board.GetTracks():
            if isinstance(t, pcbnew.PCB_VIA):
                raster(Point(copper.from_abs(t.GetPosition())).buffer(pcbnew.ToMM(t.GetDrill()) / 2), self.hole, True)
            if not soft(t):
                self._stamp(self.hard, t)
        # a cost band around the fine-pitch ICs on F.Cu: paths leave their pins radially and drop to B.Cu
        # instead of circling the package and walling in the pins that are routed later
        # Around the fine-pitch ICs: an escape ring on F.Cu that only the IC's own nets may use, so
        # passing traces cannot wall the pins in, plus a cost band so the IC's nets leave radially.
        self.static = {L: np.zeros((N, N), np.float32) for L in LAYERS}
        self.rings = []
        for ref, width in (("U601", 1.6), ("U201", 1.0), ("U304", 1.0)):
            fp = board.FindFootprintByReference(ref)
            m = np.zeros((N, N), bool)
            for p in fp.Pads():
                raster(copper.pad_geom(p), m, True, grow=0)
            ring = ndimage.binary_dilation(m, structure=disk(width / G)) & ~m
            own = {p.GetNetCode() for p in fp.Pads() if p.GetNetCode()}
            # each of the IC's nets may only cross the ring in the lane in front of (or behind) its own pins
            lanes = {}
            for p in fp.Pads():
                g = copper.pad_geom(p)
                x0, y0, x1, y1 = g.bounds
                if (x1 - x0) > 3 and (y1 - y0) > 3:         # exposed pad
                    continue
                ext = width + 0.3
                if (x1 - x0) >= (y1 - y0):
                    lane = box(x0 - ext, y0 - 0.02, x1 + ext, y1 + 0.02)
                else:
                    lane = box(x0 - 0.02, y0 - ext, x1 + 0.02, y1 + ext)
                lanes.setdefault(p.GetNetCode(), []).append(lane)
            self.rings.append((ring, own, {k: unary_union(v) for k, v in lanes.items()}))
            band = ndimage.binary_dilation(m, structure=disk(2.5 / G)) & ~ndimage.binary_dilation(m, structure=disk(0.4 / G))
            self.static[LAYERS[0]][band] += BAND_COST
        self.rebuild_soft()

    def _stamp(self, target, t):
        g = track_geom(t)
        if isinstance(t, pcbnew.PCB_VIA):
            for L in LAYERS:
                raster(g, target[L], t.GetNetCode())
        elif t.GetLayer() in LAYERS:
            raster(g, target[t.GetLayer()], t.GetNetCode())

    def rebuild_soft(self):
        self.soft = {L: np.zeros((N, N), np.int32) for L in LAYERS}
        self.soft_items = [t for t in self.board.GetTracks() if soft(t)]
        for t in self.soft_items:
            self._stamp(self.soft, t)

    def add(self, items):
        for t in items:
            self._stamp(self.soft, t)
            self.soft_items.append(t)
            if isinstance(t, pcbnew.PCB_VIA):
                raster(Point(copper.from_abs(t.GetPosition())).buffer(VIA_DRILL / 2), self.hole, True)


class Item(dict):
    """Layer -> copper geometry of a routing endpoint, plus the centre geometry tracks must end on."""
    anchor = None


def real_net(board, name):
    if board.FindNet(name) is not None:
        return name
    for n in board.GetNetsByName().keys():
        s = str(n)
        if s.replace("{slash}", "/") == name:
            return s
    return name


def find_item(board, net, desc, x, y):
    """Geometry per routing layer for the item named in a DRC line."""
    p = Point(x - place.BX0, y - place.BY0)
    m = re.search(r"[Pp]ad (\S+) \[.*\] of (\S+)", desc)
    if m:
        fp = board.FindFootprintByReference(m.group(2))
        for pd in fp.Pads():
            if pd.GetNumber() == m.group(1) and pd.GetNetname() == net:
                g = copper.pad_geom(pd)
                if g.distance(p) < 0.05:
                    tht = pd.GetAttribute() == pcbnew.PAD_ATTRIB_PTH
                    out = Item({L: g for L in LAYERS if tht or pd.IsOnLayer(L)})
                    anchors = [Point(copper.from_abs(pd.GetPosition()))]
                    # include the escape stubs and other own copper that starts on the pad
                    for t in board.GetTracks():
                        if t.GetNetname() == net and not isinstance(t, pcbnew.PCB_VIA) and t.GetLayer() in out:
                            tg = track_geom(t)
                            if tg.distance(g) < 0.01:
                                out[t.GetLayer()] = out[t.GetLayer()].union(tg)
                                anchors.append(LineString([copper.from_abs(t.GetStart()), copper.from_abs(t.GetEnd())]))
                    out.anchor = unary_union(anchors)
                    return out
    best = None
    if desc.startswith(("Track", "Via")):
        for t in board.GetTracks():
            if t.GetNetname() != net:
                continue
            Ls = LAYERS if isinstance(t, pcbnew.PCB_VIA) else ((t.GetLayer(),) if t.GetLayer() in LAYERS else ())
            if not Ls:
                continue
            g = track_geom(t)
            d = g.distance(p)
            if best is None or d < best[0]:
                anc = Point(copper.from_abs(t.GetPosition())) if isinstance(t, pcbnew.PCB_VIA) else \
                    LineString([copper.from_abs(t.GetStart()), copper.from_abs(t.GetEnd())])
                if anc.length == 0 and not isinstance(t, pcbnew.PCB_VIA):
                    anc = Point(copper.from_abs(t.GetStart()))
                best = (d, g, Ls, anc)
        if best and best[0] < 0.3:
            out = Item({L: best[1] for L in best[2]})
            out.anchor = best[3]
            return out
        return {}
    if desc.startswith("Zone"):
        lay = LAYERS[1] if " on B.Cu" in desc else LAYERS[0]
        for z in board.Zones():
            if z.GetNetname() != net or not z.IsOnLayer(lay):
                continue
            for q in zone_polys(z, lay):
                d = q.distance(p)
                if best is None or d < best[0]:
                    best = (d, q, (lay,))
        if best and best[0] < 2.0:
            return Item({L: best[1] for L in best[2]})
    return {}


def parse_unconnected(report):
    txt = open(report).read().split("\n")
    out = []
    for i, l in enumerate(txt):
        if l.startswith("[unconnected_items]"):
            items = []
            for l2 in txt[i + 2:i + 4]:
                m = re.search(r"@\(([\d.]+) mm, ([\d.]+) mm\): (.*)", l2.strip())
                if m:
                    nm = re.search(r"\[([^\]]+)\]", m.group(3))
                    items.append((float(m.group(1)), float(m.group(2)), m.group(3), nm.group(1) if nm else ""))
            if len(items) == 2 and items[0][3] == items[1][3]:
                out.append(items)
    return out


def route_pair(grid, board, net, src, dst, margin=12.0, allow_rip=False, narrow=False):
    ni = board.FindNet(net)
    nc = ni.GetNetCode()
    w, clr = CLASS[copper.assignments().get(net, "Default")]
    if narrow:
        w = 0.2              # neck down; the current of these nets is carried by pours and planes
    global HC
    if HC is None:
        HC = np.array(sorted(board.FindNet(n).GetNetCode() for n in copper.HIGH), np.int32)
    extra = max(0.0, CLASS["HighCurrent"][1] - clr)
    r = (w / 2 + clr) / G + 0.75
    rv = (VIA_D / 2 + clr) / G + 0.75
    allg = list(src.values()) + list(dst.values())
    bx0 = max(0, min(g.bounds[0] for g in allg) - margin); by0 = max(0, min(g.bounds[1] for g in allg) - margin)
    bx1 = min(place.BW, max(g.bounds[2] for g in allg) + margin); by1 = min(place.BH, max(g.bounds[3] for g in allg) + margin)
    i0, j0, i1, j1 = int(bx0 / G), int(by0 / G), int(bx1 / G), int(by1 / G)
    H, W = j1 - j0, i1 - i0
    free, cost, vfree, losm = [], [], None, []
    vcost = np.zeros((H, W), np.float32)
    ringblk = np.zeros((H, W), bool)
    for ring, own, lanes in grid.rings:
        rw = ring[j0:j1, i0:i1]
        if not rw.any():
            continue
        if nc not in own:
            ringblk |= rw
        elif USE_LANES and net not in HARD_NETS and nc in lanes:
            tmp = np.zeros((N, N), bool)
            raster(lanes[nc], tmp, True, grow=0)
            ringblk |= rw & ~tmp[j0:j1, i0:i1]
    for L in LAYERS:
        h = grid.hard[L][j0:j1, i0:i1]
        s = grid.soft[L][j0:j1, i0:i1]
        hb = ndimage.binary_dilation((h != 0) & (h != nc), structure=disk(r))
        hb |= ringblk          # the escape ring is reserved on both layers
        sb = ndimage.binary_dilation((s != 0) & (s != nc), structure=disk(r))
        if extra > 0:          # KiCad applies the larger of the two net-class clearances
            hb |= ndimage.binary_dilation(np.isin(h, HC) & (h != nc), structure=disk(r + extra / G))
            sb |= ndimage.binary_dilation(np.isin(s, HC) & (s != nc), structure=disk(r + extra / G))
        hv = ndimage.binary_dilation((h != 0) & (h != nc), structure=disk(rv))
        sv = ndimage.binary_dilation((s != 0) & (s != nc), structure=disk(rv))
        if extra > 0:
            hv |= ndimage.binary_dilation(np.isin(h, HC) & (h != nc), structure=disk(rv + extra / G))
            sv |= ndimage.binary_dilation(np.isin(s, HC) & (s != nc), structure=disk(rv + extra / G))
        # line-of-sight mask for straightening: one extra cell of clearance
        hb2 = ndimage.binary_dilation((h != 0) & (h != nc), structure=disk(r + 1.0))
        if extra > 0:
            hb2 |= ndimage.binary_dilation(((np.isin(h, HC) & (h != nc)) | (np.isin(s, HC) & (s != nc))), structure=disk(r + 1.0 + extra / G))
        if not allow_rip:
            hb2 |= ndimage.binary_dilation((s != 0) & (s != nc), structure=disk(r + 1.0))
        losm.append(~(hb2 | ringblk))
        if allow_rip:
            free.append(~hb)
            cost.append(np.where(sb, SOFT_COST, 0.0).astype(np.float32) + grid.hist[j0:j1, i0:i1] + grid.static[L][j0:j1, i0:i1])
            vf = ~hv
            vcost += np.where(sv, SOFT_COST * 3, 0.0).astype(np.float32)
        else:
            free.append(~(hb | sb))
            cost.append(grid.hist[j0:j1, i0:i1] + grid.static[L][j0:j1, i0:i1])
            vf = ~(hv | sv)
        vfree = vf if vfree is None else vfree & vf
    vfree &= ~ndimage.binary_dilation(ringblk, structure=disk(VIA_D / 2 / G + 0.5))
    vfree &= ~ndimage.binary_dilation(grid.hole[j0:j1, i0:i1], structure=disk((VIA_DRILL / 2 + 0.25 + 0.15) / G + 0.5))
    vfree &= ~ndimage.binary_dilation(grid.pads[j0:j1, i0:i1], structure=disk(VIA_D / 2 / G + 0.5))
    S = np.zeros((2, H, W), bool)
    T = np.zeros((2, H, W), bool)
    for k, L in enumerate(LAYERS):
        for dct, arr in ((src, S), (dst, T)):
            if L in dct:
                tmp = np.zeros((N, N), bool)
                raster(dct[L], tmp, True, grow=-G * 0.4)
                arr[k] = tmp[j0:j1, i0:i1]
    if not S.any() or not T.any():
        return None
    tc = np.argwhere(T).mean(axis=0)
    sc = np.argwhere(S).mean(axis=0)
    span = math.hypot(tc[1] - sc[1], tc[2] - sc[2]) * G
    hw = H_WEIGHT if span < 15 else (1.6 if span < 30 else 2.0)   # greedier search for long connections
    HW = H * W
    pas = np.concatenate([(free[0] | S[0] | T[0]).ravel(), (free[1] | S[1] | T[1]).ravel()])
    cst = np.concatenate([np.asarray(cost[0], np.float32).ravel(), np.asarray(cost[1], np.float32).ravel()])
    tgt = T.ravel()
    vf = vfree.ravel()
    vc = np.asarray(vcost, np.float32).ravel()
    gscore = np.full(2 * HW, np.inf, np.float32)
    parent = np.full(2 * HW, -1, np.int64)
    closed = np.zeros(2 * HW, bool)
    ty, tx = tc[1], tc[2]
    heap = []
    for k, y, x in np.argwhere(S):
        i = (k * H + y) * W + x
        gscore[i] = 0.0
        heap.append((hw * math.hypot(y - ty, x - tx), int(i)))
    heapq.heapify(heap)
    D = [(-1, -1, 1.4142), (-1, 0, 1.0), (-1, 1, 1.4142), (0, -1, 1.0), (0, 1, 1.0), (1, -1, 1.4142), (1, 0, 1.0), (1, 1, 1.4142)]
    end = None
    pops = 0
    LIMIT = 3_000_000
    while heap:
        _, i = heapq.heappop(heap)
        if closed[i]:
            continue
        closed[i] = True
        pops += 1
        if pops > LIMIT:
            break
        if tgt[i]:
            end = i
            break
        k, rem = divmod(i, HW)
        y, x = divmod(rem, W)
        gs = float(gscore[i])
        base = k * HW
        for dy, dx, c in D:
            ny, nx = y + dy, x + dx
            if 0 <= ny < H and 0 <= nx < W:
                j = base + ny * W + nx
                if not pas[j] or closed[j]:
                    continue
                if dy and dx and not (pas[base + y * W + nx] and pas[base + ny * W + x]):
                    continue
                ng = gs + c * (1.0 + float(cst[j]))
                if ng < gscore[j]:
                    gscore[j] = ng
                    parent[j] = i
                    heapq.heappush(heap, (ng + hw * math.hypot(ny - ty, nx - tx), j))
        if vf[rem]:
            j = (1 - k) * HW + rem
            if pas[j] and not closed[j]:
                ng = gs + VIA_COST + float(vc[rem])
                if ng < gscore[j]:
                    gscore[j] = ng
                    parent[j] = i
                    heapq.heappush(heap, (ng + hw * math.hypot(y - ty, x - tx), j))
    if end is None:
        LAST["why"] = ("limit" if pops > LIMIT else "exhausted", pops, int(S.sum()), int(T.sum()), (H, W))
        return None
    path = []
    i = end
    while i >= 0:
        k, rem = divmod(int(i), HW)
        y, x = divmod(rem, W)
        path.append((k, y, x))
        i = int(parent[i])
    path.reverse()
    # split into layer runs; vias where the layer changes
    runs, vcells = [], []
    ck, cur = path[0][0], [(path[0][1], path[0][2])]
    for k, y, x in path[1:]:
        if k != ck:
            runs.append((ck, cur)); vcells.append(cur[-1])
            ck, cur = k, [(y, x)]
        else:
            cur.append((y, x))
    runs.append((ck, cur))
    # string pulling: straight segments wherever the line of sight stays one cell inside free space
    los = [losm[k] | S[k] | T[k] for k in (0, 1)]

    def clear(k, a, b):
        n = int(max(abs(b[0] - a[0]), abs(b[1] - a[1])) * 4) + 1
        ys = np.rint(np.linspace(a[0], b[0], n)).astype(int)
        xs = np.rint(np.linspace(a[1], b[1], n)).astype(int)
        return bool(los[k][ys, xs].all())

    cell = lambda c: ((i0 + c[1]) * G, (j0 + c[0]) * G)
    segs = []
    for k, cells in runs:
        i, keep = 0, [cells[0]]
        while i < len(cells) - 1:
            step = 1
            while i + step * 2 < len(cells) and clear(k, cells[i], cells[i + step * 2]):
                step *= 2
            lo, hi = i + step, min(len(cells) - 1, i + step * 2)
            while lo < hi:
                mid = (lo + hi + 1) // 2
                if clear(k, cells[i], cells[mid]):
                    lo = mid
                else:
                    hi = mid - 1
            i = max(lo, i + 1)
            keep.append(cells[i])
        # merge collinear steps that string pulling could not straighten
        merged = [keep[0]]
        for idx in range(1, len(keep)):
            if len(merged) >= 2:
                a, b, c = merged[-2], merged[-1], keep[idx]
                if (b[0] - a[0]) * (c[1] - b[1]) == (b[1] - a[1]) * (c[0] - b[0]) and \
                        (b[0] - a[0]) * (c[0] - b[0]) + (b[1] - a[1]) * (c[1] - b[1]) > 0:
                    merged[-1] = c
                    continue
            merged.append(keep[idx])
        for p, q in zip(merged, merged[1:]):
            segs.append((k, cell(p), cell(q)))
    vias = [cell(c) for c in vcells]
    # end the route on the anchor of each endpoint (pad centre or track centre line) so KiCad sees it connected
    k0, k1 = runs[0][0], runs[-1][0]
    p0, p1 = cell(runs[0][1][0]), cell(runs[-1][1][-1])
    for item, k, p, first in ((src, k0, p0, True), (dst, k1, p1, False)):
        anc = getattr(item, "anchor", None)
        if anc is None or LAYERS[k] not in item:
            continue
        from shapely.ops import nearest_points
        q = nearest_points(Point(p), anc)[1]
        if q.distance(Point(p)) > 1e-3 and item[LAYERS[k]].buffer(1e-3).contains(LineString([p, (q.x, q.y)])):
            if first:
                segs.insert(0, (k, (q.x, q.y), p))
            else:
                segs.append((k, p, (q.x, q.y)))
    ripped = []
    if allow_rip:
        geoms = {0: [], 1: []}
        for k, a, b in segs:
            geoms[k].append(LineString([a, b]).buffer(w / 2 + clr + 0.02))
        for v in vias:
            for k in (0, 1):
                geoms[k].append(Point(v).buffer(VIA_D / 2 + clr + 0.02))
        for t in grid.soft_items:
            if t.GetNetCode() == nc:
                continue
            tg = track_geom(t)
            ks = (0, 1) if isinstance(t, pcbnew.PCB_VIA) else ((LAYERS.index(t.GetLayer()),) if t.GetLayer() in LAYERS else ())
            if any(tg.intersects(gg) for k in ks for gg in geoms[k]):
                ripped.append(t)
        for t in ripped:
            board.Delete(t)
        if ripped:
            for k, y, x in path:
                grid.hist[j0 + y, i0 + x] += 2.0
            grid.rebuild_soft()
    made = [copper.add_track(board, net, LAYERS[k], w, a, b, locked=False) for k, a, b in segs]
    made += [copper.add_via(board, net, v[0], v[1], VIA_D, VIA_DRILL, locked=False) for v in vias]
    grid.add(made)
    return made, len(ripped)


def finish(board, report, allow_rip=False, log=print):
    grid = Grid(board)
    pairs = parse_unconnected(report)
    # fine-pitch ICs first (their pins have the least room to escape), then short connections first
    fine = ("of U601", "of U201", "of J701", "of U401", "of U402", "of U304")
    pairs.sort(key=lambda ab: (0 if any(f in ab[0][2] or f in ab[1][2] for f in fine) else 1,
                               math.hypot(ab[0][0] - ab[1][0], ab[0][1] - ab[1][1])))
    ok = bad = rips = 0
    failed = []
    for a, b in pairs:
        net = real_net(board, a[3])
        src = find_item(board, net, a[2], a[0], a[1])
        dst = find_item(board, net, b[2], b[0], b[1])
        if not src or not dst:
            failed.append(f"{net}: item not found ({a[2][:30]} / {b[2][:30]})")
            bad += 1
            continue
        res = route_pair(grid, board, net, src, dst)
        if res is None:
            res = route_pair(grid, board, net, src, dst, margin=40.0)
        if res is None and CLASS[copper.assignments().get(net, "Default")][0] > 0.2:
            res = route_pair(grid, board, net, src, dst, margin=25.0, narrow=True)
        if res is None and allow_rip:
            res = route_pair(grid, board, net, src, dst, margin=25.0, allow_rip=True)
        if res is None:
            bad += 1
            failed.append(f"{net} {a[2][:40]} -> {b[2][:40]}")
        else:
            ok += 1
            rips += res[1]
    log(f"finisher: routed {ok}, failed {bad}, ripped {rips} items")
    for f in failed:
        log("  open: " + f)
    return ok, failed
