# Rayher Frappe PoC Runbook

## What This PoC Proves

This PoC proves the R&D cost allocation chain:

Employee -> Project -> Timesheet -> RD Expense Import -> RD Cost Allocation -> RD Allocation Matrix.

Payroll is not calculated in this PoC. Payroll remains in the finance system; this app provides HR records, R&D timesheet evidence, GL import, allocation snapshots, and reporting.

## Demo Scenario

The demo scenario uses period `202601`:

- GL amount: `1200.00`
- `RD-CAP`: 60% of R&D project hours, capitalized in 2026
- `RD-EXP`: 40% of R&D project hours, expensed
- Expected capitalized subtotal: `720.00`
- Expected expensed subtotal: `480.00`

Run after the app is installed on a Frappe site:

```bash
cd ~/frappe-bench
bench --site rayher.localhost execute rayher_hr_payroll.demo.create_demo_data
```

Then open the generated `RD Cost Allocation` document and verify:

```text
RD-CAP allocated amount = 720.00
RD-EXP allocated amount = 480.00
capitalized_total = 720.00
expensed_total = 480.00
```

Open `RD Allocation Matrix` and confirm it shows the same amounts by voucher and project.

## Key Controls

- Capitalized / expensed filtering is a subtotal view, not denominator recalculation.
- Allocation stores source Timesheet rows and source GL rows as snapshots.
- Submitted allocation versions should not be overwritten; corrections create a new version.
- `source_row_key` is used to reject duplicate GL rows inside an import batch.
- R&D period lock blocks Timesheet save, submit, cancel, delete, and amend paths through server hooks.
- Compensatory leave for statutory holidays is blocked by server validation.
- Project-owner review routing is custom app logic, not native Frappe routing.
- Historical department/designation for snapshots comes from `Employee Internal Work History`, with live employee fields only as fallback.

## Local Verification

Repo-level verification currently passes without a running bench:

```bash
python -m pytest rayher_hr_payroll/tests -q
```

Expected result at the time of writing:

```text
30 passed
```

Bench-level verification on the local WSL bench:

```bash
cd /home/rayher/frappe-bench
bench --site rayher.localhost migrate
bench --site rayher.localhost execute rayher_hr_payroll.demo.create_demo_data
```

Verified on 2026-06-16 after switching WSL networking to NAT and disabling WSL auto proxy. Local bench path is `/home/rayher/frappe-bench`; site is `rayher.localhost`; administrator password is `admin`.

Latest verified demo allocation:

```text
RD-CAP  capitalized  60%  720.00
RD-EXP  expensed     40%  480.00
capitalized_total = 720.00
expensed_total = 480.00
total = 1200.00
```
