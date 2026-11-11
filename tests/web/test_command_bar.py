"""The top bar's search: what a query finds, and in what order."""
from aerosuite.web.command_bar import Command, matches


def _command(key, group, label, hint="", words="", featured=False):
    return Command(key, group, label, "x", lambda: None, hint=hint, words=words, featured=featured)


COMMANDS = [_command("tracker", "Go to", "Run matrix", words="workbook excel"),
            _command("step-run", "This project", "Run"),
            _command("job-log", "This project", "Show the running job's log", featured=True),
            _command("case-a", "Cases", "M0p8_a0"),
            _command("wing", "Projects", "wing", hint="/data/me"),
            _command("guide-3", "Help", "Run", hint="Web UI guide", words="the job bar")]


def test_nothing_typed_shows_the_places_projects_and_featured():
    assert [c.key for c in matches(COMMANDS, "")] == ["tracker", "job-log", "wing"]


def test_every_word_must_match_somewhere():
    assert [c.key for c in matches(COMMANDS, "excel")] == ["tracker"]
    assert [c.key for c in matches(COMMANDS, "m0p8 a0")] == ["case-a"]
    assert matches(COMMANDS, "m0p8 zzz") == []


def test_groups_keep_their_order_and_labels_that_start_with_it_come_first():
    assert [c.key for c in matches(COMMANDS, "run")] == ["tracker", "step-run", "job-log", "guide-3"]
