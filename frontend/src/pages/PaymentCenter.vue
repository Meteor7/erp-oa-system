<script setup>
import { computed, onMounted, ref, watch } from 'vue';
import { createResource, FeatherIcon } from 'frappe-ui';
import { useRoute, useRouter } from 'vue-router';
import PreRequestCenter from './PreRequestCenter.vue';

const route = useRoute();
const router = useRouter();
const api = 'rayher_hr_payroll.api.procurement_chain.';
const loader = createResource({ url: api + 'list_payment_work_items', method: 'GET' });
const receive = createResource({ url: api + 'record_po_receipt', method: 'POST' });
const inspect = createResource({ url: api + 'record_po_inspection', method: 'POST' });
const push = createResource({ url: api + 'push_po_payment_request', method: 'POST' });

const tab = ref(route.query.request ? 'approvals' : 'workbench');
const selectedKey = ref('');
const statusFilter = ref(String(route.query.status || '未完成'));
const search = ref(String(route.query.po || ''));
const receiptDraft = ref({});
const inspectionDraft = ref({});
const receiptDate = ref(new Date().toISOString().slice(0, 10));
const inspectionDate = ref(new Date().toISOString().slice(0, 10));
const receiptEvidence = ref(null);
const inspectionEvidence = ref(null);
const uploading = ref('');
const notice = ref('');
const error = ref('');
const items = computed(() => loader.data || []);
const statuses = ['未完成', '全部', '待合同生效', '待到货资料', '待验收', '可提交付款审批', '付款审批中', '待实际付款', '已付款'];
const filteredItems = computed(() => {
  const query = search.value.trim().toLowerCase();
  return items.value.filter((item) => {
    if (statusFilter.value === '未完成' && item.work_status === '已付款') return false;
    if (!['未完成', '全部'].includes(statusFilter.value) && item.work_status !== statusFilter.value) return false;
    return !query || [item.po, item.installment_name, item.payment_stage, item.supplier, item.payment_request].join(' ').toLowerCase().includes(query);
  });
});
const activeItem = computed(() => items.value.find((item) => item.key === selectedKey.value) || filteredItems.value[0] || null);
const statusCounts = computed(() => items.value.reduce((result, item) => {
  result[item.work_status] = (result[item.work_status] || 0) + 1;
  return result;
}, {}));

function money(value, currency = 'CNY') { return `${currency || 'CNY'} ${Number(value || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`; }
function quantity(value) { return Number(value || 0).toLocaleString('zh-CN', { maximumFractionDigits: 4 }); }
function statusClass(status) {
  if (['已付款', '可提交付款审批', '已通过'].includes(status)) return 'done';
  if (['付款审批中', '待实际付款'].includes(status)) return 'active';
  if (['不合格', '退货中', '换货中'].includes(status)) return 'danger';
  return 'wait';
}
function clearFeedback() { notice.value = ''; error.value = ''; }
function fail(err, fallback) { error.value = err?.messages?.[0] || err?.message || fallback; }
function initializeDrafts(item) {
  receiptDraft.value = Object.fromEntries((item?.lines || []).map((line) => [line.name, '']));
  inspectionDraft.value = Object.fromEntries((item?.lines || []).map((line) => [line.name, '']));
  receiptEvidence.value = null;
  inspectionEvidence.value = null;
}
async function uploadEvidence(event, kind) {
  const file = event.target.files?.[0]; event.target.value = '';
  if (!file) return;
  uploading.value = kind; clearFeedback();
  try {
    const body = new FormData(); body.append('file', file); body.append('is_private', '1');
    const response = await fetch('/api/method/upload_file', { method: 'POST', body, credentials: 'same-origin', headers: { 'X-Frappe-CSRF-Token': window.csrf_token || '' } });
    const data = await response.json();
    if (!response.ok || data.exc) throw new Error(data.message || '上传失败');
    const evidence = { name: data.message.name, filename: data.message.file_name || file.name };
    if (kind === 'receipt') receiptEvidence.value = evidence; else inspectionEvidence.value = evidence;
  } catch (err) { fail(err, '资料上传失败'); }
  finally { uploading.value = ''; }
}
function selectItem(item) { selectedKey.value = item.key; initializeDrafts(item); }
async function refresh(preferredKey = selectedKey.value) {
  await loader.reload();
  selectedKey.value = items.value.some((item) => item.key === preferredKey) ? preferredKey : (filteredItems.value[0]?.key || '');
  initializeDrafts(activeItem.value);
}
async function recordReceipt() {
  clearFeedback();
  const lines = (activeItem.value?.lines || []).filter((line) => Number(receiptDraft.value[line.name]) > 0).map((line) => ({ line: line.name, quantity: Number(receiptDraft.value[line.name]) }));
  if (!lines.length) return fail(null, '请填写至少一项本次到货数量');
  if (!receiptDate.value || !receiptEvidence.value) return fail(null, '请填写到货日期并上传送货单、收料单或入库单');
  try {
    await receive.submit({ name: activeItem.value.po, lines: JSON.stringify(lines), arrival_date: receiptDate.value, file_ref: receiptEvidence.value.name });
    notice.value = '到货资料已登记，付款条件状态已同步';
    await refresh();
  } catch (err) { fail(err, '登记到货失败'); }
}
async function recordInspection() {
  clearFeedback();
  const lines = (activeItem.value?.lines || []).filter((line) => inspectionDraft.value[line.name]).map((line) => ({ line: line.name, status: inspectionDraft.value[line.name] }));
  if (!lines.length) return fail(null, '请至少选择一项验收结果');
  if (!inspectionDate.value || !inspectionEvidence.value) return fail(null, '请填写验收日期并上传验收资料');
  try {
    await inspect.submit({ name: activeItem.value.po, lines: JSON.stringify(lines), inspection_date: inspectionDate.value, file_ref: inspectionEvidence.value.name });
    notice.value = '验收结果已登记，付款条件状态已同步';
    await refresh();
  } catch (err) { fail(err, '登记验收失败'); }
}
async function submitPaymentApproval() {
  clearFeedback();
  try {
    const result = await push.submit({ name: activeItem.value.po, payment_plan_row: activeItem.value.payment_plan_row });
    notice.value = `已生成采购付款 ${result.payment_request} 并进入审批`;
    await refresh();
    await openApproval(result.payment_request);
  } catch (err) { fail(err, '提交付款审批失败'); }
}
async function openApproval(name) {
  tab.value = 'approvals';
  await router.replace({ path: route.path, query: name ? { request: name } : {} });
}
async function showWorkbench() {
  tab.value = 'workbench';
  await router.replace({ path: route.path, query: {} });
}
watch(filteredItems, (rows) => {
  if (!rows.some((item) => item.key === selectedKey.value)) {
    selectedKey.value = rows[0]?.key || '';
    initializeDrafts(activeItem.value);
  }
});
onMounted(refresh);
</script>

<template>
  <div class="payment-shell">
    <header class="page-head">
      <div><span>PROCUREMENT PAYMENT</span><h1>采购付款工作台</h1><p>付款计划、付款条件、到货验收、付款审批和实际付款统一在这里处理</p></div>
      <button type="button" class="icon-button" title="刷新" @click="tab === 'workbench' && refresh()"><FeatherIcon name="refresh-cw" class="h-4 w-4" /></button>
    </header>
    <nav class="tabs">
      <button type="button" :class="{ active: tab === 'workbench' }" @click="showWorkbench"><FeatherIcon name="trello" class="h-4 w-4" />付款工作项<span>{{ items.length }}</span></button>
      <button type="button" :class="{ active: tab === 'approvals' }" @click="tab = 'approvals'"><FeatherIcon name="check-square" class="h-4 w-4" />付款审批单</button>
    </nav>
    <template v-if="tab === 'workbench'">
      <div v-if="notice" class="alert success">{{ notice }}</div><div v-if="error" class="alert danger">{{ error }}</div>
      <section class="filters">
        <div class="status-filters"><button v-for="status in statuses" :key="status" type="button" :class="{ active: statusFilter === status }" @click="statusFilter = status">{{ status }}<span v-if="!['未完成', '全部'].includes(status)">{{ statusCounts[status] || 0 }}</span></button></div>
        <label class="search"><FeatherIcon name="search" class="h-4 w-4" /><input v-model="search" placeholder="搜索 PO、供应商、期次" /></label>
      </section>
      <section class="workspace">
        <aside class="work-list">
          <button v-for="item in filteredItems" :key="item.key" type="button" :class="{ active: activeItem?.key === item.key }" @click="selectItem(item)">
            <div><strong>{{ item.po }}</strong><span :class="['pill', statusClass(item.work_status)]">{{ item.work_status }}</span></div><b>{{ item.installment_name }} · {{ item.payment_stage }}</b><small>{{ item.supplier }}</small>
            <footer><span>{{ item.lines.length }} 项物料</span><strong>{{ money(item.amount, item.currency) }}</strong></footer>
          </button><div v-if="!filteredItems.length" class="empty">当前筛选下没有付款期次</div>
        </aside>
        <article v-if="activeItem" class="detail">
          <header class="document-head">
            <div><span class="document-number">{{ activeItem.po }} · {{ activeItem.installment_name }}</span><div><span :class="['pill', statusClass(activeItem.work_status)]">{{ activeItem.work_status }}</span><span>{{ activeItem.supplier }}</span><span>{{ activeItem.payment_stage }}</span></div></div>
            <section><small>本期付款金额</small><strong>{{ money(activeItem.amount, activeItem.currency) }}</strong><span>{{ activeItem.percentage }}%</span></section>
            <button v-if="activeItem.payment_request" type="button" class="secondary" @click="openApproval(activeItem.payment_request)"><FeatherIcon name="external-link" class="h-4 w-4" />查看付款审批</button>
          </header>
          <div class="facts">
            <dl><dt>付款条件</dt><dd>{{ activeItem.trigger_condition || '无附加条件' }}</dd></dl><dl><dt>发票要求</dt><dd>{{ activeItem.invoice_requirement || '未约定' }}</dd></dl><dl><dt>计划日期</dt><dd>{{ activeItem.planned_date || '-' }}</dd></dl><dl><dt>合同状态</dt><dd>{{ activeItem.contract_status || '-' }}</dd></dl><dl><dt>价格审批来源</dt><dd>{{ activeItem.source_price_approvals || '-' }}</dd></dl><dl><dt>付款审批单</dt><dd>{{ activeItem.payment_request || '尚未生成' }}</dd></dl>
          </div>
          <section class="condition-panel"><header><strong>本期付款条件</strong><span>条件满足后才开放付款审批</span></header><div class="condition-list">
            <span :class="['condition', activeItem.contract_status === '已生效' ? 'satisfied' : 'blocked']"><FeatherIcon :name="activeItem.contract_status === '已生效' ? 'check-circle' : 'clock'" class="h-4 w-4" />合同已生效</span>
            <span v-if="activeItem.trigger_condition.includes('到货')" :class="['condition', activeItem.all_received ? 'satisfied' : 'blocked']"><FeatherIcon :name="activeItem.all_received ? 'check-circle' : 'clock'" class="h-4 w-4" />全部到货</span>
            <span v-if="activeItem.trigger_condition.includes('验收')" :class="['condition', activeItem.all_inspected ? 'satisfied' : 'blocked']"><FeatherIcon :name="activeItem.all_inspected ? 'check-circle' : 'clock'" class="h-4 w-4" />验收通过</span><span class="condition neutral"><FeatherIcon name="file-text" class="h-4 w-4" />{{ activeItem.invoice_requirement || '无发票前置要求' }}</span>
          </div><p v-if="activeItem.blockers.length">当前阻塞：{{ activeItem.blockers.join('；') }}</p></section>
          <div class="table-frame"><table><thead><tr><th>物料流水号</th><th>来源 OA / PR</th><th>物料 / 规格</th><th class="number">数量</th><th class="number">单价</th><th class="number">金额</th><th class="number">累计到货</th><th>验收</th></tr></thead><tbody><tr v-for="line in activeItem.lines" :key="line.name">
            <td><strong class="serial">{{ line.material_serial }}</strong><small>{{ line.material_code || '-' }}</small></td><td><strong>{{ line.source_request || '-' }}</strong><small>{{ line.source_pr || '-' }}</small></td><td><strong>{{ line.item_name }}</strong><small>{{ line.specification || '-' }}</small></td><td class="number">{{ quantity(line.quantity) }} {{ line.unit }}</td><td class="number">{{ money(line.unit_price, activeItem.currency) }}</td><td class="number strong-number">{{ money(line.amount, activeItem.currency) }}</td><td class="number">{{ quantity(line.received_quantity) }} / {{ quantity(line.quantity) }}</td><td><span :class="['pill', statusClass(line.inspection_status)]">{{ line.inspection_status || '未验收' }}</span></td>
          </tr></tbody></table></div>
          <section v-if="activeItem.fulfillment_records?.length" class="record-history"><header><strong>到货与验收记录</strong><span>{{ activeItem.fulfillment_records.length }} 条不可覆盖的履约记录</span></header><div class="history-list"><article v-for="record in activeItem.fulfillment_records" :key="record.name"><span :class="['pill', record.record_type === '验收' ? 'active' : 'done']">{{ record.record_type }}</span><div><strong>{{ record.record_date }} · {{ record.recorded_by }}</strong><small>{{ record.details.map((line) => `${line.material_serial} ${line.quantity || line.status || ''}${line.unit || ''}`).join('；') }}</small></div><a :href="record.evidence_file" target="_blank" rel="noopener"><FeatherIcon name="paperclip" class="h-4 w-4" />{{ record.original_filename }}</a></article></div></section>
          <div class="operations">
            <section v-if="activeItem.can_record_receipt" class="operation-panel"><header><FeatherIcon name="truck" class="h-4 w-4" /><strong>到货资料登记</strong><span>生产主管演示员工241</span></header><div class="evidence-fields"><label>到货日期<input v-model="receiptDate" type="date" /></label><label class="file-picker"><span>{{ receiptEvidence?.filename || '上传送货单 / 收料单 / 入库单' }}</span><input type="file" accept=".pdf,.png,.jpg,.jpeg,.doc,.docx,.xls,.xlsx" :disabled="uploading" @change="uploadEvidence($event, 'receipt')" /></label></div><div v-for="line in activeItem.lines" :key="line.name" class="operation-row"><span><b>{{ line.material_serial }}</b>{{ line.item_name }}</span><small>未到 {{ quantity(Math.max(0, Number(line.quantity) - Number(line.received_quantity))) }} {{ line.unit }}</small><input v-model.number="receiptDraft[line.name]" type="number" min="0" :max="Number(line.quantity) - Number(line.received_quantity)" step="0.0001" placeholder="本次到货" /></div><button type="button" class="secondary full" :disabled="uploading === 'receipt'" @click="recordReceipt"><FeatherIcon name="save" class="h-4 w-4" />保存到货资料</button></section>
            <section v-if="activeItem.can_record_inspection" class="operation-panel"><header><FeatherIcon name="clipboard" class="h-4 w-4" /><strong>验收资料登记</strong><span>采购</span></header><div class="evidence-fields"><label>验收日期<input v-model="inspectionDate" type="date" /></label><label class="file-picker"><span>{{ inspectionEvidence?.filename || '上传验收记录 / 照片 / 报告' }}</span><input type="file" accept=".pdf,.png,.jpg,.jpeg,.doc,.docx,.xls,.xlsx" :disabled="uploading" @change="uploadEvidence($event, 'inspection')" /></label></div><div v-for="line in activeItem.lines" :key="line.name" class="operation-row"><span><b>{{ line.material_serial }}</b>{{ line.item_name }}</span><small>已到 {{ quantity(line.received_quantity) }} {{ line.unit }}</small><select v-model="inspectionDraft[line.name]" :disabled="Number(line.received_quantity) <= 0"><option value="">不变</option><option>已通过</option><option>不合格</option><option>退货中</option><option>换货中</option></select></div><button type="button" class="secondary full" :disabled="uploading === 'inspection'" @click="recordInspection"><FeatherIcon name="check-square" class="h-4 w-4" />保存验收资料</button></section>
            <section class="operation-panel submit-panel"><header><FeatherIcon name="send" class="h-4 w-4" /><strong>付款审批</strong><span>{{ activeItem.work_status }}</span></header><p v-if="activeItem.can_push_payment">本期付款条件已满足，可以生成采购付款审批单。</p><p v-else-if="activeItem.payment_request">审批单 {{ activeItem.payment_request }} 已生成，后续审批及实际付款在付款审批单中完成。</p><p v-else>{{ activeItem.blockers.join('；') || '当前期次不可提交付款审批' }}</p><button v-if="activeItem.can_push_payment" type="button" class="primary full" @click="submitPaymentApproval"><FeatherIcon name="send" class="h-4 w-4" />提交付款审批</button><button v-else-if="activeItem.payment_request" type="button" class="secondary full" @click="openApproval(activeItem.payment_request)"><FeatherIcon name="external-link" class="h-4 w-4" />进入付款审批单</button></section>
          </div>
        </article><div v-else class="detail-empty"><FeatherIcon name="credit-card" class="h-8 w-8" /><strong>选择付款期次查看完整流程</strong></div>
      </section>
    </template>
    <PreRequestCenter v-else />
  </div>
</template>

<style scoped>
.payment-shell{min-height:calc(100vh - 80px);padding:4px 0 24px;background:#f5f7f7;color:#29383a}.page-head{display:flex;align-items:end;justify-content:space-between;gap:20px;padding:10px 4px 18px;border-bottom:1px solid #cbd4d5}.page-head span{font-size:10px;font-weight:700;color:#657578}.page-head h1{margin:3px 0 0;font-size:23px;line-height:1.25}.page-head p{margin:4px 0 0;font-size:13px;color:#69777a}.icon-button{width:34px;height:34px;display:inline-flex;align-items:center;justify-content:center;border:1px solid #b9c5c7;border-radius:4px;background:#fff;color:#40575a}.tabs{display:flex;margin-top:14px;border-bottom:1px solid #cbd4d5}.tabs button{height:42px;display:flex;align-items:center;gap:7px;padding:0 16px;border:0;border-bottom:3px solid transparent;background:transparent;color:#627174;font-size:13px;font-weight:650}.tabs button.active{border-color:#176f73;background:#edf5f4;color:#16595c}.tabs span,.status-filters span{min-width:18px;padding:1px 5px;border-radius:9px;background:#dfe8e8;font-size:10px;text-align:center}.alert{margin-top:10px;padding:9px 12px;border:1px solid;border-radius:4px;font-size:12px}.success{border-color:#aad5bf;background:#edf8f2;color:#176448}.danger{border-color:#e3b4b0;background:#fff2f1;color:#9d352e}.filters{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:11px 12px;border:1px solid #cfd8d9;border-top:0;background:#fff}.status-filters{display:flex;flex-wrap:wrap;gap:4px}.status-filters button{height:30px;padding:0 9px;border:1px solid #cbd5d6;border-radius:3px;background:#fff;color:#5d6d70;font-size:11px}.status-filters button.active{border-color:#176f73;background:#e8f2f1;color:#155b5e;font-weight:700}.search{width:250px;height:32px;display:flex;align-items:center;gap:6px;padding:0 9px;border:1px solid #c5d0d1;border-radius:3px}.search input{width:100%;border:0;box-shadow:none;font-size:11px}.workspace{display:grid;grid-template-columns:270px minmax(0,1fr);min-height:650px;border:1px solid #cfd8d9;border-top:0;background:#fff}.work-list{max-height:720px;overflow:auto;border-right:1px solid #d5dedf;background:#eef3f3}.work-list>button{width:100%;padding:10px 11px;border:0;border-bottom:1px solid #d6dfe0;background:transparent;text-align:left}.work-list>button:hover,.work-list>button.active{background:#fff}.work-list>button.active{box-shadow:inset 3px 0 #176f73}.work-list>button>div,.work-list footer{display:flex;align-items:center;justify-content:space-between;gap:6px}.work-list b{display:block;margin-top:6px;font-size:11px}.work-list small{display:block;margin-top:3px;color:#718083;font-size:10px}.work-list footer{margin-top:7px;color:#718083;font-size:10px}.work-list footer strong{color:#294346;font-size:11px}.pill{display:inline-flex;align-items:center;padding:2px 7px;border-radius:10px;font-size:10px;font-weight:700;white-space:nowrap}.pill.done{background:#dff2e8;color:#176346}.pill.active{background:#dcecf1;color:#225f71}.pill.wait{background:#f6edd5;color:#7b5b12}.pill.danger{background:#fae5e3;color:#a13c34}.empty{padding:36px 15px;text-align:center;color:#819093;font-size:11px}.detail{min-width:0;padding-bottom:20px;background:#f7f9f9}.document-head{min-height:78px;display:flex;align-items:center;gap:18px;padding:12px 15px;border-bottom:1px solid #d2dcdd;background:#fff}.document-head>div{min-width:0}.document-number{display:block;color:#203538;font-size:17px;font-weight:750}.document-head>div>div{display:flex;align-items:center;gap:8px;margin-top:6px;color:#748184;font-size:10px}.document-head>section{margin-left:auto;text-align:right}.document-head>section small,.document-head>section span{display:block;color:#788588;font-size:10px}.document-head>section strong{display:block;margin:2px 0;color:#164e50;font-size:17px}.primary,.secondary{min-height:34px;display:inline-flex;align-items:center;justify-content:center;gap:7px;padding:0 12px;border-radius:4px;font-size:12px;font-weight:700}.primary{border:1px solid #176f73;background:#176f73;color:#fff}.secondary{border:1px solid #adbbbd;background:#fff;color:#344b4f}.full{width:100%}.facts{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));margin:12px 14px 0;border:1px solid #d4dddd;background:#fff}.facts dl{min-width:0;margin:0;padding:9px 10px;border-right:1px solid #e0e6e7}.facts dt{color:#7a888a;font-size:9px}.facts dd{margin:3px 0 0;overflow:hidden;text-overflow:ellipsis;color:#33494c;font-size:11px;white-space:nowrap}.condition-panel{margin:10px 14px 0;border:1px solid #d4dddd;background:#fff}.condition-panel header{display:flex;align-items:baseline;gap:10px;padding:9px 11px;border-bottom:1px solid #e0e6e7}.condition-panel header strong{font-size:12px}.condition-panel header span,.condition-panel p{color:#788588;font-size:10px}.condition-list{display:flex;flex-wrap:wrap;gap:7px;padding:10px}.condition{display:inline-flex;align-items:center;gap:5px;padding:6px 8px;border:1px solid;border-radius:3px;font-size:10px}.condition.satisfied{border-color:#a9d0bc;background:#edf8f2;color:#176448}.condition.blocked{border-color:#e0c991;background:#fff8e7;color:#765714}.condition.neutral{border-color:#c8d4d6;background:#f2f6f6;color:#496165}.condition-panel p{margin:0;padding:0 10px 10px;color:#8a5914}.table-frame{margin:10px 14px 0;overflow:auto;border:1px solid #d4dddd;background:#fff}.table-frame table{width:100%;min-width:1060px;border-collapse:collapse;table-layout:fixed;font-size:11px}.table-frame th{padding:8px;border-right:1px solid #dce4e5;border-bottom:1px solid #ccd6d7;background:#eaf0f0;color:#43575a;text-align:left}.table-frame td{height:45px;padding:7px 8px;border-right:1px solid #e7ebec;border-bottom:1px solid #e1e6e7}.table-frame strong,.table-frame small{display:block}.table-frame small{margin-top:2px;color:#788588;font-size:9px}.serial{color:#12657a;font-family:ui-monospace,monospace}.number{text-align:right;font-variant-numeric:tabular-nums}.strong-number{font-weight:700;color:#174f52}.operations{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin:10px 14px 0}.operation-panel{align-self:start;border:1px solid #d2dcdd;background:#fff}.operation-panel>header{display:flex;align-items:center;gap:7px;padding:9px 10px;border-bottom:1px solid #e0e6e7}.operation-panel>header strong{font-size:11px}.operation-panel>header span{margin-left:auto;color:#778587;font-size:9px}.operation-row{display:grid;grid-template-columns:minmax(0,1fr) auto 95px;align-items:center;gap:7px;padding:7px 9px;border-bottom:1px solid #edf0f0;font-size:10px}.operation-row span{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.operation-row b{display:block;color:#12657a;font-family:ui-monospace,monospace;font-size:9px}.operation-row small{color:#788588;font-size:9px;white-space:nowrap}.operation-row input,.operation-row select{width:95px;height:28px;border:1px solid #becacc;border-radius:3px;font-size:10px}.operation-panel>.full{margin:9px;width:calc(100% - 18px)}.submit-panel p{min-height:52px;margin:0;padding:12px;color:#657578;font-size:11px;line-height:1.6}.detail-empty{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:10px;color:#849295}.h-4{width:16px;height:16px}.h-8{width:32px;height:32px}@media(max-width:1100px){.facts{grid-template-columns:repeat(3,minmax(0,1fr))}.operations{grid-template-columns:1fr}.workspace{grid-template-columns:230px minmax(0,1fr)}}@media(max-width:760px){.filters{align-items:stretch;flex-direction:column}.search{width:100%}.workspace{display:block}.work-list{max-height:280px;border-right:0;border-bottom:1px solid #d5dedf}.document-head{align-items:flex-start;flex-wrap:wrap}.document-head>section{margin-left:0}.facts{grid-template-columns:repeat(2,minmax(0,1fr));margin-inline:8px}.condition-panel,.table-frame,.operations{margin-inline:8px}}
.evidence-fields{display:grid;grid-template-columns:125px minmax(0,1fr);gap:7px;padding:9px;border-bottom:1px solid #edf0f0}.evidence-fields label{display:grid;gap:3px;color:#67777a;font-size:9px}.evidence-fields input{min-width:0;height:29px;border:1px solid #becacc;border-radius:3px;font-size:10px}.file-picker{position:relative;justify-content:center;padding:0 8px;border:1px dashed #9fb5b7;border-radius:3px;background:#f4f8f8;color:#315b60!important;overflow:hidden}.file-picker span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.file-picker input{position:absolute;inset:0;width:100%;height:100%;opacity:0;cursor:pointer}.record-history{margin:10px 14px 0;border:1px solid #d4dddd;background:#fff}.record-history>header{display:flex;align-items:baseline;gap:10px;padding:9px 11px;border-bottom:1px solid #e0e6e7}.record-history>header strong{font-size:11px}.record-history>header span{color:#788588;font-size:9px}.history-list article{display:grid;grid-template-columns:auto minmax(0,1fr) auto;align-items:center;gap:10px;padding:8px 10px;border-bottom:1px solid #edf0f0}.history-list article:last-child{border-bottom:0}.history-list strong,.history-list small{display:block}.history-list strong{font-size:10px}.history-list small{margin-top:2px;color:#778587;font-size:9px}.history-list a{display:inline-flex;align-items:center;gap:5px;max-width:220px;overflow:hidden;color:#176f73;font-size:10px;text-overflow:ellipsis;white-space:nowrap}
</style>
