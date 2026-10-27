"""Settings: the server-wide settings in $AEROSUITE_HOME/settings.json — the default backend and how Slurm is used.

Four tabs (`?tab=general|slurm|partitions|remote` opens one): General, Slurm, Partitions (one card per partition;
the chosen one's settings, its own job script included, under the cards; `&partition=<name>` chooses one) and Open
from your PC.
"""
from typing import Callable, Optional

from nicegui import ui

from ...engine import service
from ...engine.errors import ServiceError
from ...engine.remote import default_ssh_address, local_url, ssh_address, tunnel_command, unix_launcher, windows_launcher
from ...engine.settings import (PartitionSettings, SettingsError, load_settings, save_settings, set_value,
                                settings_path, validated)
from .. import serving
from ..fields import text_field
from ..layout import header
from ..ui_kit import banner, card, card_head, danger_button, flat_button, hint, readonly, secondary_button, titled

TABS = [("general", "General"), ("slurm", "Slurm"), ("partitions", "Partitions"), ("remote", "Open from your PC")]
# (key under slurm., label, help) per Slurm card
SUBMIT_FIELDS = [
    ("shared_root", "Shared root", "Case folders must be under it: every node mounts it (NFS)"),
    ("account", "Account", "Slurm -A; empty: none"),
    ("default_time_limit", "Default time limit", "Slurm -t, e.g. 12:00:00 or 2-00:00:00; empty: none"),
]
SCRIPT_FIELDS = [
    ("module_line", "Module line", "Run in the job script before SU2, e.g. module load mpi/openmpi-x86_64"),
    ("su2_bin", "SU2 bin folder", "Put first on PATH in the job script"),
    ("srun_command", "Launch command", "Followed by the case's .cfg, e.g. srun --mpi=pmix SU2_CFD"),
    ("job_env", "Job environment", "Exported in the job script: NAME=value, separated by spaces "
                                   "(OMPI_MCA_osc=^ucx silences Open MPI's harmless UCX warning)"),
]
ESTIMATE_FIELDS = [
    ("gb_per_million_cells", "Memory per million cells (GB)", "For the memory estimate before a submit"),
    ("poll_seconds", "Poll interval (s)", "One squeue call per interval for all jobs (5–120)"),
]
LAUNCH_HELP = ("Followed by the case's .cfg. Empty: the Slurm-wide job script (Slurm tab). Set: the partition's "
               "own job script, from the fields below only")
PARTITION_SCRIPT_FIELDS = [  # (key, label, help): a partition's own job script, used with its own launch command
    ("path", "PATH", "Replaces PATH in the job script, e.g. /usr/local/bin:/usr/bin:/bin; empty: PATH is left alone"),
    ("unset_vars", "Unset", "Variable names, separated by spaces, e.g. LD_LIBRARY_PATH"),
    ("module_line", "Module line", "Run before SU2; empty: none"),
    ("job_env", "Job environment", "NAME=value, separated by spaces"),
]
PARTITION_FIELDS = [("default_ntasks", "Tasks per case", "Each case's MPI ranks unless the run says otherwise"),
                    ("memory_limit_mb", "Memory limit (MB)", "What an --exclusive job may use before Slurm kills it"),
                    ("ntasks_warn_above", "Warn above (tasks)", "No speed-up beyond this many tasks; empty: no warning")]
EXCLUSIVE = {"": "Slurm-wide", "yes": "One job per node", "no": "Share the node"}


def cell() -> ui.column:
    """One field of an `as-field-pair` grid: the box and its error line in one cell."""
    return ui.column().classes("gap-0 min-w-0 w-full")


def gigabytes(mb: int) -> str:
    gb = mb / 1024
    return f"{gb:.0f} GB" if gb >= 100 or gb == int(gb) else f"{gb:.1f} GB"


def register() -> None:
    @ui.page("/settings")
    def settings_page(tab: str = "general", partition: str = "") -> None:
        header("settings")
        holder = ui.column().classes("as-page w-full")
        with holder:
            with ui.row().classes("as-crumbs w-full"):
                ui.link("Projects", "/").classes("as-crumb-link").mark("crumb-projects")
                ui.label("›").classes("as-crumb-sep")
                ui.label("Settings").classes("as-crumb-current").mark("crumb-page")
            SettingsPage(tab, partition)


class SettingsPage:
    def __init__(self, tab: str = "general", partition: str = "") -> None:
        self.tab = tab if tab in dict(TABS) else "general"
        names = [p.name for p in load_settings()[0].slurm.partitions]
        self.selected = names.index(partition) if partition in names else 0  # whose settings show under the cards
        self.holder = ui.column().classes("as-settings w-full gap-4")
        self.render()

    def render(self) -> None:
        self.settings, warnings = load_settings()
        self.selected = min(self.selected, len(self.settings.slurm.partitions) - 1)
        self.holder.clear()
        with self.holder:
            for warning in warnings:
                banner("warning", warning).mark("settings-warning")
            with ui.tabs(value=self.tab, on_change=lambda e: self._set_tab(e.value)).props(
                    "dense no-caps align=left inline-label").classes("as-tabs w-full").mark("settings-tabs") as tabs:
                for key, label in TABS:
                    with ui.tab(key, label).mark(f"settings-tab-{key}"):
                        if key == "partitions":
                            ui.label(str(len(self.settings.slurm.partitions))).classes("as-tab-count")
            with ui.tab_panels(tabs, value=self.tab).props("keep-alive").classes("as-tab-panels w-full"):
                with ui.tab_panel("general").classes("gap-4"):
                    self._general()
                with ui.tab_panel("slurm").classes("gap-4"):
                    self._slurm()
                with ui.tab_panel("partitions").classes("gap-4"):
                    self._partitions()
                with ui.tab_panel("remote").classes("gap-4"):
                    self._remote()

    def _set_tab(self, tab: str) -> None:
        self.tab = tab
        ui.run_javascript(f"history.replaceState(null, '', '/settings?tab={tab}')")  # a reload keeps the tab

    # -- General -----------------------------------------------------------------------------------------------

    def _general(self) -> None:
        with card("Execution", f"Saved in {settings_path()}"):
            with ui.column().classes("w-full gap-1"):
                with ui.row().classes("items-center gap-3"):
                    ui.label("Run jobs on").classes("as-label")
                    ui.toggle({"local": "This machine (mpirun)", "slurm": "Slurm"}, value=self.settings.backend,
                              on_change=lambda e: self._set("backend", e.value)).props(
                        "dense no-caps unelevated toggle-color=primary").classes("as-toggle").mark("settings-backend")
                hint("The default for studies that have not chosen; each study can choose on its Run page.")
            with ui.column().classes("w-full gap-1"):
                ui.switch("Check each case's config with SU2 before Generate and Submit",
                          value=self.settings.check_with_su2,
                          on_change=lambda e: self._set("check_with_su2", "true" if e.value else "false")
                          ).mark("settings-check_with_su2")
                hint("SU2_CFD -d (a dry run: SU2's own checks, without loading the mesh), about 2 s per config, "
                     "from the SU2 bin folder on the Slurm tab. A config SU2 rejects stops the submit.")

    # -- Slurm -------------------------------------------------------------------------------------------------

    def _slurm(self) -> None:
        slurm = self.settings.slurm
        with ui.element("div").classes("as-settings-grid w-full"):
            with card("Submitting", "Every job is one node"):
                ui.select([p.name for p in slurm.partitions], value=slurm.default_partition,
                          label="Default partition",
                          on_change=lambda e: self._set("slurm.default_partition", e.value)).props(
                    "outlined dense").classes("as-field w-full").mark("settings-default_partition")
                self._fields(SUBMIT_FIELDS[:1])
                ui.switch("One job per node (--exclusive)", value=slurm.exclusive,
                          on_change=lambda e: self._set("slurm.exclusive", "true" if e.value else "false")
                          ).mark("settings-exclusive")
                with ui.element("div").classes("as-field-pair w-full"):
                    self._fields(SUBMIT_FIELDS[1:])
            with card("Job script", "For partitions without their own"):
                self._fields(SCRIPT_FIELDS, mono=True)
        with card("Estimates and polling"):
            with ui.element("div").classes("as-field-pair w-full"):
                self._fields(ESTIMATE_FIELDS)

    def _fields(self, fields: list, mono: bool = False) -> None:
        for key, label, help_text in fields:
            with cell():
                text_field(label, getattr(self.settings.slurm, key), self._committer(f"slurm.{key}"),
                           mark=f"settings-{key}", mono=mono, help=help_text)

    # -- Partitions --------------------------------------------------------------------------------------------

    def _partitions(self) -> None:
        with ui.row().classes("w-full items-center"):
            hint("Click a partition for its settings.")
            ui.space()
            secondary_button("Add partition", on_click=self._add, icon="add").mark("partition-add")
        self._cards = ui.element("div").classes("as-partition-grid w-full").mark("partition-cards")
        self._draw_cards()
        self._detail()

    def _draw_cards(self) -> None:
        """The partitions as cards (redrawn after each saved edit, so they follow the form under them)."""
        slurm = load_settings()[0].slurm
        self._cards.clear()
        with self._cards:
            for index, partition in enumerate(slurm.partitions):
                self._card(index, partition, partition.name == slurm.default_partition)

    def _card(self, index: int, partition: PartitionSettings, default: bool) -> None:
        """One line of name and badges, one of numbers: tasks, memory limit, warn above, over memory."""
        box = ui.column().classes("as-card as-partition-card" + (" as-partition-current" if index == self.selected
                                                                    else ""))
        box.on("click", lambda i=index: self._select(i)).mark(f"partition-card-{index}")
        with box:
            with ui.row().classes("items-center gap-2 no-wrap w-full"):
                ui.label(partition.name).classes("as-partition-name as-truncate")
                if default:
                    ui.label("default").classes("as-pill as-pill-running")
                ui.space()
                if partition.launch_command:
                    titled(ui.label("own script").classes("as-pill as-pill-pending"), partition.launch_command)
            facts = [f"{partition.default_ntasks} tasks", gigabytes(partition.memory_limit_mb)]
            if partition.ntasks_warn_above:
                facts.append(f"warn > {partition.ntasks_warn_above}")
            facts.append("blocks over memory" if partition.block_over_memory else "warns over memory")
            ui.label(" · ".join(facts)).classes("as-muted as-truncate")

    def _select(self, index: int) -> None:
        self.selected = index
        self.render()

    def _detail(self) -> None:
        """The chosen partition's settings: its limits, then its job script."""
        slurm = self.settings.slurm
        index, partition = self.selected, slurm.partitions[self.selected]
        default = partition.name == slurm.default_partition
        with card() as box:
            box.mark(f"partition-detail-{index}")
            with card_head(partition.name, "the default partition" if default else None):
                ui.space()
                if not default:
                    flat_button("Make default", on_click=lambda: self._set("slurm.default_partition",
                                                                           partition.name)).mark(
                        f"partition-{index}-make-default")
                remove = danger_button("Remove", on_click=lambda: self._remove(index), icon="delete").mark(
                    f"partition-{index}-remove")
                if len(slurm.partitions) == 1 or default:
                    remove.set_enabled(False)
                    remove.props['title'] = "The default partition stays; make another the default first"
            with ui.element("div").classes("as-field-pair w-full"):
                with cell():
                    text_field("Name", partition.name, self._partition_committer(index, "name"),
                               mark=f"partition-{index}-name")
                for key, label, help_text in PARTITION_FIELDS:
                    value = getattr(partition, key)
                    with cell():
                        text_field(label, "" if value is None else value, self._partition_committer(index, key),
                                   mark=f"partition-{index}-{key}", help=help_text)
            with ui.row().classes("items-center gap-3"):
                ui.label("Over the memory limit").classes("as-label")
                ui.toggle({False: "Warn", True: "Block"}, value=partition.block_over_memory,
                          on_change=lambda e: self._save_data(lambda d: d["slurm"]["partitions"][index].update(
                              block_over_memory=bool(e.value)))).props(
                    "dense no-caps unelevated toggle-color=primary").classes("as-toggle").mark(f"partition-{index}-block")
                hint("what a submit does when its memory estimate is above the limit")
            ui.label("Job script").classes("as-card-title as-section-title")
            text_field("Launch command", partition.launch_command, self._launch_committer(index),
                       mark=f"partition-{index}-launch_command", mono=True, help=LAUNCH_HELP,
                       placeholder=f"Slurm-wide: {slurm.srun_command}")
            if partition.launch_command:
                with ui.element("div").classes("as-field-pair w-full"):
                    for key, label, help_text in PARTITION_SCRIPT_FIELDS:
                        with cell():
                            text_field(label, getattr(partition, key), self._partition_text(index, key),
                                       mark=f"partition-{index}-{key}", mono=True, help=help_text)
                ui.switch("Login shell (#!/bin/bash -l)", value=partition.login_shell,
                          on_change=lambda e: self._save_data(lambda d: d["slurm"]["partitions"][index].update(
                              login_shell=bool(e.value)))).mark(f"partition-{index}-login_shell")
            else:
                hint("Uses the Slurm-wide job script (Slurm tab). Give it a launch command for a script of its "
                     "own, e.g. mpirun on the workstation; then only its own environment is used.").mark(
                    f"partition-{index}-slurm-wide")
            with ui.row().classes("items-center gap-3"):
                ui.label("Exclusive").classes("as-label")
                ui.toggle(EXCLUSIVE, value={None: "", True: "yes", False: "no"}[partition.exclusive],
                          on_change=lambda e: self._save_data(lambda d: d["slurm"]["partitions"][index].update(
                              exclusive={"": None, "yes": True, "no": False}[e.value]))).props(
                    "dense no-caps unelevated toggle-color=primary").classes("as-toggle").mark(
                    f"partition-{index}-exclusive")

    # -- Open from your PC -------------------------------------------------------------------------------------

    def _remote(self) -> None:
        port = serving.PORT["value"]
        address = ssh_address(self.settings)
        command = tunnel_command(address, port)
        with card("Open from your PC", "AeroSuite has no login, so it listens on this machine only; "
                                       "an SSH tunnel brings it to your PC"):
            text_field("SSH address of this machine", self.settings.ssh_address, self._address,
                       mark="settings-ssh_address", placeholder=default_ssh_address(),
                       help="user@host as your PC reaches it: the hostname on the same network, or e.g. its "
                            f"Tailscale IP. Empty: {default_ssh_address()}.")
            ui.label("Download a launcher, copy it to your PC and double-click it: it opens the tunnel, then "
                     f"AeroSuite in your browser at {local_url(port)}. Closing its window disconnects.").classes(
                "as-label")
            with ui.row().classes("gap-2"):
                secondary_button("Windows (AeroSuite.bat)", icon="download", on_click=lambda: ui.download.content(
                    windows_launcher(address, port), "AeroSuite.bat", "application/octet-stream")).mark(
                    "remote-windows")
                secondary_button("Mac or Linux (aerosuite.command)", icon="download",
                                 on_click=lambda: ui.download.content(unix_launcher(address, port), "aerosuite.command",
                                                                      "application/octet-stream")).mark("remote-mac")
            ui.label("Or run this on your PC, then open the address above:").classes("as-label")
            with ui.row().classes("w-full items-center no-wrap gap-2"):
                readonly(command, mono=True).mark("remote-command")
                secondary_button("Copy", icon="content_copy", on_click=lambda: self._copy(command)).mark("remote-copy")
            hint(self._service_note(port)).mark("remote-service")

    def _address(self, text: str) -> Optional[str]:
        message = self._set("ssh_address", text, render=False)
        if message is None:
            self.render()  # the command and the launchers follow
        return message

    def _copy(self, text: str) -> None:
        ui.clipboard.write(text)
        ui.notify("Copied", type="positive")

    def _service_note(self, port: int) -> str:
        try:
            running = service.is_installed() and service.is_active()
        except ServiceError:
            running = False
        if running:
            return "Running as a service: it starts at boot and keeps running when you log out " \
                   "(aerosuite service status / restart / stop on this machine)."
        return "To keep AeroSuite running without a terminal, run this once on this machine: " \
               f"aerosuite service install --root {self.settings.slurm.shared_root} --port {port}"

    # -- saving ------------------------------------------------------------------------------------------------

    def _committer(self, key: str) -> Callable[[str], Optional[str]]:
        def commit(text: str) -> Optional[str]:
            return self._set(key, text, render=False)

        return commit

    def _set(self, key: str, text: str, render: bool = True) -> Optional[str]:
        try:
            save_settings(set_value(load_settings()[0], key, text))
        except SettingsError as exc:
            if render:
                ui.notify(str(exc), type="negative")
            return str(exc)
        if render:
            self.render()
        return None

    def _save_data(self, change: Callable[[dict], None]) -> Optional[str]:
        data = load_settings()[0].model_dump()
        change(data)
        try:
            save_settings(validated(data))
        except SettingsError as exc:
            ui.notify(str(exc), type="negative")
            return str(exc)
        self.render()
        return None

    def _launch_committer(self, index: int) -> Callable[[str], Optional[str]]:
        """The launch command: setting or clearing it shows or hides the partition's own job script fields."""
        save = self._partition_text(index, "launch_command")

        def commit(text: str) -> Optional[str]:
            message = save(text)
            if message is None and bool(text.strip()) != bool(self.settings.slurm.partitions[index].launch_command):
                self.render()
            return message

        return commit

    def _partition_text(self, index: int, key: str) -> Callable[[str], Optional[str]]:
        def commit(text: str) -> Optional[str]:
            data = load_settings()[0].model_dump()
            partitions = data["slurm"]["partitions"]
            if index >= len(partitions):
                return "This partition is gone; reload the page"
            partitions[index][key] = text.strip()
            try:
                save_settings(validated(data))
            except SettingsError as exc:
                return str(exc)
            self._draw_cards()
            return None

        return commit

    def _partition_committer(self, index: int, key: str) -> Callable[[str], Optional[str]]:
        def commit(text: str) -> Optional[str]:
            data = load_settings()[0].model_dump()
            partitions = data["slurm"]["partitions"]
            if index >= len(partitions):
                return "This partition is gone; reload the page"
            text = text.strip()
            if key == "name":
                if data["slurm"]["default_partition"] == partitions[index]["name"]:
                    data["slurm"]["default_partition"] = text
                partitions[index]["name"] = text
            elif key == "ntasks_warn_above" and text.lower() in ("", "none"):
                partitions[index][key] = None
            else:
                try:
                    partitions[index][key] = int(text)
                except ValueError:
                    return f"{text!r} is not a whole number"
            try:
                save_settings(validated(data))
            except SettingsError as exc:
                return str(exc)
            self._draw_cards()
            return None

        return commit

    def _add(self) -> None:
        def change(data: dict) -> None:
            names = {p["name"] for p in data["slurm"]["partitions"]}
            number = len(names) + 1
            while f"node{number}" in names:
                number += 1
            data["slurm"]["partitions"].append({"name": f"node{number}", "default_ntasks": 1,
                                                "memory_limit_mb": 1024, "ntasks_warn_above": None,
                                                "block_over_memory": False})
            self.selected = len(data["slurm"]["partitions"]) - 1  # the new one opens for editing

        self._save_data(change)

    def _remove(self, index: int) -> None:
        self.selected = max(0, index - 1)
        self._save_data(lambda data: data["slurm"]["partitions"].pop(index))
