"""Render layers of a board to PNG: python3 render.py board.kicad_pcb out.png "F.Cu,F.Courtyard,Edge.Cuts" [width]"""
import os, subprocess, sys, tempfile
import cairosvg

board, out, layers = sys.argv[1], sys.argv[2], sys.argv[3]
width = int(sys.argv[4]) if len(sys.argv) > 4 else 1600
svg = tempfile.NamedTemporaryFile(suffix=".svg", delete=False).name
subprocess.run(["kicad10-cli", "pcb", "export", "svg", "-l", layers, "--exclude-drawing-sheet", "--page-size-mode", "2",
                "-o", svg, board], check=True, capture_output=True)
cairosvg.svg2png(url=svg, write_to=out, output_width=width, background_color="white")
os.unlink(svg)
