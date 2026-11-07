"""Placement for the rev B outline (140 x 80 mm), KiCad 10.

Run with KiCad 10's Python:  kicad10-python place.py <board.kicad_pcb>

- Footprints the user locked are never moved.
- ANCHORS are the hand-placed power and mechanical parts (local mm from the board's top-left corner).
- Everything else is placed by a greedy placer inside the region of its schematic block, pulled
  towards the pads it connects to, on a 0.25 mm grid with routing gaps between courtyards.
"""
import math
import re
import sys

from kc import pcbnew

OX, OY = 30.0, 59.92          # board top-left on the KiCad page
BW, BH = 140.0, 80.0
GRID = 0.25
GAP = 0.45                    # min gap between courtyards of auto-placed parts (routing channel)
EDGE = 0.6                    # courtyard to board edge
REF_H = 1.0                   # reference text height (JLCPCB minimum), stroke 0.15
LABEL_EDGE = 0.4              # reference text to board edge
LABEL_GAP = 0.3               # between two references, so they read as separate words

# ref: (x, y, rot) of the footprint origin, local mm
ANCHORS = {
    # top band: 15 A fuse at the input jack, pass element with its tab at the top edge (heatsink above
    # the board), then the relay that joins the pass-through and precision paths
    "F102": (12.2, 2.6, 0),
    "Q301": (45.0, 2.85, 0),
    "K501": (96.0, 3.6, 180),
    # pass-through shunt right under the fuse; the 10 A band runs below Q301 to K501 pin 14
    "R501": (35.5, 10.5, 0),
    # precision path: fuse, reverse-polarity P-FET, TVS, bulk cap, under the input jack
    "F101": (8.5, 24.5, 180),
    "D101": (17.0, 24.6, 180),       # GND pad on the right, out of the input pour
    "Q101": (11.0, 31.5, 180),
    "C101": (10.6, 41.5, 180),
    # tracking buck: VIN/PGND on the left (input caps), SW at the bottom into L201, control pins face the MCU
    "U201": (46.0, 30.4, 90),
    "C201": (41.7, 28.6, 90),        # input caps against the VIN/PGND pin column: smallest hot loop
    "C202": (38.4, 28.6, 90),
    "L201": (46.0, 42.0, 270),       # SW pad up against U201's SW pins, VPRE pad down
    "C211": (42.0, 54.3, 0),
    # 15 mOhm CC shunt at the head of the ranging chain, then two compact shunt columns:
    # shunt / bypass FET / clamp diodes, VFORCE -> N_MID -> VSENSE -> K501 pin 12
    "R301": (60.0, 16.5, 0),
    "U301": (60.0, 21.0, 0),          # INA293 under R301, pin 3 under pad 1 and pin 4 under pad 2 (Kelvin)
    # back-to-back output switch in the top-right corner: relay common -> Q502 drain | sources | Q503 drain -> J501
    "Q502": (113.0, 4.5, 180), "Q503": (121.0, 4.5, 0),
    "D502": (114.0, 11.0, 0),         # output TVS under the switch, cathode towards J501 pin 1
    # photovoltaic gate driver and gate pull-down below the switch (copper.HAND reaches both gates)
    "U502": (114.0, 16.75, 0), "R504": (117.5, 20.25, 0),
    "R401": (68.0, 17.5, 0), "Q401": (68.0, 21.0, 180), "D401": (68.0, 24.7, 0),
    "R402": (74.0, 17.5, 0), "Q402": (74.0, 21.0, 180), "D402": (74.0, 24.7, 0),
}

# placement keep-outs (x0, y0, x1, y1): the 10 A pass-through band from R501 to K501 pin 14 on F.Cu
# the fuse-to-shunt pour (VIN_PT) beside it, and the relay common (SW_IN) band from K501 to Q502's drain tab
KEEPOUTS = [(38.0, 7.4, 72.0, 13.8), (24.0, 1.0, 34.8, 12.8), (98.8, 5.0, 109.5, 9.7)]

# block regions (x0, y0, x1, y1), local mm. Several rectangles per block are allowed.
REGIONS = {
    "inp":   [(0.6, 21.9, 20.9, 36.0), (0.6, 36.0, 20.9, 47.2)],
    "hk":    [(0.6, 47.2, 20.9, 58.1), (20.9, 58.9, 61.0, 79.4)],
    "buck":  [(21.0, 26.5, 62.4, 58.9)],
    "lin":   [(21.0, 13.8, 68.4, 26.5), (21.0, 7.9, 38.0, 13.8)],
    "chain": [(63.0, 14.6, 109.3, 24.5)],
    "rsense": [(76.5, 14.6, 109.3, 24.5), (63.0, 14.6, 109.3, 27.0), (82.4, 24.5, 112.0, 30.0)],
    "out":   [(99.3, 0.6, 132.0, 8.4), (109.3, 8.4, 119.3, 24.0), (119.3, 21.9, 139.4, 36.0)],
    "iso":   [(82.4, 24.5, 112.0, 46.0)],
    "amp":   [(112.0, 24.5, 139.4, 58.1), (82.4, 46.0, 112.0, 58.1)],
    "mcu":   [(62.4, 24.5, 82.4, 49.0)],
    "usbm":  [(60.0, 44.0, 82.0, 64.0)],
    "ui":    [(76.6, 58.9, 119.3, 79.4)],
}
AMP_ICS = {"U302", "U303", "U304"}

AMP_PASSIVES = set()
INP = {"F101", "Q101", "D101", "D102", "C101", "R101", "R102", "R103", "C102", "C103", "C104"}
CHAIN = {"R401", "R402", "Q401", "Q402", "D401", "D402"}
ISO = {"PS401", "U403", "U404", "U405"}
COIL = {"Q501", "D501"}


def sheet(ref):
    return int(re.search(r"\d+", ref).group(0)) // 100


def region_of(ref, nets_of):
    s = sheet(ref)
    if s == 1:
        return "inp" if ref in INP else "hk"
    if s == 2:
        return "buck"
    if s == 3:
        if ref in AMP_ICS or ref in AMP_PASSIVES or ref in ("D301", "D302"):
            return "amp"
        return "lin"
    if s == 4:
        if ref in CHAIN:
            return "chain"
        if ref in ISO or nets_of(ref) & {"ISO_5V", "ISO_3V3", "DRV_A", "DRV_B"}:
            return "iso"
        return "rsense"
    if s == 5:
        if ref in COIL or ref == "U501" or ref in ("C501",):
            return "rsense" if ref in COIL else "lin"
        return "out"
    if s == 6:
        if ref.startswith(("D6", "SW", "J6", "TP", "TH")):
            return "ui"
        return "mcu"
    if s == 7:
        return "usbm"
    return "mcu"


def to_abs(x, y):
    return pcbnew.VECTOR2I(pcbnew.FromMM(OX + x), pcbnew.FromMM(OY + y))


def crtyd(fp):
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
    return (pcbnew.ToMM(min(xs)) - OX, pcbnew.ToMM(min(ys)) - OY, pcbnew.ToMM(max(xs)) - OX, pcbnew.ToMM(max(ys)) - OY)


def overlap(a, b, gap):
    return a[0] < b[2] + gap and b[0] < a[2] + gap and a[1] < b[3] + gap and b[1] < a[3] + gap


def inside(r, reg):
    return r[0] >= reg[0] and r[1] >= reg[1] and r[2] <= reg[2] and r[3] <= reg[3]


def label_size(f):
    """(w, h) of the reference at REF_H, unrotated."""
    ref = f.Reference()
    ref.SetVisible(True)
    f.Value().SetVisible(False)
    ref.SetTextSize(pcbnew.VECTOR2I(pcbnew.FromMM(REF_H), pcbnew.FromMM(REF_H)))
    ref.SetTextThickness(pcbnew.FromMM(0.15))
    ref.SetTextAngleDegrees(0)
    bb = ref.GetEffectiveTextShape().BBox()       # the glyphs; GetBoundingBox() adds line spacing
    return pcbnew.ToMM(bb.GetWidth()) + 0.2, pcbnew.ToMM(bb.GetHeight()) + 0.2


def label_spots(r, w, h):
    """Reference positions around courtyard r, best first: centred above/below, then left/right
    (rotated), then slid along the sides. Each is (x0, y0, x1, y1, rot)."""
    out = []
    cx, cy = (r[0] + r[2]) / 2, (r[1] + r[3]) / 2
    for d in (0.0, 0.25):
        for f in (0.0, -0.3, 0.3):
            sx = f * (r[2] - r[0] + w)
            out.append((cx + sx - w / 2, r[1] - d - h, cx + sx + w / 2, r[1] - d, 0))
            out.append((cx + sx - w / 2, r[3] + d, cx + sx + w / 2, r[3] + d + h, 0))
            sy = f * (r[3] - r[1] + w)
            out.append((r[0] - d - h, cy + sy - w / 2, r[0] - d, cy + sy + w / 2, 90))
            out.append((r[2] + d, cy + sy - w / 2, r[2] + d + h, cy + sy + w / 2, 90))
    return out


def set_label(f, spot):
    x0, y0, x1, y1, rot = spot
    ref = f.Reference()
    ref.SetTextAngleDegrees(rot)
    ref.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_CENTER)
    ref.SetVertJustify(pcbnew.GR_TEXT_V_ALIGN_CENTER)
    ref.SetPosition(to_abs((x0 + x1) / 2, (y0 + y1) / 2))


def run(path):
    board = pcbnew.LoadBoard(path)
    fps = {f.GetReference(): f for f in board.GetFootprints()}
    lsize = {ref: label_size(f) for ref, f in fps.items()}
    labels = {}                   # ref -> reserved reference rectangle (x0, y0, x1, y1, rot)
    nets = {}
    for ref, f in fps.items():
        for p in f.Pads():
            if p.GetNetname():
                nets.setdefault(p.GetNetname(), []).append((ref, p))
    big = {n for n, v in nets.items() if len(v) > 12} | {"GND", "GND_USB"}

    def nets_of(ref):
        return {p.GetNetname() for p in fps[ref].Pads() if p.GetNetname()}

    # sheet-3 passives that touch the error amps or the DAC belong to the amp block
    amp_nets = set()
    for ic in AMP_ICS:
        amp_nets |= nets_of(ic)
    amp_nets -= big
    for ref in fps:
        if sheet(ref) == 3 and ref[0] in "RCD" and nets_of(ref) & amp_nets and not ref.startswith("D3"):
            AMP_PASSIVES.add(ref)
    used_pins = {}

    placed = {}
    for ref, f in fps.items():
        if f.IsLocked():
            placed[ref] = crtyd(f)
    for ref, (x, y, rot) in ANCHORS.items():
        f = fps[ref]
        f.SetOrientationDegrees(rot)
        f.SetPosition(to_abs(x, y))
        r = crtyd(f)
        for o, ro in placed.items():
            if overlap(r, ro, 0.0):
                print(f"ANCHOR OVERLAP {ref} / {o}")
        placed[ref] = r
    # parts the user placed but did not lock (USB section) stay where they are
    for ref, f in fps.items():
        x, y = pcbnew.ToMM(f.GetPosition().x) - OX, pcbnew.ToMM(f.GetPosition().y) - OY
        if ref not in placed and 0 < x < BW and 0 < y < BH:
            placed[ref] = crtyd(f)
    def find_label(ref, r, extra=None):
        """First reference spot around r clear of every courtyard, reserved label and the board edge."""
        w, h = lsize[ref]
        for sp in label_spots(r, w, h):
            if sp[0] < LABEL_EDGE or sp[1] < LABEL_EDGE or sp[2] > BW - LABEL_EDGE or sp[3] > BH - LABEL_EDGE:
                continue
            if extra is not None and overlap(sp, extra, 0.0):
                continue
            if any(overlap(sp, o, 0.0) for k, o in placed.items() if not k.startswith("__")):
                continue
            if any(overlap(sp, o, LABEL_GAP) for o in labels.values()):
                continue
            return sp
        return None

    # labels for the fixed parts first, so the auto-placed ones leave room for them
    for ref in sorted(placed, key=lambda k: (placed[k][2] - placed[k][0]) * (placed[k][3] - placed[k][1])):
        sp = find_label(ref, placed[ref])
        if sp is not None:
            labels[ref] = sp
    for i, k in enumerate(KEEPOUTS):
        placed[f"__keepout{i}"] = k
    print("fixed:", len(placed), "labels", len(labels))

    def targets(ref):
        """pad number -> list of (x, y) of placed pads on the same small net."""
        tg = {}
        for p in fps[ref].Pads():
            n = p.GetNetname()
            if not n or n in big:
                continue
            pts = [(pcbnew.ToMM(q.GetPosition().x) - OX, pcbnew.ToMM(q.GetPosition().y) - OY)
                   for r2, q in nets[n] if r2 != ref and r2 in placed]
            if pts:
                tg.setdefault(p.GetNumber(), []).extend(pts)
        if not tg and ref[0] == "C":
            # decoupling cap: target one power pin of a placed IC of the same sheet (spread over the pins)
            for p in fps[ref].Pads():
                n = p.GetNetname()
                if not n or n in ("GND", "GND_USB"):
                    continue
                pins = [(r2, q) for r2, q in nets.get(n, []) if r2 != ref and r2 in placed and r2[0] == "U" and sheet(r2) == sheet(ref)]
                if pins:
                    r2, q = min(pins, key=lambda t: used_pins.get((t[0], t[1].GetNumber()), 0))
                    tg[p.GetNumber()] = [(pcbnew.ToMM(q.GetPosition().x) - OX, pcbnew.ToMM(q.GetPosition().y) - OY)]
                    tg["__pin__"] = (r2, q.GetNumber())
                    break
        return tg

    # geometry per rotation, relative to the footprint origin (computed once: the SWIG calls are slow)
    geo = {}

    def shape(ref, rot):
        k = (ref, rot)
        if k not in geo:
            f = fps[ref]
            f.SetOrientationDegrees(rot)
            f.SetPosition(to_abs(0, 0))
            c = crtyd(f)
            pads = [(p.GetNumber(), pcbnew.ToMM(p.GetPosition().x) - OX, pcbnew.ToMM(p.GetPosition().y) - OY) for p in f.Pads()]
            geo[k] = (c, pads)
        return geo[k]

    def area(ref):
        c = shape(ref, 0)[0]
        return (c[2] - c[0]) * (c[3] - c[1])

    todo = [r for r in fps if r not in placed]
    unplaced = []
    while todo:
        # most connections to already-placed parts first; ICs before passives on ties
        todo.sort(key=lambda r: (-(area(r) > 40), -sum(len(v) for k, v in targets(r).items() if k != "__pin__"),
                                 not r.startswith("U"), r))
        ref = todo.pop(0)
        f = fps[ref]
        regs = REGIONS[region_of(ref, nets_of)]
        tg = targets(ref)
        pin = tg.pop("__pin__", None)
        if pin:
            used_pins[pin] = used_pins.get(pin, 0) + 1
        allpts = [pt for v in tg.values() for pt in v]
        if allpts:
            cx = sum(p[0] for p in allpts) / len(allpts); cy = sum(p[1] for p in allpts) / len(allpts)
        else:
            cx, cy = (regs[0][0] + regs[0][2]) / 2, (regs[0][1] + regs[0][3]) / 2
        shapes = {rot: shape(ref, rot) for rot in (0, 90, 180, 270)}
        best = None
        n_geo = n_lab = 0
        for reg in regs + [None]:
            if reg is None:
                if best is not None:
                    break
                reg = (0.0, 0.0, BW, BH)           # fallback: anywhere near its connections
            tx = min(max(cx, reg[0]), reg[2]); ty = min(max(cy, reg[1]), reg[3])
            found = 0
            for ring in range(0, 160):
                cands = [(tx, ty)] if ring == 0 else \
                    [(tx + dx * GRID, ty + dy * GRID) for i in range(-ring, ring + 1)
                     for dx, dy in ((i, -ring), (i, ring), (-ring, i), (ring, i))]
                for x, y in cands:
                    x = round(x / GRID) * GRID; y = round(y / GRID) * GRID
                    for rot, (c, pads) in shapes.items():
                        r = (c[0] + x, c[1] + y, c[2] + x, c[3] + y)
                        if not inside(r, reg) or r[0] < EDGE or r[1] < EDGE or r[2] > BW - EDGE or r[3] > BH - EDGE:
                            continue
                        if any(overlap(r, o, GAP) for o in placed.values()):
                            continue
                        if any(overlap(r, o, 0.0) for o in labels.values()):
                            continue
                        cost = 0.0
                        for num, px, py in pads:
                            pts = tg.get(num)
                            if pts:
                                cost += min(math.hypot(px + x - a, py + y - b) for a, b in pts)
                        cost += 0.05 * math.hypot(x - cx, y - cy) + (0.3 if rot in (180, 270) else 0.0)
                        n_geo += 1
                        if best is None or cost < best[0]:
                            sp = find_label(ref, r)      # only parts that keep room for their reference
                            if sp is None:
                                n_lab += 1
                                continue
                            best = (cost, x, y, rot, r, sp)
                        found += 1
                if found >= 16 and ring > 3:
                    break
        if best is None:
            print(f"  {ref}: {n_geo} free spots, {n_lab} without room for the reference, target {cx:.1f},{cy:.1f}")
            unplaced.append(ref)
            f.SetOrientationDegrees(0)
            f.SetPosition(to_abs(BW + 20, 0))
            continue
        _, x, y, rot, r, sp = best
        f.SetOrientationDegrees(rot)
        f.SetPosition(to_abs(x, y))
        placed[ref] = r
        labels[ref] = sp
    if unplaced:
        print("UNPLACED:", unplaced)
    for ref, sp in labels.items():
        set_label(fps[ref], sp)
    print("labels reserved", len(labels), "of", len(fps))
    pcbnew.SaveBoard(path, board)
    return unplaced


if __name__ == "__main__":
    run(sys.argv[1])
