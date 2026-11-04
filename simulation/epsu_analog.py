"""ngspice netlist of the e-psu analog path, built from the KiCad schematic values.

Covered (schematic sheet 4/5/6): pass FET Q301, CC shunt R301 + INA293 (U301), force-node caps and
bleeder, ranging shunts R401/R402 with BAV199 clamps and bypass FETs Q401/Q402 (island drive),
INA190 range amps, sense buffer U303, CV amp U302A with FBV divider and compensation, CC amp U302B,
diode-OR gate drive with R312 pull-up, hold/OCP FETs, mode relay + back-to-back output switch
(as resistances), output network and the load.  VPRE (tracking buck) and the setpoint DAC are
ideal sources (with optional ripple / steps).
"""
from kicad_values import values

V = values()
G_CC = 50.0                     # INA293A2 gain
RANGE_STATES = {"3A": (1, 1), "30mA": (0, 1), "300uA": (0, 0)}   # (Q401 on, Q402 on)
R_RELAY = 0.05                  # HF115F NC contact (datasheet max 100 mOhm)
R_SWITCH = 2 * 1.8e-3           # 2x NTMFS5C430N at VGS ~ 8.5 V (VOM1271 open-circuit 8.4-8.7 V)
VIN = 30.0                      # VIN_PROT

# Changes proposed by this simulation (schematic rev A -> proposed):
#   CV: C304 1n -> 5.6n C0G, new R327 8.2k in series with C304 (feed-forward path), C305 9.1n -> DNP,
#       R305 10k -> 3.9k, C306 2.2n -> 1n C0G
#   CC: R307 10k -> 1k, C307 4.7n -> 1.5n
#   bleeder: 2 mA -> 10 mA (R319 330R -> 68R, R318 1k -> 100R; Q304 MMBT3904 -> SOT-89 NPN, ~0.25 W)
PROPOSED = {"C304": 5.6e-9, "RFF": 8200.0, "C305": 0, "R305": 3900.0, "C306": 1e-9, "R307": 1000.0,
            "C307": 1.5e-9, "R319": 68.0, "R318": 100.0}


def cv_dac(vout):
    """DAC_A voltage for an output setpoint (sense node VSENSE)."""
    return vout * V["R304"] / (V["R303"] + V["R304"])


def cc_dac(ilim):
    return ilim * G_CC * V["R301"]


def netlist(vout=12.0, ilim=3.2, rng="3A", load=None, cload=0.0, esr=0.05, vpre=None, loop=None,
            extra="", drv=None, ocp=False, vpre_src=None, dac_src=None, vin=VIN, opamp=None, fet=None,
            slow=False, comp=None):
    """load: ("R", ohms) | ("I", amps) | None (open).  loop: (vi_ac, ii_ac) inserts the Tian probe at
    the gate-drive node.  drv: (va_expr, vb_expr) override range-drive states (0/1 behavioural
    expressions); extra: additional netlist lines.  Returns netlist text."""
    v = dict(V)
    if "R327" in v and "RFF" not in v:      # the feed-forward resistor once it is in the schematic
        v["RFF"] = v["R327"]
    if comp:
        v.update(comp)          # e.g. {"C306": 10e-9, "R305": 4.7e3}: compensation experiments
    if slow:                    # DC-identical, heavily damped copy used to find the operating point
        v["C306"] = v["C307"] = 10e-9      # pure, slower integrators (caps and series R do not affect DC)
        v["R305"] = v["R307"] = 1.0
        v["R306"] = 2e3                     # no DC current flows in R306 (capacitive feedback)
        v["C304"] = 1e-12
        v["RFF"] = 0
    vpre = vpre if vpre is not None else min(max(vout + 1.5, 2.0), 27.5)
    sa, sb = RANGE_STATES[rng]
    va_expr, vb_expr = drv if drv else (str(sa), str(sb))
    op = opamp or {}
    opp = " ".join(f"{k}={val}" for k, val in op.items())
    lines = [f"* e-psu analog path  vout={vout} ilim={ilim} range={rng} load={load} cload={cload}",
             ".include {MODELS}/opamp.lib", ".include {MODELS}/discrete.lib",
             f"Vin vin 0 {vin}", "V3v3 v3v3 0 3.3", "V5 v5 0 5", "V33a v33a 0 3.3",
             vpre_src or f"Vpre vpre 0 {vpre}",
             ]
    fet_model = fet or "IRFP260N"
    lines += [
        # pass element and gate network
        f"M301 vpre gate vsrc vsrc {fet_model}",
        f"R313 gdrv_b gate {v['R313']}",
        "D303 zcl gate DZ15", "D304 zcl vsrc DZ15",
        f"R301 vsrc vforce {v['R301']}",
        f"XU301 vsrc vforce v5 0 i3a INA_BEHAV G={G_CC} BW=1.3e6 SR=2.5e6 VSW=0.07",
        f"C313 vforce 0 {v['C313']}", f"C314 vforce 0 {v['C314']}",
        # bleeder Q304
        f"R318 vforce bld_c {v['R318']}", "Q304 bld_c bld_b bld_e Q2N3904",
        f"R319 bld_e 0 {v['R319']}", f"R320 v3v3 bld_b {v['R320']}", f"R321 bld_b 0 {v['R321']}",
        # ranging shunts, clamps, bypass FETs driven from the VFORCE island
        f"R401 vforce nmid {v['R401']}", f"R402 nmid vsense {v['R402']}",
        "D401a vforce nmid DBAV199", "D401b nmid vforce DBAV199",
        "D402a nmid vsense DBAV199", "D402b vsense nmid DBAV199",
        "M401 vforce g_a nmid nmid AO3400A", f"R404 g_a nmid {v['R404']}", f"R403 drv_a g_a {v['R403']}",
        "M402 nmid g_b vsense vsense AO3400A", f"R406 g_b vsense {v['R406']}", f"R405 drv_b g_b {v['R405']}",
        f"Bdra drva_i 0 V=V(vforce)+5*({va_expr})", "Rdra drva_i drv_a 1.5",
        f"Bdrb drvb_i 0 V=V(vforce)+5*({vb_expr})", "Rdrb drvb_i drv_b 1.5",
        f"C401 vsense 0 {v['C401']}",
        # range amplifiers (measurement + hardware range-up comparators)
        f"R407 vforce in1p {v['R407']}", f"R408 nmid in1n {v['R408']}", f"C402 in1p in1n {v['C402']}",
        "XU401 in1p in1n v33a 0 i30ma INA_BEHAV G=100 BW=35e3 SR=0.3e6 VSW=0.02",
        f"R409 nmid in2p {v['R409']}", f"R410 vsense in2n {v['R410']}", f"C404 in2p in2n {v['C404']}",
        "XU402 in2p in2n v33a 0 i300ua INA_BEHAV G=100 BW=35e3 SR=0.3e6 VSW=0.02",
        # mode relay (NC) + back-to-back output switch, output network
        f"Rrly vsense sw_in {R_RELAY}", f"Rsw sw_in outp {R_SWITCH}",
        f"C502 outp 0 {v['C502']}", f"R508 outp vterm {v['R508']}", f"R509 vterm 0 {v['R509']}",
        f"C503 vterm 0 {v['C503']}",
        # sense buffer U303 and dividers
        f"R322 vsense sns_in {v['R322']}",
        f"XU303 sns_in vs_buf vin_op 0 vs_buf OPAMP_RRIO {opp}",
        f"R325 vs_buf vout_adc {v['R325']}", f"R326 vout_adc 0 {v['R326']}", f"C321 vout_adc 0 {v['C321']}",
        f"R303 vs_buf fbv {v['R303']}", f"R304 fbv 0 {v['R304']}",
        (f"C304 vforce ffm {v['C304']}\nRFF ffm fbv {v['RFF']}" if v.get("RFF") else f"C304 vforce fbv {v['C304']}"),
        (f"C305 fbv 0 {v['C305']}" if v.get("C305") else ""),
        # op-amp supply VOP = VIN_PROT through R106 10 R, VNEG = GND
        "Rvop vin vin_op 10", "Cvop vin_op 0 10u",
        # setpoint DAC (ideal) + RC filters
        dac_src or f"Vdaca dac_a 0 {cv_dac(vout):.6g}\nVdacb dac_b 0 {cc_dac(ilim):.6g}",
        f"R310 dac_a dac_cv_f {v['R310']}", f"C308 dac_cv_f 0 {v['C308']}",
        f"R311 dac_b dac_cc_f {v['R311']}", f"C309 dac_cc_f 0 {v['C309']}",
        # CV error amp U302A
        f"XU302A dac_cv_f fbv vin_op 0 cv_out OPAMP_RRIO {opp}",
        f"C306 fbv cv_rc {v['C306']}", f"R305 cv_rc cv_out {v['R305']}",
        # CC error amp U302B
        f"R306 i3a fbi {v['R306']}",
        f"XU302B dac_cc_f fbi vin_op 0 cc_out OPAMP_RRIO {opp}",
        f"C307 fbi cc_rc {v['C307']}", f"R307 cc_rc cc_out {v['R307']}",
        f"R308 cc_out cc_mon {v['R308']}", f"R309 cc_mon 0 {v['R309']}", f"C319 cc_mon 0 {v['C319']}",
        # diode-OR gate drive, pull-up from VIN_PROT (R314 = 0 R)
        f"R312 vin gdrv {v['R312']}",
        "D301 gdrv cv_out D1N4148", "D302 gdrv cc_out D1N4148",
        "M302 gdrv hold 0 0 N2N7002", "Vhold hold 0 0",
        "M303 gdrv ocp 0 0 N2N7002",
        ("" if ocp else "Vocp ocp 0 0"),
    ]
    if loop:
        lines += [f"Vinj gdrv gdrv_b DC 0 AC {loop[0]}", f"Iinj 0 gdrv DC 0 AC {loop[1]}"]
    else:
        lines += ["Vinj gdrv gdrv_b DC 0"]
    # load
    if cload and not slow:      # capacitors do not change the DC solution
        lines += [f"Cl outp cl_esr {cload}", f"Resr cl_esr 0 {esr}"]
    if load and load[0] == "R":
        lines.append(f"Rload outp 0 {load[1]}")
    elif load and load[0] == "I":
        lines.append(f"Iload outp 0 DC {load[1]}")
    elif load and load[0] == "raw":
        lines.append(load[1])
    lines.append(extra)
    # operating-point hints (CV mode)
    lines.append(".options gmin=1e-12 reltol=1e-4 abstol=1e-12 vntol=1e-7 itl1=500 itl4=200 method=gear")
    return "\n".join(l for l in lines if l is not None)
