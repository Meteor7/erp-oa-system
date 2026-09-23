<script setup>
// 发票夹：上传 → 识别 → 核对 → 确认。确认后的发票才能在报销、付款里选用；识别不全的字段可以对照原件补。
// 财务在这里处理疑似重复。版式按已确认的设计稿第 5 版。
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue';
import '../styles/expenseUi.css';
import InvoicePreviewDrawer from '../components/invoice/InvoicePreviewDrawer.vue';
import { callApi, isFinanceUser, money, pillClass } from '../lib/expenseClaims.js';
import { confirmBlockers, editableByOwner, filterFolder, folderTabs, missingFields, stillRecognizing, usedByText } from '../lib/invoiceFolderView.js';
import {
  confirmInvoice, createInvoiceBatch, excludeInvoice, resolveDuplicate, retryInvoice,
  updateInvoice, updateInvoiceExpenseContext, uploadInvoiceFiles, validateInvoiceFiles,
} from '../lib/invoiceOcr.js';

const finance = isFinanceUser();
const tab = ref(finance ? 'dup' : 'list');
const invoices = ref([]);
const selectedName = ref('');
const edit = reactive({});
const loading = ref(false);
const busy = ref(false);
const banner = reactive({ ok: '', err: '' });
const previewOpen = ref(false);
const fileInput = ref(null);
let poller = null;

const tabs = computed(() => folderTabs(invoices.value, finance));
const rows = computed(() => filterFolder(invoices.value, finance && tab.value === 'allinv' ? 'list' : tab.value));
const selected = computed(() => rows.value.find((row) => row.name === selectedName.value) || rows.value[0] || null);
const editable = computed(() => editableByOwner(selected.value, finance));
const missing = computed(() => (selected.value && editable.value ? missingFields({ ...selected.value, ...edit }) : []));
const currentUser = typeof window !== 'undefined' ? (window.full_name || window.user || '') : '';

function flash(ok = '', err = '') {
  banner.ok = ok;
  banner.err = err;
}

function hydrate(invoice) {
  Object.keys(edit).forEach((key) => delete edit[key]);
  if (!invoice) return;
  Object.assign(edit, {
    invoice_category: invoice.invoice_category || '', project_name: invoice.project_name || '',
    issue_date: invoice.issue_date || '', invoice_number: invoice.invoice_number || '',
    amount_before_tax: invoice.amount_before_tax ?? '', tax_amount: invoice.tax_amount ?? '',
    total_amount: invoice.total_amount ?? '', expense_description: invoice.expense_description || '',
  });
}

async function load() {
  loading.value = true;
  try {
    const result = await callApi('invoice_folder_entry.list_invoice_folder', { view: finance ? 'all' : 'mine' }, { method: 'GET' });
    invoices.value = result?.invoices || [];
    hydrate(selected.value);
    if (poller) clearTimeout(poller);
    // 识别是后台任务：还有识别中的发票就每 4 秒刷新一次。
    if (stillRecognizing(invoices.value)) poller = setTimeout(load, 4000);
  } catch (error) {
    flash('', String(error?.message || error));
  } finally {
    loading.value = false;
  }
}

function select(invoice) {
  selectedName.value = invoice.name;
  hydrate(invoice);
}

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
    tab.value = 'todo';
    await load();
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
    invoice_number: edit.invoice_number, amount_before_tax: edit.amount_before_tax, tax_amount: edit.tax_amount,
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
      throw new Error(`发票号码、开票日期和金额与 ${result.conflict.duplicate_of} 相同，已标为疑似重复，等待财务处理`);
    }
    return result;
  }, '发票已确认，可以在报销、付款里选用');
}

async function saveOnly() {
  await run(saveEdits, '已保存修改');
}

async function exclude(reasonPrompt = '请填写排除原因') {
  const reason = (window.prompt(reasonPrompt) || '').trim();
  if (!reason) return;
  await run(() => excludeInvoice(selected.value.name, reason), '发票已排除');
}

async function notDuplicate() {
  const reason = (window.prompt('请填写复核结论（例如：号码相同但是两张不同的发票）') || '').trim();
  if (!reason) return;
  await run(() => resolveDuplicate(selected.value.name, reason), '已解除重复，发票退回员工确认');
}

async function retry() {
  await run(() => retryInvoice(selected.value.name), '已重新提交识别');
}

onMounted(load);
onBeforeUnmount(() => { if (poller) clearTimeout(poller); });
</script>

<template>
  <div class="xp">
    <div class="ph">
      <div>
        <h3>发票夹</h3>
        <div class="muted">{{ finance ? '处理疑似重复的发票，确认是否真的重复。' : '先上传、识别、核对，确认后的发票才能在报销和付款里选用。' }}</div>
      </div>
      <label v-if="!finance" class="btn pri" :class="{ disabled: busy }">
        ＋ 上传发票
        <input ref="fileInput" type="file" multiple accept=".pdf,.jpg,.jpeg,.png" hidden :disabled="busy" @change="upload" />
      </label>
    </div>
    <div class="tabs" role="tablist">
      <button v-for="item in tabs" :key="item.key" role="tab" :aria-selected="tab === item.key" @click="tab = item.key; selectedName = ''; hydrate(null)">
        {{ item.label }}<span class="c">{{ item.count }}</span>
      </button>
    </div>
    <div v-if="banner.ok" class="banner ok">{{ banner.ok }}</div>
    <div v-if="banner.err" class="banner err" role="alert">{{ banner.err }}</div>

    <div class="inv-grid">
      <div class="panel flush">
        <div class="tbl narrow">
          <table>
            <thead><tr><th>发票号码</th><th>项目名称</th><th v-if="finance">上传人</th><th class="r">合计</th><th>状态</th></tr></thead>
            <tbody>
              <tr v-for="invoice in rows" :key="invoice.name" class="row-sel" :class="{ on: selected?.name === invoice.name }" tabindex="0"
                @click="select(invoice)" @keydown.enter="select(invoice)">
                <td class="num"><template v-if="invoice.invoice_number">{{ invoice.invoice_number }}</template><span v-else class="muted">未识别</span></td>
                <td>{{ invoice.project_name || '—' }}</td>
                <td v-if="finance">{{ invoice.owner_name || invoice.owner || '—' }}</td>
                <td class="r num">{{ money(invoice.total_amount) }}</td>
                <td><span :class="pillClass(invoice.folder_status)">{{ invoice.folder_status }}</span></td>
              </tr>
              <tr v-if="!rows.length"><td :colspan="finance ? 5 : 4" class="empty">{{ loading ? '正在加载…' : '这里没有发票' }}</td></tr>
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
            发票号码、开票日期和合计金额与 {{ selected.duplicate_of }} 相同，{{ finance ? '请确认是否为同一张发票' : '等待财务处理' }}
          </div>

          <h4>识别结果<template v-if="editable">（可修改）</template></h4>
          <div class="form">
            <div class="f"><label>发票类别</label><input v-model="edit.invoice_category" :readonly="!editable" /></div>
            <div class="f"><label>项目名称</label><input v-model="edit.project_name" :readonly="!editable" /><div class="h">发票上的货物或服务名称</div></div>
            <div class="f"><label>开票日期<b>*</b></label><input v-model="edit.issue_date" type="date" :readonly="!editable" /></div>
            <div class="f"><label>发票号码<b>*</b></label><input v-model="edit.invoice_number" :readonly="!editable" /></div>
            <div class="f"><label>税前金额</label><input v-model="edit.amount_before_tax" type="number" step="0.01" :readonly="!editable" /></div>
            <div class="f"><label>税额</label><input v-model="edit.tax_amount" type="number" step="0.01" :readonly="!editable" /></div>
            <div class="f"><label>合计<b>*</b></label><input v-model="edit.total_amount" type="number" step="0.01" :readonly="!editable" /></div>
            <div class="f"><label>费用说明<b>*</b></label><input v-model="edit.expense_description" :readonly="!editable" /><div class="h">写清楚这笔钱花在什么上，审批人会看到</div></div>
          </div>

          <div class="actions">
            <template v-if="editable">
              <button type="button" class="btn pri" :disabled="busy" @click="confirm">确认发票</button>
              <button type="button" class="btn" :disabled="busy" @click="saveOnly">只保存修改</button>
              <button type="button" class="btn danger" :disabled="busy" @click="exclude()">排除</button>
            </template>
            <template v-else-if="!finance && selected.folder_status === '识别失败'">
              <button type="button" class="btn pri" :disabled="busy" @click="retry">重新识别</button>
              <button type="button" class="btn danger" :disabled="busy" @click="exclude()">排除</button>
            </template>
            <template v-else-if="finance && selected.folder_status === '疑似重复'">
              <button type="button" class="btn" :disabled="busy" @click="notDuplicate">不是重复，退回员工确认</button>
              <button type="button" class="btn pri" :disabled="busy" @click="exclude('确认是重复发票，请填写排除原因')">确认重复，排除</button>
            </template>
          </div>
        </div>
      </div>
    </div>

    <InvoicePreviewDrawer :open="previewOpen" :invoice="selected?.name || ''" :current-user="currentUser" :title="selected?.invoice_number || '发票原件'" @close="previewOpen = false" />
  </div>
</template>
