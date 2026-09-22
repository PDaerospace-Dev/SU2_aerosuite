"""Test stand-in for a text editor.

Each run pops the next action from the JSON list in the file named by $FAKE_EDITOR_PLAN
and applies it to the file given as argv[1].
"""
import json
import os
import sys
from pathlib import Path

plan_path = Path(os.environ["FAKE_EDITOR_PLAN"])
actions = json.loads(plan_path.read_text())
action = actions.pop(0)
plan_path.write_text(json.dumps(actions))
target = Path(sys.argv[1])

if action == "noop":
    pass
elif action == "break":
    target.write_text("{not json")
elif action == "latin1":
    data = json.loads(target.read_text())
    data["name"] = "caf\xe9"
    target.write_bytes(json.dumps(data, ensure_ascii=False).encode("latin-1"))
else:
    data = json.loads(target.read_text())
    kind, _, value = action.partition(":")
    if kind == "rename":
        data["name"] = value
    elif kind == "alpha":
        data["sweep"]["alpha"] = [float(v) for v in value.split(",")]
    elif kind == "partitions":
        data["run"]["partitions"] = int(value)
    else:
        raise SystemExit(f"unknown action {action!r}")
    target.write_text(json.dumps(data))
