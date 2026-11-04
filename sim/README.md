# e-psu analog simulations (ngspice)

This folder simulates the linear CV/CC stage, the current ranging and the output path. Component values are read from `../kicad/*.kicad_sch`, so changing a value in KiCad changes the simulation. The results are in [REPORT.md](REPORT.md).

Put this folder next to the KiCad project, so the repo has `kicad/` and `sim/` side by side, or set `EPSU_KICAD=/path/to/kicad`.

## Requirements

- ngspice 40 or newer (`apt install ngspice`)
- Python 3.10+ with numpy and matplotlib

## Run

```bash
python3 sweep.py          # stability matrices (CV and CC, as drawn and proposed) -> results/*.csv, ~6 min on 2 cores
python3 make_plots.py     # transients, AC, buck injection, all plots -> plots/, results/summary.json, ~1 min
python3 corners.py '{"R305": 4700}' trial   # quick 18-corner stability check of a value change
python3 tune.py candidates.json             # margins + load-step settling for several candidate sets
```

## Files

| File | What it does |
|---|---|
| `epsu_analog.py` | Builds the netlist from the KiCad values. `PROPOSED` holds the recommended changes, and `comp=` overrides any value. |
| `kicad_values.py` | Reads the reference designators and values from the schematic (skips DNP parts). |
| `spice.py` | Runs ngspice in batch mode. Also finds operating points by settling a DC-identical damped copy, and computes Tian loop gain and margins. |
| `loop.py` | Loop gain at the gate-drive node |
| `corners.py`, `sweep.py`, `tune.py` | Corner sets, full matrices and candidate comparisons |
| `transients.py`, `make_plots.py` | Load steps, range-up logic, short circuit with and without OCP, setpoint steps, PSRR, Zout, buck FB injection |
| `models/` | Op-amp and sense-amp macromodels; MOSFET, diode and BJT models. Sources are listed in REPORT.md. |

The schematic (rev A1) now includes the proposed changes, R327 included, so `comp={}` simulates the current design. REPORT.md compares rev A as it was drawn with these changes.
