"""The tag index: every #tag used in a job's note, in every project ($AEROSUITE_HOME/tags.json), for the Run page's
autocomplete. Kept current whenever a note is saved, never by reading job files while someone types; when the file is
missing it is rebuilt once from the recent projects' job files.

The file is {tag: {"count": jobs with the tag, "projects": {project folder: jobs with the tag there}}}."""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import NamedTuple, Optional

from .errors import JobError
from .home import aerosuite_home, load_recent
from .jobs.runner import note_tags
from .jobs.store import scan_jobs

_lock = threading.Lock()
_cache: dict = {"stamp": None, "index": {}}  # the file as last read, by (mtime, size)


def tags_file() -> Path:
    return aerosuite_home() / "tags.json"


def _read() -> Optional[dict]:
    """The index on disk, None when it is missing or not an index."""
    path = tags_file()
    try:
        stat = path.stat()
    except OSError:
        return None
    stamp = (stat.st_mtime_ns, stat.st_size)
    if _cache["stamp"] == stamp:
        return _cache["index"]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    index = {tag: entry for tag, entry in data.items()
             if isinstance(tag, str) and isinstance(entry, dict) and isinstance(entry.get("projects"), dict)}
    _cache.update(stamp=stamp, index=index)
    return index


def _write(index: dict) -> None:
    """Atomically, as a job record is saved. A failure is ignored: the index is a convenience."""
    path = tags_file()
    tmp = path.with_name(path.name + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(index, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        return
    _cache["stamp"] = None


def rebuild(projects: list[Path]) -> dict:
    """The index from every job of `projects` (a note's tags counted once per job); written to disk."""
    index: dict = {}
    for directory in dict.fromkeys(str(Path(p).resolve()) for p in projects):
        try:
            jobs, _problems = scan_jobs(Path(directory))
        except (JobError, OSError):
            continue
        for job in jobs:
            for tag in note_tags(job.note):
                entry = index.setdefault(tag, {"count": 0, "projects": {}})
                entry["count"] += 1
                entry["projects"][directory] = entry["projects"].get(directory, 0) + 1
    _write(index)
    return index


def load_index(project_dir: Optional[Path] = None) -> dict:
    """The index, built from the recent projects (and `project_dir`) when there is none yet."""
    with _lock:
        index = _read()
        if index is None:
            index = rebuild(load_recent() + ([Path(project_dir)] if project_dir is not None else []))
        return index


def note_changed(project_dir: Path, old: str, new: str) -> None:
    """A job of `project_dir` had the note `old` and now has `new`: move the tags' counts."""
    before, after = set(note_tags(old)), set(note_tags(new))
    if before == after:
        return
    directory = str(Path(project_dir).resolve())
    with _lock:
        index = _read()
        if index is None:  # first use: the job files, which hold the new note already, are the truth
            rebuild(load_recent() + [Path(directory)])
            return
        for tag in before - after:
            entry = index.get(tag)
            if entry is None:
                continue
            entry["count"] = max(0, entry["count"] - 1)
            here = entry["projects"].get(directory, 0) - 1
            if here > 0:
                entry["projects"][directory] = here
            else:
                entry["projects"].pop(directory, None)
            if entry["count"] == 0 or not entry["projects"]:
                del index[tag]
        for tag in after - before:
            entry = index.setdefault(tag, {"count": 0, "projects": {}})
            entry["count"] += 1
            entry["projects"][directory] = entry["projects"].get(directory, 0) + 1
        _write(index)


class TagMatch(NamedTuple):
    tag: str
    count: int
    scope: str  # "this project" when only the project asked from uses it, else "all projects"


def matching_tags(prefix: str, project_dir: Path, limit: int = 6) -> list[TagMatch]:
    """The tags starting with `prefix` (no #), the most used first."""
    directory = str(Path(project_dir).resolve())
    prefix = prefix.lower()
    found = []
    for tag, entry in load_index(project_dir).items():
        if tag.startswith(prefix) and entry["count"] > 0:
            only_here = set(entry["projects"]) <= {directory}
            found.append(TagMatch(tag, entry["count"], "this project" if only_here else "all projects"))
    found.sort(key=lambda match: (-match.count, match.tag))
    return found[:limit]
