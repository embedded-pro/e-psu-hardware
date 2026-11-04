"""Quick matplotlib view of the board: courtyards, pads, refs, tracks, vias, zones."""
import sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, Polygon
import pcbnew
import place

COL = {"in": "#e67e22", "hk": "#16a085", "buck": "#c0392b", "pass": "#8e44ad", "amp": "#2980b9", "rng": "#d35400",
       "iso": "#27ae60", "mcu": "#2c3e50", "out": "#b7950b", "usb": "#7f8c8d", "ui": "#e84393"}
LAYC = {pcbnew.F_Cu: "#c0392b", pcbnew.In1_Cu: "#27ae60", pcbnew.In2_Cu: "#d4ac0d", pcbnew.B_Cu: "#2471a3"}


def mm(v):
    return pcbnew.ToMM(v)


def draw(path, out, labels=True, zones=True, tracks=True, ratsnest=False, layers=None):
    board = pcbnew.LoadBoard(path)
    fig, ax = plt.subplots(figsize=(13, 13))
    ax.add_patch(Rectangle((0, 0), place.BW, place.BH, fill=False, lw=1.5, color="k"))
    if zones:
        for z in board.Zones():
            if layers and z.GetLayer() not in layers:
                continue
            fp_ = z.GetFilledPolysList(z.GetLayer()) if z.IsFilled() else None
            c = LAYC.get(z.GetLayer(), "#999")
            if fp_ and fp_.OutlineCount():
                for i in range(fp_.OutlineCount()):
                    ol = fp_.Outline(i)
                    pts = [(mm(ol.CPoint(k).x) - place.BX0, mm(ol.CPoint(k).y) - place.BY0) for k in range(ol.PointCount())]
                    ax.add_patch(Polygon(pts, closed=True, color=c, alpha=0.18, lw=0))
            else:
                ol = z.Outline().Outline(0)
                pts = [(mm(ol.CPoint(k).x) - place.BX0, mm(ol.CPoint(k).y) - place.BY0) for k in range(ol.PointCount())]
                ax.add_patch(Polygon(pts, closed=True, fill=False, ls="--", color=c, lw=0.8))
    if tracks:
        for t in board.GetTracks():
            if layers and t.GetLayer() not in layers and not isinstance(t, pcbnew.PCB_VIA):
                continue
            if isinstance(t, pcbnew.PCB_VIA):
                p = t.GetPosition()
                ax.plot(mm(p.x) - place.BX0, mm(p.y) - place.BY0, "o", ms=2.2, color="#555", mfc="white", mew=0.6)
            else:
                s, e = t.GetStart(), t.GetEnd()
                ax.plot([mm(s.x) - place.BX0, mm(e.x) - place.BX0], [mm(s.y) - place.BY0, mm(e.y) - place.BY0],
                        color=LAYC.get(t.GetLayer(), "k"), lw=max(0.4, mm(t.GetWidth()) * 4.2), alpha=0.75,
                        solid_capstyle="round")
    for fp in board.GetFootprints():
        ref = fp.GetReference()
        r = place.crtyd_abs(fp)
        c = COL.get(place.region_of(ref), "k")
        ax.add_patch(Rectangle((r[0], r[1]), r[2] - r[0], r[3] - r[1], fill=False, lw=0.6, color=c))
        for p in fp.Pads():
            bb = p.GetBoundingBox()
            ax.add_patch(Rectangle((mm(bb.GetLeft()) - place.BX0, mm(bb.GetTop()) - place.BY0), mm(bb.GetWidth()),
                                   mm(bb.GetHeight()), color="#b08d57", alpha=0.55, lw=0))
        if labels:
            ax.text((r[0] + r[2]) / 2, (r[1] + r[3]) / 2, ref, fontsize=4.2 if (r[2] - r[0]) < 6 else 6,
                    ha="center", va="center", color=c)
    if ratsnest:
        nets = {}
        for fp in board.GetFootprints():
            for p in fp.Pads():
                if p.GetNetname() and p.GetNetname() not in ("GND",):
                    nets.setdefault(p.GetNetname(), []).append((mm(p.GetPosition().x) - place.BX0, mm(p.GetPosition().y) - place.BY0))
        for n, pts in nets.items():
            if len(pts) < 2 or len(pts) > 20:
                continue
            # simple star from first pad
            for q in pts[1:]:
                ax.plot([pts[0][0], q[0]], [pts[0][1], q[1]], color="#888", lw=0.25, alpha=0.6)
    ax.set_xlim(-22, 122); ax.set_ylim(104, -4); ax.set_aspect("equal")
    ax.set_xticks(range(0, 101, 10)); ax.set_yticks(range(0, 101, 10)); ax.grid(alpha=0.2)
    fig.tight_layout(); fig.savefig(out, dpi=110); plt.close(fig)


if __name__ == "__main__":
    draw(sys.argv[1], sys.argv[2], ratsnest="--rats" in sys.argv)
