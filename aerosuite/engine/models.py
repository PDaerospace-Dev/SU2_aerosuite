"""Project model: every setting of a study, saved as project.json."""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

SCHEMA_VERSION = 3


class Mesh(BaseModel):
    path: str = ""
    markers: list[str] = Field(default_factory=list)


class Freestream(BaseModel):
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
    altitude: str = "sl"
    naming: Naming = Field(default_factory=Naming)


RestartOption = Literal["none", "previous", "custom"]


class Case(BaseModel):
    name: str
    mach: float
    alpha: float
    beta: float
    restart: RestartOption = "none"
    # custom: absolute path of a restart file, or of a case folder holding one
    restart_ref: Optional[str] = None


class RunSettings(BaseModel):
    partitions: int = Field(default=1, ge=1)
    sweep_script: str = ""  # empty = bundled resources/aoa_sweep_v8.py
    sweep_python: str = "python3"  # must be able to import SU2


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
