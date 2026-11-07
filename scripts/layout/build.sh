#!/bin/bash
# Rebuild the rev B layout from the user's placement commit (KiCad 10).
#   scripts/layout/build.sh <placement-commit> [work-dir]
# The board in hardware/e-psu is replaced by the result; review the renders before committing.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
BASE="${1:?placement commit (the user's locked-anchor board)}"
W="${2:-$(mktemp -d)}"
PY="${KICAD_PYTHON:-kicad10-python}"
RULES="${PCB_RULES:-$REPO/.hw-skills/plugins/hardware-design/skills/pcb-design-rules/scripts/pcb_rules.py}"

mkdir -p "$W"
git -C "$REPO" show "$BASE:hardware/e-psu/e-psu.kicad_pcb" > "$W/e-psu.kicad_pcb"
cp "$REPO"/hardware/e-psu/e-psu.kicad_{pro,dru} "$REPO"/hardware/e-psu/*.kicad_sch "$W/"
cd "$HERE"
$PY widen.py "$W/e-psu.kicad_pcb" 10 10
$PY place.py "$W/e-psu.kicad_pcb"
$PY copper.py "$W/e-psu.kicad_pcb"
$PY octoroute.py "$W/e-psu.kicad_pcb"
$PY finish.py "$W/e-psu.kicad_pcb"
python3 "$RULES" check "$W/e-psu.kicad_pcb" --report "$W/pcb-quality.md" || true
cp "$W/e-psu.kicad_pcb" "$REPO/hardware/e-psu/e-psu.kicad_pcb"
echo "board written; report: $W/pcb-quality.md"
