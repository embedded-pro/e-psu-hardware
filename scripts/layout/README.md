# scripts/layout: rev B layout flow (KiCad 10)

Scripts that take the user's placement (locked anchors + outline) to a routed board that passes
`pcb_rules.py check` from the [`pcb-design-rules`](https://github.com/gabrielfrasantos/claude-hardware-skills/tree/main/plugins/hardware-design/skills/pcb-design-rules) skill.
Run them with KiCad 10's Python (`kicad10-python` here; any Python that can `import pcbnew` from KiCad 10).

| Step | Script | What it does |
|---|---|---|
| 1 | `widen.py board L R` | Moves the left/right edges out by L/R mm, with the jacks and mounting holes tied to them |
| 2 | `place.py board` | Hand anchors for the power parts + region-based placer for the rest; locked parts never move |
| 3 | `copper.py board` | In1 GND plane with the isolated GND_USB island, In2 +3V3 plane with VIN_PROT / VPRE / Q301-source corridors, outer-layer pours along the 10 A and 5 A paths |
| 4 | `octoroute.py board --out routed` | Octilinear grid router: Kelvin sense traces first, plane fan-out, then every other connection pad to pad |
| 5 | `finish.py board` | GND pours on F.Cu/B.Cu, stitching vias, references placed clear of pads |
| 6 | `pcb_rules.py check board` | DRC + shorts/clearance + fab floor + geometry gates |

`render.py board out.png "F.Cu,Edge.Cuts"` renders layers for review; `dump.py` writes footprint geometry to JSON.

## Router rules (`octoroute.py`)

- 0.1 mm grid on F.Cu (preferred horizontal) and B.Cu (preferred vertical); 0.6/0.3 mm vias.
- Moves in 8 directions; turns of 45° only, with a minimum straight run between turns. No any-angle
  segments, no 90° or acute corners, no jogs.
- Tracks start and end on pads, pours or a via into the net's plane, never on another track: no tees.
- Clearance = max(net classes) + half the track width, from the project's net classes.
- Kelvin pairs (sense amplifier → shunt pad inner half) are routed first and protected by no-fill strips.

## Known limits

- Single pass with re-ordering instead of rip-up: nets that fail are routed first in the next run (`--first`).
- Differential pairs (USB) are routed as two single nets; at full speed (12 Mbit/s) the mismatch is irrelevant.
