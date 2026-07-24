# AeroSuite Pro V2

AeroSuite Pro is a desktop application for preparing, running, and reviewing SU2 CFD studies. It combines project setup, mesh selection, configuration generation, batch control, sweep execution, convergence monitoring, and results summaries in one PyQt5 interface.

## Features

### ISA and Y+ Calculator
- Atmospheric properties at any altitude (0–100 km): temperature, pressure, density
- Dynamic and kinematic viscosity via Sutherland's law
- Speed of sound, true airspeed, dynamic pressure, Reynolds number
- Press **Enter** in any input field to calculate instantly
- One-click transfer of altitude, temperature, and Reynolds number directly to the SU2 Config Generator
- Calulate Y+values

### SU2 Config Generator
- Batch-generate `.cfg` files from a master template across Mach, alpha, and beta sweep ranges
- Custom placeholder support for any non-standard template fields
- Mesh marker auto-extraction from SU2 mesh files
- Profile save/load (JSON) to persist all settings between sessions
- **Standalone Control File Generator** — scan an existing folder of `.cfg` files and write `run_control.txt` without re-generating the configs (collapsible panel in the Batch Control tab)

### Sweep Runner
- Launches `aoa_sweep_v8.py` (or any compatible sweep script) as a subprocess from inside the config directory — exactly as it was used from the terminal
- Browse for sweep script, config dir, control file, and MPI partitions
- **Remembers the sweep script path** between sessions (saved in application settings)
- Load Plan button previews the execution order from the control file before running
- Full SU2 output streams live to the terminal; a summary table with pass/fail and iteration counts appears on completion
- Stop button terminates the sweep cleanly mid-run

### Convergence Monitor
- Loads SU2 history files (`.csv` or `.dat`, legacy and new format)
- Real-time auto-refresh plot at 500 ms intervals while a sweep is running
- Per-column checkboxes to show/hide individual residuals
- Normalization option (divide by iteration-1 value)
- Matplotlib toolbar for zoom, pan, and export

### Results Analysis
- Consolidates multiple SU2 history files from a batch run directory into a single summary CSV
- Configurable column extraction and averaging window
- Convergence check per case
- Auto-generates CL, CD, and moment plots
- Append or overwrite mode for the summary file

## Project Structure

```
aerosuite/
├── main.py                     # Main window and application entry point
├── __init__.py                 # Package constants and version
├── ui/
│   ├── isa_tab.py              # ISA Calculator tab
│   ├── su2_tab.py              # SU2 Config Generator tab (4 sub-tabs)
│   ├── sweep_tab.py            # Sweep Runner tab
│   ├── monitor_tab.py          # Convergence Monitor tab
│   └── aerosummary_tab.py      # Results Analysis tab
├── core/
│   ├── isa_calculator.py       # ISA atmospheric model and Y+ value
│   ├── su2_generator.py        # Config file generation logic
│   ├── sweep_runner.py         # Subprocess wrapper for sweep script
│   ├── monitor.py              # SU2 history file reader
│   └── aerosummary.py          # Results consolidation and plotting
└── utils/
    ├── validators.py           # Input validation helpers
    └── file_handlers.py        # JSON profile and file I/O
```

## Installation

### Requirements

- Python 3.7+
- PyQt5
- pandas
- matplotlib

```bash
pip install PyQt5 pandas matplotlib
```

## Running

```bash
cd aerosuite_edited
python run_aerosuite.py
```

The Aerosuite is added to source in the workstation. In the terminal:

```bash
su2aero
```

## Typical Workflow

*Calculator*
1. **ISA and Y+ Calculator** — enter altitude and Mach, click Transfer → values land in SU2 tab.

*SU2 Project*
1. Set a project directory and select the mesh.
2. Open **CFG** and complete the **General** or **Aircraft Aero** settings.
3. Generate one or more SU2 configuration files.
4. In **Control File**, scan the configuration folder and write `run_control.txt`.
5. In **Run**, choose the sweep script, configuration directory, and control file; load the plan and run it.
4. **Convergence Monitor** — select a history file while the sweep is running; plot auto-refreshes
5. **Results Analysis** — point at the run directory, select columns, consolidate and plot


## Profile Save / Load

Use **Profiles → Save SU2 Profile** (Ctrl+S) to save all SU2 Generator settings to a JSON file.  
Use **Profiles → Load SU2 Profile** (Ctrl+O) to restore them.

## Version History
- v2
