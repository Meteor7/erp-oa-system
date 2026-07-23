# Invoice Expense Context and Account Tree Design

Date: 2026-07-23  
Branch: `feat/ocr-monthly-timesheet-integration`  
Status: approved for implementation

## 1. Objective

Move each invoice's required expense description and optional supplemental attachments from the reimbursement draft editor to the invoice OCR workbench, preserve their one-to-one relationship through push, and make them easy to review in the approval detail. Replace the incorrect flat expense-item list with the approved two-level account tree from `费用科目.xlsx` while keeping existing project-name aggregation.

## 2. Confirmed behavior

- The field is named `费用说明`.
- Every invoice must have a non-empty expense description before `确认内容`.
- Supplemental attachments are optional, private, and limited to the existing PDF/JPG/JPEG/PNG, 10 MB per file, 10 files per invoice rules.
- Confirmed but not yet pushed invoices may still edit expense description and supplemental attachments.
- Pushed invoices are read-only. To change the context, first withdraw the invoice push.
- The upload workbench remains the employee entry point; the reimbursement detail becomes the approval/review surface.
- Every invoice retains its own description and attachment collection even when several invoices aggregate into one project-name group.
- Manual expense entry keeps `项目名称`, `日期`, `税后金额`, and required `费用说明`.
- Manual expense entry removes `无票原因`.
- Manual expense entry replaces the flat `费用项目` with required dependent `一级科目` and `二级科目` fields. A second-level selection is required only when the selected first-level account has children.
- Finance may change the account chosen on a manual expense. Invoice-backed expenses continue to be classified by Finance during approval.
- Aggregation remains by exact normalized project name. Manual expenses are not switched to invoice-category aggregation.

## 3. Chosen architecture

### 3.1 Invoice context is the pre-push source of truth

Add `expense_description` to `OA Invoice Record`. Add a standalone `OA Invoice Supplemental Attachment` DocType keyed by invoice record and private File. Supplemental Files remain attached to the invoice record for their whole life; they are not copied or moved when the invoice is pushed or withdrawn.

This is preferred over creating a reimbursement draft early because early drafts would pollute the approval board and complicate abandoned uploads. It is preferred over copying attachments at push time because copying creates duplicate Files, difficult rollback, and mismatched delete behavior.

The request serializer resolves invoice supplemental attachments through each expense line's `source_invoice`. Existing `OA Expense Line Attachment` records remain supported for legacy drafts and manual lines, so deployment does not delete or orphan current data.

### 3.2 Separate OCR fields from expense context

OCR correction stays limited to the seven recognized invoice fields. Add a dedicated update endpoint for expense context so a confirmed-but-unpushed invoice can change its description without reopening or silently changing confirmed OCR data.

Backend confirmation and push both revalidate the description. Frontend validation is convenience only.

### 3.3 Canonical two-level expense-account tree

Add a small backend module that defines and validates the normalized account tree imported from the workbook. `get_options` returns the same tree to the frontend. Duplicate `信息技术服务费` is collapsed, surrounding whitespace such as `广告宣传费 ` is removed, and every other label is preserved, including `Philippe` and `Sabri`.

Store `expense_account_level_1` and `expense_account_level_2` on each expense line. Continue populating legacy `expense_item` with a deterministic display value for existing reporting and compatibility:

- first level with children: `一级科目 / 二级科目`
- first level without children: `一级科目`

Backend validation, not the browser, decides whether a pair is valid.

## 4. Account tree

- 差旅费: 飞机票, 高铁\\火车票, 市内交通费, 乘车费, 住宿费, 出差补助, 过路/停车费, Philippe, Sabri
- 员工福利费: 员工聚餐, 节日福利, 员工工服, 日常零食, 团建活动
- 中介机构费: 审计费, 资质认证咨询服务费, 体系认证咨询服务费, 代办服务费
- 业务招待费: 餐饮费, 乘车费
- 租赁费: 房屋, 车辆, 仪器
- Leaf first-level accounts: 市内交通费, 办公费, 保洁费, 快递费, 物业费, 水费, 电费, 会议费, 咨询费, 招聘费, 培训费, 维修费, 装修费, 押金/保证金, 燃油费, 商标\\专利费, 信息技术服务费, 固定资产-电子设备, 固定资产-办公家具、工具及器具, 劳保费, 安全生产费, 招投标费, 保险费, 包装费, 运输费, 装卸费, 广告宣传费, 展览费, 经济补偿金, 诉讼费, 其他

## 5. Upload workbench design

Keep the invoice list at left and make the selected-invoice panel a clear review card:

1. Invoice identity and recognition status.
2. Seven OCR fields.
3. Required full-width `费用说明`.
4. Optional `补充附件` uploader with count, filename chips, preview, and delete.
5. Warnings and actions.

The selected invoice cannot be confirmed while the description is blank. A row also cannot be checked for push unless it is confirmed, unpushed, and has a description.

## 6. Approval detail design

Increase the reimbursement detail dialog to `min(96vw, 1720px)` and retain the sticky header and footer. Each project group remains one section, but its source invoices render as readable responsive rows/cards rather than one wide table.

For every source invoice, render in one visual unit:

- recognized invoice fields and amounts;
- `查看发票`;
- the corresponding read-only `费用说明`;
- the corresponding attachment chips and preview actions.

Manual lines render their project name, selected account hierarchy, date, amount, and description without invoice actions. Finance account selection stays prominent at group level and writes the validated account pair consistently to all lines in the same project group.

## 7. Compatibility and migration

- Add schema fields and DocType through normal Frappe migration.
- Backfill `OA Invoice Record.expense_description` from linked request expense lines when the record value is empty.
- Preserve all existing request-line attachments and include them in approval serialization.
- Do not rewrite invoice files, approval history, workflow status, payments, totals, or completed classifications.
- Existing legacy `expense_item` text stays readable. A new save uses the canonical pair and derived display value.
- Withdrawal does not move supplemental files because their permanent owner is the invoice record.

## 8. Security and validation

- Only the invoice uploader, framework Administrator, System Manager, or a user with edit access to the linked draft may edit pre-push context.
- Once `request` is set, invoice context writes are rejected.
- Attachment Files must be private, owned by the registering user before registration, not linked to another document, and pass the existing content/magic-byte checks.
- Preview uses a short-lived, single-use POST token and rechecks invoice/request read permission.
- Every mutation uses the existing transaction-lock convention.

## 9. Verification

Backend tests cover account-tree normalization/validation, description confirmation and push gates, attachment ownership/preview/delete, serialization, withdrawal stability, manual-expense validation, Finance classification, and legacy compatibility.

Frontend tests cover dependent selects, required description, attachment actions, push eligibility, removed no-invoice reason, retained project name, and approval one-to-one rendering. Browser acceptance covers upload, OCR edit, description, attachment preview, confirm, push, Finance classification, approval review, withdrawal, and responsive layout without horizontal overflow.
