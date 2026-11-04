"""Run KiCad's DRC on a board file and summarise the report."""
import collections
import re
import sys

import os

import pcbnew

import copper


def run(path, report, fill=True):
    b = pcbnew.LoadBoard(path)
    if fill:
        pcbnew.ZONE_FILLER(b).Fill(b.Zones())
        pcbnew.SaveBoard(path, b)
    copper.write_project(pro=os.path.splitext(path)[0] + ".kicad_pro")
    b = pcbnew.LoadBoard(path)
    pcbnew.WriteDRCReport(b, report, pcbnew.EDA_UNITS_MILLIMETRES, True)
    return summarize(report)


def summarize(report):
    txt = open(report).read()
    sec = {}
    for m in re.finditer(r"\*\* Found (\d+) (.+?) \*\*", txt):
        sec[m.group(2)] = int(m.group(1))
    kinds = collections.Counter(re.findall(r"^\[(\w+)\]", txt, re.M))
    return sec, kinds


def items(report, kind):
    """Yield (headline, detail lines) for one violation kind."""
    txt = open(report).read().splitlines()
    for i, line in enumerate(txt):
        if line.startswith(f"[{kind}]"):
            det = []
            for l2 in txt[i + 1:i + 4]:
                if l2.startswith("    "):
                    det.append(l2.strip())
            yield line, det


if __name__ == "__main__":
    s, k = run(sys.argv[1], sys.argv[2], fill="--nofill" not in sys.argv)
    print(s)
    for kk, v in k.most_common():
        print(f"  {kk}: {v}")
