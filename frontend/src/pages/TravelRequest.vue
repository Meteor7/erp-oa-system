<script setup>
// 出差申请：只审批"该不该去"，不填金额。审批通过后可以在报销、付款里关联它。
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { callApi, statusTone } from '../lib/expenseClaims.js';

const route = useRoute();
const router = useRouter();
const tab = ref('mine');
const rows = ref([]);
const selected = ref(null);
const projects = ref([]);
const loading = ref(false);
const busy = ref(false);
const errorMessage = ref('');
const message = ref('');
const editorOpen = ref(false);
const editingName = ref('');

const form = reactive({ subject: '', travel_destination: '', travel_start_date: '', travel_end_date: '', reason: '', project: '' });

const days = computed(() => {
  const start = Date.parse(form.travel_start_date);
  const end = Date.parse(form.travel_end_date);
  if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) return 0;
  return Math.round((end - start) / 86400000) + 1;
});
const blockers = computed(() => {
  const messages = [];
  if (!form.subject.trim()) messages.push('请填写主题');
  if (!form.travel_destination.trim()) messages.push('请填写出差地点');
  if (!form.travel_start_date || !form.travel_end_date) messages.push('请填写出发和返回日期');
  else if (days.value <= 0) messages.push('返回日期不能早于出发日期');
  if (!form.reason.trim()) messages.push('请填写出差事由');
  return messages;
});

function fail(error) {
  errorMessage.value = String(error?.message || error || '操作失败');
}

async function run(action) {
  busy.value = true;
  errorMessage.value = '';
  message.value = '';
  try {
    const result = await action();
    await load(selected.value?.name || '');
    return result;
  } catch (error) {
    fail(error);
    return null;
  } finally {
    busy.value = false;
  }
}

async function loadOne(name) {
  const found = await callApi('oa_entry.list_requests', { view: 'all', name, limit: 1 }, { method: 'GET' });
  return (found || [])[0] || null;
}

async function load(selectName = '') {
  loading.value = true;
  try {
    rows.value = await callApi('oa_entry.list_requests', { view: tab.value, request_type: '出差申请', limit: 100 }, { method: 'GET' }) || [];
    const wanted = selectName || selected.value?.name || String(route.query.request || '');
    selected.value = wanted ? await loadOne(wanted) : null;
  } catch (error) {
    fail(error);
  } finally {
    loading.value = false;
  }
}

function openNew() {
  Object.assign(form, { subject: '', travel_destination: '', travel_start_date: '', travel_end_date: '', reason: '', project: '' });
  editingName.value = '';
  editorOpen.value = true;
}

async function openDraft(row) {
  const doc = await loadOne(row.name);
  if (!doc) return;
  Object.assign(form, {
    subject: doc.subject || '', travel_destination: doc.travel_destination || '',
    travel_start_date: doc.travel_start_date || '', travel_end_date: doc.travel_end_date || '',
    reason: doc.reason || '', project: doc.project || '',
  });
  editingName.value = doc.name;
  editorOpen.value = true;
}

async function save({ thenSubmit = false } = {}) {
  const saved = await run(async () => {
    const doc = await callApi('travel_entry.save_travel_draft', { payload: JSON.stringify({ ...form }), name: editingName.value || undefined });
    editingName.value = doc.name;
    if (thenSubmit) await callApi('oa_entry.submit_request', { name: doc.name });
    return doc;
  });
  if (saved) {
    message.value = thenSubmit ? `出差申请 ${saved.name} 已提交` : `草稿 ${saved.name} 已保存`;
    if (thenSubmit) editorOpen.value = false;
    await load(saved.name);
  }
}

async function select(row) {
  selected.value = await loadOne(row.name);
  router.replace({ path: route.path, query: { ...route.query, request: row.name } });
}

async function act(action) {
  const note = action === 'reject' ? (window.prompt('请填写驳回原因') || '').trim() : '';
  if (action === 'reject' && !note) return;
  await run(() => callApi('oa_entry.action_request', { name: selected.value.name, action, note, reject_target: action === 'reject' ? 'applicant' : undefined }));
  message.value = action === 'reject' ? '已驳回给申请人' : '已同意';
}

async function withdraw() {
  const note = (window.prompt('请填写撤回原因（可选）') || '').trim();
  await run(() => callApi('oa_entry.withdraw_request', { name: selected.value.name, note }));
  message.value = '已撤回，单据回到草稿';
}

watch(tab, () => load(''));
onMounted(async () => {
  await load();
  try {
    projects.value = ((await callApi('oa_entry.list_approval_center_projects', {}, { method: 'GET' })) || []).map((row) => row.name || row);
  } catch {
    projects.value = [];
  }
});
</script>

<template>
  <div class="space-y-4">
    <section class="rounded-lg border bg-white p-5 shadow-sm">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 class="text-xl font-semibold">出差申请</h1>
          <p class="mt-1 text-sm text-gray-500">只审批行程，不填金额；审批通过后报销和付款可以关联它。路线：直属主管 → 副总经理。</p>
        </div>
        <button type="button" class="rounded bg-gray-900 px-3 py-1.5 text-sm text-white" :disabled="busy" @click="openNew">新建出差申请</button>
      </div>
      <div class="mt-4 flex gap-2">
        <button v-for="item in [{ key: 'mine', label: '我的申请' }, { key: 'pending', label: '待我处理' }, { key: 'all', label: '全部可见' }]" :key="item.key"
          type="button" class="rounded px-3 py-1.5 text-sm" :class="tab === item.key ? 'bg-gray-900 text-white' : 'border'" @click="tab = item.key">{{ item.label }}</button>
      </div>
      <p v-if="errorMessage" class="mt-3 rounded bg-red-50 px-3 py-2 text-sm text-red-700">{{ errorMessage }}</p>
      <p v-if="message" class="mt-3 rounded bg-emerald-50 px-3 py-2 text-sm text-emerald-700">{{ message }}</p>
    </section>

    <section v-if="editorOpen" class="rounded-lg border bg-white p-5 shadow-sm">
      <div class="flex items-center justify-between">
        <h2 class="font-semibold">{{ editingName ? `编辑草稿 ${editingName}` : '新建出差申请' }}</h2>
        <button type="button" class="text-sm text-gray-500 underline" @click="editorOpen = false">关闭</button>
      </div>
      <div class="mt-4 grid gap-3 md:grid-cols-2">
        <label class="text-sm">主题<input v-model="form.subject" class="mt-1 w-full rounded border px-2 py-1.5" /></label>
        <label class="text-sm">出差地点<input v-model="form.travel_destination" class="mt-1 w-full rounded border px-2 py-1.5" /></label>
        <label class="text-sm">出发日期<input v-model="form.travel_start_date" type="date" class="mt-1 w-full rounded border px-2 py-1.5" /></label>
        <label class="text-sm">返回日期<input v-model="form.travel_end_date" type="date" class="mt-1 w-full rounded border px-2 py-1.5" /></label>
        <label class="text-sm">所属项目
          <select v-model="form.project" class="mt-1 w-full rounded border px-2 py-1.5">
            <option value="">非项目</option>
            <option v-for="project in projects" :key="project" :value="project">{{ project }}</option>
          </select>
        </label>
        <div class="text-sm">出差天数<div class="mt-1 rounded border bg-gray-50 px-2 py-1.5">{{ days || '-' }}</div></div>
        <label class="text-sm md:col-span-2">出差事由<textarea v-model="form.reason" rows="2" class="mt-1 w-full rounded border px-2 py-1.5"></textarea></label>
      </div>
      <div class="mt-4 flex justify-end gap-2 border-t pt-3">
        <button type="button" class="rounded border px-3 py-1.5 text-sm" :disabled="busy" @click="save()">保存草稿</button>
        <button type="button" class="rounded bg-gray-900 px-3 py-1.5 text-sm text-white disabled:opacity-50" :disabled="busy || blockers.length" @click="save({ thenSubmit: true })">提交</button>
      </div>
      <ul v-if="blockers.length" class="mt-2 list-disc pl-5 text-sm text-amber-700"><li v-for="item in blockers" :key="item">{{ item }}</li></ul>
    </section>

    <section class="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      <div class="rounded-lg border bg-white p-4 shadow-sm">
        <p v-if="loading" class="py-8 text-center text-sm text-gray-500">正在加载…</p>
        <table v-else class="min-w-full text-sm">
          <thead><tr class="border-b text-left text-gray-500"><th class="p-2">单号</th><th class="p-2">主题</th><th class="p-2">行程</th><th class="p-2">状态</th></tr></thead>
          <tbody>
            <tr v-for="row in rows" :key="row.name" class="cursor-pointer border-b hover:bg-gray-50" :class="{ 'bg-gray-50': selected?.name === row.name }" @click="select(row)">
              <td class="p-2 font-medium text-blue-700">{{ row.name }}</td>
              <td class="p-2">{{ row.subject }}</td>
              <td class="p-2">{{ row.travel_destination }} · {{ row.travel_start_date }} → {{ row.travel_end_date }}（{{ row.travel_days }} 天）</td>
              <td class="p-2"><span class="rounded px-2 py-0.5 text-xs" :class="statusTone(row.business_status || row.workflow_status)">{{ row.business_status || row.workflow_status }}</span></td>
            </tr>
          </tbody>
        </table>
        <p v-if="!loading && !rows.length" class="py-10 text-center text-gray-400">暂无出差申请。</p>
      </div>

      <div v-if="selected" class="rounded-lg border bg-white p-5 shadow-sm">
        <div class="flex items-start justify-between gap-2">
          <div>
            <h2 class="font-semibold">{{ selected.name }} · {{ selected.subject }}</h2>
            <p class="mt-1 text-sm text-gray-500">{{ selected.employee_name }} · {{ selected.travel_destination }} · {{ selected.travel_start_date }} → {{ selected.travel_end_date }}（{{ selected.travel_days }} 天）</p>
            <p class="mt-1 text-sm text-gray-500">所属项目 {{ selected.project || '非项目' }} · 当前节点 {{ selected.current_step_label || '-' }}</p>
          </div>
          <span class="rounded px-2 py-0.5 text-xs" :class="statusTone(selected.business_status || selected.workflow_status)">{{ selected.business_status || selected.workflow_status }}</span>
        </div>
        <p class="mt-3 whitespace-pre-line text-sm">{{ selected.reason }}</p>
        <ol class="mt-4 space-y-1 text-sm">
          <li v-for="step in selected.steps || []" :key="step.step_index" class="flex justify-between border-b py-1">
            <span>{{ step.step_index }}. {{ step.label }}</span>
            <span class="text-gray-500">{{ step.status }}<span v-if="step.action_by"> · {{ step.action_by }}</span></span>
          </li>
        </ol>
        <div class="mt-4 flex flex-wrap gap-2 border-t pt-3">
          <button v-if="selected.workflow_status === '草稿'" type="button" class="rounded border px-3 py-1.5 text-sm" :disabled="busy" @click="openDraft(selected)">编辑草稿</button>
          <button v-if="selected.can_approve" type="button" class="rounded bg-gray-900 px-3 py-1.5 text-sm text-white" :disabled="busy" @click="act('approve')">同意</button>
          <button v-if="selected.can_reject" type="button" class="rounded border px-3 py-1.5 text-sm" :disabled="busy" @click="act('reject')">驳回</button>
          <button v-if="selected.can_withdraw" type="button" class="rounded border px-3 py-1.5 text-sm" :disabled="busy" @click="withdraw">撤回</button>
        </div>
      </div>
      <div v-else class="rounded-lg border bg-white p-10 text-center text-sm text-gray-400 shadow-sm">在左侧选择一张申请查看明细。</div>
    </section>
  </div>
</template>
