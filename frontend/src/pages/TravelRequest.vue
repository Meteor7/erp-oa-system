<script setup>
// 出差申请：只批该不该去，不设金额；报销、付款关联它即可。版式按已确认的设计稿第 5 版。
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import '../styles/expenseUi.css';
import { callApi, displayStatus, pillClass, stepChips } from '../lib/expenseClaims.js';

const route = useRoute();
const router = useRouter();
const tab = ref('list');
const rows = ref([]);
const selected = ref(null);
const projects = ref([]);
const loading = ref(false);
const busy = ref(false);
const banner = reactive({ ok: '', err: '' });
const editingName = ref('');
const form = reactive({});

function resetForm() {
  Object.assign(form, { subject: '', travel_destination: '', travel_start_date: '', travel_end_date: '', reason: '', project: '' });
  editingName.value = '';
}
resetForm();

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
  else if (!days.value) messages.push('返回日期不能早于出发日期');
  if (!form.reason.trim()) messages.push('请填写出差事由');
  return messages;
});

function flash(ok = '', err = '') {
  banner.ok = ok;
  banner.err = err;
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

const loadOne = async (name) => ((await callApi('oa_entry.list_requests', { view: 'all', name, limit: 1 }, { method: 'GET' })) || [])[0] || null;

async function load() {
  loading.value = true;
  try {
    rows.value = await callApi('oa_entry.list_requests', { view: 'mine', request_type: '出差申请', limit: 100 }, { method: 'GET' }) || [];
    const wanted = String(route.query.request || '') || selected.value?.name || '';
    selected.value = wanted ? await loadOne(wanted) : null;
  } catch (error) {
    flash('', String(error?.message || error));
  } finally {
    loading.value = false;
  }
}

function openNew() {
  resetForm();
  tab.value = 'new';
}

function openDraft(row) {
  resetForm();
  Object.assign(form, {
    subject: row.subject || '', travel_destination: row.travel_destination || '',
    travel_start_date: row.travel_start_date || '', travel_end_date: row.travel_end_date || '',
    reason: row.reason || '', project: row.project || '',
  });
  editingName.value = row.name;
  tab.value = 'new';
}

async function save({ submit = false } = {}) {
  const saved = await run(async () => {
    const doc = await callApi('travel_entry.save_travel_draft', { payload: JSON.stringify({ ...form }), name: editingName.value || undefined });
    editingName.value = doc.name;
    if (submit) await callApi('oa_entry.submit_request', { name: doc.name });
    return doc;
  }, (doc) => (submit ? `出差申请 ${doc.name} 已提交审批` : `草稿 ${doc.name} 已保存`));
  if (saved && submit) {
    resetForm();
    tab.value = 'list';
  }
}

function select(row) {
  router.replace({ path: route.path, query: { request: row.name } });
}

async function act(action) {
  const note = action === 'reject' ? (window.prompt('请填写驳回原因') || '').trim() : '';
  if (action === 'reject' && !note) return;
  await run(() => callApi('oa_entry.action_request', { name: selected.value.name, action, note, reject_target: action === 'reject' ? 'applicant' : undefined }),
    action === 'reject' ? '已驳回给申请人' : '已同意');
}

async function withdraw(row) {
  const note = (window.prompt('请填写撤回原因（可选）') || '').trim();
  await run(() => callApi('oa_entry.withdraw_request', { name: row.name, note }), '已撤回为草稿');
}

function push(row, kind) {
  router.push({ path: kind === 'claim' ? '/approval/claim' : '/approval/payment', query: { source: row.name } });
}

watch(() => route.query.request, load);
onMounted(async () => {
  await load();
  try {
    projects.value = ((await callApi('expense_claim_entry.list_claim_projects', { request_type: '出差申请' }, { method: 'GET' })) || []).map((row) => row.name || row);
  } catch {
    projects.value = [];
  }
});
</script>

<template>
  <div class="xp">
    <div class="ph">
      <div>
        <h3>出差申请</h3>
        <div class="muted">只批该不该去，不设金额；报销、付款关联它即可。审批路线：直属主管 → 副总经理。</div>
      </div>
    </div>
    <div class="tabs" role="tablist">
      <button role="tab" :aria-selected="tab === 'list'" @click="tab = 'list'">我的出差申请<span class="c">{{ rows.length }}</span></button>
      <button role="tab" :aria-selected="tab === 'new'" @click="openNew">新建出差申请</button>
    </div>
    <div v-if="banner.ok" class="banner ok">{{ banner.ok }}</div>
    <div v-if="banner.err" class="banner err" role="alert">{{ banner.err }}</div>

    <template v-if="tab === 'new'">
      <div class="panel">
        <div class="pt">{{ editingName ? `编辑草稿 ${editingName}` : '出差信息' }}</div>
        <div class="form">
          <div class="f"><label>主题<b>*</b></label><input v-model="form.subject" placeholder="如：上海客户拜访" /></div>
          <div class="f"><label>出差地点<b>*</b></label><input v-model="form.travel_destination" /></div>
          <div class="f"><label>出发日期<b>*</b></label><input v-model="form.travel_start_date" type="date" /></div>
          <div class="f"><label>返回日期<b>*</b></label><input v-model="form.travel_end_date" type="date" /></div>
          <div class="f"><label>天数</label><input :value="days ? days + ' 天' : ''" readonly /><div class="h">按出发、返回日期自动计算</div></div>
          <div class="f">
            <label>所属项目</label>
            <select v-model="form.project"><option value="">非项目</option><option v-for="project in projects" :key="project" :value="project">{{ project }}</option></select>
          </div>
          <div class="f s2"><label>出差事由<b>*</b></label><textarea v-model="form.reason"></textarea></div>
        </div>
      </div>
      <div v-if="blockers.length" class="err" role="alert">{{ blockers.join('；') }}</div>
      <div class="actions">
        <button type="button" class="btn pri" :disabled="busy || blockers.length > 0" @click="save({ submit: true })">提交审批</button>
        <button type="button" class="btn" :disabled="busy" @click="save()">保存草稿</button>
        <button type="button" class="btn" :disabled="busy" @click="tab = 'list'; resetForm()">取消</button>
      </div>
    </template>

    <template v-else>
      <div v-if="selected && !rows.some((row) => row.name === selected.name)" class="panel focus">
        <div class="pt"><span><span class="num">{{ selected.name }}</span> <span :class="pillClass(displayStatus(selected))">{{ displayStatus(selected) }}</span> <span class="muted">{{ selected.subject }}</span></span></div>
        <div class="kv">
          <div><span>出差人</span>{{ selected.employee_name }}</div>
          <div><span>地点</span>{{ selected.travel_destination }}</div>
          <div><span>日期</span>{{ selected.travel_start_date }} ~ {{ selected.travel_end_date }}（{{ selected.travel_days }} 天）</div>
          <div><span>所属项目</span>{{ selected.project || '非项目' }}</div>
        </div>
        <h4>出差事由</h4><div style="white-space:pre-line">{{ selected.reason }}</div>
        <h4>审批进度</h4><div class="steps"><span v-for="step in stepChips(selected)" :key="step.key" :class="step.state">{{ step.label }}</span></div>
        <div class="actions">
          <button v-if="selected.can_approve" type="button" class="btn pri" :disabled="busy" @click="act('approve')">同意</button>
          <button v-if="selected.can_reject" type="button" class="btn" :disabled="busy" @click="act('reject')">驳回</button>
        </div>
      </div>

      <div class="panel flush">
        <div class="tbl">
          <table>
            <thead><tr><th>单号 / 主题</th><th>地点</th><th>日期</th><th>状态</th><th>操作</th></tr></thead>
            <tbody>
              <tr v-for="row in rows" :key="row.name" class="row-sel" :class="{ on: selected?.name === row.name }" @click="select(row)">
                <td><div class="num" style="font-weight:600">{{ row.name }}</div><div class="muted">{{ row.subject }}</div></td>
                <td>{{ row.travel_destination }}</td>
                <td class="num">{{ row.travel_start_date }} ~ {{ row.travel_end_date }}<div class="muted">{{ row.travel_days }} 天</div></td>
                <td><span :class="pillClass(displayStatus(row))">{{ displayStatus(row) }}</span></td>
                <td @click.stop>
                  <template v-if="row.workflow_status === '已完成'">
                    <button type="button" class="btn sm" @click="push(row, 'claim')">下推报销</button>
                    <button type="button" class="btn sm" style="margin-left:4px" @click="push(row, 'payment')">下推付款</button>
                  </template>
                  <button v-else-if="row.workflow_status === '草稿'" type="button" class="btn sm" @click="openDraft(row)">继续编辑</button>
                  <button v-else-if="row.can_withdraw" type="button" class="btn sm" @click="withdraw(row)">撤回</button>
                </td>
              </tr>
              <tr v-if="!loading && !rows.length"><td colspan="5" class="empty">还没有出差申请，点"新建出差申请"</td></tr>
              <tr v-if="loading"><td colspan="5" class="empty">正在加载…</td></tr>
            </tbody>
          </table>
        </div>
      </div>

      <div v-if="selected && rows.some((row) => row.name === selected.name)" class="panel">
        <div class="pt"><span><span class="num">{{ selected.name }}</span> <span class="muted">{{ selected.subject }}</span></span></div>
        <div class="kv">
          <div><span>地点</span>{{ selected.travel_destination }}</div>
          <div><span>日期</span>{{ selected.travel_start_date }} ~ {{ selected.travel_end_date }}（{{ selected.travel_days }} 天）</div>
          <div><span>所属项目</span>{{ selected.project || '非项目' }}</div>
        </div>
        <h4>出差事由</h4><div style="white-space:pre-line">{{ selected.reason }}</div>
        <h4>审批进度</h4><div class="steps"><span v-for="step in stepChips(selected)" :key="step.key" :class="step.state">{{ step.label }}</span></div>
        <div class="actions">
          <button v-if="selected.can_approve" type="button" class="btn pri" :disabled="busy" @click="act('approve')">同意</button>
          <button v-if="selected.can_reject" type="button" class="btn" :disabled="busy" @click="act('reject')">驳回</button>
        </div>
      </div>
    </template>
  </div>
</template>
