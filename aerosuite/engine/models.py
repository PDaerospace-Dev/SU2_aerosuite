"""Project model: every setting of a study, saved as project.json."""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

SCHEMA_VERSION = 7


class Mesh(BaseModel):
    path: str = ""
    markers: list[str] = Field(default_factory=list)


FreestreamMode = Literal["manual", "altitude"]


class Freestream(BaseModel):
    # "altitude": each case's temperature and Reynolds number come from the ISA at its altitude and its own
    # Mach; temperature_K and reynolds are then kept (unused) for switching back.
    mode: FreestreamMode = "manual"
    altitude_km: Optional[float] = None  # the single case's altitude; a sweep uses SweepSpec.altitudes_km
    temperature_K: Optional[float] = None
    reynolds: Optional[float] = None
    reynolds_length: Optional[float] = None


class Reference(BaseModel):
    origin_x: Optional[float] = None
    origin_y: Optional[float] = None
    origin_z: Optional[float] = None
    ref_length: Optional[float] = None
    ref_area: Optional[float] = None


class Numerics(BaseModel):
    turb_model: Optional[str] = None
    cfl: Optional[float] = None
    iter: Optional[int] = None
    conv_method: Optional[str] = None
    muscl: Optional[str] = None


class Settings(BaseModel):
    """Project-wide SU2 settings. A field left as None keeps the template's value."""

    freestream: Freestream = Field(default_factory=Freestream)
    reference: Reference = Field(default_factory=Reference)
    numerics: Numerics = Field(default_factory=Numerics)
    # None removes the MARKER_ line; an absent key keeps the template's line.
    markers: dict[str, Optional[str]] = Field(default_factory=dict)
    overrides: dict[str, str] = Field(default_factory=dict)


class Naming(BaseModel):
    include_mach: bool = True
    include_alpha: bool = True
    include_beta: bool = True
    include_altitude: bool = True
    include_base: bool = True
    base_name: str = ""


class SweepSpec(BaseModel):
    enabled: bool = True  # False: the project is a single case
    mach: list[float] = Field(default_factory=list)
    alpha: list[float] = Field(default_factory=list)
    beta: list[float] = Field(default_factory=list)
    # Swept (outermost) in altitude mode; kept, unused, in manual mode.
    altitudes_km: list[float] = Field(default_factory=list)
    altitude: str = "sl"  # the typed name label (manual mode, or altitude mode without altitudes)
    naming: Naming = Field(default_factory=Naming)


RestartOption = Literal["none", "previous", "custom"]


class Case(BaseModel):
    name: str
    mach: float
    alpha: float
    beta: float
    altitude_km: Optional[float] = None  # set in altitude mode with the sweep on
    restart: RestartOption = "none"
    # custom: absolute path of a restart file, or of a case folder holding one
    restart_ref: Optional[str] = None


class RunSettings(BaseModel):
    partitions: int = Field(default=1, ge=1)
    sweep_script: str = ""  # empty = bundled resources/aoa_sweep_v8.py
    sweep_python: str = "python3"  # must be able to import SU2


class DerivedValue(BaseModel):
    """A per-case formula (derived) or a per-curve one (characteristic value); see engine/formula.py."""
    name: str
    formula: str
    unit: str = ""


class PlotSpec(BaseModel):
    x: str  # a sweep variable (Mach, Alpha, Beta, Altitude) or a parameter
    y: list[str] = Field(min_length=1)
    split: Optional[str] = None  # the sweep variable that makes one line each; None = automatic


ResultsSection = Literal["plots", "characteristics", "results"]


class ResultsSettings(BaseModel):
    """The Results page, per study."""
    # History columns and derived names, in display order; None: not chosen yet (the packages' or the first ones)
    parameters: Optional[list[str]] = None
    derived: list[DerivedValue] = Field(default_factory=list)
    characteristics: list[DerivedValue] = Field(default_factory=list)
    plots: list[PlotSpec] = Field(default_factory=list)  # the user's own; packages bring their own
    packages: Optional[list[str]] = None  # None: not chosen yet (the page enables what the history supports)
    compare: list[str] = Field(default_factory=list)  # other study folders drawn over this one
    filters: dict[str, list[float]] = Field(default_factory=dict)  # sweep variable -> values shown; absent = all
    average_last: int = Field(default=100, ge=1)
    folded: list[ResultsSection] = Field(default_factory=list)


class ImportedCase(BaseModel):
    """A case folder of an imported study (paths absolute); its values from its .cfg, else its folder name."""
    name: str
    folder: str
    cfg: Optional[str] = None
    history: str
    mach: float
    alpha: float
    beta: float = 0.0
    altitude_km: Optional[float] = None
    temperature_K: Optional[float] = None
    base: str = ""  # the unrecognised parts of the folder name, e.g. "vt"


class ImportedRuns(BaseModel):
    """Existing SU2 runs this read-only study reads (engine/imported.py); the source is never written."""
    source: str
    cases: list[ImportedCase] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)  # from the last scan


class Project(BaseModel):
    schema_version: int = SCHEMA_VERSION
    name: str
    created: datetime = Field(default_factory=datetime.now)
    modified: datetime = Field(default_factory=datetime.now)
    mesh: Mesh = Field(default_factory=Mesh)
    template: str = "template.cfg"
    preset: Optional[str] = None
    profile: Optional[str] = None  # aircraft profile id; None = general project
    settings: Settings = Field(default_factory=Settings)
    sweep: SweepSpec = Field(default_factory=SweepSpec)
    cases: list[Case] = Field(default_factory=list)
    run: RunSettings = Field(default_factory=RunSettings)
    results: ResultsSettings = Field(default_factory=ResultsSettings)
    imported: Optional[ImportedRuns] = None  # set: a read-only study of existing runs
