<script setup>
// 发票夹：上传 → 识别 → 核对 → 确认。确认后的发票才能在报销、付款里选用；识别不全的字段可以对照原件补。
// 财务在这里处理疑似重复。版式按已确认的设计稿第 5 版；2026-09-30 改版：先进首页（上传区 + 分栏目），
// 点栏目或发票进列表页（原来的列表 + 右侧核对面板）。
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import '../styles/expenseUi.css';
import '../styles/invoiceAttachUi.css';
import InvoicePreviewDrawer from '../components/invoice/InvoicePreviewDrawer.vue';
import { callApi, isFinanceUser, money, pillClass } from '../lib/expenseClaims.js';
import {
  canEditAttachments, confirmBlockers, duplicateText, editableByOwner, folderStatusBar, folderTabsFromCounts, isRequiredField, missingFields,
  retryState, tabStatuses, usedByText,
} from '../lib/invoiceFolderView.js';
import {
  confirmInvoice, createInvoiceBatch, deleteInvoiceSupplementalAttachment, excludeInvoice, fetchInvoiceSupplementalAttachmentPreview,
  listInvoiceSupplementalAttachments, resolveDuplicate, retryInvoice, unconfirmInvoice,
  updateInvoice, updateInvoiceExpenseContext, uploadInvoiceFiles, uploadInvoiceSupplementalAttachment, validateInvoiceFiles,
} from '../lib/invoiceOcr.js';
import { validateExpenseAttachments } from '../lib/expenseWorkflow.js';
import { normalizeFolderTab } from '../lib/dashboardLanding.js';

const finance = isFinanceUser();
const route = useRoute();
const router = useRouter();
const view = computed(() => (route.query.view === 'list' ? 'list' : 'home'));
// 页签来自地址（看板点进来 ?view=list&tab=todo|dup|ok|used|allinv|mine）；财务和员工的页签不同，不属于自己这套的会退到最接近的一个。
const tab = ref(normalizeFolderTab(route.query.tab, finance));
const invoices = ref([]);
const selectedName = ref(String(route.query.invoice || ''));
const ATTENTION = ['待确认', '识别中', '识别失败', '疑似重复'];
const home = reactive({ attention: [], ready: [], duplicates: [], counts: {}, countsAll: {} });
const attentionCount = computed(() => ATTENTION.reduce((sum, status) => sum + Number(home.counts[status] || 0), 0));
const allStatus = computed(() => folderStatusBar(home.countsAll));
const edit = reactive({});
const loading = ref(false);
const busy = ref(false);
const banner = reactive({ ok: '', err: '' });
const previewOpen = ref(false);
const fileInput = ref(null);
const counts = ref({});
const countsAll = ref(null);
const countsMine = ref(null);
const total = ref(0);
const PAGE = 100;
let poller = null;
let alive = true;

// 修复（2026-09-28）：财务也要报销、也要上传发票。财务有“我的发票”页签，在里面上传、核对、确认自己的发票；
// 另外两个页签（疑似重复待处理、全部发票）是只读的财务视图。
const ownView = computed(() => !finance || tab.value === 'mine');
const tabs = computed(() => folderTabsFromCounts(countsAll.value || counts.value, finance, countsMine.value));
const rows = computed(() => invoices.value);
const selected = computed(() => rows.value.find((row) => row.name === selectedName.value) || rows.value[0] || null);
const editable = computed(() => editableByOwner(selected.value, !ownView.value));
const missing = computed(() => (selected.value && editable.value ? missingFields({ ...selected.value, ...edit }) : []));
const currentUser = typeof window !== 'undefined' ? (window.full_name || window.user || '') : '';

// 补充附件（选填：行程单、付款凭证等）：打开一张发票时读取；发票用到单据之前本人可以加、删，之后只能看。
const attachments = ref([]);
const attachBusy = ref(false);
const previewAttachment = ref(null);
const attachmentsEditable = computed(() => ownView.value && canEditAttachments(selected.value));
let attachmentToken = 0;
const star = (field) => (isRequiredField(field) ? '*' : '');

function flash(ok = '', err = '') {
  banner.ok = ok;
  banner.err = err;
}

function go(query = {}) {
  flash();
  router.push({ path: route.path, query });
}

function homeCount(status) {
  return Number(home.counts[status] || 0);
}

function attentionReason(invoice) {
  if (invoice.folder_status === '疑似重复') return duplicateText(invoice);
  if (invoice.folder_status === '识别失败') return invoice.processing_error || '识别失败，可以重新识别';
  if (invoice.folder_status === '识别中') return '正在识别，完成后会自动刷新';
  return missingFields(invoice).length ? `请补全：${missingFields(invoice).join('、')}` : '识别完成，请核对后确认';
}

function refresh() {
  return view.value === 'list' ? load() : loadHome();
}

// 首页：本人需要处理的、可用的发票各取几张，数量用服务端统计；财务另外看全部发票和疑似重复。
async function loadHome() {
  const folder = (listView, statuses, limit) => callApi('invoice_folder_entry.list_invoice_folder', {
    view: listView, statuses: statuses.join(','), limit, offset: 0,
  }, { method: 'GET' });
  try {
    const [attention, ready, duplicates] = await Promise.all([
      folder('mine', ATTENTION, 5),
      folder('mine', ['可用'], 5),
      finance ? folder('all', ['疑似重复'], 20) : null,
    ]);
    home.attention = attention?.invoices || [];
    home.ready = ready?.invoices || [];
    home.duplicates = duplicates?.invoices || [];
    home.counts = attention?.counts || {};
    home.countsAll = duplicates?.counts || {};
    if (poller) clearTimeout(poller);
    if (alive && view.value === 'home' && homeCount('识别中') > 0) poller = setTimeout(refresh, 4000);
  } catch (error) {
    flash('', String(error?.message || error));
  }
}

function hydrate(invoice) {
  Object.keys(edit).forEach((key) => delete edit[key]);
  if (!invoice) return;
  Object.assign(edit, {
    invoice_category: invoice.invoice_category || '', project_name: invoice.project_name || '',
    issue_date: invoice.issue_date || '', invoice_number: invoice.invoice_number || '', invoice_code: invoice.invoice_code || '',
    amount_before_tax: invoice.amount_before_tax ?? '', tax_amount: invoice.tax_amount ?? '',
    total_amount: invoice.total_amount ?? '', expense_description: invoice.expense_description || '',
  });
}

async function load({ more = false } = {}) {
  loading.value = true;
  try {
    const result = await callApi('invoice_folder_entry.list_invoice_folder', {
      view: ownView.value ? 'mine' : 'all',
      statuses: tabStatuses(tab.value).join(','),
      // 刷新时把已经翻出来的几页一起取回，列表不会缩回第一页。
      limit: more ? PAGE : Math.max(PAGE, invoices.value.length),
      offset: more ? invoices.value.length : 0,
    }, { method: 'GET' });
    invoices.value = more ? [...invoices.value, ...(result?.invoices || [])] : (result?.invoices || []);
    counts.value = result?.counts || {};
    countsAll.value = result?.counts_all || null;
    countsMine.value = result?.counts_mine || null;
    total.value = result?.total ?? invoices.value.length;
    if (poller) clearTimeout(poller);
    // 识别是后台任务：还有识别中的发票就每 4 秒刷新一次；离开页面后不再刷新。
    if (alive && Number(counts.value['识别中'] || 0) > 0) poller = setTimeout(refresh, 4000);
  } catch (error) {
    flash('', String(error?.message || error));
  } finally {
    loading.value = false;
  }
}

function select(invoice) {
  selectedName.value = invoice.name;
}

// 修复（2026-09-23）：只在换了一张发票、或这张发票的状态变了时才把识别结果填进表单。
// 原来识别中每 4 秒刷新一次都会重填，把正在修改的内容冲掉；切换页签后表单是空的，
// 点确认会把已保存的费用说明清空。
watch(() => (selected.value ? `${selected.value.name}|${selected.value.folder_status}` : ''), () => hydrate(selected.value), { immediate: true });
watch(() => selected.value?.name || '', loadAttachments, { immediate: true });
watch(tab, () => {
  selectedName.value = String(route.query.invoice || '');
  if (view.value === 'list') load();
});
watch(() => [route.query.tab, route.query.invoice], ([nextTab, invoice]) => {
  const wanted = nextTab ? normalizeFolderTab(nextTab, finance) : '';
  if (wanted && wanted !== tab.value) tab.value = wanted;
  else if (invoice) selectedName.value = String(invoice);
});
watch(view, () => refresh());

async function run(action, okText) {
  busy.value = true;
  flash();
  try {
    const result = await action();
    if (okText) flash(typeof okText === 'function' ? okText(result) : okText);
    await load();
    return result;
  } catch (error) {
    flash('', String(error?.message || error || '操作失败'));
    return null;
  } finally {
    busy.value = false;
  }
}

async function upload(event) {
  const files = event?.target?.files;
  if (!files?.length) return;
  busy.value = true;
  flash();
  try {
    validateInvoiceFiles(files);
    const batch = await createInvoiceBatch();
    const results = await uploadInvoiceFiles(files, batch.name);
    const failed = results.filter((result) => result.error);
    flash(`已上传 ${results.length - failed.length} 张发票，正在识别`, failed.length ? `${failed.length} 个文件上传失败：${failed[0].error}` : '');
    const target = finance ? 'mine' : 'todo';
    // 从首页上传：进列表页看识别结果。
    if (view.value !== 'list') go({ view: 'list', tab: target });
    else if (tab.value === target) await load();
    else go({ view: 'list', tab: target });
  } catch (error) {
    flash('', String(error?.message || error));
  } finally {
    busy.value = false;
    if (fileInput.value) fileInput.value.value = '';
  }
}

async function saveEdits() {
  const invoice = selected.value;
  await updateInvoice(invoice.name, {
    invoice_category: edit.invoice_category, project_name: edit.project_name, issue_date: edit.issue_date,
    invoice_number: edit.invoice_number, invoice_code: edit.invoice_code, amount_before_tax: edit.amount_before_tax, tax_amount: edit.tax_amount,
    total_amount: edit.total_amount,
  });
  if ((edit.expense_description || '') !== (invoice.expense_description || '')) {
    await updateInvoiceExpenseContext(invoice.name, edit.expense_description || '');
  }
}

async function confirm() {
  const problems = confirmBlockers({ ...selected.value, ...edit });
  if (problems.length) {
    flash('', problems[0]);
    return;
  }
  await run(async () => {
    await saveEdits();
    const result = await confirmInvoice(selected.value.name);
    if (result?.conflict?.code === 'duplicate') {
      await load();
      throw new Error(`发票号码与已确认的 ${result.conflict.duplicate_of} 相同，已标为疑似重复，等待财务处理`);
    }
    return result;
  }, '发票已确认，可以在报销、付款里选用');
}

async function saveOnly() {
  await run(saveEdits, '已保存修改');
}

// 本人排除自己的发票（多半是传错了）不用写原因，直接确定就记「传错了」；财务确认重复必须写原因。
async function exclude(reasonPrompt = '排除这张发票。原因可以不改，默认记为「传错了」。', { required = false } = {}) {
  const typed = window.prompt(reasonPrompt, required ? '' : '传错了');
  if (typed === null) return;
  const reason = typed.trim();
  if (required && !reason) {
    flash('', '请填写排除原因');
    return;
  }
  await run(() => excludeInvoice(selected.value.name, reason), '发票已排除');
}

// 已确认、还没用到任何单据的发票可以撤回确认，回到「待确认」重新修改。
async function undoConfirm() {
  if (!window.confirm('撤回确认后，这张发票回到「待确认」，可以重新修改识别内容。确定吗？')) return;
  await run(() => unconfirmInvoice(selected.value.name, '用户撤回确认'), '已撤回确认，可以重新修改识别内容');
}

async function notDuplicate() {
  const reason = (window.prompt('请填写复核结论（例如：号码相同但是两张不同的发票）') || '').trim();
  if (!reason) return;
  await run(() => resolveDuplicate(selected.value.name, reason), '已解除重复，发票退回员工确认');
}

async function retry() {
  await run(() => retryInvoice(selected.value.name), '已重新提交识别');
}

async function loadAttachments() {
  const invoice = selected.value;
  const token = ++attachmentToken;
  attachments.value = [];
  if (!invoice) return;
  try {
    const list = await listInvoiceSupplementalAttachments(invoice.name);
    if (token === attachmentToken) attachments.value = list || [];
  } catch {
    // 读不到附件不挡核对和确认，当作没有。
  }
}

async function addAttachments(event) {
  const input = event?.target;
  const files = Array.from(input?.files || []);
  const invoice = selected.value;
  if (!files.length || !invoice) return;
  try {
    validateExpenseAttachments(files, attachments.value.length);
  } catch (error) {
    flash('', String(error?.message || error));
    if (input) input.value = '';
    return;
  }
  attachBusy.value = true;
  flash();
  try {
    for (const file of files) {
      const saved = await uploadInvoiceSupplementalAttachment(invoice.name, file);
      if (selected.value?.name === invoice.name) attachments.value = [...attachments.value, saved];
    }
    flash('补充附件已上传');
  } catch (error) {
    flash('', String(error?.message || error));
  } finally {
    attachBusy.value = false;
    if (input) input.value = '';
  }
}

async function removeAttachment(file) {
  const invoice = selected.value;
  if (!invoice || !window.confirm(`删除补充附件“${file.original_filename}”吗？`)) return;
  attachBusy.value = true;
  flash();
  try {
    await deleteInvoiceSupplementalAttachment(invoice.name, file.name);
    attachments.value = attachments.value.filter((item) => item.name !== file.name);
    flash('补充附件已删除');
  } catch (error) {
    flash('', String(error?.message || error));
  } finally {
    attachBusy.value = false;
  }
}

onMounted(refresh);
onBeforeUnmount(() => {
  alive = false;
  if (poller) clearTimeout(poller);
});
</script>

<template>
  <div class="xp">
    <div class="ph">
      <div>
        <div v-if="view === 'list'" class="crumb"><button type="button" class="link" @click="go({})">发票夹</button> › 列表</div>
        <h3>发票夹</h3>
        <div class="muted">{{ finance ? '处理疑似重复的发票；自己的发票在“我的发票”里上传、核对、确认。' : '先上传、识别、核对，确认后的发票才能在报销和付款里选用。' }}</div>
      </div>
      <label class="btn pri" :class="{ disabled: busy }">
        ＋ 上传发票
        <input ref="fileInput" type="file" multiple accept=".pdf,.jpg,.jpeg,.png" hidden :disabled="busy" @change="upload" />
      </label>
    </div>
    <div v-if="banner.ok" class="banner ok">{{ banner.ok }}</div>
    <div v-if="banner.err" class="banner err" role="alert">{{ banner.err }}</div>

    <!-- ============================== 首页（2026-09-30 改版） ============================== -->
    <template v-if="view === 'home'">
      <label class="drop-zone" :class="{ disabled: busy }">
        <svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="#8A93A3" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 16V4"></path><path d="M7 9l5-5 5 5"></path><path d="M4 16v3a1 1 0 001 1h14a1 1 0 001-1v-3"></path></svg>
        <span class="grow-col"><b>点这里选择发票上传</b><span class="muted">PDF 或照片，一次最多 20 个文件；识别完会自动刷新</span></span>
        <span v-if="homeCount('识别中')" class="recognizing"><span class="muted">正在识别 {{ homeCount('识别中') }} 张</span><span class="pulse"><i></i></span></span>
        <span class="btn">选择文件</span>
        <input type="file" multiple accept=".pdf,.jpg,.jpeg,.png" hidden :disabled="busy" @change="upload" />
      </label>

      <div class="home-grid">
        <section class="panel">
          <div class="pt"><span>需要你看一下 <span class="count-pill">{{ attentionCount }}</span></span><button type="button" class="link" @click="go({ view: 'list', tab: finance ? 'mine' : 'todo' })">全部 →</button></div>
          <button v-for="invoice in home.attention" :key="invoice.name" type="button" class="folder-row" @click="go({ view: 'list', tab: finance ? 'mine' : invoice.folder_status === '疑似重复' ? 'dup' : 'todo', invoice: invoice.name })">
            <span :class="pillClass(invoice.folder_status)">{{ invoice.folder_status }}</span>
            <span class="grow-col"><b class="ellipsis">{{ invoice.project_name || invoice.original_filename || '未识别' }}</b><span class="muted ellipsis">{{ attentionReason(invoice) }}</span></span>
            <span class="amount">{{ Number(invoice.total_amount) ? '¥ ' + money(invoice.total_amount) : '—' }}</span>
          </button>
          <div v-if="!home.attention.length" class="empty">没有需要处理的发票</div>
        </section>

        <section class="panel">
          <div class="pt"><span>可以用来报销、付款 <span class="muted">{{ homeCount('可用') }} 张</span></span><button type="button" class="link" @click="router.push({ path: '/approval/claim', query: { view: 'new', pick: 'all' } })">用这些发票新建报销 →</button></div>
          <button v-for="invoice in home.ready" :key="invoice.name" type="button" class="folder-row" @click="go({ view: 'list', tab: finance ? 'mine' : 'ok', invoice: invoice.name })">
            <span class="grow-col"><span class="ellipsis">{{ invoice.project_name || '未填写项目名称' }}</span><span class="muted num">{{ invoice.invoice_number }} · {{ invoice.issue_date || '—' }}</span></span>
            <span class="amount">¥ {{ money(invoice.total_amount) }}</span>
          </button>
          <div v-if="!home.ready.length" class="empty">还没有确认好的发票</div>
        </section>
      </div>

      <div class="home-grid">
        <section class="panel">
          <div class="pt"><span>已用于报销 / 付款</span><button type="button" class="link" @click="go({ view: 'list', tab: finance ? 'mine' : 'used' })">全部 →</button></div>
          <div class="bucket-cards">
            <div class="bucket-card static"><span class="muted">已使用</span><b>{{ homeCount('已使用') }} 张</b></div>
            <div class="bucket-card static"><span class="muted">可用</span><b>{{ homeCount('可用') }} 张</b></div>
            <div class="bucket-card static"><span class="muted">待确认 / 识别失败</span><b>{{ homeCount('待确认') + homeCount('识别失败') }} 张</b></div>
          </div>
        </section>

        <section v-if="finance" class="panel">
          <div class="pt"><span>全部发票 <span class="tag">财务可见</span></span><button type="button" class="link" @click="go({ view: 'list', tab: 'allinv' })">全部列表 →</button></div>
          <div class="stack-bar"><i v-for="item in allStatus" :key="item.label" :style="{ width: item.width, background: item.color }"></i></div>
          <div class="bucket-legend"><span v-for="item in allStatus" :key="item.label"><i :style="{ background: item.color }"></i>{{ item.label }} {{ item.count }}</span></div>
          <button v-if="home.duplicates.length" type="button" class="link" @click="go({ view: 'list', tab: 'dup' })">{{ home.duplicates.length }} 张疑似重复等你处理 →</button>
        </section>
      </div>
    </template>

    <template v-else>
    <div class="tabs" role="tablist">
      <button v-for="item in tabs" :key="item.key" role="tab" :aria-selected="tab === item.key" @click="go({ view: 'list', tab: item.key })">
        {{ item.label }}<span class="c">{{ item.count }}</span>
      </button>
    </div>

    <div class="inv-grid">
      <div class="panel flush">
        <div class="tbl narrow">
          <table>
            <thead><tr><th>发票号码</th><th>项目名称</th><th v-if="!ownView">上传人</th><th class="r">合计</th><th>状态</th></tr></thead>
            <tbody>
              <tr v-for="invoice in rows" :key="invoice.name" class="row-sel" :class="{ on: selected?.name === invoice.name }" tabindex="0"
                @click="select(invoice)" @keydown.enter="select(invoice)">
                <td class="num"><template v-if="invoice.invoice_number">{{ invoice.invoice_number }}</template><span v-else class="muted">未识别</span></td>
                <td>{{ invoice.project_name || '—' }}</td>
                <td v-if="!ownView">{{ invoice.owner_name || invoice.owner || '—' }}</td>
                <td class="r num">{{ money(invoice.total_amount) }}</td>
                <td><span :class="pillClass(invoice.folder_status)">{{ invoice.folder_status }}</span></td>
              </tr>
              <tr v-if="!rows.length"><td :colspan="ownView ? 4 : 5" class="empty">{{ loading ? '正在加载…' : '这里没有发票' }}</td></tr>
              <tr v-if="rows.length && rows.length < total">
                <td :colspan="ownView ? 4 : 5" class="empty">
                  <button type="button" class="btn sm" :disabled="loading" @click="load({ more: true })">加载更多（还有 {{ total - rows.length }} 张）</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div>
        <div v-if="!selected" class="panel empty">选择左侧一张发票查看</div>
        <div v-else class="panel">
          <div class="pt">
            <span>{{ selected.invoice_number || '未识别号码' }} <span :class="pillClass(selected.folder_status)">{{ selected.folder_status }}</span></span>
            <span v-if="selected.used_by" class="muted">用于 {{ usedByText(selected) }}</span>
          </div>
          <div class="thumb">
            <span>{{ selected.original_filename || '发票原件' }}</span>
            <button type="button" class="btn sm" @click="previewOpen = true">查看原件</button>
          </div>
          <div v-if="selected.folder_status === '识别中'" class="muted">正在识别，识别结果出来后会自动刷新。</div>
          <div v-if="selected.processing_error" class="err">识别失败：{{ selected.processing_error }}</div>
          <div v-if="missing.length" class="err">识别不完整：{{ missing.join('、') }} 未识别，请对照原件补全</div>
          <div v-if="selected.folder_status === '疑似重复'" class="err">
            {{ duplicateText(selected) }}，{{ ownView ? '等待财务处理' : '请确认是否为同一张发票' }}
          </div>
          <div v-if="ownView && retryState(selected) === 'exhausted'" class="err">这张发票已经重试 3 次仍没有识别出来，请排除后重新上传更清晰的文件。</div>
          <div v-if="ownView && retryState(selected) === 'stuck'" class="muted">识别超过 15 分钟还没有结果，可以重新识别。</div>

          <h4>识别结果<template v-if="editable">（可修改）</template></h4>
          <div class="form">
            <div class="f"><label>发票类别</label><input v-model="edit.invoice_category" :readonly="!editable" :placeholder="editable ? '识别不出来可以留空' : ''" /></div>
            <div class="f"><label>项目名称<b>{{ star('project_name') }}</b></label><input v-model="edit.project_name" :readonly="!editable" /><div class="h">发票上的货物或服务名称</div></div>
            <div class="f"><label>开票日期<b>{{ star('issue_date') }}</b></label><input v-model="edit.issue_date" type="date" :readonly="!editable" /></div>
            <div class="f"><label>发票号码<b>{{ star('invoice_number') }}</b></label><input v-model="edit.invoice_number" :readonly="!editable" /><div class="h">查重只看号码；识别不出来的请对照原件填写</div></div>
            <div class="f"><label>发票代码</label><input v-model="edit.invoice_code" :readonly="!editable" /><div class="h">老版发票左上角 10 或 12 位；全电发票没有，可不填</div></div>
            <div class="f"><label>税前金额</label><input v-model="edit.amount_before_tax" type="number" step="0.01" :readonly="!editable" /></div>
            <div class="f"><label>税额</label><input v-model="edit.tax_amount" type="number" step="0.01" :readonly="!editable" /></div>
            <div class="f"><label>合计<b>{{ star('total_amount') }}</b></label><input v-model="edit.total_amount" type="number" step="0.01" :readonly="!editable" /></div>
            <div class="f"><label>费用说明<b>{{ star('expense_description') }}</b></label><input v-model="edit.expense_description" :readonly="!editable" /><div class="h">写清楚这笔钱花在什么上，审批人会看到</div></div>
          </div>

          <h4>补充附件 <span class="muted">选填 · 行程单、付款凭证等，最多 10 个；审批人和出纳会和发票一起看到</span></h4>
          <div class="attach-list">
            <span v-for="file in attachments" :key="file.name" class="attach-chip">
              <button type="button" class="link" :title="file.original_filename" @click="previewAttachment = file">{{ file.original_filename }}</button>
              <button v-if="attachmentsEditable" type="button" class="x" title="删除附件" aria-label="删除附件" :disabled="attachBusy" @click="removeAttachment(file)">×</button>
            </span>
            <span v-if="!attachments.length" class="muted">暂无补充附件</span>
            <label v-if="attachmentsEditable" class="btn sm" :class="{ disabled: attachBusy }">
              {{ attachBusy ? '上传中…' : '＋ 添加附件' }}
              <input type="file" multiple accept=".pdf,.jpg,.jpeg,.png" hidden :disabled="attachBusy" @change="addAttachments" />
            </label>
          </div>

          <div class="actions">
            <template v-if="editable">
              <button type="button" class="btn pri" :disabled="busy" @click="confirm">确认发票</button>
              <button type="button" class="btn" :disabled="busy" @click="saveOnly">只保存修改</button>
              <button type="button" class="btn danger" :disabled="busy" @click="exclude()">排除</button>
            </template>
            <template v-else-if="ownView && ['retry', 'stuck', 'exhausted'].includes(retryState(selected))">
              <button v-if="retryState(selected) !== 'exhausted'" type="button" class="btn pri" :disabled="busy" @click="retry">重新识别</button>
              <button type="button" class="btn danger" :disabled="busy" @click="exclude()">排除</button>
            </template>
            <template v-else-if="ownView && selected.folder_status === '可用'">
              <button type="button" class="btn" :disabled="busy" @click="undoConfirm">撤回确认</button>
              <span class="muted">还没用到任何单据，撤回后可以重新修改。</span>
            </template>
            <template v-else-if="ownView && selected.folder_status === '已使用'">
              <span class="muted">已用于 {{ usedByText(selected) }}；要先从那张单据里移出这张发票，才能撤回确认。</span>
            </template>
            <template v-else-if="!ownView && selected.folder_status === '疑似重复'">
              <button type="button" class="btn" :disabled="busy" @click="notDuplicate">不是重复，退回员工确认</button>
              <button type="button" class="btn pri" :disabled="busy" @click="exclude('确认是重复发票，请填写排除原因', { required: true })">确认重复，排除</button>
            </template>
          </div>
        </div>
      </div>
    </div>

    </template>

    <InvoicePreviewDrawer :open="previewOpen" :invoice="selected?.name || ''" :current-user="currentUser" :title="selected?.invoice_number || '发票原件'" @close="previewOpen = false" />
    <InvoicePreviewDrawer :open="Boolean(previewAttachment)" :invoice="previewAttachment?.name || ''" :current-user="currentUser" :preview-loader="fetchInvoiceSupplementalAttachmentPreview" :title="previewAttachment?.original_filename || '补充附件'" @close="previewAttachment = null" />
  </div>
</template>
