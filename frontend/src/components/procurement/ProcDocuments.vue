<script setup>
// 需求附件（业务资料）：列表、上传、作废（审批开始后要写原因，原因在行内填，不再弹窗）。
// 报价、合同、送货单、验收记录属于价格审批单和 PO，在对应页面上传；这里只留需求附件，
// 以及旧单据里还要求补齐的资料（documentChecklistForRequest 不为空时才出现）。
import { computed, ref, watch } from 'vue';
import { csrfHeaders } from '../../lib/expenseClaims.js';
import { documentChecklistForRequest } from '../../lib/businessDocumentChecklist.js';
import { copiedToLabels } from '../../lib/procurementView.js';
import { apiGet, apiPost, errText } from './procData.js';
import { useProc } from './context.js';

const props = defineProps({
  request: { type: String, default: '' },
  row: { type: Object, default: null },
  // 单据已被批准、归档或别人的草稿时不让上传
  readonly: { type: Boolean, default: false },
});
const ctx = useProc();
const docs = ref([]);
const uploading = ref(false);
const input = ref(null);
const uploadType = ref('需求申请');
const removing = ref('');
const reason = ref('');
let requested = '';

async function load() {
  const name = props.request;
  requested = name;
  if (!name) { docs.value = []; return; }
  try {
    const rows = (await apiGet('oa_entry.list_approval_business_documents', { request: name })) || [];
    if (requested === name) docs.value = rows;
  } catch (error) {
    if (requested === name) ctx.flash('', errText(error, '资料加载失败'));
  }
}

watch(() => props.request, load, { immediate: true });
defineExpose({ reload: load });

const checklist = computed(() => documentChecklistForRequest(props.row, docs.value));
const missing = computed(() => checklist.value.filter((item) => item.required && !item.satisfied).length);
const active = computed(() => docs.value.filter((doc) => doc.status !== '已作废'));
const copied = computed(() => copiedToLabels(props.row));
// 草稿和刚批准、还没询价的资料删除不留痕，其余要写作废原因（后端同样要求）。
const needsReason = computed(() => props.row?.workflow_status !== '草稿' && props.row?.business_status !== '需求已批准/待询价');

function pick(type) {
  uploadType.value = type;
  input.value?.click();
}

async function upload(event) {
  const file = event.target.files?.[0];
  event.target.value = '';
  if (!file || !props.request) { ctx.flash('', '请先保存草稿或选择申请单，再上传资料'); return; }
  uploading.value = true;
  ctx.flash();
  try {
    const body = new FormData();
    body.append('file', file);
    body.append('is_private', '1');
    const response = await fetch('/api/method/upload_file', { method: 'POST', body, credentials: 'same-origin', headers: csrfHeaders() });
    const data = await response.json();
    if (!response.ok || data.exc) throw new Error(data.message || '上传失败');
    await apiPost('oa_entry.attach_approval_business_document', { request: props.request, document_type: uploadType.value, file_ref: data.message.name });
    ctx.flash('资料已归档');
    await load();
  } catch (error) {
    ctx.flash('', errText(error, '上传失败'));
  } finally {
    uploading.value = false;
  }
}

function askRemove(doc) {
  removing.value = doc.name;
  reason.value = '';
}

async function confirmRemove(doc) {
  if (needsReason.value && !reason.value.trim()) { ctx.flash('', '审批开始后的资料会保留审计记录，请填写作废原因'); return; }
  try {
    await apiPost('oa_entry.remove_approval_business_document', { name: doc.name, reason: reason.value.trim() });
    ctx.flash(reason.value.trim() ? '资料已作废并保留审计记录' : '错误资料已删除');
    removing.value = '';
    await load();
  } catch (error) {
    ctx.flash('', errText(error, '资料移除失败'));
  }
}
</script>

<template>
  <section class="panel pr-docs">
    <div class="pt"><span>需求附件</span><span class="muted">{{ active.length }} 份</span></div>
    <div v-for="doc in docs" :key="doc.name" :class="['pr-doc', { void: doc.status === '已作废' }]">
      <div class="pr-doc-main">
        <a :href="doc.file" target="_blank" rel="noopener" class="ellipsis">{{ doc.original_filename }}</a>
        <span class="muted">{{ doc.document_type }} · v{{ doc.version_no }}<template v-if="doc.status === '已作废'"> · 已作废</template></span>
      </div>
      <button v-if="doc.status !== '已作废' && !readonly && removing !== doc.name" type="button" class="link" @click="askRemove(doc)">作废</button>
      <div v-if="removing === doc.name" class="pr-inline-form">
        <input v-model="reason" :placeholder="needsReason ? '作废原因（必填）' : '作废原因（可选）'" aria-label="作废原因" />
        <button type="button" class="btn sm danger" @click="confirmRemove(doc)">确认作废</button>
        <button type="button" class="btn sm" @click="removing = ''">取消</button>
      </div>
    </div>
    <div v-if="!docs.length" class="muted">暂无已归档资料</div>

    <div v-for="item in checklist" :key="item.key" class="pr-check">
      <div class="split"><b>{{ item.label }}</b><span :class="['pill', item.satisfied ? 'p-jade' : 'p-sun']">{{ item.satisfied ? '已满足' : '待补资料' }}</span></div>
      <div class="muted">{{ item.description }}</div>
      <div v-if="!item.satisfied && item.uploadTypes?.length && !readonly" class="actions">
        <button v-for="type in item.uploadTypes" :key="type" type="button" class="btn sm" :disabled="uploading || !request" @click="pick(type)">上传{{ type }}</button>
      </div>
    </div>
    <div v-if="missing" class="muted">当前节点还缺 {{ missing }} 项资料。</div>

    <div v-if="!readonly" class="actions">
      <button type="button" class="btn" :disabled="uploading || !request" @click="pick('需求申请')">{{ uploading ? '上传中…' : '＋ 上传附件' }}</button>
    </div>
    <input ref="input" type="file" class="pr-hidden" accept=".pdf,.png,.jpg,.jpeg,.doc,.docx,.xls,.xlsx" :disabled="uploading || !request" aria-label="选择附件" @change="upload" />
    <div v-if="ctx.isProcurement" class="muted pr-docs-note">报价、合同、送货单、验收记录不在这里：它们属于价格审批单和 PO，在对应页面上传。</div>
    <div v-if="copied.length" class="muted pr-copy">抄送：{{ copied.join('、') }}</div>
  </section>
</template>
