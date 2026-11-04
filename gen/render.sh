#!/bin/bash
set -e
cd "$(dirname "$0")"
python3 epsu.py | grep -E "ERC errors|warnings|Footprint check|Layout lint|  [EWL] " 
python3 check.py ../kicad/e-psu.kicad_sch expected.json
cd ../kicad && kicad-cli sch export pdf -o e-psu.pdf e-psu.kicad_sch >/dev/null 2>&1
D=/tmp/claude-0/-home-claude/1343fb3e-9000-5805-86c8-032e2c5e8cd4/scratchpad/pages3
mkdir -p "$D"
pdftoppm -r ${RES:-110} -png e-psu.pdf "$D/p"
python3 - "$D" <<'PY'
import sys, glob
from PIL import Image
D = sys.argv[1]
for f in sorted(glob.glob(D + '/p-*.png')):
    im = Image.open(f); W, H = im.size
    im.crop((int(W*0.03), int(H*0.06), int(W*0.97), int(H*0.72))).save(f.replace('/p-', '/c-'))
PY
echo rendered
