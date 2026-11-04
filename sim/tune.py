import sys, json, numpy as np
import corners as K, transients as T
EXTRA = [("30mA no load 1000uF", dict(vout=12, rng="30mA", load=None, cload=1e-3)),
         ("300uA no load 1000uF", dict(vout=12, rng="300uA", load=None, cload=1e-3)),
         ("300uA 100uA 1000uF", dict(vout=12, rng="300uA", load=("R", 120e3), cload=1e-3))]
def settle_metric(comp, lab):
    r = T.load_step("ls_" + lab, comp, "3A", 0.1, 1.0, t1=3e-3, tend=3e-3)
    t, v = r["scale"], r["v(outp)"]; final = 12 - 0.0536
    pts = {dt: 1e3 * (v[np.argmin(abs(t - (0.2e-3 + dt)))] - final) for dt in (50e-6, 0.2e-3, 1e-3, 2.5e-3)}
    return v[t > 0.2e-3].min(), pts
K.CV_CORNERS += [("1V no load", dict(vout=1, rng="3A", load=None)), ("1V no load 1000uF", dict(vout=1, rng="3A", load=None, cload=1e-3))]
cands = json.loads(open(sys.argv[1]).read())
for lab, comp in cands.items():
    res = K.evaluate(comp, lab, K.CV_CORNERS + EXTRA)
    pm = {n: (p, fc) for n, m, fc, p, g, vo in res}
    worst = min((p for p, fc in pm.values() if p is not None), default=None)
    vmin, pts = settle_metric(comp, lab)
    print(f"{lab}: worst PM {worst:.1f} | 3A1A fc {pm['3A 1A'][1]/1e3:.1f}k PM {pm['3A 1A'][0]:.0f} | noload fc {pm['3A no load'][1]/1e3:.2f}k PM {pm['3A no load'][0]:.0f} | "
          f"NL1000u PM {pm["3A no load 1000uF"][0]:.0f} 1V-NL1000u {pm["1V no load 1000uF"][0]:.0f} | 300uA1000u {pm['300uA no load 1000uF'][0]:.0f}/{pm['300uA 100uA 1000uF'][0]:.0f} | 30mA1000u {pm['30mA no load 1000uF'][0]:.0f} | "
          f"step min {vmin:.3f}  err " + " ".join(f"{k*1e6:.0f}us:{v:+.0f}mV" for k, v in pts.items()))
