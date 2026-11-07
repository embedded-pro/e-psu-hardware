"""Finishing pass for rev B (KiCad 10): GND pours on the outer layers, stitching vias, silkscreen references.

    kicad10-python finish.py board.kicad_pcb
"""
import math
import sys

import numpy as np
import shapely
from shapely.geometry import Point, box
from shapely.ops import unary_union

from kc import pcbnew
import copper
import octoroute as oc

STITCH = 4.0          # stitching via pitch, mm


def pours(board):
    edge = box(copper.INSET, copper.INSET, copper.BW - copper.INSET, copper.BH - copper.INSET)
    usb_cut = None
    for z in board.Zones():
        if not z.GetIsRuleArea() and z.GetNetname() == "GND_USB" and z.IsOnLayer(pcbnew.In1_Cu):
            ol = z.Outline().Outline(0)
            pts = [(pcbnew.ToMM(ol.CPoint(i).x) - copper.OX, pcbnew.ToMM(ol.CPoint(i).y) - copper.OY) for i in range(ol.PointCount())]
            usb_cut = shapely.Polygon(pts)
    gnd = edge.difference(usb_cut.buffer(copper.USB_GAP, join_style=2)) if usb_cut is not None else edge
    n = 0
    for layer in ("F.Cu", "B.Cu"):
        n += copper.add_zone(board, "GND", layer, gnd, 0, solid=False, min_w=0.3)
        if usb_cut is not None:
            n += copper.add_zone(board, "GND_USB", layer, usb_cut, 0, solid=False, min_w=0.3)
    return n


def stitch(board):
    """GND vias on a regular grid wherever a via fits on both outer layers and inside the In1 GND plane."""
    r = oc.Router(board)
    r.build()
    nid = r.netid["GND"]
    plane = oc.plane_mask(r, "GND")
    vias = 0
    placed = []
    for y in np.arange(2.0, copper.BH - 1.0, STITCH):
        for x in np.arange(2.0, copper.BW - 1.0, STITCH):
            ax, ay = float(copper.OX + x), float(copper.OY + y)
            i, j = int(round((ax - r.x0) / oc.G)), int(round((ay - r.y0) / oc.G))
            if not plane[j, i]:
                continue
            ok = True
            for l in (0, 1):
                win = r.via[l, j - 2:j + 3, i - 2:i + 3]
                if not np.all((win == oc.FREE) | (win == nid)):
                    ok = False
            if not ok:
                continue
            v = pcbnew.PCB_VIA(board)
            v.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(ax), pcbnew.FromMM(ay)))
            v.SetWidth(pcbnew.FromMM(oc.VIA_D)); v.SetDrill(pcbnew.FromMM(oc.VIA_DRILL))
            v.SetNet(board.FindNet("GND")); v.SetViaType(pcbnew.VIATYPE_THROUGH)
            board.Add(v)
            r.add_copper((0, 1), Point(ax, ay).buffer(oc.VIA_D / 2), nid, 0.15)
            vias += 1
    return vias


def silk(board):
    """Put each reference next to its part, clear of every pad, other references and the board edge."""
    pads = []
    for fp in board.GetFootprints():
        for p in fp.Pads():
            bb = p.GetBoundingBox()
            pads.append(box(pcbnew.ToMM(bb.GetLeft()) - 0.2, pcbnew.ToMM(bb.GetTop()) - 0.2,
                            pcbnew.ToMM(bb.GetRight()) + 0.2, pcbnew.ToMM(bb.GetBottom()) + 0.2))
    tree = shapely.STRtree(pads)
    taken = []
    x0, y0 = copper.OX + 0.4, copper.OY + 0.4
    x1, y1 = copper.OX + copper.BW - 0.4, copper.OY + copper.BH - 0.4
    fps = sorted(board.GetFootprints(), key=lambda f: -f.GetBoundingBox(False).GetArea())
    moved = 0
    for fp in fps:
        ref = fp.Reference()
        if not ref.IsVisible():
            continue
        txt = fp.GetReference()
        h = 1.0
        w = 0.62 * h * len(txt) + 0.3
        bb = fp.GetCourtyard(pcbnew.F_CrtYd).BBox() if fp.GetCourtyard(pcbnew.F_CrtYd).OutlineCount() else fp.GetBoundingBox(False)
        cl, ct, cr, cb = (pcbnew.ToMM(bb.GetLeft()), pcbnew.ToMM(bb.GetTop()), pcbnew.ToMM(bb.GetRight()), pcbnew.ToMM(bb.GetBottom()))
        cx, cy = (cl + cr) / 2, (ct + cb) / 2
        cands = []
        if (cr - cl) > w + 1 and (cb - ct) > h + 1:
            cands.append((cx, cy, 0))                      # inside the body of large parts
        for d in (0.15, 0.6, 1.2, 2.0, 3.0, 4.0):
            for rot in (0, 90):
                tw, th = (w, h) if rot == 0 else (h, w)
                cands += [(cx, ct - th / 2 - d, rot), (cx, cb + th / 2 + d, rot),
                          (cl - tw / 2 - d, cy, rot), (cr + tw / 2 + d, cy, rot),
                          (cl - tw / 2 - d, ct - th / 2 - d, rot), (cr + tw / 2 + d, ct - th / 2 - d, rot),
                          (cl - tw / 2 - d, cb + th / 2 + d, rot), (cr + tw / 2 + d, cb + th / 2 + d, rot)]
        best = None
        for (x, y, rot) in cands:
            tw, th = (w, h) if rot == 0 else (h, w)
            r = box(x - tw / 2, y - th / 2, x + tw / 2, y + th / 2)
            if r.bounds[0] < x0 or r.bounds[1] < y0 or r.bounds[2] > x1 or r.bounds[3] > y1:
                continue
            if any(r.intersects(pads[k]) for k in tree.query(r)):
                continue
            if any(r.intersects(t) for t in taken):
                continue
            best = (x, y, rot, r)
            break
        if best is None:
            continue
        x, y, rot, r = best
        ref.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y)))
        ref.SetTextAngleDegrees(rot)
        ref.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_CENTER)
        ref.SetVertJustify(pcbnew.GR_TEXT_V_ALIGN_CENTER)
        taken.append(r)
        moved += 1
    return moved


def run(path):
    board = pcbnew.LoadBoard(path)
    print("pours", pours(board))
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    print("stitching vias", stitch(board))
    print("references placed", silk(board))
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    pcbnew.SaveBoard(path, board)


if __name__ == "__main__":
    run(sys.argv[1])
