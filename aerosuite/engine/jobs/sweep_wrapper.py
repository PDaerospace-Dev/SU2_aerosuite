"""Runs the sweep script and records its exit code, so a detached job's outcome survives a server restart.

Usage: python -I sweep_wrapper.py <exit file> <sweep command...>

Started by LocalRunner under AeroSuite's own Python; the sweep command runs under the sweep's Python (which
must import SU2) with this process's stdin, stdout and environment. Standard library only. When this
process is killed (Cancel, or from outside) no exit file is written.
"""
import os
import subprocess
import sys


def main(argv: list) -> int:
    exit_file, command = argv[1], argv[2:]
    try:
        code = subprocess.call(command)
    except OSError as exc:
        print(f"Cannot start the sweep script ({' '.join(command)}): {exc}", flush=True)
        code = 127
    tmp = exit_file + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(str(code))
    os.replace(tmp, exit_file)
    return 0 if code == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
