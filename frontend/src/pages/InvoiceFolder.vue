<script setup>
// 发票夹：上传 → 识别 → 核对 → 确认。确认后的发票变成"可用"，报销和付款从这里选；
// 被单据用掉后变成"已使用"。识别不出来的字段可以手工改，疑似重复交给财务处理。
import { computed, onMounted, onBeforeUnmount, ref } from 'vue';
import {
  canConfirm, canEditFields, canRetry, confirmBlockers, folderTone, missingFields,
  stillRecognizing, tabsWithCounts, usedByText,
} from '../lib/invoiceFolderView.js';
import { callApi, money } from '../lib/expenseClaims.js';
import {
  confirmInvoice, createInvoiceBatch, excludeInvoice, resolveDuplicate, retryInvoice,
  updateInvoice, updateInvoiceExpenseContext, uploadInvoiceFiles, validateInvoiceFiles,
} from '../lib/invoiceOcr.js';

const tab = ref('');
const invoices = ref([]);
const counts = ref({});
const duplicates = ref([]);
const financeView = ref(false);
const loading = ref(false);
const busy = ref(false);
const errorMessage = ref('');
const message = ref('');
const edits = ref({});
const fileInput = ref(null);
let poller = null;

const isFinance = computed(() => ((typeof window !== 'undefined' && window.roles) || []).some((role) => ['System Manager', 'Accounts User'].includes(role)));
const tabs = computed(() => tabsWithCounts(counts.value));
const rows = computed(() => invoices.value);

function fail(error) {
  errorMessage.value = String(error?.message || error || '操作失败');
}

async function load() {
  loading.value = true;
  try {
    const result = await callApi('invoice_folder_entry.list_invoice_folder', { status: tab.value }, { method: 'GET' });
    invoices.value = result?.invoices || [];
    counts.value = result?.counts || {};
    edits.value = Object.fromEntries(invoices.value.filter(canEditFields).map((invoice) => [invoice.name, { ...invoice }]));
    if (financeView.value) duplicates.value = await callApi('invoice_folder_entry.list_duplicate_invoices', {}, { method: 'GET' }) || [];
    schedulePoll();
  } catch (error) {
    fail(error);
  } finally {
    loading.value = false;
  }
}

function schedulePoll() {
  if (poller) clearTimeout(poller);
  // 识别是后台任务，识别中的发票每 4 秒刷新一次，直到全部出结果。
  if (stillRecognizing(invoices.value)) poller = setTimeout(load, 4000);
}

async function run(action, successMessage) {
  busy.value = true;
  errorMessage.value = '';
  message.value = '';
  try {
    await action();
    message.value = successMessage;
    await load();
  } catch (error) {
    fail(error);
  } finally {
    busy.value = false;
  }
}

async function upload(event) {
  const files = event?.target?.files;
  if (!files?.length) return;
  busy.value = true;
  errorMessage.value = '';
  message.value = '';
  try {
    validateInvoiceFiles(files);
    const batch = await createInvoiceBatch();
    const results = await uploadInvoiceFiles(files, batch.name);
    const failed = results.filter((result) => result.error);
    message.value = `已上传 ${results.length - failed.length} 张发票，正在识别`;
    if (failed.length) errorMessage.value = `${failed.length} 个文件上传失败：${failed[0].error}`;
    await load();
  } catch (error) {
    fail(error);
  } finally {
    busy.value = false;
    if (fileInput.value) fileInput.value.value = '';
  }
}

async function saveFields(invoice) {
  const draft = edits.value[invoice.name] || {};
  await run(async () => {
    await updateInvoice(invoice.name, {
      invoice_category: draft.invoice_category || '',
      project_name: draft.project_name || '',
      issue_date: draft.issue_date || '',
      invoice_number: draft.invoice_number || '',
      amount_before_tax: draft.amount_before_tax ?? '',
      tax_amount: draft.tax_amount ?? '',
      total_amount: draft.total_amount ?? '',
    });
    if ((draft.expense_description || '') !== (invoice.expense_description || '')) {
      await updateInvoiceExpenseContext(invoice.name, draft.expense_description || '');
    }
  }, '发票信息已保存');
}

async function confirm(invoice) {
  const draft = edits.value[invoice.name] || invoice;
  const problems = confirmBlockers(draft);
  if (problems.length) {
    errorMessage.value = problems[0];
    return;
  }
  await run(async () => {
    await saveFieldsQuietly(invoice, draft);
    const result = await confirmInvoice(invoice.name);
    if (result?.conflict?.code === 'duplicate') {
      errorMessage.value = `发票号码、开票日期和金额与 ${result.conflict.duplicate_of} 相同，已标为疑似重复，请联系财务处理。`;
    }
  }, '发票已确认，可以在报销、付款里选用');
}

async function saveFieldsQuietly(invoice, draft) {
  await updateInvoice(invoice.name, {
    invoice_category: draft.invoice_category || '',
    project_name: draft.project_name || '',
    issue_date: draft.issue_date || '',
    invoice_number: draft.invoice_number || '',
    amount_before_tax: draft.amount_before_tax ?? '',
    tax_amount: draft.tax_amount ?? '',
    total_amount: draft.total_amount ?? '',
  });
  if ((draft.expense_description || '') !== (invoice.expense_description || '')) {
    await updateInvoiceExpenseContext(invoice.name, draft.expense_description || '');
  }
}

async function retry(invoice) {
  await run(() => retryInvoice(invoice.name), '已重新识别');
}

async function exclude(invoice) {
  const reason = (window.prompt('请填写排除原因') || '').trim();
  if (!reason) return;
  await run(() => excludeInvoice(invoice.name, reason), '发票已排除');
}

async function resolve(invoice) {
  const reason = (window.prompt('请填写解除重复的复核原因') || '').trim();
  if (!reason) return;
  await run(() => resolveDuplicate(invoice.name, reason), '已解除重复，发票回到待确认');
}

async function toggleFinance() {
  financeView.value = !financeView.value;
  await load();
}

onMounted(load);
onBeforeUnmount(() => { if (poller) clearTimeout(poller); });
</script>

<template>
  <div class="space-y-4">
    <section class="rounded-lg border bg-white p-5 shadow-sm">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 class="text-xl font-semibold">发票夹</h1>
          <p class="mt-1 text-sm text-gray-500">上传 → 识别 → 核对 → 确认。确认后的发票在报销、付款里可选；识别不出来的字段可以手工填写。</p>
        </div>
        <div class="flex items-center gap-2">
          <button v-if="isFinance" type="button" class="rounded border px-3 py-1.5 text-sm" @click="toggleFinance">
            {{ financeView ? '返回我的发票夹' : '疑似重复处理' }}
          </button>
          <label class="cursor-pointer rounded bg-gray-900 px-3 py-1.5 text-sm text-white">
            上传发票
            <input ref="fileInput" type="file" multiple accept=".pdf,.jpg,.jpeg,.png" class="hidden" :disabled="busy" @change="upload" />
          </label>
        </div>
      </div>
      <div v-if="!financeView" class="mt-4 flex flex-wrap gap-2">
        <button v-for="item in tabs" :key="item.key" type="button" class="rounded px-3 py-1.5 text-sm"
          :class="tab === item.key ? 'bg-gray-900 text-white' : 'border'" @click="tab = item.key; load()">
          {{ item.label }}<span class="ml-1 text-xs opacity-70">{{ item.count }}</span>
        </button>
      </div>
      <p v-if="errorMessage" class="mt-3 rounded bg-red-50 px-3 py-2 text-sm text-red-700">{{ errorMessage }}</p>
      <p v-if="message" class="mt-3 rounded bg-emerald-50 px-3 py-2 text-sm text-emerald-700">{{ message }}</p>
    </section>

    <section v-if="financeView" class="rounded-lg border bg-white p-5 shadow-sm">
      <h2 class="font-semibold">疑似重复发票（{{ duplicates.length }}）</h2>
      <p class="mt-1 text-xs text-gray-500">发票号码、开票日期和合计金额与已确认发票相同的会停在这里，由财务核实后解除或排除。</p>
      <table class="mt-3 min-w-full text-sm">
        <thead><tr class="border-b text-left text-gray-500"><th class="p-2">发票</th><th class="p-2">上传人</th><th class="p-2 text-right">合计</th><th class="p-2">重复对象</th><th class="p-2">操作</th></tr></thead>
        <tbody>
          <tr v-for="invoice in duplicates" :key="invoice.name" class="border-b">
            <td class="p-2">{{ invoice.invoice_number || invoice.name }}<div class="text-xs text-gray-500">{{ invoice.project_name }} · {{ invoice.issue_date }}</div></td>
            <td class="p-2">{{ invoice.uploaded_by }}</td>
            <td class="p-2 text-right">{{ money(invoice.total_amount) }}</td>
            <td class="p-2">
              <div v-if="invoice.duplicate_original">{{ invoice.duplicate_original.invoice_number || invoice.duplicate_original.name }}
                <div class="text-xs text-gray-500">{{ usedByText(invoice.duplicate_original) || '未被单据使用' }}</div>
              </div>
              <span v-else class="text-gray-400">-</span>
            </td>
            <td class="p-2">
              <button type="button" class="rounded border px-2 py-1 text-xs" :disabled="busy" @click="resolve(invoice)">解除重复</button>
              <button type="button" class="ml-1 rounded border px-2 py-1 text-xs" :disabled="busy" @click="exclude(invoice)">排除</button>
            </td>
          </tr>
        </tbody>
      </table>
      <p v-if="!duplicates.length" class="py-8 text-center text-gray-400">暂无疑似重复发票。</p>
    </section>

    <section v-else class="space-y-3">
      <p v-if="loading" class="rounded-lg border bg-white p-8 text-center text-sm text-gray-500 shadow-sm">正在加载…</p>
      <article v-for="invoice in rows" :key="invoice.name" class="rounded-lg border bg-white p-4 shadow-sm">
        <div class="flex flex-wrap items-start justify-between gap-2">
          <div>
            <span class="rounded px-2 py-0.5 text-xs" :class="folderTone(invoice.folder_status)">{{ invoice.folder_status }}</span>
            <span class="ml-2 font-medium">{{ invoice.invoice_number || invoice.original_filename || invoice.name }}</span>
            <div class="mt-1 text-xs text-gray-500">
              {{ invoice.invoice_category || '未识别类别' }} · {{ invoice.project_name || '未识别项目名称' }} · {{ invoice.issue_date || '未识别开票日期' }}
              <span v-if="invoice.used_by"> · {{ usedByText(invoice) }}</span>
            </div>
          </div>
          <div class="text-right">
            <div class="text-lg font-semibold">{{ money(invoice.total_amount) }}</div>
            <div class="text-xs text-gray-500">税前 {{ money(invoice.amount_before_tax) }} · 税额 {{ money(invoice.tax_amount) }}</div>
          </div>
        </div>
        <p v-if="invoice.processing_error" class="mt-2 text-xs text-red-600">识别失败：{{ invoice.processing_error }}</p>
        <p v-if="invoice.duplicate_reason" class="mt-2 text-xs text-red-600">{{ invoice.duplicate_reason }}（重复对象 {{ invoice.duplicate_of }}），请联系财务处理。</p>

        <div v-if="canEditFields(invoice) && edits[invoice.name]" class="mt-3 grid gap-2 md:grid-cols-4">
          <label class="text-xs">发票类别<input v-model="edits[invoice.name].invoice_category" class="mt-1 w-full rounded border px-2 py-1 text-sm" /></label>
          <label class="text-xs">项目名称<input v-model="edits[invoice.name].project_name" class="mt-1 w-full rounded border px-2 py-1 text-sm" /></label>
          <label class="text-xs">开票日期<input v-model="edits[invoice.name].issue_date" type="date" class="mt-1 w-full rounded border px-2 py-1 text-sm" /></label>
          <label class="text-xs">发票号码<input v-model="edits[invoice.name].invoice_number" class="mt-1 w-full rounded border px-2 py-1 text-sm" /></label>
          <label class="text-xs">税前金额<input v-model="edits[invoice.name].amount_before_tax" type="number" step="0.01" class="mt-1 w-full rounded border px-2 py-1 text-sm" /></label>
          <label class="text-xs">税额<input v-model="edits[invoice.name].tax_amount" type="number" step="0.01" class="mt-1 w-full rounded border px-2 py-1 text-sm" /></label>
          <label class="text-xs">合计<input v-model="edits[invoice.name].total_amount" type="number" step="0.01" class="mt-1 w-full rounded border px-2 py-1 text-sm" /></label>
          <label class="text-xs">费用说明（必填）<input v-model="edits[invoice.name].expense_description" class="mt-1 w-full rounded border px-2 py-1 text-sm" /></label>
        </div>
        <p v-if="canEditFields(invoice) && missingFields(edits[invoice.name] || invoice).length" class="mt-2 text-xs text-amber-700">
          还需补全：{{ missingFields(edits[invoice.name] || invoice).join('、') }}
        </p>

        <div class="mt-3 flex flex-wrap gap-2">
          <button v-if="canEditFields(invoice)" type="button" class="rounded border px-3 py-1.5 text-sm" :disabled="busy" @click="saveFields(invoice)">保存修改</button>
          <button v-if="canConfirm(invoice)" type="button" class="rounded bg-gray-900 px-3 py-1.5 text-sm text-white" :disabled="busy" @click="confirm(invoice)">确认发票</button>
          <button v-if="canRetry(invoice)" type="button" class="rounded border px-3 py-1.5 text-sm" :disabled="busy" @click="retry(invoice)">重新识别</button>
          <button v-if="!invoice.used_by && invoice.folder_status !== '已排除'" type="button" class="rounded border px-3 py-1.5 text-sm" :disabled="busy" @click="exclude(invoice)">排除</button>
        </div>
      </article>
      <p v-if="!loading && !rows.length" class="rounded-lg border bg-white p-10 text-center text-gray-400 shadow-sm">发票夹里暂无发票，点右上角上传。</p>
    </section>
  </div>
</template>
