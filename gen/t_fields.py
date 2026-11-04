import os
from sch import Project, Sheet
D="/tmp/claude-0/-home-claude/1343fb3e-9000-5805-86c8-032e2c5e8cd4/scratchpad/tf"
P=Project("tf"); sh=Sheet(P,"t","t.kicad_sch","fields")
r1=sh.part("Device:R","R1","AAAA",(50,50),rot=90); sh.net(r1[1],"A"); sh.net(r1[2],"B")
r2=sh.part("Device:R","R2","BBBB",(100,50),rot=0); sh.net(r2[1],"A"); sh.net(r2[2],"B")
P.build(D,"t")
# patch R1 field angles to 90
s=open(D+"/t.kicad_sch").read()
import re
s=s.replace('(property "Value" "AAAA" (at','(property "Value" "AAAA" (atX',1)
open(D+"/t.kicad_sch","w").write(s)
