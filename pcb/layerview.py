"""Per-layer view: filled zones coloured by net with labels, tracks, vias, pads."""
import sys
import zlib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, Polygon
import pcbnew
import place

SHORT = lambda n: n.split("/")[-1].replace("Net-(", "").replace(")", "")[:10]
PAL = plt.cm.tab20.colors


def col(n):
    if n == "GND":
        return (0.55, 0.55, 0.55)
    return PAL[zlib.crc32(n.encode()) % 20]


def mm(v):
    return pcbnew.ToMM(v)


def draw_layer(path, out, layer, win=(0, 0, 100, 100), labels=True, board=None):
    b = board or pcbnew.LoadBoard(path)
    x0, y0, x1, y1 = win
    fig, ax = plt.subplots(figsize=(14, 14 * (y1 - y0) / (x1 - x0)))
    ax.add_patch(Rectangle((0, 0), place.BW, place.BH, fill=False, lw=1.2, color="k"))
    for z in b.Zones():
        if z.GetLayer() != layer:
            continue
        n = z.GetNetname()
        fp_ = z.GetFilledPolysList(layer)
        for i in range(fp_.OutlineCount()):
            ol = fp_.Outline(i)
            pts = [(mm(ol.CPoint(k).x) - place.BX0, mm(ol.CPoint(k).y) - place.BY0) for k in range(ol.PointCount())]
            ax.add_patch(Polygon(pts, closed=True, color=col(n), alpha=0.45, lw=0))
        bb = z.GetBoundingBox()
        if labels:
            cx, cy = mm(bb.Centre().x) - place.BX0, mm(bb.Centre().y) - place.BY0
            ax.text(cx, cy, SHORT(n), fontsize=7, ha="center", color="k", weight="bold", alpha=0.8)
    for fp in b.GetFootprints():
        for p in fp.Pads():
            if not p.IsOnLayer(layer):
                continue
            bb = p.GetBoundingBox()
            ax.add_patch(Rectangle((mm(bb.GetLeft()) - place.BX0, mm(bb.GetTop()) - place.BY0), mm(bb.GetWidth()),
                                   mm(bb.GetHeight()), color=col(p.GetNetname()) if p.GetNetname() else "#bbb",
                                   alpha=0.9, lw=0.3, ec="k"))
    for t in b.GetTracks():
        if isinstance(t, pcbnew.PCB_VIA):
            p = t.GetPosition()
            ax.add_patch(plt.Circle((mm(p.x) - place.BX0, mm(p.y) - place.BY0), mm(t.GetWidth()) / 2,
                                    color=col(t.GetNetname()), ec="k", lw=0.3))
        elif t.GetLayer() == layer:
            s, e = t.GetStart(), t.GetEnd()
            ax.plot([mm(s.x) - place.BX0, mm(e.x) - place.BX0], [mm(s.y) - place.BY0, mm(e.y) - place.BY0],
                    color=col(t.GetNetname()), lw=max(0.3, mm(t.GetWidth()) * 14 / (x1 - x0) * 72),
                    solid_capstyle="round", alpha=0.95)
    ax.set_xlim(x0, x1); ax.set_ylim(y1, y0); ax.set_aspect("equal")
    ax.set_title(b.GetLayerName(layer))
    ax.grid(alpha=0.2)
    fig.tight_layout(); fig.savefig(out, dpi=90); plt.close(fig)


if __name__ == "__main__":
    lay = {"F": pcbnew.F_Cu, "I1": pcbnew.In1_Cu, "I2": pcbnew.In2_Cu, "B": pcbnew.B_Cu}[sys.argv[3]]
    win = tuple(float(v) for v in sys.argv[4:8]) if len(sys.argv) > 4 else (0, 0, 100, 100)
    draw_layer(sys.argv[1], sys.argv[2], lay, win)
