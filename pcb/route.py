"""Autoroute with Freerouting: export DSN (with net classes), run Freerouting headless, import the SES."""
import os
import re
import subprocess
import time

import pcbnew

import copper
import place
from sexp import parse

HERE = os.path.dirname(os.path.abspath(__file__))
JAR = os.path.join(HERE, "..", "tools", "freerouting.jar")


def _q(n):
    return f'"{n}"' if re.search(r'[\s()"{}]', n) or n == "" else n


def _close(s, start):
    """Index of the ')' matching the '(' at start (quotes respected)."""
    depth, q = 0, False
    for k in range(start, len(s)):
        c = s[k]
        if c == '"':
            q = not q
        elif not q and c == "(":
            depth += 1
        elif not q and c == ")":
            depth -= 1
            if depth == 0:
                return k
    raise ValueError("unbalanced")


def export_dsn(board, path, erode=0.45):
    assert pcbnew.ExportSpecctraDSN(board, path)
    fix_classes(path)
    add_pour_keepouts(board, path, erode)


def add_pour_keepouts(board, path, erode):
    """Freerouting reads KiCad zones as conduction areas that never block other nets, so signal traces
    would cut straight through the power pours. Add a keepout for the core of every pour on a routing
    layer; the pour's own net can still attach to its edge."""
    from shapely.geometry import Polygon
    import copper
    s = open(path).read()
    out = []
    for z in board.Zones():
        L = z.GetLayer()
        if L not in (pcbnew.F_Cu, pcbnew.B_Cu) or z.GetIsRuleArea():
            continue
        ol = z.Outline()
        for i in range(ol.OutlineCount()):
            o = ol.Outline(i)
            pts = [copper.from_abs(o.CPoint(k)) for k in range(o.PointCount())]
            g = Polygon(pts).buffer(-erode, join_style=2)
            for q in ([g] if g.geom_type == "Polygon" else list(getattr(g, "geoms", []))):
                if q.is_empty or q.area < 0.5:
                    continue
                q = q.simplify(0.02)
                xy = " ".join(f"{(x + place.BX0) * 1000:.1f} {-(y + place.BY0) * 1000:.1f}" for x, y in list(q.exterior.coords))
                lname = board.GetLayerName(L)
                out.append(f'    (keepout "" (polygon {lname} 0  {xy}))\n')
    i = s.index("(structure")
    k = _close(s, i)
    s = s[:k] + "".join(out) + "  " + s[k:]
    open(path, "w").write(s)


def fix_classes(path):
    """KiCad 7 exports every net into kicad_default when the board has no project; rewrite the class blocks."""
    s = open(path).read()
    i = s.index("(class kicad_default")
    j = s.index("(wiring") if "(wiring" in s else s.rindex(")")
    # end of the network section = last ')' before wiring
    head = s[:i]
    tail = s[j:]
    members = {}
    assign = {}
    for cls, nets in (("HighCurrent", copper.HIGH), ("Power", copper.POWER), ("USB", copper.USB)):
        for n in nets:
            assign[n] = cls
    # collect all net names from the network section
    netnames = re.findall(r'\(net ("(?:[^"\\]|\\.)*"|\S+)\n', s[:i])
    allnets = [n.strip('"') for n in netnames]
    for n in allnets:
        members.setdefault(assign.get(n, "kicad_default"), []).append(n)
    out = []
    for cls in ("kicad_default", "HighCurrent", "Power", "USB"):
        c = copper.NETCLASSES["Default" if cls == "kicad_default" else cls]
        names = " ".join(_q(n) for n in members.get(cls, []))
        out.append(f'    (class {cls} {names}\n      (circuit\n        (use_via Via[0-3]_600:300_um)\n      )\n'
                   f'      (rule\n        (width {c["track"] * 1000:.0f})\n        (clearance {c["clr"] * 1000 + 8:.1f})\n'
                   f'      )\n    )\n')
    # end of the old class list = the ')' that closes (network
    k = _close(s, s.rindex("(network", 0, i))
    new = head + "".join(out) + "  " + s[k:]
    new = new.replace("(clearance 150.1)", "(clearance 158)").replace("(clearance 150.1 (type default_smd))",
                                                                       "(clearance 158 (type default_smd))")
    open(path, "w").write(new)


def keep_nets(path, out, nets):
    """Write a copy of a DSN whose network only contains the given nets (the other pins stay as obstacles)."""
    s = open(path).read()
    i = s.index("(network")
    k = _close(s, i)
    body = s[i:k + 1]
    pos = len("(network")
    parts = []
    j = pos
    while True:
        a = body.find("(", j)
        if a < 0:
            break
        b = _close(body, a)
        item = body[a:b + 1]
        head = item[1:].split(None, 1)[0]
        if head == "net":
            name = item[5:].strip()
            name = name[1:name.index('"', 1)] if name.startswith('"') else name.split()[0]
            # nets that are not routed in this stage keep their name (their wiring and planes still
            # reference it) but lose their pins, so Freerouting has nothing to connect
            parts.append(item if name in nets else f"(net {_q(name)})")
        elif head == "class":
            toks = re.findall(r'"(?:[^"\\]|\\.)*"|[^\s()]+', item.split("(circuit")[0])
            cname = toks[1]
            members = [t.strip('"') for t in toks[2:]]
            members = members
            rest = item[item.index("(circuit"):]
            parts.append(f"(class {cname} " + " ".join(_q(m) for m in members) + "\n      " + rest)
        else:
            parts.append(item)
        j = b + 1
    new = s[:i] + "(network\n    " + "\n    ".join(parts) + "\n  )" + s[k + 1:]
    open(out, "w").write(new)


def run_freerouting(dsn, ses, minutes=14, log=None, via_cost=12):
    """Freerouting 2.1 ignores -mp in batch mode, so the run is bounded by the job timeout instead
    (it keeps the best board found and writes the SES when the time is up)."""
    cmd = ["java", "-Xmx3g", "-jar", JAR, "-de", dsn, "-do", ses, "--gui.enabled=false",
           f"--router.job_timeout=00:{minutes:02d}:00", "--router.optimizer.max_passes=0",
           f"--router.scoring.via_costs={via_cost}", "--router.scoring.plane_via_costs=3",
           "--router.scoring.start_ripup_costs=50", "--usage_and_diagnostic_data.disable_analytics=true"]
    t0 = time.time()
    if os.path.exists(ses):
        os.remove(ses)
    with open(log or os.devnull, "w") as lf:
        p = subprocess.run(cmd, stdout=lf, stderr=subprocess.STDOUT, timeout=minutes * 60 + 600)
    return p.returncode, time.time() - t0


def import_ses(board, ses, log=print):
    t = parse(open(ses).read())
    routes = None
    for it in t[1:]:
        if isinstance(it, list) and it and str(it[0]) == "routes":
            routes = it
    res = 1.0
    for it in routes[1:]:
        if isinstance(it, list) and str(it[0]) == "resolution":
            res = float(it[2])
    scale = 1000.0 / res      # SES unit -> nm  (um / res)
    padstacks = {}
    nets = None
    for it in routes[1:]:
        if isinstance(it, list) and str(it[0]) == "library_out":
            for ps in it[1:]:
                if isinstance(ps, list) and str(ps[0]) == "padstack":
                    name = str(ps[1])
                    m = re.search(r"_(\d+):(\d+)_um", name)
                    padstacks[name] = (int(m.group(1)), int(m.group(2))) if m else (600, 300)
        if isinstance(it, list) and str(it[0]) == "network_out":
            nets = it
    layers = {"F.Cu": pcbnew.F_Cu, "In1.Cu": pcbnew.In1_Cu, "In2.Cu": pcbnew.In2_Cu, "B.Cu": pcbnew.B_Cu}
    nt = nv = 0
    # the SES carries every wire and via; keep the locked (fixed) ones, replace the rest
    rm = [t for t in board.GetTracks() if not t.IsLocked()]
    for t in rm:
        board.Delete(t)
    del rm
    G = 20000   # 20 um matching grid
    have_v = set()
    have_t = set()
    for t in board.GetTracks():
        if isinstance(t, pcbnew.PCB_VIA):
            p = t.GetPosition()
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    have_v.add((round(p.x / G) + dx, round(p.y / G) + dy))
        else:
            a, b = t.GetStart(), t.GetEnd()
            ka = (round(a.x / G), round(a.y / G)); kb = (round(b.x / G), round(b.y / G))
            have_t.add((t.GetLayer(), ka, kb)); have_t.add((t.GetLayer(), kb, ka))
    for net in nets[1:]:
        name = str(net[1])
        ni = board.FindNet(name)
        if ni is None:
            log("unknown net " + name)
            continue
        for w in net[2:]:
            if not isinstance(w, list):
                continue
            kind = str(w[0])
            if kind == "wire":
                path = [x for x in w[1:] if isinstance(x, list) and str(x[0]) == "path"][0]
                layer = layers[str(path[1])]
                width = int(round(float(path[2]) * scale))
                xy = [float(v) for v in path[3:]]
                pts = [pcbnew.VECTOR2I(int(round(xy[k] * scale)), int(round(-xy[k + 1] * scale)))
                       for k in range(0, len(xy), 2)]
                for a, b in zip(pts, pts[1:]):
                    if a == b:
                        continue
                    if (layer, (round(a.x / G), round(a.y / G)), (round(b.x / G), round(b.y / G))) in have_t:
                        continue
                    tr = pcbnew.PCB_TRACK(board)
                    tr.SetStart(a); tr.SetEnd(b); tr.SetWidth(width); tr.SetLayer(layer); tr.SetNet(ni)
                    board.Add(tr)
                    nt += 1
            elif kind == "via":
                d, drill = padstacks.get(str(w[1]), (600, 300))
                x, y = float(w[2]) * scale, -float(w[3]) * scale
                if (round(x / G), round(y / G)) in have_v:
                    continue
                v = pcbnew.PCB_VIA(board)
                v.SetPosition(pcbnew.VECTOR2I(int(round(x)), int(round(y))))
                v.SetWidth(pcbnew.FromMM(d / 1000)); v.SetDrill(pcbnew.FromMM(drill / 1000))
                v.SetViaType(pcbnew.VIATYPE_THROUGH); v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu); v.SetNet(ni)
                board.Add(v)
                nv += 1
    log(f"imported {nt} track segments, {nv} vias")
    return nt, nv
