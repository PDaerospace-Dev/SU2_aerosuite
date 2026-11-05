# Keeping a run-matrix workbook up to date

AeroSuite (the **Run matrix** page, or `aerosuite tracker sync`) fills in the **Status** column of a CFD run-matrix
sheet (the *CFD Simulation Run Matrix* template: Mach × altitude × AoA × elevator × sideslip, Run ID / Status / Notes
from row 5) from the projects' job records. It saves you from copying Running / Converged / Not Converged into the
sheet by hand.

## In the web UI

Open **Run matrix** from the Projects page (or the project menu in the top bar).

- **Run matrix** (`/tracker`) lists the linked sheets, grouped by workbook. Each row shows a bar of the statuses the
  sheet has now, how many statuses are waiting to be written, and how many of your verdicts the jobs disagree with.
  **Write** writes the waiting statuses. **Download** fetches the workbook. **Write automatically** turns automatic
  writing on or off for every sheet of that workbook.
- **Link a sheet** (`/tracker/link`) takes the workbook path and the sheet. It confirms the run matrix it found,
  lists the projects beside the workbook and your recent projects with their elevator deflection (read from the
  folder name, editable), and has the tag filters, the choice for disagreeing verdicts and automatic writing. The side
  panel counts what would be written as you change things. **Save and preview** opens the preview.
- **New sheet from template** (`/tracker/new`) adds a sheet for a new case to the workbook, copied from its template
  sheet (by default the last visible sheet whose name has "template", e.g. *Case Template_v1*). Tick the projects
  whose cases it tracks and the sweep fills itself from their cases (`configs/cases.json`, the cases their jobs ran,
  their run folders) and deflections; change any list. The case details are the template's column D (Case Name, mesh,
  S_ref, …; a start date defaults to today). **Create sheet** adds it as the workbook's last sheet, links it to the
  projects and opens its preview.
- **Preview** (`/tracker/preview?link=…`) has three tabs: **To write**, **Your verdicts kept** (with the convergence
  check's reason, and **Use the job's** per row or for all) and **Not in the sheet** (with the sweep value the sheet
  lacks). **Write N statuses** writes the changes plus the job verdicts you chose.
- **Coverage** (`/tracker/coverage?link=…`, the **Coverage** button on a sheet's row or the preview) colours every
  run by its Status, so gaps and problem areas show at a glance. A ring marks a run with a status waiting to be
  written. Choose the view at the top right:
  - **Panels**: one small grid per altitude and elevator deflection, AoA down and Mach across, with the converged
    count under each.
  - **Table**: one altitude at a time (a switch), AoA down and Mach across, each Mach split by elevator, with the
    converged share per row and per Mach.
  - **Pivot**: any two swept parameters as rows and columns. Each box gathers the runs that share that pair of
    values, as a bar and a converged count; this suits a large sheet.

  Click a run (or a pivot box) to list it below the view. The chips at the top switch to another linked sheet in
  the same view.

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
- **Tags**: `--tag 2nd_order` counts only jobs whose note contains `#2nd_order`. `--skip-tag 2nd_order` leaves those
  jobs out. Both can be repeated. A tag may start with a digit here, even though the Run page's tag list skips such
  tags.
- **Statuses**: CONVERGED → Converged, UNCONVERGED → Not Converged, FAILED → Failed, RUNNING → Running,
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
  a verdict, because the case is running again. Diverged is kept when a job says Not Converged or Failed.
- **Completed on.** Once every run has a verdict (Converged, Not Converged, Diverged or Failed), a blank
  Completed on cell gets the day the last of the runs' jobs ended. A date already there, typed by you, stays.
- **Everything else in the file.** Only the Status cells (and a blank Completed on) change. Notes, formulas, formatting, the dropdown, text
  boxes, add-ins and the SharePoint properties are copied byte for byte. Excel recalculates the scorecard when it
  opens the file.
- **A workbook open in Excel or LibreOffice.** If Excel's `~$` lock file or LibreOffice's `.~lock.<name>#` file sits
  next to the workbook, the sync stops and asks you to close it. Automatic writes try again once it is closed.

Each save keeps the previous file as `<name>.bak.xlsx` next to the workbook.

## Running it on a schedule

Keep the workbook where the server can see it (e.g. `$X/CFD_Run-Matrix_X07-80.xlsx`) and put the lines above in a
script for cron, e.g. every 30 minutes:

```bash
*/30 * * * * /data/cases/midhun/x07/sync_tracker.sh >> /data/cases/midhun/x07/sync_tracker.log 2>&1
```
