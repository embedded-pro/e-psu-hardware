import json, os
from sch import Project
P = Project("ttest")
s = P.sheets and None
from sch import Sheet
sh = Sheet(P, "t", "t.kicad_sch", "transform test")
for i, rot in enumerate((0, 90, 180, 270)):
    r = sh.part("Device:R", f"R{i+1}", "1k", (50 + i*25, 50), rot=rot)
    sh.net(r[1], f"A{rot}"); sh.net(r[2], f"B{rot}")
    u = sh.part("Regulator_Switching:LMR16006YQ", f"U{i+1}", "LMR16006", (50 + i*60, 120), rot=rot)
    for pn in "123456":
        sh.net(u[pn], "GND" if pn == "2" else f"U{rot}_{pn}")
    q = sh.part("Transistor_FET:AO3400A", f"Q{i+1}", "AO3400A", (50 + i*25, 180), rot=rot)
    sh.net(q[1], f"QG{rot}"); sh.net(q[3], "+3V3"); sh.net(q[2], "GND")
r5 = sh.part("Device:R", "R5", "1k", (50, 220)); r6 = sh.part("Device:R", "R6", "1k", (70, 225), rot=90)
sh.link(r5[2], r6[1], "LNK"); sh.net(r5[2], "LNK"); sh.net(r5[1], "L1"); sh.net(r6[2], "L2")
P.build("/tmp/claude-0/-home-claude/1343fb3e-9000-5805-86c8-032e2c5e8cd4/scratchpad/ttest", "test")
json.dump({k: sorted(v) for k, v in P.expected.items()}, open("/tmp/claude-0/-home-claude/1343fb3e-9000-5805-86c8-032e2c5e8cd4/scratchpad/ttest/exp.json", "w"))
