"""Read component values from the e-psu KiCad schematic, so the simulation uses the same values.

values() -> {"R303": 90900.0, "C306": 2.2e-09, ...}   (DNP parts are skipped)
"""
import glob
import os
import re

from sexp import parse, find, findall

KICAD_DIR = os.environ.get("EPSU_KICAD", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "hardware", "e-psu"))
_MULT = {"p": 1e-12, "n": 1e-9, "u": 1e-6, "µ": 1e-6, "m": 1e-3, "R": 1.0, "k": 1e3, "K": 1e3,
         "M": 1e6, "G": 1e9}


def parse_value(text):
    """'90.9k 0.1%' -> 90900, '15m 1% 3W' -> 0.015, '4R7' -> 4.7, '1M' -> 1e6, '2.2u 50V' -> 2.2e-6."""
    tok = text.strip().split()[0]
    m = re.fullmatch(r"(\d+)([pnuµmRkKMG])(\d+)", tok)          # 4R7, 2k2
    if m:
        return float(m.group(1) + "." + m.group(3)) * _MULT[m.group(2)]
    m = re.fullmatch(r"(\d+(?:\.\d+)?)([pnuµmRkKMG]?)(?:F|H|Ohm|R)?", tok)
    if not m:
        raise ValueError(f"cannot parse value {text!r}")
    return float(m.group(1)) * _MULT.get(m.group(2), 1.0) if m.group(2) else float(m.group(1))


def raw_values(kicad_dir=KICAD_DIR):
    out = {}
    for path in sorted(glob.glob(os.path.join(kicad_dir, "*.kicad_sch"))):
        tree = parse(open(path, encoding="utf-8").read())
        for sym in findall(tree, "symbol"):
            if find(sym, "lib_id") is None:
                continue
            props = {str(p[1]): str(p[2]) for p in findall(sym, "property")}
            ref = props.get("Reference", "")
            if not ref or ref.startswith("#"):
                continue
            dnp = find(sym, "dnp")
            out[ref] = (props.get("Value", ""), bool(dnp and str(dnp[1]) == "yes"))
    return out


def values(kicad_dir=KICAD_DIR):
    vals = {}
    for ref, (val, dnp) in raw_values(kicad_dir).items():
        if dnp or ref[0] not in "RCL":
            continue
        if ref.startswith(("RV", "LED")):
            continue
        try:
            vals[ref] = parse_value(val)
        except ValueError:
            pass
    return vals


if __name__ == "__main__":
    v = values()
    for k in ("R303", "R304", "C304", "C305", "C306", "R305", "R306", "C307", "R307", "R301", "R312",
              "R313", "R401", "R402", "C401", "C313", "R508", "R509", "R201", "R203", "R318", "R319"):
        print(k, v.get(k))
    print(len(v), "R/C/L values")
