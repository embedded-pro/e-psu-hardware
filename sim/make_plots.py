"""Run the time-domain / AC checks and draw every plot used in REPORT.md -> plots/, results/summary.json"""
import csv
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

import epsu_analog as E
import loop
import transients as T

HERE = os.path.dirname(os.path.abspath(__file__))
P = lambda n: os.path.join(HERE, "plots", n)
C_OLD, C_NEW, C_AUX = "#c0392b", "#1f6fb2", "#7f8c8d"
plt.rcParams.update({"font.size": 9, "axes.grid": True, "grid.alpha": 0.3, "figure.dpi": 110,
                     "axes.spines.top": False, "axes.spines.right": False})
S = {}


def bode():
    fig, ax = plt.subplots(2, 1, figsize=(8, 6), sharex=True)
    for comp, col, lab in (({}, C_OLD, "as drawn"), (E.PROPOSED, C_NEW, "proposed")):
        for ld, ls, ll in ((("R", 12.0), "-", "1 A"), (None, "--", "no load")):
            r = loop.loop_gain(f"bode_{lab}_{ll}", comp=comp, vout=12, rng="3A", load=ld)
            ax[0].semilogx(r["f"], 20 * np.log10(abs(r["t"])), ls, color=col, label=f"{lab}, {ll}")
            ax[1].semilogx(r["f"], np.unwrap(np.angle(r["t"])) * 180 / np.pi, ls, color=col)
            S[f"bode_{lab}_{ll}"] = dict(fc=r["fc"], pm=r["pm"])
    ax[0].axhline(0, color="k", lw=0.7); ax[0].set_ylim(-80, 60); ax[0].set_ylabel("loop gain |T| (dB)")
    ax[0].legend(fontsize=8); ax[1].axhline(-180, color="k", lw=0.7); ax[1].set_ylabel("phase (deg)")
    ax[1].set_xlabel("frequency (Hz)"); ax[0].set_title("CV loop gain at 12 V, 3 A range (broken at the gate-drive node)")
    fig.tight_layout(); fig.savefig(P("cv_loop_bode.png")); plt.close(fig)


def pm_maps():
    def load(name):
        return list(csv.DictReader(open(os.path.join(HERE, "results", name))))
    rows_old, rows_new = load("cv_asdrawn.csv"), load("cv_proposed.csv")
    cl = ["0", "1e-06", "1e-05", "0.0001", "0.001"]
    cl_lab = ["none", "1 µF", "10 µF", "100 µF", "1000 µF"]
    cases = [("3A", "0.0", "3 A rng, open"), ("3A", "0.1", "3 A rng, 0.1 A"), ("3A", "1.0", "3 A rng, 1 A"),
             ("3A", "3.0", "3 A rng, 3 A"), ("30mA", "0.0", "30 mA rng, open"), ("30mA", "0.001", "30 mA rng, 1 mA"),
             ("30mA", "0.03", "30 mA rng, 30 mA"), ("300uA", "0.0", "300 µA rng, open"),
             ("300uA", "3e-05", "300 µA rng, 30 µA"), ("300uA", "0.0003", "300 µA rng, 300 µA")]
    fig, axs = plt.subplots(1, 2, figsize=(10, 4.6), sharey=True)
    for ax, rows, title in ((axs[0], rows_old, "as drawn"), (axs[1], rows_new, "proposed")):
        m = np.full((len(cases), len(cl)), np.nan)
        for i, (rng, il, _) in enumerate(cases):
            for j, c in enumerate(cl):
                pms = [float(r["pm"]) for r in rows if r["rng"] == rng and float(r["iload"]) == float(il)
                       and float(r["cload"]) == float(c) and r["pm"] not in ("", "None")]
                if pms:
                    m[i, j] = min(pms)
        im = ax.imshow(m, cmap="RdYlGn", vmin=-60, vmax=90, aspect="auto")
        for i in range(m.shape[0]):
            for j in range(m.shape[1]):
                ax.text(j, i, f"{m[i, j]:.0f}", ha="center", va="center", fontsize=7.5,
                        color="black")
        ax.set_xticks(range(len(cl))); ax.set_xticklabels(cl_lab, fontsize=8)
        ax.set_yticks(range(len(cases))); ax.set_yticklabels([c[2] for c in cases], fontsize=8)
        ax.set_title(f"{title}: worst phase margin (deg)\nover 1 / 12 / 24 V" + (" and both FET corners" if title == "proposed" else ""), fontsize=9)
        ax.set_xlabel("load capacitance (+50 mΩ ESR)"); ax.grid(False)
    fig.colorbar(im, ax=axs, shrink=0.8, label="phase margin (deg)")
    fig.savefig(P("cv_phase_margin_map.png"), bbox_inches="tight"); plt.close(fig)


def load_steps():
    fig, ax = plt.subplots(2, 1, figsize=(8, 6), sharex=True)
    for comp, col, lab in (({}, C_OLD, "as drawn"), (E.PROPOSED, C_NEW, "proposed")):
        r = T.load_step(f"ls3a_{lab}", comp, "3A", 0.1, 1.0, t0=0.2e-3, t1=2.2e-3, tend=4.2e-3)
        t = r["scale"] * 1e3
        ax[0].plot(t, r["v(outp)"], color=col, label=lab, lw=0.9)
        ax[1].plot(t, -r["i(vpre)"], color=col, lw=0.9)
        if lab == "proposed":
            v, tt = r["v(outp)"], r["scale"]
            fin = v[(tt > 2.0e-3) & (tt < 2.2e-3)].mean()
            S["step_3A"] = dict(v_before=float(v[tt < 0.2e-3][-1]), v_min=float(v[(tt > 0.2e-3) & (tt < 2.2e-3)].min()),
                                v_final=float(fin), v_max_release=float(v[tt > 2.2e-3].max()),
                                err_200us_mV=float(1e3 * (v[np.argmin(abs(tt - 0.4e-3))] - fin)),
                                err_1ms_mV=float(1e3 * (v[np.argmin(abs(tt - 1.2e-3))] - fin)))
    ax[0].set_ylabel("output (V)"); ax[0].legend(); ax[0].set_ylim(11.2, 12.6)
    ax[0].set_title("Load step 0.1 A → 1 A → 0.1 A at 12 V, 3 A range, no extra output capacitor")
    ax[1].set_ylabel("pass-FET current (A)"); ax[1].set_xlabel("time (ms)")
    fig.tight_layout(); fig.savefig(P("load_step_3A.png")); plt.close(fig)
    # low range
    fig, ax = plt.subplots(figsize=(8, 3.2))
    r = T.load_step("ls30m", E.PROPOSED, "30mA", 1e-3, 20e-3, t0=0.2e-3, t1=1.2e-3, tend=2.2e-3)
    t = r["scale"] * 1e3
    ax.plot(t, r["v(outp)"], color=C_NEW, lw=0.9)
    v = r["v(outp)"]; tt = r["scale"]
    S["step_30mA"] = dict(v_min=float(v[(tt > 0.2e-3) & (tt < 1.2e-3)].min()), v_max=float(v[tt > 1.2e-3].max()),
                          v_final=float(v[(tt > 1.1e-3) & (tt < 1.2e-3)].mean()))
    ax.set_title("Proposed: load step 1 mA → 20 mA → 1 mA at 12 V, 30 mA range (1 Ω shunt in the path)")
    ax.set_ylabel("output (V)"); ax.set_xlabel("time (ms)")
    fig.tight_layout(); fig.savefig(P("load_step_30mA.png")); plt.close(fig)


def range_up():
    fig, ax = plt.subplots(3, 1, figsize=(8, 7.5), sharex=True)
    for i1, col, lab in ((10e-3, C_NEW, "100 µA → 10 mA"), (1.0, "#8e44ad", "100 µA → 1 A")):
        r = T.range_up(f"ru_{i1}", E.PROPOSED, i1=i1, tend=0.6e-3)
        t = (r["scale"] - 0.1e-3) * 1e6
        m = t > -20
        ax[0].plot(t[m], r["v(outp)"][m], color=col, label=lab, lw=0.9)
        ax[1].plot(t[m], (r["v(vforce)"] - r["v(vsense)"])[m], color=col, lw=0.9)
        ax[2].plot(t[m], r["v(i300ua)"][m], color=col, lw=0.9, label="I_300UA" if i1 == 10e-3 else None)
        ax[2].plot(t[m], r["v(i30ma)"][m], color=col, lw=0.9, ls=":", label="I_30MA" if i1 == 10e-3 else None)
        lb, la = r["v(lbd)"], r["v(lad)"]
        tb = t[np.where((lb > 0.25) & (t > 0))[0][0]] if np.any((lb > 0.25) & (t > 0)) else None
        ta = t[np.where((la > 0.25) & (t > 0))[0][0]] if np.any((la > 0.25) & (t > 0)) else None
        for k_, (tx, nm) in enumerate(((tb, "RANGE_B"), (ta, "RANGE_A"))):
            if tx is not None:
                for a in ax:
                    a.axvline(tx, color=col, lw=0.6, ls="--")
                ax[2].annotate(f"{nm} {tx:.1f} µs", (tx + 1.5, 0.35 + 0.45 * k_ + (0.9 if i1 > 0.1 else 0)),
                               fontsize=7, color=col)
        v = r["v(outp)"]
        S[f"range_up_{lab}"] = dict(t_range_b_us=tb, t_range_a_us=ta, v_min=float(v[t > 0].min()),
                                    v_max=float(v[t > 0].max()), burden_max=float((r["v(vforce)"] - r["v(vsense)"])[t > 0].max()),
                                    v_end=float(v[-1]))
    ax[0].set_ylabel("output (V)"); ax[0].legend(fontsize=8)
    ax[0].set_title("Hardware range-up from the 300 µA range at 12 V (COMP → TIM break → isolator → driver, 75 ns)")
    ax[1].set_ylabel("burden VFORCE−VSENSE (V)")
    ax[2].axhline(3.1, color="k", lw=0.6); ax[2].set_ylabel("range amp output (V)"); ax[2].legend(fontsize=8)
    ax[2].set_xlabel("time after the load step (µs)")
    fig.tight_layout(); fig.savefig(P("range_up.png")); plt.close(fig)


def short():
    fig, ax = plt.subplots(2, 1, figsize=(8, 5.6), sharex=True)
    for comp, col, lab, thr in (({}, C_OLD, "as drawn, CC loop only", None), (E.PROPOSED, C_NEW, "proposed, CC loop only", None),
                                (E.PROPOSED, "#16a085", "proposed + hardware OCP at 2 A", 1.5)):
        r = T.short_circuit(f"sc_{lab}", comp, ilim=1.0, rl=24.0, tend=0.5e-3, ocp_thr=thr)
        t = (r["scale"] - 0.2e-3) * 1e6
        m = t > -20
        i = -r["i(vpre)"]
        ax[0].plot(t[m], i[m], color=col, label=lab, lw=0.9)
        ax[1].plot(t[m], r["v(gate)"][m], color=col, lw=0.9)
        above = t[(t > 0) & (i > 3.0)]
        S[f"short_{lab}"] = dict(i_peak=float(i[t > 0].max()), i_end=float(i[-50:].mean()),
                                  t_above_3A_us=float(above[-1] - above[0]) if len(above) else 0.0)
    ax[0].set_yscale("symlog", linthresh=2); ax[0].axhline(1.0, color="k", lw=0.6)
    ax[0].set_ylabel("pass-FET current (A)"); ax[0].legend(fontsize=8)
    ax[0].set_title("Dead short from CV (12 V, 0.5 A load), 1 A current limit, 3 A range, ideal VPRE")
    ax[1].set_ylabel("gate (V)"); ax[1].set_xlabel("time after the short (µs)"); ax[1].set_xlim(-20, 300)
    fig.tight_layout(); fig.savefig(P("short_circuit.png")); plt.close(fig)


def setpoint():
    fig, ax = plt.subplots(1, 2, figsize=(10, 3.4))
    r = T.setpoint_step("sp_up", E.PROPOSED, 1.0, 12.0, rl=1000.0, tend=5e-3)
    ax[0].plot(r["scale"] * 1e3, r["v(outp)"], color=C_NEW, lw=0.9)
    ax[0].set_title("Setpoint 1 V → 12 V, 1 kΩ load"); ax[0].set_xlabel("time (ms)"); ax[0].set_ylabel("output (V)")
    v, t = r["v(outp)"], r["scale"]
    S["setpoint_up"] = dict(v_max=float(v.max()), t_90_us=float((t[np.where(v > 1 + 0.9 * 11)[0][0]] - 0.1e-3) * 1e6))
    for rl, col, lab in ((None, C_NEW, "no load (bleeder only)"), (100.0, "#16a085", "100 Ω load")):
        r = T.setpoint_step(f"sp_dn_{rl}", E.PROPOSED, 12.0, 1.0, rl=rl, tend=6e-3, cload=0.0)
        ax[1].plot(r["scale"] * 1e3, r["v(outp)"], color=col, lw=0.9, label=lab)
        v, t = r["v(outp)"], r["scale"]
        idx = np.where(v < 1 + 0.1 * 11)[0]
        S[f"setpoint_down_{lab}"] = dict(t_90_ms=float((t[idx[0]] - 0.1e-3) * 1e3) if len(idx) else None)
    ax[1].set_title("Setpoint 12 V → 1 V (the follower cannot sink current)"); ax[1].set_xlabel("time (ms)")
    ax[1].legend(fontsize=8)
    fig.tight_layout(); fig.savefig(P("setpoint_steps.png")); plt.close(fig)


def ac():
    fig, ax = plt.subplots(1, 2, figsize=(10, 3.6))
    for ld, ls, lab in ((("R", 12.0), "-", "1 A"), (None, "--", "no load")):
        r = T.ac_response(f"psrr_{lab}", E.PROPOSED, "psrr", vout=12, rng="3A", load=ld)
        g = 20 * np.log10(abs(r["v(outp)"]))
        ax[0].semilogx(r["scale"], g, ls, color=C_NEW, label=lab)
        S[f"psrr_{lab}"] = {f"{int(f)}Hz": float(g[np.argmin(abs(r['scale'] - f))]) for f in (100, 1e3, 1e4, 1e5, 5e5)}
    ax[0].set_title("Ripple rejection VPRE → output (12 V, 3 A range)"); ax[0].set_ylabel("dB"); ax[0].set_xlabel("Hz")
    ax[0].axvline(500e3, color=C_AUX, lw=0.6); ax[0].legend(fontsize=8)
    for rng, ld, col in (("3A", ("R", 12.0), C_NEW), ("30mA", ("R", 1200.0), "#16a085"), ("300uA", ("R", 120e3), "#8e44ad")):
        r = T.ac_response(f"zout_{rng}", E.PROPOSED, "zout", vout=12, rng=rng, load=ld)
        z = abs(r["v(outp)"])
        ax[1].loglog(r["scale"], z, color=col, label=f"{rng} range")
        S[f"zout_{rng}"] = {f"{int(f)}Hz": float(z[np.argmin(abs(r['scale'] - f))]) for f in (10, 1e3, 1e5)}
    ax[1].set_title("Output impedance at 12 V (closed loop)"); ax[1].set_ylabel("Ω"); ax[1].set_xlabel("Hz")
    ax[1].legend(fontsize=8)
    fig.tight_layout(); fig.savefig(P("psrr_zout.png")); plt.close(fig)


def buck():
    d, vp = T.buck_injection()
    fig, ax = plt.subplots(figsize=(6, 3.4))
    ax.plot(d, vp, color=C_NEW)
    ax.set_xlabel("BUCK_DAC (V)"); ax.set_ylabel("VPRE (V)"); ax.set_title("Tracking buck: VPRE vs DAC injection")
    fig.tight_layout(); fig.savefig(P("buck_injection.png")); plt.close(fig)
    S["buck"] = {f"{x:.1f}V": float(vp[np.argmin(abs(d - x))]) for x in (0.0, 0.2, 0.5, 1.0, 1.006, 1.1, 3.3)}
    S["buck_slope_V_per_V"] = float((vp[np.argmin(abs(d - 0.2))] - vp[np.argmin(abs(d - 0.8))]) / 0.6)


if __name__ == "__main__":
    import sys
    if os.path.exists(os.path.join(HERE, "results", "summary.json")):
        S.update(json.load(open(os.path.join(HERE, "results", "summary.json"))))
    sel = sys.argv[1:]
    for fn in (bode, pm_maps, load_steps, range_up, short, setpoint, ac, buck):
        if sel and fn.__name__ not in sel:
            continue
        fn()
        print("done", fn.__name__, flush=True)
    json.dump(S, open(os.path.join(HERE, "results", "summary.json"), "w"), indent=1, default=float)
    print(json.dumps(S, indent=1, default=float))
