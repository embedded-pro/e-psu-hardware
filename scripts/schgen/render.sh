#!/bin/bash
set -e
cd "$(dirname "$0")"
python3 epsu.py | grep -E "ERC errors|warnings|Footprint check|Layout lint|  [EWL] " 
python3 check.py ../../hardware/e-psu/e-psu.kicad_sch expected.json
D=${OUT:-$(mktemp -d)}
mkdir -p "$D"
kicad-cli sch export pdf -o "$D/e-psu.pdf" ../../hardware/e-psu/e-psu.kicad_sch >/dev/null 2>&1
pdftoppm -r ${RES:-110} -png "$D/e-psu.pdf" "$D/p"
python3 - "$D" <<'PY'
import sys, glob
from PIL import Image
D = sys.argv[1]
for f in sorted(glob.glob(D + '/p-*.png')):
    im = Image.open(f); W, H = im.size
    im.crop((int(W*0.03), int(H*0.06), int(W*0.97), int(H*0.72))).save(f.replace('/p-', '/c-'))
PY
echo "rendered into $D"
