"""
User interface modules for AeroSuite Pro.

Submodules:
- isa_tab: ISA / y+ Calculator tab
- directory_tab: Directory (working directory + output folder)
- mesh_tab: Mesh (mesh file, marker extraction)
- cfg_tab: CFG pages - AircraftAeroPage, GeneralPage
- reference_panel: shared collapsible reference-config viewer used by CFG pages
- sweep_setup_tab: Sweep (base cfg + freestream ranges + generate)
- control_file_tab: Control File (scan folder, restart table, run_control.txt)
- su2_tab: legacy combined SU2 Configuration Generator tab (superseded, kept for reference)
- monitor_tab: SU2 Convergence Monitor tab
- aerosummary_tab: SU2 Results Analysis tab
- sweep_tab: Sweep Runner (Run) tab
- style: shared font/color constants and helpers
"""

from .isa_tab import ISATab
from .directory_tab import DirectoryTab
from .mesh_tab import MeshTab
from .cfg_tab import AircraftAeroPage, GeneralPage
from .reference_panel import ReferencePanel
from .sweep_setup_tab import SweepSetupTab
from .control_file_tab import ControlFileTab
from .su2_tab import SU2Tab
from .monitor_tab import MonitorTab
from .aerosummary_tab import AeroSummaryTab
from .sweep_tab import SweepTab
