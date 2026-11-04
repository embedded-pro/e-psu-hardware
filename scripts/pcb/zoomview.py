"""Zoomed view with pads labelled by short net name (for designing copper)."""
import sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, Polygon
import pcbnew
import place

SHORT = lambda n: n.split("/")[-1].replace("Net-(", "").replace(")", "")[:9]


def zoom(path, out, x0, y0, x1, y1, polys=()):
    b = pcbnew.LoadBoard(path)
    fig, ax = plt.subplots(figsize=(14, 14 * (y1 - y0) / (x1 - x0)))
    cols = {}
    pal = plt.cm.tab20.colors
    for fp in b.GetFootprints():
        r = place.crtyd_abs(fp)
        if r[2] < x0 or r[0] > x1 or r[3] < y0 or r[1] > y1:
            continue
        ax.add_patch(Rectangle((r[0], r[1]), r[2] - r[0], r[3] - r[1], fill=False, lw=0.5, color="#888"))
        ax.text(r[0], r[1], fp.GetReference(), fontsize=6, color="#444", va="bottom")
        for p in fp.Pads():
            bb = p.GetBoundingBox()
            n = p.GetNetname()
            c = cols.setdefault(n, pal[len(cols) % 20]) if n else (0.6, 0.6, 0.6)
            x, y = pcbnew.ToMM(bb.GetLeft()) - place.BX0, pcbnew.ToMM(bb.GetTop()) - place.BY0
            w, h = pcbnew.ToMM(bb.GetWidth()), pcbnew.ToMM(bb.GetHeight())
            ax.add_patch(Rectangle((x, y), w, h, color=c, alpha=0.7, lw=0))
            if n and n != "GND":
                ax.text(x + w / 2, y + h / 2, SHORT(n), fontsize=4.5, ha="center", va="center")
            elif n == "GND":
                ax.text(x + w / 2, y + h / 2, "G", fontsize=4.5, ha="center", va="center")
    for pts, c in polys:
        ax.add_patch(Polygon(pts, closed=True, fill=False, color=c, lw=1.2))
    ax.set_xlim(x0, x1); ax.set_ylim(y1, y0); ax.set_aspect("equal")
    import numpy as np
    ax.set_xticks(np.arange(x0, x1 + 0.1, 1), minor=True); ax.set_yticks(np.arange(y0, y1 + 0.1, 1), minor=True)
    ax.grid(which="minor", alpha=0.15); ax.grid(which="major", alpha=0.4)
    fig.tight_layout(); fig.savefig(out, dpi=100); plt.close(fig)


if __name__ == "__main__":
    a = [float(v) for v in sys.argv[3:7]]
    zoom(sys.argv[1], sys.argv[2], *a)
