"""Signal routing with Freerouting 2.1 (KiCad 10).

    kicad10-python autoroute.py export board.kicad_pcb out.dsn      # DSN with 45-degree snapping
    python3 autoroute.py run out.dsn out.ses MINUTES                 # Freerouting, headless
    kicad10-python autoroute.py import board.kicad_pcb out.ses       # SES back into the board
"""
import os
import re
import subprocess
import sys
import time

JAR = os.environ.get("FREEROUTING_JAR", "/home/claude/e-psu-hw/tools/freerouting.jar")


def export(board_path, dsn):
    from kc import pcbnew
    b = pcbnew.LoadBoard(board_path)
    assert pcbnew.ExportSpecctraDSN(b, dsn)
    t = open(dsn).read()
    # 45-degree traces only; Freerouting's pull-tight keeps to the snap angle
    if "snap_angle" not in t:
        t = re.sub(r"(\(structure\s*\n)", r"\1    (snap_angle fortyfive_degree)\n", t, count=1)
    open(dsn, "w").write(t)


def run(dsn, ses, minutes):
    cmd = ["java", "-Xmx4g", "-jar", JAR, "-de", dsn, "-do", ses, "--gui.enabled=false",
           f"--router.job_timeout=00:{int(minutes):02d}:00", "--router.optimizer.max_passes=0",
           "--router.scoring.via_costs=40", "--router.scoring.plane_via_costs=5",
           "--router.scoring.start_ripup_costs=100", "--usage_and_diagnostic_data.disable_analytics=true"]
    if os.path.exists(ses):
        os.remove(ses)
    t0 = time.time()
    with open(ses + ".log", "w") as lf:
        p = subprocess.run(cmd, stdout=lf, stderr=subprocess.STDOUT, timeout=int(minutes) * 60 + 900)
    print("freerouting exit", p.returncode, "after", round(time.time() - t0), "s; ses", os.path.exists(ses))


def import_ses(board_path, ses):
    from kc import pcbnew
    b = pcbnew.LoadBoard(board_path)
    assert pcbnew.ImportSpecctraSES(b, ses)
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    pcbnew.SaveBoard(board_path, b)
    print("imported", ses)


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "export":
        export(sys.argv[2], sys.argv[3])
    elif cmd == "run":
        run(sys.argv[2], sys.argv[3], sys.argv[4])
    elif cmd == "import":
        import_ses(sys.argv[2], sys.argv[3])
