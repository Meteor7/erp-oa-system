# OA Expense Approval and Organization Routing Design

Date: 2026-07-27
Branch: `feat/ocr-monthly-timesheet-integration`
Status: user-approved design

## 1. Objective

Replace the incomplete expense approval route with the confirmed six-stage route, connect every approval node to a real enabled User, and derive the direct-supervisor decision from the supplied organization chart without turning the chart's employee lists into artificial reporting chains.

The implementation must preserve the currently working invoice OCR, reimbursement workbench, private attachments, audit history, and dynamic approval features. Docker remains the local deployment and acceptance environment; the clean PR worktree remains the source of truth.

## 2. Source-of-truth and synchronization

The PR #24 head worktree is the implementation baseline. Before changing behavior, recover the valid Docker-only OA fixes into that worktree:

- Ren Feifan as the non-electronic fixed-asset approver;
- corrected Ren Feifan, Li Qinggele, and Wang Yansong account mappings;
- `Rayher Business Executive` invoice visibility;
- current OA API Chinese text and authorized expense-line serialization fixes.

Do not copy the older PR OA files over Docker. After the recovered fixes and new route pass tests, deploy the exact worktree state to Docker, run migration and acceptance checks, then commit and push the final verified state to PR #24. Finally, make Docker run the exact PR commit instead of an old `main` checkout plus copied files.

## 3. Canonical identities

Approval route data stores stable User IDs. Chinese names are display labels only.

| Responsibility | Employee | User |
| --- | --- | --- |
| Finance audit and final payment confirmation | Ye Liwei / 演示员工13 | `person067@legacy.example.invalid` |
| Non-electronic fixed assets | Ren Feifan / 演示员工10 | `person047@legacy.example.invalid` |
| Electronic fixed assets | Yi Jiawei / 演示员工18 | `person068@legacy.example.invalid` |
| Finance manager | Zhang Meng / 演示员工16 | `person072@legacy.example.invalid` |
| Vice General Manager | Li Qinggele / 演示员工21 / 演示员工37 | `person046@business.example.invalid` |
| General Manager | Wang Yansong / 演示员工29 / 演示员工28 | `person060@legacy.example.invalid` |

Wang Bo is an alias for Wang Yansong. Qing Bo is an alias for Li Qinggele. Route generation and migration normalize those legacy names to the canonical identities above.

## 4. Organization interpretation

### 4.1 Department supervisors, not employee chains

The organization chart is interpreted by department or team ownership:

- all ordinary members in a leaf team report to that team's named supervisor;
- names listed vertically under the same team are peers, not a chain;
- a team supervisor reports to the parent department supervisor;
- only department levels are traversed upward.

Examples:

- all `Software-12` members report directly to Jun Zhang / 演示员工132;
- all `Algorithm-10` members report directly to Xi He / 演示员工108;
- Ye Liwei and Yan Luying report directly to Zhang Meng;
- HR and Admin members report directly to Ren Feifan.

### 4.2 Non-participating managers and top executives

Philippe and Sabri remain organization nodes but never receive accounts or approval steps.

When resolving the stage-two direct-supervisor decision:

1. Start with the applicant's department supervisor.
2. If that supervisor is Philippe, Sabri, otherwise excluded, or has no enabled linked User, move to the parent department supervisor.
3. If the first eligible result is Li Qinggele or Wang Yansong, add no stage-two supervisor step.
4. If the first eligible result is another enabled linked User, add exactly one stage-two supervisor step for that User.
5. Never infer a chain from the visual ordering of employee names.

The BU branches under Sabri connect upward to Li Qinggele and Wang Yansong for this decision, so their stage-two supervisor step is skipped.

Example for Jun Zhang:

`Jun Zhang -> Philippe -> Li Qinggele / Wang Yansong`

Philippe is bypassed. Reaching Li Qinggele or Wang Yansong causes stage two to be skipped. Jun Zhang still participates later in the department-based executive stage only according to the applicant's department.

Example for a Software team member:

`Software employee -> Jun Zhang`

Jun Zhang has an enabled linked User and is not Li Qinggele or Wang Yansong, so stage two contains Jun Zhang.

## 5. Canonical expense route

### Stage 1: Finance audit and expense classification

Every submitted expense request starts with Ye Liwei.

- Ye Liwei can select or replace the expense item for every expense line.
- Approval is blocked until every line has a valid expense item.
- The selected expense items remain visible and read-only at later stages.

### Stage 2: Direct-supervisor decision

Resolve the organization chain using section 4.

- Result is Li Qinggele or Wang Yansong: skip this stage.
- Result is another enabled linked supervisor: add one approval step.
- Excluded or accountless supervisors are never free-text approvers and never block the route when a parent department supervisor exists.

### Stage 3: Single asset-type decision

After invoice recognition and before submission, the applicant must select exactly one asset type for the whole reimbursement request:

1. `非电子类固定资产（人事/行政）` -> Ren Feifan approval;
2. `电子类固定资产（IT）` -> Yi Jiawei approval;
3. `其他` -> no asset-specialist step.

`其他` includes non-fixed-asset reimbursement and consumables, such as taxi fares and tissues. The field is a required single-select control, never a multi-select.

### Stage 4: Finance manager

Every request goes to Zhang Meng after the asset decision, including a request submitted by Zhang Meng.

### Stage 5: Department executive approval

Department classification uses the applicant's Employee department:

- Finance department -> Wang Yansong;
- Sales department -> Li Qinggele and Wang Yansong in an `all` co-sign step;
- all other departments -> Li Qinggele, then Wang Yansong as two sequential steps.

Both `客服部` and `客户服务部` are classified as Sales. Co-sign requires both assigned users to approve in any order. An applicant who is also an approver must approve their own node; self-approval is not automatically skipped.

### Stage 6: Final payment confirmation

After all approval nodes complete, the request returns to Ye Liwei in a distinct `handle` step. Ye Liwei must click the explicit confirmation action to complete payment handling. Merely opening the request or completing Stage 1 must not complete Stage 6.

## 6. Route snapshot and migration

The generated route is stored as a request-specific approval-step snapshot. Later organization changes do not silently rewrite an already submitted request.

Only unresolved steps of active requests may be migrated. Completed actions, actor history, expense lines, invoices, attachments, amounts, and operation logs remain unchanged. Migration is idempotent and provides a dry-run report before mutation.

The current environment contains no retained draft or pending OA test requests after the authorized cleanup, so acceptance tests create isolated named fixtures and remove only those fixtures afterward.

## 7. Backend and frontend contract

The backend owns:

- applicant department lookup;
- department-supervisor resolution;
- excluded-manager traversal;
- User-link and enabled-state validation;
- route construction;
- asset-type validation;
- step capabilities and action authorization.

The frontend:

- displays the backend-provided applicant department and supervisor result;
- renders the required request-level asset single-select after OCR confirmation;
- never accepts a free-text approver identity;
- shows a route preview returned by the backend;
- keeps expense classification editable only for the active Stage 1 actor;
- renders a distinct final payment confirmation action at Stage 6.

## 8. Error handling

- Submission is blocked if no organization path can reach either an enabled non-executive supervisor or Li Qinggele/Wang Yansong.
- Submission identifies an employee whose department or supervisor mapping is missing.
- Missing or disabled required accounts for Ye Liwei, Ren Feifan, Yi Jiawei, Zhang Meng, Li Qinggele, or Wang Yansong block route activation with a precise diagnostic.
- Stale actions cannot advance a different current step.
- Duplicate clicks remain idempotent.
- No fallback creates guessed Users or stores Chinese names as approver IDs.

## 9. Verification

Implementation follows test-driven development.

Unit route tests cover:

- an ordinary employee with an enabled department supervisor;
- a department supervisor under Philippe;
- a team under an accountless supervisor;
- BU paths under Sabri;
- direct resolution to Li Qinggele and Wang Yansong;
- all three asset types;
- Finance, Sales/customer-service, and other departments;
- self-approval;
- mandatory Zhang Meng and final Ye Liwei steps;
- Sales `all` co-sign and other-department sequential approval.

Integration tests cover:

- Employee-to-User resolution and enabled-state checks;
- Finance expense-item readiness;
- route snapshot persistence;
- current-step authorization;
- final confirmation behavior;
- idempotent migration;
- no corruption of invoice, attachment, or audit data.

Live Docker acceptance uses real linked accounts and at least these scenarios:

1. R&D ordinary employee, non-fixed-asset expense;
2. R&D department supervisor under Philippe, non-electronic fixed asset;
3. customer-service employee, electronic fixed asset, Sales co-sign;
4. Finance employee, other expense;
5. applicant who also owns a later approval node.

Each scenario must complete from submission through Ye Liwei's final confirmation. Browser checks include route preview, correct action visibility, invoice preview, no console errors, and no leftover test requests.

## 10. Completion criteria

The work is complete only when:

- Docker-only valid fixes are present in the clean worktree;
- targeted and full backend tests pass;
- frontend tests and production build pass;
- organization mappings and required accounts pass diagnostics;
- all live acceptance scenarios complete;
- PR #24 contains the tested code, migrations, tests, and exact frontend assets;
- Docker runs the exact final PR commit;
- all host worktrees and the Docker app checkout report a clean Git status.
