"""Silkscreen tidy-up: small reference designators placed next to their parts without touching pads,
other references or the board edge; references that do not fit are hidden (they stay on F.Fab).
Also adds board markings."""
import pcbnew
from shapely.geometry import box
from shapely.strtree import STRtree

import place

SIZE = 0.8
THICK = 0.16
LARGE = 1.0


def nm(v):
    return pcbnew.FromMM(v)


def rect_mm(bb):
    return (pcbnew.ToMM(bb.GetLeft()) - place.BX0, pcbnew.ToMM(bb.GetTop()) - place.BY0,
            pcbnew.ToMM(bb.GetRight()) - place.BX0, pcbnew.ToMM(bb.GetBottom()) - place.BY0)


def tidy(board, log=print):
    pads = []
    for fp in board.GetFootprints():
        for p in fp.Pads():
            if p.IsOnLayer(pcbnew.F_Cu) or p.IsOnLayer(pcbnew.F_Mask):
                pads.append(box(*rect_mm(p.GetBoundingBox())).buffer(0.12))
    silk_lines = []
    for fp in board.GetFootprints():
        for g in fp.GraphicalItems():
            if g.GetLayer() == pcbnew.F_SilkS and not isinstance(g, pcbnew.FP_TEXT):
                silk_lines.append(box(*rect_mm(g.GetBoundingBox())).buffer(0.05))
    tree = STRtree(pads)
    taken = []
    hidden = []
    edge = box(0.6, 0.6, place.BW - 0.6, place.BH - 0.6)
    fps = sorted(board.GetFootprints(), key=lambda f: -(lambda r: (r[2] - r[0]) * (r[3] - r[1]))(place.crtyd_abs(f)))
    for fp in fps:
        ref = fp.Reference()
        if fp.GetReference().startswith(("H", "TP")):
            ref.SetVisible(False)
            continue
        cr = place.crtyd_abs(fp)
        w, h = cr[2] - cr[0], cr[3] - cr[1]
        size = LARGE if min(w, h) > 8 else SIZE
        ref.SetTextSize(pcbnew.VECTOR2I(nm(size), nm(size)))
        ref.SetTextThickness(nm(THICK if size == SIZE else 0.18))
        ref.SetLayer(pcbnew.F_SilkS)
        ref.SetVisible(True)
        ref.SetKeepUpright(True)
        cx, cy = (cr[0] + cr[2]) / 2, (cr[1] + cr[3]) / 2
        tw = len(fp.GetReference()) * size * 0.75 + 0.2
        th = size + 0.2
        cands = [
            (cx, cr[1] - th / 2 - 0.05, 0), (cx, cr[3] + th / 2 + 0.05, 0),
            (cr[0] - th / 2 - 0.05, cy, 90), (cr[2] + th / 2 + 0.05, cy, 90),
            (cr[0] + tw / 2, cr[1] - th / 2 - 0.05, 0), (cr[2] - tw / 2, cr[1] - th / 2 - 0.05, 0),
            (cr[0] + tw / 2, cr[3] + th / 2 + 0.05, 0), (cr[2] - tw / 2, cr[3] + th / 2 + 0.05, 0),
            (cx, cy, 0), (cx, cy, 90),
        ]
        for off in (0.35, 0.7):
            cands += [(cx, cr[1] - th / 2 - off, 0), (cx, cr[3] + th / 2 + off, 0),
                      (cr[0] - th / 2 - off, cy, 90), (cr[2] + th / 2 + off, cy, 90)]
        # inside the courtyard for parts whose body is big enough
        cands += [(cx, cy - h / 4, 0), (cx, cy + h / 4, 0), (cx - w / 4, cy, 90), (cx + w / 4, cy, 90)]
        best = None
        ref.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_CENTER)
        ref.SetVertJustify(pcbnew.GR_TEXT_V_ALIGN_CENTER)
        for x, y, rot in cands:
            ref.SetTextAngleDegrees(rot)
            ref.SetPosition(pcbnew.VECTOR2I(nm(place.BX0 + x), nm(place.BY0 + y)))
            r = box(*rect_mm(ref.GetBoundingBox())).buffer(0.03)
            if not edge.contains(r):
                continue
            if any(r.intersects(pads[i]) for i in tree.query(r)):
                continue
            if any(r.intersects(t) for t in taken):
                continue
            pen = sum(1 for s in silk_lines if r.intersects(s))
            score = pen * 10 + (0 if (x, y) == cands[0][:2] else 1)
            if best is None or score < best[0]:
                best = (score, x, y, rot, r)
                if score == 0:
                    break
        if best is None:
            ref.SetVisible(False)
            hidden.append(fp.GetReference())
            continue
        _, x, y, rot, r = best
        ref.SetTextAngleDegrees(rot)
        ref.SetPosition(pcbnew.VECTOR2I(nm(place.BX0 + x), nm(place.BY0 + y)))
        ref.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_CENTER)
        ref.SetVertJustify(pcbnew.GR_TEXT_V_ALIGN_CENTER)
        taken.append(r.buffer(0.1))
    log(f"silk: {len(hidden)} references hidden: {' '.join(sorted(hidden))}")
    return hidden


def text(board, s, x, y, size=1.2, rot=0, layer=pcbnew.F_SilkS, thick=None, bold=False):
    t = pcbnew.PCB_TEXT(board)
    t.SetText(s)
    t.SetPosition(pcbnew.VECTOR2I(nm(place.BX0 + x), nm(place.BY0 + y)))
    t.SetTextSize(pcbnew.VECTOR2I(nm(size), nm(size)))
    t.SetTextThickness(nm(thick or size * (0.2 if bold else 0.15)))
    t.SetTextAngleDegrees(rot)
    t.SetLayer(layer)
    if layer in (pcbnew.B_SilkS, pcbnew.B_Cu):
        t.SetMirrored(True)
    board.Add(t)
    return t
