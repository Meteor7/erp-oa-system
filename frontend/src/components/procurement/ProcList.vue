<script setup>
// 采购申请列表：待我处理 / 我提交的 / 全部（全局角色）或与我相关（其他人）。
// 搜索、阶段、项目、加急都是在已取回的最近 200 张里筛（后端没有搜索接口）；每页 50 张。
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import {
  LIST_LIMIT, PAGE_SIZE, STAGE_FILTERS, approvalWait, filterRows, listScope, mergeRows, pageCount, pageSlice,
  projectOptions, projectText, statusOf, waitText, whereText,
} from '../../lib/procurementView.js';
import { apiGet, errText } from './procData.js';
import { useProc } from './context.js';

const ctx = useProc();
const route = useRoute();
const data = reactive({ mine: [], pending: [], all: [], loaded: false });
const loading = ref(false);
const loadError = ref('');
const now = ctx.now;
const filters = reactive({ text: '', stage: String(route.query.stage || ''), project: '', urgent: false });
const page = ref(0);

const scope = computed(() => listScope(route.query, ctx.globalAccess ? 'todo' : 'mine'));
const listFor = (view) => apiGet('oa_entry.list_requests', { view, request_type: ctx.requestType, limit: LIST_LIMIT });

async function load({ silent = false } = {}) {
  if (!silent) loading.value = true;
  try {
    const [mine, pending, all] = await Promise.all([listFor('mine'), listFor('pending'), ctx.globalAccess ? listFor('all') : []]);
    Object.assign(data, { mine: mine || [], pending: pending || [], all: all || [], loaded: true });
    loadError.value = '';
  } catch (error) {
    loadError.value = errText(error, '业务单据加载失败');
    if (silent) ctx.flash('', loadError.value);
  } finally {
    loading.value = false;
  }
}

onMounted(() => load());
defineExpose({ reload: load });

const related = computed(() => mergeRows(ctx.requestType, data.mine, data.pending));
const byScope = computed(() => ({
  todo: data.pending,
  mine: data.mine,
  all: ctx.globalAccess ? data.all : related.value,
}));
const scopes = computed(() => [
  { key: 'todo', label: '待我处理', count: data.pending.length },
  { key: 'mine', label: '我提交的', count: data.mine.length },
  { key: 'all', label: ctx.globalAccess ? '全部' : '与我相关', count: byScope.value.all.length },
]);
const scopeLabel = computed(() => scopes.value.find((item) => item.key === scope.value)?.label || '');
const base = computed(() => byScope.value[scope.value] || []);
const rows = computed(() => filterRows(base.value, filters, ctx.projectName));
const pages = computed(() => pageCount(rows.value.length));
const shown = computed(() => pageSlice(rows.value, Math.min(page.value, pages.value - 1)));
const projectChoices = computed(() => projectOptions(base.value, ctx.projectName));
const maybeMore = computed(() => base.value.length >= LIST_LIMIT);
const emptyText = computed(() => {
  if (loading.value) return '正在读取申请和待办，请稍候';
  if (loadError.value) return `业务单据加载失败：${loadError.value}`;
  if (scope.value === 'todo' && !base.value.length) return '没有要你审批的采购申请';
  return '没有符合条件的采购申请';
});

watch(filters, () => { page.value = 0; }, { deep: true });

function open(row) {
  if (row.workflow_status === '草稿' && scope.value === 'mine') ctx.goNew({ draft: row.name });
  else ctx.go({ request: row.name });
}
</script>

<template>
  <div class="pr-list">
    <div class="ph">
      <div>
        <div class="crumb"><button type="button" class="link" @click="ctx.go({})">采购申请</button> › 列表</div>
        <h3>{{ scopeLabel }} · {{ rows.length }} 张</h3>
      </div>
      <div class="head-actions">
        <div class="seg">
          <button v-for="item in scopes" :key="item.key" type="button" :aria-pressed="scope === item.key" @click="ctx.go({ view: 'list', scope: item.key })">{{ item.label }} {{ item.count }}</button>
        </div>
        <button type="button" class="btn pri" @click="ctx.goNew()">＋ 新建采购申请</button>
      </div>
    </div>

    <div class="filter-bar">
      <input v-model="filters.text" type="search" placeholder="搜索单号、主题、申请人、项目或物料名称" aria-label="搜索" />
      <select v-model="filters.stage" class="pr-select" aria-label="阶段">
        <option value="">全部阶段</option>
        <option v-for="stage in STAGE_FILTERS" :key="stage.key" :value="stage.key">{{ stage.label }}</option>
      </select>
      <select v-model="filters.project" class="pr-select" aria-label="项目">
        <option value="">全部项目</option>
        <option v-for="project in projectChoices" :key="project.key" :value="project.key">{{ project.label }}</option>
      </select>
      <button type="button" :class="['chip', { on: filters.urgent }]" :aria-pressed="filters.urgent" @click="filters.urgent = !filters.urgent">加急</button>
    </div>

    <div class="panel flush">
      <div class="tbl">
        <table class="pr-table">
          <thead>
            <tr><th>主题 / 单号</th><th>申请人</th><th>项目 / 归属</th><th class="r">物料</th><th>阶段</th><th>当前在哪（待谁 / 哪张 PO）</th><th class="r">等待</th></tr>
          </thead>
          <tbody>
            <tr v-for="row in shown" :key="row.name" class="row-sel" @click="open(row)">
              <td>
                <button type="button" class="link strong pr-subject" @click.stop="open(row)">{{ row.subject || '（无主题）' }}</button>
                <span v-if="row.urgency === '加急'" class="pill p-red pr-urgent">加急</span>
                <div class="muted num">{{ row.name }}</div>
              </td>
              <td>{{ row.employee_name }}<div class="muted">{{ row.department }}</div></td>
              <td class="ellipsis-cell">{{ projectText(row, ctx.projectName) }}</td>
              <td class="r">{{ (row.business_lines || []).length }} 项</td>
              <td><span :class="['pill', statusOf(row).tone]">{{ statusOf(row).label }}</span></td>
              <td class="ellipsis-cell">{{ whereText(row) }}</td>
              <td :class="['r', { warn: (approvalWait(row, now) || 0) >= 3 }]">{{ approvalWait(row, now) === null ? '—' : waitText(approvalWait(row, now)) }}</td>
            </tr>
            <tr v-if="!shown.length">
              <td colspan="7" class="empty" :role="loadError ? 'alert' : undefined">
                {{ emptyText }}
                <button v-if="loadError" type="button" class="link" @click="load()">重新加载</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="pr-foot">
        <span class="muted">共 {{ rows.length }} 张 · 每页 {{ PAGE_SIZE }} 张<template v-if="maybeMore"> · 只取了最近 {{ LIST_LIMIT }} 张，更早的单据请用单号直接打开</template></span>
        <span class="row-actions">
          <button type="button" class="btn sm" :disabled="page === 0" @click="page -= 1">上一页</button>
          <span class="muted pr-pageno">第 {{ Math.min(page, pages - 1) + 1 }} / {{ pages }} 页</span>
          <button type="button" class="btn sm" :disabled="page >= pages - 1" @click="page += 1">下一页</button>
        </span>
      </div>
    </div>
  </div>
</template>
