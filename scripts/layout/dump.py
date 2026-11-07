"""Dump footprints (rot-0 courtyard, pads, nets) of the board to parts.json (KiCad 10)."""
import json, sys
from kc import pcbnew

def crtyd(fp):
    xs, ys = [], []
    for it in fp.GraphicalItems():
        if it.GetLayer() in (pcbnew.F_CrtYd, pcbnew.B_CrtYd):
            bb = it.GetBoundingBox(); xs += [bb.GetLeft(), bb.GetRight()]; ys += [bb.GetTop(), bb.GetBottom()]
    if not xs:
        for p in fp.Pads():
            bb = p.GetBoundingBox(); xs += [bb.GetLeft(), bb.GetRight()]; ys += [bb.GetTop(), bb.GetBottom()]
    return [pcbnew.ToMM(min(xs)), pcbnew.ToMM(min(ys)), pcbnew.ToMM(max(xs)), pcbnew.ToMM(max(ys))]

b = pcbnew.LoadBoard(sys.argv[1])
out = {}
for fp in b.GetFootprints():
    pos, rot = fp.GetPosition(), fp.GetOrientationDegrees()
    fp.SetOrientationDegrees(0)
    c = crtyd(fp)
    ox, oy = pcbnew.ToMM(pos.x), pcbnew.ToMM(pos.y)
    pads = [dict(num=p.GetNumber(), net=p.GetNetname(), x=round(pcbnew.ToMM(p.GetPosition().x) - ox, 4),
                 y=round(pcbnew.ToMM(p.GetPosition().y) - oy, 4), w=pcbnew.ToMM(p.GetSize(pcbnew.F_Cu).x),
                 h=pcbnew.ToMM(p.GetSize(pcbnew.F_Cu).y), th=p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH) for p in fp.Pads()]
    fp.SetOrientationDegrees(rot)
    out[fp.GetReference()] = dict(value=fp.GetValue(), fpid=fp.GetFPIDAsString(), x=ox, y=oy, rot=rot,
                                  locked=fp.IsLocked(), crtyd=[round(c[0] - ox, 3), round(c[1] - oy, 3), round(c[2] - ox, 3), round(c[3] - oy, 3)],
                                  pads=pads)
json.dump(out, open(sys.argv[2], "w"), indent=1)
print(len(out))
