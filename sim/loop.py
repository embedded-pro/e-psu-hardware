"""Loop gain of the CV / CC regulation loop, broken at the gate-drive node (between the diode-OR
node GATE_DRV and R313), which every regulation path passes through."""
import numpy as np
import spice
import epsu_analog as E

AC = "ac dec 30 10 50meg"


def loop_gain(tag, **kw):
    """kw: epsu_analog.netlist arguments.  Returns margins and the loop-gain curve."""
    b = lambda slow: E.netlist(slow=slow, **kw)
    base, st, opr = spice.operating_point(b, tag=tag)
    nodeset = base[len(b(False)):]
    fn = lambda vi, ii: E.netlist(loop=(vi, ii), **kw) + nodeset
    f, t, _ = spice.tian(fn, AC, "gdrv", "vinj", tag)
    fc, pm, gm = spice.margins(f, t)
    mode = "CC" if float(opr["v(cc_out)"][0]) < float(opr["v(cv_out)"][0]) else "CV"
    return dict(f=f, t=t, fc=fc, pm=pm, gm=gm, mode=mode, vout=float(opr["v(outp)"][0]))


if __name__ == "__main__":
    for rng, ld in (("3A", ("R", 12.0)), ("3A", None), ("30mA", ("R", 1200.0)), ("300uA", ("R", 120e3))):
        r = loop_gain(f"lg_{rng}_{ld}", vout=12, rng=rng, load=ld)
        print(rng, ld, r["mode"], f"vout {r['vout']:.3f}", "fc", r["fc"] and f"{r['fc']/1e3:.1f} kHz", "PM", r["pm"] and round(r["pm"], 1), "GM", r["gm"] and round(r["gm"], 1))
