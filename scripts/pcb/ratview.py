"""Board view with routed tracks (F red, B blue) and DRC unconnected pairs as black lines."""
import re
import sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import pcbnew
import place


def draw(pcb, report, out, win=(0, 0, 100, 100)):
    b = pcbnew.LoadBoard(pcb)
    x0, y0, x1, y1 = win
    fig, ax = plt.subplots(figsize=(15, 15 * (y1 - y0) / (x1 - x0)))
    k = 15 / (x1 - x0) * 72
    for z in b.Zones():
        L = z.GetLayer()
        if L not in (pcbnew.F_Cu, pcbnew.B_Cu):
            continue
        fp_ = z.GetFilledPolysList(L)
        for i in range(fp_.OutlineCount()):
            ol = fp_.Outline(i)
            pts = [(pcbnew.ToMM(ol.CPoint(j).x) - place.BX0, pcbnew.ToMM(ol.CPoint(j).y) - place.BY0) for j in range(ol.PointCount())]
            ax.add_patch(plt.Polygon(pts, color="#e8a0a0" if L == pcbnew.F_Cu else "#a0b8e8", alpha=0.35, lw=0))
    for fp in b.GetFootprints():
        for p in fp.Pads():
            bb = p.GetBoundingBox()
            ax.add_patch(Rectangle((pcbnew.ToMM(bb.GetLeft()) - place.BX0, pcbnew.ToMM(bb.GetTop()) - place.BY0),
                                   pcbnew.ToMM(bb.GetWidth()), pcbnew.ToMM(bb.GetHeight()), color="#b08d57", alpha=0.6, lw=0))
    for t in b.GetTracks():
        if isinstance(t, pcbnew.PCB_VIA):
            p = t.GetPosition()
            ax.add_patch(plt.Circle((pcbnew.ToMM(p.x) - place.BX0, pcbnew.ToMM(p.y) - place.BY0), 0.3, color="#444", lw=0))
        else:
            s, e = t.GetStart(), t.GetEnd()
            ax.plot([pcbnew.ToMM(s.x) - place.BX0, pcbnew.ToMM(e.x) - place.BX0],
                    [pcbnew.ToMM(s.y) - place.BY0, pcbnew.ToMM(e.y) - place.BY0],
                    color="#c0392b" if t.GetLayer() == pcbnew.F_Cu else "#2471a3",
                    lw=max(0.4, pcbnew.ToMM(t.GetWidth()) * k), alpha=0.8, solid_capstyle="round")
    if report:
        txt = open(report).read().split("\n")
        for i, l in enumerate(txt):
            if l.startswith("[unconnected_items]"):
                pts = []
                for l2 in txt[i + 2:i + 4]:
                    m = re.search(r"@\(([\d.]+) mm, ([\d.]+) mm\)", l2)
                    if m:
                        pts.append((float(m.group(1)) - place.BX0, float(m.group(2)) - place.BY0))
                if len(pts) == 2:
                    ax.plot([pts[0][0], pts[1][0]], [pts[0][1], pts[1][1]], color="k", lw=1.2)
                    ax.plot(*pts[0], "ko", ms=3); ax.plot(*pts[1], "ko", ms=3)
    ax.add_patch(Rectangle((0, 0), place.BW, place.BH, fill=False, lw=1, color="k"))
    ax.set_xlim(x0, x1); ax.set_ylim(y1, y0); ax.set_aspect("equal"); ax.grid(alpha=0.2)
    fig.tight_layout(); fig.savefig(out, dpi=80); plt.close(fig)


if __name__ == "__main__":
    win = tuple(float(v) for v in sys.argv[4:8]) if len(sys.argv) > 4 else (0, 0, 100, 100)
    draw(sys.argv[1], sys.argv[2], sys.argv[3], win)
