"""A stand-in for Slurm's sbatch, squeue, sinfo, scancel, sacct and seff, for tests.

Usage: python fake_slurm.py <command> <args...>   (the shims the `fake_slurm` fixture writes call it so)

The cluster lives in the JSON file named by $FAKE_SLURM_STATE; tests move jobs through their states by editing it
(see FakeSlurm in tests/conftest.py). Every call is appended to its "calls" list. Standard library only.
"""
import getpass
import json
import os
import re
import sys

CONTROLLER_DOWN = "slurm_load_jobs error: Unable to contact slurm controller (connect failure)"
ACCOUNTING_DOWN = "sacct: error: Problem talking to the database: Connection refused"


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def save(path, state):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=1)
    os.replace(tmp, path)


def fail(message, code=1):
    sys.stderr.write(message + "\n")
    return code


def directives(script_path):
    """The #SBATCH options of a job script: {"-p": "node1", "--dependency": "afterok:101", ...}."""
    found = {}
    with open(script_path, encoding="utf-8") as fh:
        for line in fh:
            match = re.match(r"#SBATCH\s+(\S+)(?:\s+(\S+))?", line)
            if not match:
                continue
            option, value = match.group(1), match.group(2)
            if "=" in option:
                option, value = option.split("=", 1)
            found[option] = value if value is not None else True
    return found


def sbatch(state, args):
    if state.get("controller_down"):
        return fail("sbatch: error: Batch job submission failed: Unable to contact slurm controller (connect failure)")
    if state.get("sbatch_fail_after") is not None and state["sbatch_count"] >= state["sbatch_fail_after"]:
        return fail("sbatch: error: Batch job submission failed: " + state.get("sbatch_message", "Invalid partition"))
    script = args[-1]
    options = directives(script)
    job_id = str(state["next_id"])
    state["next_id"] += 1
    state["sbatch_count"] += 1
    dependency = options.get("--dependency")
    state["jobs"][job_id] = {
        "name": options.get("-J", ""), "partition": options.get("-p", ""), "ntasks": options.get("-n", ""),
        "dependency": dependency, "cwd": os.getcwd(), "script": os.path.abspath(script),
        "env_virtual_env": os.environ.get("VIRTUAL_ENV"),
        "user": os.environ.get("FAKE_SLURM_USER") or getpass.getuser(),
        "state": "PENDING", "in_queue": True, "node": "", "time": "0:00",
        "reason": "Dependency" if dependency else "Priority",
        "exit_code": "0:0", "elapsed": "00:00:00", "accounted": True, "seff": None,
    }
    sys.stdout.write(job_id + state.get("sbatch_suffix", "") + "\n")
    return 0


def squeue(state, args):
    if state.get("controller_down"):
        return fail(CONTROLLER_DOWN)
    me = getpass.getuser()
    for job_id, job in sorted(state["jobs"].items(), key=lambda item: int(item[0])):
        user = job.get("user") or me
        if not job["in_queue"] or ("--me" in args and user != me):
            continue
        reason = job["node"] if job["state"] in ("RUNNING", "COMPLETING") else "(" + job["reason"] + ")"
        fields = [job_id, job["state"], job["node"], job["time"], reason, user, job.get("name", ""),
                  job.get("cwd", "") or "(null)"]
        sys.stdout.write("|".join(fields) + "\n")
    return 0


def sacct(state, args):
    if state.get("accounting_down"):
        return fail(ACCOUNTING_DOWN)
    if "-S" in args:  # the recent history: the user's ended, accounted jobs
        me = getpass.getuser()
        for job_id, job in sorted(state["jobs"].items(), key=lambda item: int(item[0])):
            if job["in_queue"] or not job.get("accounted", True) or (job.get("user") or me) != me:
                continue
            fields = [job_id, job.get("name", ""), job["state"], job["exit_code"], job["elapsed"], job["node"],
                      job.get("partition", ""), job.get("start", ""), job.get("end", ""), job.get("cwd", "")]
            sys.stdout.write("|".join(fields) + "\n")
        return 0
    ids = args[args.index("-j") + 1].split(",")
    for job_id in ids:
        job = state["jobs"].get(job_id)
        if job is None or not job.get("accounted", True):
            continue
        rows = [[job_id, job["state"], job["exit_code"], job["elapsed"], "", job["node"]]]
        if "-X" not in args:
            rows.append([job_id + ".batch", job["state"], job["exit_code"], job["elapsed"], "22960K", job["node"]])
        for row in rows:
            sys.stdout.write("|".join(row) + "\n")
    return 0


def scancel(state, args):
    if state.get("controller_down"):
        return fail("scancel: error: Kill job error on job id: Unable to contact slurm controller (connect failure)")
    for job_id in args:
        job = state["jobs"].get(job_id)
        if job is None:
            sys.stderr.write(f"scancel: error: Kill job error on job id {job_id}: Invalid job id specified\n")
            continue
        if job["in_queue"]:
            job.update(state="CANCELLED", in_queue=False, exit_code="0:15")
    return 0


def sinfo(state, args):
    if state.get("controller_down"):
        return fail("slurm_load_partitions: Unable to contact slurm controller (connect failure)")
    if "-N" in args:
        lines = state.get("nodes", [])
    else:
        lines = state["reasons"] if "-R" in args else state["partitions"]
    for line in lines:
        sys.stdout.write(line + "\n")
    return 0


def seff(state, args):
    if state.get("accounting_down"):
        return fail(ACCOUNTING_DOWN)
    job = state["jobs"].get(args[0])
    if job is None or job.get("seff") is None:
        return fail("Job not found.")
    sys.stdout.write(job["seff"])
    return 0


COMMANDS = {"sbatch": sbatch, "squeue": squeue, "sacct": sacct, "scancel": scancel, "sinfo": sinfo, "seff": seff}


def main(argv):
    command, args = argv[1], argv[2:]
    path = os.environ["FAKE_SLURM_STATE"]
    state = load(path)
    state["calls"].append([command] + args)
    code = COMMANDS[command](state, args)
    save(path, state)
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
