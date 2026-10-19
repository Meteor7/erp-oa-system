# QIHENG DEMO Account Domain and Timesheet Limit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate every approved QIHENG Demo business login to `@staff.example.invalid`, preserve all account and approval relationships, and enforce/display employee monthly workday and hour limits from the ERP holiday calendar.

**Architecture:** Add an idempotent account-domain maintenance module that preflights User rename collisions and repairs OA JSON/text references after Frappe renames. Add a focused working-calendar module that resolves employee/company Holiday Lists with a weekday fallback, then make the monthly timesheet API and Vue page consume the same limit. Deploy only reviewed commits, run a live backup and dry run before mutation, and regenerate credential workbooks after login verification.

**Tech Stack:** Frappe/ERPNext Python APIs, MariaDB, pytest, Vue 3, frappe-ui, Vitest/Node source tests, Docker bench, `@oai/artifact-tool` for `.xlsx` delivery.

## Global Constraints

- Rename all current `@legacy.example.invalid` Users and `admin@legacy-business.example.invalid` to the same local part at `@staff.example.invalid`.
- Keep existing `@business.example.invalid`, `Administrator`, `Guest`, `rayher.localhost`, Docker names, app/package names, and repository names unchanged.
- Preserve passwords for the nine `@legacy.example.invalid` Users; assign one new random strong password only to the renamed management account.
- Passwords must never enter Git, shell logs, test output, or chat; only final credential workbooks may contain them.
- Monthly day limit comes from Employee Holiday List, then Company Default Holiday List, then Monday-Friday fallback; hours equal days times 8.
- Do not adjust limits for leave, joining/leaving dates, or shifts in this implementation.
- Use TipRay-safe writers and verify generated shared files start with the plaintext `PK` ZIP header, not a TSD header.

---

### Task 1: Account-domain migration module

**Files:**
- Create: `rayher_hr_payroll/maintenance/account_domain_migration.py`
- Create: `rayher_hr_payroll/tests/test_account_domain_migration.py`
- Modify: `rayher_hr_payroll/maintenance/business_account_bootstrap.py`
- Modify: `rayher_hr_payroll/maintenance/user_account_migration.py`
- Modify: `rayher_hr_payroll/tests/test_business_account_bootstrap.py`
- Modify: `rayher_hr_payroll/tests/test_user_account_migration.py`

**Interfaces:**
- Produces: `build_domain_mappings(user_ids: Iterable[str]) -> list[dict]`.
- Produces: `plan_account_domain_migration() -> dict` with `mappings`, `collisions`, and `old_reference_counts`.
- Produces: `migrate_account_domains(dry_run: bool = True, management_password: str | None = None) -> dict`.
- Produces: `replace_exact_user_ids(value: str, mapping: dict[str, str]) -> str` for JSON/text OA fields.

- [ ] **Step 1: Write failing pure-function and preflight tests**

```python
def test_build_domain_mappings_only_targets_approved_old_domains():
    rows = build_domain_mappings([
        "person067@legacy.example.invalid",
        "admin@legacy-business.example.invalid",
        "person046@business.example.invalid",
        "Administrator",
    ])
    assert rows == [
        {"old_user": "admin@legacy-business.example.invalid", "new_user": "admin@staff.example.invalid", "management": True},
        {"old_user": "person067@legacy.example.invalid", "new_user": "person067@staff.example.invalid", "management": False},
    ]


def test_exact_reference_replacement_handles_json_without_partial_matches():
    mapping = {"person067@legacy.example.invalid": "person067@staff.example.invalid"}
    assert json.loads(replace_exact_user_ids('["person067@legacy.example.invalid"]', mapping)) == ["person067@staff.example.invalid"]
    assert replace_exact_user_ids("person045@legacy.example.invalid", mapping) == "person045@legacy.example.invalid"
```

- [ ] **Step 2: Run tests and verify the new module is missing**

Run: `pytest -q rayher_hr_payroll/tests/test_account_domain_migration.py rayher_hr_payroll/tests/test_business_account_bootstrap.py rayher_hr_payroll/tests/test_user_account_migration.py`

Expected: FAIL because `account_domain_migration` and PLANCK internal-domain constants do not exist.

- [ ] **Step 3: Implement deterministic mapping, collision preflight, framework rename, and OA reference repair**

```python
OLD_LOCAL_DOMAIN = "legacy.example.invalid"
TARGET_LOCAL_DOMAIN = "staff.example.invalid"
LEGACY_MANAGEMENT_USER = "admin@legacy-business.example.invalid"
TARGET_MANAGEMENT_USER = "admin@staff.example.invalid"

def build_domain_mappings(user_ids):
    mappings = []
    for raw in sorted({str(value).strip().lower() for value in user_ids or []}):
        if raw == LEGACY_MANAGEMENT_USER:
            mappings.append({"old_user": raw, "new_user": TARGET_MANAGEMENT_USER, "management": True})
        elif raw.endswith("@" + OLD_LOCAL_DOMAIN):
            local = raw[: -len(OLD_LOCAL_DOMAIN) - 1]
            mappings.append({"old_user": raw, "new_user": f"{local}@{TARGET_LOCAL_DOMAIN}", "management": False})
    return mappings
```

Implement `plan_account_domain_migration()` by reading matching User rows, rejecting existing target Users, snapshotting Employee links and OA reference counts, and returning no passwords. Implement apply mode with a database savepoint, `frappe.rename_doc("User", old, new, force=True, show_alert=False)`, exact JSON/text replacement for `OA Approval Step.approvers`, `OA Approval Step.approved_by`, and `OA Approval Request.paid_by`, management `update_password`, postconditions, commit, and rollback on any exception.

Update `ACCOUNT_SPECS`, `USER_DOMAIN`, generated-user regexes, and production expectations to `staff.example.invalid`; keep `person046@business.example.invalid` unchanged.

- [ ] **Step 4: Run focused tests**

Run: `pytest -q rayher_hr_payroll/tests/test_account_domain_migration.py rayher_hr_payroll/tests/test_business_account_bootstrap.py rayher_hr_payroll/tests/test_user_account_migration.py rayher_hr_payroll/tests/test_oa_routing_diagnostics.py rayher_hr_payroll/tests/test_oa_organization.py rayher_hr_payroll/tests/test_oa_approval_routes.py`

Expected: PASS.

- [ ] **Step 5: Commit account migration implementation**

```bash
git add rayher_hr_payroll/maintenance/account_domain_migration.py rayher_hr_payroll/maintenance/business_account_bootstrap.py rayher_hr_payroll/maintenance/user_account_migration.py rayher_hr_payroll/tests/test_account_domain_migration.py rayher_hr_payroll/tests/test_business_account_bootstrap.py rayher_hr_payroll/tests/test_user_account_migration.py rayher_hr_payroll/tests/test_oa_routing_diagnostics.py rayher_hr_payroll/tests/test_oa_organization.py rayher_hr_payroll/tests/test_oa_approval_routes.py
git commit -m "feat(accounts): migrate internal users to planck domain"
```

### Task 2: Holiday-calendar work-limit service

**Files:**
- Create: `rayher_hr_payroll/working_calendar.py`
- Create: `rayher_hr_payroll/tests/test_working_calendar.py`

**Interfaces:**
- Produces: `count_work_dates(year: int, month: int, holiday_dates: Iterable[date] | None) -> list[date]`.
- Produces: `resolve_monthly_work_limit(year: int, month: int, employee: str | None = None, company: str | None = None) -> dict` returning `day_limit`, `hour_limit`, `calendar_source`, `holiday_list`, and internal `work_dates`.

- [ ] **Step 1: Write failing calendar tests**

```python
def test_holiday_list_excludes_listed_dates_and_keeps_makeup_saturday():
    holidays = {date(2026, 7, 4), date(2026, 7, 5), date(2026, 7, 12)}
    work_dates = count_work_dates(2026, 7, holidays)
    assert date(2026, 7, 11) in work_dates
    assert date(2026, 7, 12) not in work_dates


def test_weekday_fallback_excludes_saturday_and_sunday():
    work_dates = count_work_dates(2026, 7, None)
    assert all(value.weekday() < 5 for value in work_dates)
```

Add resolver tests for Employee Holiday List priority, Company Default Holiday List fallback, incomplete/out-of-range list fallback, and `hour_limit == day_limit * 8`.

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest -q rayher_hr_payroll/tests/test_working_calendar.py`

Expected: FAIL because `working_calendar.py` does not exist.

- [ ] **Step 3: Implement the focused calendar resolver**

```python
HOURS_PER_WORKDAY = 8

def count_work_dates(year, month, holiday_dates):
    dates = [date(year, month, day) for day in range(1, monthrange(year, month)[1] + 1)]
    if holiday_dates is None:
        return [value for value in dates if value.weekday() < 5]
    excluded = {getdate(value) for value in holiday_dates}
    return [value for value in dates if value not in excluded]
```

Resolve `Employee.holiday_list` before `Company.default_holiday_list`; only accept a Holiday List whose `from_date` and `to_date` cover the full selected month. Read child `Holiday.holiday_date` rows for that parent. Return `weekday_fallback` with an empty `holiday_list` when no complete list is available.

- [ ] **Step 4: Run calendar tests**

Run: `pytest -q rayher_hr_payroll/tests/test_working_calendar.py`

Expected: PASS.

- [ ] **Step 5: Commit calendar service**

```bash
git add rayher_hr_payroll/working_calendar.py rayher_hr_payroll/tests/test_working_calendar.py
git commit -m "feat(timesheet): calculate monthly workday limits"
```

### Task 3: Enforce workday limits in monthly timesheet API

**Files:**
- Modify: `rayher_hr_payroll/api/monthly_timesheet_entry.py`
- Modify: `rayher_hr_payroll/tests/test_monthly_timesheet_entry.py`

**Interfaces:**
- Consumes: `resolve_monthly_work_limit(...)` from Task 2.
- Changes: `prepare_monthly_rows(..., day_limit: Decimal)` requires the resolved limit.
- Changes: `build_technical_time_logs(..., work_dates: list[date])` allocates technical logs only onto eligible work dates.
- Produces API fields: `day_limit`, `hour_limit`, `calendar_source`, `holiday_list`.

- [ ] **Step 1: Replace natural-day test expectations with failing workday-limit tests**

```python
def test_prepare_monthly_rows_rejects_total_above_resolved_workday_limit(monthly_module):
    mod, _ = monthly_module
    with pytest.raises(RuleError):
        mod.prepare_monthly_rows(rows_for_days("20.01"), 2026, 7, resolve, Decimal("20.00"))


def test_list_monthly_entries_returns_workday_and_hour_limits(monthly_module, monkeypatch):
    monkeypatch.setattr(mod, "resolve_monthly_work_limit", lambda **kwargs: {
        "day_limit": 22, "hour_limit": 176, "calendar_source": "company_holiday_list", "holiday_list": "2026 Company Holidays", "work_dates": [],
    })
    result = mod.list_monthly_entries("2026-07", employee="EMP-1")
    assert result["day_limit"] == 22
    assert result["hour_limit"] == 176
```

Add equality-at-limit success, above-limit rejection in `save_monthly_entries`, and technical-log allocation skipping excluded dates.

- [ ] **Step 2: Run focused API tests and verify old natural-day behavior fails**

Run: `pytest -q rayher_hr_payroll/tests/test_monthly_timesheet_entry.py`

Expected: FAIL on missing resolver fields/signatures and old `31`-day expectation.

- [ ] **Step 3: Wire the calendar service through list, save, preparation, and technical-log allocation**

Resolve the limit server-side for every list/save request. Pass `Decimal(str(limit["day_limit"]))` into preparation, pass `limit["work_dates"]` to log generation, and expose only serializable fields to the response. Do not accept limit values from the client.

- [ ] **Step 4: Run API and adjacent timesheet tests**

Run: `pytest -q rayher_hr_payroll/tests/test_monthly_timesheet_entry.py rayher_hr_payroll/tests/test_timesheet_entry.py rayher_hr_payroll/tests/test_timesheet_controls.py`

Expected: PASS.

- [ ] **Step 5: Commit API enforcement**

```bash
git add rayher_hr_payroll/api/monthly_timesheet_entry.py rayher_hr_payroll/tests/test_monthly_timesheet_entry.py
git commit -m "feat(timesheet): enforce holiday-calendar monthly limits"
```

### Task 4: Display limits and fallback notice in the Vue page

**Files:**
- Modify: `frontend/src/pages/TimesheetEntry.vue`
- Modify: `frontend/tests/timesheet-entry-source.test.js`

**Interfaces:**
- Consumes API fields from Task 3.
- Produces visible text `本月上限：X 天 / Y 小时` and fallback message `未配置假日表，当前按周一至周五计算`.

- [ ] **Step 1: Add failing source assertions**

```javascript
assert.match(source, /hour_limit/)
assert.match(source, /本月上限/)
assert.match(source, /未配置假日表，当前按周一至周五计算/)
assert.match(source, /calendar_source/)
```

- [ ] **Step 2: Run frontend test and verify failure**

Run: `npm --prefix frontend test -- --run tests/timesheet-entry-source.test.js`

Expected: FAIL because the page only renders a natural-day limit.

- [ ] **Step 3: Implement computed values and concise page copy**

Add `hourLimit`, `calendarSource`, and `usesWeekdayFallback` computed values. Replace the current suffix with a standalone display of both day and hour limits when one employee is selected; show the fallback notice beneath the header only when `calendar_source === "weekday_fallback"`. Keep the all-employees view read-only without comparing its aggregate to a single-person limit.

- [ ] **Step 4: Run source tests and production build**

Run: `npm --prefix frontend test -- --run tests/timesheet-entry-source.test.js tests/timesheet-import.test.js`

Run: `npm --prefix frontend run build`

Expected: tests PASS and Vite build succeeds.

- [ ] **Step 5: Commit frontend display**

```bash
git add frontend/src/pages/TimesheetEntry.vue frontend/tests/timesheet-entry-source.test.js rayher_hr_payroll/public/frontend
git commit -m "feat(frontend): show monthly workday and hour limits"
```

### Task 5: Full regression and reviewed deployment artifact

**Files:**
- Modify only if failures reveal in-scope regressions.

**Interfaces:**
- Consumes all code from Tasks 1-4.
- Produces one reviewed Git SHA for Docker deployment.

- [ ] **Step 1: Run backend regression suite**

Run: `pytest -q rayher_hr_payroll/tests`

Expected: PASS.

- [ ] **Step 2: Run frontend regression suite**

Run from `frontend`: `npm test -- --run`

Expected: PASS.

- [ ] **Step 3: Verify diff hygiene and plaintext files**

Run: `git diff --check && git status --short`

Verify every changed source begins as readable plaintext and no output contains a TipRay `%TSD-Header` marker.

- [ ] **Step 4: Record deploy SHA and commit any test-only corrections**

Run: `git rev-parse HEAD`

Expected: one clean, immutable SHA and no uncommitted tracked changes.

### Task 6: Backup, deploy, migrate live accounts, and verify

**Files:**
- Runtime: Docker app at `/workspace/development/frappe-bench/apps/rayher_hr_payroll`
- Runtime: site `rayher.localhost`
- Output: `D:/rayher/outputs/planck-credentials-20260729/PLANCK_SEMICON_管理账号_2026-07-29.xlsx`
- Output: `D:/rayher/outputs/planck-credentials-20260729/PLANCK_SEMICON_全体账号密码_2026-07-29.xlsx`
- Output: eight supervisor workbooks under `D:/rayher/outputs/planck-credentials-by-supervisor-20260729/`

**Interfaces:**
- Consumes: reviewed SHA, migration dry run, existing credential passwords, and supervisor routing diagnostics.
- Produces: migrated live accounts, deployed UI/API, verified login/approval/timesheet behavior, and plaintext credential workbooks.

- [ ] **Step 1: Create and verify a live backup**

Run `bench --site rayher.localhost backup --with-files --compress`, copy the exact database/files backup and `site_config.json` to a timestamped host backup directory, and verify every archive exists and is non-empty.

- [ ] **Step 2: Deploy the exact reviewed source and build**

Copy only the reviewed Git state to the Docker app, run `bench --site rayher.localhost migrate`, `bench build --app rayher_hr_payroll`, clear site/website cache, and restart required bench processes. Verify deployed app files match the recorded Git SHA/content hashes.

- [ ] **Step 3: Run account migration dry run**

Run: `bench --site rayher.localhost execute rayher_hr_payroll.maintenance.account_domain_migration.migrate_account_domains --kwargs '{"dry_run": true}'`

Expected: exactly 10 mappings, zero collisions, nine Employee links, and no mutation.

- [ ] **Step 4: Generate the management password outside Git and apply migration once**

Generate a cryptographically random password, keep it only in a protected temporary credential artifact, invoke apply mode without printing the password, and verify the transaction reports 10 renamed accounts with zero stale OA references.

- [ ] **Step 5: Verify login and business links**

Authenticate all nine renamed users with their preserved passwords and the management user with its new password without logging secrets. Verify old-domain login attempts fail. Run OA routing diagnostics and assert zero errors; query Employee, roles, User Permission, Project owner, pending OA steps, historical approved-by fields, and paid-by fields for stale old-domain references.

- [ ] **Step 6: Verify monthly work limits live**

For a selected month with a configured Holiday List, compare API `day_limit` to the list’s holiday dates and confirm `hour_limit = day_limit * 8`. Verify equal-limit save succeeds in an isolated reversible test record, over-limit save is rejected, and remove the test record. Verify fallback behavior against a controlled employee/company without a complete list only if it can be done without changing production HR settings; otherwise cover fallback with automated tests.

- [ ] **Step 7: Generate and visually verify credential workbooks**

Use `@oai/artifact-tool` to regenerate the management-only, all-account, and eight supervisor workbooks with QIHENG DEMO titles and new login IDs. Inspect key ranges, scan formula errors, render every sheet for visual QA, and verify each final `.xlsx` starts with `PK` and not a TipRay TSD header.

- [ ] **Step 8: Browser QA**

Open the live app using the existing authenticated browser session. Verify the timesheet page shows correct Chinese text, `本月上限：X 天 / Y 小时`, fallback copy only when applicable, no console errors, and no clipped header layout at desktop width.

- [ ] **Step 9: Push the reviewed commits and update PR #24**

Push `feat/ocr-monthly-timesheet-integration`, confirm the remote SHA matches the deployed SHA, and report the PR URL plus exact verification evidence.