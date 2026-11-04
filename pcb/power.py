"""Power copper plan (board coordinates in mm, origin = board top-left).

Each zone is (net, layer, shape, options). Shapes are unions of boxes; copper.py clips them to the board,
cuts clearance around other-net pads and earlier zones on the same layer, and turns enclosed
other-net pads into escape channels, so the outlines here can be rough.

Layer use:
  F.Cu  : parts, short power pours, signals
  In1.Cu: GND plane, split for the isolated USB side (GND_USB) and the ranging island (VFORCE)
  In2.Cu: power distribution (10 A highway copy, VIN_PROT, VPRE, VSENSE, +5V, +3V3); no signals
  B.Cu  : 10 A highway copy, signals, GND fill
"""
from shapely.geometry import box, Polygon
from shapely.ops import unary_union

BW = BH = 100.0

VIN_RAW = "Net-(D101-A2)"
Q101_D = "Net-(Q101-D)"
PT_SW = "Net-(U501-IN-)"
SRC_COM = "/Pass-through & output switch/SRC_COM"
OUT_P = "/Pass-through & output switch/OUT_P"
SW_IN = "/Pass-through & output switch/SW_IN"
SW_BUCK = "/Tracking buck pre-regulator/SW_BUCK"
D304K = "Net-(D304-K)"
N_MID = "/Current measurement & auto-ranging/N_MID"


def U(*boxes):
    return unary_union([box(*b) for b in boxes])


# ---- shapes ---------------------------------------------------------------------------------------------
S = {
    # 10 A highway: J101 -> F102 -> R501 -> K501 NO/COM -> Q502/Q503 -> J501
    "vin_raw": U((1.0, 6.4, 25.0, 14.0), (5.0, 6.4, 14.2, 19.6), (14.2, 14.0, 20.2, 21.8)),
    "vin_pt": U((27.3, 6.4, 40.0, 13.6)),
    "pt_sw": U((46.0, 1.0, 80.2, 6.6), (46.0, 1.0, 49.6, 10.4), (75.4, 1.0, 80.2, 19.6)),
    "sw_in": U((68.7, 8.2, 73.9, 28.5)),
    "src_com": U((74.6, 23.0, 78.2, 28.0)),
    "out_p": U((80.2, 11.2, 99.3, 18.9), (79.3, 18.9, 84.4, 28.5)),
    # 3 A precision path: F101 -> Q101 -> VIN_PROT -> buck -> VPRE -> Q301 -> R301 -> ranging -> VSENSE -> K501 NC
    "q101_d": U((22.5, 14.6, 32.4, 24.3)),
    "vin_prot_f": U((28.4, 24.6, 33.4, 37.0), (25.6, 33.0, 33.4, 37.0)),
    "sw_buck": U((34.8, 28.6, 38.45, 41.6), (33.4, 41.0, 38.4, 46.8)),
    "vpre_f": U((44.0, 43.2, 57.6, 49.2), (44.6, 49.2, 58.0, 52.4)),
    "d304k": U((89.0, 53.4, 99.4, 59.9)),
    "vforce_bar": U((79.0, 53.6, 83.0, 63.0)),
    "nmid_bar": U((73.0, 54.9, 78.4, 63.0)),
    "vsense_bar": U((66.0, 55.5, 72.2, 63.0)),
    # In2 distribution
    "vin_prot_i2": U((22.6, 24.6, 47.6, 33.4), (1.0, 33.4, 31.0, 49.5)),
    "vpre_i2": U((44.0, 41.0, 58.0, 56.5), (52.0, 56.5, 58.0, 68.0), (52.0, 64.0, 92.0, 68.0), (89.2, 47.8, 99.3, 68.0)),
    "vsense_i2": U((64.6, 8.4, 68.4, 63.0), (64.6, 55.0, 72.4, 63.0)),
    "p5v_i2": U((1.0, 49.8, 31.0, 66.0)),
    "p3v3_i2": U((22.6, 70.8, 70.4, 99.4)),
    # In1 splits
    "usb_i1": U((0.6, 69.0, 20.6, 99.4)),
    "island_i1": Polygon([(71.6, 76.6), (88.7, 76.6), (88.7, 81.6), (99.4, 81.6), (99.4, 99.4), (71.6, 99.4)]),
}
S["gnd_i1"] = box(0, 0, BW, BH).difference(S["usb_i1"].buffer(1.0, join_style=2)).difference(
    S["island_i1"].buffer(1.0, join_style=2))

HC = dict(clr=0.3, connect="tht_thermal", spoke=1.0)       # high-current pours
PL = dict(clr=0.3, connect="full")                         # planes

# order matters: earlier zones win the area on their layer
ZONES = [
    # (name, net, layer, shape, opts)
    ("vin_raw", VIN_RAW, "F.Cu", S["vin_raw"], HC),
    ("vin_pt", "VIN_PT", "F.Cu", S["vin_pt"], HC),
    ("pt_sw", PT_SW, "F.Cu", S["pt_sw"], HC),
    ("sw_in", SW_IN, "F.Cu", S["sw_in"], HC),
    ("src_com", SRC_COM, "F.Cu", S["src_com"], HC),
    ("out_p", OUT_P, "F.Cu", S["out_p"], HC),
    ("q101_d", Q101_D, "F.Cu", S["q101_d"], HC),
    ("vin_prot", "VIN_PROT", "F.Cu", S["vin_prot_f"], HC),
    ("sw_buck", SW_BUCK, "F.Cu", S["sw_buck"], HC),
    ("vpre", "VPRE", "F.Cu", S["vpre_f"], HC),
    ("d304k", D304K, "F.Cu", S["d304k"], HC),
    ("vforce_bar", "VFORCE", "F.Cu", S["vforce_bar"], HC),
    ("nmid_bar", N_MID, "F.Cu", S["nmid_bar"], HC),
    ("vsense_bar", "VSENSE", "F.Cu", S["vsense_bar"], HC),

    ("vin_raw", VIN_RAW, "B.Cu", S["vin_raw"], HC),
    ("vin_pt", "VIN_PT", "B.Cu", S["vin_pt"], HC),
    ("pt_sw", PT_SW, "B.Cu", S["pt_sw"], HC),
    ("sw_in", SW_IN, "B.Cu", S["sw_in"], HC),
    ("out_p", OUT_P, "B.Cu", S["out_p"], HC),

    ("vin_raw", VIN_RAW, "In2.Cu", S["vin_raw"], HC),
    ("vin_pt", "VIN_PT", "In2.Cu", S["vin_pt"], HC),
    ("sw_in", SW_IN, "In2.Cu", S["sw_in"], HC),
    ("vsense", "VSENSE", "In2.Cu", S["vsense_i2"], HC),
    ("pt_sw", PT_SW, "In2.Cu", S["pt_sw"], HC),
    ("out_p", OUT_P, "In2.Cu", S["out_p"], HC),
    ("vin_prot", "VIN_PROT", "In2.Cu", S["vin_prot_i2"], PL),
    ("vpre", "VPRE", "In2.Cu", S["vpre_i2"], HC),
    ("p5v", "+5V", "In2.Cu", S["p5v_i2"], PL),
    ("p3v3", "+3V3", "In2.Cu", S["p3v3_i2"], PL),

    ("gnd_usb", "GND_USB", "In1.Cu", S["usb_i1"], PL),
    ("island", "VFORCE", "In1.Cu", S["island_i1"], PL),
    ("gnd", "GND", "In1.Cu", S["gnd_i1"], PL),
]

# nets whose pours are joined across layers with via arrays: (net, layers, max vias)
STITCH = [
    (VIN_RAW, ("F.Cu", "In2.Cu", "B.Cu"), 24),
    ("VIN_PT", ("F.Cu", "In2.Cu", "B.Cu"), 24),
    (PT_SW, ("F.Cu", "In2.Cu", "B.Cu"), 30),
    (SW_IN, ("F.Cu", "In2.Cu", "B.Cu"), 20),
    (OUT_P, ("F.Cu", "In2.Cu", "B.Cu"), 24),
    ("VPRE", ("F.Cu", "In2.Cu"), 16),
    ("VSENSE", ("F.Cu", "In2.Cu"), 12),
    ("VIN_PROT", ("F.Cu", "In2.Cu"), 10),
]

# Kelvin sense traces (locked): (net, width, path). The path starts on F.Cu; a "B"/"F" token puts a via at
# the previous point and continues on that layer.
KELVIN = [
    # U501 is rotated so its IN+/IN- pins face the shunt; the two sense lines cross, IN+ on B.Cu
    ("VIN_PT", 0.25, [(40.35, 9.9), (40.35, 10.8), (41.0, 11.4), "B", (44.9, 12.6), "F", (44.1, 13.5)]),  # R501.1 -> U501 IN+
    (PT_SW, 0.25, [(45.65, 9.9), (45.65, 10.8), (42.6, 12.8), (41.9, 13.5)]),                            # R501.2 -> U501 IN-
    (D304K, 0.25, [(88.6, 59.45), (88.6, 61.35), (87.135, 61.35)]),      # R301.1 -> U301 IN+
    ("VFORCE", 0.25, [(83.4, 59.45), (83.4, 61.35), (84.865, 61.35)]),   # R301.2 -> U301 IN-
]


def kelvin_segments():
    """(net, width, layer, a, b) segments and (net, x, y) vias of the Kelvin paths."""
    segs, vias = [], []
    for net, w, path in KELVIN:
        layer, prev = "F.Cu", None
        for item in path:
            if isinstance(item, str):
                vias.append((net, prev[0], prev[1]))
                layer = "B.Cu" if item == "B" else "F.Cu"
                continue
            if prev is not None and prev != item:
                segs.append((net, w, layer, prev, item))
            prev = item
    return segs, vias


def placement_keepouts():
    """F.Cu pour areas that auto-placed parts must stay out of."""
    return [shape for (_, _, layer, shape, _) in ZONES if layer == "F.Cu"]
