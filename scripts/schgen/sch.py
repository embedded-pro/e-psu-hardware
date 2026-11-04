"""Generate KiCad 7 hierarchical schematics from Python descriptions.

Connections are made with short wire stubs ending in net labels (local or global) or power
symbols, plus explicit straight/L wires between pins where the layout allows it. Every
connection is recorded so the exported netlist can be checked against the intent.
"""
import copy
import math
import uuid as _uuid
from sexp import Q, dump, find, findall
from lib import get_symbol, pins as lib_pins, bbox as lib_bbox

GRID = 1.27
STUB = 2.54
FONT = 1.27

POWER_SYMS = {
    "GND": "power:GND", "+3V3": "power:+3V3", "+5V": "power:+5V",
    "+3.3VA": "power:+3.3VA", "+5VA": "power:+5VA",
}
POWER_NATURAL = {"GND": (0, 1)}  # GND body points down; all other power symbols point up
SYM = "\x00sym:"                 # net-name prefix: draw this connection with the project's alias power symbol


def uid():
    return str(_uuid.uuid4())


def snap(v):
    return round(round(v / GRID) * GRID, 4)


def rot_vec(dx, dy, ang):
    """Rotate a lib-space (Y-up) vector CCW by ang degrees."""
    a = math.radians(ang)
    return (dx * math.cos(a) - dy * math.sin(a), dx * math.sin(a) + dy * math.cos(a))


class PinRef:
    def __init__(self, part, number, x, y, out, info):
        self.part, self.number, self.x, self.y, self.out, self.info = part, number, x, y, out, info

    @property
    def pos(self):
        return (self.x, self.y)

    def __repr__(self):
        return f"{self.part.ref}.{self.number}"


class Part:
    def __init__(self, sheet, lib_id, ref, value, at, rot, unit, fields, dnp, extra_lib, mirror=None):
        self.sheet, self.lib_id, self.ref, self.value = sheet, lib_id, ref, value
        self.x, self.y = snap(at[0]), snap(at[1])
        self.rot, self.unit, self.fields, self.dnp = rot % 360, unit, fields, dnp
        self.mirror = mirror     # None, "x" (flip vertically) or "y" (flip horizontally); rot 0/180 only
        assert mirror is None or self.rot in (0, 180)
        self.sym = get_symbol(lib_id, extra_lib)
        self.allpins = lib_pins(self.sym)
        self.uuid = uid()
        self.is_power = lib_id.startswith("power:") or ["power"] in self.sym
        self.fpos = None     # (dx, dy, justify) override: Reference at (x+dx, y+dy), Value 2.54 below

    def _xf(self, x, y):
        rx, ry = rot_vec(x, y, self.rot)
        if self.mirror == "y":
            rx = -rx
        elif self.mirror == "x":
            ry = -ry
        return (round(self.x + rx, 4), round(self.y - ry, 4))

    def unit_pins(self):
        return [p for p in self.allpins if p["unit"] in (0, self.unit)]

    def pin(self, number):
        number = str(number)
        cands = [p for p in self.unit_pins() if p["number"] == number]
        if not cands:
            cands = [p for p in self.unit_pins() if p["name"] == number]
            if len(cands) != 1:
                raise KeyError(f"{self.ref}: pin {number} not found / ambiguous")
        p = cands[0]
        x, y = self._xf(p["x"], p["y"])
        a = math.radians(p["angle"] + 180)
        dx, dy = rot_vec(math.cos(a), math.sin(a), self.rot)
        if self.mirror == "y":
            dx = -dx
        elif self.mirror == "x":
            dy = -dy
        out = (round(dx), round(-dy))
        return PinRef(self, p["number"], x, y, out, p)

    def __getitem__(self, k):
        return self.pin(k)

    def screen_bbox(self):
        x0, y0, x1, y1 = lib_bbox(self.sym, self.unit)
        pts = [self._xf(x, y) for x, y in ((x0, y0), (x0, y1), (x1, y0), (x1, y1))]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        return (min(xs), min(ys), max(xs), max(ys))


class Sheet:
    def __init__(self, project, name, filename, title, paper="A3", page=None):
        self.project, self.name, self.filename, self.title, self.paper = project, name, filename, title, paper
        self.uuid = uid()
        self.parts, self.wires, self.texts, self.rects, self.ncs = [], [], [], [], []
        self.conns = []      # (PinRef, net, mode)
        self.rails = []
        self.links = []      # (PinRef, PinRef, net) explicit wires
        self.paths = []
        self.page = page
        self.extra_lib = project.extra_lib
        project.sheets.append(self)

    # ---- content ----
    def part(self, lib_id, ref, value, at, rot=0, unit=1, fp="", lcsc="", mpn="", dnp=False, ds="~", mirror=None,
             **fields):
        f = {"Footprint": fp, "Datasheet": ds}
        if lcsc:
            f["LCSC"] = lcsc
        if mpn:
            f["MPN"] = mpn
        f.update(fields)
        p = Part(self, lib_id, ref, value, at, rot, unit, f, dnp, self.extra_lib, mirror)
        self.parts.append(p)
        return p

    def net(self, pinref, net, label=True):
        self.conns.append((pinref, net, label))
        return pinref

    def nets(self, part, mapping):
        for k, v in mapping.items():
            if v is None:
                self.nc(part[k])
            else:
                self.net(part[k], v)

    def link(self, a, b, net, via=None):
        """Wire pin a to pin b (straight or one corner). `via` forces corner 'h' or 'v' first."""
        self.links.append((a, b, net, via))
        self._wired(a, net); self._wired(b, net)

    def _wired(self, pr, net):
        """Pin is connected by drawn wire: drop any label request for it and record the connection."""
        for c in self.conns:
            if c[0].part is pr.part and c[0].number == pr.number and c[1] != net:
                raise ValueError(f"{pr} wired to {net} but already on {c[1]}")
        self.conns = [c for c in self.conns if not (c[0].part is pr.part and c[0].number == pr.number)]
        self.conns.append((pr, net, False))
        # stacked pins at the same spot are wired too
        for q in pr.part.unit_pins():
            if q["number"] != pr.number:
                o = pr.part.pin(q["number"])
                if abs(o.x - pr.x) < 1e-3 and abs(o.y - pr.y) < 1e-3:
                    self.conns = [c for c in self.conns if not (c[0].part is o.part and c[0].number == o.number)]
                    self.conns.append((o, net, False))

    def nc(self, pinref):
        self.ncs.append(pinref)

    def rail(self, net, y, pins, label=None, ext=2.54, tap=None, style=None):
        """Horizontal wire at height y joining `pins` (vertical drops from pins above/below, or pins
        lying on the rail). label: 'left' / 'right' puts the net label (or power symbol) at that end.
        tap=(x, (dx, dy)): label / power symbol on a short stub leaving the rail at x."""
        y = snap(y)
        for pr in pins:
            if isinstance(pr, PinRef):
                self._wired(pr, net)
        self.rails.append((SYM + net if style == "sym" else net, "h", y, list(pins), label, ext, tap))

    def vrail(self, net, x, pins, label=None, ext=2.54, tap=None, style=None):
        """Vertical wire at x joining `pins` (horizontal drops). label: 'top' / 'bottom'. tap=(y, (dx, dy))."""
        x = snap(x)
        for pr in pins:
            if isinstance(pr, PinRef):
                self._wired(pr, net)
        self.rails.append((SYM + net if style == "sym" else net, "v", x, list(pins), label, ext, tap))

    def path(self, net, items):
        """Polyline through PinRefs and (x, y) points (each corner must be given)."""
        for it in items:
            if isinstance(it, PinRef):
                self._wired(it, net)
        self.paths.append((net, list(items)))

    def flag(self, net, at, label=True):
        """PWR_FLAG on `net` (marks the net as driven for ERC). label=False: caller wires it (e.g. rail)."""
        self.project._flag_n = getattr(self.project, "_flag_n", 0) + 1
        f = self.part("power:PWR_FLAG", "#FLG%03d" % self.project._flag_n, "PWR_FLAG", at)
        f.fields = {"Footprint": "", "Datasheet": "~"}
        if label:
            self.net(f["1"], net)
        return f

    def text(self, s, at, size=FONT, bold=False):
        self.texts.append((s, snap(at[0]), snap(at[1]), size, bold))

    def box(self, x0, y0, x1, y1, title=None):
        self.rects.append((snap(x0), snap(y0), snap(x1), snap(y1)))
        if title:
            self.text(title, (x0 + 1.27, y0 + 3.0), size=1.8, bold=True)


class Project:
    def __init__(self, name, extra_lib=None):
        self.name = name
        self.extra_lib = extra_lib or {}
        self.sheets = []
        self.root_uuid = uid()
        self.expected = {}   # net -> set((ref, pin))
        self.sym_alias = {}  # net -> project power symbol (drawn for connections made with label="sym")

    # ---------------------------------------------------------------- build
    def build(self, outdir, root_title, root_texts=(), date="", rev="A", company=""):
        import os
        os.makedirs(outdir, exist_ok=True)
        # which nets are used on more than one sheet -> global labels
        use = {}
        for sh in self.sheets:
            for pr, n, _ in sh.conns:
                use.setdefault(n, set()).add(sh.name)
        self.global_nets = {n for n, s in use.items() if len(s) > 1 and n not in POWER_SYMS}
        for sh in self.sheets:      # sheets drawn with global labels only (e.g. the MCU pin map)
            if getattr(sh, "global_all", False):
                self.global_nets |= {n for pr, n, _ in sh.conns if n not in POWER_SYMS}
                for rl in sh.rails:
                    if not rl[0].startswith(SYM) and rl[0] not in POWER_SYMS:
                        self.global_nets.add(rl[0])
        # expected connectivity
        for sh in self.sheets:
            for pr, n, _ in sh.conns:
                key = n if (n in self.global_nets or n in POWER_SYMS) else f"/{sh.name}/{n}"
                if not pr.part.ref.startswith("#"):
                    self.expected.setdefault(key, set()).add((pr.part.ref, pr.number))
        for i, sh in enumerate(self.sheets):
            sh.page = str(i + 2)
            self._write_sheet(sh, os.path.join(outdir, sh.filename), date, rev, company)
        self._write_root(os.path.join(outdir, self.name + ".kicad_sch"), root_title, root_texts, date, rev, company)
        self._write_project(outdir)

    # ---------------------------------------------------------------- helpers
    def _title_block(self, title, date, rev, company, comments=()):
        tb = ["title_block", ["title", Q(title)], ["date", Q(date)], ["rev", Q(rev)], ["company", Q(company)]]
        for i, c in enumerate(comments):
            tb.append(["comment", str(i + 1), Q(c)])
        return tb

    def _effects(self, size=FONT, justify=None, hide=False, bold=False):
        font = ["font", ["size", size, size]]
        if bold:
            font.append("bold")
        e = ["effects", font]
        if justify:
            e.append(["justify"] + justify.split())
        if hide:
            e.append("hide")
        return e

    def _prop(self, key, val, x, y, ang=0, justify=None, hide=False, size=FONT):
        return ["property", Q(key), Q(val), ["at", x, y, ang], self._effects(size, justify, hide)]

    def _symbol_inst(self, p, path):
        node = ["symbol", ["lib_id", Q(p.lib_id)], ["at", p.x, p.y, p.rot]] + \
            ([["mirror", p.mirror]] if p.mirror else []) + [["unit", p.unit],
                ["in_bom", "no" if p.is_power else "yes"], ["on_board", "no" if p.is_power else "yes"],
                ["dnp", "yes" if p.dnp else "no"], ["uuid", Q(p.uuid)]]
        bx0, by0, bx1, by1 = p.screen_bbox()
        npins = len([q for q in p.unit_pins()])
        fa = 90 if p.rot in (90, 270) else 0      # field angle is relative to the symbol
        if p.fpos and not p.is_power:
            dx, dy, jj = p.fpos
            if (p.rot + fa) % 360 == 180:
                jj = {"left": "right", "right": "left"}.get(jj, jj)
            node.append(self._prop("Reference", p.ref, round(p.x + dx, 3), round(p.y + dy, 3), fa, jj))
            node.append(self._prop("Value", p.value, round(p.x + dx, 3), round(p.y + dy + 2.54, 3), fa, jj))
        elif p.is_power:
            o = (0, 1) if (p.value.startswith("GND") or p.lib_id in self.sym_alias.values()) else (0, -1)
            rx, ry = rot_vec(o[0], -o[1], p.rot)
            o = (round(rx), round(-ry))
            vx, vy = p.x + o[0] * 3.81, p.y + o[1] * 3.81
            if o[0] != 0:
                vx, vy = p.x + o[0] * 4.6, p.y
            node.append(self._prop("Reference", p.ref, p.x, p.y, fa, hide=True))
            node.append(self._prop("Value", p.value, round(vx, 3), round(vy, 3), fa))
        elif npins <= 3 and (bx1 - bx0) < (by1 - by0) and (bx1 - bx0) <= 5.2:
            xr = snap(bx1 + 1.27)
            j = "left" if (p.rot + fa) % 360 == 0 else "right"
            node.append(self._prop("Reference", p.ref, xr, round(p.y - 1.27, 3), fa, j))
            node.append(self._prop("Value", p.value, xr, round(p.y + 1.27, 3), fa, j))
        elif npins <= 3 and (by1 - by0) <= 5.2:
            node.append(self._prop("Reference", p.ref, p.x, round(by0 - 1.27, 3), fa))
            node.append(self._prop("Value", p.value, p.x, round(by1 + 2.2, 3), fa))
        elif p.rot != 0:
            cx = round((bx0 + bx1) / 2, 3)
            node.append(self._prop("Reference", p.ref, cx, round(by0 - 1.9, 3), fa))
            node.append(self._prop("Value", p.value, cx, round(by1 + 2.5, 3), fa))
        else:
            node.append(self._prop("Reference", p.ref, round(bx0, 3), round(by0 - 1.27, 3), 0, "left"))
            node.append(self._prop("Value", p.value, round(bx0, 3), round(by1 + 1.9, 3), 0, "left"))
        for k, v in p.fields.items():
            node.append(self._prop(k, v, p.x, p.y, 0, hide=True))
        for q in p.allpins:
            if q["unit"] in (0, p.unit):
                node.append(["pin", Q(q["number"]), ["uuid", Q(uid())]])
        node.append(["instances", ["project", Q(self.name), ["path", Q(path), ["reference", Q(p.ref)], ["unit", p.unit]]]])
        return node

    def _power_part(self, sh, net, x, y, out, counter):
        if net.startswith(SYM):
            net = net[len(SYM):]
            lib_id, natural = self.sym_alias[net], (0, 1)
        else:
            lib_id = POWER_SYMS[net]
            natural = POWER_NATURAL.get(net, (0, -1))
        # rotation that maps natural direction to `out`
        ang_nat = math.degrees(math.atan2(-natural[1], natural[0]))
        ang_out = math.degrees(math.atan2(-out[1], out[0]))
        rot = round(ang_out - ang_nat) % 360
        ref = "#PWR%04d" % counter
        p = Part(sh, lib_id, ref, net, (x, y), rot, 1, {"Footprint": "", "Datasheet": ""}, False, self.extra_lib)
        return p

    def _write_sheet(self, sh, path, date, rev, company):
        sheetpath = f"/{self.root_uuid}/{sh.uuid}"
        items = []
        lib_ids = {}
        extra_parts = []
        counter = [getattr(self, "_pwr_counter", 1)]
        segs = []            # (x1, y1, x2, y2)
        pin_pts = []
        bboxes = []
        for p in sh.parts:
            bboxes.append((p, p.screen_bbox()))
            for q in p.unit_pins():
                pr = p.pin(q["number"])
                pin_pts.append((round(pr.x, 3), round(pr.y, 3)))
        pinset = set(pin_pts)

        def seg(p1, p2):
            p1 = (round(p1[0], 3), round(p1[1], 3)); p2 = (round(p2[0], 3), round(p2[1], 3))
            if p1 != p2:
                segs.append(p1 + p2)

        def put_label(net, x, y, out):
            if net in POWER_SYMS or net.startswith(SYM):
                pp = self._power_part(sh, net, x, y, out, counter[0])
                counter[0] += 1
                extra_parts.append(pp)
                return
            ang = {(1, 0): 0, (-1, 0): 180, (0, -1): 90, (0, 1): 270}[out]
            if net in self.global_nets:
                just = "left" if ang in (0, 90) else "right"
                items.append(["global_label", Q(net), ["shape", "bidirectional"], ["at", x, y, ang],
                              ["fields_autoplaced"], self._effects(FONT, just), ["uuid", Q(uid())],
                              ["property", Q("Intersheetrefs"), Q("${INTERSHEET_REFS}"), ["at", x, y, 0],
                               self._effects(FONT, None, hide=True)]])
            else:
                just = ("left" if ang in (0, 90) else "right") + " bottom"
                items.append(["label", Q(net), ["at", x, y, ang], ["fields_autoplaced"],
                              self._effects(FONT, just), ["uuid", Q(uid())]])

        # explicit links
        linked = set()
        for a_, b_, net, via in sh.links:
            pts = [a_.pos]
            if a_.x != b_.x and a_.y != b_.y:
                if via == "v" or (via is None and a_.out[0] == 0):
                    pts.append((a_.x, b_.y))
                else:
                    pts.append((b_.x, a_.y))
            pts.append(b_.pos)
            for p1, p2 in zip(pts, pts[1:]):
                seg(p1, p2)
            linked.add((round(a_.x, 3), round(a_.y, 3))); linked.add((round(b_.x, 3), round(b_.y, 3)))

        for net, orient, c, pins, label, ext, tap in sh.rails:
            if net in getattr(sh, "sym_nets", ()):
                net = SYM + net
            # work in (u = along, v = across) coordinates; h: u=x, v=y ; v: u=y, v=x
            def P(u, v):
                return (u, v) if orient == "h" else (v, u)
            us = []
            for pr in pins:
                pos = pr.pos if isinstance(pr, PinRef) else (round(pr[0], 3), round(pr[1], 3))
                pu, pv = pos if orient == "h" else (pos[1], pos[0])
                if abs(pv - c) > 1e-3:
                    if not isinstance(pr, PinRef):
                        raise ValueError(f"rail {net}: point {pr} not on the rail")
                    seg(pos, P(pu, c))
                us.append(round(pu, 3))
            pts = sorted(set(us))
            if label in ("left", "top"):
                pts = [round(pts[0] - ext, 3)] + pts
            elif label in ("right", "bottom"):
                pts = pts + [round(pts[-1] + ext, 3)]
            if tap:
                pts = sorted(set(pts + [round(tap[0], 3)]))
            for a_u, b_u in zip(pts, pts[1:]):
                seg(P(a_u, c), P(b_u, c))
            if tap:
                tu, td = tap
                tp = P(tu, c)
                te = (round(tp[0] + td[0] * STUB, 3), round(tp[1] + td[1] * STUB, 3))
                seg(tp, te)
                put_label(net, te[0], te[1], td)
            if label in ("left", "top"):
                put_label(net, *P(pts[0], c), (-1, 0) if orient == "h" else (0, -1))
            elif label in ("right", "bottom"):
                put_label(net, *P(pts[-1], c), (1, 0) if orient == "h" else (0, 1))
            for pr in pins:
                if isinstance(pr, PinRef):
                    linked.add((round(pr.x, 3), round(pr.y, 3)))

        for net, pitems in sh.paths:
            pts = [it.pos if isinstance(it, PinRef) else it for it in pitems]
            for p1, p2 in zip(pts, pts[1:]):
                if p1[0] != p2[0] and p1[1] != p2[1]:
                    raise ValueError(f"path {net}: diagonal segment {p1} -> {p2}")
                seg(p1, p2)
            for it in pitems:
                if isinstance(it, PinRef):
                    linked.add((round(it.x, 3), round(it.y, 3)))

        # unique label requests by position
        reqs, seen = [], set()
        for pr, net, label in sh.conns:
            key = (round(pr.x, 3), round(pr.y, 3))
            if not label or (key, net) in seen:
                continue
            seen.add((key, net))
            sym = label == "sym" or net in getattr(sh, "sym_nets", ())
            reqs.append((pr, SYM + net if sym else net))
        stub_end = {id(r[0]): (r[0].x + r[0].out[0] * STUB, r[0].y + r[0].out[1] * STUB) for r in reqs}
        local_count = {}
        for pr, net in reqs:
            local_count[net] = local_count.get(net, 0) + 1

        def clear(p1, p2, skip_parts, own_pts=()):
            x1, y1, x2, y2 = min(p1[0], p2[0]), min(p1[1], p2[1]), max(p1[0], p2[0]), max(p1[1], p2[1])
            for part, (bx0, by0, bx1, by1) in bboxes:
                if part in skip_parts:
                    continue
                if x1 == x2:
                    if bx0 - 0.3 < x1 < bx1 + 0.3 and max(y1, by0) < min(y2, by1):
                        return False
                else:
                    if by0 - 0.3 < y1 < by1 + 0.3 and max(x1, bx0) < min(x2, bx1):
                        return False
            for (sx1, sy1, sx2, sy2) in segs:
                if x1 == x2 and sx1 == sx2 == x1 and max(y1, min(sy1, sy2)) < min(y2, max(sy1, sy2)):
                    return False
                if y1 == y2 and sy1 == sy2 == y1 and max(x1, min(sx1, sx2)) < min(x2, max(sx1, sx2)):
                    return False
            own = {tuple(map(lambda v: round(v, 3), p)) for p in own_pts}
            for (px, py) in pin_pts + [(round(e[0], 3), round(e[1], 3)) for e in stub_end.values()]:
                if (px, py) in own:
                    continue
                if x1 - 0.01 <= px <= x2 + 0.01 and y1 - 0.01 <= py <= y2 + 0.01:
                    return False
            return True

        def free_box(x0, y0, x1, y1):
            for part, (bx0, by0, bx1, by1) in bboxes:
                if max(x0, bx0) < min(x1, bx1) and max(y0, by0) < min(y1, by1):
                    return False
            return True

        # facing pairs -> wire + one tap label at the midpoint
        used = set()
        cands = []
        for i, (pa, na) in enumerate(reqs):
            if na in POWER_SYMS or na.startswith(SYM):
                continue
            for j, (pb, nb) in enumerate(reqs):
                if i == j or na != nb or pa.part is pb.part:
                    continue
                if pa.out == (0, 1) and pb.out == (0, -1) and abs(pa.x - pb.x) < 1e-3 and pb.y > pa.y:
                    d = pb.y - pa.y
                elif pa.out == (1, 0) and pb.out == (-1, 0) and abs(pa.y - pb.y) < 1e-3 and pb.x > pa.x:
                    d = pb.x - pa.x
                else:
                    continue
                own = [pa.pos, pb.pos, stub_end[id(pa)], stub_end[id(pb)]]
                if 2.5 <= d <= 30 and clear(pa.pos, pb.pos, {pa.part, pb.part}, own):
                    cands.append((d, i, j))
        cands.sort()
        pairs = []
        for d, i, j in cands:
            if i in used or j in used:
                continue
            used.add(i); used.add(j)
            pairs.append((i, j))
        for i, j in pairs:
            pa, net = reqs[i]; pb, _ = reqs[j]
            need = (net in self.global_nets) or local_count[net] > 2 or \
                any(net == n for (x, y, n, *_r) in []) or \
                ((round(pa.x, 3), round(pa.y, 3)) in linked) or ((round(pb.x, 3), round(pb.y, 3)) in linked)
            # local net used elsewhere on this sheet through explicit links also needs the label
            vertical = abs(pa.x - pb.x) < 1e-3
            if vertical:
                mid = (pa.x, snap((pa.y + pb.y) / 2))
            else:
                mid = (snap((pa.x + pb.x) / 2), pa.y)
            if not need:
                seg(pa.pos, pb.pos)
                continue
            seg(pa.pos, mid); seg(mid, pb.pos)
            L = len(net) * 1.05 + 4
            if vertical:
                opts = [((1, 0), (mid[0] + 2.54, mid[1] - 1.5, mid[0] + 2.54 + L, mid[1] + 1.5)),
                        ((-1, 0), (mid[0] - 2.54 - L, mid[1] - 1.5, mid[0] - 2.54, mid[1] + 1.5))]
            else:
                opts = [((0, -1), (mid[0] - 1.5, mid[1] - 2.54 - L, mid[0] + 1.5, mid[1] - 2.54)),
                        ((0, 1), (mid[0] - 1.5, mid[1] + 2.54, mid[0] + 1.5, mid[1] + 2.54 + L))]
            out = next((o for o, bx in opts if free_box(*bx)), opts[0][0])
            end = (round(mid[0] + out[0] * STUB, 3), round(mid[1] + out[1] * STUB, 3))
            seg(mid, end)
            put_label(net, end[0], end[1], out)

        # combs: same-net neighbours in a row, same outward direction
        rest = [k for k in range(len(reqs)) if k not in used]
        groups = {}
        for k in rest:
            pr, net = reqs[k]
            key = (net, pr.out, round(pr.y, 3) if pr.out[1] == 0 and False else (round(pr.y, 3) if pr.out[0] == 0 else round(pr.x, 3)))
            groups.setdefault(key, []).append(k)
        combed = set()
        for (net, out, line), ks in groups.items():
            if len(ks) < 2:
                continue
            along = 0 if out[0] == 0 else 1          # coordinate that varies along the row
            ks.sort(key=lambda k: reqs[k][0].pos[along])
            runs, cur = [], [ks[0]]
            for k in ks[1:]:
                prev = reqs[cur[-1]][0].pos[along]
                here = reqs[k][0].pos[along]
                between = [r for r in reqs if r[1] != net and abs(r[0].pos[1 - along] - line) < 1e-3
                           and r[0].out == out and prev < r[0].pos[along] < here]
                if here - prev <= 5.09 and not between:
                    cur.append(k)
                else:
                    runs.append(cur); cur = [k]
            runs.append(cur)
            for run in runs:
                if len(run) < 2:
                    continue
                ends = []
                for k in run:
                    pr = reqs[k][0]
                    e = (round(pr.x + out[0] * STUB, 3), round(pr.y + out[1] * STUB, 3))
                    seg(pr.pos, e)
                    ends.append(e)
                    combed.add(k)
                for e1, e2 in zip(ends, ends[1:]):
                    seg(e1, e2)
                m = ends[len(ends) // 2]
                put_label(net, m[0], m[1], out)

        # plain stubs
        for k in rest:
            if k in combed:
                continue
            pr, net = reqs[k]
            e = (round(pr.x + pr.out[0] * STUB, 3), round(pr.y + pr.out[1] * STUB, 3))
            seg(pr.pos, e)
            put_label(net, e[0], e[1], pr.out)

        # layout lint: wires through part bodies, pins touching a wire mid-span
        lint = getattr(self, "lint", [])
        for (x1, y1, x2, y2) in segs:
            lx0, ly0, lx1, ly1 = min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)
            for part, (bx0, by0, bx1, by1) in bboxes:
                if part.lib_id == "power:PWR_FLAG":
                    continue
                own = {(round(q.x, 3), round(q.y, 3)) for q in (part.pin(pp["number"]) for pp in part.unit_pins())}
                if (x1, y1) in own or (x2, y2) in own:
                    continue
                m = 0.6
                if max(lx0, bx0 + m) < min(lx1, bx1 - m) + (1e-6 if lx0 == lx1 else 0) and \
                        max(ly0, by0 + m) < min(ly1, by1 - m) + (1e-6 if ly0 == ly1 else 0):
                    if (bx0 + m) <= lx0 <= (bx1 - m) or (by0 + m) <= ly0 <= (by1 - m):
                        lint.append(f"{sh.name}: wire ({x1},{y1})-({x2},{y2}) crosses {part.ref}")
            for (px, py) in pin_pts:
                if (px, py) in ((x1, y1), (x2, y2)):
                    continue
                if lx0 - 1e-3 <= px <= lx1 + 1e-3 and ly0 - 1e-3 <= py <= ly1 + 1e-3:
                    lint.append(f"{sh.name}: pin at ({px},{py}) touches wire ({x1},{y1})-({x2},{y2}) mid-span")
        self.lint = lint
        for (x1, y1, x2, y2) in segs:
            items.append(["wire", ["pts", ["xy", x1, y1], ["xy", x2, y2]],
                          ["stroke", ["width", 0], ["type", "default"]], ["uuid", Q(uid())]])
        # junctions: >= 3 connection items meeting at a point
        cnt = {}
        for (x1, y1, x2, y2) in segs:
            for pt in ((x1, y1), (x2, y2)):
                cnt[pt] = cnt.get(pt, 0) + 1
        for pt in pinset:
            if pt in cnt:
                cnt[pt] += 1
        for pp in extra_parts:
            k = (round(pp.x, 3), round(pp.y, 3))
            if k in cnt:
                cnt[k] += 1
        for k, n in cnt.items():
            if n >= 3:
                items.append(["junction", ["at", k[0], k[1]], ["diameter", 0], ["color", 0, 0, 0, 0], ["uuid", Q(uid())]])
        self._pwr_counter = counter[0]
        for pr in sh.ncs:
            items.append(["no_connect", ["at", pr.x, pr.y], ["uuid", Q(uid())]])
        for (s, x, y, size, bold) in sh.texts:
            items.append(["text", Q(s), ["at", x, y, 0], self._effects(size, "left bottom", bold=bold), ["uuid", Q(uid())]])
        for (x0, y0, x1, y1) in sh.rects:
            items.append(["rectangle", ["start", x0, y0], ["end", x1, y1],
                          ["stroke", ["width", 0], ["type", "dash"]], ["fill", ["type", "none"]], ["uuid", Q(uid())]])
        allparts = sh.parts + extra_parts
        for p in allparts:
            lib_ids[p.lib_id] = p.sym
        syms = [self._symbol_inst(p, sheetpath) for p in allparts]
        root = ["kicad_sch", ["version", "20230121"], ["generator", "eeschema"], ["uuid", Q(sh.uuid)],
                ["paper", Q(sh.paper)], self._title_block(sh.title, date, rev, company, (self.name,)),
                ["lib_symbols"] + [copy.deepcopy(s) for s in lib_ids.values()]]
        root += items + syms
        with open(path, "w", encoding="utf-8") as f:
            f.write(dump(root) + "\n")

    def _write_root(self, path, title, texts, date, rev, company):
        items = []
        x0, y0, w, h, gap = 30.48, 50.8, 76.2, 30.48, 12.7
        for i, sh in enumerate(self.sheets):
            col, row = i % 4, i // 4
            x, y = x0 + col * (w + 20.32), y0 + row * (h + 25.4)
            items.append(["sheet", ["at", x, y], ["size", w, h], ["fields_autoplaced"],
                          ["stroke", ["width", 0.1524], ["type", "solid"]], ["fill", ["color", 0, 0, 0, 0.0]],
                          ["uuid", Q(sh.uuid)],
                          ["property", Q("Sheetname"), Q(sh.title), ["at", x, round(y - 0.7, 3), 0],
                           self._effects(FONT, "left bottom")],
                          ["property", Q("Sheetfile"), Q(sh.filename), ["at", x, round(y + h + 0.6, 3), 0],
                           self._effects(FONT, "left top")],
                          ["instances", ["project", Q(self.name), ["path", Q("/" + self.root_uuid), ["page", Q(sh.page)]]]]])
            if getattr(sh, "desc", None):
                items.append(["text", Q("\n".join(sh.desc)), ["at", round(x + 2.54, 3), snap(y + 5.08 + (len(sh.desc) - 1) * 2.1), 0],
                              self._effects(FONT, "left bottom"), ["uuid", Q(uid())]])
        for (s, x, y, size, bold) in texts:
            items.append(["text", Q(s), ["at", x, y, 0], self._effects(size, "left bottom", bold=bold), ["uuid", Q(uid())]])
        root = ["kicad_sch", ["version", "20230121"], ["generator", "eeschema"], ["uuid", Q(self.root_uuid)],
                ["paper", Q("A3")], self._title_block(title, date, rev, company), ["lib_symbols"]]
        root += items
        root.append(["sheet_instances", ["path", Q("/"), ["page", Q("1")]]])
        with open(path, "w", encoding="utf-8") as f:
            f.write(dump(root) + "\n")

    def _write_project(self, outdir):
        import json, os
        pro = {"meta": {"filename": self.name + ".kicad_pro", "version": 1},
               "schematic": {"legacy_lib_dir": "", "legacy_lib_list": []},
               "sheets": [[self.root_uuid, "Root"]] + [[s.uuid, s.title] for s in self.sheets]}
        with open(os.path.join(outdir, self.name + ".kicad_pro"), "w") as f:
            json.dump(pro, f, indent=2)
