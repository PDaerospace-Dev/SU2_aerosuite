# AeroSuite Pro V2

AeroSuite Pro is a desktop application for preparing, running, and reviewing SU2 CFD studies. From mesh loading through config (CFG) generation, parametric sweeps, execution, convergence monitoring, and results analysis.

## Layout

```
+--------------------------------------------------------------------+
| Menu   Toolbar                                      Project Name   |
+---------------+----------------------------------------------------+
| Workflow Tree |                                                    |
|               |                                                    |
| Calculators   |                Content Pane                        |
|  ISA Calc     |         (the page for whatever's selected          |
|  y+ Calc      |          in the tree on the left)                  |
| Project       |                                                    |
|  Directory    |                                                    |
|  Mesh         |                                                    |
|  CFG          |                                                    |
|   Aircraft    |                                                    |
|   General     |                                                    |
|  Sweep        |                                                    |
|  Control File |                                                    |
|  Run          |                                                    |
|  Monitor      |                                                    |
|  Results      |                                                    |
+---------------+----------------------------------------------------+
| Console / Log                                                      |
+--------------------------------------------------------------------+
```
## Workflow
The tree runs top to bottom in execution order:

1. **Calculators**
   - **ISA Calculator** — Standard atmosphere properties at any altitude up to 100 km.
   - **y+ Calculator** — First-cell height for a target y+, feeding into mesh sizing.

*The **"Update SU2 Parameters"** button pushes altitude/temperature/Reynolds straight into the Sweep and CFG pages.*

2. **Directory** — Working directory + output run-folder name. Everything downstream (Mesh, Sweep, Control File) reads its default paths from here.

3. **Mesh** — Load a mesh file. 
For `.su2` meshes, marker tags (e.g. `airfoil`, `farfield`) are auto-extracted and surfaced on the CFG page.

4. **CFG**

   - **Aircraft Aero** (Designed for X07) - Load a `.cfg` template and set freestream, toggle markers, set physical/reference properties and numerics, and generate a single config file. Also includes a live preview of cfg file.

   - **General** — load any `.cfg` file and edit its raw text directly, with the reference panel at the side. 

*Reference- https://github.com/su2code/SU2/blob/master/config_template.cfg (config_template.cfg) for checking or copying marker blocks.*

5. **Sweep** — Load a base `.cfg` file and generate the full Mach × Alpha × Beta parametric sweep from it.

6. **Control File** — Scan a folder of generated `.cfg` files (defaults to the Directory page's working directory) into a per-case restart-configuration table, and write `run_control.txt` from it.
- *Includes a collapsible "What is a control file?" explainer.*

7. **Run** — Launches the sweep script (`aoa_sweep_v8.py` or compatible) as a subprocess and streams its output live.

8. **Monitor** — Live-refreshing residual plots read from SU2 history files.

9. **Results** — Consolidates a batch run's history files into a summary CSV and auto-plots CL/CD/moment.
## Project Structure
```
run_aerosuite.py             Entry point
diagnose.py                  Startup diagnostics (see "Running" above)
aerosuite/
├── main.py                  Main window: menu, toolbar, workflow tree, console
├── requirements.txt
├── resources/
│   └── config_template.cfg  Bundled default reference config (CFG page)
├── core/                    Calculation & generation logic (no Qt dependencies)
│   ├── isa_calculator.py    ISA atmosphere model
│   ├── yplus_calculator.py  y+ / first-cell-height calculation
│   ├── su2_generator.py     Template substitution, marker extraction, filenames
│   ├── sweep_runner.py      Subprocess wrapper for the sweep script
│   ├── monitor.py           SU2 history-file reading for convergence plots
│   └── aerosummary.py       Batch results consolidation (CL/CD/moment)
├── ui/                      PyQt5 pages, one per workflow-tree node (roughly)
│   ├── style.py              Shared font/color constants — import from here
│   │                          rather than hardcoding new font sizes
│   ├── isa_tab.py            Calculators: ISA + y+
│   ├── directory_tab.py       Directory
│   ├── mesh_tab.py            Mesh
│   ├── cfg_tab.py             CFG: AircraftAeroPage, GeneralPage
│   ├── reference_panel.py     Shared collapsible reference-config viewer
│   ├── sweep_setup_tab.py     Sweep
│   ├── control_file_tab.py    Control File
│   ├── sweep_tab.py           Run
│   ├── monitor_tab.py         Monitor
│   ├── aerosummary_tab.py     Results
│   └── su2_tab.py             Legacy combined generator tab — superseded,
│                                kept for reference, not imported by main.py
└── utils/
    ├── validators.py         Input validation helpers
    └── file_handlers.py      JSON/text file read/write helpers
```
## Installation
### Requirements
- Python 3.7+
- PyQt5
- pandas
- matplotlib

```bash
pip install -r aerosuite/requirements.txt
```
### Running
Run the following python script in the terminal from the folder
```bash
python run_aerosuite.py
```

**OR**

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

## Future Plans
-   

## Contributors
Thanks to the following contributors for their work on this project:
1. Midhun
2. Martino
3. Daniel
