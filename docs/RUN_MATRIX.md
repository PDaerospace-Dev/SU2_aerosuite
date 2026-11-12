# Keeping a run-matrix workbook up to date

AeroSuite (the **Run matrix** page, or `aerosuite tracker sync`) fills in the **Status** column of a CFD run-matrix
sheet (the *CFD Simulation Run Matrix* template: Mach × altitude × AoA × elevator × sideslip, Run ID / Status / Notes
from row 5) from the projects' job records. It saves you from copying Running / Converged / Not Converged into the
sheet by hand.

## In the web UI

Open **Run matrix** from the top bar (or search for a sheet by name).

- **Run matrix** (`/tracker`) lists the linked sheets in two tabs, **Ongoing** and **Completed**, grouped by
  workbook. A sheet is completed once every run has a verdict (Converged, Not Converged, Diverged, Failed), or when
  you mark it so. Each row has the sheet's name over one line (its runs, the solver order and tags it takes, its
  projects) and a bar of the statuses the sheet has now: converged, not converged, failed or diverged (red), running
  or queued, hold; the colours are named once at the bottom of the page. A click on the row opens its coverage. A row
  says more only when something waits: **Write N** appears when N statuses are waiting to be written (automatic
  writing off, or the workbook open in Excel), an amber line counts your verdicts the jobs disagree with (click it
  to review them), and another counts the hand edits queued until the workbook is closed. The row's **⋮** menu has
  **Coverage**, **Preview a write**, **Change the link**, **Mark as completed** (or **Move to ongoing**) and **Remove
  from the run matrix** (the workbook stays as it is). The tiles at the top count the runs of every sheet: all,
  converged, not converged, failed or diverged, and your verdicts the jobs disagree with. **Download** fetches the
  workbook. **Write automatically** turns
  automatic writing on or off for every sheet of that workbook. **Recent writes**, at the bottom, opens with its
  chevron.
- **Link a sheet** (`/tracker/link`) takes the workbook path and the sheet. It confirms the run matrix it found,
  lists the projects beside the workbook and your recent projects with their elevator deflection (read from the
  folder name, editable), and has **Solver order**, the tag filters, the choice for disagreeing verdicts and automatic
  writing. The side panel counts what would be written as you change things. **Save and preview** opens the preview.
- **New sheet from template** (`/tracker/new`) adds a sheet for a new case to the workbook, copied from its template
  sheet (by default the last visible sheet whose name has "template", e.g. *Case Template_v1*). Tick the projects
  whose cases it tracks and the sweep fills itself from their cases (`configs/cases.json`, the cases their jobs ran,
  their run folders) and deflections; change any list. The case details are the template's column D (Case Name, mesh,
  S_ref, …; a start date defaults to today). **Create sheet** adds it as the workbook's last sheet, links it to the
  projects and opens its preview.
- **Preview** (`/tracker/preview?link=…`) has three tabs: **To write**, **Your verdicts kept** (with the convergence
  check's reason, and **Use the job's** per row or for all) and **Not in the sheet** (with the sweep value the sheet
  lacks). **Write N statuses** writes the changes plus the job verdicts you chose.
- **Coverage** (`/tracker/coverage?link=…`, the **Coverage** button at the top, which opens the first ongoing sheet,
  a sheet's **⋮** menu, or the preview) colours every
  run by its Status, so gaps and problem areas show at a glance. A ring marks a run with a status waiting to be
  written. Choose the view at the top right:
  - **Panels**: one small grid per altitude and elevator deflection, AoA down and Mach across, with the converged
    count under each.
  - **Table**: one altitude at a time (a switch), AoA down and Mach across, each Mach split by elevator, with the
    converged share per row and per Mach.
  - **Pivot**: any two swept parameters as rows and columns. Each box gathers the runs that share that pair of
    values, as a bar and a converged count; this suits a large sheet.

  The chips at the top switch to another linked sheet in the same view.

  **Editing by hand.** Click a run to open it below the view. Set its **Status in the sheet** (Converged, Not
  converged, Diverged, Failed, Hold or Blank) and its **Notes**. Beside them, **What the jobs say** shows the newest
  job's verdict, the convergence check's reason, the job and the case, with a link to Monitor. **Save** writes the two
  cells straight into the workbook. To change many runs at once, select them:
  - **Shift-click** (or Ctrl-click / ⌘-click) adds a run to the selection, or takes it out.
  - **Drag** across runs to select them all.
  - Click a **Mach** or **AoA** label to select that row or column.
  - Click a pivot box, then **Select these N**.

  A bar at the bottom then marks every selected run with one status, or adds a note to them all. A new note goes
  after the notes already there, unless you tick **Replace their notes**. Running and Pending can't be set by hand:
  only a job knows those.

  **While the workbook is open** in Excel or LibreOffice, an edit is *queued*: the run gets the ring, its card says
  **Queued** (with **Discard it**), and the Run matrix row counts the edits queued. The server writes them within
  20 s of the workbook being closed, before any automatic write. A cell you changed in Excel in the meantime is
  left as Excel has it; Recent writes says which queued edits were left out.

Links and the log of writes are kept in `$AEROSUITE_HOME/tracker.json`, so they are shared by everyone using this
server. With **Write automatically** on, the server checks every 20 s whether a linked project's job records (or the
workbook, or Excel's lock file) changed, and writes what is new. The first check after a link is saved, or after the
server starts, only takes note of where things stand, so nothing is written before you have seen the preview. A write
skipped because the workbook was open in Excel is tried again once Excel closes it. The web UI reads the job records
as they are, because the server's own pollers keep them current.

## From the command line

```bash
X=/data/cases/midhun/x07
BOOK=$X/CFD_Run-Matrix_X07-80.xlsx

aerosuite tracker sync $BOOK X07-80E_supersonic_1st $X/supersonic_del* --skip-tag 2nd_order --dry-run
aerosuite tracker sync $BOOK X07-80E_supersonic_1st $X/supersonic_del* --skip-tag 2nd_order
aerosuite tracker sync $BOOK X07-80E_subsonic_1st   $X/subsonic_del*   --skip-tag 2nd_order
aerosuite tracker sync $BOOK X07-80E_subsonic_2nd   $X/subsonic_del*   --tag 2nd_order
aerosuite tracker sync $BOOK X07-80E_subsonic_2nd   $X/subsonic_del*   --order 2nd   # from the configs, not the notes
```

A new sheet from the template, linked to the projects (the sweep from their cases unless given; `--detail` sets a
case detail by the start of its label):

```bash
aerosuite tracker new-sheet $BOOK X07-80E_transonic_1st $X/subsonic_del* --mach 0.9,1.1 --skip-tag 2nd_order \
    --detail "Case Name=Transonic sweep" --detail "Notes=1st order" --dry-run
```

- **Projects**: give one project folder per elevator deflection. The deflection comes from the folder name
  (`del0` → 0, `del20p` → +20, `del30m` / `del_60m` → −30 / −60). If a name doesn't carry it, write it as
  `FOLDER=DEGREES`, e.g. `$X/baseline=-30`.
- **Matching**: each sheet row is found from the sweep values entered in columns A–E (rows 25 on), in the order the
  sheet's formulas give: Mach changes slowest, then altitude, AoA, elevator and sideslip. A case's Mach, altitude,
  AoA and β come from `configs/cases.json`, or else from its name (`M2p0_25km_a15_del0`). Sideslip defaults to 0.
- **Which job**: the newest job that ran a case decides its status. A case that a newer job cancelled keeps the
  older job's result. **Hold** is written only when no job has a result for that case.
- **Solver order**: `--order 1st` or `--order 2nd` (**Solver order** on the link) counts only the cases a job ran
  at that order. It is read from the config the job kept for each case (`jobs/<id>/configs/<case>.cfg`):
  `MUSCL_FLOW= NO` is 1st order; `YES`, or no such line (SU2's default), is 2nd order. The note plays no part, so a
  forgotten or mistyped tag cannot put a run in the wrong sheet. Only a job that kept no config goes by its note:
  2nd order with `#2nd_order`, else 1st.
- **Tags**: `--tag fine` counts only jobs whose note contains `#fine`. `--skip-tag fine` leaves those jobs out. Both
  can be repeated, and they apply on top of the solver order. The `#` matters: a note that says `fine` without it has
  no tag (the Run page points this out for tags a sheet filters on).
- **Statuses**: CONVERGED → Converged, UNCONVERGED → Not Converged, FAILED → Failed, or **Diverged** when the
  case's output ends with SU2's divergence message (NaN detected); RUNNING → Running,
  PENDING → Pending, CANCELLED / BLOCKED → Hold. A running job's state is refreshed first, as `aerosuite status`
  does.

## A new sheet from the template

The template sheet is copied inside the file, as Excel's *Move or Copy… › Create a copy* would: its formulas, Status
dropdown, colours, merged cells and its text box come along. The copy gets the case details and the sweep values
(at most 100 per parameter, and no more runs than the template has rows for), and an empty Status column. The other
sheets and every other part of the file are left byte for byte, as for a write; the workbook is refused while open in
Excel, and the previous file is kept as `<name>.bak.xlsx`. The new sheet's name must suit Excel: at most 31
characters, none of `: \ / ? * [ ]`, and not one the workbook has.

## What it leaves alone

- **Your verdicts.** If the sheet already says Converged, Not Converged, Diverged or Failed and the job's verdict
  differs, the sheet keeps yours. AeroSuite's convergence check (CL, CD, CMy steady over the last 10%) is stricter
  than a look at the history, for example when CMy is close to zero. The summary line counts these rows, and
  `--dry-run` lists each one. `--overwrite` lets the job's verdict replace them. Running and Pending always replace
  a verdict, because the case is running again. Diverged is kept when a job says Not Converged or Failed, and a
  Failed in the sheet becomes Diverged when the job says so (the same failure, said more exactly).
- **Completed on.** Once every run has a verdict (Converged, Not Converged, Diverged or Failed), a blank
  Completed on cell gets the day the last of the runs' jobs ended. A date already there, typed by you, stays.
- **What you set on the coverage page.** A verdict you set there is kept, just like one typed in Excel. Hold or
  Blank is not a verdict, so the next write fills it from the jobs if one has run that case.
- **Everything else in the file.** A sync changes only the Status cells (and a blank Completed on). An edit on the
  coverage page changes only the Status and Notes cells of its runs, and refuses a Notes cell that holds a formula.
  Formulas, formatting, the dropdown, text boxes, add-ins and the SharePoint properties are copied byte for byte. Excel recalculates the scorecard when it
  opens the file.
- **A workbook open in Excel or LibreOffice.** If Excel's `~$` lock file or LibreOffice's `.~lock.<name>#` file sits
  next to the workbook, the sync stops and asks you to close it. Automatic writes try again once it is closed.

Each save keeps the previous file as `<name>.bak.xlsx` next to the workbook. The first save of a day also keeps the
workbook as it was in `<name>.backups/<name>.<date>.xlsx`, and the newest 7 of those stay: a week to go back over,
which the one-write-old `.bak` cannot give with automatic writes. The clock icon beside **Download** lists them.

**The links file.** `tracker.json` is changed under a lock that the server and the `aerosuite` command both take, and
the file before each save is kept as `tracker.json.bak`. A `tracker.json` that cannot be read is reported (on the Run
matrix page, and by the command) and left alone: it is never treated as "no links" and saved over.

## Running it on a schedule

Keep the workbook where the server can see it (e.g. `$X/CFD_Run-Matrix_X07-80.xlsx`) and put the lines above in a
script for cron, e.g. every 30 minutes:

```bash
*/30 * * * * /data/cases/midhun/x07/sync_tracker.sh >> /data/cases/midhun/x07/sync_tracker.log 2>&1
```
