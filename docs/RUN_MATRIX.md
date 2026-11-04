# Keeping a run-matrix workbook up to date

`aerosuite tracker sync` fills in the **Status** column of a CFD run-matrix sheet (the *CFD Simulation Run Matrix*
template: Mach × altitude × AoA × elevator × sideslip, Run ID / Status / Notes from row 5) from the projects' job
records. It saves you from copying Running / Converged / Not Converged into the sheet by hand.

```bash
X=/data/cases/midhun/x07
BOOK=$X/CFD_Run-Matrix_X07-80.xlsx

aerosuite tracker sync $BOOK X07-80E_supersonic_1st $X/supersonic_del* --skip-tag 2nd_order --dry-run
aerosuite tracker sync $BOOK X07-80E_supersonic_1st $X/supersonic_del* --skip-tag 2nd_order
aerosuite tracker sync $BOOK X07-80E_subsonic_1st   $X/subsonic_del*   --skip-tag 2nd_order
aerosuite tracker sync $BOOK X07-80E_subsonic_2nd   $X/subsonic_del*   --tag 2nd_order
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

## What it leaves alone

- **Your verdicts.** If the sheet already says Converged, Not Converged, Diverged or Failed and the job's verdict
  differs, the sheet keeps yours. AeroSuite's convergence check (CL, CD, CMy steady over the last 10%) is stricter
  than a look at the history, for example when CMy is close to zero. The summary line counts these rows, and
  `--dry-run` lists each one. `--overwrite` lets the job's verdict replace them. Running and Pending always replace
  a verdict, because the case is running again. Diverged is kept when a job says Not Converged or Failed.
- **Everything else in the file.** Only the Status cells change. Notes, formulas, formatting, the dropdown, text
  boxes, add-ins and the SharePoint properties are copied byte for byte. Excel recalculates the scorecard when it
  opens the file.
- **A workbook open in Excel.** If Excel's `~$` lock file sits next to the workbook, the sync stops and asks you to
  close it.

Each save keeps the previous file as `<name>.bak.xlsx` next to the workbook.

## Running it on a schedule

Keep the workbook where the server can see it (e.g. `$X/CFD_Run-Matrix_X07-80.xlsx`) and put the lines above in a
script for cron, e.g. every 30 minutes:

```bash
*/30 * * * * /data/cases/midhun/x07/sync_tracker.sh >> /data/cases/midhun/x07/sync_tracker.log 2>&1
```
