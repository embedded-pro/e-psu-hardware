"""Project symbol library e-psu.kicad_sym: parts missing from KiCad's standard libraries.
Pinouts are from the manufacturers' datasheets (see notes beside each)."""
import copy
from sexp import Q, find, findall
from symgen import ic_symbol, write_lib
from lib import get_symbol

P, PI, PO, I, O, B, OC, NCt = "passive", "power_in", "power_out", "input", "output", "bidirectional", "open_collector", "no_connect"


def renumber(src_lib_id, new_name, mapping, ref=None, value=None):
    """Copy a library symbol, renaming it and renumbering pins.
    mapping: old pin number -> list of new numbers (extra numbers become stacked pins)."""
    sym = get_symbol(src_lib_id)
    old = sym[1].split(":", 1)[1]
    out = ["symbol", Q(new_name)]
    for x in sym[2:]:
        if isinstance(x, list) and x and x[0] == "symbol":
            sub = copy.deepcopy(x)
            sub[1] = Q(sub[1].replace(old, new_name, 1))
            newsub = sub[:2]
            for g in sub[2:]:
                if isinstance(g, list) and g and g[0] == "pin":
                    num = str(find(g, "number")[1])
                    for k, nn in enumerate(mapping.get(num, [num])):
                        pg = copy.deepcopy(g)
                        find(pg, "number")[1] = Q(nn)
                        if k > 0:
                            # stacked duplicate (KLC S4.3): invisible + passive
                            pg[1] = "passive"
                            pg.insert(5, "hide")
                        newsub.append(pg)
                else:
                    newsub.append(g)
            out.append(newsub)
        elif isinstance(x, list) and x and x[0] == "property":
            p = copy.deepcopy(x)
            if p[1] == "Reference" and ref:
                p[2] = Q(ref)
            if p[1] == "Value" and value:
                p[2] = Q(value)
            if p[1] == "Footprint":
                p[2] = Q("")
            out.append(p)
        else:
            out.append(copy.deepcopy(x))
    return out


def power_alias(src, net, desc):
    """Copy a power symbol (e.g. power:GNDREF) as a project power symbol for `net`."""
    sym = renumber(src, net, {}, value=net)
    for x in sym:
        if isinstance(x, list) and x and x[0] == "property" and x[1] == "ki_description":
            x[2] = Q(desc)
        if isinstance(x, list) and x and x[0] == "symbol":
            for g in x:
                if isinstance(g, list) and g and g[0] == "pin":
                    find(g, "name")[1] = Q(net)
    return sym


def build(path):
    syms = []
    syms.append(power_alias("power:GNDREF", "VFORCE",
                            "Island reference: the floating range-drive supply is referred to VFORCE"))
    syms.append(power_alias("power:GNDPWR", "GND_USB", "PC-side ground of the USB isolator (from the USB cable)"))
    # TI LM76003 (WQFN-30 RNP), datasheet SNVSAK0A "Pin Functions". NC pins: "connect to ground copper".
    syms.append(ic_symbol(
        "LM76003", "U",
        left=[(["20", "21", "22"], "PVIN", PI), None, (["18"], "EN", I), None, None, (["17"], "SYNC/MODE", I),
              (["9"], "BIAS", PI), (["10"], "RT", P), (["11"], "SS/TRK", P)],
        right=[(["1", "2", "3", "4", "5"], "SW", PO), (["6"], "BOOT", P), None, (["16"], "PGOOD", OC), None,
               (["12"], "FB", I), None, (["8"], "VCC", PO)],
        bottom=[(["13", "14", "15"], "AGND", PI), (["24", "25", "26"], "PGND", PI),
                (["7", "19", "23", "27", "28", "29", "30"], "NC(GND)", P), (["31"], "EP", P)],
        width=25.4, value="LM76003RNPR",
        ds="https://www.ti.com/lit/ds/symlink/lm76003.pdf",
        desc="60 V 3.5 A synchronous buck, WQFN-30 (RNP)"))
    # ADI ADuM3160/ADuM4160 (SOIC-16W), datasheet Rev. D Table 9.
    syms.append(ic_symbol(
        "ADuM3160", "U",
        left=[("1", "VBUS1", PI), ("3", "VDD1", PO), ("4", "PDEN", I), ("5", "SPU", I), None,
              ("6", "UD-", B), ("7", "UD+", B), None, (["2", "8"], "GND1", PI)],
        right=[("16", "VBUS2", PI), ("14", "VDD2", PI), ("13", "SPD", I), ("12", "PIN", I), None,
               ("11", "DD-", B), ("10", "DD+", B), None, (["9", "15"], "GND2", PI)],
        width=20.32, value="ADuM3160BRWZ",
        ds="https://www.analog.com/media/en/technical-documentation/data-sheets/ADuM3160.pdf",
        desc="Full/low-speed USB isolator, 2.5 kV"))
    # Vishay VOM1271 photovoltaic MOSFET driver (SOP-4): 1 A, 2 K, 4 +, 3 - (per datasheet Fig. 10 labels)
    syms.append(ic_symbol(
        "VOM1271", "U",
        left=[("1", "A", P), ("2", "K", P)],
        right=[("4", "+", P), ("3", "-", P)],
        width=12.7, value="VOM1271T", ds="https://www.vishay.com/docs/83469/vom1271.pdf",
        desc="Photovoltaic MOSFET driver with fast turn-off, SOP-4"))
    # B0505S-1WR3 isolated DC/DC (SIP-4): 1 GND(-Vin), 2 Vin, 3 0V, 4 +Vo
    syms.append(ic_symbol(
        "B0505S", "PS",
        left=[("2", "+VIN", PI), ("1", "-VIN", PI)],
        right=[("4", "+VO", PO), ("3", "0V", PO)],
        width=15.24, value="B0505S-1WR3", desc="Isolated 1 W DC/DC, 5 V -> 5 V, SIP-4"))
    # onsemi SO-8FL N-MOSFET: pads 1-3 source, 4 gate, 5 drain (KiCad ONSemi_SO-8FL_488AA)
    syms.append(renumber("Device:Q_NMOS_SGD", "Q_NMOS_SO8FL", {"1": ["1", "2", "3"], "2": ["4"], "3": ["5"]},
                         ref="Q", value="NTMFS5C430N"))
    # TI INA190 in DDF (SOT-23-8 thin), datasheet SBOS863 pin table
    syms.append(ic_symbol(
        "INA190_DDF", "U",
        left=[("7", "IN+", I), ("8", "IN-", I), ("3", "REF", I)],
        right=[("2", "ENABLE", I), ("5", "OUT", O), ("6", "NC", NCt)],
        top=[("1", "VS", PI)], bottom=[("4", "GND", PI)],
        width=12.7, value="INA190A3IDDFR", ds="https://www.ti.com/lit/ds/symlink/ina190.pdf",
        desc="Current-sense amplifier, 40 V CM, pA bias, gain 100 (A3)"))
    # TI INA293A / INA281A in DBV (SOT-23-5), "A" pinout: 1 OUT, 2 GND, 3 IN+, 4 IN-, 5 VS
    syms.append(ic_symbol(
        "INAx_A_DBV", "U",
        left=[("3", "IN+", I), ("4", "IN-", I)], right=[("1", "OUT", O)],
        top=[("5", "VS", PI)], bottom=[("2", "GND", PI)],
        width=10.16, value="INA293A2IDBVR", ds="https://www.ti.com/lit/ds/symlink/ina293.pdf",
        desc="Current-sense amplifier, 110 V CM, A pinout (INA293A / INA281A)"))
    # TI UCC27524A (SOIC-8): 1 ENA, 2 INA, 3 GND, 4 INB, 5 OUTB, 6 VDD, 7 OUTA, 8 ENB
    syms.append(ic_symbol(
        "UCC27524A", "U",
        left=[("1", "ENA", I), ("8", "ENB", I), ("2", "INA", I), ("4", "INB", I)],
        right=[("6", "VDD", PI), ("7", "OUTA", O), ("5", "OUTB", O), ("3", "GND", PI)],
        width=12.7, value="UCC27524ADR", ds="https://www.ti.com/lit/ds/symlink/ucc27524a.pdf",
        desc="Dual 5 A low-side gate driver"))
    # Chipanalog CA-IS3720 (SOIC-8): 1 VDDA, 2 VI1, 3 VI2, 4 GNDA, 5 GNDB, 6 VO2, 7 VO1, 8 VDDB
    syms.append(ic_symbol(
        "CA-IS3720", "U",
        left=[("1", "VDDA", PI), ("2", "VI1", I), ("3", "VI2", I), ("4", "GNDA", PI)],
        right=[("8", "VDDB", PI), ("7", "VO1", O), ("6", "VO2", O), ("5", "GNDB", PI)],
        width=12.7, value="CA-IS3720HS", desc="Dual digital isolator, 2 forward channels, default high (H)"))
    return syms


if __name__ == "__main__":
    import sys
    write_lib(sys.argv[1], build(sys.argv[1]))
