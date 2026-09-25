"""Test stand-in for aoa_sweep_v8.py: same CLI, banners and output layout, no SU2.

Per-case behaviour comes from <cfg_dir>/fake_plan.json:
    {"delay": 0.05, "cases": {"<case name>": "converge" | "diverge" | "fail" | "hang" | "exit"}}
Cases not listed converge. "exit" ends the whole script (exit code 1) right after that case's banner.

Each case folder gets restart_used.txt (its run_control.txt line) and restart_applied.txt: "yes" when
the line asks for a restart (previous / from_case / custom) and the case cfg has RESTART_SOL= YES,
else "no" -- like aoa_sweep_v8.py, which ignores the restart file unless RESTART_SOL is YES.
"""
import argparse
import json
import math
import re
import shutil
import sys
import time
from pathlib import Path


def write_history(folder: Path, diverge: bool) -> None:
    lines = ['"Inner_Iter",   "rms[Rho]",   "CL",   "CD",   "CMy"']
    for i in range(50):
        cl = 0.5 + (0.2 * math.sin(i) if diverge else 0.0)
        lines.append(f"{i:8d}, {-2 - 0.1 * i:12.6f}, {cl:12.8f}, {0.02:12.8f}, {-0.1:12.8f}")
    (folder / "history.csv").write_text("\n".join(lines) + "\n")


def restart_applied(line: str, cfg: Path) -> bool:
    fields = [field.strip() for field in line.split(",")]
    if len(fields) < 2 or fields[1] not in ("previous", "from_case", "custom"):
        return False
    text = cfg.read_text() if cfg.is_file() else ""
    match = re.search(r"^RESTART_SOL\s*=\s*(\S+)", text, re.MULTILINE)
    return bool(match) and match.group(1).upper() == "YES"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("-d", dest="cfg_dir", required=True)
    parser.add_argument("-c", dest="control_file", required=True)
    parser.add_argument("-n", dest="partitions", default="1")
    parser.add_argument("-r", dest="initial_restart", default=None)
    args = parser.parse_args()

    plan_path = Path(args.cfg_dir) / "fake_plan.json"
    if not plan_path.is_file():  # jobs run from jobs/<id>/configs; tests write the plan into configs/
        plan_path = Path.cwd().parent / "configs" / "fake_plan.json"
    plan = json.loads(plan_path.read_text()) if plan_path.is_file() else {}
    delay = float(plan.get("delay", 0.05))
    behaviour = plan.get("cases", {})
    lines = [
        line.strip()
        for line in Path(args.control_file).read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]
    cfgs = [line.split(",")[0].strip() for line in lines]

    if input("Proceed with this execution plan? (yes/no): ").strip().lower() not in ("yes", "y"):
        print("Execution cancelled by user.")
        return 0

    for i, (cfg, line) in enumerate(zip(cfgs, lines), 1):
        print(f"=== Running Case {i}/{len(cfgs)}: {cfg} ===")
        name = cfg[:-4]
        folder = Path(name)
        if folder.is_dir():
            shutil.rmtree(folder)
        folder.mkdir()
        source = Path(args.cfg_dir) / cfg
        if source.is_file():
            shutil.copy(source, folder)
        (folder / "restart_used.txt").write_text(line + "\n")
        (folder / "restart_applied.txt").write_text("yes\n" if restart_applied(line, source) else "no\n")
        mode = behaviour.get(name, "converge")
        if mode == "exit":
            sys.stdout.flush()
            sys.exit(1)
        if mode == "hang":
            while True:
                time.sleep(0.1)
        time.sleep(delay)
        if mode == "fail":
            (folder / "error.log").write_text(f"Failed to run {cfg}:\nboom\n")
            print(f"ERROR: Simulation for {cfg} failed: boom")
            continue
        write_history(folder, diverge=(mode == "diverge"))
        (folder / "restart_flow.dat").write_text(f"solution of {name}\n")
        print("--> Iterations completed: 50")
    return 0


if __name__ == "__main__":
    sys.exit(main())
