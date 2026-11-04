"""Placement: hand anchors + greedy connectivity placer for the rest (board coords: mm, origin top-left)."""
import math
import pcbnew
from shapely.geometry import box as sbox
from shapely.prepared import prep
from shapely.ops import unary_union

BX0, BY0 = 50.0, 40.0           # board origin on the KiCad page
BW, BH = 100.0, 100.0
CLR = 0.25                       # courtyard spacing (anchors)
CLR_AUTO = 0.55
ESCAPE_ROOM = {"U601": 2.2, "U201": 1.2, "U304": 1.0}                  # spacing for auto-placed parts: leaves routing channels

# ref: (x, y, rot)  -- footprint origin in board coordinates, rot CCW degrees
ANCHORS = {
    # mounting holes
    "H601": (4, 4, 0), "H602": (96, 4, 0), "H603": (4, 96, 0), "H604": (96, 96, 0),
    # input posts (left edge), output posts (right edge); post bodies overhang the edge
    "J101": (9.5, 15, 0), "J102": (9.5, 35, 0), "J501": (90.5, 15, 180), "J502": (90.5, 35, 180),
    # 10 A pass-through highway along the top
    "F102": (20, 9, 0), "R501": (43, 8.5, 0), "U501": (43, 14.5, 180),
    "K501": (52, 17.5, 0),
    "Q502": (72, 25.5, 180), "Q503": (80.8, 25.5, 0),
    # input protection
    "F101": (21.2, 16.5, 0), "Q101": (29.2, 22.0, 90), "D101": (18, 22.3, 90), "C101": (24, 34.8, 180),
    # housekeeping rails
    "U101": (7, 47, 0), "L101": (14.5, 47, 0), "U102": (8, 58, 0), "U103": (17, 57, 0), "U104": (24, 62, 0),
    # tracking buck
    "U201": (41, 30, 0), "L201": (41, 44, 0), "C211": (54.5, 44, 90),
    "C202": (42.8, 25.4, 180), "C201": (42.8, 22.1, 180), "Q304": (85.0, 49.5, 0),
    "C207": (46.2, 53.3, 270), "C208": (49.6, 53.3, 270), "C209": (53.0, 53.3, 270), "C210": (56.4, 53.3, 270),
    # pass element at the right edge (heatsink overhangs the edge)
    "Q301": (95, 45.5, 270),
    # linear stage
    "R301": (86, 58, 180), "U301": (86, 62.3, 180), "TH301": (93.5, 61.5, 0), "U302": (60, 60, 0), "U303": (60, 70, 0), "U304": (49, 66, 0),
    # ranging + island
    "Q401": (78.4, 55.2, 0), "R401": (79.0, 58.2, 180), "D401": (78.4, 61.2, 180),
    "Q402": (72.4, 55.2, 0), "R402": (73.0, 58.2, 180), "D402": (72.4, 61.2, 180),
    "U401": (78, 69, 0), "U402": (86, 69, 0),
    "PS401": (91, 77, 0), "U403": (83, 92, 0), "U404": (71, 86, 0), "U405": (79, 80, 0),
    # MCU, debug, UI
    "U601": (40, 85, 180), "Y601": (49.5, 89, 90), "J601": (56.6, 94, 0), "SW601": (66.2, 96, 0),
    # USB
    "J701": (5, 84, 270), "U701": (12.5, 75.5, 0), "U702": (21.5, 86, 0),
}

# block regions (x0, y0, x1, y1) for auto-placed parts
REGIONS = {
    "in": (12, 12, 38, 46), "hk": (0, 39, 30, 66), "buck": (30, 18, 62, 56), "pass": (60, 33, 92, 53),
    "amp": (43, 52, 66, 78), "rng": (64, 52, 92, 76), "iso": (71.6, 76.6, 99.5, 99.5), "mcu": (26, 70, 64, 100),
    "out": (44, 18, 100, 40), "usbpc": (0, 66, 16, 100), "usbmcu": (24, 70, 30, 100), "ui": (52, 82, 71.2, 100), "psin": (82, 72, 89.4, 80.6), "isomcu": (60, 76, 70.6, 92),
}


def region_of(ref, val=""):
    n = int("".join(ch for ch in ref if ch.isdigit()) or 0)
    s, k = n // 100, n % 100
    if s == 1:
        return "in" if (ref in ("R101", "R102", "R103", "C102", "C103", "C104", "D102") or ref.startswith("F")) else "hk"
    if s == 2:
        return "buck"
    if s == 3:
        if ref in ("U302", "U303", "U304") or ref in [f"R{x}" for x in (303, 304, 305, 306, 307, 308, 309, 310, 311, 322, 325, 326, 327)] \
                or ref in [f"C{x}" for x in (302, 303, 304, 305, 306, 307, 308, 309, 310, 311, 319, 320, 321, 322)]:
            return "amp"
        return "pass"
    if s == 4:
        if ref == "C406":
            return "psin"
        if ref in ("C409", "R412", "R413"):
            return "isomcu"
        if ref in ("PS401", "U403", "U404", "U405", "R411") or ref in [f"C{x}" for x in range(406, 413)]:
            return "iso"
        return "rng"
    if s == 5:
        return "out"
    if s == 6:
        if ref.startswith(("D6", "SW")) or ref in ("R602", "R603", "R604", "R605", "R606", "C614"):
            return "ui"
        return "mcu"
    if s == 7:
        return "usbmcu" if ref in ("R706", "R707", "R708", "C706", "C707") else "usbpc"
    return "mcu"


def to_abs(x, y):
    return pcbnew.VECTOR2I(pcbnew.FromMM(BX0 + x), pcbnew.FromMM(BY0 + y))


def crtyd_abs(fp):
    xs, ys = [], []
    for it in fp.GraphicalItems():
        if it.GetLayer() in (pcbnew.F_CrtYd, pcbnew.B_CrtYd):
            bb = it.GetBoundingBox()
            xs += [bb.GetLeft(), bb.GetRight()]; ys += [bb.GetTop(), bb.GetBottom()]
    if not xs:
        for p in fp.Pads():
            bb = p.GetBoundingBox()
            xs += [bb.GetLeft(), bb.GetRight()]; ys += [bb.GetTop(), bb.GetBottom()]
        m = pcbnew.FromMM(0.25)
        xs = [min(xs) - m, max(xs) + m]; ys = [min(ys) - m, max(ys) + m]
    return (pcbnew.ToMM(min(xs)) - BX0, pcbnew.ToMM(min(ys)) - BY0, pcbnew.ToMM(max(xs)) - BX0, pcbnew.ToMM(max(ys)) - BY0)


def put(fp, x, y, rot):
    fp.SetPosition(to_abs(x, y))
    fp.SetOrientationDegrees(rot)


def overlaps(a, b, c=CLR):
    return a[0] < b[2] + c and b[0] < a[2] + c and a[1] < b[3] + c and b[1] < a[3] + c


def clip_board(r):
    """Courtyard part that lies on the board (posts and the TO-247 overhang the edge)."""
    return (max(r[0], 0), max(r[1], 0), min(r[2], BW), min(r[3], BH))


def run(board, fps, comps, nets, log=print):
    """fps: ref -> FOOTPRINT (on board).  Places anchors then the rest."""
    placed = {}
    for ref, (x, y, rot) in ANCHORS.items():
        put(fps[ref], x, y, rot)
        r = clip_board(crtyd_abs(fps[ref]))
        for o, ro in placed.items():
            if overlaps(r, ro, 0.0):
                log(f"ANCHOR OVERLAP {ref} / {o}")
        placed[ref] = r
    # escape room around the fine-pitch ICs: auto-placed parts stay this far from their courtyards
    for ref, room in ESCAPE_ROOM.items():
        r = placed[ref]
        placed[ref] = (r[0] - room, r[1] - room, r[2] + room, r[3] + room)
    # net membership (pads) for attraction
    pad_net = {}
    for net, nodes in nets.items():
        for r, p in nodes:
            pad_net[(r, p)] = net
    big = {n for n, nodes in nets.items() if len(nodes) > 14}

    def net_targets(ref):
        """For each pad of ref: centroid of the already placed pads on the same (small) net."""
        tg = {}
        for p in fps[ref].Pads():
            n = pad_net.get((ref, p.GetNumber()))
            if not n or n in big:
                continue
            pts = []
            for r2, p2 in nets[n]:
                if r2 != ref and r2 in placed:
                    for q in fps[r2].Pads():
                        if q.GetNumber() == p2:
                            pts.append((pcbnew.ToMM(q.GetPosition().x) - BX0, pcbnew.ToMM(q.GetPosition().y) - BY0))
                            break
            if pts:
                tg[p.GetNumber()] = (sum(a for a, _ in pts) / len(pts), sum(b for _, b in pts) / len(pts))
        return tg

    import power
    keep = prep(unary_union(power.placement_keepouts()).buffer(0.15))
    todo = [r for r in fps if r not in placed]
    unplaced = []
    while todo:
        # most-connected-to-placed first
        scored = sorted(todo, key=lambda r: -len(net_targets(r)))
        ref = scored[0]
        todo.remove(ref)
        reg = REGIONS[region_of(ref)]
        tg = net_targets(ref)
        if tg:
            cx = sum(v[0] for v in tg.values()) / len(tg); cy = sum(v[1] for v in tg.values()) / len(tg)
        else:
            cx, cy = (reg[0] + reg[2]) / 2, (reg[1] + reg[3]) / 2
        cx = min(max(cx, reg[0] + 1), reg[2] - 1); cy = min(max(cy, reg[1] + 1), reg[3] - 1)
        fp = fps[ref]
        best = None
        found = 0
        step = 0.5
        for ring in range(0, 80):
            cands = []
            if ring == 0:
                cands = [(cx, cy)]
            else:
                for i in range(-ring, ring + 1):
                    for (dx, dy) in ((i, -ring), (i, ring), (-ring, i), (ring, i)):
                        cands.append((cx + dx * step, cy + dy * step))
            for (x, y) in cands:
                for rot in (0, 90, 180, 270):
                    put(fp, x, y, rot)
                    r = crtyd_abs(fp)
                    if r[0] < reg[0] or r[1] < reg[1] or r[2] > reg[2] or r[3] > reg[3]:
                        continue
                    if r[0] < 0.5 or r[1] < 0.5 or r[2] > BW - 0.5 or r[3] > BH - 0.5:
                        continue
                    if any(overlaps(r, o, CLR_AUTO) for o in placed.values()):
                        continue
                    if keep.intersects(sbox(*r)):
                        continue
                    cost = 0.0
                    for p in fp.Pads():
                        t = tg.get(p.GetNumber())
                        if t:
                            px = pcbnew.ToMM(p.GetPosition().x) - BX0; py = pcbnew.ToMM(p.GetPosition().y) - BY0
                            cost += math.hypot(px - t[0], py - t[1])
                    cost += 0.15 * math.hypot(x - cx, y - cy)
                    if best is None or cost < best[0]:
                        best = (cost, x, y, rot, r)
                    found += 1
            if found >= 12 and ring > 2:
                break
        if best is None:
            unplaced.append(ref)
            put(fp, -20, -20, 0)
            continue
        _, x, y, rot, r = best
        put(fp, x, y, rot)
        placed[ref] = r
    if unplaced:
        log(f"UNPLACED: {unplaced}")
    return placed, unplaced
