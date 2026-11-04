"""Fabrication outputs for JLCPCB: Gerbers, Excellon drills, BOM and CPL, plus PNG renders."""
import csv
import os
import shutil
import subprocess
import zipfile

import pcbnew

import netlist
import place

HERE = os.path.dirname(os.path.abspath(__file__))
KDIR = os.path.join(HERE, "..", "kicad")
PCB = os.path.join(KDIR, "e-psu.kicad_pcb")
OUT = os.path.join(HERE, "..", "fab")
LAYERS = ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu", "F.Paste", "B.Paste", "F.Silkscreen", "B.Silkscreen",
          "F.Mask", "B.Mask", "Edge.Cuts"]


def sh(*cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(" ".join(cmd) + "\n" + r.stdout + r.stderr)
    return r.stdout


def set_origin():
    b = pcbnew.LoadBoard(PCB)
    ds = b.GetDesignSettings()
    o = pcbnew.VECTOR2I(pcbnew.FromMM(place.BX0), pcbnew.FromMM(place.BY0 + place.BH))
    ds.SetAuxOrigin(o)
    ds.SetGridOrigin(o)
    pcbnew.SaveBoard(PCB, b)


def gerbers():
    g = os.path.join(OUT, "gerber")
    shutil.rmtree(g, ignore_errors=True)
    os.makedirs(g)
    sh("kicad-cli", "pcb", "export", "gerbers", "-o", g + "/", "-l", ",".join(LAYERS), "--subtract-soldermask",
       "--use-drill-file-origin", "--no-x2", PCB)
    sh("kicad-cli", "pcb", "export", "drill", "-o", g + "/", "--format", "excellon", "--drill-origin", "plot",
       "--excellon-units", "mm", "--excellon-separate-th", "--generate-map", "--map-format", "gerberx2", PCB)
    z = os.path.join(OUT, "e-psu-revA-gerbers.zip")
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(os.listdir(g)):
            zf.write(os.path.join(g, f), f)
    return z, sorted(os.listdir(g))


def bom_cpl():
    comps, _ = netlist.load(os.path.join(HERE, "e-psu.net"))
    pos_csv = os.path.join(OUT, "pos.csv")
    sh("kicad-cli", "pcb", "export", "pos", "-o", pos_csv, "--format", "csv", "--units", "mm", "--side", "front",
       "--use-drill-file-origin", PCB)
    rows = list(csv.DictReader(open(pos_csv)))
    skip = lambda r: comps[r]["dnp"] or r.startswith(("H", "TP"))
    with open(os.path.join(OUT, "e-psu-revA-cpl.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Designator", "Mid X", "Mid Y", "Layer", "Rotation"])
        for r in rows:
            ref = r["Ref"]
            if skip(ref):
                continue
            w.writerow([ref, f'{float(r["PosX"]):.3f}mm', f'{float(r["PosY"]):.3f}mm', "Top",
                        f'{float(r["Rot"]) % 360:.0f}'])
    groups = {}
    for ref, c in comps.items():
        if skip(ref):
            continue
        key = (c["value"], c["footprint"].split(":")[1], c["fields"].get("LCSC", ""), c["fields"].get("MPN", ""))
        groups.setdefault(key, []).append(ref)
    nolcsc = []
    with open(os.path.join(OUT, "e-psu-revA-bom.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Comment", "Designator", "Footprint", "LCSC Part #", "MPN", "Qty"])
        for (val, fp, lcsc, mpn), refs in sorted(groups.items(), key=lambda kv: kv[1][0]):
            refs.sort(key=lambda r: (r[0], int("".join(ch for ch in r if ch.isdigit()))))
            w.writerow([val, ",".join(refs), fp, lcsc, mpn, len(refs)])
            if not lcsc:
                nolcsc += refs
    os.remove(pos_csv)
    return len(groups), nolcsc


def renders(prefix):
    """Top and bottom PNGs from kicad-cli SVG exports."""
    out = []
    for side, layers, mirror in (("top", "F.Cu,F.Mask,F.Silkscreen,Edge.Cuts", False),
                                 ("bottom", "B.Cu,B.Mask,B.Silkscreen,Edge.Cuts", True)):
        svg = f"{prefix}-{side}.svg"
        args = ["kicad-cli", "pcb", "export", "svg", "-o", svg, "-l", layers, "--page-size-mode", "2",
                "--exclude-drawing-sheet"]
        if mirror:
            args.append("-m")
        sh(*args, PCB)
        png = f"{prefix}-{side}.png"
        sh("convert", "-density", "300", "-background", "white", "-flatten", svg, png)
        out.append(png)
    return out


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    set_origin()
    print(gerbers())
    print(bom_cpl())
