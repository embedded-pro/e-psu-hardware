# e-psu — Hardware

[![kicad-bot](https://github.com/embedded-pro/e-psu-hardware/actions/workflows/kicad-bot.yml/badge.svg)](https://github.com/embedded-pro/e-psu-hardware/actions/workflows/kicad-bot.yml)
[![KiCad](https://img.shields.io/badge/KiCad-7-blue.svg)](https://www.kicad.org/)
[![License](https://img.shields.io/badge/license-CERN--OHL--P--2.0-green.svg)](LICENSE)

e-psu is an open-source, USB-controlled front end for a 0–30 V / 10 A bench power supply. It sets the output voltage and current limit, measures current with auto-ranging down to µA resolution, and switches the output, similar to an Otii.

This repository holds the **KiCad** design (schematic and a fully routed 4-layer PCB), the scripts that generate and route the board, and the ngspice simulation of the analog stage. The board sits between an external 30 V bench supply and the load. An STM32G474 runs the control loops' setpoints, the range switching and the USB link.

> **Scope:** this repo is the *hardware*. Firmware is not part of it. The hardware facts the firmware must respect are listed in [Firmware constraints](#firmware-constraints).

| Top | Bottom |
|---|---|
| ![top](docs/images/e-psu-revA-top.png) | ![bottom](docs/images/e-psu-revA-bottom.png) |

> **Status: rev A, not built yet.** The schematic is complete and simulated. The board is fully routed: KiCad 7 DRC shows 0 errors and 0 unconnected items. See [Before ordering](#before-ordering).

---

## Highlights

- **Tracking pre-regulator plus linear stage.** An `LM76003` buck keeps VPRE about 1.5 V above the output. An `IRFP260N` source follower then gives a clean output with low dissipation.
- **Analog CV/CC loops.** `OPA2192` voltage and current error amps are diode-ORed onto the gate drive. Setpoints come from a `DAC80502`, and the loops were compensated from ngspice stability sweeps ([report](simulation/REPORT.md)).
- **Three current ranges, switched in hardware:**
  - 3 A on a 15 mΩ shunt with `INA293`;
  - 30 mA on 1 Ω with `INA190`;
  - 300 µA on 100 Ω with `INA190`.
  
  The bypass FETs sit on an isolated gate-drive island referenced to the output. Range-up is triggered by MCU comparators through timers, without firmware latency.
- **10 A pass-through path.** A 2 mΩ shunt with `INA281`, selected by a relay, measures current at the full 300 W.
- **Output switch.** Back-to-back `NTMFS5C430N` FETs driven by a `VOM1271` photovoltaic driver. The gate is held low at reset.
- **Hardware overcurrent clamp.** STM32G474 comparators drive the TIM20 break input, so the clamp acts within about 1 µs.
- **Isolated USB-C.** `ADuM3160` isolation, `USBLC6` ESD protection, and a separate ground plane for the PC side.
- **Input protection.** TVS, reverse-polarity P-FET, and fuses on both paths.

---

## Board architecture

The schematic is an 8-sheet hierarchical design. Each sheet is one functional block:

| Sheet | Function | Key parts |
|-------|----------|-----------|
| `e-psu.kicad_sch` | Top level: block overview, power flow, ground domains | — |
| `power_input` | 30 V input protection, housekeeping rails (+5 V, +3V3, +3.3VA, +5VA, VOP) | `SMBJ33CA`, `AOD4185`, `LMR16006X`, `AMS1117`, `TLV75533` |
| `buck` | Tracking pre-regulator (VPRE = VOUT + 1.5 V by DAC injection into FB) | `LM76003` |
| `linear` | Pass element, CV/CC loops, sense buffer, setpoint DAC, OCP clamp | `IRFP260N`, `OPA2192`, `OPA192`, `INA293`, `DAC80502` |
| `ranging` | Shunt ladder, range amplifiers, isolated gate-drive island | `INA190`, `AO3400A`, `B0505S`, `CA-IS3720HS`, `UCC27524A` |
| `output` | 10 A pass-through, mode relay, back-to-back output switch, terminals | `INA281`, `HF115F`, `NTMFS5C430N`, `VOM1271` |
| `mcu` | MCU pin map, SWD, LEDs, button, board NTC | `STM32G474RET6` |
| `usb` | Isolated USB-C | `USBLC6`, `ADuM3160` |

---

## Design requirements (spec)

These are the **hard design targets** the board must meet. They are the authoritative requirements for design review and sign-off.

| # | Requirement | Target |
|---|-------------|--------|
| R1 | Input | **30 V DC** from an external bench supply. Reverse-polarity and surge protected. |
| R2 | Output voltage | **0–30 V**, programmable (CV) |
| R3 | Output current, precision path | **3 A** max, programmable current limit (CC) |
| R4 | Output current, pass-through | **10 A** (300 W) through a relay-selected low-loss path |
| R5 | Current measurement | Auto-ranging **3 A / 30 mA / 300 µA**, µA resolution, hardware range-up |
| R6 | Output control | Output switch with a **safe state at reset** (output off, gate held low) |
| R7 | Protection | Hardware overcurrent clamp, fuses, input TVS, board temperature sensor |
| R8 | Host interface | **USB-C, galvanically isolated** from the power ground |
| R9 | PCB | **4 layers**, 100 × 100 mm, JLCPCB standard process and assembly |

### As-built component capability

| Parameter | Value |
|-----------|-------|
| Pre-regulator | `LM76003` synchronous buck, 500 kHz. VPRE = 33.8 V − 31.6 × BUCK_DAC. |
| Pass element | `IRFP260N` (TO-247) source follower at the board edge, ready for a heatsink |
| Control | Analog CV/CC loops (`OPA2192`), `DAC80502` setpoints, `OPA192` sense buffer |
| Current sense | 15 mΩ + `INA293` (3 A), 1 Ω / 100 Ω + `INA190` (30 mA / 300 µA), 2 mΩ + `INA281` (10 A) |
| Range switching | `AO3400A` bypass FETs, `BAV199` clamps, isolated island (`B0505S` + `CA-IS3720HS` + `UCC27524A`) |
| Output | `HF115F` mode relay; back-to-back `NTMFS5C430N` switch with a `VOM1271` driver |
| MCU | `STM32G474RET6`: comparators and timers for OCP and range-up, SWD |
| USB | USB-C, `USBLC6-2` ESD, `ADuM3160` full-speed isolator |
| PCB | 4 layers (F sig / In1 GND / In2 power / B sig), 1.6 mm, 1 oz outer + **1 oz inner**, 244 parts |

### Simulation results

The loops were checked across corners with ngspice. The compensation changes from the sweep are in schematic rev A1:

- CV loop phase margin: worst case 35°, median 63°.
- CC loop phase margin: at least 91°.
- A dead short peaks at 33 A for 0.9 µs with the hardware OCP armed.

Details are in [`simulation/REPORT.md`](simulation/REPORT.md).

### Firmware constraints

- Clamp **BUCK_DAC ≥ 0.2 V** (VPRE = 27.5 V). At 0 V, VPRE is commanded above VIN and the buck runs at maximum duty. In reset, the DAC pin is high-impedance, which gives a safe 2 V.
- Keep the **hardware OCP armed**: COMP3/4/6 → TIM20 BRK. Without it, a short is limited only by the analog CC loop, giving tens of amps for about 95 µs.
- **Range-up is in hardware:** COMP1 → TIM1 → RANGE_B and COMP2 → TIM8 → RANGE_A. Firmware only handles range-down.
- The analog CC loop cannot limit below about 30 mA. Lower limits need firmware supervision.

---

## Repository layout

```
e-psu-hardware/
├── hardware/                       # KiCad projects — one folder per board
│   └── e-psu/                      #   main board (KiCad 7 format)
│       ├── e-psu.kicad_pro
│       ├── e-psu.kicad_sch         #     top-level (root) schematic
│       ├── power_input / buck / linear / ranging / output / mcu / usb .kicad_sch
│       ├── e-psu.kicad_pcb         #     PCB layout (4 layers)
│       ├── e-psu.kicad_sym         #     project symbols
│       ├── e-psu.pretty/           #     project footprints
│       └── sym-lib-table, fp-lib-table
├── scripts/
│   ├── export_review.py            # review package     -> review_exports/<board>/
│   ├── export_jlcpcb.py            # fab + assembly     -> manufacturing/<board>/
│   ├── export_release.py           # release bundle     -> release/<board>-<version>.zip
│   ├── visual_diff.py              # PR visual diff     -> diff/<board>/
│   ├── pcb/                        # board generator: placement, power copper, router, renders
│   └── schgen/                     # schematic generator (one-way: overwrites hardware/e-psu/)
├── simulation/                     # ngspice suite of the analog stage + REPORT.md
├── docs/
│   ├── psu-hardware-design-guide.md   # design & review knowledge base
│   └── images/                     # board renders
├── .claude/agents/psu-board-reviewer.md   # design-review agent
├── PROJECT_CONTEXT.md              # design summary, decisions, open items
└── .github/workflows/              # CI: kicad-bot, kicad-diff, pcb-quality, release
```

> Each board is a self-contained KiCad project in its own `hardware/<board>/` folder. The `.kicad_pro`, root schematic and board share that folder. Generated outputs are gitignored and go to `review_exports/<board>/`, `manufacturing/<board>/` and `release/`.

---

## Getting started

This is a [**KiCad**](https://www.kicad.org/) project saved in KiCad 7 format. It opens in KiCad 7 or newer.

1. Clone the repository:
   ```bash
   git clone https://github.com/embedded-pro/e-psu-hardware.git
   cd e-psu-hardware
   ```
2. Open `hardware/e-psu/e-psu.kicad_pro` in KiCad.
3. Use the schematic editor for the hierarchical sheets, or the PCB editor for the layout.

### Headless checks (the same ones CI runs)

With KiCad 8 or newer installed, you can run the electrical and design-rule checks locally:

```bash
kicad-cli sch erc  --output erc.json --format json hardware/e-psu/e-psu.kicad_sch
kicad-cli pcb drc  --output drc.json --format json --schematic-parity hardware/e-psu/e-psu.kicad_pcb
```

The export helpers produce the full packages:
- `python scripts/export_review.py` builds the review package;
- `python scripts/export_jlcpcb.py` builds the JLCPCB fab and assembly files.

### Regenerating the board and the simulation

- `scripts/pcb/make_board.py --own` rebuilds and re-routes the board from the schematic. It needs KiCad 7 and pcbnew; see [`scripts/pcb/README.md`](scripts/pcb/README.md).
- `simulation/sweep.py` and `simulation/make_plots.py` rerun the analog simulation with ngspice; see [`simulation/README.md`](simulation/README.md).

---

## Before ordering

1. **Replace the U201 footprint.** The `LM76003` land (TI RNP0030B, WQFN-30, 6 × 4 mm) in `e-psu.pretty` is provisional.
   - Get the real one from TI, or from LCSC/EasyEDA (C470958).
   - Save it as `e-psu:TI_RNP0030B_WQFN-30`.
   - Re-route the buck corner, either with `scripts/pcb/make_board.py --own` or by hand.
2. **Check these pinouts against the makers' drawings:**
   - K501 `HF115F`, mapped onto the KiCad Schrack RT1 footprint;
   - PS401 `B0505S`;
   - U502 `VOM1271`: pin 4 is assumed to be +.
3. **Get ERC clean.** kicad-bot runs it on every push.
4. **JLCPCB order options:**
   - 4 layers, 1.6 mm, **1 oz inner copper** (needed for the 10 A path on In2);
   - "Specify a location" for the order number (the `JLCJLCJLCJLC` text on the bottom);
   - check every rotation in the CPL preview.
5. **Add LCSC part numbers** for the passives that don't have one yet. THT parts are hand-soldered or ordered as THT assembly: banana jacks, F102, K501, Q301, PS401.

---

## Continuous integration

Every push and pull request is checked by [**kicad-bot**](https://github.com/embedded-pro/kicad-bot). It is a CI quality gate that wraps `kicad-cli`, KiBot, KiCost and KiDiff, and runs:

- **ERC / DRC verification:** electrical and design-rule checks, with schematic parity.
- **BOM availability:** distributor stock and lifecycle flags (not available in kicad-bot yet).
- **Visual diffs:** for pull requests, [`kicad-diff.yml`](.github/workflows/kicad-diff.yml) renders the base and head with `kicad-cli` and uploads red/green overlays.
- **Layout quality:** for pull requests, [`pcb-quality.yml`](.github/workflows/pcb-quality.yml) runs a hard short/clearance gate (exclusions ignored, plus the fab minimum), DRC and geometry gates (45° corners only, no mid-track branches, jogs, segments and vias per connection) with `pcb_rules.py` from the [`pcb-design-rules`](https://github.com/gabrielfrasantos/claude-hardware-skills/tree/main/plugins/hardware-design/skills/pcb-design-rules) skill. The report is in the job summary. It stays red until the board is re-laid out.

The workflow is [`.github/workflows/kicad-bot.yml`](.github/workflows/kicad-bot.yml). It uploads a `kicad-bot-output-<board>` artifact containing the report, metrics and raw violation data.

> kicad-bot is a CI guardrail, **not** a substitute for design review or sign-off. For a review, use the `psu-board-reviewer` agent in [`.claude/agents/`](.claude/agents/).

All third-party actions are **pinned to a full commit SHA**, with the version in a trailing comment, for supply-chain hardening.

## Releases

Releases are automated with [release-please](https://github.com/googleapis/release-please) and driven by [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, …). The flow, defined in [`.github/workflows/release.yml`](.github/workflows/release.yml):

1. Commits to `main` keep an open **release PR** with the next version bump and the `CHANGELOG.md` entries.
2. Merging that PR cuts a **GitHub Release** and a tag. The first release is `v0.1.0`.
3. On release, kicad-bot re-runs **ERC/DRC**, so a release requires a clean design. Then `scripts/export_release.py` builds `e-psu-<version>.zip` and attaches it to the release. The zip contains:
   - the schematic PDF;
   - board PDFs (copper and silkscreen, inner layers included);
   - Gerbers and drill files;
   - BOM and CPL.

Version state is tracked in [`.release-please-manifest.json`](.release-please-manifest.json). The behaviour is configured in [`release-please-config.json`](release-please-config.json).

---

## License

Released under the [CERN Open Hardware Licence Version 2 – Permissive](LICENSE) (CERN-OHL-P-2.0).
