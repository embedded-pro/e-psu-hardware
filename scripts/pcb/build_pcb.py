"""Build hardware/e-psu/e-psu.kicad_pcb from the schematic netlist (exported with kicad-cli)."""
import json
import os
import subprocess
import sys

import pcbnew

import fputil
import netlist
import place

HERE = os.path.dirname(os.path.abspath(__file__))
KDIR = os.path.join(HERE, "..", "..", "hardware", "e-psu")
OUT = os.path.join(KDIR, "e-psu.kicad_pcb")
WORK = os.path.join(HERE, "work")


def export_netlist():
    """Export the schematic netlist into work/, so the board is always built from the current schematic."""
    os.makedirs(WORK, exist_ok=True)
    net = os.path.join(WORK, "e-psu.net")
    subprocess.run(["kicad-cli", "sch", "export", "netlist", "--format", "kicadsexpr", "-o", net,
                    os.path.join(KDIR, "e-psu.kicad_sch")], check=True, capture_output=True)
    return net


def build(stage="place"):
    comps, nets = netlist.load(export_netlist())
    board = pcbnew.BOARD()
    board.SetCopperLayerCount(4)
    ds = board.GetDesignSettings()
    ds.SetCopperLayerCount(4)
    # nets
    netinfo = {}
    for name in sorted(nets):
        ni = pcbnew.NETINFO_ITEM(board, name)
        board.Add(ni)
        netinfo[name] = ni
    pad_net = {(r, p): n for n, nodes in nets.items() for r, p in nodes}
    fps = {}
    for ref, c in sorted(comps.items()):
        fp = fputil.load(c["footprint"])
        fp.SetReference(ref)
        fp.SetValue(c["value"])
        fp.SetFPIDAsString(c["footprint"])
        fp.SetPath(pcbnew.KIID_PATH(c["sheet_ts"] + c["ts"]))
        if c["dnp"]:
            fp.SetAttributes(fp.GetAttributes() | pcbnew.FP_EXCLUDE_FROM_BOM | pcbnew.FP_EXCLUDE_FROM_POS_FILES)
        board.Add(fp)
        fp.SetLocalClearance(0)            # use the net-class rules everywhere
        for p in fp.Pads():
            p.SetLocalClearance(0)
            p.SetZoneConnection(pcbnew.ZONE_CONNECTION_INHERITED)   # SO-8FL drain pads ship with "no zone connection"
            n = pad_net.get((ref, p.GetNumber()))
            if n:
                p.SetNet(netinfo[n])
        fps[ref] = fp
    placed, unplaced = place.run(board, fps, comps, nets)
    # board outline
    edge = pcbnew.PCB_SHAPE(board)
    edge.SetShape(pcbnew.SHAPE_T_RECT)
    edge.SetStart(place.to_abs(0, 0)); edge.SetEnd(place.to_abs(place.BW, place.BH))
    edge.SetLayer(pcbnew.Edge_Cuts); edge.SetWidth(pcbnew.FromMM(0.1))
    board.Add(edge)
    pcbnew.SaveBoard(OUT, board)
    json.dump({r: list(v) for r, v in placed.items()}, open(os.path.join(WORK, "placed.json"), "w"))
    return board, fps, placed, unplaced


if __name__ == "__main__":
    b, fps, placed, unplaced = build()
    print("placed", len(placed), "unplaced", unplaced)
