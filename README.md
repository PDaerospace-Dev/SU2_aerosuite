# AeroSuite Pro

A PyQt5-based desktop toolkit for SU2 CFD preprocessing and aerodynamic calculations.

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
- Sub-tabs for Setup & Freestream, Batch Control, Markers, and Physics & Numerics
- Custom placeholder support for any non-standard template fields
- Dry-run preview (list filenames before generating)
- Mesh marker auto-extraction from SU2 mesh files
- Profile save/load (JSON) to persist all settings between sessions
- **Auto-generates `run_control.txt`** alongside the `.cfg` files on every generation
- **Standalone Control File Generator** — scan an existing folder of `.cfg` files and write `run_control.txt` without re-generating the configs (collapsible panel in the Batch Control tab)
- After generation, **automatically switches to Sweep Runner** and pre-fills the config directory and control file

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

## Typical Workflow

1. **ISA and Y+ Calculator** — enter altitude and Mach, click Transfer → values land in SU2 tab
2. **SU2 Config Generator** — set sweep ranges, generate configs → app switches to Sweep Runner automatically
3. **Sweep Runner** — config dir and control file are already filled; click Load Plan then Run Sweep
4. **Convergence Monitor** — select a history file while the sweep is running; plot auto-refreshes
5. **Results Analysis** — point at the run directory, select columns, consolidate and plot

## Profile Save / Load

Use **Profiles → Save SU2 Profile** (Ctrl+S) to save all SU2 Generator settings to a JSON file.  
Use **Profiles → Load SU2 Profile** (Ctrl+O) to restore them.

## Version History

### v10.4 — Current
- SU2 Config Generator: Batch Control tab moved to last position
- Batch Control tab: per-file preview table — each generated cfg file appears as a row with its own Restart Option dropdown (none / previous / custom) and editable Custom Path field
- When a row is changed to `previous` or `custom`, RESTART_SOL is automatically patched to YES in the corresponding .cfg file on disk; changing back to `none` sets it to NO
- "Apply to All" button to set all rows at once
- "Write run_control.txt from Table" button writes the control file using per-file settings
- After Generate Config Files, the Batch Control tab auto-opens and is pre-populated
- Standalone scan panel updated: "Scan Existing .cfg Folder" now loads files into the preview table instead of writing directly

### v10.3
- Sweep Runner: timestamped log file written to Config Dir on every run (e.g. `sweep_20250501_143022.log`) — captures all script output, iteration progress, errors, and exit code for post-run review
- Log file path shown in the Execution Summary panel and in the completion dialog

### v10.2
- Sweep Runner: mesh file copy — browse a mesh from any directory and copy it into Config Dir with one click
- Sweep Runner: simulation is now independent of AeroSuite — closing the app will NOT kill SU2 (subprocess detached via `start_new_session`)
- Sweep Runner: Stop button removed (no longer applicable with detached process)

### v10.x
- Added Y+ value


### v9.x
- Sweep Runner: clean subprocess architecture, script runs exactly as from terminal
- Cross-tab auto-fill: SU2 generation → Sweep Runner paths pre-populated


### v8.x
- Standalone control file generator (Batch Control tab)


### v7 — Modular Edition
- combined all the python scripts to one.
- Modular approach
- Sweep Runner tab added
---
© 2024 AeroSuite Development Team
