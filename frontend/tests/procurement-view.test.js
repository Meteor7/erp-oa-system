import assert from 'node:assert/strict';
import test from 'node:test';
import {
  FIXED_ASSET_CATEGORIES, PAGE_SIZE, REQUEST_DIRECT, REQUEST_PROCUREMENT, applyMaterial, approvalButtonLabel, approveBlocker,
  approvalWorkItems, blankForm, canActOn, canWithdrawRow, categoryChildren, chainRoute, chainStrip, currentStepKey,
  detailBanner, directMaterials, draftKind, filterRows, formBlockers, formFromRow, listScope, mergeRows, pageCount,
  pageSlice, paymentWorkItems, pmcLines, poWorkItems, prWorkItems, priceWorkItems, procurementView, relatedDocuments,
  requestFacts, requestTypeForPath, stageDistribution, stageKey, statusOf, stepTimeline, summarizeLines, validateRequestForm,
  waitText, waitedDays, whereText,
} from '../src/lib/procurementView.js';

const line = (extra = {}) => ({
  material_code: '', category_code: '1.ELC.3', item_name: '光纤跳线', specification: 'FC/APC', brand: 'Thorlabs', unit: '根', quantity: 2, ...extra,
});
const base = (extra = {}) => ({
  name: 'OA-1', request_type: REQUEST_PROCUREMENT, workflow_status: '待审批', business_status: '待审批', subject: '线缆采购',
  employee: 'EMP-1', employee_name: '演示员工163', department: '研发部', urgency: '一般', current_step_index: 1, current_step_label: '会签',
  steps: [], business_lines: [line()], procurement_chain: { stage: 'demand', label: '需求审批中', summary: '', pr_numbers: [], price_approval_numbers: [], po_numbers: [] },
  ...extra,
});

test('route decides the page: home, list, detail, new and PMC edit', () => {
  assert.equal(procurementView({ path: '/approval/procurement', query: {} }), 'home');
  assert.equal(procurementView({ path: '/approval/procurement', query: { view: 'list', scope: 'todo' } }), 'list');
  assert.equal(procurementView({ path: '/approval/procurement', query: { request: 'OA-1' } }), 'detail');
  assert.equal(procurementView({ path: '/approval/procurement', query: { view: 'list', request: 'OA-1' } }), 'detail');
  assert.equal(procurementView({ name: 'procurement-new', path: '/approval/procurement/new', query: { draft: 'OA-2' } }), 'new');
  assert.equal(procurementView({ name: 'direct-purchase-new', path: '/approval/direct-purchase/new', query: {} }), 'new');
  assert.equal(procurementView({ name: 'procurement-pmc-edit', path: '/approval/procurement/OA-1/pmc-edit', query: {} }), 'pmc-edit');
  assert.equal(requestTypeForPath('/approval/direct-purchase'), REQUEST_DIRECT);
  assert.equal(requestTypeForPath('/approval/direct-purchase/new'), REQUEST_DIRECT);
  assert.equal(requestTypeForPath('/approval/procurement'), REQUEST_PROCUREMENT);
  assert.equal(requestTypeForPath('/approval/procurement/new'), REQUEST_PROCUREMENT);
  assert.equal(listScope({ scope: 'all' }, 'mine'), 'all');
  assert.equal(listScope({ scope: 'bogus' }, 'todo'), 'todo');
});

test('stage comes from the backend procurement chain, drafts and legacy rows are handled', () => {
  assert.equal(stageKey(base()), 'demand');
  assert.equal(stageKey(base({ workflow_status: '已完成', procurement_chain: { stage: 'await_pr' } })), 'await_pr');
  assert.equal(stageKey(base({ workflow_status: '已完成', procurement_chain: { stage: 'quote' } })), 'quote');
  assert.equal(stageKey(base({ workflow_status: '已完成', procurement_chain: { stage: 'price' } })), 'price');
  assert.equal(stageKey(base({ workflow_status: '已完成', procurement_chain: { stage: 'po', po_numbers: ['PO-1'] } })), 'po');
  assert.equal(stageKey(base({ workflow_status: '已完成', procurement_chain: { stage: 'closed', po_numbers: ['PO-1'] } })), 'closed');
  assert.equal(stageKey(base({ workflow_status: '已完成', business_status: '采购执行中', procurement_chain: { stage: 'await_pr' } })), 'po');
  assert.equal(stageKey(base({ workflow_status: '草稿', business_status: '已撤回' })), 'withdrawn');
  assert.equal(stageKey(base({ workflow_status: '草稿', business_status: '', operation_log: [{ action: '驳回' }] })), 'rejected');
  assert.equal(draftKind(base({ workflow_status: '草稿', business_status: '', operation_log: [] })), 'draft');
  assert.equal(statusOf(base({ workflow_status: '已完成', procurement_chain: { stage: 'await_pr' } })).label, '等待提 PR');
  assert.equal(statusOf({ request_type: REQUEST_DIRECT, workflow_status: '待审批' }).label, '审批中');
  assert.equal(statusOf({ request_type: REQUEST_DIRECT, workflow_status: '已完成', business_status: '待付款' }).label, '待付款');
});

test('where text names the waiting step, the PO or the next action', () => {
  assert.equal(whereText(base()), '会签');
  assert.match(whereText(base({ workflow_status: '已完成', procurement_chain: { stage: 'await_pr' } })), /物料看板/);
  assert.match(whereText(base({ workflow_status: '已完成', procurement_chain: { stage: 'po', po_numbers: ['PO-9'], summary: '已进入 PO 1 项' } })), /PO-9/);
});

test('queue merges mine and pending without duplicates, filters client side and pages by 50', () => {
  const rows = mergeRows(REQUEST_PROCUREMENT, [base({ name: 'A', modified: '2026-09-02' }), base({ name: 'B', modified: '2026-09-01' })], [base({ name: 'A' }), base({ name: 'C', modified: '2026-09-03' }), { name: 'X', request_type: REQUEST_DIRECT }]);
  assert.deepEqual(rows.map((row) => row.name), ['C', 'A', 'B']);
  const list = [
    base({ name: 'OA-1', subject: '线缆', project: 'P1', urgency: '加急' }),
    base({ name: 'OA-2', subject: '耗材', project: '', workflow_status: '已完成', procurement_chain: { stage: 'po', po_numbers: ['PO-5'] }, business_lines: [line({ item_name: '擦镜纸' })] }),
  ];
  const projectName = (name) => ({ P1: '硅光样机' }[name] || name);
  assert.deepEqual(filterRows(list, { text: '擦镜' }, projectName).map((row) => row.name), ['OA-2']);
  assert.deepEqual(filterRows(list, { text: '硅光' }, projectName).map((row) => row.name), ['OA-1']);
  assert.deepEqual(filterRows(list, { text: 'po-5' }).map((row) => row.name), ['OA-2']);
  assert.deepEqual(filterRows(list, { urgent: true }).map((row) => row.name), ['OA-1']);
  assert.deepEqual(filterRows(list, { stage: 'po' }).map((row) => row.name), ['OA-2']);
  assert.deepEqual(filterRows(list, { project: '__none__' }).map((row) => row.name), ['OA-2']);
  assert.deepEqual(filterRows(list, { project: 'P1' }).map((row) => row.name), ['OA-1']);
  const many = Array.from({ length: 120 }, (_, index) => index);
  assert.equal(PAGE_SIZE, 50);
  assert.equal(pageCount(many.length), 3);
  assert.equal(pageSlice(many, 2).length, 20);
});

test('waiting days only count while approval is active', () => {
  const now = Date.parse('2026-09-30T12:00:00');
  assert.equal(waitedDays({ steps: [{ acted_on: '2026-09-27 10:00:00' }] }, now), 3);
  assert.equal(waitedDays({ creation: '2026-09-30 08:00:00' }, now), 0);
  assert.equal(waitText(0), '今天');
  assert.equal(waitText(3), '等了 3 天');
  assert.equal(waitText(null), '—');
});

test('approval actions: button label, PMC block, local hide after acting on the same step', () => {
  const pmc = base({ can_approve: true, can_reject: true, can_modify_procurement_request: true, current_step_label: 'PMC', steps: [{ step_index: 1, step_key: 'k1', label: 'PMC', mode: 'approve' }], business_lines: [line({ material_code: '1.ELC.3.001' }), line()] });
  assert.match(approveBlocker(pmc), /1 项物料没有绑定物料编号/);
  assert.equal(approveBlocker({ ...pmc, business_lines: [line({ material_code: 'X' })] }), '');
  assert.equal(approveBlocker({ ...pmc, can_modify_procurement_request: false }), '');
  assert.equal(approvalButtonLabel(pmc), '需求审批通过');
  assert.equal(approvalButtonLabel({ request_type: REQUEST_DIRECT, workflow_status: '待审批' }, { mode: 'approve', label: '会签' }), '审批通过');
  assert.equal(approvalButtonLabel({}, { mode: 'handle', label: '总经理付款' }), '确认付款');
  assert.equal(approvalButtonLabel({}, { mode: 'handle', label: '出纳' }), '办理完成');
  assert.equal(currentStepKey(pmc), 'k1');
  assert.equal(canActOn(pmc, {}), true);
  assert.equal(canActOn(pmc, { 'OA-1': 'k1' }), false);
  assert.equal(canActOn(pmc, { 'OA-1': 'other' }), true);
  assert.equal(canActOn({ ...pmc, can_reject: false }, {}, 'can_reject'), false);
});

test('only the applicant can withdraw, and only while approval is pending', () => {
  assert.equal(canWithdrawRow(base({ can_withdraw: true }), 'EMP-1'), true);
  assert.equal(canWithdrawRow(base({ can_withdraw: false }), 'EMP-1'), true);
  assert.equal(canWithdrawRow(base({ can_withdraw: false }), 'EMP-9'), false);
  assert.equal(canWithdrawRow(base({ workflow_status: '已完成', can_withdraw: true }), 'EMP-1'), false);
  assert.equal(canWithdrawRow(base({ workflow_status: '草稿', can_withdraw: true }), 'EMP-1'), false);
});

test('timeline lists every parallel co-signer and who has agreed', () => {
  const row = base({
    current_step_index: 1,
    steps: [
      { step_index: 1, step_key: 'a', label: '直属主管：直属领导、项目主管：项目主管（会签）', mode: 'approve', status: '待审批', approvers: ['a@x', 'b@x'], approved_by: ['a@x'] },
      { step_index: 2, step_key: 'b', label: 'PMC', mode: 'approve', status: '待流转', approvers: ['c@x'], approved_by: [] },
    ],
  });
  const items = stepTimeline(row, (user) => user.split('@')[0]);
  assert.equal(items[0].state, 'now');
  assert.equal(items[0].parallel, true);
  assert.deepEqual(items[0].people.map((p) => [p.name, p.done]), [['直属主管：直属领导', true], ['项目主管：项目主管', false]]);
  assert.match(items[0].sub, /已同意 1\/2/);
  assert.equal(items[1].state, 'todo');
  const done = stepTimeline({ ...row, workflow_status: '已完成', steps: [{ ...row.steps[0], status: '已通过', acted_on: '2026-09-27 14:20:00' }] }, (u) => u);
  assert.equal(done[0].state, 'done');
  assert.match(done[0].sub, /全部同意/);
});

test('stage strip, links and banner follow the chain and the role flags', () => {
  const executing = base({ workflow_status: '已完成', procurement_chain: { stage: 'price', label: '价格审批中', summary: '待演示员工37选择并审批 1 项', pr_numbers: ['PR-1'], price_approval_numbers: ['PA-1'], po_numbers: [] } });
  const strip = chainStrip(executing);
  assert.deepEqual(strip.map((item) => item.label), ['需求审批', '等待提 PR', '询价比价', '价格审批', 'PO 执行中', '已关闭']);
  assert.deepEqual(strip.map((item) => item.state), ['done', 'done', 'done', 'now', 'todo', 'todo']);
  assert.match(strip[3].sub, /待演示员工37/);
  assert.deepEqual(chainStrip(base({ workflow_status: '草稿', business_status: '' })), []);
  const hidden = relatedDocuments({ ...executing, can_view_procurement_price: false, can_view_procurement_po: false });
  assert.equal(hidden.find((item) => item.key === 'price').to, null);
  assert.equal(hidden.find((item) => item.key === 'price').v, '无权限查看');
  assert.equal(hidden.some((item) => item.key === 'board'), false);
  const allowed = relatedDocuments({ ...executing, can_view_procurement_price: true }, { canBoard: true });
  assert.deepEqual(allowed.find((item) => item.key === 'price').to, { name: 'procurement-price-approvals', query: { approval: 'PA-1' } });
  assert.equal(allowed.some((item) => item.key === 'board'), true);
  assert.deepEqual(chainRoute({ name: 'OA-1', procurement_chain: { stage: 'await_pr' } }), { path: '/approval/material-progress', query: { request: 'OA-1' } });
  assert.equal(chainRoute({ name: 'OA-1', procurement_chain: { stage: 'quote' } }).query.view, 'source');
  assert.match(detailBanner(base({ workflow_status: '草稿', business_status: '已撤回' })).text, /已撤回/);
  assert.equal(detailBanner(base({ can_approve: true, can_modify_procurement_request: true, business_lines: [line()] }), { canAct: true }).tone, 'warn');
  assert.match(detailBanner(executing, { insider: false }).text, /价格、供应商只对采购和财务显示/);
});

test('facts: procurement and direct purchase show their own fields', () => {
  const facts = requestFacts(base({ reason: '试制', procurement_scope: '项目采购', project: 'P1', asset_nature: '非固定资产', expected_delivery_date: '2026-10-20', purchaser_user: 'buyer@x' }), {
    projectName: () => '硅光样机', purchasers: [{ name: 'buyer@x', full_name: '采购经办' }],
  });
  assert.deepEqual(facts.map((fact) => fact.k), ['申请用途', '采购范围', '采购归属', '资产属性', '预计交期', '采购经办人', '申请部门']);
  assert.equal(facts.find((fact) => fact.k === '采购归属').v, '项目 · 硅光样机');
  assert.equal(facts.find((fact) => fact.k === '采购经办人').v, '采购经办');
  const direct = requestFacts({ request_type: REQUEST_DIRECT, purchase_method: '京东购买', asset_nature: '固定资产', fixed_asset_category: FIXED_ASSET_CATEGORIES[0], source_purchase_order: 'PO-3', department: '销售部' });
  assert.deepEqual(direct.map((fact) => fact.k), ['申请用途', '购买方式', '采购归属', '资产属性', '固定资产类别', '预计交期', '申请部门', '来源 PO']);
});

test('fixed asset categories match the backend list', () => {
  assert.deepEqual([...FIXED_ASSET_CATEGORIES], ['办公家具、工具及器具', '电子设备、研发专用设备、仪器仪表', '生产设备、生产工具及器具']);
});

test('form blockers cover header, direct purchase rules and the first line problem', () => {
  const form = blankForm();
  assert.ok(formBlockers(form, REQUEST_PROCUREMENT).includes('主题未填'));
  assert.ok(formBlockers(form, REQUEST_PROCUREMENT).includes('预计交期未填'));
  assert.ok(formBlockers(form, REQUEST_PROCUREMENT).includes('所属项目未选'));
  form.procurement_scope = '非项目采购';
  assert.ok(formBlockers(form, REQUEST_PROCUREMENT).includes('所属部门未选'));
  form.non_project_department = '财务部 - RAY';
  assert.ok(!formBlockers(form, REQUEST_PROCUREMENT).includes('所属部门未选'));
  const direct = { ...blankForm(), subject: '投屏器', expected_delivery_date: '2026-10-15', asset_nature: '固定资产' };
  direct.business_lines = [{ item_name: '投屏器', unit: '台', quantity: 1 }];
  assert.deepEqual(formBlockers(direct, REQUEST_DIRECT), ['固定资产类别未选']);
  direct.fixed_asset_category = FIXED_ASSET_CATEGORIES[1];
  assert.equal(validateRequestForm(direct, REQUEST_DIRECT), '');
  const proc = { ...blankForm(), subject: '线缆', expected_delivery_date: '2026-10-20', project: 'P1' };
  proc.business_lines = [{ ...line({ category_code: '1.ELC' }) }];
  assert.match(validateRequestForm(proc, REQUEST_PROCUREMENT), /至少选择到三级/);
  proc.business_lines = [line({ category_code: '1.ELC.3' })];
  assert.equal(validateRequestForm(proc, REQUEST_PROCUREMENT), '');
});

test('opening a returned draft restores the whole form, PMC lines keep the system serial', () => {
  const row = base({
    workflow_status: '草稿', procurement_scope: '非项目采购', non_project_allocation_type: '部门', non_project_department: '生产部', expected_delivery_date: '2026-10-15',
    reason: '补货', employee: 'EMP-7', business_lines: [line({ material_code: '1.ELC.3.001', material_serial: 'MAT-1', quantity: '3' })],
  });
  const form = formFromRow(row);
  assert.equal(form.applicant_employee, 'EMP-7');
  assert.equal(form.non_project_department, '生产部');
  assert.equal(form.business_lines[0].quantity, 3);
  assert.deepEqual(form.business_lines[0].category_parts, ['1', '1.ELC', '1.ELC.3']);
  assert.equal(formFromRow({ request_type: REQUEST_DIRECT, employee: 'EMP-7', business_lines: [] }).applicant_employee, '');
  assert.equal(pmcLines(form.business_lines)[0].material_serial, 'MAT-1');
  assert.equal(pmcLines(form.business_lines)[0]._uid, undefined);
  const sums = summarizeLines([line({ material_code: 'A' }), line()], REQUEST_PROCUREMENT);
  assert.deepEqual([sums.total, sums.bound, sums.pending], [2, 1, 1]);
});

test('material picker helpers keep catalog data and only direct serials', () => {
  const l = { material_code: '', category_code: '' };
  applyMaterial(l, { material_code: '1.ELC.3.3.01.001', material_name: '光纤跳线', specification: 'FC', brand: 'T', unit: '根' });
  assert.equal(l.category_code, '1.ELC.3.3.01');
  assert.equal(l.item_name, '光纤跳线');
  const categories = [{ category_code: '1', category_name: 'A' }, { category_code: '1.ELC', parent_category: '1' }, { category_code: '1.OPT' }];
  assert.deepEqual(categoryChildren(categories, '1').map((item) => item.category_code), ['1.ELC', '1.OPT']);
  const rows = [{ material_code: '1.ELC.3.001' }, { material_code: '1.ELC.3.001.002' }, { material_code: '', category_code: '1.ELC.3' }];
  assert.equal(directMaterials(rows, '1.ELC.3').length, 2);
});

test('home work groups: PMC, buyer and vice manager items come from PR, price approval and PO data', () => {
  const pr = prWorkItems([
    { pr_eligible: 1, source_request: 'OA-9', item_name: '测试工装', requester: '演示员工163', pr_available_quantity: 5, unit: '块' },
    { pr_eligible: 1, source_request: 'OA-9', item_name: '线材', requester: '演示员工163', pr_available_quantity: 20, unit: '支' },
    { pr_eligible: 0, source_request: 'OA-8', item_name: '已提完' },
  ]);
  assert.equal(pr.length, 1);
  assert.equal(pr[0].count, 2);
  assert.equal(pr[0].to.path, '/approval/material-progress');
  const price = priceWorkItems({ prs: [{ name: 'PR-1', can_create_price_approval: 1, available_line_count: 1, available_quantity: 40 }, { name: 'PR-2', can_create_price_approval: 0 }], drafts: [{ name: 'PA-1' }] });
  assert.deepEqual(price.map((item) => item.tag), ['待比价', '价格审批']);
  const orders = [
    { name: 'PO-1', status: '草稿', can_manage_purchase: 1 },
    { name: 'PO-2', status: '待合同复核', contract_status: '待补充信息', can_manage_purchase: 1 },
    { name: 'PO-3', status: '待合同复核', contract_status: '草稿待复核', can_manage_purchase: 1 },
    { name: 'PO-4', status: '待电子用印', can_seal_contract: 1, can_manage_purchase: 0 },
    { name: 'PO-5', status: '供应商制作中', can_manage_purchase: 1 },
  ];
  assert.deepEqual(poWorkItems(orders, { manage: true, seal: false }).map((item) => item.tag), ['确认 PO', '合同草稿', '复核合同']);
  assert.deepEqual(poWorkItems(orders, { manage: false, seal: true }).map((item) => item.tag), ['电子用印']);
  assert.equal(approvalWorkItems([{ name: 'PA-2', status: '待审批', can_select_quote: 1 }, { name: 'PA-3', status: '待审批', can_select_quote: 0 }]).length, 1);
  const pay = paymentWorkItems([
    { key: 'PO-1:r1', po: 'PO-1', installment_name: '第1期', payment_stage: '预付款', work_status: '可提交付款审批', can_push_payment: 1 },
    { key: 'PO-1:r2', po: 'PO-1', work_status: '待验收', can_push_payment: 0 },
  ]);
  assert.equal(pay.length, 1);
  assert.match(pay[0].subject, /PO-1 · 第1期预付款/);
});

test('stage distribution counts each request once and breaks PO down by PO status', () => {
  const rows = [
    base({ name: '1', current_step_label: '直属主管：直属领导、项目主管：项目主管（会签）' }),
    base({ name: '2', current_step_label: 'PMC' }),
    base({ name: '3', workflow_status: '已完成', procurement_chain: { stage: 'await_pr' } }),
    base({ name: '4', workflow_status: '已完成', procurement_chain: { stage: 'po', po_numbers: ['PO-1', 'PO-2'] } }),
    base({ name: '5', workflow_status: '已完成', procurement_chain: { stage: 'po', po_numbers: ['PO-3'] } }),
    base({ name: '6', workflow_status: '草稿', business_status: '' }),
  ];
  const cells = stageDistribution(rows, { 'PO-1': '到货验收中', 'PO-2': '供应商制作中', 'PO-3': '付款中' });
  assert.deepEqual(cells.map((cell) => cell.count), [2, 1, 0, 0, 2, 0]);
  assert.match(cells[0].sub, /会签 1/);
  assert.match(cells[0].sub, /PMC 1/);
  assert.match(cells[4].sub, /供应商制作中 1/);
  assert.match(cells[4].sub, /付款中 1/);
});

test('the expense category of a procurement request follows the project or the department (2026-10-09)', async () => {
  const { expenseCategoryOf, formFromRow, requestFacts } = await import('../src/lib/procurementView.js');
  const departments = [{ name: '研发软件部 - RAY', category: '研发费用' }, { name: '财务部 - RAY', category: '管理费用' }, { name: '制造部 - RAY', category: '生产成本' }];
  assert.equal(expenseCategoryOf({ procurement_scope: '项目采购', project: 'RD03' }, departments), '研发费用');
  assert.equal(expenseCategoryOf({ procurement_scope: '项目采购', non_project_department: '财务部 - RAY' }, departments), '研发费用');
  assert.equal(expenseCategoryOf({ procurement_scope: '非项目采购', non_project_department: '财务部 - RAY' }, departments), '管理费用');
  assert.equal(expenseCategoryOf({ procurement_scope: '非项目采购', non_project_department: '制造部 - RAY' }, departments), '生产成本');
  assert.equal(expenseCategoryOf({ procurement_scope: '非项目采购', non_project_department: '' }, departments), '');
  assert.equal(expenseCategoryOf({ procurement_scope: '非项目采购', non_project_department: '别的部门' }, departments), '');
  // 旧草稿里的"成本中心"归属：改回按部门，部门要重新选
  const old = formFromRow({ procurement_scope: '非项目采购', non_project_allocation_type: '成本中心', non_project_cost_center: 'CC-1', expected_delivery_date: '2026-10-15', business_lines: [] });
  assert.equal(old.non_project_allocation_type, '部门');
  assert.equal(old.non_project_department, '');
  assert.equal(requestFacts({ request_type: '采购申请', procurement_scope: '非项目采购', non_project_department: '财务部 - RAY', expense_account_category: '管理费用' }).find((item) => item.k === '费用类别').v, '管理费用');
});
