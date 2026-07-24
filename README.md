AeroSuite Pro V2
AeroSuite Pro is a desktop application for preparing, running, and reviewing SU2 CFD studies. From mesh loading through config (CFG) generation, parametric sweeps, execution, convergence monitoring, and results analysis.

Layout
+--------------------------------------------------------------------+
| Menu   Toolbar                                      Project Name   |
+---------------+------------------------------------------------------+
| Workflow Tree |                                                    |
|               |                                                    |
| Calculators   |                Content Pane                        |
|  ISA Calc     |         (the page for whatever's selected          |
|  y+ Calc      |          in the tree on the left)                  |
| Project       |                                                    |
|  Directory    |                                                    |
|  Geometry     |                                                    |
|  Mesh         |                                                    |
|  CFG          |                                                    |
|   Aircraft    |                                                    |
|   General     |                                                    |
|  Sweep        |                                                    |
|  Control File |                                                    |
|  Run          |                                                    |
|  Monitor      |                                                    |
|  Results      |                                                    |
+---------------+------------------------------------------------------+
| Console / Log                                                      |
+--------------------------------------------------------------------+


Each node in the Workflow Tree shows a status glyph so you can tell at a glance what's been set up:

Glyph	Meaning
✓	Done
⚠	Started but incomplete / file not found
✗	Not started
▶	Ready to run
○	Pending (comes after something not yet done)
Geometry is greyed out and disabled — it's a placeholder for a future stage, not part of the current workflow.

Workflow
The tree runs top to bottom in execution order:

Calculators

ISA Calculator — Standard atmosphere properties at any altitude up to 100 km.
y+ Calculator — First-cell height for a target y+, feeding into mesh sizing. The "Update SU2 Parameters" button pushes altitude/temperature/Reynolds straight into the Sweep and CFG pages.
Directory — Working directory + output run-folder name. Everything downstream (Mesh, Sweep, Control File) reads its default paths from here.

Geometry — not yet implemented.

Mesh — Load a mesh file. For .su2 meshes, marker tags (e.g. airfoil, farfield) are auto-extracted and surfaced on the CFG page.

CFG

Aircraft Aero (Designed for X07)
load a .cfg template and set freestream, toggle markers, set physical/reference properties and numerics, and generate a single config file.
Includes a live preview of the substituted output.
General — load any .cfg file and edit its raw text directly, with the reference panel at the side.
Reference- https://github.com/su2code/SU2/blob/master/config_template.cfg (config_template.cfg) for checking or copying marker blocks.
Sweep — Load a base .cfg file and generate the full Mach × Alpha × Beta parametric sweep from it.

Control File — Scan a folder of generated .cfg files (defaults to the Directory page's working directory) into a per-case restart-configuration table, and write run_control.txt from it.

Includes a collapsible "What is a control file?" explainer.
Run — Launches the sweep script (aoa_sweep_v8.py or compatible) as a subprocess and streams its output live.
For long sweeps, running directly in a terminal (rather than through the GUI) is recommended so the run isn't tied to the app staying open.
Monitor — Live-refreshing residual plots read from SU2 history files.

Results — Consolidates a batch run's history files into a summary CSV and auto-plots CL/CD/moment.

Project Structure
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
Installation
Requirements
Python 3.7+
PyQt5
pandas
matplotlib
pip install -r aerosuite/requirements.txt
Running
Run the following python script in the terminal

python run_aerosuite.py
OR

The Aerosuite is added to source in the workstation. In the terminal:

su2aero2
Typical Workflow
Calculator

ISA and Y+ Calculator — enter altitude and Mach, click Transfer → values land in SU2 tab.
SU2 Project

Set a project directory and select the mesh.
Open CFG and complete the General or Aircraft Aero settings.
Generate one or more SU2 configuration files.
In Control File, scan the configuration folder and write run_control.txt.
In Run, choose the sweep script, configuration directory, and control file; load the plan and run it.
Convergence Monitor — select a history file while the sweep is running; plot auto-refreshes
Results Analysis — point at the run directory, select columns, consolidate and plot
Profile Save / Load
Use Profiles → Save SU2 Profile (Ctrl+S) to save all SU2 Generator settings to a JSON file.
Use Profiles → Load SU2 Profile (Ctrl+O) to restore them.

Future Plans
