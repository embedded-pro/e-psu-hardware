"""Small ngspice driver: run a netlist in batch mode and read vectors written with wrdata."""
import os
import re
import subprocess
import uuid


def _safe(tag):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", tag)

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(HERE, "work")
MODELS = os.path.join(HERE, "models")


def run(netlist, analysis, vectors, tag=None, timeout=300):
    """netlist: circuit text without .control/.end; analysis: e.g. 'ac dec 40 1 100meg' or 'tran 1n 1m'.
    Returns dict: scale + each vector (complex for AC)."""
    os.makedirs(WORK, exist_ok=True)
    tag = _safe(tag or uuid.uuid4().hex[:8])
    cir = os.path.join(WORK, tag + ".cir")
    out = os.path.join(WORK, tag + ".dat")
    ctrl = "\n".join([
        ".control",
        "set wr_singlescale", "set wr_vecnames", "set filetype=ascii", "option numdgt=8",
        analysis,
        "wrdata %s %s" % (out, " ".join(vectors)),
        "quit", ".endc", ".end"])
    text = netlist.replace("{MODELS}", MODELS) + "\n" + ctrl + "\n"
    open(cir, "w").write(text)
    if os.path.exists(out):
        os.remove(out)
    r = subprocess.run(["ngspice", "-b", cir], capture_output=True, text=True, timeout=timeout)
    if not os.path.exists(out):
        raise RuntimeError(f"ngspice failed for {tag}:\n{r.stdout[-3000:]}\n{r.stderr[-3000:]}")
    with open(out) as f:
        header = f.readline().split()
    data = np.loadtxt(out, skiprows=1, ndmin=2)
    res = {}
    is_ac = analysis.strip().lower().startswith("ac")
    res["scale"] = data[:, 0]
    col = 1
    names = header[1:]
    if is_ac:
        # complex vectors are written as real, imag column pairs
        for v in vectors:
            res[v] = data[:, col] + 1j * data[:, col + 1]
            col += 2
    else:
        for v in vectors:
            res[v] = data[:, col]
            col += 1
    res["_log"] = r.stdout
    res["_names"] = names
    if analysis.strip().lower().startswith("tran"):
        tstop = analysis.split()[2]
        mult = {"m": 1e-3, "u": 1e-6, "n": 1e-9}
        tv = float(tstop[:-1]) * mult[tstop[-1]] if tstop[-1] in mult else float(tstop)
        if res["scale"][-1] < 0.99 * tv:
            raise RuntimeError(f"{tag}: transient aborted at t={res['scale'][-1]:.4g} s\n{r.stderr[-800:]}")
    return res


def tian(netlist_fn, analysis, xnode, vsrc, tag):
    """Loop gain by Tian's method. netlist_fn(vi_ac, ii_ac) returns the netlist with the voltage probe
    `vsrc` (V xnode ynode) and current source (I 0 xnode) set to those AC magnitudes.
    Returns (f, T) with T the loop gain (closed loop ~ 1/(1+T))."""
    r1 = run(netlist_fn(1, 0), analysis, [f"v({xnode})", f"i({vsrc})"], tag + "_v")
    r2 = run(netlist_fn(0, 1), analysis, [f"v({xnode})", f"i({vsrc})"], tag + "_i")
    vx1, ix1 = r1[f"v({xnode})"], r1[f"i({vsrc})"]
    vx2, ix2 = r2[f"v({xnode})"], r2[f"i({vsrc})"]
    t = -1.0 / (1.0 - 1.0 / (2.0 * (ix1 * vx2 - vx1 * ix2) + vx1 + ix2))
    return r1["scale"], t, (r1, r2)


def margins(f, t):
    """Crossover frequency, phase margin (deg), gain margin (dB) for loop gain t (closed loop 1/(1+T))."""
    mag = np.abs(t)
    ph = np.unwrap(np.angle(t)) * 180 / np.pi
    fc = pm = gm = None
    idx = np.where((mag[:-1] >= 1) & (mag[1:] < 1))[0]
    if len(idx):
        i = idx[-1]
        a = (np.log(mag[i]) - 0) / (np.log(mag[i]) - np.log(mag[i + 1]))
        fc = np.exp(np.log(f[i]) + a * (np.log(f[i + 1]) - np.log(f[i])))
        phc = ph[i] + a * (ph[i + 1] - ph[i])
        pm = 180.0 + phc
        pm = (pm + 180) % 360 - 180
    # gain margin: |T| where phase crosses -180 (mod 360), above crossover
    wrapped = (ph + 180) % 360 - 180
    for i in range(len(f) - 1):
        if fc is not None and f[i] < fc:
            continue
        if np.sign(wrapped[i] + 180 - 1e-9) != np.sign(wrapped[i + 1] + 180 - 1e-9) and abs(wrapped[i] - wrapped[i + 1]) < 180:
            gm = -20 * np.log10(mag[i])
            break
    return fc, pm, gm


def _read_raw_last(path):
    """Last point of every vector in an ASCII rawfile -> {name: value}."""
    names, vals = [], {}
    with open(path) as f:
        lines = f.read().splitlines()
    i = 0
    nvars = npts = 0
    while i < len(lines):
        l = lines[i]
        if l.startswith("No. Variables:"):
            nvars = int(l.split(":")[1])
        elif l.startswith("No. Points:"):
            npts = int(l.split(":")[1])
        elif l.startswith("Variables:"):
            for k in range(nvars):
                parts = lines[i + 1 + k].split()
                names.append(parts[1])
            i += nvars
        elif l.startswith("Values:"):
            body = [x for x in lines[i + 1:] if x.strip()]
            last = body[-nvars:]
            for k, x in enumerate(last):
                tok = x.split()
                vals[names[k]] = float(tok[-1].split(",")[0])
            break
        i += 1
    return vals


def ramp_sources(netlist, tramp="200u"):
    """Replace plain DC voltage sources 'Vname n+ n- value' by a PWL ramp from 0 (power-up)."""
    import re
    out = []
    for line in netlist.splitlines():
        m = re.match(r"^(V\S+)\s+(\S+)\s+(\S+)\s+([-+0-9.eE]+)\s*$", line)
        if m and float(m.group(4)) != 0.0:
            line = f"{m.group(1)} {m.group(2)} {m.group(3)} PWL(0 0 {tramp} {m.group(4)})"
        out.append(line)
    return "\n".join(out)


def settle(netlist, tstop, tstep="2u", tag=None, timeout=600):
    """Power-up transient (sources ramped from 0) and return the end-state node voltages."""
    os.makedirs(WORK, exist_ok=True)
    tag = _safe(tag or uuid.uuid4().hex[:8])
    cir = os.path.join(WORK, tag + "_settle.cir")
    raw = os.path.join(WORK, tag + "_settle.raw")
    text = ramp_sources(netlist).replace("{MODELS}", MODELS) + "\n" + "\n".join([
        ".control", "set filetype=ascii", f"tran {tstep} {tstop}", f"write {raw}", "quit", ".endc", ".end"]) + "\n"
    open(cir, "w").write(text)
    if os.path.exists(raw):
        os.remove(raw)
    r = subprocess.run(["ngspice", "-b", cir], capture_output=True, text=True, timeout=timeout)
    if not os.path.exists(raw):
        raise RuntimeError(f"settle failed {tag}\n{r.stdout[-2000:]}\n{r.stderr[-2000:]}")
    vals = _read_raw_last(raw)
    return {k: v for k, v in vals.items() if k.startswith("v(") or ("#" not in k and k != "time" and not k.startswith("i("))}


def nodeset_from(state):
    """.nodeset line(s) from settle() output."""
    items = []
    for k, v in state.items():
        name = k[2:-1] if k.startswith("v(") else k
        if name.lower() in ("time", "0") or name.startswith("@"):
            continue
        items.append(f"v({name})={v:.9g}")
    out = []
    for j in range(0, len(items), 8):
        out.append(".nodeset " + " ".join(items[j:j + 8]))
    return "\n".join(out)


CHECK_NODES = ["v(outp)", "v(gate)", "v(cv_out)", "v(cc_out)"]


def _op_ok(netlist, st, tag):
    try:
        r = run(netlist, "op", CHECK_NODES, tag)
    except RuntimeError:
        return False, None
    if "Transient op" in r["_log"]:
        return False, r
    bad = [k for k in CHECK_NODES if abs(float(r[k][0]) - st.get(k, 1e9)) > 0.05 + 0.002 * abs(st.get(k, 0))]
    return not bad, r


def operating_point(build, tstop="25m", tag="op"):
    """build(slow) -> netlist.  The DC solution is checked against a power-up transient of a
    DC-identical, heavily damped copy (so an unstable loop cannot hide it).  Returns the netlist
    variant whose .op matches, the settled state, and the op result."""
    st = settle(build(True), tstop, tstep="5u", tag=tag)
    base = build(False)
    ext = {k: v for k, v in st.items() if "." not in k}
    for variant in (base, base + "\n" + nodeset_from(ext), base + "\n" + nodeset_from(st)):
        ok, r = _op_ok(variant, st, tag + "_chk")
        if ok:
            return variant, st, r
    raise RuntimeError(f"{tag}: no DC solution matching the settled state "
                       f"(settled outp={st.get('v(outp)')})")
