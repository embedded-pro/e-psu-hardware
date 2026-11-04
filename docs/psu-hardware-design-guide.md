# Programmable Bench-PSU Hardware Design Guide

> This guide is a **component-agnostic** body of knowledge for designing and reviewing a programmable linear power supply / source-measure front end. Such a board has:
> - a tracking pre-regulator;
> - a linear pass stage with CV/CC loops;
> - auto-ranging current measurement;
> - a high-current pass-through;
> - an isolated host interface.
>
> It records what a senior analog and power engineer checks when designing the stages, protecting them, and laying them out.
>
> Treat this guide as an **interface**, not an implementation. It describes the *functional blocks* and the *parameters* that constrain them. It never names specific part numbers. A board is one implementation of this interface. Its concrete parts and numeric targets live in that board's **README / spec**, which is the binding contract. When this guide and a board's spec disagree, the **spec wins**.
>
> **Design parameters.** A board's spec fixes their values. They are used throughout:
>
> | Symbol | Meaning |
> |---|---|
> | $V_{in}$ | Maximum input voltage |
> | $V_{out}$ | Maximum programmable output voltage |
> | $I_{p}$ | Maximum current of the precision (linear) path |
> | $I_{pt}$ | Maximum current of the pass-through path |
> | $V_{hr}$ | Pre-regulator headroom above the output |
> | $I_{FS,k}$ | Full-scale current of measurement range *k* |
> | $f_{sw}$ | Pre-regulator switching frequency |
> | $N_{layer}$ | PCB copper layers |

---

## Table of contents

1. [System overview](#1-system-overview)
2. [Input & protection](#2-input--protection)
3. [Housekeeping rails](#3-housekeeping-rails)
4. [Tracking pre-regulator](#4-tracking-pre-regulator)
5. [Linear pass stage](#5-linear-pass-stage)
6. [CV/CC control loops & stability](#6-cvcc-control-loops--stability)
7. [Current measurement & auto-ranging](#7-current-measurement--auto-ranging)
8. [Output path: pass-through, relay, output switch](#8-output-path-pass-through-relay-output-switch)
9. [Protection & safe state](#9-protection--safe-state)
10. [Isolation](#10-isolation)
11. [Thermal design](#11-thermal-design)
12. [PCB layout](#12-pcb-layout)
13. [KiCad workflow: tips & tricks](#13-kicad-workflow-tips--tricks)
14. [Design-review checklist](#14-design-review-checklist)
15. [References](#15-references)

---

## 1. System overview

A programmable supply has three jobs:
- turn an unregulated or coarse input into a **clean, programmable output**;
- **limit and measure** the output current accurately over many decades;
- **fail safe** when the load, the cable or the firmware misbehaves.

```
 Vin ─ TVS ─ rev.pol ─ fuse ─┬──────────────────────── pass-through (shunt) ───┐
                             │                                                 │ relay
                             └─ tracking buck ─ VPRE ─ linear pass ─ range ────┤ (mode)
                                (VPRE ≈ VOUT + Vhr)       element     shunts   │
                                                          ▲  ▲               output switch
                                       CV / CC error amps ┘  └ sense amps      │
                                       (setpoint DAC)          (ADC, comparators)
                                                                            OUT+ / OUT−
   MCU ─ isolator ─ USB          isolated gate drive for range FETs (floating island)
```

The **pre-regulator** sets efficiency. The **linear stage** sets noise, accuracy and transient response. The **range shunts** set measurement dynamic range. **Protection** decides whether a mistake costs a fuse or a board.

---

## 2. Input & protection

### 2.1 Surge and reverse polarity
- **TVS standoff ≥ $V_{in}$ max**, including the source's own overshoot. A TVS clamps at roughly 1.4–1.6 × its standoff voltage at rated pulse current. **Every part on the input rail must survive the clamp voltage**, not only the standoff: regulators, bulk caps, and the reverse-polarity FET's $V_{DS}$.
- **Reverse polarity.** A P-FET in the positive line, with a gate-source Zener clamp, costs only $I^2 R_{DS(on)}$. A series diode costs $V_f \cdot I$, which is unacceptable at high current. Check the FET's $V_{GS}$ abs-max against $V_{in}$ and confirm the Zener holds it.
- **Inrush.** Large bulk capacitance behind a hot-plugged bench supply sees a large charging spike. Check fuse I²t and FET SOA for that pulse.

### 2.2 Fusing
- **Fuse each path separately.** The precision path's fuse rating sits just above $I_p$. The pass-through fuse sits above $I_{pt}$.
- A fuse is a **fire backstop**, not circuit protection. Electronic limits must act long before the fuse does (§9).
- Check the fuse's **voltage rating** and **breaking capacity** against the source, and its **derating at temperature** (typically 75–80 % of the nominal rating).

---

## 3. Housekeeping rails

- **Logic and analog rails are separate.** Feed the precision analog parts (references, ADC/DAC, sense amplifiers) from a low-noise LDO or a ferrite-filtered branch, not straight from a buck output.
- **Op-amp supply headroom.** The CV/CC error amplifiers drive the pass-element gate, which sits **above the output** by $V_{GS}$ in a source follower. Their supply must exceed $V_{out}$ max + $V_{GS}$ at $I_p$ + the output-swing margin. Feeding them from $V_{in}$ through a small series resistor is common.
- **Near 0 V.** To regulate down to 0 V and 0 A, the amplifiers' outputs and inputs must work at ground. Use rail-to-rail parts with enough margin, or provide a small negative rail. Document the lowest guaranteed voltage and current.
- **Sequencing and reset.** At power-up the MCU is in reset, so DAC outputs are high-impedance and GPIOs float. Every setpoint and enable needs a **defined default** from pull-ups or pull-downs that commands output off and minimum current (§9.3).

---

## 4. Tracking pre-regulator

The pre-regulator keeps the linear stage's input $V_{PRE}$ ≈ $V_{OUT}$ + $V_{hr}$, so the pass element only drops $V_{hr}$.

- **Headroom $V_{hr}$.** It must cover:
  - the pass element's $V_{GS}$ at $I_p$ (source follower), or its dropout;
  - the shunt burden voltage;
  - the pre-regulator's output ripple;
  - the load-step dip before the pre-regulator responds.
  
  A larger $V_{hr}$ means more heat. Too small, and the linear stage saturates and loses PSRR.
- **Setpoint by FB injection.** A DAC injects current into the regulator's feedback node through a resistor:
  - Derive the transfer function, e.g. $V_{PRE} = a - b \cdot V_{DAC}$.
  - Check the **end points**: the DAC code that commands $V_{PRE} > V_{in}$ forces maximum duty, or dropout. Firmware must clamp it.
  - Check the **reset state**: a high-impedance DAC must give a *safe* $V_{PRE}$.
  - Confirm the **step size** per DAC LSB.
- **Response.** The pre-regulator is slower than the linear loop. During an output up-step, $V_{PRE}$ lags. During a short, $V_{PRE}$ is still high while the output collapses, so the pass element sees $V_{PRE}$ × $I_{limit}$ until the tracking catches up. Size the SOA for that case (§5.2).
- **Ripple and PSRR.** Linear-stage PSRR falls with frequency. At $f_{sw}$ it is often only tens of dB, so filter $V_{PRE}$ with an LC or π stage, or accept the ripple and state it in the spec.
- **Layout.** Keep the hot loop (input cap → switch → GND) minimal. Keep the switch node small, and keep it away from the sense amplifiers and the shunts. Use the vendor's recommended land and exposed-pad vias exactly (§12).

---

## 5. Linear pass stage

### 5.1 Topology
- A **source follower** (N-FET, drain on $V_{PRE}$) is inherently stable and has low output impedance. Its gate must swing above the output, so the driver needs headroom (§3).
- A **common-source** (P-FET) stage gives low dropout but has more gain inside the loop and needs more compensation.

### 5.2 Safe operating area — the most common cause of dead linear supplies
- Worst-case continuous dissipation is $P = (V_{PRE} - V_{OUT}) \cdot I$. With tracking, that is $V_{hr} \cdot I_p$. **Without** tracking (pre-regulator fault, DAC at the wrong end, transient), it is up to $V_{in} \cdot I_p$.
- Check the **DC SOA at the real case temperature**, not at 25 °C. Datasheet DC SOA curves are often extrapolated.
- **Linear-mode instability (Spirito effect).** Modern trench MOSFETs have a positive temperature coefficient of drain current at low $V_{GS}$. In linear mode, hot spots then run away. **Prefer planar MOSFETs, or parts specified for linear mode.** Treat a trench part's DC SOA with suspicion.
- For several pass elements in parallel, each needs its own **source resistor** so they share current.
- Transients count: a short with $V_{PRE}$ still high is a single-pulse SOA check of $V_{PRE} \cdot I_{limit}$ for the pre-regulator's settling time.

### 5.3 Gate network
- Add a series gate resistor and a local gate-source clamp. The clamp stops the error amplifier from overdriving $V_{GS}$ during a short.
- A **gate pull-down / hold-off** device keeps the pass element off during reset and faults (§9.3).

---

## 6. CV/CC control loops & stability

- **Architecture.** Separate CV and CC error amplifiers, diode-ORed (or minimum-selected) onto the gate drive. Whichever loop asks for less output wins. Watch the hand-over: the losing amplifier saturates, and its recovery time limits how fast the supply can switch from CC back to CV.
- **Measure loop gain properly.** Break the loop at the gate-drive node and use a method that accounts for loading, such as the Tian or Middlebrook method in simulation. Sweep the corners:
  - load from no load to full current;
  - output capacitance from none to the largest the spec allows;
  - temperature;
  - component tolerances.
- **Targets.** Phase margin ≥ 45° at the worst corner (60° typical) and gain margin ≥ 10 dB. CC loops through a high-gain sense amplifier are usually the harder ones.
- **Output capacitance.** It interacts with the pass element's output impedance. Many supplies are stable only with a minimum or maximum load capacitance, so state it in the spec.
- **Down-programming.** A source follower can only source current. With no load, the output falls only as fast as a bleeder (or an active sink) discharges the output capacitance. Size the bleeder current against the down-step time spec and its own dissipation at $V_{out}$.
- **Setpoint DAC.** Check:
  - the DAC reference's accuracy and drift against the spec;
  - the setpoint divider's ratio tolerance (0.1 % or better for voltage);
  - the DAC's output state in reset.
- **Sense point.** Sense the output where the user connects: at the terminal, or with remote sense leads. Otherwise, the drop across the output switch, relay and shunt is unregulated.

---

## 7. Current measurement & auto-ranging

### 7.1 Shunt and amplifier per range
- **Burden voltage** $I_{FS} \cdot R_{sh}$. It is typically tens of mV. It adds to the headroom and appears as an output error unless it sits inside the CV loop.
- **Shunt power and pulse rating.** $I^2 R$ must hold at full scale, and at the *fault* current until the range switches up (§7.2). High-value shunts must survive the energy of a range-up event.
- **Amplifier error budget.** Include:
  - input offset, referred as $V_{os}/R_{sh}$;
  - gain error;
  - CMRR at the shunt's common-mode voltage (a high-side shunt sits at up to $V_{out}$);
  - **input bias current**, which flows through the shunt and dominates on high-ohm ranges, so pick pA–nA amplifiers.
- **Kelvin sensing.** Take separate sense traces from the inner edge of each shunt pad, with no load current in them (§12).

### 7.2 Range switching
- **Bypass switches.** FETs across the higher-value shunts. Check:
  - $R_{DS(on)}$, which adds to the lower range's shunt;
  - **leakage** when off, which is an error on the µA range;
  - $C_{oss}$, which affects transient behaviour.
- **Clamp diodes** across each high-value shunt cap the burden voltage while the range switches up. Without them, a load step on the µA range puts the full current through a 100 Ω-class shunt. Diode leakage is an error on the lowest range.
- **Range-up must be hardware-fast.** Use comparators that trigger a switch directly, through timers or logic, without waiting for firmware. Measure the latency and keep the load's voltage dip within spec. Range-down can be slower and is done by firmware, with hysteresis.
- **Floating gate drive.** When the shunts sit in the output path, the bypass FETs' sources move with the output. Their gate drive must be referenced to that node: an isolated DC/DC, a digital isolator and a gate driver form a small "island" (§10).
- **Make-before-break.** Never open a range path before the next one is closed, or the output drops out.

### 7.3 ADC chain
- Add an anti-alias RC at each amplifier output, sized to the ADC sample rate and the amplifier's output drive.
- Use one ADC reference, buffered, and decouple it at the pin.
- Synchronize sampling with the range state, and discard samples taken during a range transition.

---

## 8. Output path: pass-through, relay, output switch

- **Pass-through path** (current measured, voltage not regulated):
  - size the shunt for $I_{pt}^2 R$;
  - choose a sense amplifier whose common-mode range covers $V_{in}$;
  - route its copper for $I_{pt}$ (§11, §12).
- **Mode relay:**
  - check contact current, carry and switching ratings at **DC** voltage (DC breaking is much harder than AC);
  - put a flyback diode on the coil;
  - define the coil's default state (de-energised = precision path is the usual safe choice);
  - switch the relay only with the output off.
- **Output switch.** Two N-FETs back-to-back (common source) block both directions. A single FET's body diode would conduct from an external source, such as a battery under test, back into the supply.
  - A photovoltaic or isolated driver gives a floating $V_{GS}$ without a charge pump.
  - Check turn-off time: photovoltaic drivers can be slow without an active turn-off.
- **Reverse current from the load.** A battery or charged capacitor on the output can back-feed the supply. Check what the pass element, the clamp diodes and the bleeder see when the output is driven from outside.

---

## 9. Protection & safe state

### 9.1 Overcurrent
- Use three layers:
  1. the analog CC loop (fast, continuous);
  2. a **hardware trip**: comparator → timer break / latch → gate off, acting within µs;
  3. firmware limits and the fuse as a backstop.
- The hardware trip must work with the MCU's firmware in any state, and stay armed by default.
- Simulate a **dead short**. Report the peak current and its duration with and without the hardware trip, and check them against the pass element's single-pulse SOA and the shunt pulse rating.

### 9.2 Over-temperature
- Put an NTC at the hottest point: the pass-element heatsink or tab, plus the board. Firmware folds back the current limit or shuts down. Ideally a hardware comparator does it too.

### 9.3 Safe state
- With the MCU in reset or brown-out, the supply must end up with:
  - the pass-element gate held low;
  - the output switch open;
  - the relay in its default position;
  - range FETs giving a *defined* range;
  - DAC outputs and the pre-regulator setpoint at safe levels.
- Verify every enable and setpoint net's pull-up or pull-down against that list.

### 9.4 Overvoltage
- A fault in the pass element (drain-source short) puts $V_{PRE}$ on the output. Consider an OVP comparator that drops the pre-regulator to minimum and opens the output switch.

---

## 10. Isolation

- **Host isolation.** Isolate USB (data and power) between the PC and the power ground. This breaks ground loops through the DUT and the PC, and protects the PC.
  - A data isolator plus an isolated or host-side supply defines two ground domains.
  - Choose ESD protection on the connector side.
- **Floating islands** (range gate drive, §7.2) are a second domain referenced to the output node.
- **Clearance and creepage.** Size gaps to the working voltage between domains, at least $V_{in}$, using IPC-2221 (external, uncoated):
  - 0.1 mm up to 30 V;
  - 0.6 mm for 31–100 V.
  
  For a nominal isolation rating, follow the isolator's datasheet creepage and the relevant safety standard. **1 mm or more is good practice even for functional isolation.**
- **No copper crosses a gap** on *any* layer, including inner planes and outer pours. Only the isolator, the isolated DC/DC and any intended Y-cap straddle it. Mark the gaps on silkscreen.
- Each domain has its own reference plane. A signal routed over the other domain's plane loses its return path.

---

## 11. Thermal design

- **Pass element.** $T_J = T_A + P \cdot (R_{\theta JC} + R_{\theta CS} + R_{\theta SA})$ at worst-case continuous $P$ (§5.2). Mount the part at the board edge on a heatsink with an insulating pad if the tab is live. Verify the heatsink's $R_{\theta SA}$, or specify the fan.
- **Shunts.** $I^2 R$ at full scale, derated with temperature. Give shunt pads generous copper. Note that copper heating adds to the shunt's tempco error.
- **Copper for high current.** IPC-2221 gives these external 1 oz (35 µm) widths for 10 A:

  | Temperature rise | Width |
  |---|---|
  | 10 °C | ≈ 7 mm |
  | 20 °C | ≈ 4.7 mm |

  Inner layers need about 2.5× that for the same rise. Parallel layers share current, so stitch them with via arrays. IPC-2152 gives more realistic (less conservative) numbers when planes are nearby. **Specify the inner copper weight** to the fab: many default to 0.5 oz inner.
- **Vias.** A 0.3 mm plated via carries about 1–1.5 A continuous. Use arrays for power transitions and thermal pads.

---

## 12. PCB layout

The priority order:

1. **High-current copper first.**
   - Use pours, not tracks, for the $I_{pt}$ and $I_p$ paths.
   - Duplicate them on several layers and stitch them with via arrays.
   - Keep the path short from the input terminal through the fuse, shunt, relay and switch to the output terminal.
2. **Kelvin sense.**
   - Sense traces leave the **inner edge** of each shunt pad and run as a tight pair to the amplifier.
   - No load current flows in them, and they never share copper with the pour.
   - Use 4-terminal shunts where available.
3. **Pre-regulator hot loop.**
   - Use the vendor's recommended layout.
   - Place the input caps at the pins.
   - Keep the switch node minimal.
   - Place the feedback divider at the FB pin, away from the switch node.
4. **Analog ground and references.**
   - Use one continuous ground plane under the analog section.
   - Keep the buck's return currents and the high-current loop out of it.
   - Decouple references and ADC/DAC pins at the pins.
5. **Isolation gaps** on every layer (§10).
6. **Thermal.**
   - Place the pass element at the edge for the heatsink.
   - Give shunts and FETs copper and vias.
   - Keep temperature-sensitive references and dividers away from hot parts.
7. **Fine-pitch escapes.** Leave routing room around QFN/QFP parts. Tie exposed pads to their net with vias, following the vendor's via pattern.
8. **Test points** on rails, setpoints, the gate drive and range-control signals, for bring-up.

---

## 13. KiCad workflow: tips & tricks

- **Net classes.** Give High-current, Power, Default and USB their own width and clearance, and assign them by pattern. Zones carry the current; tracks only connect.
- **Zones.**
  - Set priorities explicitly where pours of different nets meet.
  - Use thermal reliefs for hand-soldered THT pins on pours, and solid connections for SMD power pads and thermal vias.
  - Refill all zones before DRC and before plotting.
- **ERC.**
  - Place `PWR_FLAG` on every rail driven from outside the schematic (connector inputs, outputs of isolated converters).
  - Keep sense nets distinct; never merge a Kelvin net into a power net by label.
  - Use the no-connect flag only where it is intended.
- **DRC.**
  - Run with **schematic parity**.
  - Match the rules to the fab's standard tier: track/space, via drill and annular ring, hole-to-hole, copper to edge.
  - Know the single tightest rule that sets the price tier.
- **Fab outputs.**
  - Set the drill/aux origin.
  - Generate the CPL relative to it.
  - Put LCSC part numbers in a symbol field.
  - Check JLC's placement preview for rotations.
  - Note the THT parts.

---

## 14. Design-review checklist

A condensed go/no-go list. The reviewer agent expands on it.

**Spec & devices**
- [ ] Every part on the input rail survives the TVS **clamp** voltage; TVS standoff ≥ $V_{in}$ max.
- [ ] Pass element: **DC SOA at the real case temperature** for $V_{hr} \cdot I_p$ continuous, and single-pulse SOA for $V_{PRE} \cdot I_{limit}$ during a short. Planar or linear-mode-rated part.
- [ ] Error-amplifier supply ≥ $V_{out}$ + $V_{GS}$ + swing margin; behaviour near 0 V / 0 A defined.
- [ ] **Footprint matches the real package land**, especially QFN/WQFN regulators, SO-8FL FETs and relays.
- [ ] Shunt power and pulse ratings; amplifier offset, bias current and CMRR inside the per-range error budget.
- [ ] Relay DC contact rating; fuse voltage, breaking capacity and temperature derating.

**Loops & ranging**
- [ ] CV and CC phase margin ≥ 45° at the worst corner (load, $C_{out}$, temperature, tolerance); simulation evidence attached.
- [ ] Pre-regulator setpoint end points clamped; reset state safe.
- [ ] Hardware range-up latency measured or simulated; burden clamped while switching; range FET leakage inside the µA error budget.
- [ ] Down-programming time and bleeder dissipation within spec.

**Protection & isolation**
- [ ] Hardware OCP trip, armed by default, independent of firmware; dead-short peak inside SOA.
- [ ] Safe state at reset and brown-out: gate low, output switch open, relay default, setpoints safe.
- [ ] Back-feed from an external source on the output considered.
- [ ] Isolation gaps ≥ the spec on **all** layers; nothing crosses except the isolators and DC/DCs.

**Layout**
- [ ] High-current pours sized (IPC-2152/2221) with **inner copper weight specified**; via arrays at layer changes.
- [ ] Kelvin taps from the inner pad edges; sense pairs routed together, away from the switch node.
- [ ] Buck hot loop as in the vendor layout; FB divider at the pin.
- [ ] Pass element at the edge on a heatsink; NTC at the hot spot.

**Manufacturing (KiCad/fab)**
- [ ] ERC clean (PWR_FLAGs placed, no merged sense nets).
- [ ] DRC clean with schematic parity; rules inside the fab's standard tier.
- [ ] Zones refilled; no islands or slivers; mask webs OK.
- [ ] Drill/aux origin set; CPL board-relative; BOM has LCSC numbers; Gerbers complete (all copper layers, mask, paste, silk, edge, PTH/NPTH drill).

---

## 15. References

Verify every rating against the live datasheet or app note. The numbers here are for orientation and may change.

**Functional blocks.** This guide is component-agnostic: pick parts that meet each block's interface. A board's README lists its concrete choices.
- **Input protection:** TVS, reverse-polarity P-FET with gate clamp, fuses per path.
- **Pre-regulator:** synchronous buck rated above $V_{in}$ with margin, with an externally adjustable setpoint.
- **Pass element:** MOSFET with a usable DC SOA (planar or linear-mode rated), heatsinkable package.
- **Error amplifiers:** precision op-amps with an output swing covering the gate drive.
- **Current sense:** current-sense amplifiers with the right common-mode range, low offset, and low bias for high-ohm ranges.
- **Range switches:** low-leakage FETs; isolated DC/DC, digital isolator and gate driver for the floating island.
- **Output switch:** back-to-back FETs with a photovoltaic or isolated driver; DC-rated relay for mode selection.
- **Host isolation:** USB isolator plus ESD protection.

**Standards & app notes**
- **IPC-2152:** conductor current-carrying capacity.
- **IPC-2221:** generic PCB design, conductor spacing (Table 6-1), current capacity.
- **MOSFETs in linear mode:** vendor app notes on the Spirito effect and DC SOA, from Infineon, Nexperia and IXYS (linear MOSFETs).
- **Loop-gain measurement:** M. Tian, V. Visvanathan, J. Hantgan, K. Kundert, "Striving for Small-Signal Stability", IEEE Circuits and Devices Magazine 17(1), 2001 (Tian method); R. D. Middlebrook, "Measurement of Loop Gain in Feedback Systems", Int. J. Electronics 38(4), 1975 (double injection).
- **Layout:** the pre-regulator's datasheet layout section, and the current-sense amplifier's Kelvin layout guidance.
- **JLCPCB capabilities** (jlcpcb.com/capabilities): check the current numbers; they change over time.
