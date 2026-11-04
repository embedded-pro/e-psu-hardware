import os

import pcbnew

FPDIRS = {"e-psu": os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "kicad", "e-psu.pretty")}


def libdir(lib):
    return FPDIRS.get(lib, f"/usr/share/kicad/footprints/{lib}.pretty")


def load(fpid):
    lib, name = fpid.split(":", 1)
    fp = pcbnew.FootprintLoad(libdir(lib), name)
    if fp is None:
        raise FileNotFoundError(fpid)
    return fp


def crtyd_bbox_local(fp):
    """Courtyard bbox (mm) in footprint-local coordinates (orientation 0, at origin), front or back courtyard;
    falls back to pads + fab outline."""
    xs, ys = [], []
    for it in fp.GraphicalItems():
        if it.GetLayer() in (pcbnew.F_CrtYd, pcbnew.B_CrtYd):
            bb = it.GetBoundingBox()
            xs += [bb.GetLeft(), bb.GetRight()]; ys += [bb.GetTop(), bb.GetBottom()]
    if not xs:
        for p in fp.Pads():
            bb = p.GetBoundingBox()
            xs += [bb.GetLeft(), bb.GetRight()]; ys += [bb.GetTop(), bb.GetBottom()]
        for it in fp.GraphicalItems():
            if it.GetLayer() == pcbnew.F_Fab:
                bb = it.GetBoundingBox()
                xs += [bb.GetLeft(), bb.GetRight()]; ys += [bb.GetTop(), bb.GetBottom()]
        pad = pcbnew.FromMM(0.25)
        return tuple(pcbnew.ToMM(v) for v in (min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad))
    return tuple(pcbnew.ToMM(v) for v in (min(xs), min(ys), max(xs), max(ys)))
