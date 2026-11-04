"""Full stability matrices for the as-drawn and the proposed compensation -> results/*.csv"""
import csv
import itertools
import os
import sys
from concurrent.futures import ProcessPoolExecutor

import epsu_analog as E
import loop

HERE = os.path.dirname(os.path.abspath(__file__))
LOADS = {"3A": [None, 0.1, 1.0, 3.0], "30mA": [None, 1e-3, 30e-3], "300uA": [None, 30e-6, 300e-6]}
VOUTS = [1.0, 12.0, 24.0]
CLOADS = [0.0, 1e-6, 10e-6, 100e-6, 1e-3]


def cv_cases(fets=("IRFP260N",)):
    for fet, vout, (rng, loads), cl in itertools.product(fets, VOUTS, LOADS.items(), CLOADS):
        for il in loads:
            yield dict(fet=fet, vout=vout, rng=rng, iload=il or 0.0, cload=cl,
                       kw=dict(vout=vout, rng=rng, load=("R", vout / il) if il else None, cload=cl, esr=0.05, fet=fet))


def cc_cases(fets=("IRFP260N",)):
    for fet, ilim, frac, cl in itertools.product(fets, [0.03, 0.1, 1.0, 3.0], [0.0, 0.5], [0.0, 10e-6, 1e-3]):
        vcc = 12.0 * frac
        rl = max(vcc / ilim, 0.1) if frac else 0.1
        yield dict(fet=fet, vout=12.0, rng="3A", ilim=ilim, rload=rl, cload=cl,
                   kw=dict(vout=12.0, ilim=ilim, rng="3A", load=("R", rl), cload=cl, esr=0.05, fet=fet))


def _run(args):
    i, case, comp, label = args
    try:
        r = loop.loop_gain(f"{label}_{i}", comp=comp, **case["kw"])
        return dict(case, mode=r["mode"], fc=r["fc"], pm=r["pm"], gm=r["gm"], vout_meas=r["vout"], err="")
    except Exception as ex:   # noqa
        return dict(case, mode="ERR", fc=None, pm=None, gm=None, vout_meas=None, err=str(ex)[:100])


def run(cases, comp, label, workers=2):
    jobs = [(i, c, comp, label) for i, c in enumerate(cases)]
    with ProcessPoolExecutor(workers) as ex:
        rows = list(ex.map(_run, jobs))
    path = os.path.join(HERE, "results", f"{label}.csv")
    keys = [k for k in rows[0] if k != "kw"]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow({k: r[k] for k in keys})
    return rows


if __name__ == "__main__":
    which = sys.argv[1:] or ["cv_asdrawn", "cv_proposed", "cc_asdrawn", "cc_proposed"]
    for lab in which:
        kind, design = lab.split("_")
        comp = {} if design == "asdrawn" else E.PROPOSED
        fets = ("IRFP260N",) if design == "asdrawn" else ("IRFP260N", "IRFP260NW")
        cases = list(cv_cases(fets) if kind == "cv" else cc_cases(fets))
        rows = run(cases, comp, lab)
        pms = [r["pm"] for r in rows if r["pm"] is not None]
        errs = [r for r in rows if r["mode"] == "ERR"]
        print(f"{lab}: {len(rows)} cases, {len(errs)} errors, worst PM {min(pms):.1f}, "
              f"PM<45: {sum(p < 45 for p in pms)}, PM<0: {sum(p < 0 for p in pms)}")
        for r in errs[:5]:
            print("   ERR", r["vout"], r["rng"], r.get("iload"), r["cload"], r["err"])
