"""Widen the board: move the left and right edges out and the parts tied to them (KiCad 10).
    kicad10-python widen.py board.kicad_pcb DX_LEFT DX_RIGHT"""
import re, sys
from kc import pcbnew

path, dl, dr = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
LEFT, RIGHT = ("J101", "J102", "H601", "H603"), ("J501", "J502", "H602", "H604")
b = pcbnew.LoadBoard(path)
for refs, dx in ((LEFT, -dl), (RIGHT, dr)):
    for ref in refs:
        f = b.FindFootprintByReference(ref)
        p = f.GetPosition()
        f.SetPosition(pcbnew.VECTOR2I(p.x + pcbnew.FromMM(dx), p.y))
pcbnew.SaveBoard(path, b)
t = open(path).read()
m = re.search(r'\(gr_rect\s+\(start ([\d.]+) ([\d.]+)\)\s+\(end ([\d.]+) ([\d.]+)\)', t)
x0, x1 = float(m.group(1)), float(m.group(3))
t = t[:m.start(1)] + f"{x0 - dl:g}" + t[m.end(1):m.start(3)] + f"{x1 + dr:g}" + t[m.end(3):]
open(path, "w").write(t)
print(f"outline x {x0}..{x1} -> {x0 - dl:g}..{x1 + dr:g}")
