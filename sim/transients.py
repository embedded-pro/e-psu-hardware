"""Time-domain checks: load steps, hardware range-up, CV->CC short circuit, setpoint steps,
plus AC ripple rejection / output impedance and the buck FB-injection transfer."""
import json
import os

import numpy as np

import epsu_analog as E
import spice

HERE = os.path.dirname(os.path.abspath(__file__))


def tran(tag, analysis, vectors, comp=None, settle_kw=None, **kw):
    """settle_kw: arguments that replace kw for the DC-settling copy (e.g. no range-up logic)."""
    def b(slow):
        k = dict(kw)
        if slow and settle_kw:
            k.update(settle_kw)
        return E.netlist(slow=slow, comp=comp, **k)
    base, st, _ = spice.operating_point(b, tag=tag)
    return spice.run(base, analysis, vectors, tag + "_tr", timeout=900)


def load_step(tag, comp, rng, i0, i1, t0=0.2e-3, t1=0.6e-3, tend=1.0e-3, vout=12.0, cload=0.0):
    src = f"Iload outp 0 PWL(0 {i0} {t0} {i0} {t0 + 1e-6} {i1} {t1} {i1} {t1 + 1e-6} {i0})"
    return tran(tag, f"tran 50n {tend}", ["v(outp)", "v(gate)", "i(vpre)", "v(vforce)"], comp=comp,
                vout=vout, rng=rng, load=("raw", src), cload=cload, esr=0.05, settle_kw=dict(load=("I", i0)))


RANGE_CHAIN = """* hardware range-up: STM32 COMP -> TIM break (latched) -> CA-IS3720 -> UCC27524A, total delay TD
Bcb cb 0 V=V(i300ua) > 3.1 ? 1 : 0
Bca ca 0 V=V(i30ma) > 3.1 ? 1 : 0
Blb 0 lb I=1m*V(cb)
Cl_b lb 0 10p
Rl_b lb 0 1g
Dlb lb lbh DL
Vlbh lbh 0 1
Bla 0 la I=1m*V(ca)
Cl_a la 0 10p
Rl_a la 0 1g
Dla la lah DL
Vlah lah 0 1
.model DL D(Is=1e-14 N=0.05)
Eb1 lbi 0 lb 0 1
Rb1 lbi lbt 50
Tb lbt 0 lbd 0 Z0=50 TD={td}
Rb2 lbd 0 50
Ea1 lai 0 la 0 1
Ra1 lai lat 50
Ta lat 0 lad 0 Z0=50 TD={td}
Ra2 lad 0 50
"""


def range_up(tag, comp, i0=100e-6, i1=10e-3, td=75e-9, tstep=0.1e-3, tend=0.4e-3):
    src = f"Iload outp 0 PWL(0 {i0} {tstep} {i0} {tstep + 0.2e-6} {i1})"
    # latched states: (V(lad) > 0.5), the delayed latch outputs (0 .. ~1 V)
    drv = ("min(max((V(lad)-0.2)*2, 0), 1)", "min(max((V(lbd)-0.2)*2, 0), 1)")   # ~5 ns edges
    return tran(tag, f"tran 20n {tend}", ["v(outp)", "v(vforce)", "v(vsense)", "v(nmid)", "v(i300ua)",
                                          "v(i30ma)", "v(lbd)", "v(lad)"],
                comp=comp, vout=12.0, rng="300uA", load=("raw", src), drv=drv,
                extra=RANGE_CHAIN.replace("{td}", f"{td:.3g}"), cload=0.0,
                settle_kw=dict(drv=None, extra="", load=("I", i0)))


OCP_CHAIN = """* hardware OCP: COMP3 (I_3A > threshold) -> TIM20 break (latched) -> PB2 OCP_TRIP -> Q303 gate
Bc3 c3 0 V=V(i3a) > {thr} ? 1 : 0
Bl3 0 l3 I=1m*V(c3)
Cl3 l3 0 10p
Rl3 l3 0 1g
Dl3 l3 l3h DL3
Vl3h l3h 0 1
.model DL3 D(Is=1e-14 N=0.05)
E31 l3i 0 l3 0 1
R31 l3i l3t 50
T3 l3t 0 l3d 0 Z0=50 TD={td}
R32 l3d 0 50
Bocp ocp_i 0 V=3.3*min(max((V(l3d)-0.2)*2, 0), 1)
Rocp ocp_i ocp 50
"""


def short_circuit(tag, comp, ilim=1.0, rl=12.0, cload=0.0, tsc=0.2e-3, tend=1.2e-3, ocp_thr=None, td=50e-9):
    src = (f"Rl outp 0 {rl}\nS1 outp 0 sc 0 SWM\nVsc sc 0 PWL(0 0 {tsc} 0 {tsc + 0.1e-6} 1)\n"
           ".model SWM SW(Ron=0.05 Roff=1e8 Vt=0.5 Vh=0.1)")
    if ocp_thr is not None:
        extra = OCP_CHAIN.replace("{thr}", f"{ocp_thr:.4g}").replace("{td}", f"{td:.3g}")
        return tran(tag, f"tran 10n {tend}", ["v(outp)", "i(vpre)", "v(i3a)", "v(cv_out)", "v(cc_out)", "v(gate)", "v(ocp)"],
                    comp=comp, vout=12.0, ilim=ilim, rng="3A", load=("raw", src), cload=cload, esr=0.05,
                    ocp=True, extra=extra, settle_kw=dict(load=("R", rl), ocp=False, extra=""))
    return tran(tag, f"tran 20n {tend}", ["v(outp)", "i(vpre)", "v(i3a)", "v(cv_out)", "v(cc_out)", "v(gate)"],
                comp=comp, vout=12.0, ilim=ilim, rng="3A", load=("raw", src), cload=cload, esr=0.05,
                settle_kw=dict(load=("R", rl)))


def setpoint_step(tag, comp, v0=1.0, v1=12.0, t0=0.1e-3, tend=2e-3, rl=None, cload=0.0):
    a0, a1 = E.cv_dac(v0), E.cv_dac(v1)
    dac = f"Vdaca dac_a 0 PWL(0 {a0} {t0} {a0} {t0 + 2e-6} {a1})\nVdacb dac_b 0 {E.cc_dac(3.2)}"
    load = ("R", rl) if rl else None
    return tran(tag, f"tran 0.1u {tend}", ["v(outp)", "v(gate)", "i(vpre)"], comp=comp, vout=v0,
                vpre=max(v0, v1) + 1.5, dac_src=dac, load=load, cload=cload, esr=0.05,
                settle_kw=dict(dac_src=None))


def ac_response(tag, comp, kind, **kw):
    """kind 'psrr': AC on VPRE -> |v(outp)|;  'zout': 1 A AC into outp -> |v(outp)| = |Zout|."""
    b = lambda slow: E.netlist(slow=slow, comp=comp, **kw)
    base, st, _ = spice.operating_point(b, tag=tag)
    if kind == "psrr":
        vp = [l for l in base.splitlines() if l.startswith("Vpre ")][0]
        base = base.replace(vp, vp + " AC 1")
    else:
        base += "\nIzac 0 outp DC 0 AC 1"
    return spice.run(base, "ac dec 30 10 10meg", ["v(outp)"], tag + "_ac")


def buck_injection():
    """LM76003 FB node with DAC injection; regulator idealised as 'VPRE so that FB = VFB'."""
    v = E.V
    net = f"""* buck FB injection
Vdac dac 0 0
R203 dac fb {v['R203']}
R201 vpre fb {v['R201']}
R202 fb 0 {v['R202']}
Bbuck vpre 0 V=min(max(1e5*(1.006-V(fb)) , 0), 40)
Rl vpre 0 1k
"""
    r = spice.run(net, "dc vdac 0 3.3 0.01", ["v(vpre)"], "buck_inj")
    return r["scale"], r["v(vpre)"]
