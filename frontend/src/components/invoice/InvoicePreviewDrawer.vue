<template>
  <Teleport to="body">
    <div v-if="open && invoiceName" class="fixed inset-0 z-[80] flex justify-end bg-gray-900/55" role="dialog" aria-modal="true" tabindex="-1" @click.self="closeDrawer" @keydown.esc="closeDrawer">
      <aside class="flex h-full w-full max-w-5xl flex-col bg-white shadow-2xl">
        <header class="flex items-center justify-between border-b border-gray-200 px-4 py-3">
          <div class="min-w-0">
            <h3 v-if="title" class="font-semibold text-gray-900">{{ title }}</h3>
            <h3 v-else class="font-semibold text-gray-900">&#x53D1;&#x7968;&#x9884;&#x89C8;</h3>
            <p class="truncate text-xs text-gray-500">{{ metadata?.display_name || invoiceName }}</p>
          </div>
          <button type="button" class="rounded-lg border border-gray-200 px-3 py-2 text-sm text-gray-700 hover:bg-gray-100" @click="closeDrawer">&#x5173;&#x95ED;</button>
        </header>
        <div v-if="isPdf && pdfDocument && !errorMessage" class="flex items-center justify-center gap-2 border-b bg-gray-50 px-3 py-2 text-sm text-gray-700">
          <button class="rounded border bg-white px-3 py-1 disabled:text-gray-300" :disabled="pageNumber <= 1 || loading" @click="changePage(-1)">&#x4E0A;&#x4E00;&#x9875;</button>
          <span>{{ pageNumber }} / {{ pageCount }}</span>
          <button class="rounded border bg-white px-3 py-1 disabled:text-gray-300" :disabled="pageNumber >= pageCount || loading" @click="changePage(1)">&#x4E0B;&#x4E00;&#x9875;</button>
          <span class="mx-2 h-5 border-l"></span>
          <button class="rounded border bg-white px-3 py-1" :disabled="loading" @click="changeScale(-0.15)">-</button>
          <span>{{ Math.round(pageScale * 100) }}%</span>
          <button class="rounded border bg-white px-3 py-1" :disabled="loading" @click="changeScale(0.15)">+</button>
        </div>
        <div class="relative flex-1 overflow-hidden bg-gray-100">
          <p v-if="loading" class="absolute inset-0 z-20 grid place-items-center bg-gray-100/80 text-sm text-gray-600">&#x5B89;&#x5168;&#x9884;&#x89C8;&#x52A0;&#x8F7D;&#x4E2D;...</p>
          <p v-else-if="errorMessage" role="alert" class="m-4 rounded-lg bg-red-50 p-3 text-sm text-red-700">{{ errorMessage }}</p>
          <div v-show="isPdf && pdfDocument && !errorMessage" class="h-full overflow-auto p-4 text-center">
            <canvas ref="pdfCanvas" class="mx-auto bg-white shadow-lg"></canvas>
          </div>
          <div v-if="objectUrl && !isPdf && !errorMessage" class="flex h-full items-center justify-center overflow-auto p-4">
            <img :src="objectUrl" alt="Invoice preview" class="max-h-full max-w-full select-none object-contain shadow-lg" draggable="false">
          </div>
          <div v-if="hasPreview" class="watermark pointer-events-none absolute inset-0 grid grid-cols-3 content-around overflow-hidden text-center" aria-hidden="true">
            <span v-for="index in 12" :key="index" class="-rotate-12 whitespace-nowrap text-xs font-semibold text-gray-700/25">{{ watermarkText }}</span>
          </div>
        </div>
      </aside>
    </div>
  </Teleport>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, ref, shallowRef, watch } from 'vue';
import { GlobalWorkerOptions, getDocument } from 'pdfjs-dist/build/pdf.mjs';
import pdfWorkerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url';
import { fetchInvoicePreview } from '../../lib/invoiceOcr.js';

GlobalWorkerOptions.workerSrc = pdfWorkerUrl;

// Security contract: preview_invoice POST -> one-time preview token -> local canvas or image blob.
const props = defineProps({
  open: { type: Boolean, default: false },
  invoice: { type: [String, Object], default: '' },
  currentUser: { type: String, default: '' },
  title: { type: String, default: '' },
  previewLoader: { type: Function, default: fetchInvoicePreview },
});
const emit = defineEmits(['close']);
const loading = ref(false);
const errorMessage = ref('');
const metadata = ref(null);
const objectUrl = ref('');
const loadedMimeType = ref('');
const viewedAt = ref('');
const pdfCanvas = ref(null);
const pdfDocument = shallowRef(null);
const pageNumber = ref(1);
const pageCount = ref(0);
const pageScale = ref(1.15);
let controller = null;
let loadingTask = null;
let renderTask = null;
let loadVersion = 0;
let disposed = false;

const invoiceName = computed(() => typeof props.invoice === 'string' ? props.invoice : props.invoice?.name || '');
const isPdf = computed(() => (loadedMimeType.value || metadata.value?.mime_type || '').toLowerCase().split(';')[0] === 'application/pdf');
const hasPreview = computed(() => Boolean((isPdf.value && pdfDocument.value) || objectUrl.value));
const watermarkText = computed(() => `${props.currentUser || globalThis.window?.frappe?.session?.user || 'user'}  ${viewedAt.value}`);

function revokePreview() {
  if (objectUrl.value) URL.revokeObjectURL(objectUrl.value);
  objectUrl.value = '';
}
function cancelPdfRender() {
  try { renderTask?.cancel(); } catch { /* already complete */ }
  renderTask = null;
}
async function destroyPdf() {
  cancelPdfRender();
  const task = loadingTask;
  const document = pdfDocument.value;
  loadingTask = null;
  pdfDocument.value = null;
  pageCount.value = 0;
  try { await task?.destroy?.(); } catch { /* cleanup is best effort */ }
  if (document && document !== task?._transport) {
    try { await document.destroy?.(); } catch { /* cleanup is best effort */ }
  }
}
function cancelLoad() {
  loadVersion += 1;
  controller?.abort();
  controller = null;
  loading.value = false;
  cancelPdfRender();
}
async function renderPdfPage() {
  if (!pdfDocument.value || !pdfCanvas.value || disposed) return;
  cancelPdfRender();
  const page = await pdfDocument.value.getPage(pageNumber.value);
  const viewport = page.getViewport({ scale: pageScale.value });
  const canvas = pdfCanvas.value;
  const context = canvas.getContext('2d', { alpha: false });
  const outputScale = Math.max(1, Math.min(Number(globalThis.devicePixelRatio || 1), 2));
  canvas.width = Math.floor(viewport.width * outputScale);
  canvas.height = Math.floor(viewport.height * outputScale);
  canvas.style.width = `${Math.floor(viewport.width)}px`;
  canvas.style.height = `${Math.floor(viewport.height)}px`;
  renderTask = page.render({
    canvasContext: context,
    viewport,
    transform: outputScale === 1 ? null : [outputScale, 0, 0, outputScale, 0, 0],
  });
  try {
    await renderTask.promise;
  } catch (error) {
    if (error?.name !== 'RenderingCancelledException') throw error;
  } finally {
    renderTask = null;
  }
}
async function loadPdf(blob, version) {
  const bytes = new Uint8Array(await blob.arrayBuffer());
  if (disposed || version !== loadVersion || !props.open) return;
  loadingTask = getDocument({ data: bytes, useWorkerFetch: false, isEvalSupported: false });
  const document = await loadingTask.promise;
  if (disposed || version !== loadVersion || !props.open) {
    await document.destroy();
    return;
  }
  pdfDocument.value = document;
  pageCount.value = document.numPages;
  pageNumber.value = 1;
  await nextTick();
  await renderPdfPage();
}
async function loadPreview() {
  cancelLoad();
  await destroyPdf();
  revokePreview();
  metadata.value = null;
  loadedMimeType.value = '';
  errorMessage.value = '';
  if (!props.open || !invoiceName.value || disposed) return;
  const version = loadVersion;
  controller = new AbortController();
  loading.value = true;
  try {
    const result = await props.previewLoader(invoiceName.value, { signal: controller.signal });
    if (disposed || version !== loadVersion || !props.open) return;
    metadata.value = result.metadata;
    loadedMimeType.value = result.blob.type || result.metadata?.mime_type || '';
    viewedAt.value = new Date().toLocaleString();
    if (isPdf.value) await loadPdf(result.blob, version);
    else objectUrl.value = URL.createObjectURL(result.blob);
  } catch (error) {
    if (error?.name !== 'AbortError' && error?.name !== 'RenderingCancelledException' && version === loadVersion) {
      errorMessage.value = error?.message || '\u9884\u89c8\u52a0\u8f7d\u5931\u8d25';
    }
  } finally {
    if (version === loadVersion) {
      controller = null;
      loading.value = false;
    }
  }
}
async function changePage(delta) {
  const nextPage = Math.min(pageCount.value, Math.max(1, pageNumber.value + delta));
  if (nextPage === pageNumber.value) return;
  pageNumber.value = nextPage;
  loading.value = true;
  try { await renderPdfPage(); } finally { loading.value = false; }
}
async function changeScale(delta) {
  pageScale.value = Math.min(2.5, Math.max(0.55, Math.round((pageScale.value + delta) * 100) / 100));
  loading.value = true;
  try { await renderPdfPage(); } finally { loading.value = false; }
}
async function closeDrawer() {
  cancelLoad();
  await destroyPdf();
  revokePreview();
  metadata.value = null;
  emit('close');
}
watch(() => [props.open, invoiceName.value], ([open, name], previous = []) => {
  if (open && name && (open !== previous[0] || name !== previous[1])) loadPreview();
  if (!open) {
    cancelLoad();
    destroyPdf();
    revokePreview();
  }
}, { immediate: true });
onBeforeUnmount(() => {
  disposed = true;
  cancelLoad();
  destroyPdf();
  revokePreview();
});
</script>

<style scoped>
.watermark {
  text-shadow: 0 0 1px rgb(255 255 255 / 60%);
}
</style>
