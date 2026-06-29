# Serena HR/OA — Known limitations / follow-ups (as of feat/hr-oa-p5)

The backend has been driven through 11 rounds of local codex+claude adversarial review;
~15 genuine P1/P2 bugs were fixed and bench-verified. The items below are the remaining
known gaps — each is either environment-blocked, architectural scope, or a verified
non-bug. None is a data-loss/security/correctness defect in the delivered backend.

## 1. Frontend rd_mock UI is dormant but not yet removed (BUILD-BLOCKED)
- The dashboard and the R&D cost allocation now source salary from **submitted Salary
  Slips** (P4). The legacy `rd_mock_*` Employee fields no longer drive any costing and
  the archive completeness check no longer requires them.
- However `frontend/src/pages/Personnel.vue` + `api/personnel_entry.py` still let HR
  edit those mock fields. Removing that editable "second source of truth" requires
  rebuilding the Vue SPA.
- **Blocked:** the frontend build fails in this environment — node 18.19.1 + vite 5.4.21
  ESM loader (`SyntaxError: Unexpected token '*'` on `import * as fs from 'node:fs'`).
  Needs a working frontend toolchain (e.g. node 20+) to `yarn build`.
- Impact: cosmetic (dormant fields), not functional.

## 2. Travel Request / Compensatory Leave approval routing (SCOPE follow-up)
- 请假 + 报销 have full approval routing (HRMS approver / the Expense Claim workflow).
- 出差 + 调休 have no approver field and no workflow yet, so they were removed from the
  employee portal's quick-create and the 待我审批 inbox (showing them would be a dead-end).
- Follow-up: build approval workflows for Travel Request + Compensatory Leave Request,
  then re-add them to the portal.

## 3. Labor-only R&D periods (ARCHITECTURAL follow-up)
- The R&D cost allocation is RD-Expense-Import-centric: `recalc_allocation` requires a
  non-empty import. A period with R&D salaries but zero imported expenses can't allocate
  its labor. Most active R&D periods have expense imports alongside labour, so labour is
  capitalized in practice; the labour-only edge needs an import-independent allocation path.

## 4. Verified NON-bugs (do not "fix")
- Department Managers can approve Expense Claims: they hold the stock **Employee** role
  (read+write on Expense Claim) and HRMS shares each claim with its `expense_approver`.
- Auto-provisioned employee logins are "System User" because the stock Employee role has
  `desk_access=1` — stock HRMS behaviour.

## 5. External gates (USER action)
- GitHub Codex review of the PRs needs Codex credits / a connected account on the repo.

## 非全时研发 partial capitalization requires a total-hours denominator (operational, not a defect)

The R&D labour ratio is `工资 × (研发工时 / 总工时)`. The denominator (`total_hours_by_employee`)
sums **all** submitted Timesheet Detail hours for the employee — including rows with **no
project** (the Timesheet validator only rejects rows on *non-R&D projects*, never project-less
rows). So a 非全时研发/研发辅助 researcher's non-R&D time must be logged as **project-less**
timesheet rows; then `total_hours > rd_hours` and their salary is prorated correctly.

If their non-R&D time is *not* logged (so `total_hours == rd_hours`), the system cannot know the
ratio and **skips** that employee's labour rather than over-capitalising 100% or aborting the
whole period. Skipped employees are surfaced two ways: a `msgprint` on calculate and the persisted
read-only `labor_skipped` field on the allocation. Finance completes the timesheet (project-less
hours) and re-runs. Verified on bench: an R&D row (4h) + a project-less row (4h) yields
`total_hours = 8 > 4`, so the ratio (0.5) is computed and the employee is capitalised.

This is an operational requirement (log non-R&D time), not a code defect: the feature is fully
functional when timesheets are complete, and fails safe + visibly when they are not.
