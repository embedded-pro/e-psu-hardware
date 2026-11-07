"""Per-layer review renders: python3 review.py board.kicad_pcb out_dir
Writes top.png (F.Cu + F.Silkscreen), bottom.png (B.Cu), in1.png, in2.png and a 2x2 overview."""
import os
import subprocess
import sys
import tempfile

import cairosvg
from PIL import Image

board, out = sys.argv[1], sys.argv[2]
os.makedirs(out, exist_ok=True)
SETS = {"top": "F.Cu,F.Silkscreen,Edge.Cuts", "bottom": "B.Cu,Edge.Cuts", "in1": "In1.Cu,Edge.Cuts", "in2": "In2.Cu,Edge.Cuts"}
imgs = []
for name, layers in SETS.items():
    svg = tempfile.NamedTemporaryFile(suffix=".svg", delete=False).name
    args = ["kicad10-cli", "pcb", "export", "svg", "-l", layers, "--exclude-drawing-sheet", "--page-size-mode", "2", "-o", svg, board]
    if name == "bottom":
        args.insert(-1, "--mirror")
    subprocess.run(args, check=True, capture_output=True)
    png = os.path.join(out, name + ".png")
    cairosvg.svg2png(url=svg, write_to=png, output_width=2400, background_color="white")
    os.unlink(svg)
    imgs.append(Image.open(png))
w, h = imgs[0].size
sheet = Image.new("RGB", (w, h * 2 + 40), "white")
sheet.paste(imgs[0], (0, 0))
sheet.paste(imgs[1].resize((w // 2 - 10, h // 2)), (0, h + 40))
sheet.paste(imgs[2].resize((w // 4 - 10, h // 4)), (w // 2, h + 40))
sheet.paste(imgs[3].resize((w // 4 - 10, h // 4)), (3 * w // 4, h + 40))
sheet.save(os.path.join(out, "overview.png"))
print("renders in", out)
