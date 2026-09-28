"""Profiles: what a new study of an aircraft starts from. See them, edit them, copy or delete them.

The Aircraft form's settings (freestream, numerics, markers, placeholders) are shown, not edited here:
they come from a study, through Setup's "Save as profile…".
"""
from pathlib import Path
from typing import Callable, Optional

from nicegui import ui

from ...engine.cfg import settings_parameters
from ...engine.editing import parse_value_list
from ...engine.errors import ProjectError
from ...engine.models import Settings
from ...engine.naming import format_value
from ...engine.profiles import (BUNDLED_PROFILES, Profile, ProfileData, delete_profile, duplicate_profile,
                                edit_profile, list_profiles, load_profile, set_profile_mesh, set_profile_template)
from ..fields import text_field
from ..layout import header
from ..picker import pick_path
from ..session import parse_int, parse_optional_number
from ..ui_kit import (banner, card, card_head, danger_button, field, hint, primary_button, secondary_button, table,
                      td, th)

REFERENCE = [("Reference length", "ref_length"), ("Reference area", "ref_area"), ("Moment origin x", "origin_x"),
             ("Moment origin y", "origin_y"), ("Moment origin z", "origin_z")]
SWEEP_LISTS = [("Mach", "mach"), ("α (deg)", "alpha"), ("β (deg)", "beta")]
EDITED_HERE = {"REF_LENGTH", "REF_AREA", "REF_ORIGIN_MOMENT_X", "REF_ORIGIN_MOMENT_Y", "REF_ORIGIN_MOMENT_Z"}


def profiles_url(profile_id: str = "") -> str:
    return f"/profiles?id={profile_id}" if profile_id else "/profiles"


def register() -> None:
    @ui.page("/profiles")
    def profiles_page(id: str = "") -> None:  # noqa: A002 - the query parameter is ?id=
        header()
        with ui.column().classes("as-page w-full"):
            with ui.row().classes("as-crumbs w-full"):
                ui.link("Projects", "/").classes("as-crumb-link").mark("crumb-projects")
                ui.label("›").classes("as-crumb-sep")
                ui.label("Profiles").classes("as-crumb-current").mark("crumb-page")
            ProfilesView(id)


def _kind(profile: Profile) -> str:
    if profile.bundled:
        return "bundled"
    return "your copy" if (BUNDLED_PROFILES / profile.id).is_dir() else "yours"


class ProfilesView:
    def __init__(self, chosen: str) -> None:
        profiles, problems = list_profiles()
        for problem in problems:
            banner("warning", f"Profile skipped: {problem}").mark("profile-problem")
        ids = [p.id for p in profiles]
        self.id = chosen if chosen in ids else (ids[0] if ids else "")
        with ui.element("div").classes("as-columns as-columns-profiles"):
            self.list_box = ui.column().classes("gap-4 w-full")
            self.detail = ui.column().classes("gap-4 w-full")
        self.render_list()
        with self.detail:
            if self.id:
                self._detail()
            else:
                ui.label("No profiles yet.").classes("as-muted")

    # -- the list -----------------------------------------------------------------

    def render_list(self) -> None:
        profiles, _ = list_profiles()
        self.list_box.clear()
        with self.list_box, card(flush=True):
            card_head("Profiles", "what a new study starts from")
            for profile in profiles:
                row = ui.link(target=profiles_url(profile.id)).classes(
                    "as-recent-row" + (" as-recent-row-on" if profile.id == self.id else "")).mark(
                    f"profile-row-{profile.id}")
                with row:
                    with ui.column().classes("gap-0 grow min-w-0"):
                        ui.label(profile.name).classes("as-strong as-truncate")
                        ui.label(profile.description or profile.id).classes("as-muted as-truncate")
                    ui.label(_kind(profile)).classes("as-tag")

    # -- the chosen profile ---------------------------------------------------------

    @property
    def profile(self) -> Profile:
        return load_profile(self.id)

    def edit(self, change: Callable[[ProfileData], None]) -> Optional[str]:
        """Save a change to the profile; returns the reason it was refused, if it was."""
        try:
            edit_profile(self.id, change)
        except ProjectError as exc:
            return str(exc)
        self.render_list()
        self.head.refresh()
        return None

    def _detail(self) -> None:
        try:
            profile = self.profile
        except ProjectError as exc:
            banner("error", f"Error: {exc}").mark("profile-error")
            return
        data = profile.data

        @ui.refreshable
        def head() -> None:
            current = self.profile
            with card_head(current.name, _kind(current)):
                ui.space()
                secondary_button("Duplicate…", on_click=self.duplicate, icon="content_copy").mark(
                    "profile-duplicate")
                if not current.bundled:
                    label = "Reset to bundled" if _kind(current) == "your copy" else "Delete"
                    danger_button(label, on_click=self.delete, icon="delete").mark("profile-delete")
            if current.bundled:
                banner("info", f"{current.name} is bundled with AeroSuite: a change here saves your own copy, "
                       "which you can reset to the bundled one later.").mark("profile-bundled-note")

        self.head = head
        with card():
            head()
            with ui.element("div").classes("as-grid-2"):
                with ui.column().classes("gap-1"):
                    text_field("Name", data.name, lambda text: self.edit(lambda d: setattr(d, "name", text.strip())),
                               mark="profile-name")
                with ui.column().classes("gap-1"):
                    text_field("Description", data.description,
                               lambda text: self.edit(lambda d: setattr(d, "description", text.strip())),
                               mark="profile-description")
        self._files()
        with card("Reference dimensions"):
            with ui.element("div").classes("as-grid-3"):
                for label, name in REFERENCE:
                    with ui.column().classes("gap-1"):
                        self._reference_field(label, name, data)
        with card("Sweep", "a new study's Mach, α and β; each study can change them"):
            with ui.element("div").classes("as-grid-3"):
                for label, name in SWEEP_LISTS:
                    with ui.column().classes("gap-1"):
                        self._list_field(label, name, data)
            with ui.element("div").classes("as-grid-3"):
                with ui.column().classes("gap-1"):
                    text_field("Altitude label", data.sweep.get("altitude", ""),
                               lambda text: self.edit(lambda d: _set_or_drop(d.sweep, "altitude", text.strip())),
                               mark="profile-altitude", placeholder="sl, 10km, …")
        with card("Run"):
            with ui.element("div").classes("as-grid-3"):
                with ui.column().classes("gap-1"):
                    text_field("MPI partitions per case", data.run.get("partitions", ""),
                               lambda text: self.edit(lambda d: _set_or_drop(
                                   d.run, "partitions", parse_int(text, "Partitions") if text.strip() else None)),
                               mark="profile-partitions", placeholder="1")
        self._form_values(data)

    def _files(self) -> None:
        @ui.refreshable
        def files() -> None:
            profile = self.profile
            with ui.element("div").classes("as-grid-form w-full"):
                ui.label("Template").classes("as-label")
                with ui.row().classes("items-center no-wrap gap-2 min-w-0"):
                    if profile.template is not None:
                        ui.label(profile.template.name).classes("as-mono as-strong grow").mark("profile-template")
                    else:
                        ui.label("No template").classes("as-muted grow").mark("profile-template")
                    secondary_button("Browse", on_click=lambda: choose_template()).mark("profile-template-browse")
                ui.label("Mesh").classes("as-label")
                with ui.row().classes("items-center no-wrap gap-2 min-w-0"):
                    mesh = profile.data.mesh
                    if mesh:
                        ui.label(mesh).classes("as-mono as-truncate grow").mark("profile-mesh")
                        if not _exists(mesh):
                            ui.label("File not found").classes("as-error-text").mark("profile-mesh-missing")
                    else:
                        ui.label("No mesh").classes("as-muted grow").mark("profile-mesh")
                    secondary_button("Browse", on_click=lambda: choose_mesh()).mark("profile-mesh-browse")
                    if mesh:
                        secondary_button("Remove", on_click=lambda: set_mesh(None)).mark("profile-mesh-remove")

        async def choose_template() -> None:
            path = await pick_path("Choose the profile's template", mode="file", suffixes=(".cfg",))
            if path is not None:
                run(lambda: set_profile_template(self.id, path))

        async def choose_mesh() -> None:
            path = await pick_path("Choose the profile's mesh", mode="file", suffixes=(".su2", ".cgns"))
            if path is not None:
                set_mesh(path)

        def set_mesh(path) -> None:
            run(lambda: set_profile_mesh(self.id, path))

        def run(action: Callable[[], object]) -> None:
            try:
                action()
            except ProjectError as exc:
                error.set_text(str(exc))
                return
            error.set_text("")
            files.refresh()
            self.render_list()
            self.head.refresh()

        with card("Files", "the template is copied into the profile; the mesh stays where it is"):
            files()
            error = ui.label("").classes("as-error-text").mark("profile-files-error")

    def _reference_field(self, label: str, name: str, data: ProfileData) -> None:
        value = data.settings.get("reference", {}).get(name)

        def change(text: str) -> Optional[str]:
            try:
                number = parse_optional_number(text, label)
            except ProjectError as exc:
                return str(exc)
            return self.edit(lambda d: _set_or_drop(d.settings.setdefault("reference", {}), name, number))

        text_field(label, "" if value is None else format_value(value), change, mark=f"profile-{name}")

    def _list_field(self, label: str, name: str, data: ProfileData) -> None:
        values = data.sweep.get(name)

        def change(text: str) -> Optional[str]:
            try:
                parsed = parse_value_list(text) if text.strip() else None
            except ProjectError as exc:
                return str(exc)
            return self.edit(lambda d: _set_or_drop(d.sweep, name, parsed))

        text_field(label, ", ".join(format_value(v) for v in values) if values else "", change,
                   mark=f"profile-{name}", placeholder="e.g. 0.6, 0.8 or 0:10:2")

    def _form_values(self, data: ProfileData) -> None:
        params = {k: v for k, v in settings_parameters(Settings.model_validate(data.settings)).items()
                  if k not in EDITED_HERE}
        with card("From the Aircraft form", "change these in a study's Aircraft page, then Setup → Save as "
                  "profile… with this id", flush=True) as box:
            box.mark("profile-form-values")
            if not params and not data.hints:
                ui.label("None: new studies use the template's values.").classes("as-muted px-4 pb-4")
                return
            with table("minmax(12rem, 16rem) minmax(0, 1fr)"):
                th("Option")
                th("Value")
                for key, value in sorted(params.items()):
                    td(key, mono=True)
                    td("(removed from the config)" if value is None else str(value), mono=True)
                for key, value in sorted(data.hints.items()):
                    if key not in params:
                        td(key, mono=True)
                        td(f"{value}  (hint)", mono=True)

    # -- copy and delete --------------------------------------------------------------

    async def duplicate(self) -> None:
        with ui.dialog() as dialog, ui.card().classes("w-96"):
            ui.label(f"Copy {self.profile.name} as a new profile").classes("as-dialog-title")
            id_box = field(ui.input("New id (letters, digits, - and _)")).classes("w-full").mark("duplicate-id")
            name_box = field(ui.input("Name")).classes("w-full").mark("duplicate-name")
            error = ui.label("").classes("as-error-text").mark("duplicate-error")
            with ui.row().classes("w-full justify-end gap-2"):
                secondary_button("Cancel", on_click=lambda: dialog.submit(None)).mark("duplicate-cancel")
                primary_button("Copy", on_click=lambda: attempt()).mark("duplicate-save")

        def attempt() -> None:
            try:
                copy = duplicate_profile(self.id, (id_box.value or "").strip(), name_box.value or "")
            except ProjectError as exc:
                error.text = str(exc)
                return
            dialog.submit(copy.id)

        new_id = await dialog
        dialog.delete()
        if new_id:
            ui.navigate.to(profiles_url(new_id))

    async def delete(self) -> None:
        profile = self.profile
        reset = _kind(profile) == "your copy"
        text = (f"Reset {profile.name} to the bundled profile? Your changes to it are deleted."
                if reset else f"Delete the profile {profile.name}? Studies made from it keep their settings.")
        with ui.dialog() as dialog, ui.card():
            ui.label(text)
            with ui.row().classes("w-full justify-end gap-2"):
                secondary_button("Cancel", on_click=lambda: dialog.submit(False)).mark("confirm-cancel")
                danger_button("Reset" if reset else "Delete", on_click=lambda: dialog.submit(True)).mark(
                    "confirm-delete")
        confirmed = await dialog
        dialog.delete()
        if not confirmed:
            return
        try:
            delete_profile(self.id)
        except ProjectError as exc:
            ui.notify(str(exc), type="negative")
            return
        ui.navigate.to(profiles_url(self.id if reset else ""))


def _set_or_drop(values: dict, key: str, value) -> None:
    """Set `key`, or remove it when `value` is empty (a new study then keeps its own default)."""
    if value is None or value == "":
        values.pop(key, None)
    else:
        values[key] = value


def _exists(path: str) -> bool:
    return Path(path).is_file()
