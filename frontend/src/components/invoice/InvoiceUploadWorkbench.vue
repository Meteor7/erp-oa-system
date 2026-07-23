<script setup>
import { Button, FeatherIcon } from 'frappe-ui';
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue';
import {
  ACTIVE_RECOGNITION_STATUSES,
  confirmInvoice,
  createInvoiceBatch,
  deriveInvoiceTotal,
  excludeInvoice,
  listWorkbenchInvoices,
  invoiceFieldWarnings,
  invoiceSelectionReason,
  pushInvoices,
  resolveDuplicate,
  retryInvoice,
  unconfirmInvoice,
  updateInvoice,
  uploadInvoiceFiles,
  validateInvoiceFiles,
  withdrawInvoicePush,
} from '../../lib/invoiceOcr.js';
import InvoicePreviewDrawer from './InvoicePreviewDrawer.vue';

const props = defineProps({
  options: { type: Object, default: () => ({}) },
});
const emit = defineEmits(['request-created']);

const rows = ref([]);
const selectedName = ref('');
const checkedNames = ref([]);
const busy = ref(false);
const loading = ref(false);
const uploadText = ref('');
const errorMessage = ref('');
const message = ref('');
const previewRow = ref(null);
const showPush = ref(false);
const statusFilter = ref('');
const pushForm = reactive({
  subject: '',
  company: '',
  department: '',
   asset_category: '其它',
  doc_type: '',
  urgency: '',
  payment_type: '',
  payment_method: '',
  bank_name: '',
  payee_name: '',
  branch: '',
  account_no: '',
  reason: '',
});
let pollTimer = null;
let disposed = false;

const fields = [
  ['invoice_category', '发票类别', 'text'],
  ['project_name', '项目名称', 'text'],
  ['issue_date', '开票日期', 'date'],
  ['invoice_number', '发票号码', 'text'],
  ['amount_before_tax', '税前金额', 'number'],
  ['tax_amount', '税额', 'number'],
  ['total_amount', '合计金额', 'number'],
];

const visibleRows = computed(() => rows.value.filter((row) => !statusFilter.value || row.recognition_status === statusFilter.value));
const selectedRow = computed(() => rows.value.find((row) => row.name === selectedName.value) || visibleRows.value[0] || null);
const applicant = computed(() => props.options?.current_applicant || props.options?.context || {});
const selectableRows = computed(() => rows.value.filter((row) => !invoiceSelectionReason(row)));
const selectedTotal = computed(() => rows.value
  .filter((row) => checkedNames.value.includes(row.name))
  .reduce((sum, row) => sum + Number(row.total_amount || 0), 0));
const stats = computed(() => ({
  total: rows.value.length,
  pending: rows.value.filter((row) => row.recognition_status === '待确认').length,
  confirmed: rows.value.filter((row) => row.recognition_status === '已确认').length,
  pushed: rows.value.filter((row) => Boolean(row.request)).length,
  duplicate: rows.value.filter((row) => row.recognition_status === '疑似重复').length,
}));

function syncDerivedTotal(row, field) {
  if (!['amount_before_tax', 'tax_amount'].includes(field)) return;
  const derived = deriveInvoiceTotal(row);
  if (derived) row.total_amount = derived;
}

function cleanError(error, fallback) {
  return String(error?.message || fallback).replace(/<[^>]*>/g, '').trim();
}

function money(value) {
  if (value === null || value === undefined || value === '') return '-';
  return Number(value).toLocaleString('zh-CN', { style: 'currency', currency: 'CNY', minimumFractionDigits: 2 });
}

function statusClass(status) {
  return {
    排队中: 'bg-gray-100 text-gray-700',
    识别中: 'bg-blue-50 text-blue-700',
    待确认: 'bg-amber-50 text-amber-700',
    已确认: 'bg-emerald-50 text-emerald-700',
    疑似重复: 'bg-red-50 text-red-700',
    失败: 'bg-red-50 text-red-700',
    已排除: 'bg-gray-100 text-gray-500',
  }[status] || 'bg-gray-100 text-gray-700';
}

function isEditable(row) {
  return ['待确认', '疑似重复'].includes(row?.recognition_status);
}

function selectionReason(row) {
  return invoiceSelectionReason(row);
}

function canCheck(row) {
  return !selectionReason(row);
}

function syncChecked() {
  const allowed = new Set(selectableRows.value.map((row) => row.name));
  checkedNames.value = checkedNames.value.filter((name) => allowed.has(name));
}

function schedulePoll() {
  clearTimeout(pollTimer);
  if (disposed || !rows.value.some((row) => ACTIVE_RECOGNITION_STATUSES.includes(row.recognition_status))) return;
  pollTimer = setTimeout(() => reload(false), 1500);
}

async function reload(showError = true) {
  loading.value = true;
  try {
    rows.value = await listWorkbenchInvoices({ view: 'all', status: statusFilter.value, limit: 300 }) || [];
    if (!rows.value.some((row) => row.name === selectedName.value)) selectedName.value = rows.value[0]?.name || '';
    syncChecked();
    schedulePoll();
  } catch (error) {
    if (showError) errorMessage.value = cleanError(error, '发票列表加载失败');
  } finally {
    loading.value = false;
  }
}

async function uploadFiles(event) {
  const input = event.target;
  const files = Array.from(input.files || []);
  input.value = '';
  if (!files.length) return;
  errorMessage.value = '';
  message.value = '';
  busy.value = true;
  try {
    validateInvoiceFiles(files);
    const batch = await createInvoiceBatch();
    const batchName = typeof batch === 'string' ? batch : batch?.name;
    if (!batchName) throw new Error('未能创建发票批次');
    const results = await uploadInvoiceFiles(files, batchName, {
      onSettled: (_result, _index, complete, total) => {
        uploadText.value = `上传并识别中 ${complete}/${total}`;
      },
    });
    const failed = results.filter((result) => result?.error);
    message.value = `已接收 ${results.length - failed.length} 张发票，OCR 正在后台处理。`;
    if (failed.length) errorMessage.value = `${failed.length} 个文件上传失败，其余文件继续识别。`;
    await reload(false);
  } catch (error) {
    errorMessage.value = cleanError(error, '发票上传失败');
  } finally {
    busy.value = false;
    uploadText.value = '';
  }
}

async function saveFields(row) {
  busy.value = true;
  errorMessage.value = '';
  try {
    const updated = await updateInvoice(row.name, Object.fromEntries(fields.map(([name]) => [name, row[name]])));
    rows.value = rows.value.map((item) => item.name === updated.name ? updated : item);
    message.value = '识别内容已保存。';
  } catch (error) {
    errorMessage.value = cleanError(error, '识别内容保存失败');
  } finally {
    busy.value = false;
  }
}

async function confirmRow(row) {
  busy.value = true;
  errorMessage.value = '';
  try {
    const updated = await confirmInvoice(row.name, Object.fromEntries(fields.map(([name]) => [name, row[name]])));
    rows.value = rows.value.map((item) => item.name === row.name ? updated : item);
    message.value = updated.conflict ? '检测到疑似重复发票，请财务复核。' : '发票内容已确认，可勾选下推。';
  } catch (error) {
    errorMessage.value = cleanError(error, '发票确认失败');
  } finally {
    busy.value = false;
  }
}

async function undoConfirm(row) {
  if (!window.confirm('确认撤回这张发票的内容确认吗？')) return;
  busy.value = true;
  try {
    const updated = await unconfirmInvoice(row.name, '用户撤回确认');
    rows.value = rows.value.map((item) => item.name === row.name ? updated : item);
    syncChecked();
    message.value = '已撤回确认，可重新修改识别内容。';
  } catch (error) {
    errorMessage.value = cleanError(error, '撤回确认失败');
  } finally {
    busy.value = false;
  }
}

async function retryRow(row) {
  busy.value = true;
  try {
    const updated = await retryInvoice(row.name);
    rows.value = rows.value.map((item) => item.name === row.name ? updated : item);
    schedulePoll();
  } catch (error) {
    errorMessage.value = cleanError(error, '重新识别失败');
  } finally {
    busy.value = false;
  }
}

async function resolveRow(row) {
  const reason = window.prompt('请填写解除重复的复核原因');
  if (!reason?.trim()) return;
  busy.value = true;
  try {
    const updated = await resolveDuplicate(row.name, reason);
    rows.value = rows.value.map((item) => item.name === row.name ? updated : item);
    message.value = '重复标记已解除，请再次确认内容。';
  } catch (error) {
    errorMessage.value = cleanError(error, '重复复核失败');
  } finally {
    busy.value = false;
  }
}

async function excludeRow(row) {
  const reason = window.prompt('请填写排除原因');
  if (!reason?.trim()) return;
  busy.value = true;
  try {
    await excludeInvoice(row.name, reason);
    await reload(false);
  } catch (error) {
    errorMessage.value = cleanError(error, '排除失败');
  } finally {
    busy.value = false;
  }
}

function toggleChecked(name) {
  checkedNames.value = checkedNames.value.includes(name)
    ? checkedNames.value.filter((item) => item !== name)
    : [...checkedNames.value, name];
}

function warningText(warning) {
  const raw = typeof warning === 'object' ? (warning?.message || warning?.code || '') : String(warning || '');
  const labels = {
    required_fields_missing: '\u5fc5\u586b\u4fe1\u606f\u672a\u8bc6\u522b\u5b8c\u6574\uff0c\u8bf7\u8865\u5145\u540e\u786e\u8ba4',
    invoice_category_raw_missing: '\u672a\u8bc6\u522b\u5230\u53d1\u7968\u7968\u9762\u7c7b\u522b\uff0c\u8bf7\u4eba\u5de5\u586b\u5199',
    amount_before_tax_derived_from_total_minus_tax: '\u7a0e\u524d\u91d1\u989d\u7531\u5408\u8ba1\u91d1\u989d\u51cf\u7a0e\u989d\u8ba1\u7b97\u5f97\u51fa\uff0c\u8bf7\u6838\u5bf9',
    zero_tax_rule_applied: '\u5f53\u524d\u53d1\u7968\u6309\u96f6\u7a0e\u7387\u89c4\u5219\u5904\u7406\uff0c\u8bf7\u786e\u8ba4\u7a0e\u989d',
    tax_amount_missing_for_taxable_invoice: '\u53d1\u7968\u53ef\u80fd\u542b\u7a0e\uff0c\u4f46\u672a\u8bc6\u522b\u5230\u7a0e\u989d\uff0c\u8bf7\u8865\u5145\u540e\u786e\u8ba4',
    amount_arithmetic_mismatch: '\u7a0e\u524d\u91d1\u989d\u3001\u7a0e\u989d\u4e0e\u5408\u8ba1\u91d1\u989d\u7684\u8ba1\u7b97\u5173\u7cfb\u4e0d\u4e00\u81f4\uff0c\u8bf7\u6838\u5bf9',
    amount_mismatch: '\u7a0e\u524d\u91d1\u989d\u3001\u7a0e\u989d\u4e0e\u5408\u8ba1\u91d1\u989d\u53ef\u80fd\u4e0d\u4e00\u81f4\uff0c\u8bf7\u6838\u5bf9',
    dependent_fields_cleared_due_to_conflict: '\u8bc6\u522b\u7ed3\u679c\u51b2\u7a81\uff0c\u76f8\u5173\u91d1\u989d\u5b57\u6bb5\u5df2\u7559\u7a7a\uff0c\u8bf7\u8865\u5145\u540e\u786e\u8ba4',
    'temporary_files_cleanup_failed:sensitive_invoice_files_may_remain': '\u4e34\u65f6\u6587\u4ef6\u6e05\u7406\u5f02\u5e38\uff0c\u8bf7\u8054\u7cfb\u7ba1\u7406\u5458\u68c0\u67e5\u670d\u52a1\u5668',
  };
  if (labels[raw]) return labels[raw];
  const fieldLabels = {
    invoice_category: '\u53d1\u7968\u7c7b\u522b',
    invoice_category_normalized: '\u53d1\u7968\u7c7b\u522b',
    project_name: '\u9879\u76ee\u540d\u79f0',
    issue_date: '\u5f00\u7968\u65e5\u671f',
    invoice_number: '\u53d1\u7968\u53f7\u7801',
    amount_before_tax: '\u7a0e\u524d\u91d1\u989d',
    tax_amount: '\u7a0e\u989d',
    total_amount: '\u5408\u8ba1\u91d1\u989d',
  };
  if (raw.startsWith('field_conflict:')) return (fieldLabels[raw.split(':')[1]] || '\u5b57\u6bb5') + '\u8bc6\u522b\u7ed3\u679c\u5b58\u5728\u51b2\u7a81\uff0c\u8bf7\u4eba\u5de5\u786e\u8ba4';
  if (raw.startsWith('low_confidence:')) return (fieldLabels[raw.split(':')[1]] || '\u5b57\u6bb5') + '\u8bc6\u522b\u7f6e\u4fe1\u5ea6\u8f83\u4f4e\uff0c\u8bf7\u4eba\u5de5\u6838\u5bf9';
  if (/[\u3400-\u9fff]/.test(raw)) return raw;
  return '\u8bc6\u522b\u7ed3\u679c\u5b58\u5728\u5f02\u5e38\uff0c\u8bf7\u4eba\u5de5\u6838\u5bf9';
}

function applyPushDefaults() {
  const context = props.options?.context || {};
  pushForm.company ||= props.options?.companies?.[0] || '';
  pushForm.department ||= context.department || props.options?.departments?.[0] || '';
   pushForm.doc_type ||= props.options?.doc_types?.[0] || '';
  pushForm.urgency ||= props.options?.urgencies?.[0] || '';
  pushForm.payment_type ||= props.options?.payment_types?.[0] || '';
  pushForm.payment_method ||= props.options?.payment_methods?.[0] || '';
  pushForm.payee_name ||= applicant.value.employee_name || '';
}

function openPush() {
  if (!checkedNames.value.length) {
    errorMessage.value = '请先勾选已确认且未下推的发票。';
    return;
  }
  applyPushDefaults();
  showPush.value = true;
}

async function submitPush() {
  busy.value = true;
  errorMessage.value = '';
  try {
    const request = await pushInvoices(checkedNames.value, pushForm);
    showPush.value = false;
    checkedNames.value = [];
    message.value = `已生成费用报销草稿 ${request.name}。`;
    emit('request-created', request.name);
    await reload(false);
  } catch (error) {
    errorMessage.value = cleanError(error, '下推失败');
  } finally {
    busy.value = false;
  }
}

async function undoPush(row) {
  if (!window.confirm('撤回下推会将关联报销单退回草稿，并解除这张发票的费用明细，是否继续？')) return;
  busy.value = true;
  errorMessage.value = '';
  try {
    await withdrawInvoicePush([row.name], '用户操作失误撤回下推');
    message.value = '已撤回下推，发票可重新选择。';
    await reload(false);
  } catch (error) {
    errorMessage.value = cleanError(error, '撤回下推失败');
  } finally {
    busy.value = false;
  }
}

onMounted(() => reload());
onBeforeUnmount(() => {
  disposed = true;
  clearTimeout(pollTimer);
});
</script>

<template>
  <div class="space-y-5 pb-6">
    <header class="sticky top-0 z-10 -mx-1 flex flex-col gap-4 border-b border-gray-200 bg-white/95 px-1 py-3 backdrop-blur md:flex-row md:items-center md:justify-between">
      <div class="min-w-0">
        <h2 class="text-xl font-bold tracking-tight text-gray-900">上传发票</h2>
        <p class="mt-1 text-sm leading-5 text-gray-500">批量上传后由本地 OCR 识别，人工确认七项内容，再下推到费用报销流。</p>
      </div>
      <div class="flex shrink-0 flex-wrap items-center gap-2">
        <div v-if="checkedNames.length" class="mr-1 text-right text-xs text-gray-500">
          <div>已选择 {{ checkedNames.length }} 张</div>
          <div class="mt-0.5 font-semibold text-gray-800">{{ money(selectedTotal) }}</div>
        </div>
        <label class="inline-flex h-9 cursor-pointer items-center gap-2 rounded-lg bg-blue-600 px-4 text-sm font-semibold text-white shadow-sm transition hover:bg-blue-700 focus-within:ring-2 focus-within:ring-blue-500 focus-within:ring-offset-2">
          <FeatherIcon name="upload-cloud" class="h-4 w-4" />
          {{ uploadText || '批量上传发票' }}
          <input class="hidden" type="file" accept=".pdf,.jpg,.jpeg,.png" multiple :disabled="busy" @change="uploadFiles" />
        </label>
        <Button variant="subtle" :loading="loading" @click="reload"><FeatherIcon name="refresh-cw" class="h-4 w-4" />刷新</Button>
        <Button variant="solid" :disabled="!checkedNames.length" @click="openPush">下推到费用报销流（{{ checkedNames.length }}）</Button>
      </div>
    </header>

    <div v-if="message" class="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">{{ message }}</div>
    <div v-if="errorMessage" role="alert" class="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{{ errorMessage }}</div>

    <section class="grid grid-cols-2 gap-3 lg:grid-cols-5">
      <div v-for="item in [
        ['发票总数', stats.total, 'bg-blue-500'],
        ['待确认', stats.pending, 'bg-amber-500'],
        ['已确认', stats.confirmed, 'bg-emerald-500'],
        ['已下推', stats.pushed, 'bg-cyan-500'],
        ['疑似重复', stats.duplicate, 'bg-red-500'],
      ]" :key="item[0]" class="relative overflow-hidden rounded-xl border border-gray-200 bg-white px-4 py-3 shadow-sm">
        <div class="absolute inset-y-0 left-0 w-1" :class="item[2]"></div>
        <div class="text-xs font-medium text-gray-500">{{ item[0] }}</div>
        <div class="mt-1 text-2xl font-semibold tracking-tight text-gray-900">{{ item[1] }}</div>
      </div>
    </section>

    <section class="grid gap-5 xl:grid-cols-[minmax(0,1fr)_420px]">
      <div class="min-w-0 overflow-hidden rounded-xl border border-gray-200 bg-white shadow-sm">
        <div class="flex flex-col gap-3 border-b border-gray-200 px-4 py-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h3 class="font-semibold text-gray-900">发票列表</h3>
            <p class="mt-1 text-xs leading-5 text-gray-500">可下推 {{ selectableRows.length }} 张；已确认且未下推的发票才可勾选。</p>
          </div>
          <label class="flex items-center gap-2 text-xs text-gray-500">
            状态
            <select v-model="statusFilter" class="h-9 rounded-lg border border-gray-300 bg-white px-3 text-sm text-gray-700 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100" @change="reload">
              <option value="">全部状态</option>
              <option v-for="status in ['排队中','识别中','待确认','已确认','疑似重复','失败','已排除']" :key="status">{{ status }}</option>
            </select>
          </label>
        </div>
        <div class="max-h-[calc(100vh-360px)] overflow-x-auto overflow-y-auto">
          <table class="w-full min-w-[920px] text-sm">
            <thead class="sticky top-0 z-[1] border-b border-gray-200 bg-gray-50 text-xs font-medium text-gray-500 shadow-[0_1px_0_rgba(0,0,0,0.04)]">
              <tr>
                <th class="w-11 px-3 py-3"></th>
                <th class="px-3 py-3 text-left">文件</th>
                <th class="px-3 py-3 text-left">状态</th>
                <th class="px-3 py-3 text-left">发票类别</th>
                <th class="px-3 py-3 text-left">项目名称</th>
                <th class="px-3 py-3 text-left">开票日期</th>
                <th class="px-3 py-3 text-left">发票号码</th>
                <th class="px-3 py-3 text-right">合计金额</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in visibleRows" :key="row.name" class="group cursor-pointer border-b border-gray-100 transition hover:bg-blue-50/60" :class="selectedRow?.name === row.name ? 'bg-blue-50 shadow-[inset_3px_0_0_#2563eb]' : ''" :aria-current="selectedRow?.name === row.name ? 'true' : undefined" @click="selectedName = row.name">
                <td class="px-3 py-3.5" :title="selectionReason(row)" @click.stop>
                  <input type="checkbox" class="h-4 w-4 rounded border-gray-300 text-blue-600 disabled:cursor-not-allowed disabled:opacity-40" :checked="checkedNames.includes(row.name)" :disabled="!canCheck(row)" @change="toggleChecked(row.name)" />
                </td>
                <td class="max-w-[230px] px-3 py-3.5">
                  <div class="truncate font-medium text-gray-800" :title="row.original_filename">{{ row.original_filename }}</div>
                  <div class="mt-1 truncate text-[11px] text-gray-400">{{ row.name }}</div>
                </td>
                <td class="px-3 py-3.5">
                  <span class="inline-flex rounded-md px-2 py-1 text-xs font-medium" :class="statusClass(row.recognition_status)">{{ row.request ? '已下推' : row.recognition_status }}</span>
                  <p v-if="selectionReason(row)" class="mt-1.5 max-w-[190px] text-[11px] leading-4 text-gray-500">{{ selectionReason(row) }}</p>
                </td>
                <td class="max-w-[190px] truncate px-3 py-3.5 text-gray-700">{{ row.invoice_category || '-' }}</td>
                <td class="max-w-[190px] truncate px-3 py-3.5 text-gray-700">{{ row.project_name || '-' }}</td>
                <td class="whitespace-nowrap px-3 py-3.5 text-gray-600">{{ row.issue_date || '-' }}</td>
                <td class="whitespace-nowrap px-3 py-3.5 font-mono text-xs text-gray-600">{{ row.invoice_number || '-' }}</td>
                <td class="whitespace-nowrap px-3 py-3.5 text-right font-semibold text-red-600">{{ money(row.total_amount) }}</td>
              </tr>
              <tr v-if="!visibleRows.length"><td colspan="8" class="py-20 text-center"><FeatherIcon name="file-text" class="mx-auto h-8 w-8 text-gray-300" /><p class="mt-3 text-sm text-gray-400">还没有发票，请点击上方“批量上传发票”。</p></td></tr>
            </tbody>
          </table>
        </div>
      </div>

      <aside class="overflow-hidden rounded-xl border border-gray-200 bg-white shadow-sm xl:sticky xl:top-4 xl:h-fit">
        <template v-if="selectedRow">
          <header class="border-b border-gray-200 bg-gray-50/70 px-5 py-4">
            <div class="flex items-start justify-between gap-3">
              <div class="min-w-0">
                <h3 class="truncate font-semibold text-gray-900" :title="selectedRow.original_filename">{{ selectedRow.original_filename }}</h3>
                <p class="mt-1 truncate text-xs text-gray-500">{{ selectedRow.name }}</p>
              </div>
              <span class="shrink-0 rounded-md px-2 py-1 text-xs font-medium" :class="statusClass(selectedRow.recognition_status)">{{ selectedRow.request ? '已下推' : selectedRow.recognition_status }}</span>
            </div>
          </header>
          <div class="space-y-4 p-5">
            <div class="grid gap-3 sm:grid-cols-2">
              <label v-for="[name, label, type] in fields" :key="name" class="text-xs font-medium text-gray-500" :class="name === 'project_name' || name === 'invoice_category' ? 'sm:col-span-2' : ''">
                {{ label }}
                <input v-model="selectedRow[name]" :type="type" @input="syncDerivedTotal(selectedRow, name)" :step="type === 'number' ? '0.01' : undefined" :disabled="!isEditable(selectedRow)" class="mt-1.5 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-800 outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-100 disabled:border-gray-200 disabled:bg-gray-50 disabled:text-gray-600" />
              </label>
            </div>
            <div v-if="invoiceFieldWarnings(selectedRow.field_warnings).length" class="break-words rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs leading-5 text-amber-800">
              <div class="mb-1 font-semibold">请检查识别结果</div>
              <div v-for="warning in invoiceFieldWarnings(selectedRow.field_warnings)" :key="String(warning)">{{ warningText(warning) }}</div>
            </div>
            <div v-if="selectedRow.request" class="rounded-lg border border-blue-200 bg-blue-50 p-3 text-sm leading-5 text-blue-700">已下推到费用报销流：{{ selectedRow.request }}</div>
            <div class="flex flex-wrap gap-2 border-t border-gray-200 pt-4">
              <Button variant="subtle" @click="previewRow = selectedRow"><FeatherIcon name="eye" class="h-4 w-4" />查看发票</Button>
              <Button v-if="isEditable(selectedRow)" variant="subtle" :disabled="busy" @click="saveFields(selectedRow)">保存修改</Button>
              <Button v-if="selectedRow.recognition_status === '待确认'" variant="solid" :disabled="busy" @click="confirmRow(selectedRow)">确认内容</Button>
              <Button v-if="selectedRow.recognition_status === '已确认' && !selectedRow.request" variant="subtle" :disabled="busy" @click="undoConfirm(selectedRow)">撤回确认</Button>
              <Button v-if="selectedRow.recognition_status === '失败'" variant="solid" :disabled="busy" @click="retryRow(selectedRow)">重新识别</Button>
              <Button v-if="selectedRow.recognition_status === '疑似重复'" variant="solid" :disabled="busy" @click="resolveRow(selectedRow)">解除重复</Button>
              <Button v-if="selectedRow.request" variant="subtle" :disabled="busy" @click="undoPush(selectedRow)">撤回下推</Button>
              <Button v-if="['待确认','疑似重复','失败'].includes(selectedRow.recognition_status)" variant="subtle" :disabled="busy" @click="excludeRow(selectedRow)">排除</Button>
            </div>
          </div>
        </template>
        <div v-else class="flex min-h-[360px] flex-col items-center justify-center px-6 text-center text-sm text-gray-400">
          <FeatherIcon name="mouse-pointer" class="h-8 w-8 text-gray-300" />
          <p class="mt-3">从左侧选择一张发票</p>
          <p class="mt-1 text-xs text-gray-300">识别结果和确认操作会显示在这里</p>
        </div>
      </aside>
    </section>

    <div v-if="showPush" class="fixed inset-0 z-50 flex items-center justify-center bg-gray-900/40 p-4" @click.self="showPush = false">
      <div role="dialog" aria-modal="true" class="w-full max-w-4xl overflow-hidden rounded bg-white shadow-xl">
        <header class="flex items-center justify-between border-b bg-gray-50 px-5 py-4">
          <div>
            <h3 class="font-semibold">下推到费用报销流</h3>
            <p class="mt-1 text-xs text-gray-500">已选 {{ checkedNames.length }} 张发票，将生成一张报销草稿和 {{ checkedNames.length }} 行费用明细，合计 {{ money(selectedTotal) }}。</p>
          </div>
          <button title="关闭" @click="showPush = false"><FeatherIcon name="x" class="h-5 w-5" /></button>
        </header>
        <div class="grid max-h-[65vh] gap-3 overflow-y-auto p-5 md:grid-cols-3">
          <label class="text-xs text-gray-500 md:col-span-2">主题<input v-model="pushForm.subject" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm" placeholder="发票报销" /></label>
          <label class="text-xs text-gray-500">公司<select v-model="pushForm.company" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm"><option v-for="item in props.options?.companies || []" :key="item">{{ item }}</option></select></label>
          <label class="text-xs text-gray-500">申请部门<select v-model="pushForm.department" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm"><option v-for="item in props.options?.departments || []" :key="item">{{ item }}</option></select></label>
          <label class="text-xs text-gray-500">申请人<input :value="applicant.employee_name || applicant.user" readonly class="mt-1 w-full rounded border border-gray-200 bg-gray-50 px-3 py-2 text-sm text-gray-600" /></label>
          <label class="text-xs text-gray-500">付款类型<select v-model="pushForm.payment_type" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm"><option v-for="item in props.options?.payment_types || []" :key="item">{{ item }}</option></select></label>
          <label class="text-xs text-gray-500">支付方式<select v-model="pushForm.payment_method" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm"><option v-for="item in props.options?.payment_methods || []" :key="item">{{ item }}</option></select></label>
          <label class="text-xs text-gray-500">收款人<input v-model="pushForm.payee_name" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm" /></label>
          <label class="text-xs text-gray-500">开户行<input v-model="pushForm.bank_name" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm" /></label>
          <label class="text-xs text-gray-500">支行<input v-model="pushForm.branch" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm" /></label>
          <label class="text-xs text-gray-500">收款账号<input v-model="pushForm.account_no" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm" /></label>
          <label class="text-xs text-gray-500 md:col-span-3">备注<textarea v-model="pushForm.reason" rows="2" class="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm"></textarea></label>
        </div>
        <footer class="flex justify-end gap-2 border-t bg-gray-50 px-5 py-3">
          <Button variant="subtle" @click="showPush = false">取消</Button>
          <Button variant="solid" :loading="busy" @click="submitPush">生成报销草稿</Button>
        </footer>
      </div>
    </div>

    <InvoicePreviewDrawer :open="Boolean(previewRow)" :invoice="previewRow" @close="previewRow = null" />
  </div>
</template>
