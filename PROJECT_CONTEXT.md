# e-psu: project context

Paste or attach this file at the start of a new conversation to restore the context.

## What it is

e-psu is a public open-source project in the embedded-pro style (github.com/embedded-pro). The hardware repo is github.com/embedded-pro/e-psu-hardware (license CERN-OHL-P-2.0). It adds USB control to a 0–30 V / 10 A / 300 W bench power supply, similar to an Otii:

- set the output voltage and the current limit;
- measure current with µA resolution;
- switch the output on and off over USB.

It uses an STM32G474 and is built and assembled at JLCPCB/LCSC.

## Architecture (rev A1 schematic: KiCad 7, 8 pages)

### Input and power rails

- **Input:** 30 V from the bench PSU.
  - SMBJ33CA TVS.
  - AOD4185 P-FET for reverse polarity.
  - F101 5 A fuse on the precision path; F102 15 A fuse on the pass-through.
- **Housekeeping:**
  - LMR16006X 30 V → 5 V buck.
  - AMS1117 for +3V3.
  - TLV75533 for +3.3VA.
  - +5VA through a ferrite.
  - VOP = VIN through 10 Ω.
  - Optional LM2776 for VNEG (not fitted).

### Tracking pre-regulator

- LM76003 at 500 kHz.
- VPRE = VOUT + 1.5 V, set by injecting a DAC voltage into FB: VPRE = 33.8 V − 31.6 × BUCK_DAC.
- Firmware must keep BUCK_DAC ≥ 0.2 V.
- The footprint (TI RNP0030B) still has to be imported.

### Linear stage

- **Pass element:** IRFP260N source follower.
- **CC sense:** 15 mΩ shunt with INA293A2.
- **Error amps:** OPA2192 CV and CC amplifiers, diode-ORed onto the gate drive, with a 22 kΩ pull-up.
- **Sense buffer:** OPA192.
- **Setpoints:** DAC80502.
- **Protection and hold:**
  - Q302 holds the gate low at reset.
  - Q303 is the hardware OCP clamp (COMP3/4/6 → TIM20 BRK → OCP_TRIP).

### Current ranging

- 1 Ω (30 mA range) and 100 Ω (300 µA range) shunts, clamped by BAV199 diodes, with INA190A3 range amplifiers.
- AO3400A bypass FETs are driven by an isolated "island" referenced to VFORCE: B0505S DC/DC, AMS1117, CA-IS3720HS isolator, UCC27524A driver.
- Hardware range-up path:
  - COMP1 → TIM1 → RANGE_B
  - COMP2 → TIM8 → RANGE_A

### Output

- **10 A pass-through:** 2 mΩ shunt with INA281A3, through an HF115F relay. The NC contact is the precision path.
- **Output switch:** two NTMFS5C430N back to back, driven by a VOM1271.
- **Terminal sense:** VOUT_TERM divider.

### USB

USB-C, USBLC6 ESD protection and an ADuM3160 isolator.

## Simulation results (ngspice, `simulation/`, REPORT.md)

- **As drawn, the loops are unstable:**
  - CV loop phase margin is as low as −92° (unstable in 52 of 150 cases).
  - The CC loop has margins from −15° to 22°.
- **Changes, now in the schematic (rev A1):**
  - C304 1n → 5.6n C0G, plus a new R327 8.2 kΩ in series with it.
  - C305 → not fitted.
  - R305 10k → 3.9k.
  - C306 2.2n → 1n C0G.
  - R307 10k → 1k.
  - C307 4.7n → 1.5n.
  - Bleeder 2 → 10 mA: R319 → 68 Ω, R318 → 100 Ω, Q304 → SOT-89 NPN.
- **Result with these changes:**
  - CV loop: worst case 35°, median 63°; crossover 24 kHz at load, 4–7 kHz with no load.
  - CC loop: at least 91°.
- **Other findings:**
  - The hardware OCP must stay armed: a dead short is 33 A for 0.9 µs with it, versus ~95 µs of tens of amps without it.
  - Range-up takes 13–18 µs, limited by the INA190 slew rate.
  - Ripple rejection from VPRE is only 17 dB at 500 kHz with a 1 A load.
  - The analog CC loop can't limit below about 30 mA.
  - Down-programming with no load is slow.

## PCB (rev A, `hardware/e-psu/e-psu.kicad_pcb`, `scripts/pcb/`)

- **Board:** 100 × 100 mm, 4 layers: F signals and pours / In1 GND plane / In2 power planes / B signals and pours. JLCPCB standard process; specify 1 oz inner copper.
- **Placement:** follows the 3D mockup.
  - Banana jacks overhang the left and right edges.
  - Q301 (TO-247) sits at the right edge with its tab facing outward, for a heatsink.
  - The MCU is rotated 180° so its pins face their loads.
  - Escape room is kept clear around U601, U201 and U304.
- **Power copper:**
  - 10 A path as 3-layer pours with via arrays.
  - Ranging chain as three copper bars: VFORCE → N_MID → VSENSE.
  - VPRE and VSENSE corridors on In2.
  - Kelvin traces on R501 and R301. U501 is rotated, and its IN+ crosses on B.Cu.
- **In1 splits:** GND_USB under the PC side of the ADuM3160; VFORCE under the isolated ranging driver.
- **Routing:** scripted.
  - Plane fan-out, including QFN ground pins tied to the exposed pad.
  - Own grid router with rip-up, driven by KiCad DRC. Freerouting 2.1 left about 60 connections open on this board.
  - Escape rings around fine-pitch ICs.
  - Rebuild: `cd scripts/pcb && python3 make_board.py --own`, then `--tidy` if DRC shows anything.
- **Status:** fully routed. 244 parts, 887 vias. KiCad DRC: 0 errors, 0 unconnected, 39 silkscreen warnings.
- **Fab:** `scripts/export_jlcpcb.py` writes Gerbers, BOM and CPL to `manufacturing/e-psu/` (gitignored). Every GitHub Release attaches a bundle. JLC 4-layer, 1.6 mm, 1 oz inner.
- **Gotcha:** saving a board from Python makes KiCad overwrite the .kicad_pro net-class patterns, so call `copper.write_project()` after every save and run DRC in a fresh process.

## Still to check or do

- Pinouts against the makers' drawings: HF115F onto the RT1 footprint (8 pins, which matches), B0505S, and VOM1271 (pin 4 = +).
- Get KiCad ERC clean. kicad-bot (KiCad 10) runs ERC and DRC in CI and gates releases on them.
- **U201 footprint is provisional.** Import TI RNP0030B and re-route the buck corner before ordering.
- LCSC part numbers for the passives: 69 of 100 BOM lines are missing. Only ICs and special parts have them.
- Check the JLCPCB CPL rotations in their preview.

## Repository (same shape as embedded-pro/e-foc-hardware)

- `hardware/e-psu/`: KiCad 7 project (schematic, PCB, project symbols and footprints).
- `scripts/`: e-foc-style export helpers:
  - `export_review.py`;
  - `export_jlcpcb.py`;
  - `export_release.py`;
  - `visual_diff.py`.
- `scripts/pcb/`: board build scripts (`make_board.py`), router, copper plan (`power.py`), renders.
- `scripts/schgen/`: Python schematic generator. It is one-way and overwrites `hardware/e-psu/`.
- `simulation/`: ngspice suite that reads component values from `hardware/e-psu/`.
- `docs/`: the PSU design and review guide (`psu-hardware-design-guide.md`) and the board renders.
- `.claude/agents/psu-board-reviewer.md`: design-review agent.
- `.github/workflows/`:
  - kicad-bot ERC/DRC on every push and PR;
  - visual diff on PRs;
  - layout-quality gate on PRs (`pcb_rules.py check` from the pcb-design-rules skill, pinned by commit);
  - release-please releases with a fabrication bundle.
- Commit messages follow Conventional Commits (`feat:`, `fix:`, `chore:`, …), which drive the version and the CHANGELOG.
