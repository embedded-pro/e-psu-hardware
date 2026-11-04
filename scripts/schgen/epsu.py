"""e-psu rev A schematic: generates the KiCad 7 project into ../../hardware/e-psu."""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "..", "hardware", "e-psu")
sys.path.insert(0, HERE)

import lib
from sch import Project, Sheet
import parts_lib
from symgen import write_lib

PROJ_LIB = os.path.join(OUT, "e-psu.kicad_sym")
os.makedirs(OUT, exist_ok=True)
write_lib(PROJ_LIB, parts_lib.build(PROJ_LIB))
lib._cache.pop(PROJ_LIB, None)

# ---------------------------------------------------------------- footprints
R0603 = "Resistor_SMD:R_0603_1608Metric"
R0805 = "Resistor_SMD:R_0805_2012Metric"
R2512 = "Resistor_SMD:R_2512_6332Metric"
C0603 = "Capacitor_SMD:C_0603_1608Metric"
C0805 = "Capacitor_SMD:C_0805_2012Metric"
C1206 = "Capacitor_SMD:C_1206_3216Metric"
C1210 = "Capacitor_SMD:C_1210_3225Metric"
SOD123 = "Diode_SMD:D_SOD-123"
SMA = "Diode_SMD:D_SMA"
SMB = "Diode_SMD:D_SMB"
SOT23 = "Package_TO_SOT_SMD:SOT-23"
SOT23_5 = "Package_TO_SOT_SMD:SOT-23-5"
SOT23_6 = "Package_TO_SOT_SMD:SOT-23-6"
SOT23_8 = "Package_TO_SOT_SMD:SOT-23-8"
SOT223 = "Package_TO_SOT_SMD:SOT-223-3_TabPin2"
SOIC8 = "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm"
FB0805 = "Inductor_SMD:L_0805_2012Metric"
LED0603 = "LED_SMD:LED_0603_1608Metric"
POST_R = "Connector:Banana_Cliff_FCR7350R_S16N-PC_Horizontal"
POST_B = "Connector:Banana_Cliff_FCR7350B_S16N-PC_Horizontal"

P = Project("e-psu", extra_lib={"e-psu": PROJ_LIB})
P.sym_alias = {"VFORCE": "e-psu:VFORCE", "GND_USB": "e-psu:GND_USB"}


# ---------------------------------------------------------------- helpers
def R(sh, ref, val, x, y, n1, n2, rot=0, fp=R0603, **kw):
    p = sh.part("Device:R", ref, val, (x, y), rot, fp=fp, **kw)
    sh.net(p["1"], n1); sh.net(p["2"], n2)
    return p


def C(sh, ref, val, x, y, n1, n2="GND", rot=0, fp=C0603, lib_id="Device:C", **kw):
    p = sh.part(lib_id, ref, val, (x, y), rot, fp=fp, **kw)
    sh.net(p["1"], n1); sh.net(p["2"], n2)
    return p


def D(sh, lib_id, ref, val, x, y, nK, nA, rot=0, fp=SOD123, **kw):
    """Diode with pin 1 = K, pin 2 = A. rot 0: K left; 180: K right; 270: K top; 90: K bottom."""
    p = sh.part(lib_id, ref, val, (x, y), rot, fp=fp, **kw)
    sh.net(p["1"], nK); sh.net(p["2"], nA)
    return p


def Q3(sh, lib_id, ref, val, x, y, g, d, s, rot=0, fp=SOT23, **kw):
    p = sh.part(lib_id, ref, val, (x, y), rot, fp=fp, **kw)
    sh.net(p["G"], g); sh.net(p["D"], d); sh.net(p["S"], s)
    return p


def note(sh, x, y, lines, size=1.27):
    sh.text("\n".join(lines), (x, y), size=size)


# ============================================================ 1. power input
def sheet_power():
    sh = Sheet(P, "power_input", "power_input.kicad_sch", "Power input & housekeeping rails")
    # ---------------------------------------------------------------- input & protection
    sh.box(15.24, 20.32, 205.74, 111.76, "Input & protection (30 V from the bench PSU)")
    j1 = sh.part("Connector_Generic:Conn_01x01", "J101", "IN+", (25.4, 58.42), 180, fp=POST_R,
                 mpn="Cliff FCR7350R (4 mm, 16 A)")
    j2 = sh.part("Connector_Generic:Conn_01x01", "J102", "IN-", (25.4, 81.28), 180, fp=POST_B,
                 mpn="Cliff FCR7350B (4 mm, 16 A)")
    tvs = sh.part("Device:D_TVS", "D101", "SMBJ33CA", (43.18, 69.85), 90, fp=SMB, mpn="SMBJ33CA (bidirectional)")
    f2 = sh.part("Device:Fuse", "F102", "15A ATO", (63.5, 40.64), 90,
                 fp="Fuse:FuseHolder_Blade_ATO_Littelfuse_FLR_178.6165", mpn="ATO blade fuse 15 A + PCB holder")
    sh.net(f2["2"], "VIN_PT")
    f1 = sh.part("Device:Fuse", "F101", "5A fast", (63.5, 58.42), 90, fp="Fuse:Fuse_Littelfuse-NANO2-451_453",
                 mpn="Littelfuse 0451005.MRL (NANO2 5 A)")
    q = sh.part("Device:Q_PMOS_GDS", "Q101", "AOD4185", (81.28, 60.96), 90, fp="Package_TO_SOT_SMD:TO-252-2",
                mpn="AOD4185 (-40 V, 40 A, DPAK)")
    sh.link(f1["2"], q["D"], "VIN_F")
    r101 = R(sh, "R101", "22k", 81.28, 73.66, "PFET_G", "GND")
    d102 = D(sh, "Device:D_Zener", "D102", "BZT52C15", 93.98, 66.04, "VIN_PROT", "PFET_G", rot=270)
    caps = [C(sh, "C101", "100u 63V", 109.22, 69.85, "VIN_PROT", lib_id="Device:C_Polarized",
              fp="Capacitor_SMD:CP_Elec_10x10.5"),
            C(sh, "C102", "4.7u 50V", 121.92, 69.85, "VIN_PROT", fp=C1210),
            C(sh, "C103", "4.7u 50V", 134.62, 69.85, "VIN_PROT", fp=C1210)]
    fvp = sh.flag("VIN_PROT", (144.78, 58.42), label=False)
    fg = sh.flag("GND", (147.32, 81.28), label=False)
    r102 = R(sh, "R102", "100k", 160.02, 66.04, "VIN_PROT", "VIN_SENSE")
    r103 = R(sh, "R103", "10k", 160.02, 76.2, "VIN_SENSE", "GND")
    c104 = C(sh, "C104", "10n", 172.72, 73.66, "VIN_SENSE")
    sh.rail("VIN_RAW", 58.42, [j1["1"], tvs["2"], f1["1"], f2["1"]])
    sh.rail("VIN_PROT", 58.42, [q["S"], d102["1"]] + [c["1"] for c in caps] + [fvp["1"], r102["1"]], label="right")
    sh.rail("PFET_G", 69.85, [q["G"], r101["1"], d102["2"]])
    sh.rail("VIN_SENSE", 69.85, [r102["2"], r103["1"], c104["1"]], label="right")
    sh.rail("GND", 81.28, [j2["1"], tvs["1"], r101["2"]] + [c["2"] for c in caps] + [fg["1"], r103["2"], c104["2"]],
            tap=(101.6, (0, 1)))
    note(sh, 20.32, 96.52, [
        "D101 bidirectional TVS (33 V stand-off): a reversed input does not conduct.",
        "Q101 blocks a reversed input on the precision path; D102 limits VGS to -15 V.",
        "F102 / VIN_PT feed the 10 A pass-through shunt (output sheet) directly.",
        "VIN_SENSE = VIN x 10k / 110k  (30 V -> 2.73 V)"])

    # ---------------------------------------------------------------- housekeeping buck
    sh.box(15.24, 119.38, 205.74, 226.06, "Housekeeping buck 30 V -> 5 V (0.6 A)")
    c105 = C(sh, "C105", "2.2u 50V", 43.18, 160.02, "VIN_PROT", fp=C1206)
    u = sh.part("Regulator_Switching:LMR16006YQ", "U101", "LMR16006XDDCR", (71.12, 167.64), fp=SOT23_6,
                mpn="TI LMR16006XDDCR (700 kHz)")
    sh.net(u["2"], "GND")
    sh.link(u["4"], u["5"], "VIN_PROT")
    c106 = C(sh, "C106", "100n", 93.98, 161.29, "CB_5V", "SW_5V")
    d103 = D(sh, "Diode:SS16", "D103", "SS16", 104.14, 175.26, "SW_5V", "GND", rot=270, fp=SMA)
    l1 = sh.part("Device:L", "L101", "27u", (119.38, 167.64), 90, fp="Inductor_SMD:L_Sunlord_SWPA5040S",
                 mpn="27 uH, Isat >= 1 A (e.g. Sunlord SWPA5040S270MT)")
    r104 = R(sh, "R104", "56.2k", 137.16, 177.8, "+5V", "FB_5V")
    r105 = R(sh, "R105", "10k", 137.16, 195.58, "FB_5V", "GND")
    c107 = C(sh, "C107", "22u 10V", 149.86, 171.45, "+5V", fp=C0805)
    c108 = C(sh, "C108", "22u 10V", 162.56, 171.45, "+5V", fp=C0805)
    f5 = sh.flag("+5V", (172.72, 167.64), label=False)
    sh.rail("VIN_PROT", 152.4, [c105["1"], u["5"]], label="left")
    sh.rail("CB_5V", 157.48, [u["1"], c106["1"]])
    sh.rail("SW_5V", 167.64, [u["6"], c106["2"], d103["1"], l1["1"]])
    sh.rail("+5V", 167.64, [l1["2"], r104["1"], c107["1"], c108["1"], f5["1"]], tap=(129.54, (0, -1)))
    sh.rail("FB_5V", 187.96, [u["3"], r104["2"], r105["1"]])
    note(sh, 20.32, 208.28, [
        "VOUT = 0.765 V x (1 + R104/R105) = 5.06 V.  X version (700 kHz): the Y version at 2.1 MHz",
        "is at its 80 ns minimum on-time for 30 V -> 5 V.  D103: Schottky catch diode (asynchronous part).",
        "Loads: 3.3 V LDOs, relay coil (81 mA), isolated DC/DC, sense amps: about 250 mA total."])

    # ---------------------------------------------------------------- logic / analog rails
    sh.box(215.9, 20.32, 405.13, 111.76, "Logic and analog rails")
    c109 = C(sh, "C109", "10u", 238.76, 54.61, "+5V", fp=C0805)
    u2 = sh.part("Regulator_Linear:AMS1117-3.3", "U102", "AMS1117-3.3", (259.08, 50.8), fp=SOT223, lcsc="C6186")
    sh.net(u2["1"], "GND")
    c110 = C(sh, "C110", "22u", 276.86, 54.61, "+3V3", fp=C1206)
    c111 = C(sh, "C111", "100n", 287.02, 54.61, "+3V3")
    sh.rail("+5V", 50.8, [c109["1"], u2["3"]], tap=(228.6, (0, -1)))
    sh.rail("+3V3", 50.8, [u2["2"], c110["1"], c111["1"]], tap=(297.18, (0, -1)))
    c112 = C(sh, "C112", "1u", 320.04, 54.61, "+5V")
    u3 = sh.part("Regulator_Linear:TLV75533PDBV", "U103", "TLV75533PDBVR", (345.44, 53.34), fp=SOT23_5,
                 lcsc="C404027")
    sh.net(u3["2"], "GND"); sh.nc(u3["4"])
    c113 = C(sh, "C113", "1u", 363.22, 54.61, "+3.3VA")
    c114 = C(sh, "C114", "10u", 375.92, 54.61, "+3.3VA", fp=C0805)
    sh.rail("+5V", 50.8, [c112["1"], u3["1"]], tap=(309.88, (0, -1)))
    sh.link(u3["3"], u3["1"], "+5V")
    sh.rail("+3.3VA", 50.8, [u3["5"], c113["1"], c114["1"]], tap=(386.08, (0, -1)))
    fb = sh.part("Device:FerriteBead_Small", "FB101", "600R@100MHz", (243.84, 86.36), 90, fp=FB0805)
    c115 = C(sh, "C115", "10u", 256.54, 90.17, "+5VA", fp=C0805)
    c116 = C(sh, "C116", "100n", 266.7, 90.17, "+5VA")
    f5a = sh.flag("+5VA", (276.86, 86.36), label=False)
    sh.rail("+5V", 86.36, [fb["1"]], tap=(228.6, (0, -1)))
    sh.rail("+5VA", 86.36, [fb["2"], c115["1"], c116["1"], f5a["1"]], tap=(287.02, (0, -1)))
    note(sh, 309.88, 83.82, ["+3V3:  MCU, isolators, logic", "+3.3VA: INA190 ranges, MCU VDDA/VREF+, NTCs",
                             "+5VA:  setpoint DAC (DAC80502)"])

    # ---------------------------------------------------------------- op-amp supplies
    sh.box(215.9, 119.38, 405.13, 226.06, "Op-amp supplies (VOP / VNEG)")
    r106 = R(sh, "R106", "10R", 243.84, 147.32, "VIN_PROT", "VOP", rot=90, fp=R0805)
    c117 = C(sh, "C117", "10u 50V", 259.08, 151.13, "VOP", fp=C1210)
    c118 = C(sh, "C118", "100n 50V", 271.78, 151.13, "VOP")
    fvop = sh.flag("VOP", (281.94, 147.32), label=False)
    sh.rail("VOP", 147.32, [r106["2"], c117["1"], c118["1"], fvop["1"]], label="right")
    u4 = sh.part("Regulator_SwitchedCapacitor:LM2776", "U104", "LM2776DBVR", (322.58, 175.26), fp=SOT23_6,
                 lcsc="C69527", dnp=True)
    sh.net(u4["2"], "GND")
    sh.rail("+3V3", 162.56, [u4["3"], u4["4"]], tap=(317.5, (0, -1)))
    c119 = sh.part("Device:C", "C119", "1u", (302.26, 179.07), fp=C0603, dnp=True)
    sh.link(u4["5"], c119["1"], "CP_C1P")
    sh.link(u4["6"], c119["2"], "CP_C1N", via="v")
    c120 = C(sh, "C120", "2.2u", 342.9, 176.53, "VNEG_CP", dnp=True)
    r107 = sh.part("Device:R", "R107", "0R", (355.6, 172.72), 90, fp=R0603, dnp=True)
    r108 = R(sh, "R108", "0R", 368.3, 176.53, "VNEG", "GND")
    c121 = C(sh, "C121", "1u", 378.46, 176.53, "VNEG")
    fvn = sh.flag("VNEG", (386.08, 172.72), label=False)
    sh.rail("VNEG_CP", 172.72, [u4["1"], c120["1"], r107["1"]])
    sh.rail("VNEG", 172.72, [r107["2"], r108["1"], c121["1"], fvn["1"]], label="right")
    note(sh, 220.98, 203.2, [
        "Default (single supply): R108 fitted, U104 / C119 / C120 / R107 not fitted -> VNEG = GND.",
        "For a true 0 V output: fit U104, C119, C120, R107 and remove R108 (VNEG = -3.2 V).",
        "VOP + |VNEG| must stay <= 36 V (OPA2192 / OPA192 supply limit)."])
    return sh


# ============================================================ 2. tracking buck
def sheet_buck():
    sh = Sheet(P, "buck", "buck.kicad_sch", "Tracking buck pre-regulator")
    sh.box(15.24, 20.32, 405.13, 137.16, "LM76003 tracking pre-regulator: VPRE = VOUT + 1.5 V (2 V ... 27.5 V)")
    u = sh.part("e-psu:LM76003", "U201", "LM76003RNPR", (127.0, 101.6), fp="e-psu:TI_RNP0030B_WQFN-30",
                lcsc="C470958", mpn="TI LM76003RNPR")
    u.fpos = (-11.43, -21.59, "left")
    sh.nc(u["10"])
    # input
    cin = [C(sh, "C203", "100n 50V", 63.5, 77.47, "VIN_PROT"),
           C(sh, "C201", "4.7u 50V", 78.74, 77.47, "VIN_PROT", fp=C1210),
           C(sh, "C202", "4.7u 50V", 93.98, 77.47, "VIN_PROT", fp=C1210)]
    sh.rail("VIN_PROT", 73.66, [c["1"] for c in cin] + [u["20"]], label="left")
    r204 = R(sh, "R204", "100k", 86.36, 95.25, "BUCK_EN", "GND")
    sh.rail("BUCK_EN", 91.44, [u["18"], r204["1"]], label="left")
    c206 = C(sh, "C206", "1u", 93.98, 105.41, "+3V3")
    sh.link(u["17"], u["9"], "+3V3")
    sh.rail("+3V3", 101.6, [u["9"], c206["1"]], tap=(104.14, (0, -1)))
    c212 = C(sh, "C212", "22n", 104.14, 110.49, "SS_BUCK", dnp=True)
    sh.link(u["11"], c212["1"], "SS_BUCK")
    sh.rail("GND", 121.92, [u["13"], u["24"], u["7"], u["31"]], tap=(127.0, (0, 1)))
    # switch node, bootstrap, PGOOD, VCC
    c204 = C(sh, "C204", "470n", 149.86, 85.09, "SW_BUCK", "BOOT_BUCK")
    sh.link(u["6"], c204["2"], "BOOT_BUCK")
    l2 = sh.part("Device:L", "L201", "15u", (172.72, 73.66), 90, fp="Inductor_SMD:L_Wuerth_HCI-1350",
                 lcsc="C20415554", mpn="FANGCHENG FCH1365-150M (Isat 12 A)")
    sh.rail("SW_BUCK", 73.66, [u["1"], c204["1"], l2["1"]], tap=(157.48, (0, -1)))
    r205 = R(sh, "R205", "100k", 160.02, 90.17, "+3V3", "BUCK_PG")
    sh.rail("BUCK_PG", 93.98, [u["16"], r205["2"]], label="right")
    c205 = C(sh, "C205", "2.2u 10V", 149.86, 107.95, "VCC_BUCK")
    sh.link(u["8"], c205["1"], "VCC_BUCK")
    # output and feedback
    cout = [C(sh, "C%d" % (207 + i), "10u 50V", x, 77.47, "VPRE", fp=C1210)
            for i, x in enumerate((190.5, 205.74, 220.98, 236.22))]
    cout.append(C(sh, "C211", "47u 50V", 251.46, 77.47, "VPRE", lib_id="Device:C_Polarized",
                  fp="Capacitor_SMD:CP_Elec_8x10"))
    r201 = R(sh, "R201", "100k", 269.24, 90.17, "VPRE", "FB_BUCK")
    c213 = C(sh, "C213", "CFF", 281.94, 90.17, "VPRE", "FB_BUCK", dnp=True)
    r202 = R(sh, "R202", "100k", 269.24, 105.41, "FB_BUCK", "GND")
    r203 = R(sh, "R203", "3.16k 0.1%", 299.72, 99.06, "FB_BUCK", "BUCK_DAC", rot=90)
    r206 = R(sh, "R206", "100k", 325.12, 77.47, "VPRE", "VPRE_SENSE")
    r207 = R(sh, "R207", "10k", 325.12, 88.9, "VPRE_SENSE", "GND")
    c214 = C(sh, "C214", "10n", 337.82, 87.63, "VPRE_SENSE")
    sh.rail("VPRE", 73.66, [l2["2"]] + [c["1"] for c in cout] + [r201["1"], c213["1"], r206["1"]], label="right")
    sh.rail("FB_BUCK", 99.06, [u["12"], r201["2"], c213["2"], r202["1"], r203["1"]])
    sh.rail("VPRE_SENSE", 83.82, [r206["2"], r207["1"], c214["1"]], label="right")
    note(sh, 20.32, 45.72, [
        "VPRE = VFB (1 + R201/R202) + (VFB - V_BUCK_DAC) R201/R203,  VFB = 1.006 V",
        "BUCK_DAC 0.2 V -> 27.5 V;  1.0 V -> 2.0 V;  ~25 mV per G474 DAC step.",
        "MCU in reset: PA4 is high-impedance -> no injection -> VPRE = 2.0 V (safe default).",
        "Firmware rule: VPRE = measured VOUT + 1.5 V; raise VPRE before VOUT, lower VOUT before VPRE."])
    note(sh, 220.98, 129.54, [
        "RT open = 500 kHz.  SYNC/MODE high = forced PWM (VPRE can be pulled down).",
        "BIAS from +3V3 (VPRE leaves the 3.3-18 V BIAS range).  SS/TRK open = internal soft start.",
        "U201 footprint: TI RNP0030B (WQFN-30, 6 x 4 mm) is not in the KiCad library;",
        "import it from TI or LCSC/EasyEDA (C470958).  LM76005 (5 A) is pin-compatible."])

    sh.box(15.24, 144.78, 260.35, 190.5, "Optional gate-drive charge pump V_GATE = VIN + 10 V (not fitted)")
    y = 162.56
    r208 = R(sh, "R208", "100R", 45.72, y, "SW_BUCK", "PUMP_R", rot=90, dnp=True)
    c215 = sh.part("Device:C", "C215", "1n 100V", (63.5, y), 90, fp=C0603, dnp=True)
    sh.link(r208["2"], c215["1"], "PUMP_R")
    d201 = sh.part("Diode:1N4148W", "D201", "1N4148W", (81.28, y + 3.81), 270, fp=SOD123, dnp=True)
    d202 = sh.part("Diode:1N4148W", "D202", "1N4148W", (99.06, y), 180, fp=SOD123, dnp=True)
    c216 = sh.part("Device:C", "C216", "100n 50V", (119.38, y + 3.81), fp=C0603, dnp=True)
    d203 = sh.part("Device:D_Zener", "D203", "BZT52C10", (137.16, y + 3.81), 270, fp=SOD123, dnp=True)
    sh.rail("PUMP_A", y, [c215["2"], d201["1"], d202["2"]])
    sh.rail("V_GATE", y, [d202["1"], c216["1"], d203["1"]], label="right", ext=7.62)
    sh.rail("VIN_PROT", y + 12.7, [d201["2"], c216["2"], d203["2"]], label="left", ext=5.08)
    note(sh, 170.18, 177.8, ["Fit to raise the maximum output from ~24 V to ~27 V:",
                             "fit R208, C215, D201-D203, C216 and R315 (linear sheet),",
                             "remove R314."])
    return sh


# ============================================================ 3. linear stage
def sheet_linear():
    sh = Sheet(P, "linear", "linear.kicad_sch", "Linear CV/CC stage & setpoint DAC")
    # ---------------------------------------------------------------- pass element
    sh.box(15.24, 20.32, 205.74, 132.08, "Pass element, CC shunt and force node")
    q = sh.part("Transistor_FET:IRF540N", "Q301", "IRFP260N", (60.96, 66.04), fp="Package_TO_SOT_THT:TO-247-3_Vertical",
                lcsc="C2678", mpn="Infineon IRFP260NPBF on heatsink (or a linear-mode FET with DC SOA)")
    q.fpos = (5.08, -1.27, "left")
    sh.rail("VPRE", 50.8, [q["2"]], label="left", ext=7.62)
    r313 = R(sh, "R313", "100R", 40.64, 66.04, "GATE_DRV", "GATE", rot=90)
    d303 = D(sh, "Device:D_Zener", "D303", "BZT52C15", 50.8, 72.39, "GATE", "ZCLAMP", rot=270)
    d304 = D(sh, "Device:D_Zener", "D304", "BZT52C15", 50.8, 83.82, "VSRC", "ZCLAMP", rot=90)
    sh.rail("GATE", 66.04, [r313["2"], d303["1"], q["1"]])
    r301 = R(sh, "R301", "15m 1% 3W", 91.44, 91.44, "VSRC", "VFORCE", rot=90, fp=R2512, lcsc="C459682")
    sh.rail("VSRC", 91.44, [d304["1"], q["3"], r301["1"]])
    u = sh.part("e-psu:INAx_A_DBV", "U301", "INA293A2IDBVR", (111.76, 68.58), fp=SOT23_5, lcsc="C1855792")
    sh.link(u["3"], r301["1"], "VSRC", via="h")
    sh.link(u["4"], r301["2"], "VFORCE", via="h")
    sh.net(u["2"], "GND"); sh.net(u["1"], "I_3A")
    c301 = C(sh, "C301", "100n", 124.46, 52.07, "+5V")
    sh.rail("+5V", 48.26, [u["5"], c301["1"]], tap=(104.14, (0, -1)))
    r318 = R(sh, "R318", "100R", 109.22, 100.33, "VFORCE", "BLD_C")
    c313 = C(sh, "C313", "10u 50V", 127.0, 95.25, "VFORCE", fp=C1210)
    c314 = C(sh, "C314", "100n 50V", 139.7, 95.25, "VFORCE")
    sh.rail("VFORCE", 91.44, [r301["2"], r318["1"], c313["1"], c314["1"]], label="right", ext=5.08)
    bj = sh.part("Transistor_BJT:BCX56", "Q304", "BCX56-16", (106.68, 111.76), fp="Package_TO_SOT_SMD:SOT-89-3",
                 mpn="BCX56-16 (SOT-89, 1 W): ~0.25 W at 24 V / 10 mA")
    sh.net(bj["C"], "BLD_C"); sh.net(bj["E"], "BLD_E")
    r319 = R(sh, "R319", "68R", 109.22, 123.19, "BLD_E", "GND", fp=R0805)
    r320 = R(sh, "R320", "15k", 93.98, 107.95, "+3V3", "BLD_B")
    r321 = R(sh, "R321", "10k", 93.98, 119.38, "BLD_B", "GND")
    sh.rail("BLD_B", 111.76, [bj["B"], r320["2"], r321["1"]])
    r324 = R(sh, "R324", "10k", 167.64, 102.87, "+3.3VA", "NTC_PASS")
    th = sh.part("Device:Thermistor_NTC", "TH301", "10k B3380", (167.64, 116.84), fp=R0603, lcsc="C13564",
                 mpn="Murata NCP18XH103F03RB, on the heatsink side of Q301")
    sh.net(th["2"], "GND")
    c316 = C(sh, "C316", "100n", 182.88, 113.03, "NTC_PASS")
    sh.rail("NTC_PASS", 109.22, [r324["2"], th["1"], c316["1"]], label="right")
    note(sh, 20.32, 38.1, [
        "I_3A = 15 mOhm x 50 = 0.75 V/A (3.33 A full scale).  D303/D304: |VGS| <= 15.7 V.",
        "Q304: 10 mA bleeder at the force node keeps the loop in control at no load",
        "(it sits before the ranging shunts, so it is never measured)."])

    # ---------------------------------------------------------------- gate drive
    sh.box(15.24, 139.7, 205.74, 209.55, "Gate drive and hardware clamps")
    r314 = R(sh, "R314", "0R", 45.72, 152.4, "VIN_PROT", "VGATE_SUP", rot=90)
    r315 = R(sh, "R315", "0R", 45.72, 162.56, "V_GATE", "VGATE_SUP", rot=90, dnp=True)
    r312 = R(sh, "R312", "22k", 116.84, 158.75, "VGATE_SUP", "GATE_DRV")
    sh.rail("VGATE_SUP", 152.4, [r314["2"], r315["2"], r312["1"]])
    q2 = Q3(sh, "Transistor_FET:2N7002", "Q302", "2N7002", 55.88, 185.42, "GATE_HOLD", "GATE_DRV", "GND")
    r316 = R(sh, "R316", "10k", 45.72, 181.61, "+3V3", "GATE_HOLD")
    sh.rail("GATE_HOLD", 185.42, [q2["G"], r316["2"]], label="left")
    q3 = Q3(sh, "Transistor_FET:2N7002", "Q303", "2N7002", 96.52, 185.42, "OCP_TRIP", "GATE_DRV", "GND")
    r317 = R(sh, "R317", "100k", 86.36, 189.23, "OCP_TRIP", "GND")
    sh.rail("OCP_TRIP", 185.42, [q3["G"], r317["1"]], label="left")
    for qq in (q2, q3):
        qq.fpos = (5.08, -1.27, "left")
    d301 = D(sh, "Diode:1N4148W", "D301", "1N4148W", 124.46, 180.34, "CV_OUT", "GATE_DRV", rot=180)
    d302 = D(sh, "Diode:1N4148W", "D302", "1N4148W", 124.46, 190.5, "CC_OUT", "GATE_DRV", rot=180)
    sh.rail("GATE_DRV", 175.26, [q2["D"], q3["D"], (116.84, 175.26)], tap=(73.66, (0, -1)))
    sh.vrail("GATE_DRV", 116.84, [r312["2"], (116.84, 175.26), d301["2"], d302["2"]])
    note(sh, 20.32, 205.74, [
        "CV / CC amps only pull the gate down (D301, D302); R312 pulls it up.  Q302 holds the gate low until",
        "firmware releases GATE_HOLD (pull-up = output off at reset).  Q303: comparator trip (TIM20 break, us)."])

    # ---------------------------------------------------------------- setpoint DAC
    sh.box(15.24, 215.9, 205.74, 283.21, "Setpoint DAC: CV and CC references (0 ... 2.5 V)")
    dac = sh.part("Analog_DAC:DAC80502", "U304", "DAC80502DRXT", (88.9, 248.92),
                  fp="Package_SON:Texas_DRX_WSON-10_2.5x2.5mm_P0.5mm", lcsc="C2861168")
    sh.nets(dac, {"4": "GND", "3": "GND", "5": "GND", "6": "DAC_SCLK", "8": "DAC_SDIN", "7": "DAC_SYNC"})
    c310 = C(sh, "C310", "1u", 43.18, 234.95, "+5VA")
    c311 = C(sh, "C311", "100n", 55.88, 234.95, "+5VA")
    sh.rail("+5VA", 231.14, [c310["1"], c311["1"], dac["1"]], tap=(68.58, (0, -1)))
    c322 = C(sh, "C322", "220n", 152.4, 247.65, "VREF_DAC")
    sh.rail("VREF_DAC", 243.84, [dac["10"], c322["1"]])
    r310 = R(sh, "R310", "1k", 107.95, 248.92, "DAC_A", "DAC_CV_F", rot=90)
    c308 = C(sh, "C308", "100n", 124.46, 252.73, "DAC_CV_F")
    sh.link(dac["2"], r310["1"], "DAC_A")
    sh.rail("DAC_CV_F", 248.92, [r310["2"], c308["1"]], label="right")
    r311 = R(sh, "R311", "1k", 104.14, 259.08, "DAC_B", "DAC_CC_F")
    sh.link(dac["9"], r311["1"], "DAC_B", via="h")
    c309 = C(sh, "C309", "100n", 116.84, 270.51, "DAC_CC_F")
    sh.rail("DAC_CC_F", 266.7, [r311["2"], c309["1"]], label="right")
    note(sh, 160.02, 241.3, ["RSTSEL = GND: zero scale at", "power-up (0 V / 0 A).",
                             "SPI2C = GND: SPI mode.", "Firmware writes GAIN = 0x0103",
                             "(REF-DIV=1, gain 2) -> 2.5 V FS.", "CV: 0.4 mV/LSB, CC: 51 uA/LSB"])

    # ---------------------------------------------------------------- error amplifiers
    sh.box(215.9, 20.32, 405.13, 220.98, "Sense buffer (OPA192), CV / CC error amplifiers (OPA2192)")
    buf = sh.part("Amplifier_Operational:OPA197xD", "U303", "OPA192IDR", (264.16, 63.5), fp=SOIC8, lcsc="C2861286")
    r322 = R(sh, "R322", "1k", 248.92, 60.96, "VSENSE", "SNS_IN", rot=90)
    sh.net(buf["3"], "SNS_IN")
    c320 = C(sh, "C320", "100n 50V", 271.78, 49.53, "VOP")
    sh.rail("VOP", 45.72, [buf["7"], c320["1"]], label="left")
    sh.rail("VNEG", 76.2, [buf["4"]], label="right")
    sh.path("VS_BUF", [buf["2"], (254.0, 66.04), (254.0, 81.28), (281.94, 81.28)])
    r325 = R(sh, "R325", "90.9k 0.1%", 292.1, 67.31, "VS_BUF", "VOUT_ADC")
    r326 = R(sh, "R326", "10k 0.1%", 292.1, 82.55, "VOUT_ADC", "GND")
    c321 = C(sh, "C321", "10n", 304.8, 78.74, "VOUT_ADC")
    sh.rail("VOUT_ADC", 74.93, [r325["2"], r326["1"], c321["1"]], label="right")
    sh.rail("VS_BUF", 63.5, [buf["6"], (281.94, 63.5), r325["1"]])
    sh.vrail("VS_BUF", 281.94, [(281.94, 63.5), (281.94, 81.28), (281.94, 100.33)])
    # CV loop
    cv = sh.part("Amplifier_Operational:OPA2197xD", "U302", "OPA2192IDR", (350.52, 116.84), unit=1, fp=SOIC8,
                 lcsc="C110074")
    sh.net(cv["3"], "DAC_CV_F")
    r303 = R(sh, "R303", "90.9k 0.1%", 299.72, 111.76, "VS_BUF", "FBV")
    r304 = R(sh, "R304", "10k 0.1%", 299.72, 127.0, "FBV", "GND")
    c304 = C(sh, "C304", "5.6n C0G", 314.96, 100.33, "VFORCE", "FF_CV")
    r327 = R(sh, "R327", "8.2k", 314.96, 111.76, "FF_CV", "FBV")
    c305 = C(sh, "C305", "DNP", 325.12, 127.0, "FBV", "GND", dnp=True)
    sh.rail("VS_BUF", 100.33, [(281.94, 100.33), r303["1"]])
    sh.rail("VFORCE", 93.98, [c304["1"]], label="right")
    c306 = sh.part("Device:C", "C306", "1n C0G", (340.36, 134.62), 90, fp=C0603)
    r305 = sh.part("Device:R", "R305", "3.9k", (355.6, 134.62), 90, fp=R0603)
    sh.net(c306["2"], "CV_RC"); sh.net(r305["1"], "CV_RC")
    sh.rail("FBV", 119.38, [r303["2"], r304["1"], r327["2"], c305["1"], c306["1"], cv["2"]])
    sh.rail("CV_OUT", 116.84, [cv["1"], r305["2"]], label="right")
    # CC loop
    cc = sh.part("Amplifier_Operational:OPA2197xD", "U302", "OPA2192IDR", (350.52, 175.26), unit=2, fp=SOIC8,
                 lcsc="C110074")
    sh.net(cc["5"], "DAC_CC_F")
    r306 = R(sh, "R306", "10k", 320.04, 177.8, "I_3A", "FBI", rot=90)
    c307 = sh.part("Device:C", "C307", "1.5n C0G", (340.36, 193.04), 90, fp=C0603)
    r307 = sh.part("Device:R", "R307", "1k", (355.6, 193.04), 90, fp=R0603)
    sh.net(c307["2"], "CC_RC"); sh.net(r307["1"], "CC_RC")
    sh.rail("FBI", 177.8, [r306["2"], c307["1"], cc["6"]])
    r308 = R(sh, "R308", "100k", 370.84, 182.88, "CC_OUT", "CC_MON")
    r309 = R(sh, "R309", "10k", 370.84, 198.12, "CC_MON", "GND")
    c319 = C(sh, "C319", "10n", 383.54, 194.31, "CC_MON")
    sh.rail("CC_OUT", 175.26, [cc["7"], r307["2"], r308["1"]], label="right")
    sh.rail("CC_MON", 190.5, [r308["2"], r309["1"], c319["1"]], label="right")
    # op-amp supply
    pw = sh.part("Amplifier_Operational:OPA2197xD", "U302", "OPA2192IDR", (381.0, 63.5), unit=3, fp=SOIC8,
                 lcsc="C110074")
    pw.fpos = (-3.81, -1.27, "right")
    c302 = C(sh, "C302", "100n 50V", 391.16, 54.61, "VOP")
    c303 = C(sh, "C303", "100n", 391.16, 80.01, "VNEG")
    sh.rail("VOP", 50.8, [pw["8"], c302["1"]], label="left")
    sh.rail("VNEG", 76.2, [pw["4"], c303["1"]], label="left")
    note(sh, 220.98, 215.9, [
        "FBV = VS_BUF / 10.09 (DC, sense node); C304 + R327 feed the force node in at AC, so the loop",
        "stays stable in every shunt range.  FBI = I_3A (0.75 V/A).  Compensation verified in ngspice",
        "(sim/REPORT.md): CV PM >= 35 deg, CC PM >= 91 deg over load, range, C_load 0-1000 uF."])
    return sh


# ============================================================ 4. ranging
def iso_gnd(sh, pin, dy=5.08):
    """Island ground (VFORCE) symbol under a pin that points sideways."""
    sh.rail("VFORCE", pin.y + dy, [pin], tap=(pin.x, (0, 1)), style="sym")


def sheet_ranging():
    sh = Sheet(P, "ranging", "ranging.kicad_sch", "Current measurement & auto-ranging")
    # ---------------------------------------------------------------- shunt ladder
    sh.box(15.24, 20.32, 205.74, 127.0, "Shunt chain: force node -> 1 R -> 100 R -> sense node, with bypass FETs")
    A, B, Cx = 50.8, 88.9, 127.0
    r401 = R(sh, "R401", "1R 0.1%", 69.85, 45.72, "VFORCE", "N_MID", rot=90, fp=R0805, lcsc="C865286")
    d401 = sh.part("Diode:BAV99", "D401", "BAV199", (66.04, 63.5), 90, fp=SOT23, lcsc="C40919")
    q401 = sh.part("Transistor_FET:AO3400A", "Q401", "AO3400A", (69.85, 86.36), 90, fp=SOT23, lcsc="C20917")
    r402 = R(sh, "R402", "100R 0.1%", 107.95, 43.18, "N_MID", "VSENSE", rot=90, fp=R0805, lcsc="C110773")
    d402 = sh.part("Diode:BAV99", "D402", "BAV199", (104.14, 63.5), 90, fp=SOT23, lcsc="C40919")
    q402 = sh.part("Transistor_FET:AO3400A", "Q402", "AO3400A", (107.95, 88.9), 90, fp=SOT23, lcsc="C20917")
    r403 = R(sh, "R403", "10R", 64.77, 102.87, "G_A", "DRV_A")
    r404 = R(sh, "R404", "100k", 80.01, 96.52, "G_A", "N_MID", rot=90)
    r405 = R(sh, "R405", "10R", 102.87, 105.41, "G_B", "DRV_B")
    r406 = R(sh, "R406", "100k", 118.11, 99.06, "G_B", "VSENSE", rot=90)
    c401 = C(sh, "C401", "1u 50V", 137.16, 72.39, "VSENSE", fp=C0805)
    sh.vrail("VFORCE", A, [r401["1"], d401["2"], d401["1"], q401["D"]], tap=(38.1, (-1, 0)))
    sh.vrail("N_MID", B, [r401["2"], d401["3"], q401["S"], r404["2"], r402["1"], d402["2"], d402["1"], q402["D"]],
             tap=(50.8, (1, 0)))
    sh.vrail("VSENSE", Cx, [r402["2"], d402["3"], q402["S"], r406["2"], c401["1"]], tap=(38.1, (1, 0)))
    sh.rail("G_A", 96.52, [q401["G"], r404["1"], r403["1"]])
    sh.rail("DRV_A", 110.49, [r403["2"]], label="left")
    sh.rail("G_B", 99.06, [r405["1"], q402["G"], r406["1"]])
    sh.rail("DRV_B", 113.03, [r405["2"]], label="right")
    note(sh, 147.32, 45.72, ["R401 + R402: 30 mA and 300 uA ranges.",
                             "Q401 / Q402 short them for the 3 A range.",
                             "D401 / D402 (BAV199, 5 nA leakage) cap",
                             "the burden at ~0.6 V per shunt while",
                             "ranging up.  C401: <= 1 uF after the shunts."])

    # ---------------------------------------------------------------- range amplifiers
    sh.box(15.24, 134.62, 205.74, 254.0, "Range sense amplifiers (INA190A3, gain 100, 30 mV full scale)")
    for k, (y0, inp, inn, out, ra, rb, c, cd, ref) in enumerate([
            (165.1, "VFORCE", "N_MID", "I_30MA", "R407", "R408", "C402", "C403", "U401"),
            (220.98, "N_MID", "VSENSE", "I_300UA", "R409", "R410", "C404", "C405", "U402")]):
        a, b = f"IN{k + 1}P", f"IN{k + 1}N"
        ua = sh.part("e-psu:INA190_DDF", ref, "INA190A3IDDFR", (96.52, y0), fp=SOT23_8, lcsc="C1852076")
        rp = R(sh, ra, "10R", 55.88, y0 - 7.62, inp, a, rot=90)
        rn = R(sh, rb, "10R", 55.88, y0 + 7.62, inn, b, rot=90)
        cf = C(sh, c, "10n C0G", 68.58, y0, a, b)
        sh.rail(a, y0 - 7.62, [rp["2"], cf["1"], (78.74, y0 - 7.62)])
        sh.path(a, [(78.74, y0 - 7.62), (78.74, y0 - 2.54), ua["7"]])
        sh.rail(b, y0 + 7.62, [rn["2"], cf["2"], (81.28, y0 + 7.62)])
        sh.path(b, [(81.28, y0 + 7.62), (81.28, y0), ua["8"]])
        sh.vrail("GND", 83.82, [ua["3"]], tap=(y0 + 7.62, (0, 1)))
        sh.net(ua["4"], "GND"); sh.net(ua["5"], out)
        cdec = C(sh, cd, "100n", 119.38, y0 - 13.97, "+3.3VA")
        sh.rail("+3.3VA", y0 - 17.78, [ua["1"], cdec["1"], (111.76, y0 - 17.78)], tap=(91.44, (0, -1)))
        sh.path("+3.3VA", [ua["2"], (111.76, y0 - 2.54), (111.76, y0 - 17.78)])
    note(sh, 20.32, 250.19, [
        "I_30MA: 30 mA -> 3.0 V (8 uA/LSB @ 12 bit).  I_300UA: 300 uA -> 3.0 V (80 nA/LSB).",
        "Range-up in hardware: COMP1 (I_300UA) / COMP2 (I_30MA) trip the TIM1 / TIM8 break",
        "-> RANGE_B / RANGE_A latch high within ~1 us; firmware ranges down with hysteresis."])

    # ---------------------------------------------------------------- isolated island
    sh.box(215.9, 20.32, 405.13, 190.5, "Isolated gate-drive island (reference = VFORCE)")
    ps = sh.part("e-psu:B0505S", "PS401", "B0505S-1WR3", (254.0, 55.88), fp="Converter_DCDC:Converter_DCDC_Murata_MEE1SxxxxSC_THT",
                 lcsc="C2992394", mpn="B0505S-1WR3 (1 W, SIP-4; verify pinout vs maker drawing)")
    c406 = C(sh, "C406", "4.7u", 228.6, 57.15, "+5V", fp=C0805)
    sh.rail("+5V", 53.34, [c406["1"], ps["2"]], tap=(223.52, (0, -1)))
    sh.vrail("GND", 238.76, [ps["1"]], tap=(60.96, (0, 1)))
    iso_gnd(sh, ps["3"])
    c407 = sh.part("Device:C", "C407", "10u", (274.32, 57.15), fp=C1206)
    r411 = sh.part("Device:R", "R411", "330R", (284.48, 57.15), fp=R0805)
    ldo = sh.part("Regulator_Linear:AMS1117-3.3", "U403", "AMS1117-3.3", (304.8, 53.34), fp=SOT223, lcsc="C6186")
    c408 = sh.part("Device:C", "C408", "22u", (322.58, 57.15), fp=C1206)
    for p_ in (c407["2"], r411["2"], ldo["1"], c408["2"]):
        sh.net(p_, "VFORCE", label="sym")
    sh.rail("ISO_5V", 53.34, [ps["4"], c407["1"], r411["1"], ldo["3"]], tap=(269.24, (0, -1)))
    sh.rail("ISO_3V3", 53.34, [ldo["2"], c408["1"]], label="right")
    # isolator + driver
    iso = sh.part("e-psu:CA-IS3720", "U404", "CA-IS3720HS", (279.4, 116.84), fp=SOIC8, lcsc="C428882")
    c409 = C(sh, "C409", "100n", 264.16, 102.87, "+3V3")
    sh.rail("+3V3", 99.06, [c409["1"], iso["1"]], tap=(259.08, (0, -1)))
    sh.net(iso["2"], "RANGE_A"); sh.net(iso["3"], "RANGE_B")
    sh.vrail("GND", 266.7, [iso["4"]], tap=(127.0, (0, 1)))
    c410 = sh.part("Device:C", "C410", "100n", (309.88, 107.95), fp=C0603)
    sh.net(c410["2"], "VFORCE", label="sym")
    sh.rail("ISO_3V3", 104.14, [iso["8"], c410["1"]], tap=(299.72, (0, -1)))
    iso_gnd(sh, iso["5"])
    drv = sh.part("e-psu:UCC27524A", "U405", "UCC27524ADR", (335.28, 119.38), fp=SOIC8, lcsc="C185857")
    sh.path("ISO_A", [iso["7"], (304.8, 116.84), (304.8, 121.92), drv["2"]])
    sh.path("ISO_B", [iso["6"], (302.26, 119.38), (302.26, 124.46), drv["4"]])
    c411 = sh.part("Device:C", "C411", "1u", (355.6, 102.87), fp=C0603)
    c412 = sh.part("Device:C", "C412", "100n", (365.76, 102.87), fp=C0603)
    for p_ in (c411["2"], c412["2"]):
        sh.net(p_, "VFORCE", label="sym")
    sh.vrail("ISO_5V", 320.04, [drv["1"], drv["8"], (320.04, 99.06)])
    sh.rail("ISO_5V", 99.06, [(320.04, 99.06), drv["6"], c411["1"], c412["1"]], label="right")
    sh.net(drv["7"], "DRV_A"); sh.net(drv["5"], "DRV_B")
    iso_gnd(sh, drv["3"])
    r412 = R(sh, "R412", "100k", 236.22, 149.86, "+3V3", "RANGE_A")
    r413 = R(sh, "R413", "100k", 248.92, 149.86, "+3V3", "RANGE_B")
    sh.rail("+3V3", 143.51, [r412["1"], r413["1"]], tap=(242.57, (0, -1)))
    sh.rail("RANGE_A", 157.48, [r412["2"]], label="left")
    sh.rail("RANGE_B", 160.02, [r413["2"]], label="right")
    note(sh, 220.98, 182.88, [
        "The island floats at the force node, so the bypass FETs get VGS = 5 V at any output voltage.",
        "CA-IS3720HS (suffix H): outputs default HIGH while the MCU does not drive RANGE_A/B (reset)",
        "-> both bypass FETs on -> highest range (lowest burden).  R412/R413 make that explicit.",
        "R411: B0505S needs >= 20 mA (10 %) load; the island draws ~8 mA, R411 adds 15 mA.",
        "Keep the island compact; no copper of other nets under PS401 / U404 (isolation).",
        "Range bypass: RANGE_A -> Q401 (1 R), RANGE_B -> Q402 (100 R)."])
    return sh


# ============================================================ 5. output
def sheet_output():
    sh = Sheet(P, "output", "output.kicad_sch", "Pass-through & output switch")
    # ---------------------------------------------------------------- pass-through + relay
    sh.box(15.24, 20.32, 205.74, 132.08, "10 A pass-through measurement and mode relay")
    u = sh.part("e-psu:INAx_A_DBV", "U501", "INA281A3IDBVR", (86.36, 50.8), fp=SOT23_5, lcsc="C1517407")
    r501 = R(sh, "R501", "2m 1% 3W", 63.5, 71.12, "VIN_PT", "PT_SW", rot=90, fp=R2512, lcsc="C459679")
    sh.link(u["3"], r501["1"], "VIN_PT", via="h")
    sh.link(u["4"], r501["2"], "PT_SW", via="h")
    sh.net(u["2"], "GND"); sh.net(u["1"], "I_PT")
    c501 = C(sh, "C501", "100n", 111.76, 36.83, "+5V")
    sh.rail("+5V", 33.02, [u["5"], c501["1"]], tap=(80.01, (0, -1)))
    sh.rail("VIN_PT", 71.12, [r501["1"]], label="left", ext=7.62)
    k = sh.part("Relay:Relay_SPDT", "K501", "HF115F/005-1ZS3", (147.32, 93.98),
                fp="Relay_THT:Relay_SPDT_Schrack-RT1-16A-FormC_RM5mm", lcsc="C9225",
                mpn="Hongfa HF115F/005-1ZS3 (verify pin map vs RT1 footprint)")
    k.fpos = (12.7, -3.81, "left")
    sh.rail("PT_SW", 71.12, [r501["2"], k["14"]])
    sh.rail("VSENSE", 76.2, [k["12"]], label="left", ext=2.54)
    d501 = D(sh, "Diode:1N4148W", "D501", "1N4148W", 129.54, 88.9, "+5V", "RLY_DRV", rot=270)
    d501.fpos = (-2.54, -1.27, "right")
    sh.rail("+5V", 81.28, [k["A1"], d501["1"]], tap=(121.92, (0, -1)))
    q501 = Q3(sh, "Transistor_FET:AO3400A", "Q501", "AO3400A", 139.7, 116.84, "RLY_G", "RLY_DRV", "GND", lcsc="C20917")
    sh.rail("RLY_DRV", 106.68, [k["A2"], d501["2"], q501["D"]])
    r502 = R(sh, "R502", "100R", 119.38, 116.84, "RELAY_PT", "RLY_G", rot=90)
    r503 = R(sh, "R503", "100k", 127.0, 120.65, "RLY_G", "GND")
    sh.rail("RLY_G", 116.84, [q501["G"], r502["2"], r503["1"]])
    sh.rail("SW_IN", 109.22, [k["11"]], label="right")
    note(sh, 165.1, 63.5, ["I_PT = 2 mOhm x 100", "= 0.2 V/A (10 A -> 2.0 V).",
                           "Relay: NC = precision path",
                           "(default), NO = pass-through.",
                           "Switched only with the output", "switch off (no hot switching)."])

    # ---------------------------------------------------------------- output switch
    sh.box(15.24, 139.7, 205.74, 215.9, "Output switch: back-to-back N-FETs, photovoltaic gate driver")
    qa = sh.part("e-psu:Q_NMOS_SO8FL", "Q502", "NTMFS5C430N", (101.6, 160.02), fp="Package_SO:ONSemi_SO-8FL_488AA",
                 lcsc="C604436")
    qb = sh.part("e-psu:Q_NMOS_SO8FL", "Q503", "NTMFS5C430N", (101.6, 177.8), fp="Package_SO:ONSemi_SO-8FL_488AA",
                 lcsc="C604436", mirror="x")
    for qq in (qa, qb):
        qq.fpos = (5.08, -1.27, "left")
    sh.rail("SW_IN", 149.86, [qa["5"]], label="right", ext=5.08)
    sh.rail("OUT_P", 187.96, [qb["5"]], label="right", ext=5.08)
    r504 = sh.part("Device:R", "R504", "1M", (99.06, 170.18), 90, fp=R0603)
    r504.fpos = (0, 3.81, "left")
    sh.vrail("SRC_COM", 104.14, [qa["1"], qb["1"], r504["2"]], tap=(167.64, (1, 0)))
    pv = sh.part("e-psu:VOM1271", "U502", "VOM1271T", (76.2, 175.26), fp="Package_SO:SO-4_4.4x3.6mm_P2.54mm",
                 lcsc="C146286", mpn="Vishay VOM1271T (check output polarity: pin 4 = +, pin 3 = -)")
    sh.vrail("SW_GATE", 93.98, [qa["4"], qb["4"], r504["1"], pv["4"]])
    sh.rail("SRC_COM", 182.88, [pv["3"]], tap=(86.36, (0, 1)))
    r505 = R(sh, "R505", "82R", 58.42, 168.91, "+3V3", "PV_A")
    q505 = Q3(sh, "Transistor_FET:AO3400A", "Q505", "AO3400A", 45.72, 177.8, "OCP_TRIP", "PV_A", "GND", lcsc="C20917")
    sh.rail("PV_A", 172.72, [pv["1"], r505["2"], q505["D"]])
    q504 = Q3(sh, "Transistor_FET:AO3400A", "Q504", "AO3400A", 60.96, 195.58, "OUT_EN_G", "PV_K", "GND", lcsc="C20917")
    sh.path("PV_K", [pv["2"], (63.5, 175.26), q504["D"]])
    r506 = R(sh, "R506", "100R", 40.64, 195.58, "OUT_EN", "OUT_EN_G", rot=90)
    r507 = R(sh, "R507", "100k", 48.26, 199.39, "OUT_EN_G", "GND")
    sh.rail("OUT_EN_G", 195.58, [q504["G"], r506["2"], r507["1"]])
    note(sh, 127.0, 175.26, ["Works at any output voltage (0 ... 30 V).",
                             "LED 20 mA -> ~30 uA gate current:",
                             "turn-on ~3 ms, turn-off ~0.1 ms.",
                             "OCP_TRIP shorts the LED (Q505).",
                             "Q502 / Q503 share the source node:",
                             "both body diodes block when off."])

    # ---------------------------------------------------------------- terminals
    sh.box(215.9, 20.32, 405.13, 116.84, "Output terminals and terminal voltage sense")
    tvs = sh.part("Device:D_TVS", "D502", "SMBJ33CA", (243.84, 58.42), 90, fp=SMB, mpn="SMBJ33CA (bidirectional)")
    c502 = C(sh, "C502", "100n 50V", 256.54, 58.42, "OUT_P")
    r508 = R(sh, "R508", "1M 0.1%", 274.32, 58.42, "OUT_P", "VOUT_TERM")
    r509 = R(sh, "R509", "110k 0.1%", 274.32, 73.66, "VOUT_TERM", "GND")
    c503 = C(sh, "C503", "100n", 289.56, 69.85, "VOUT_TERM")
    j1 = sh.part("Connector_Generic:Conn_01x01", "J501", "OUT+", (322.58, 50.8), 0, fp=POST_R, mpn="Cliff FCR7350R")
    j2 = sh.part("Connector_Generic:Conn_01x01", "J502", "OUT-", (322.58, 86.36), 0, fp=POST_B, mpn="Cliff FCR7350B")
    sh.rail("OUT_P", 50.8, [tvs["2"], c502["1"], r508["1"], j1["1"]], label="left", ext=7.62)
    sh.rail("VOUT_TERM", 66.04, [r508["2"], r509["1"], c503["1"]], label="right")
    sh.rail("GND", 86.36, [tvs["1"], c502["2"], r509["2"], c503["2"], j2["1"]], tap=(231.14, (0, 1)))
    note(sh, 220.98, 109.22, [
        "VOUT_TERM = OUT_P / 10.09 at the terminals: firmware trims the CV setpoint for the relay +",
        "switch drop (slow outer loop) and subtracts the divider current (VOUT / 1.11 MOhm) from I."])
    return sh


# ============================================================ 6. MCU
def sheet_mcu():
    sh = Sheet(P, "mcu", "mcu.kicad_sch", "MCU, debug & user interface")
    sh.global_all = True
    sh.box(15.24, 20.32, 260.35, 205.74, "STM32G474RET6")
    u = sh.part("MCU_ST_STM32G4:STM32G474RETx", "U601", "STM32G474RET6", (165.1, 119.38),
                fp="Package_QFP:LQFP-64_10x10mm_P0.5mm", lcsc="C521608",
                mpn="STM32G474RET6 (fallback STM32G431RBT6, C431633)")
    pinmap = {
        "1": "+3V3", "2": "BTN", "3": None, "4": None, "5": "OSC_IN", "6": "OSC_OUT", "7": "NRST",
        "8": "NTC_PASS", "9": "I_3A", "10": None, "11": "NTC_BOARD", "12": None, "13": "I_300UA",
        "14": "UART_TX", "15": "GND", "16": "+3V3", "17": "UART_RX", "18": "BUCK_DAC", "19": None,
        "20": None, "21": "I_30MA", "22": "RELAY_PT", "23": "BUCK_PG", "24": "I_PT", "25": "VPRE_SENSE",
        "26": "OCP_TRIP", "27": "GND", "29": "+3.3VA", "30": None, "31": "GND",
        "32": "+3V3", "33": "VOUT_ADC", "34": "VIN_SENSE", "35": None, "36": "CC_MON", "37": "VOUT_TERM",
        "38": "RANGE_A", "39": "BUCK_EN", "40": "GATE_HOLD", "41": "OUT_EN", "42": "RANGE_B", "43": None,
        "44": "USB_CONNECT", "45": "USB_DM", "46": "USB_DP", "47": "GND", "48": "+3V3", "49": "SWDIO",
        "50": "SWCLK", "51": "DAC_SYNC", "52": "DAC_SCLK", "53": None, "54": "DAC_SDIN", "55": None,
        "56": "SWO", "57": None, "58": "LED_CV", "59": "LED_CC", "60": "LED_OUT", "61": "BOOT0",
        "62": "LED_PT", "63": "GND", "64": "+3V3"}
    sh.nets(u, pinmap)
    vref = u["28"]
    sh.vrail("+3.3VA", vref.x - 2.54, [vref], tap=(vref.y - 2.54, (0, -1)))
    # decoupling
    cd = [C(sh, "C%d" % (601 + i), "100n", x, 44.45, "+3V3") for i, x in enumerate((38.1, 50.8, 63.5, 76.2))]
    cd.append(C(sh, "C605", "4.7u", 88.9, 44.45, "+3V3", fp=C0805))
    cd.append(C(sh, "C610", "100n", 101.6, 44.45, "+3V3"))
    sh.rail("+3V3", 40.64, [c["1"] for c in cd], tap=(30.48, (0, -1)))
    ca = [C(sh, "C606", "1u", 210.82, 44.45, "+3.3VA"), C(sh, "C607", "10n", 223.52, 44.45, "+3.3VA"),
          C(sh, "C608", "1u", 236.22, 44.45, "+3.3VA"), C(sh, "C609", "100n", 248.92, 44.45, "+3.3VA")]
    sh.rail("+3.3VA", 40.64, [c["1"] for c in ca], tap=(200.66, (0, -1)))
    note(sh, 20.32, 58.42, ["One 100 nF per VDD pin (1, 16, 32, 48, 64) close to the pin; 1 uF + 10 nF on VDDA and VREF+."])
    # clock, reset, boot
    y = sh.part("Device:Crystal", "Y601", "8MHz", (50.8, 81.28), fp="Crystal:Crystal_SMD_HC49-SD", lcsc="C12674")
    y.fpos = (-3.81, -6.35, "left")
    c611 = C(sh, "C611", "27p C0G", 40.64, 85.09, "OSC_IN")
    c612 = C(sh, "C612", "27p C0G", 63.5, 85.09, "OSC_OUT")
    sh.rail("OSC_IN", 81.28, [c611["1"], y["1"]], label="left")
    sh.rail("OSC_OUT", 81.28, [y["2"], c612["1"]], label="right")
    c613 = C(sh, "C613", "100n", 45.72, 110.49, "NRST")
    sh.rail("NRST", 106.68, [c613["1"]], label="left")
    r601 = R(sh, "R601", "10k", 76.2, 110.49, "BOOT0", "GND")
    sh.rail("BOOT0", 106.68, [r601["1"]], label="left")
    # SWD
    j = sh.part("Connector_Generic:Conn_02x05_Odd_Even", "J601", "SWD", (50.8, 154.94),
                fp="Connector_PinHeader_1.27mm:PinHeader_2x05_P1.27mm_Vertical_SMD", lcsc="C5160761",
                mpn="Cortex debug 2x5 1.27 mm")
    sh.nets(j, {"2": "SWDIO", "4": "SWCLK", "6": "SWO", "10": "NRST", "7": None, "8": None})
    sh.vrail("+3V3", 43.18, [j["1"]], tap=(147.32, (0, -1)))
    sh.vrail("GND", 43.18, [j["3"], j["5"], j["9"]], tap=(162.56, (0, 1)))
    for ref, net, x in (("TP601", "UART_TX", 38.1), ("TP602", "UART_RX", 66.04)):
        tp = sh.part("Connector:TestPoint", ref, net, (x, 182.88), fp="TestPoint:TestPoint_Pad_D1.5mm")
        tp.fpos = (-2.54, -3.81, "right")
        sh.rail(net, 185.42, [tp["1"]], label="right")
    tp = sh.part("Connector:TestPoint", "TP603", "GND", (93.98, 182.88), fp="TestPoint:TestPoint_Pad_D1.5mm")
    sh.net(tp["1"], "GND")
    note(sh, 20.32, 200.66, ["UART log: USART2 (PA2 TX, PA3 RX), 3.3 V.  SWD: Cortex 10-pin, SWO on PB3."])

    # ---------------------------------------------------------------- user interface
    sh.box(266.7, 20.32, 405.13, 119.38, "User interface")
    r602 = R(sh, "R602", "10k", 287.02, 44.45, "+3V3", "BTN")
    c614 = C(sh, "C614", "100n", 297.18, 59.69, "BTN")
    sw = sh.part("Switch:SW_Push", "SW601", "OUTPUT", (317.5, 55.88), fp="Button_Switch_SMD:SW_SPST_PTS645")
    sh.rail("BTN", 55.88, [r602["2"], c614["1"], sw["1"]], label="left", ext=5.08)
    sh.vrail("GND", 325.12, [sw["2"]], tap=(60.96, (0, 1)))
    leds = []
    for i, (net, col, rv) in enumerate((("LED_CV", "green CV", "1k"), ("LED_CC", "red CC", "1k"),
                                         ("LED_OUT", "yellow OUT", "1k"), ("LED_PT", "blue PASS", "470R"))):
        yy = 78.74 + i * 8.89
        yy = round(round(yy / 1.27) * 1.27, 2)
        rl = R(sh, "R%d" % (603 + i), rv, 299.72, yy, net, "LEDA%d" % (i + 1), rot=90)
        led = sh.part("Device:LED", "D%d" % (601 + i), col, (325.12, yy), 180, fp=LED0603)
        sh.link(rl["2"], led["2"], "LEDA%d" % (i + 1))
        leds.append(led)
    sh.vrail("GND", 335.28, [l_["1"] for l_ in leds], tap=(leds[-1]["1"].y + 5.08, (0, 1)))

    # ---------------------------------------------------------------- temperature, mounting
    sh.box(266.7, 127.0, 405.13, 205.74, "Board temperature and mounting")
    r607 = R(sh, "R607", "10k", 284.48, 144.78, "+3.3VA", "NTC_BOARD")
    th = sh.part("Device:Thermistor_NTC", "TH601", "10k B3380", (284.48, 158.75), fp=R0603, lcsc="C13564")
    sh.net(th["2"], "GND")
    c615 = C(sh, "C615", "100n", 297.18, 154.94, "NTC_BOARD")
    sh.rail("NTC_BOARD", 151.13, [r607["2"], th["1"], c615["1"]], label="right")
    for i in range(4):
        sh.part("Mechanical:MountingHole", "H%d" % (601 + i), "M3", (335.28 + i * 15.24, 149.86),
                fp="MountingHole:MountingHole_3.2mm_M3")
    note(sh, 271.78, 200.66, [
        "Pin plan (STM32G474RE, LQFP-64):",
        "COMP1+ PA1 I_300UA -> TIM1 BRK -> PA8 RANGE_B",
        "COMP2+ PA7 I_30MA  -> TIM8 BRK -> PC6 RANGE_A",
        "COMP3+ PC1 I_3A, COMP4+ PB0 I_PT, COMP6+ PB11 VOUT_ADC",
        "  -> TIM20 BRK -> PB2 OCP_TRIP (idle state high)",
        "DAC1_OUT1 PA4 BUCK_DAC;  SPI3 PC10/PC12/PA15 -> DAC80502",
        "ADC: PC0 PC3 PB1 PB12 PB14 PB15 (temps, VPRE, VIN, CC_MON, VOUT_TERM)"])
    return sh


# ============================================================ 7. USB
def sheet_usb():
    sh = Sheet(P, "usb", "usb.kicad_sch", "Isolated USB")
    sh.sym_nets = {"GND_USB"}
    sh.box(15.24, 20.32, 152.4, 205.74, "PC side (GND_USB, powered from the USB cable)")
    sh.box(228.6, 20.32, 405.13, 205.74, "e-psu side (GND, +3V3)")
    j = sh.part("Connector:USB_C_Receptacle_USB2.0_16P", "J701", "USB-C", (58.42, 101.6),
                fp="Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12", lcsc="C165948")
    j.fpos = (-10.16, -22.86, "left")
    sh.net(j["A5"], "CC1"); sh.net(j["B5"], "CC2")
    for pn in ("A1", "A12", "B1", "B12"):
        sh.net(j[pn], "GND_USB")
    sh.nc(j["A8"]); sh.nc(j["B8"])
    sh.link(j["A7"], j["B7"], "USB_C_DM")
    sh.link(j["A6"], j["B6"], "USB_C_DP")
    esd = sh.part("Power_Protection:USBLC6-2SC6", "U701", "USBLC6-2SC6", (101.6, 101.6), fp=SOT23_6, lcsc="C7519")
    sh.net(esd["2"], "GND_USB")
    sh.rail("USB_C_DM", 101.6, [j["B7"], esd["1"]], tap=(86.36, (0, -1)))
    sh.rail("USB_C_DP", 104.14, [j["A6"], esd["3"]], tap=(88.9, (0, 1)))
    fb = sh.part("Device:FerriteBead_Small", "FB701", "600R@100MHz", (124.46, 78.74), 90, fp=FB0805)
    sh.rail("VBUS_C", 78.74, [j["A4"], esd["5"], fb["1"]])
    c702 = C(sh, "C702", "4.7u", 134.62, 82.55, "VBUS_ISO", "GND_USB", fp=C0805)
    c703 = C(sh, "C703", "100n", 147.32, 82.55, "VBUS_ISO", "GND_USB")
    fv = sh.flag("VBUS_ISO", (157.48, 78.74), label=False)
    r705 = R(sh, "R705", "24R 1%", 160.02, 101.6, "USB_C_DM", "UDM", rot=90)
    r705.fpos = (-3.81, -5.08, "left")
    r704 = R(sh, "R704", "24R 1%", 172.72, 104.14, "USB_C_DP", "UDP", rot=90)
    sh.rail("USB_C_DM", 101.6, [esd["6"], r705["1"]], tap=(116.84, (0, -1)))
    sh.rail("USB_C_DP", 104.14, [esd["4"], r704["1"]], tap=(119.38, (0, 1)))
    # isolator straddles the barrier
    iso = sh.part("e-psu:ADuM3160", "U702", "ADuM3160BRWZ-RL", (205.74, 99.06),
                  fp="Package_SO:SOIC-16W_7.5x10.3mm_P1.27mm", lcsc="C284149")
    sh.rail("VBUS_ISO", 78.74, [fb["2"], c702["1"], c703["1"], fv["1"], iso["1"]])
    sh.rail("UDM", 101.6, [r705["2"], iso["6"]])
    sh.rail("UDP", 104.14, [r704["2"], iso["7"]])
    c704 = C(sh, "C704", "1u", 180.34, 87.63, "VDD1_USB", "GND_USB")
    c705 = C(sh, "C705", "100n", 167.64, 87.63, "VDD1_USB", "GND_USB")
    sh.vrail("VDD1_USB", 190.5, [iso["3"], iso["4"], iso["5"], (190.5, 83.82)])
    sh.rail("VDD1_USB", 83.82, [(190.5, 83.82), c704["1"], c705["1"]])
    sh.vrail("GND_USB", 190.5, [iso["2"]], tap=(113.03, (0, 1)))
    note(sh, 196.85, 124.46, ["isolation", "barrier (U702)"])
    # CC, shield, ground flag
    r701 = R(sh, "R701", "5.1k", 63.5, 148.59, "CC1", "GND_USB")
    r702 = R(sh, "R702", "5.1k", 83.82, 148.59, "CC2", "GND_USB")
    sh.rail("CC1", 142.24, [r701["1"]], label="left")
    sh.rail("CC2", 142.24, [r702["1"]], label="left")
    r703 = R(sh, "R703", "1M", 43.18, 133.35, "USB_SHIELD", "GND_USB")
    c701 = C(sh, "C701", "4.7n 1kV", 27.94, 133.35, "USB_SHIELD", "GND_USB", fp=C1206)
    sh.rail("USB_SHIELD", 129.54, [j["S1"], r703["1"], c701["1"]])
    fg = sh.flag("GND_USB", (114.3, 121.92), label=False)
    sh.rail("GND_USB", 121.92, [fg["1"]], tap=(114.3, (0, 1)))
    note(sh, 20.32, 200.66, [
        "Full speed: SPU = SPD = high.  PDEN = VDD1 (normal operation).  24 R +/-1 % on all four data lines.",
        "USBLC6 pins 1-6 / 3-4 are flow-through pairs: route D-/D+ across the pads."])
    # e-psu side
    sh.vrail("+3V3", 220.98, [iso["16"], iso["14"], iso["13"], (220.98, 83.82)])
    c706 = C(sh, "C706", "1u", 299.72, 87.63, "+3V3")
    c707 = C(sh, "C707", "100n", 312.42, 87.63, "+3V3")
    sh.rail("+3V3", 83.82, [(220.98, 83.82), c706["1"], c707["1"]], tap=(231.14, (0, -1)))
    sh.net(iso["12"], "USB_CONNECT")
    r707 = R(sh, "R707", "24R 1%", 256.54, 101.6, "DDM", "USB_DM", rot=90)
    r707.fpos = (-3.81, -5.08, "left")
    r706 = R(sh, "R706", "24R 1%", 287.02, 104.14, "DDP", "USB_DP", rot=90)
    sh.rail("DDM", 101.6, [iso["11"], r707["1"]])
    sh.rail("DDP", 104.14, [iso["10"], r706["1"]])
    sh.vrail("GND", 220.98, [iso["9"]], tap=(113.03, (0, 1)))
    r708 = R(sh, "R708", "100k", 243.84, 129.54, "USB_CONNECT", "GND")
    sh.rail("USB_CONNECT", 125.73, [r708["1"]], label="left")
    note(sh, 226.06, 200.66, [
        "USB_CONNECT (PA10) enables the PC-side pull-up only when the USB stack is ready",
        "(re-enumerate by pulling it low for ~100 ms).  VBUS2 = VDD2 = +3V3 (regulator bypassed).",
        "Layout: >= 8 mm creepage under U702, no copper on any layer crossing it; 90 Ohm D+/D- pairs."])
    return sh


sheets = [sheet_power(), sheet_buck(), sheet_linear(), sheet_ranging(), sheet_output(), sheet_mcu(), sheet_usb()]
DESC = [
    ["30 V input, reverse-polarity P-FET, TVS, fuses", "LMR16006X 30 V -> 5 V housekeeping buck",
     "+3V3 (AMS1117), +3.3VA (TLV755), +5VA", "VOP filter, optional LM2776 VNEG"],
    ["LM76003 synchronous buck, 500 kHz", "VPRE tracks VOUT + 1.5 V via DAC injection",
     "into FB (BUCK_DAC from PA4)", "Optional V_GATE charge pump (not fitted)"],
    ["IRFP260N source follower + 15 mOhm CC shunt", "OPA2192 CV / CC error amps, OPA192 buffer",
     "DAC80502 16-bit setpoints (SPI)", "Gate hold / OCP clamp, no-load bleeder"],
    ["1 R + 100 R ranging shunts with BAV199 clamps", "AO3400A bypass FETs on a VFORCE island",
     "(B0505S, CA-IS3720HS, UCC27524A)", "INA190A3 range amplifiers"],
    ["10 A pass-through: 2 mOhm + INA281A3", "HF115F mode relay (NC = precision path)",
     "Back-to-back NTMFS5C430N output switch", "VOM1271 driver, output TVS, VOUT_TERM"],
    ["STM32G474RET6, 8 MHz crystal, SWD", "COMP + TIM break for us range-up / OCP",
     "Buttons, 4 status LEDs, board NTC", ""],
    ["USB-C (USB 2.0 FS), USBLC6 ESD", "ADuM3160 2.5 kV isolator",
     "PC side powered from VBUS", ""],
]
for sh_, d_ in zip(sheets, DESC):
    sh_.desc = [x for x in d_ if x]

ROOT_NOTES = [
    ("e-psu  rev A", 30.48, 30.48, 2.54, True),
    ("USB-controlled precision power stage for a bench PSU: 0-24 V / 0-3 A CV/CC with uA-resolution current ranging,\n"
     "plus a measured 10 A pass-through.  github.com/embedded-pro/e-psu", 30.48, 38.1, 1.5, False),
    ("Power flow:  bench PSU (30 V) -> input protection -> tracking buck (VPRE = VOUT + 1.5 V) -> linear CV/CC stage\n"
     "-> force node -> ranging shunts (1 R / 100 R) -> sense node -> mode relay -> back-to-back output switch -> OUT\n"
     "Pass-through:  bench PSU -> 15 A fuse -> 2 mOhm shunt -> mode relay (NO) -> output switch -> OUT", 30.48, 190.5, 1.5, False),
    ("Ground domains:  GND (main board) | GND_USB (PC side of U702) | VFORCE island (range-drive, floats with the output).\n"
     "Generated schematic: run ERC in KiCad 7+ after opening. U201 footprint (TI RNP0030B) must be imported.", 30.48, 210.82, 1.5, False),
]

P.build(OUT, "e-psu: precision USB power stage", [(t, x, y, s, b) for (t, x, y, s, b) in ROOT_NOTES],
        date="2026-11-03", rev="A1", company="embedded-pro")
json.dump({k: sorted(v) for k, v in P.expected.items()}, open(os.path.join(OUT, "..", "gen", "expected.json"), "w"), indent=0)
with open(os.path.join(OUT, "sym-lib-table"), "w") as f:
    f.write('(sym_lib_table\n  (lib (name "e-psu")(type "KiCad")(uri "${KIPRJMOD}/e-psu.kicad_sym")(options "")(descr "e-psu project symbols"))\n)\n')

if __name__ == "__main__":
    import erc
    errs, warns = erc.run(P)
    fps = erc.check_footprints(P)
    print("ERC errors:", len(errs))
    for e in errs:
        print("  E", e)
    print("ERC warnings:", len(warns))
    for w in warns:
        print("  W", w)
    print("Layout lint:", len(getattr(P, "lint", [])))
    for l in getattr(P, "lint", []):
        print("  L", l)
    print("Footprint check:", len(fps))
    for f in fps:
        print("  F", f)
