<script setup>
import { computed, reactive, ref, watch } from 'vue';
import { createResource } from 'frappe-ui';
import { useRoute } from 'vue-router';

const route = useRoute();
const config = computed(() => ({
  '/approval/procurement': { requestType: '采购申请', title: '采购申请' },
  '/approval/direct-purchase': { requestType: '购买申请', title: '购买申请' },
  '/approval/procurement-payment': { requestType: '采购付款', title: '采购付款' },
}[route.path] || { requestType: '采购申请', title: '采购申请' }));
const isPayment = computed(() => config.value.requestType === '采购付款');
const form = reactive({
  subject: '', reason: '', urgency: '一般', asset_nature: '非固定资产',
  fixed_asset_category: '', source_request: '',
  business_lines: [{ item_name: '', specification: '', quantity: 1, unit: '个', unit_price: 0, remarks: '' }],
});
const draftName = ref('');
const message = ref('');
const error = ref('');
const documentType = ref('合同');
const documents = ref([]);
const saving = ref(false);
const uploading = ref(false);
const documentTypes = ['需求申请', '报价单', '价格审批表', 'PR', 'PO', '合同', '付款计划', '发票', '验收资料', '送货单', '收料单', '入库单', '付款回单', '采购完成报告'];
const fixedCategories = ['办公家具、工具及器具', '电子设备、研发专用设备、仪器仪表', '生产设备、生产工具及器具'];
const saver = createResource({ url: 'rayher_hr_payroll.api.oa_entry.save_approval_center_draft' });
const attacher = createResource({ url: 'rayher_hr_payroll.api.oa_entry.attach_approval_business_document' });
const documentLoader = createResource({ url: 'rayher_hr_payroll.api.oa_entry.list_approval_business_documents', method: 'GET' });
watch(() => route.path, () => {
  draftName.value = '';
  documents.value = [];
  message.value = '';
  error.value = '';
});

function addLine() {
  if (form.business_lines.length < 100) form.business_lines.push({ item_name: '', specification: '', quantity: 1, unit: '个', unit_price: 0, remarks: '' });
}
function removeLine(index) {
  if (form.business_lines.length > 1) form.business_lines.splice(index, 1);
}
function cleanPayload() {
  return {
    subject: form.subject,
    reason: form.reason,
    urgency: form.urgency,
    asset_nature: form.asset_nature,
    fixed_asset_category: form.asset_nature === '固定资产' ? form.fixed_asset_category : '',
    source_request: isPayment.value ? form.source_request : '',
    business_lines: form.business_lines.map((line) => ({ ...line })),
  };
}
async function saveDraft() {
  saving.value = true; error.value = ''; message.value = '';
  try {
    const result = await saver.submit({ request_type: config.value.requestType, payload: JSON.stringify(cleanPayload()), name: draftName.value || undefined });
    draftName.value = result.name;
    message.value = `草稿 ${result.name} 已保存`;
    await loadDocuments();
  } catch (e) {
    error.value = e?.messages?.[0] || e?.message || '保存失败';
  } finally { saving.value = false; }
}
async function loadDocuments() {
  if (!draftName.value) return;
  documents.value = await documentLoader.fetch({ request: draftName.value }) || [];
}
async function uploadDocument(event) {
  const file = event.target.files?.[0];
  event.target.value = '';
  if (!file || !draftName.value) { error.value = '请先保存草稿，再上传资料'; return; }
  uploading.value = true; error.value = '';
  try {
    const body = new FormData();
    body.append('file', file);
    body.append('is_private', '1');
    const response = await fetch('/api/method/upload_file', { method: 'POST', body, credentials: 'same-origin', headers: { 'X-Frappe-CSRF-Token': window.csrf_token || '' } });
    const data = await response.json();
    if (!response.ok || data.exc) throw new Error(data.message || '上传失败');
    await attacher.submit({ request: draftName.value, document_type: documentType.value, file_ref: data.message.name });
    message.value = '资料已归档并生成新版本';
    await loadDocuments();
  } catch (e) { error.value = e?.messages?.[0] || e?.message || '上传失败'; }
  finally { uploading.value = false; }
}
</script>

<template>
  <div class='space-y-5'>
    <section class='rounded-lg border bg-white p-6 shadow-sm'>
      <div class='flex items-start justify-between gap-4'>
        <div><h1 class='text-xl font-semibold'>{{ config.title }}</h1><p class='mt-1 text-sm text-gray-500'>审批中心 · 申请与资料归档安全底座</p></div>
        <span v-if='draftName' class='rounded bg-gray-100 px-3 py-1 text-sm'>{{ draftName }}</span>
      </div>
      <div class='mt-4 rounded border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800'>审批流程尚未配置，当前仅可保存本地草稿。</div>
      <div class='mt-5 grid gap-4 md:grid-cols-2'>
        <label class='text-sm'>主题<input v-model='form.subject' class='mt-1 w-full rounded border px-3 py-2' maxlength='140' /></label>
        <label class='text-sm'>紧急程度<select v-model='form.urgency' class='mt-1 w-full rounded border px-3 py-2'><option>一般</option><option>加急</option></select></label>
        <label class='text-sm'>资产属性<select v-model='form.asset_nature' class='mt-1 w-full rounded border px-3 py-2'><option>非固定资产</option><option>固定资产</option></select></label>
        <label v-if='form.asset_nature === "固定资产"' class='text-sm'>固定资产类别<select v-model='form.fixed_asset_category' class='mt-1 w-full rounded border px-3 py-2'><option value=''>请选择</option><option v-for='item in fixedCategories' :key='item'>{{ item }}</option></select></label>
        <label v-if='isPayment' class='text-sm'>关联采购申请<input v-model='form.source_request' class='mt-1 w-full rounded border px-3 py-2' maxlength='140' placeholder='可暂不关联；关联时必须为已完成采购申请' /></label>
        <label class='text-sm md:col-span-2'>申请说明<textarea v-model='form.reason' class='mt-1 w-full rounded border px-3 py-2' maxlength='1000'></textarea></label>
      </div>
    </section>

    <section class='rounded-lg border bg-white p-6 shadow-sm'>
      <div class='mb-3 flex items-center justify-between'><h2 class='font-semibold'>采购/购买明细</h2><button type='button' class='rounded border px-3 py-1.5 text-sm' @click='addLine'>添加一行</button></div>
      <div class='overflow-x-auto'><table class='min-w-full text-sm'><thead><tr class='border-b text-left text-gray-500'><th class='p-2'>物品名称</th><th class='p-2'>规格</th><th class='p-2'>数量</th><th class='p-2'>单位</th><th class='p-2'>单价</th><th class='p-2'>备注</th><th></th></tr></thead><tbody>
        <tr v-for='(line, index) in form.business_lines' :key='index' class='border-b'><td class='p-2'><input v-model='line.item_name' class='w-40 rounded border px-2 py-1.5' /></td><td class='p-2'><input v-model='line.specification' class='w-32 rounded border px-2 py-1.5' /></td><td class='p-2'><input v-model.number='line.quantity' type='number' min='0.0001' step='0.0001' class='w-24 rounded border px-2 py-1.5' /></td><td class='p-2'><input v-model='line.unit' class='w-20 rounded border px-2 py-1.5' /></td><td class='p-2'><input v-model.number='line.unit_price' type='number' min='0' step='0.01' class='w-28 rounded border px-2 py-1.5' /></td><td class='p-2'><input v-model='line.remarks' class='w-40 rounded border px-2 py-1.5' /></td><td><button type='button' class='text-red-600' @click='removeLine(index)'>删除</button></td></tr>
      </tbody></table></div>
      <div class='mt-4 flex items-center gap-3'><button type='button' class='rounded bg-gray-900 px-4 py-2 text-white disabled:opacity-50' :disabled='saving' @click='saveDraft'>{{ saving ? '保存中…' : '保存草稿' }}</button><span class='text-sm text-green-700'>{{ message }}</span><span class='text-sm text-red-600'>{{ error }}</span></div>
    </section>

    <section class='rounded-lg border bg-white p-6 shadow-sm'>
      <h2 class='font-semibold'>业务资料归档</h2><p class='mt-1 text-sm text-gray-500'>仅接受私有 PDF、图片及 Office 文件；同一类型重复上传自动生成新版本。</p>
      <div class='mt-3 flex items-center gap-3'><select v-model='documentType' class='rounded border px-3 py-2 text-sm'><option v-for='item in documentTypes' :key='item'>{{ item }}</option></select><label class='cursor-pointer rounded border px-3 py-2 text-sm'>{{ uploading ? '上传中…' : '选择文件并归档' }}<input type='file' class='hidden' :disabled='uploading || !draftName' @change='uploadDocument' /></label></div>
      <div v-if='documents.length' class='mt-4 divide-y rounded border'><div v-for='doc in documents' :key='doc.name' class='flex items-center justify-between p-3 text-sm'><span>{{ doc.document_type }} · {{ doc.original_filename }}</span><span class='text-gray-500'>v{{ doc.version_no }}</span></div></div>
      <p v-else class='mt-4 text-sm text-gray-400'>暂无已归档资料</p>
    </section>
  </div>
</template>