"""Corner-case stability evaluation for a compensation candidate (parallel)."""
import json
import sys
from concurrent.futures import ProcessPoolExecutor

import loop

ESR = 0.05
CV_CORNERS = [
    ("3A 3A load", dict(vout=12, rng="3A", load=("R", 4.0))),
    ("3A 1A", dict(vout=12, rng="3A", load=("R", 12.0))),
    ("3A no load", dict(vout=12, rng="3A", load=None)),
    ("3A no load 1000uF", dict(vout=12, rng="3A", load=None, cload=1e-3)),
    ("3A 1A 1000uF", dict(vout=12, rng="3A", load=("R", 12.0), cload=1e-3)),
    ("3A 0.1A 10uF", dict(vout=12, rng="3A", load=("R", 120.0), cload=10e-6)),
    ("30mA 10mA 10uF", dict(vout=12, rng="30mA", load=("R", 1200.0), cload=10e-6)),
    ("300uA 100uA 100uF", dict(vout=12, rng="300uA", load=("R", 120e3), cload=100e-6)),
    ("300uA no load", dict(vout=12, rng="300uA", load=None)),
    ("1V 3A 1A", dict(vout=1, rng="3A", load=("R", 1.0))),
    ("24V 3A 3A", dict(vout=24, rng="3A", load=("R", 8.0))),
    ("3A 1A weakFET", dict(vout=12, rng="3A", load=("R", 12.0), fet="IRFP260NW")),
    ("3A no load weakFET", dict(vout=12, rng="3A", load=None, fet="IRFP260NW")),
]
CC_CORNERS = [
    ("CC 3A short", dict(vout=12, ilim=3.0, rng="3A", load=("R", 0.1))),
    ("CC 1A 5R", dict(vout=12, ilim=1.0, rng="3A", load=("R", 5.0))),
    ("CC 1A 5R 100uF", dict(vout=12, ilim=1.0, rng="3A", load=("R", 5.0), cload=100e-6)),
    ("CC 20mA 100R", dict(vout=12, ilim=0.02, rng="3A", load=("R", 100.0))),
    ("CC 3A short weakFET", dict(vout=12, ilim=3.0, rng="3A", load=("R", 0.1), fet="IRFP260NW")),
]


def _one(args):
    name, kw, comp, tag = args
    kw = dict(kw)
    if kw.get("cload"):
        kw["esr"] = ESR
    try:
        r = loop.loop_gain(tag, comp=comp, **kw)
        return name, r["mode"], r["fc"], r["pm"], r["gm"], r["vout"]
    except Exception as ex:          # noqa
        return name, "ERR", None, None, None, str(ex)[:120]


def evaluate(comp, label, corners=None, workers=8):
    corners = corners or (CV_CORNERS + CC_CORNERS)
    jobs = [(n, kw, comp, f"{label}_{i}") for i, (n, kw) in enumerate(corners)]
    with ProcessPoolExecutor(workers) as ex:
        res = list(ex.map(_one, jobs))
    return res


def show(res, label):
    print(f"== {label}")
    worst = 999
    for name, mode, fc, pm, gm, vout in res:
        fcs = f"{fc/1e3:8.2f} kHz" if fc else "   (none)  "
        pms = f"{pm:6.1f}" if pm is not None else "   -  "
        print(f"  {name:24s} {mode:3s} fc {fcs} PM {pms}  vout {vout if isinstance(vout, str) else round(vout, 3)}")
        if pm is not None:
            worst = min(worst, pm)
    print(f"  worst PM {worst:.1f}")
    return worst


if __name__ == "__main__":
    comp = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    label = sys.argv[2] if len(sys.argv) > 2 else "asdrawn"
    show(evaluate(comp, label), label)
