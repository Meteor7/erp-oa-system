<script setup>
// 业务资料：清单 + 已归档文件 + 上传 / 作废。PO 下推的付款只要求发票（付款前提供时），其他资料随便补；
// 没有来源 PO 的旧采购付款沿用旧资料清单。作废原因就地填写，不再弹窗。
import { computed, ref, watch } from 'vue';
import { createResource } from 'frappe-ui';
import {
  INVOICE_BEFORE, isPoSourced, legacyChecklist, missingRequired, poPaymentChecklist, removeNeedsReason, text, validateRemoveReason,
} from '../../lib/paymentView.js';
import { OA_API, errorText, uploadEvidence } from './paymentApi.js';

const props = defineProps({
  request: { type: Object, required: true },
  invoiceRequirement: { type: String, default: '' },
});
const emit = defineEmits(['loaded']);

const loader = createResource({ url: OA_API + 'list_approval_business_documents', method: 'GET' });
const attacher = createResource({ url: OA_API + 'attach_approval_business_document' });
const remover = createResource({ url: OA_API + 'remove_approval_business_document' });

const documents = ref([]);
const uploading = ref(false);
const uploadInput = ref(null);
const uploadType = ref('其他补充资料');
const ok = ref('');
const error = ref('');
const removing = ref('');
const removeReason = ref('');
const noAccess = ref(false);

const poSourced = computed(() => isPoSourced(props.request));
const checklist = computed(() => (poSourced.value
  ? poPaymentChecklist(documents.value, props.invoiceRequirement)
  : legacyChecklist(props.request, documents.value)));
const missing = computed(() => missingRequired(checklist.value));

async function load(name = props.request.name) {
  if (!name) { documents.value = []; emit('loaded', []); return; }
  try {
    const rows = (await loader.fetch({ request: name })) || [];
    if (name === props.request.name) { documents.value = rows; emit('loaded', rows); }
  } catch (err) {
    if (name !== props.request.name) return;
    // 能看到这张单，但未必有权看它的资料（审批人、财务、管理层常见）：不弹红色错误，只提示。
    if (/无权/.test(errorText(err, ''))) noAccess.value = true;
    else error.value = errorText(err, '资料加载失败');
  }
}
watch(() => props.request.name, () => { ok.value = ''; error.value = ''; noAccess.value = false; removing.value = ''; documents.value = []; load(); }, { immediate: true });

function pick(type) {
  uploadType.value = type;
  uploadInput.value?.click();
}
async function onUpload(event) {
  const file = event.target.files?.[0];
  event.target.value = '';
  if (!file || !props.request.name) return;
  uploading.value = true;
  ok.value = '';
  error.value = '';
  try {
    const evidence = await uploadEvidence(file);
    await attacher.submit({ request: props.request.name, document_type: uploadType.value, file_ref: evidence.name });
    ok.value = '资料已归档并生成新版本';
    await load();
  } catch (err) { error.value = errorText(err, '上传失败'); } finally { uploading.value = false; }
}

function askRemove(doc) {
  removing.value = doc.name;
  removeReason.value = '';
  error.value = '';
}
async function confirmRemove(doc) {
  const problem = validateRemoveReason(props.request, removeReason.value);
  if (problem) { error.value = problem; return; }
  try {
    await remover.submit({ name: doc.name, reason: removeReason.value.trim() });
    ok.value = removeNeedsReason(props.request) ? '资料已作废并保留审计记录' : '错误资料已删除';
    removing.value = '';
    await load();
  } catch (err) { error.value = errorText(err, '资料移除失败'); }
}
defineExpose({ load });
</script>

<template>
  <section class="panel pay-docs">
    <div class="pt"><span>业务资料</span><span class="muted">{{ documents.filter((d) => d.status !== '已作废').length }} 份</span></div>
    <div v-if="ok" class="banner ok" role="status">{{ ok }}</div>
    <div v-if="error" class="banner err" role="alert">{{ error }}</div>

    <div v-for="doc in documents" :key="doc.name" class="pay-doc" :class="{ void: doc.status === '已作废' }">
      <a :href="doc.file" target="_blank" rel="noopener" class="grow-col">
        <span class="ellipsis">{{ doc.original_filename }}</span>
        <span class="muted">{{ doc.document_type }} · v{{ doc.version_no }}<template v-if="doc.status === '已作废'"> · 已作废</template></span>
      </a>
      <button v-if="doc.status !== '已作废'" type="button" class="btn sm" title="删除或作废资料" @click="askRemove(doc)">作废</button>
      <div v-if="removing === doc.name" class="pay-remove">
        <input v-model="removeReason" type="text" class="cell" :placeholder="removeNeedsReason(request) ? '作废原因（必填）' : '原因（可选）'" aria-label="作废原因" />
        <button type="button" class="btn sm danger" @click="confirmRemove(doc)">确认作废</button>
        <button type="button" class="btn sm" @click="removing = ''">取消</button>
      </div>
    </div>
    <p v-if="noAccess" class="muted">你没有权限查看这张付款单的资料（发票等）。需要查看请联系申请人或财务。</p>
    <p v-else-if="!documents.length" class="muted">暂无已归档资料</p>

    <div v-for="item in (noAccess ? [] : checklist)" :key="item.key" class="pay-check">
      <div class="split"><b>{{ item.label }}</b><span class="pill" :class="`p-${item.tone}`">{{ item.state }}</span></div>
      <span class="muted">{{ item.hint }}</span>
      <span v-if="item.matched?.length" class="muted">已归档：{{ item.matched.join('、') }}</span>
      <div v-if="item.uploadTypes?.length && (!item.satisfied || item.key === 'invoice')" class="head-actions">
        <button v-for="type in item.uploadTypes" :key="type" type="button" class="btn sm" :disabled="uploading" @click="pick(type)">＋ 上传{{ type }}</button>
      </div>
    </div>

    <div v-if="!noAccess" class="pay-docs-foot">
      <button type="button" class="btn" :disabled="uploading" @click="pick('其他补充资料')">{{ uploading ? '上传中…' : '上传补充资料' }}</button>
      <span class="muted">
        <template v-if="poSourced">报价和合同属于 PO，不再出现在这里的“缺资料”里；到货、验收记录在左边只读显示。<template v-if="text(invoiceRequirement) === INVOICE_BEFORE && missing.length"> 当前缺发票，确认付款时系统会拦下。</template></template>
        <template v-else>当前节点缺少 {{ missing.length }} 项；资料可在审批后补交；到货、验收、付款、退款回单和关闭节点会再次校验。</template>
      </span>
    </div>
    <input ref="uploadInput" type="file" class="pay-hidden" :disabled="uploading" @change="onUpload" />
  </section>
</template>
