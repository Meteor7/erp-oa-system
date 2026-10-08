<script setup>
// 工时填报进度看板：一张汇总卡（已填满 N / M + 截止）+ 左侧部门列表（点击筛选）+ 右侧「需要跟进的人」。
// 数据全部来自 get_fill_progress，页面负责请求；这里只展示，并把动作用事件交出去。
// remind 事件的载荷始终是员工编号数组（勾选的人 / 单个人 / 当前范围内全部未填的人）。
import { computed, ref, watch } from 'vue';
import { Spinner } from 'frappe-ui';
import RdIcon from '../rd/RdIcon.vue';
import '../../styles/rdTimesheet.css';
import {
  REMIND_CLOSED_TEXT, barColor, boardKindLabel, daysLeft, deadlineLabel, departmentBars, fmtDays, followUpCounts, followUpRows,
  gapText, gapTone, lastRemindedText, namesText, needsRemind, progressPercent, remindClosed, statusMeta, summarizeProgress,
} from '../../lib/timesheetEntryView.js';

const props = defineProps({
  progress: { type: Object, default: null },
  loading: { type: Boolean, default: false },
  error: { type: String, default: '' },
  reminding: { type: Boolean, default: false },
});
const emit = defineEmits(['open', 'remind', 'export-list', 'retry']);

const kind = computed(() => props.progress?.kind || 'self');
const employees = computed(() => props.progress?.employees || []);
const canRemind = computed(() => Boolean(props.progress?.can_remind));
const summary = computed(() => summarizeProgress(employees.value, props.progress?.summary));
const byStatus = (status) => employees.value.filter((item) => item.status === status);
const showDepartment = computed(() => kind.value === 'all');
const left = computed(() => daysLeft(props.progress?.deadline));
const closed = computed(() => remindClosed(props.progress?.deadline));
const remindOpen = computed(() => canRemind.value && !closed.value);
const complete = computed(() => summary.value.total > 0 && summary.value.full >= summary.value.total);

const deadlineNote = computed(() => {
  if (closed.value) return canRemind.value ? '已截止，不再催办' : '已截止';
  const rest = deadlineLabel(left.value);
  return rest ? `进行中，${rest}` : '进行中';
});

// 三块统计：有人才上色，0 保持灰色
const stats = computed(() => [
  { key: 'none', label: '未填', tone: 'bad', count: summary.value.none, names: namesText(byStatus('none')) },
  { key: 'part', label: '未填满', tone: 'warn', count: summary.value.part, names: namesText(byStatus('part')) },
  { key: 'over', label: '超上限', tone: 'bad', count: summary.value.over, names: namesText(byStatus('over')) },
]);

// ---- 部门筛选 + 状态筛选 ----
const departments = computed(() => departmentBars(employees.value));
const dept = ref('all');
const statusFilter = ref('all');
const activeDept = computed(() => (dept.value !== 'all' && departments.value.some((item) => item.department === dept.value) ? dept.value : 'all'));
const counts = computed(() => followUpCounts(employees.value, activeDept.value));
const chips = computed(() => [
  { key: 'all', label: '全部', count: counts.value.all },
  { key: 'none', label: '未填', count: counts.value.none },
  { key: 'part', label: '未填满', count: counts.value.part },
  { key: 'over', label: '超上限', count: counts.value.over },
]);
const rows = computed(() => followUpRows(employees.value, { department: activeDept.value, status: statusFilter.value }));
const scopeLabel = computed(() => (activeDept.value === 'all' ? '全部人员' : activeDept.value));

// ---- 勾选与催办 ----
const picked = ref([]);
const remindable = computed(() => rows.value.filter((item) => needsRemind(item.status)));
const pickedRows = computed(() => remindable.value.filter((item) => picked.value.includes(item.employee)));
const allPicked = computed(() => remindable.value.length > 0 && pickedRows.value.length === remindable.value.length);
const somePicked = computed(() => pickedRows.value.length > 0 && !allPicked.value);
// 当前部门范围内所有「未填 / 未填满」的人，不受状态筛选影响
const scopeTodo = computed(() => followUpRows(employees.value, { department: activeDept.value }).filter((item) => needsRemind(item.status)));

function togglePick(id, checked) {
  picked.value = checked ? [...new Set([...picked.value, id])] : picked.value.filter((item) => item !== id);
}

function toggleAll(checked) {
  const ids = remindable.value.map((item) => item.employee);
  picked.value = checked ? [...new Set([...picked.value, ...ids])] : picked.value.filter((id) => !ids.includes(id));
}

// 催办完成（reminding 回到 false）后清掉勾选
watch(() => props.reminding, (now, before) => {
  if (before && !now) picked.value = [];
});
watch(() => props.progress, () => {
  const alive = new Set(employees.value.map((item) => item.employee));
  picked.value = picked.value.filter((id) => alive.has(id));
});

const emptyText = computed(() => {
  if (!employees.value.length) return '没有可显示的人员';
  if (counts.value.all === 0) return activeDept.value === 'all' ? '本月所有人都已填满，没有需要跟进的人。' : `${activeDept.value} 没有需要跟进的人。`;
  return '没有符合筛选条件的人。';
});
</script>

<template>
  <div v-if="loading && !progress" style="display: flex; justify-content: center; padding: 48px"><Spinner class="h-6 w-6" /></div>
  <div v-else-if="error && !progress" class="note bad">
    <RdIcon name="alert" /><span class="grow">{{ error }}</span>
    <button type="button" class="btn sm" @click="emit('retry')"><RdIcon name="refresh" />重试</button>
  </div>
  <div v-else-if="progress">
    <div class="card ts-summary">
      <div>
        <div class="muted">已填满 · {{ boardKindLabel(kind) }}</div>
        <div class="ts-big"><b class="num">{{ summary.full }} / {{ summary.total }}</b><span>人 · {{ summary.rate }}%</span></div>
        <div class="ts-track lg" role="img" :aria-label="`${summary.full} / ${summary.total} 人已填满`"><i :style="{ width: Math.min(100, Math.max(0, summary.rate)) + '%' }"></i></div>
        <div class="ts-deadline">
          <RdIcon name="lock" />
          <span>截止 {{ progress.deadline }}</span>
          <span>· {{ deadlineNote }}</span>
          <span v-if="complete">· 全部已填满</span>
        </div>
      </div>
      <div class="ts-stats">
        <div v-for="item in stats" :key="item.key" class="ts-stat">
          <div class="n" :class="item.count > 0 ? item.tone : ''">{{ item.count }}</div>
          <div class="t">{{ item.label }}<template v-if="item.count > 0"> · {{ item.names }}</template></div>
        </div>
      </div>
    </div>

    <div class="ts-cols" :class="{ solo: !showDepartment }">
      <div v-if="showDepartment" class="card" style="overflow: hidden">
        <div class="hd"><b>部门</b><span class="muted">按部门筛选名单</span></div>
        <button type="button" class="ts-dept" :aria-pressed="activeDept === 'all'" @click="dept = 'all'">
          <b>全部</b>
          <span class="cnt"><b>{{ summary.full }}</b> / {{ summary.total }}</span>
          <span class="ts-track"><i :style="{ width: Math.min(100, summary.rate) + '%' }"></i></span>
        </button>
        <button v-for="item in departments" :key="item.department" type="button" class="ts-dept" :aria-pressed="activeDept === item.department" @click="dept = item.department">
          <span>{{ item.department }}</span>
          <span class="cnt">{{ item.full }} / {{ item.total }}</span>
          <span class="ts-track"><i :style="{ width: item.percent + '%' }"></i></span>
        </button>
      </div>

      <div class="card" style="overflow: hidden">
        <div class="ts-follow-hd">
          <b>需要跟进的人</b>
          <div class="chips">
            <button v-for="chip in chips" :key="chip.key" type="button" class="chip" :aria-pressed="statusFilter === chip.key" @click="statusFilter = chip.key">{{ chip.label }}<small>{{ chip.count }}</small></button>
          </div>
          <div class="acts">
            <button type="button" class="btn sm" :disabled="!rows.length" @click="emit('export-list', rows)"><RdIcon name="download" />导出名单</button>
            <template v-if="remindOpen">
              <button type="button" class="btn sm pri" :disabled="!pickedRows.length || reminding" @click="emit('remind', pickedRows.map((item) => item.employee))"><RdIcon name="bell" />催办所选（{{ pickedRows.length }}）</button>
              <button type="button" class="btn sm" :disabled="!scopeTodo.length || reminding" :title="`向「${scopeLabel}」里所有未填、未填满的人发送催办`" @click="emit('remind', scopeTodo.map((item) => item.employee))">催办全部未填（{{ scopeTodo.length }}）</button>
            </template>
            <button v-else-if="canRemind" type="button" class="btn sm" disabled :title="REMIND_CLOSED_TEXT"><RdIcon name="bell" />批量催办</button>
          </div>
        </div>
        <div class="tbl ts-scroll">
          <table class="ts-table" aria-label="需要跟进的人">
            <thead>
              <tr>
                <th v-if="remindOpen" class="pick"><input type="checkbox" aria-label="全选当前列表中可催办的人" :checked="allPicked" :indeterminate="somePicked" :disabled="!remindable.length" @change="toggleAll($event.target.checked)" /></th>
                <th>姓名</th>
                <th v-if="showDepartment">部门</th>
                <th class="r">已填 / 上限（天）</th>
                <th>进度</th>
                <th class="r">还差</th>
                <th>状态</th>
                <th v-if="remindOpen" class="r">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in rows" :key="item.employee">
                <td v-if="remindOpen" class="pick">
                  <input v-if="needsRemind(item.status)" type="checkbox" :aria-label="`选择${item.employee_name || item.employee}`" :checked="picked.includes(item.employee)" @change="togglePick(item.employee, $event.target.checked)" />
                </td>
                <td><button type="button" class="btn quiet sm" style="font-weight: 600" @click="emit('open', item.employee)">{{ item.employee_name || item.employee }}</button></td>
                <td v-if="showDepartment" class="sub">{{ item.department || '-' }}</td>
                <td class="r num">{{ fmtDays(item.used_days, 1) }} / {{ fmtDays(item.limit_days, 1) }}</td>
                <td><div class="ts-track"><i :style="{ width: progressPercent(item.used_days, item.limit_days) + '%', background: barColor(item.status) }"></i></div></td>
                <td class="r"><span class="ts-gap" :class="gapTone(item)">{{ gapText(item) }}</span></td>
                <td><span v-if="item.status === 'none' || item.status === 'over'" class="tag" :class="statusMeta(item.status).tone">{{ statusMeta(item.status).label }}</span></td>
                <td v-if="remindOpen" class="r nw">
                  <template v-if="needsRemind(item.status)">
                    <span v-if="item.last_reminded" class="muted">{{ lastRemindedText(item.last_reminded) }} 已催办 </span>
                    <button type="button" class="btn sm quiet" :disabled="reminding" @click="emit('remind', [item.employee])">催办</button>
                  </template>
                </td>
              </tr>
              <tr v-if="!rows.length">
                <td :colspan="5 + (showDepartment ? 1 : 0) + (remindOpen ? 2 : 0)" class="muted" style="text-align: center; padding: 28px">{{ emptyText }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="ts-foot">共 {{ rows.length }} 人 · 还差天数最多的排在前面<template v-if="closed"> · {{ REMIND_CLOSED_TEXT }}</template></div>
      </div>
    </div>
  </div>
</template>
