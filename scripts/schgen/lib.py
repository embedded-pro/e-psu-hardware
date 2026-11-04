"""Load KiCad symbol libraries, flatten derived symbols, and list pins."""
import copy
import os
import re
from sexp import parse, find, findall, Q

SYM_DIRS = ["/usr/share/kicad/symbols"]
_cache = {}


def load_lib(path):
    if path not in _cache:
        with open(path, encoding="utf-8") as f:
            tree = parse(f.read())
        _cache[path] = {x[1]: x for x in findall(tree, "symbol")}
    return _cache[path]


def lib_path(libname, extra=None):
    if extra and libname in extra:
        return extra[libname]
    for d in SYM_DIRS:
        p = os.path.join(d, libname + ".kicad_sym")
        if os.path.exists(p):
            return p
    raise FileNotFoundError(libname)


def get_symbol(lib_id, extra=None):
    """Return a flattened symbol definition named lib_id (e.g. 'Device:R')."""
    libname, name = lib_id.split(":", 1)
    syms = load_lib(lib_path(libname, extra))
    if name not in syms:
        raise KeyError(lib_id)
    sym = copy.deepcopy(syms[name])
    ext = find(sym, "extends")
    if ext:
        parent = get_symbol(libname + ":" + ext[1], extra)
        pname = parent[1].split(":", 1)[1]
        # child keeps its own properties; graphics/pins come from parent
        props = findall(sym, "property")
        newsym = [x for x in parent if not (isinstance(x, list) and x and x[0] in ("property",))]
        newsym = [x for x in newsym]
        out = ["symbol", Q(lib_id)]
        for x in newsym[2:]:
            if isinstance(x, list) and x and x[0] == "symbol":
                sub = copy.deepcopy(x)
                sub[1] = Q(re.sub("^" + re.escape(pname), name, sub[1]))
                out.append(sub)
            else:
                out.append(x)
        # insert child's properties before sub-symbols
        idx = next((i for i, x in enumerate(out) if isinstance(x, list) and x and x[0] == "symbol"), len(out))
        out[idx:idx] = props
        sym = out
    sym[1] = Q(lib_id)
    return sym


def pins(sym):
    """List pins: dict(number, name, type, x, y, angle, length, unit)."""
    name = sym[1].split(":", 1)[1]
    res = []
    for sub in findall(sym, "symbol"):
        m = re.match(re.escape(name) + r"_(\d+)_(\d+)$", sub[1])
        unit = int(m.group(1)) if m else 0
        for p in findall(sub, "pin"):
            at = find(p, "at")
            nm = find(p, "name")
            nu = find(p, "number")
            hidden = "hide" in p
            res.append(dict(number=str(nu[1]), name=str(nm[1]), type=p[1], x=float(at[1]), y=float(at[2]),
                            angle=float(at[3]) if len(at) > 3 else 0.0, length=float(find(p, "length")[1]),
                            unit=unit, hidden=hidden))
    return res


def bbox(sym, unit=1):
    """Rough body bbox in lib coords (Y up) from rectangles/polylines/pins."""
    name = sym[1].split(":", 1)[1]
    xs, ys = [], []
    for sub in findall(sym, "symbol"):
        m = re.match(re.escape(name) + r"_(\d+)_(\d+)$", sub[1])
        u = int(m.group(1)) if m else 0
        if u not in (0, unit):
            continue
        for g in sub[2:]:
            if not isinstance(g, list):
                continue
            if g[0] == "rectangle":
                s, e = find(g, "start"), find(g, "end")
                xs += [float(s[1]), float(e[1])]; ys += [float(s[2]), float(e[2])]
            elif g[0] in ("polyline", "bezier"):
                for p in findall(find(g, "pts"), "xy"):
                    xs.append(float(p[1])); ys.append(float(p[2]))
            elif g[0] == "circle":
                c, r = find(g, "center"), float(find(g, "radius")[1])
                xs += [float(c[1]) - r, float(c[1]) + r]; ys += [float(c[2]) - r, float(c[2]) + r]
            elif g[0] == "arc":
                for k in ("start", "mid", "end"):
                    p = find(g, k)
                    xs.append(float(p[1])); ys.append(float(p[2]))
            elif g[0] == "pin":
                at = find(g, "at")
                xs.append(float(at[1])); ys.append(float(at[2]))
    if not xs:
        return (-1, -1, 1, 1)
    return (min(xs), min(ys), max(xs), max(ys))
