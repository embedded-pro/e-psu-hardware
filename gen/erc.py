"""Our own electrical-rules check on the generator's connectivity model (KiCad 7 CLI has no ERC).

Rules mirror KiCad's main ERC classes:
  - every pin is connected or explicitly no-connect flagged (pins of type no_connect excepted)
  - a net containing power-input pins (incl. power symbols) has a power-output pin or PWR_FLAG
  - no two output / power-output pins on one net
  - a net containing input pins has some driver (output, bidirectional, tri_state, passive, power_out, open_*)
  - nets with a single pin (dangling) are reported
  - duplicate references
And a footprint check: every symbol pin number exists as a pad in the assigned footprint and vice versa.
"""
import os
import re
from sexp import parse, findall, find

FP_DIRS = ["/usr/share/kicad/footprints"]
DRIVERS = {"output", "bidirectional", "tri_state", "passive", "power_out", "open_collector", "open_emitter",
           "unspecified"}


def run(project):
    errs, warns = [], []
    refs = {}
    nets = {}
    pinnet = {}
    for sh in project.sheets:
        for p in sh.parts:
            if p.ref in refs and (refs[p.ref].lib_id != p.lib_id or refs[p.ref].unit == p.unit):
                errs.append(f"duplicate reference {p.ref}")
            refs[p.ref] = p
        for pr, n, _ in sh.conns:
            key = n if (n in project.global_nets or n in ("GND", "+3V3", "+5V", "+3.3VA", "+5VA")) else f"/{sh.name}/{n}"
            nets.setdefault(key, []).append((pr.part, pr.number, pr.info["type"]))
            pinnet.setdefault((pr.part.ref, pr.number), set()).add(key)
        ncset = {(pr.part.ref, pr.number) for pr in sh.ncs}
        for p in sh.parts:
            for q in p.unit_pins():
                k = (p.ref, q["number"])
                if k not in pinnet and k not in ncset and q["type"] != "no_connect":
                    # stacked pins at same position count as connected if a sibling is connected
                    errs.append(f"unconnected pin {p.ref}.{q['number']} ({q['name']}) on sheet {sh.name}")
                if k in ncset and k in pinnet:
                    errs.append(f"pin {p.ref}.{q['number']} both no-connect and connected")
    for k, v in pinnet.items():
        if len(v) > 1:
            errs.append(f"pin {k} on several nets: {sorted(v)}")
    flags = set(getattr(project, "pwr_flags", set()))
    for n, members in nets.items():
        types = [t for _, _, t in members]
        uniq = {(p.ref, num) for p, num, _ in members}
        is_power_sym = n in ("GND", "+3V3", "+5V", "+3.3VA", "+5VA")
        if len(uniq) == 1 and not is_power_sym:
            warns.append(f"net {n} has a single pin {list(uniq)[0]}")
        has_pin = "power_in" in types or is_power_sym
        if has_pin and "power_out" not in types and n not in flags and n.split("/")[-1] not in flags:
            errs.append(f"net {n}: power input not driven (add PWR_FLAG or a power-output pin)")
        outs = sorted({p.ref for p, num, t in members if t in ("output", "power_out")})
        if len(outs) > 1:
            errs.append(f"net {n}: several outputs {outs}")
        if "input" in types and not any(t in DRIVERS for t in types) and not is_power_sym:
            errs.append(f"net {n}: inputs not driven {[(p.ref, num) for p, num, t in members]}")
    return errs, warns


def footprint_pads(fp):
    if not fp or ":" not in fp:
        return None
    lib, name = fp.split(":", 1)
    for d in FP_DIRS:
        path = os.path.join(d, lib + ".pretty", name + ".kicad_mod")
        if os.path.exists(path):
            t = parse(open(path, encoding="utf-8").read())
            return {str(x[1]) for x in findall(t, "pad") if str(x[1]) != ""}
    return "missing"


def check_footprints(project):
    out = []
    for sh in project.sheets:
        for p in sh.parts:
            fp = p.fields.get("Footprint", "")
            if p.ref.startswith("#"):
                continue
            if not fp:
                out.append(f"{p.ref}: no footprint")
                continue
            pads = footprint_pads(fp)
            if pads == "missing":
                out.append(f"{p.ref}: footprint {fp} not in KiCad library (custom / to import)")
                continue
            pinnums = {q["number"] for q in p.allpins}
            miss = pinnums - pads
            extra = pads - pinnums
            if miss or extra:
                out.append(f"{p.ref} {p.value} [{fp}]: pins without pad {sorted(miss)}, pads without pin {sorted(extra)}")
    return out
