"""Photo-style top/bottom renders: kicad-cli SVG per layer, rasterised and composited (mask green,
gold pads, white silkscreen)."""
import io
import os
import subprocess
import sys
import tempfile

import cairosvg
import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
PCB = os.path.join(HERE, "..", "..", "hardware", "e-psu", "e-psu.kicad_pcb")
DPI = 20      # pixels per mm


def layer_mask(layer, mirror, tmp):
    svg = os.path.join(tmp, layer.replace(".", "_") + ".svg")
    args = ["kicad-cli", "pcb", "export", "svg", "-o", svg, "-l", f"{layer},Edge.Cuts", "--page-size-mode", "2",
            "--exclude-drawing-sheet", "--black-and-white"]
    if mirror:
        args.append("-m")
    subprocess.run(args + [PCB], check=True, capture_output=True)
    png = cairosvg.svg2png(url=svg, scale=DPI / 3.7795, background_color="white")
    a = np.asarray(Image.open(io.BytesIO(png)).convert("L"), np.float32) / 255.0
    return a < 0.5


def render(side, out):
    mirror = side == "bottom"
    p = "F" if side == "top" else "B"
    with tempfile.TemporaryDirectory() as tmp:
        edge = layer_mask("Edge.Cuts", mirror, tmp)
        cu = layer_mask(f"{p}.Cu", mirror, tmp) & ~edge
        mask = layer_mask(f"{p}.Mask", mirror, tmp) & ~edge
        silk = layer_mask(f"{p}.Silkscreen", mirror, tmp) & ~edge
    ys, xs = np.nonzero(edge)
    board = np.zeros_like(edge)
    board[ys.min():ys.max() + 1, xs.min():xs.max() + 1] = True
    img = np.zeros(edge.shape + (3,), np.float32)
    img[:] = (0.96, 0.96, 0.95)
    img[board] = (0.09, 0.33, 0.17)                     # solder mask over bare laminate
    img[board & cu] = (0.16, 0.45, 0.24)                # copper under mask
    img[mask & ~cu] = (0.62, 0.55, 0.38)                # mask opening without copper (holes, slots)
    img[mask & cu] = (0.83, 0.68, 0.33)                 # ENIG/HASL pads
    img[silk & ~mask] = (0.97, 0.97, 0.95)              # silkscreen
    img[edge] = (0.2, 0.2, 0.2)
    Image.fromarray((img * 255).astype(np.uint8)).save(out)
    return out


if __name__ == "__main__":
    outdir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "..", "..", "docs", "images")
    for s in ("top", "bottom"):
        print(render(s, os.path.join(outdir, f"e-psu-revA-{s}.png")))
