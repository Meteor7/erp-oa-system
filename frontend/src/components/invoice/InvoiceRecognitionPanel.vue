<template>
  <section class='space-y-4 rounded-xl border border-slate-200 bg-white p-4'>
    <header class='flex flex-wrap items-center justify-between gap-3'>
      <div>
        <h3 class='text-base font-semibold text-slate-900'>&#x53D1;&#x7968; OCR</h3>
        <p class='mt-1 text-xs text-slate-500'>PDF / JPG / JPEG / PNG&#xFF0C;&#x6BCF;&#x6279;&#x6700;&#x591A; 20 &#x4E2A;&#xFF0C;&#x5355;&#x4E2A;&#x4E0D;&#x8D85;&#x8FC7; 10MB</p>
      </div>
      <label class='inline-flex cursor-pointer items-center rounded-lg bg-sky-600 px-3 py-2 text-sm font-medium text-white' :class='{ "cursor-not-allowed opacity-50": disabled || uploading }'>
        {{ uploading ? labels.uploading : labels.choose }}
        <input class='sr-only' type='file' multiple accept='.pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png' :disabled='disabled || uploading' @change='onFilesSelected'>
      </label>
    </header>

    <div v-if='batchSummary' class='grid grid-cols-2 gap-2 rounded-lg bg-slate-50 p-3 text-xs text-slate-600 sm:grid-cols-4 lg:grid-cols-7'>
      <span>{{ labels.total }} {{ batchSummary.total_count || rows.length }}</span>
      <span>{{ labels.queued }} {{ batchSummary.queued_count || 0 }}</span>
      <span>{{ labels.processing }} {{ batchSummary.processing_count || 0 }}</span>
      <span>{{ labels.pending }} {{ batchSummary.pending_confirmation_count || 0 }}</span>
      <span>{{ labels.confirmed }} {{ batchSummary.confirmed_count || 0 }}</span>
      <span>{{ labels.duplicate }} {{ batchSummary.duplicate_count || 0 }}</span>
      <span>{{ labels.failed }} {{ batchSummary.failed_count || 0 }}</span>
    </div>

    <p v-if='errorMessage' role='alert' class='rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700'>{{ errorMessage }}</p>
    <p v-if='uploadFailures.length' class='rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800'>
      {{ uploadFailures.map((item) => item.file.name).join(labels.separator) }} {{ labels.partialFailure }}
    </p>

    <div v-if='rows.length' class='overflow-x-auto rounded-lg border border-slate-200'>
      <table class='min-w-[1500px] divide-y divide-slate-200 text-left text-xs'>
        <thead class='bg-slate-50 text-slate-600'>
          <tr>
            <th class='px-2 py-2'>{{ labels.file }}</th>
            <th v-for='field in INVOICE_FIELDS' :key='field' class='px-2 py-2'>{{ fieldLabels[field] }}</th>
            <th class='px-2 py-2'>{{ labels.status }}</th>
            <th class='px-2 py-2'>{{ labels.line }}</th>
            <th class='px-2 py-2'>{{ labels.actions }}</th>
          </tr>
        </thead>
        <tbody class='divide-y divide-slate-100'>
          <tr v-for='row in visibleRows' :key='row.name' :class='{ "opacity-60": row.recognition_status === labels.excluded }'>
            <td class='max-w-[180px] truncate px-2 py-2' :title='row.original_filename'>{{ row.original_filename }}</td>
            <td v-for='field in INVOICE_FIELDS' :key='field' class='px-1 py-1'>
              <input
                v-model='row[field]'
                :type='field === "issue_date" ? "date" : "text"'
                :inputmode='moneyFields.has(field) ? "decimal" : undefined'
                :disabled='!isEditable(row)'
                :class='fieldClass(row, field)'
                @change='saveField(row, field)'
              >
            </td>
            <td class='px-2 py-2'>
              <span class='whitespace-nowrap rounded-full bg-slate-100 px-2 py-1'>{{ row.recognition_status }}</span>
              <p v-if='row.processing_error' class='mt-1 max-w-[160px] text-rose-600'>{{ row.processing_error }}</p>
            </td>
            <td class='px-2 py-2'>
              <select :value='row.expense_line_key' class='w-44 rounded border-slate-300 text-xs' :disabled='disabled || row.recognition_status !== labels.confirmed' @change='changeLink(row, $event.target.value)'>
                <option value=''>{{ labels.unlinked }}</option>
                <option v-for='line in expenseLines' :key='line.line_key' :value='line.line_key'>{{ lineLabel(line) }}</option>
              </select>
            </td>
            <td class='space-x-2 whitespace-nowrap px-2 py-2'>
              <button v-if='row.recognition_status === labels.pending' type='button' class='text-emerald-700' :disabled='disabled || busyNames.has(row.name)' @click='confirmRow(row)'>{{ labels.confirmAction }}</button>
              <button v-if='row.recognition_status === labels.failed' type='button' class='text-sky-700' :disabled='disabled || busyNames.has(row.name)' @click='retryRow(row)'>{{ labels.retry }}</button>
              <button v-if='row.recognition_status === labels.duplicate' type='button' class='text-violet-700' :disabled='disabled || busyNames.has(row.name)' @click='resolveRow(row)'>{{ labels.resolve }}</button>
              <button v-if='[labels.pending, labels.duplicate, labels.failed].includes(row.recognition_status)' type='button' class='text-rose-700' :disabled='disabled || busyNames.has(row.name)' @click='excludeRow(row)'>{{ labels.exclude }}</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <p v-else class='rounded-lg border border-dashed border-slate-300 p-6 text-center text-sm text-slate-500'>{{ labels.empty }}</p>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import {
  ACTIVE_RECOGNITION_STATUSES,
  INVOICE_FIELDS,
  confirmInvoice,
  createOperationContext,
  createInvoiceBatch,
  excludeInvoice,
  getInvoiceBatch,
  linkInvoice,
  resolveDuplicate,
  retryInvoice,
  updateInvoice,
  uploadInvoiceFiles,
  validateInvoiceFiles,
} from '../../lib/invoiceOcr.js';

const props = defineProps({
  batch: { type: [String, Object], default: '' },
  invoices: { type: Array, default: () => [] },
  request: { type: String, default: '' },
  expenseLines: { type: Array, default: () => [] },
  disabled: { type: Boolean, default: false },
  pollInterval: { type: Number, default: 1500 },
});

const emit = defineEmits(['batch-created', 'invoices-change', 'link-change']);
const fieldLabels = Object.freeze({
  invoice_category: '\u53d1\u7968\u7c7b\u522b', project_name: '\u9879\u76ee\u540d\u79f0', issue_date: '\u5f00\u7968\u65e5\u671f',
  invoice_number: '\u53d1\u7968\u53f7\u7801', amount_before_tax: '\u7a0e\u524d\u91d1\u989d', tax_amount: '\u7a0e\u989d', total_amount: '\u5408\u8ba1\u91d1\u989d',
});
const labels = Object.freeze({
  uploading: '\u4e0a\u4f20\u4e2d...', choose: '\u6279\u91cf\u9009\u62e9\u53d1\u7968', total: '\u603b\u6570', queued: '\u6392\u961f', processing: '\u8bc6\u522b\u4e2d',
  pending: '\u5f85\u786e\u8ba4', confirmed: '\u5df2\u786e\u8ba4', duplicate: '\u7591\u4f3c\u91cd\u590d', failed: '\u5931\u8d25', excluded: '\u5df2\u6392\u9664',
  file: '\u6587\u4ef6', status: '\u72b6\u6001', line: '\u8d39\u7528\u660e\u7ec6', actions: '\u64cd\u4f5c', unlinked: '\u672a\u5173\u8054',
  confirmAction: '\u786e\u8ba4', retry: '\u91cd\u8bd5', resolve: '\u89e3\u9664\u91cd\u590d', exclude: '\u6392\u9664', empty: '\u8fd8\u6ca1\u6709\u53d1\u7968',
  partialFailure: '\u4e0a\u4f20\u5931\u8d25\uff0c\u5176\u4ed6\u6587\u4ef6\u5df2\u7ee7\u7eed\u5904\u7406\u3002', separator: '\u3001',
});

const rows = ref(props.invoices.map((row) => ({ ...row })));
const batchName = ref(typeof props.batch === 'string' ? props.batch : props.batch?.name || '');
const batchSummary = ref(typeof props.batch === 'object' ? props.batch : null);
const uploading = ref(false);
const errorMessage = ref('');
const uploadFailures = ref([]);
const busyNames = ref(new Set());
const moneyFields = new Set(['amount_before_tax', 'tax_amount', 'total_amount']);
let pollTimer = null;
let pollAbort = null;
let requestVersion = 0;
let disposed = false;
const operationContext = createOperationContext();

const visibleRows = computed(() => rows.value.filter((row) => row.recognition_status !== labels.excluded));

function isEditable(row) {
  return !props.disabled && [labels.pending, labels.duplicate].includes(row.recognition_status);
}

function operationController() {
  return operationContext.controller();
}

function finishOperation(controller) {
  operationContext.finish(controller);
}

watch(() => props.invoices, (value) => {
  rows.value = value.map((row) => ({ ...row }));
}, { deep: true });

watch(() => props.batch, (value) => {
  const nextName = typeof value === 'string' ? value : value?.name || '';
  const changed = nextName !== batchName.value;
  if (changed) {
    operationContext.invalidate();
    stopPolling();
    batchName.value = nextName;
    batchSummary.value = typeof value === 'object' ? value : null;
    rows.value = [];
    errorMessage.value = '';
    uploadFailures.value = [];
    busyNames.value = new Set();
    uploading.value = false;
  } else if (typeof value === 'object') {
    batchSummary.value = value;
  }
  if (nextName && (changed || !rows.value.length)) refreshBatch(true);
}, { immediate: true });

function replaceRows(nextRows) {
  rows.value = (nextRows || []).map((row) => ({ ...row }));
  emit('invoices-change', rows.value.map((row) => ({ ...row })));
}

function isActive() {
  return rows.value.some((row) => ACTIVE_RECOGNITION_STATUSES.includes(row.recognition_status));
}

function stopPolling() {
  requestVersion += 1;
  if (pollTimer !== null) clearTimeout(pollTimer);
  pollTimer = null;
  pollAbort?.abort();
  pollAbort = null;
}

function schedulePoll() {
  if (disposed || !isActive()) return;
  if (pollTimer !== null) clearTimeout(pollTimer);
  pollTimer = setTimeout(() => {
    pollTimer = null;
    refreshBatch(false);
  }, Math.max(300, props.pollInterval));
}

async function refreshBatch(showErrors = false) {
  if (!batchName.value || disposed) return;
  const version = ++requestVersion;
  pollAbort?.abort();
  const controller = new AbortController();
  pollAbort = controller;
  try {
    const result = await getInvoiceBatch(batchName.value, { signal: controller.signal });
    if (disposed || version !== requestVersion) return;
    batchSummary.value = result;
    replaceRows(result?.records || []);
  } catch (error) {
    if (error?.name !== 'AbortError' && showErrors && version === requestVersion) errorMessage.value = error.message;
  } finally {
    if (version === requestVersion) {
      pollAbort = null;
      schedulePoll();
    }
  }
}

async function onFilesSelected(event) {
  const files = Array.from(event.target.files || []);
  event.target.value = '';
  errorMessage.value = '';
  uploadFailures.value = [];
  try {
    validateInvoiceFiles(files);
  } catch (error) {
    errorMessage.value = error.message;
    return;
  }
  uploading.value = true;
  const controller = operationController();
  const operationVersion = operationContext.current();
  try {
    if (!batchName.value) {
      const created = await createInvoiceBatch({ signal: controller.signal });
      if (!operationContext.isCurrent(operationVersion)) return;
      batchName.value = created.name;
      batchSummary.value = created;
      emit('batch-created', created);
    }
    const results = await uploadInvoiceFiles(files, batchName.value, { signal: controller.signal });
    if (!operationContext.isCurrent(operationVersion)) return;
    uploadFailures.value = results.filter((result) => result.error);
    await refreshBatch(true);
  } catch (error) {
    if (error?.name !== 'AbortError' && !disposed && operationContext.isCurrent(operationVersion)) errorMessage.value = error.message;
  } finally {
    finishOperation(controller);
    if (operationContext.isCurrent(operationVersion)) uploading.value = false;
  }
}

function warningFields(row) {
  try {
    const warnings = typeof row.field_warnings === 'string' ? JSON.parse(row.field_warnings) : row.field_warnings;
    return new Set((Array.isArray(warnings) ? warnings : []).flatMap((warning) => [warning?.field, ...(warning?.fields || [])]).filter(Boolean));
  } catch {
    return new Set();
  }
}

function fieldClass(row, field) {
  const warned = warningFields(row).has(field) || String(row.field_warnings || '').includes(field) || row[field] === null || row[field] === undefined || String(row[field]).trim() === '';
  return ['w-full rounded border px-2 py-1 text-xs', warned ? 'border-amber-400 bg-amber-50' : 'border-slate-300', row.recognition_status === labels.confirmed ? 'bg-slate-100' : 'bg-white'];
}

function lineLabel(line) {
  return line.description || line.expense_item || line.title || line.line_key;
}

async function withBusy(row, action) {
  if (busyNames.value.has(row.name)) return;
  stopPolling();
  busyNames.value = new Set([...busyNames.value, row.name]);
  errorMessage.value = '';
  const controller = operationController();
  const operationVersion = operationContext.current();
  try {
    const changed = await action(controller.signal);
    if (!operationContext.isCurrent(operationVersion)) return;
    if (changed?.name) replaceRows(rows.value.map((item) => item.name === changed.name ? { ...item, ...changed } : item));
    else await refreshBatch(true);
  } catch (error) {
    if (error?.name !== 'AbortError' && !disposed && operationContext.isCurrent(operationVersion)) errorMessage.value = error.message;
  } finally {
    finishOperation(controller);
    if (operationContext.isCurrent(operationVersion)) {
      const next = new Set(busyNames.value);
      next.delete(row.name);
      busyNames.value = next;
      schedulePoll();
    }
  }
}

function saveField(row, field) {
  if (!INVOICE_FIELDS.includes(field) || !isEditable(row)) return;
  withBusy(row, (signal) => updateInvoice(row.name, { [field]: row[field] }, { signal }));
}

function confirmRow(row) {
  withBusy(row, (signal) => confirmInvoice(row.name, Object.fromEntries(INVOICE_FIELDS.map((field) => [field, row[field]])), { signal }));
}

function retryRow(row) {
  withBusy(row, (signal) => retryInvoice(row.name, { signal }));
}

function excludeRow(row) {
  const reason = globalThis.window?.prompt?.('\u8bf7\u8f93\u5165\u6392\u9664\u539f\u56e0')?.trim();
  if (reason) withBusy(row, (signal) => excludeInvoice(row.name, reason, { signal }));
}

function resolveRow(row) {
  const reason = globalThis.window?.prompt?.('\u8bf7\u8f93\u5165\u89e3\u9664\u91cd\u590d\u7684\u6838\u5bf9\u539f\u56e0')?.trim();
  if (reason) withBusy(row, (signal) => resolveDuplicate(row.name, reason, { signal }));
}

async function changeLink(row, expenseLineKey) {
  stopPolling();
  const previous = row.expense_line_key || '';
  row.expense_line_key = expenseLineKey;
  const controller = operationController();
  const operationVersion = operationContext.current();
  try {
    const result = await linkInvoice(row.name, props.request, expenseLineKey, { signal: controller.signal });
    if (!operationContext.isCurrent(operationVersion)) return;
    emit('link-change', { invoice: row.name, expense_line_key: expenseLineKey, request: props.request, persisted: result?.persisted !== false });
    replaceRows(rows.value);
  } catch (error) {
    if (operationContext.isCurrent(operationVersion)) {
      row.expense_line_key = previous;
      if (error?.name !== 'AbortError' && !disposed) errorMessage.value = error.message;
    }
  } finally {
    finishOperation(controller);
    if (operationContext.isCurrent(operationVersion)) schedulePoll();
  }
}

onBeforeUnmount(() => {
  disposed = true;
  stopPolling();
  operationContext.invalidate();
});
</script>
