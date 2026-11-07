"""Finishing pass for rev B (KiCad 10): GND pours on the outer layers, stitching vias, silkscreen references.

    kicad10-python finish.py board.kicad_pcb
"""
import math
import sys

import numpy as np
import shapely
from shapely.geometry import LineString, Point, box
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


REF_H = 1.0           # reference text height, mm (JLCPCB minimum; Seeed 0.58)
REF_SMALL = 0.8       # fallback height where 1.0 mm does not fit
REF_T = 0.15          # stroke width, mm (JLCPCB minimum silk line)
PAD_GAP = 0.2         # silk to pad, mm (JLCPCB 0.15, Seeed 0.1524)
LABEL_GAP = 0.3       # between two references
JACK_LABELS = {"IN+": "J101", "IN-": "J102", "OUT+": "J501", "OUT-": "J502"}


def _bbox(bb):
    return (pcbnew.ToMM(bb.GetLeft()), pcbnew.ToMM(bb.GetTop()), pcbnew.ToMM(bb.GetRight()), pcbnew.ToMM(bb.GetBottom()))


def _courtyard(fp):
    cy = fp.GetCourtyard(pcbnew.F_CrtYd)
    return _bbox(cy.BBox() if cy.OutlineCount() else fp.GetBoundingBox(False, False))


def silk(board):
    """References on, values off. A reference stays where the placer reserved room for it when that spot is
    still clear of every pad, every other part's courtyard, the other references and the board edge; the
    rest are searched for next to their part (then inside its own body for large parts, then at 0.8 mm).
    Text never goes over another part, where it would be hidden after assembly."""
    pads = []
    for fp in board.GetFootprints():
        fp.Value().SetVisible(False)
        ref = fp.Reference()
        ref.SetVisible(True)
        ref.SetLayer(pcbnew.B_SilkS if fp.IsFlipped() else pcbnew.F_SilkS)
        ref.SetTextSize(pcbnew.VECTOR2I(pcbnew.FromMM(REF_H), pcbnew.FromMM(REF_H)))
        ref.SetTextThickness(pcbnew.FromMM(REF_T))
        ref.SetKeepUpright(True)
        for p in fp.Pads():
            l, t, r_, b = _bbox(p.GetBoundingBox())
            pads.append(box(l - PAD_GAP, t - PAD_GAP, r_ + PAD_GAP, b + PAD_GAP))
    # the parts' own silkscreen (outlines, pin-1 marks): references stay 0.1 mm clear of it
    for fp in board.GetFootprints():
        for it in fp.GraphicalItems():
            if it.GetLayer() != pcbnew.F_SilkS or it.GetClass() in ("PCB_TEXT", "PCB_FIELD", "PCB_TEXTBOX"):
                continue
            hw = pcbnew.ToMM(it.GetWidth()) / 2 + 0.1
            if it.GetShape() == pcbnew.SHAPE_T_SEGMENT:
                a_, b_ = it.GetStart(), it.GetEnd()
                g = LineString([(pcbnew.ToMM(a_.x), pcbnew.ToMM(a_.y)), (pcbnew.ToMM(b_.x), pcbnew.ToMM(b_.y))])
                pads.append(g.buffer(hw, cap_style=2) if g.length > 0 else Point(g.coords[0]).buffer(hw))
            else:
                l, t, r_, b = _bbox(it.GetBoundingBox())
                pads.append(box(l - 0.1, t - 0.1, r_ + 0.1, b + 0.1))
    ptree = shapely.STRtree(pads)
    yards = {fp.GetReference(): box(*_courtyard(fp)) for fp in board.GetFootprints()}
    names = list(yards)
    ytree = shapely.STRtree([yards[n] for n in names])
    taken = []
    x0, y0 = copper.OX + 0.4, copper.OY + 0.4
    x1, y1 = copper.OX + copper.BW - 0.4, copper.OY + copper.BH - 0.4

    def clear(fp_ref, r, own_inside):
        if r.bounds[0] < x0 or r.bounds[1] < y0 or r.bounds[2] > x1 or r.bounds[3] > y1:
            return False
        if any(r.intersects(pads[k]) for k in ptree.query(r)):
            return False
        for k in ytree.query(r):
            n = names[k]
            if not r.intersects(yards[n]) or r.touches(yards[n]):
                continue
            if n != fp_ref or not (own_inside and r.within(yards[n])):
                return False
        return not any(r.distance(t) < LABEL_GAP for t in taken)

    def candidates(l, t, r_, b, w, h):
        cx, cy = (l + r_) / 2, (t + b) / 2
        out = []
        for d in (0.05, 0.3, 0.7, 1.2, 2.0):
            for rot in (0, 90):
                tw, th = (w, h) if rot == 0 else (h, w)
                for f in (0, -0.25, 0.25, -0.5, 0.5):       # slide along each side, centre first
                    sx, sy = f * (r_ - l + tw), f * (b - t + th)
                    out += [(cx + sx, t - th / 2 - d, rot), (cx + sx, b + th / 2 + d, rot),
                            (l - tw / 2 - d, cy + sy, rot), (r_ + tw / 2 + d, cy + sy, rot)]
        return out

    def size(fp, hgt):
        ref = fp.Reference()
        ref.SetTextSize(pcbnew.VECTOR2I(pcbnew.FromMM(hgt), pcbnew.FromMM(hgt)))
        a = ref.GetTextAngleDegrees()
        ref.SetTextAngleDegrees(0)
        l, t, r_, b = _bbox(ref.GetEffectiveTextShape().BBox())
        ref.SetTextAngleDegrees(a)
        return r_ - l + 0.1, b - t + 0.1

    def put(fp, x, y, rot, r):
        ref = fp.Reference()
        ref.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y)))
        ref.SetTextAngleDegrees(rot)
        ref.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_CENTER)
        ref.SetVertJustify(pcbnew.GR_TEXT_V_ALIGN_CENTER)
        taken.append(r)

    # most constrained first: small parts, which have nowhere else to go
    fps = sorted(board.GetFootprints(), key=lambda f: yards[f.GetReference()].area)
    kept, left = 0, []
    for fp in fps:
        # glyphs; the placer kept 0.1 mm around them (its courtyard box is the outline's centre line,
        # KiCad's includes the line width: 0.025 mm more)
        r = box(*_bbox(fp.Reference().GetEffectiveTextShape().BBox()))
        if clear(fp.GetReference(), r.buffer(-0.03, join_style=2), own_inside=True):
            taken.append(r)
            kept += 1
        else:
            left.append(fp)
    print(f"  references kept where the placer put them: {kept}; to place: {len(left)}", flush=True)
    placed = kept
    for stage, hgt in (("next to the part", REF_H), ("inside the part", REF_H), ("0.8 mm", REF_SMALL)):
        todo, left = left, []
        for fp in todo:
            name = fp.GetReference()
            w, h = size(fp, hgt)
            l, t, r_, b = _courtyard(fp)
            best = None
            if stage == "inside the part":
                spots = [((l + r_) / 2, (t + b) / 2, rot) for rot in (0, 90)]
            else:
                spots = candidates(l, t, r_, b, w, h)
            for (x, y, rot) in spots:
                tw, th = (w, h) if rot == 0 else (h, w)
                rr = box(x - tw / 2, y - th / 2, x + tw / 2, y + th / 2)
                if clear(name, rr, own_inside=stage == "inside the part"):
                    best = (x, y, rot, rr)
                    break
            if best is None:
                left.append(fp)
                continue
            put(fp, *best)
            placed += 1
        print(f"  references {stage}: {placed} placed, {len(left)} left", flush=True)
    for fp in left:
        fp.Reference().SetVisible(False)      # better hidden than printed over pads or another part
        print("  no room for", fp.GetReference(), "(hidden; on F.Fab)")

    # terminal names next to the jacks (the user's texts, which sat off the board)
    texts = {d.GetText(): d for d in board.GetDrawings() if d.GetClass() == "PCB_TEXT"}
    edge = box(x0, y0, x1, y1)
    for name, jack in JACK_LABELS.items():
        d = texts.get(name)
        if d is None:
            continue
        d.SetLayer(pcbnew.F_SilkS)
        d.SetMirrored(False)
        d.SetTextAngleDegrees(0)
        a = d.GetEffectiveTextShape().BBox()
        w, h = pcbnew.ToMM(a.GetWidth()) + 0.2, pcbnew.ToMM(a.GetHeight()) + 0.2
        l, t, r_, b = box(*_courtyard(board.FindFootprintByReference(jack))).intersection(edge).bounds
        for (x, y, rot) in candidates(l, t, r_, b, w, h):
            tw, th = (w, h) if rot == 0 else (h, w)
            rr = box(x - tw / 2, y - th / 2, x + tw / 2, y + th / 2)
            if clear(jack, rr, own_inside=False):
                d.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y)))
                d.SetTextAngleDegrees(rot)
                d.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_CENTER)
                d.SetVertJustify(pcbnew.GR_TEXT_V_ALIGN_CENTER)
                taken.append(rr)
                print(f"  {name} next to {jack}")
                break
        else:
            print(f"  no room for {name} next to {jack}")
    return placed


# notes on the back (the user's texts, which sat off the board): text -> (new text or None, height, local target x, y)
BACK_NOTES = {
    "e-psu": (None, 2.0, 108.0, 62.0),
    "USB-controlled bench PSU front end  rev A": ("USB-controlled bench PSU front end  rev B", 1.0, 108.0, 65.0),
    "4-layer: F sig / In1 GND / In2 PWR / B sig": (None, 1.0, 108.0, 67.0),
    "JLCJLCJLCJLC": (None, 1.0, 108.0, 69.0),
    "RANGING ISLAND (VFORCE)": (None, 1.0, 71.0, 28.5),
    "ISOLATED USB": (None, 1.0, 69.5, 67.5),
}


def back_notes(board):
    """Move the back-silkscreen notes onto the board, clear of plated pads, holes and each other."""
    obst = []
    for fp in board.GetFootprints():
        for p in fp.Pads():
            if p.GetAttribute() in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH) or p.IsOnLayer(pcbnew.B_Cu):
                l, t, r_, b = _bbox(p.GetBoundingBox())
                obst.append(box(l - 0.25, t - 0.25, r_ + 0.25, b + 0.25))
    for t in board.GetTracks():
        if t.GetClass() == "PCB_VIA":
            c = t.GetPosition()
            obst.append(Point(pcbnew.ToMM(c.x), pcbnew.ToMM(c.y)).buffer(pcbnew.ToMM(t.GetDrillValue()) / 2 + 0.15))
    tree = shapely.STRtree(obst)
    x0, y0 = copper.OX + 0.6, copper.OY + 0.6
    x1, y1 = copper.OX + copper.BW - 0.6, copper.OY + copper.BH - 0.6
    placed = []
    texts = {d.GetText(): d for d in board.GetDrawings() if d.GetClass() == "PCB_TEXT"}
    for old, (new, hgt, tx, ty) in BACK_NOTES.items():
        d = texts.get(old)
        if d is None:
            continue
        if new:
            d.SetText(new)
        d.SetLayer(pcbnew.B_SilkS)
        d.SetMirrored(True)
        d.SetTextAngleDegrees(0)
        d.SetTextSize(pcbnew.VECTOR2I(pcbnew.FromMM(hgt), pcbnew.FromMM(hgt)))
        d.SetTextThickness(pcbnew.FromMM(max(0.15, hgt * 0.15)))
        d.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_CENTER)
        d.SetVertJustify(pcbnew.GR_TEXT_V_ALIGN_CENTER)
        a = d.GetEffectiveTextShape().BBox()
        w, h = pcbnew.ToMM(a.GetWidth()) + 0.2, pcbnew.ToMM(a.GetHeight()) + 0.2
        best = None
        for ring in range(0, 60):
            for k in range(max(1, 8 * ring)):
                ang = 2 * math.pi * k / max(1, 8 * ring)
                x = copper.OX + tx + 0.25 * ring * math.cos(ang)
                y = copper.OY + ty + 0.25 * ring * math.sin(ang)
                rr = box(x - w / 2, y - h / 2, x + w / 2, y + h / 2)
                if rr.bounds[0] < x0 or rr.bounds[1] < y0 or rr.bounds[2] > x1 or rr.bounds[3] > y1:
                    continue
                if any(rr.intersects(obst[q]) for q in tree.query(rr)) or any(rr.distance(o) < 0.4 for o in placed):
                    continue
                best = (x, y, rr)
                break
            if best:
                break
        if best is None:
            print("  no room on the back for", d.GetText())
            continue
        d.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(best[0]), pcbnew.FromMM(best[1])))
        placed.append(best[2])
    return len(placed)


def run(path):
    board = pcbnew.LoadBoard(path)
    print("thermal vias joined solid:", copper.solid_thermal_vias(board))
    print("pours", pours(board))
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    print("stitching vias", stitch(board))
    print("references placed", silk(board))
    print("back notes placed", back_notes(board))
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    pcbnew.SaveBoard(path, board)


if __name__ == "__main__":
    run(sys.argv[1])
