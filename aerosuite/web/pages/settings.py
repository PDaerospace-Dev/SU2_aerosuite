"""Settings: the server-wide settings in $AEROSUITE_HOME/settings.json — the default backend and how Slurm is used."""
from typing import Callable, Optional

from nicegui import ui

from ...engine import service
from ...engine.errors import ServiceError
from ...engine.remote import default_ssh_address, local_url, ssh_address, tunnel_command, unix_launcher, windows_launcher
from ...engine.settings import SettingsError, load_settings, save_settings, set_value, settings_path, validated
from .. import serving
from ..fields import text_field
from ..layout import header
from ..ui_kit import banner, card, card_head, flat_button, hint, readonly, secondary_button, table, td_box, th

FIELDS = [  # (key under slurm., label, hint)
    ("shared_root", "Shared root", "Case folders must be under it: every node mounts it (NFS)"),
    ("module_line", "Module line", "Run in the job script before SU2, e.g. module load mpi/openmpi-x86_64"),
    ("su2_bin", "SU2 bin folder", "Put first on PATH in the job script"),
    ("srun_command", "Launch command", "Followed by the case's .cfg, e.g. srun --mpi=pmix SU2_CFD"),
    ("job_env", "Job environment", "Exported in the job script: NAME=value, separated by spaces "
                                   "(OMPI_MCA_osc=^ucx silences Open MPI's harmless UCX warning)"),
    ("account", "Account", "Slurm -A; empty: none"),
    ("default_time_limit", "Default time limit", "Slurm -t, e.g. 12:00:00 or 2-00:00:00; empty: none"),
    ("gb_per_million_cells", "Memory per million cells (GB)", "For the pre-submit memory estimate"),
    ("poll_seconds", "Poll interval (s)", "One squeue call per interval for all jobs (5–120)"),
]
PARTITION_FIELDS = [("default_ntasks", "Tasks"), ("memory_limit_mb", "Memory limit (MB)"),
                    ("ntasks_warn_above", "Warn above (tasks)")]


def register() -> None:
    @ui.page("/settings")
    def settings_page() -> None:
        header()
        holder = ui.column().classes("as-page w-full")
        with holder:
            with ui.row().classes("as-crumbs w-full"):
                ui.link("Projects", "/").classes("as-crumb-link").mark("crumb-projects")
                ui.label("›").classes("as-crumb-sep")
                ui.label("Settings").classes("as-crumb-current").mark("crumb-page")
            SettingsPage()


class SettingsPage:
    def __init__(self) -> None:
        self.holder = ui.column().classes("w-full gap-4").style("max-width: 920px")
        self.render()

    def render(self) -> None:
        self.settings, warnings = load_settings()
        self.holder.clear()
        with self.holder:
            for warning in warnings:
                banner("warning", warning).mark("settings-warning")
            with card():
                card_head("Execution", f"Saved in {settings_path()}")
                with ui.column().classes("w-full gap-3 px-4 pb-4"):
                    with ui.row().classes("items-center gap-3"):
                        ui.label("Run jobs on").classes("as-label")
                        ui.toggle({"local": "This machine (mpirun)", "slurm": "Slurm"}, value=self.settings.backend,
                                  on_change=lambda e: self._set("backend", e.value)).props(
                            "dense no-caps unelevated").mark("settings-backend")
                    hint("The default for studies that have not chosen; each study can choose on its Run page.")
            with card():
                card_head("Slurm", "Every job is one node; the defaults below are this cluster's")
                with ui.column().classes("w-full gap-2 px-4 pb-4"):
                    slurm = self.settings.slurm
                    names = [p.name for p in slurm.partitions]
                    ui.select(names, value=slurm.default_partition, label="Default partition",
                              on_change=lambda e: self._set("slurm.default_partition", e.value)).classes(
                        "w-full").mark("settings-default_partition")
                    ui.checkbox("One job per node (--exclusive)", value=slurm.exclusive,
                                on_change=lambda e: self._set("slurm.exclusive", "true" if e.value else "false")
                                ).mark("settings-exclusive")
                    for key, label, help_text in FIELDS:
                        text_field(label, getattr(slurm, key), self._committer(f"slurm.{key}"),
                                   mark=f"settings-{key}")
                        hint(help_text)
            with card(flush=True):
                card_head("Partitions", "The memory limit is what an --exclusive job may use before Slurm kills it")
                self._partitions()
            with card():
                card_head("Open from your PC", "AeroSuite has no login, so it listens on this machine only; "
                                               "an SSH tunnel brings it to your PC")
                self._remote()

    def _remote(self) -> None:
        port = serving.PORT["value"]
        address = ssh_address(self.settings)
        command = tunnel_command(address, port)
        with ui.column().classes("w-full gap-2 px-4 pb-4"):
            text_field("SSH address of this machine", self.settings.ssh_address, self._address,
                       mark="settings-ssh_address", placeholder=default_ssh_address())
            hint("user@host as your PC reaches it: the hostname on the same network, or e.g. its Tailscale IP. "
                 f"Empty: {default_ssh_address()}.")
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

    def _partitions(self) -> None:
        partitions = self.settings.slurm.partitions
        with table("minmax(7rem, 1fr) repeat(3, minmax(7rem, 1fr)) auto auto").classes("w-full"):
            for heading in ("Name", *[label for _key, label in PARTITION_FIELDS], "Block when over", ""):
                th(heading)
            for index, partition in enumerate(partitions):
                with td_box():
                    text_field("", partition.name, self._partition_committer(index, "name"),
                               mark=f"partition-{index}-name")
                for key, _label in PARTITION_FIELDS:
                    with td_box():
                        value = getattr(partition, key)
                        text_field("", "" if value is None else value, self._partition_committer(index, key),
                                   mark=f"partition-{index}-{key}")
                with td_box():
                    ui.checkbox(value=partition.block_over_memory, on_change=lambda e, i=index: self._save_data(
                        lambda d: d["slurm"]["partitions"][i].update(block_over_memory=bool(e.value)))).mark(
                        f"partition-{index}-block")
                with td_box():
                    remove = flat_button("", on_click=lambda i=index: self._remove(i), icon="delete").props(
                        "dense").mark(f"partition-{index}-remove")
                    if len(partitions) == 1 or partition.name == self.settings.slurm.default_partition:
                        remove.set_enabled(False)
        with ui.row().classes("px-4 pb-4"):
            secondary_button("Add partition", on_click=self._add, icon="add").mark("partition-add")

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

        self._save_data(change)

    def _remove(self, index: int) -> None:
        self._save_data(lambda data: data["slurm"]["partitions"].pop(index))

