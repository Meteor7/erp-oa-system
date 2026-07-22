<template>
  <Teleport to='body'>
    <div v-if="open && invoiceName" class='fixed inset-0 z-50 flex justify-end bg-gray-900/50' role='dialog' aria-modal='true' @click.self='closeDrawer'>
      <aside class='flex h-full w-full max-w-4xl flex-col bg-white shadow-2xl'>
        <header class='flex items-center justify-between border-b border-gray-200 px-4 py-3'>
          <div class='min-w-0'>
            <h3 class='font-semibold text-gray-900'>&#x53D1;&#x7968;&#x9884;&#x89C8;</h3>
            <p class='truncate text-xs text-gray-500'>{{ metadata?.display_name || invoiceName }}</p>
          </div>
          <button type='button' class='rounded-lg px-3 py-2 text-sm text-gray-600 hover:bg-gray-100' @click='closeDrawer'>&#x5173;&#x95ED;</button>
        </header>
        <div class='relative flex-1 overflow-hidden bg-gray-100'>
          <p v-if='loading' class='absolute inset-0 grid place-items-center text-sm text-gray-500'>&#x5B89;&#x5168;&#x9884;&#x89C8;&#x52A0;&#x8F7D;&#x4E2D;...</p>
          <p v-else-if='errorMessage' role='alert' class='m-4 rounded-lg bg-red-50 p-3 text-sm text-red-700'>{{ errorMessage }}</p>
          <iframe v-else-if='objectUrl && isPdf' :src='objectUrl' title='Invoice PDF preview' class='h-full w-full border-0 bg-white' sandbox></iframe>
          <div v-else-if='objectUrl' class='flex h-full items-center justify-center overflow-auto p-4'>
            <img :src='objectUrl' alt='Invoice preview' class='max-h-full max-w-full select-none object-contain shadow-lg' draggable='false'>
          </div>
          <div v-if='objectUrl' class='watermark pointer-events-none absolute inset-0 grid grid-cols-3 content-around overflow-hidden text-center' aria-hidden='true'>
            <span v-for='index in 12' :key='index' class='-rotate-12 whitespace-nowrap text-xs font-semibold text-gray-700/25'>{{ watermarkText }}</span>
          </div>
        </div>
      </aside>
    </div>
  </Teleport>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import { fetchInvoicePreview } from '../../lib/invoiceOcr.js';

// Security contract: preview_invoice POST -> token -> preview_url POST -> blob URL.
const props = defineProps({
  open: { type: Boolean, default: false },
  invoice: { type: [String, Object], default: '' },
  currentUser: { type: String, default: '' },
});
const emit = defineEmits(['close']);
const loading = ref(false);
const errorMessage = ref('');
const metadata = ref(null);
const objectUrl = ref('');
const loadedMimeType = ref('');
const viewedAt = ref('');
let controller = null;
let loadVersion = 0;
let disposed = false;

const invoiceName = computed(() => typeof props.invoice === 'string' ? props.invoice : props.invoice?.name || '');
const isPdf = computed(() => (loadedMimeType.value || metadata.value?.mime_type || '').toLowerCase().split(';')[0] === 'application/pdf');
const watermarkText = computed(() => `${props.currentUser || globalThis.window?.frappe?.session?.user || 'user'}  ${viewedAt.value}`);

function revokePreview() {
  if (objectUrl.value) URL.revokeObjectURL(objectUrl.value);
  objectUrl.value = '';
}
function cancelLoad() {
  loadVersion += 1;
  controller?.abort();
  controller = null;
  loading.value = false;
}
async function loadPreview() {
  cancelLoad();
  revokePreview();
  metadata.value = null;
  loadedMimeType.value = '';
  errorMessage.value = '';
  if (!props.open || !invoiceName.value || disposed) return;
  const version = loadVersion;
  controller = new AbortController();
  loading.value = true;
  try {
    const result = await fetchInvoicePreview(invoiceName.value, { signal: controller.signal });
    if (disposed || version !== loadVersion || !props.open) return;
    metadata.value = result.metadata;
    loadedMimeType.value = result.blob.type || result.metadata?.mime_type || '';
    viewedAt.value = new Date().toLocaleString();
    revokePreview();
    objectUrl.value = URL.createObjectURL(result.blob);
  } catch (error) {
    if (error?.name !== 'AbortError' && version === loadVersion) errorMessage.value = error.message;
  } finally {
    if (version === loadVersion) {
      controller = null;
      loading.value = false;
    }
  }
}
function closeDrawer() {
  cancelLoad();
  revokePreview();
  metadata.value = null;
  emit('close');
}
watch(() => [props.open, invoiceName.value], ([open, name], previous = []) => {
  if (open && name && (open !== previous[0] || name !== previous[1])) loadPreview();
  if (!open) {
    cancelLoad();
    revokePreview();
  }
}, { immediate: true });
onBeforeUnmount(() => {
  disposed = true;
  cancelLoad();
  revokePreview();
});
</script>

<style scoped>
.watermark {
  text-shadow: 0 0 1px rgb(255 255 255 / 60%);
}
</style>
