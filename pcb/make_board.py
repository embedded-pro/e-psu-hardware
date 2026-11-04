"""End-to-end board build:  placement -> power copper -> Freerouting -> fills/stitching/silk -> DRC.

    python3 make_board.py            # full run (routing takes several minutes)
    python3 make_board.py --reuse    # skip Freerouting, re-import work/route.ses
    python3 make_board.py --own      # no Freerouting: the grid router (finisher.py) routes everything
    python3 make_board.py --resume   # continue the router rounds from work/best.kicad_pcb
"""
import os
import shutil
import sys

import pcbnew

import build_pcb
import place
import copper
import drc
import fanout
import finish
import finisher
import route

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(HERE, "work")
PCB = build_pcb.OUT


def main(reuse=False, minutes=15, router="freerouting", rounds=8):
    os.makedirs(WORK, exist_ok=True)
    board, fps, placed, unplaced = build_pcb.build()
    assert not unplaced, unplaced
    board = pcbnew.LoadBoard(PCB)
    final = copper.apply(board)
    fanout.escapes(board, final)
    fanout.run(board, final)
    pcbnew.SaveBoard(PCB, board)
    dsn, ses = os.path.join(WORK, "route.dsn"), os.path.join(WORK, "route.ses")
    route.export_dsn(board, dsn)
    if router == "freerouting":
        if not reuse or not os.path.exists(ses):
            rc, dt = route.run_freerouting(dsn, ses, minutes=minutes, log=os.path.join(WORK, "freerouting.log"))
            print(f"freerouting exit {rc} after {dt:.0f} s", flush=True)
        route.import_ses(board, ses)
    finish.cleanup(board)
    board = route_rounds(board, rounds, rip_from=1)
    finalize(board)


def route_rounds(board, rounds, rip_from=1):
    """Grid-router rounds driven by KiCad's DRC; keeps the board state with the fewest open connections."""
    best = None
    for rnd in range(rounds):
        tmp = os.path.join(WORK, "tmp.kicad_pcb")
        pcbnew.SaveBoard(tmp, board)
        shutil.copy(os.path.join(os.path.dirname(PCB), "e-psu.kicad_pro"), os.path.join(WORK, "tmp.kicad_pro"))
        sec, _ = drc.run(tmp, os.path.join(WORK, "drc_pre.txt"), fill=False)
        open_ = sec.get("unconnected pads", 0)
        print("before finisher round", rnd + 1, "open:", open_, flush=True)
        if best is None or open_ < best:
            best = open_
            shutil.copy(tmp, os.path.join(WORK, "best.kicad_pcb"))
        if not open_:
            break
        # ripped traces leave stubs on both sides; the next round only has to bridge the gap,
        # so dangling stubs are kept until routing is complete
        finisher.finish(board, os.path.join(WORK, "drc_pre.txt"), allow_rip=rnd >= rip_from)
        pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    print("best round left", best, "open", flush=True)
    board = pcbnew.LoadBoard(os.path.join(WORK, "best.kicad_pcb"))
    finish.cleanup(board)
    return board


def finalize(board):
    finish.apply(board)
    board = polish(board)
    pcbnew.SaveBoard(PCB, board)
    copper.write_project()
    final_drc()


def tidy(board, report):
    """Solid ground-fill connections, and rip the autorouted tracks named in DRC clearance errors."""
    import re
    from shapely.geometry import Point
    import finisher as F
    for z in board.Zones():
        if z.GetAssignedPriority() == 0:
            z.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
    txt = open(report).read().split("\n")
    kill = {}
    for i, l in enumerate(txt):
        if l.startswith(("[clearance]", "[hole_clearance]", "[shorting_items]", "[tracks_crossing]")):
            for l2 in txt[i + 2:i + 4]:
                mm = re.search(r"@\(([\d.]+) mm, ([\d.]+) mm\): Track \[([^\]]+)\]", l2)
                if mm:
                    p = Point(float(mm.group(1)) - place.BX0, float(mm.group(2)) - place.BY0)
                    for t in board.GetTracks():
                        if not t.IsLocked() and not isinstance(t, pcbnew.PCB_VIA) and t.GetNetname().replace("{slash}", "/") == mm.group(3) \
                                and F.track_geom(t).distance(p) < 0.05:
                            kill[t.m_Uuid.AsString()] = t
    for t in kill.values():
        board.Delete(t)
    print(f"tidy: removed {len(kill)} tracks with clearance errors", flush=True)


def polish(board, attempts=4):
    """Removing dangling stubs can reopen a connection; route and clean until both are stable."""
    for _ in range(attempts):
        finish.cleanup(board)          # drop dead-end fragments first, so they are never chosen as targets
        tmp = os.path.join(WORK, "tmp.kicad_pcb")
        pcbnew.SaveBoard(tmp, board)
        shutil.copy(os.path.join(os.path.dirname(PCB), "e-psu.kicad_pro"), os.path.join(WORK, "tmp.kicad_pro"))
        sec, _ = drc.run(tmp, os.path.join(WORK, "drc_pre.txt"), fill=True)
        open_ = sec.get("unconnected pads", 0)
        print("polish: open", open_, flush=True)
        if not open_:
            break
        finisher.finish(board, os.path.join(WORK, "drc_pre.txt"), allow_rip=True)
    return board


def final_drc():
    """DRC in a fresh process: KiCad keeps a project in memory once loaded, so a board saved earlier in this
    process would be checked against stale net classes."""
    import subprocess
    r = subprocess.run([sys.executable, os.path.join(HERE, "drc.py"), PCB, os.path.join(WORK, "drc.txt"), "--nofill"],
                       capture_output=True, text=True)
    print("\n".join(l for l in r.stdout.splitlines() if "leak" not in l))

if __name__ == "__main__":
    if "--tidy" in sys.argv:            # fix what the last DRC found, then polish
        b = pcbnew.LoadBoard(PCB)
        tidy(b, os.path.join(WORK, "drc.txt"))
        b = polish(b, attempts=6)
        finish.trim_stubs(b)
        pcbnew.ZONE_FILLER(b).Fill(b.Zones())
        pcbnew.SaveBoard(PCB, b)
        copper.write_project()
        final_drc()
        sys.exit()
    if "--polish" in sys.argv:          # reconnect and clean the finished board in kicad/
        b = polish(pcbnew.LoadBoard(PCB))
        pcbnew.ZONE_FILLER(b).Fill(b.Zones())
        pcbnew.SaveBoard(PCB, b)
        copper.write_project()
        final_drc()
        sys.exit()
    if "--resume" in sys.argv:          # continue the router rounds from work/best.kicad_pcb
        b = pcbnew.LoadBoard(os.path.join(WORK, "best.kicad_pcb"))
        finalize(route_rounds(b, 8, rip_from=0))
        sys.exit()
    main(reuse="--reuse" in sys.argv, router="own" if "--own" in sys.argv else "freerouting",
         rounds=16 if "--own" in sys.argv else 8)
