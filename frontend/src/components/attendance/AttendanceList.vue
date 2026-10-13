<script setup>
// 申请列表：左右分栏。左边是一张卡片——范围页签（待我审批 / 我的 / 我审批过的 / 全部）、一行筛选（类型、时间、等了超过 3 天、搜索）和申请行；
// 点一行右边直接看清楚并处理（同意 / 驳回），"完整页面"才进详情页；只有"待我审批"的行可以勾选批量同意。
// 页面标题和主按钮跟着类型走。
import { computed, ref, watch } from 'vue';
import {
  SCOPES, awayToday, byWait, canQuickApprove, departmentLabel, kindOf, listTitle, newButtonLabel, personShort, scopeTabs, typeCounts,
} from '../../lib/attendanceView.js';
import { TIME_FILTERS, applyFilters, filtersActive, isSlow, lengthText, pickSelected, statusInfo, whenText } from '../../lib/attendanceFlow.js';
import { rowKind } from '../../lib/attendanceCharts.js';
import { todayText } from '../../lib/dashboardLanding.js';
import { STUCK_AFTER_DAYS } from '../../lib/waiting.js';
import AttendanceDetail from './AttendanceDetail.vue';

const props = defineProps({
  page: { type: Object, required: true },
  sets: { type: Object, required: true },
  names: { type: Object, default: () => ({}) },
  loaded: { type: Object, required: true },
  now: { type: Number, default: () => Date.now() },
  busy: { type: Boolean, default: false },
  isApprover: { type: Boolean, default: false },
  canViewAll: { type: Boolean, default: false },
  hasEmployee: { type: Boolean, default: false },
});
const emit = defineEmits(['home', 'scope', 'filter', 'new', 'open', 'approve-many', 'today-off', 'changed', 'navigate']);

const TYPE_DOT = { 请假: 'k-personal', 加班: 'k-ot', 调休: 'k-comp', 出差: 'k-trip' };
const picked = ref([]);
const time = ref('all');
const slow = ref(false);
const query = ref('');
const menu = ref(false);
const selectedName = ref('');

const scope = computed(() => props.page.scope);
const filter = computed(() => props.page.filter);
// 看板的「今天不在岗」点进来：「全部」里换成服务端按今天查好的那批人（sets.today，一人一张，和看板的人数一样，
// 不再从最近 100 张里筛），前端再按起止日期筛一遍、按人去重。
const todayOnly = computed(() => Boolean(props.page.today) && scope.value === 'all');
const title = computed(() => listTitle(filter.value));
const tabs = computed(() => scopeTabs({ sets: props.sets, filter: 'all', isApprover: props.isApprover, canViewAll: props.canViewAll, allLoaded: props.loaded.all }));
const base = computed(() => (todayOnly.value ? props.sets.today : props.sets[scope.value]) || []);
const counts = computed(() => typeCounts(base.value));
const typeItems = computed(() => [['all', '全部'], ['请假', '请假'], ['加班', '加班'], ['调休', '调休'], ['出差', '出差']].map(([key, label]) => ({ key, label, count: counts.value[key] ?? 0, on: filter.value === key })));
const ready = computed(() => (todayOnly.value ? props.loaded.today
  : ({ todo: props.loaded.review, mine: props.loaded.mine, done: props.loaded.reviewed, all: props.loaded.all })[scope.value]) ?? false);
const today = computed(() => todayText(new Date(props.now)));
const state = computed(() => ({ type: filter.value, time: time.value, slow: slow.value, query: query.value }));
const rows = computed(() => {
  let list = applyFilters(base.value, state.value, { today: today.value, now: props.now });
  if (todayOnly.value) list = awayToday(list, todayText(new Date(props.now)));
  return scope.value === 'todo' ? byWait(list, props.now) : list;
});
const slowCount = computed(() => base.value.filter((row) => isSlow(row, props.now)).length);
const active = computed(() => filtersActive(state.value) || todayOnly.value);
const current = computed(() => (ready.value ? pickSelected(rows.value, selectedName.value) : null));
const selectable = computed(() => (scope.value === 'todo' ? rows.value.filter(canQuickApprove) : []));
const chosen = computed(() => selectable.value.filter((row) => picked.value.includes(row.name)));
const allChosen = computed(() => selectable.value.length > 0 && chosen.value.length === selectable.value.length);
const timeLabel = computed(() => TIME_FILTERS.find(([key]) => key === time.value)?.[1] || '时间');

watch([scope, filter], () => { picked.value = []; selectedName.value = ''; });
watch(scope, () => { time.value = 'all'; slow.value = false; query.value = ''; menu.value = false; });
// 列表刷新后（批过的、被别人处理掉的）不再存在的单子从已选里去掉。
watch(selectable, (list) => { picked.value = picked.value.filter((name) => list.some((row) => row.name === name)); });

function toggle(row) {
  picked.value = picked.value.includes(row.name) ? picked.value.filter((name) => name !== row.name) : [...picked.value, row.name];
}

function toggleAll() {
  picked.value = allChosen.value ? [] : selectable.value.map((row) => row.name);
}

function approveChosen() {
  const list = chosen.value;
  picked.value = [];
  emit('approve-many', list);
}

function clearFilters() {
  time.value = 'all';
  slow.value = false;
  query.value = '';
  emit('filter', 'all');
  if (todayOnly.value) emit('today-off');
}

function setTime(key) {
  time.value = key;
  menu.value = false;
}

// 方向键在列表里上下移动选中的那一行。
function move(delta) {
  const list = rows.value;
  if (!list.length) return;
  const index = Math.max(0, list.findIndex((row) => row.name === current.value?.name));
  selectedName.value = list[Math.min(list.length - 1, Math.max(0, index + delta))].name;
}

const scopeLabel = computed(() => SCOPES.find((item) => item.key === scope.value)?.label || '');
const subtitle = computed(() => {
  if (todayOnly.value) return '只读：今天正在休假或调休的人（已批准的申请，按今天查，一人一行，和看板“今天不在岗”的人数一样）。';
  return scope.value === 'all' ? '只读：所有人已提交的请假、加班、调休、出差（最近 100 张）。' : '点一行，右边直接看清楚并处理；批量处理勾选后统一同意。';
});
const emptyText = computed(() => (todayOnly.value ? '今天没有人在休假或调休' : active.value ? '没有符合筛选的申请' : '这个范围里没有申请'));
</script>

<template>
  <div class="acx af-page">
    <div class="af-head">
      <div>
        <div class="af-crumb"><button type="button" class="ac-link" @click="emit('home')">考勤中心</button> › {{ title }}</div>
        <h1>{{ title }}</h1>
        <div class="ac-note">{{ subtitle }}</div>
      </div>
      <button v-if="hasEmployee" type="button" class="ac-btn pri" @click="emit('new', filter)">{{ newButtonLabel(filter) }}</button>
    </div>

    <div class="af-split">
      <section class="ac-panel" :aria-label="scopeLabel">
        <div class="af-tabs" role="tablist" aria-label="范围">
          <button v-for="tab in tabs" :key="tab.key" type="button" role="tab" :aria-selected="scope === tab.key" @click="emit('scope', tab.key)">{{ tab.label }}<small v-if="tab.count !== null">{{ tab.count }}</small></button>
        </div>

        <div class="af-fbar">
          <button v-if="todayOnly" type="button" class="af-fbtn on" aria-label="取消「今天不在岗」筛选" title="点一下取消，回到全部申请" @click="emit('today-off')">今天不在岗 ✕</button>
          <div class="af-tseg" role="group" aria-label="类型">
            <button v-for="item in typeItems" :key="item.key" type="button" :aria-pressed="item.on" @click="emit('filter', item.key)"><i v-if="TYPE_DOT[item.key]" :class="TYPE_DOT[item.key]"></i>{{ item.label }}<b>{{ item.count }}</b></button>
          </div>
          <div class="af-menuwrap">
            <button type="button" :class="['af-fbtn', { on: time !== 'all' }]" aria-haspopup="true" :aria-expanded="menu" @click="menu = !menu">{{ time === 'all' ? '时间' : timeLabel }} ▾</button>
            <div v-if="menu" class="af-pop" role="menu" @keydown.esc="menu = false">
              <button v-for="[key, label] in TIME_FILTERS" :key="key" type="button" role="menuitemradio" :aria-checked="time === key" @click="setTime(key)">{{ label }}<span v-if="time === key">✓</span></button>
            </div>
          </div>
          <button v-if="scope === 'todo'" type="button" class="af-fbtn" :aria-pressed="slow" @click="slow = !slow">等了超过 {{ STUCK_AFTER_DAYS }} 天<b>{{ slowCount }}</b></button>
          <label class="af-sbox"><svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="7" cy="7" r="4.5" fill="none" stroke="currentColor" stroke-width="1.5" /><path d="m10.5 10.5 3 3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" /></svg><input v-model="query" type="search" placeholder="搜申请人、单号、事由" aria-label="搜索" /></label>
          <button v-if="active" type="button" class="ac-link" @click="clearFilters">清除筛选</button>
        </div>

        <div class="af-listhd">
          <input v-if="scope === 'todo'" type="checkbox" aria-label="全选" :checked="allChosen" :disabled="!selectable.length" @change="toggleAll" />
          <span>{{ scope === 'todo' ? '等得最久的在前' : '最近的在前' }} · {{ active ? `筛出 ${rows.length} / ${base.length} 张` : `共 ${ready ? rows.length : 0} 张` }}</span>
          <span v-if="scope === 'todo'" class="af-batch">已选 {{ chosen.length }} 张<button type="button" class="ac-btn sm pri" :disabled="!chosen.length || busy" @click="approveChosen">批量同意</button></span>
        </div>

        <div role="listbox" aria-label="申请列表" @keydown.down.prevent="move(1)" @keydown.up.prevent="move(-1)">
          <div v-if="!scope || !ready" class="ac-empty">正在加载…</div>
          <div v-else-if="!rows.length" class="ac-empty">{{ emptyText }}</div>
          <div v-for="row in ready ? rows : []" :key="row.name + String(row.acted_on || '')" :class="['af-row', { on: current && current.name === row.name, nocheck: scope !== 'todo' }]" tabindex="0" role="option" :aria-selected="current && current.name === row.name" @click="selectedName = row.name" @keydown.enter="selectedName = row.name">
            <input v-if="scope === 'todo'" type="checkbox" :aria-label="'选择 ' + row.name" :checked="picked.includes(row.name)" :disabled="!canQuickApprove(row)" :title="canQuickApprove(row) ? '' : '这一步要进详情页处理'" @click.stop @change="toggle(row)" />
            <span :class="['ac-av', rowKind(row)]">{{ personShort(row.employee_name) }}</span>
            <div class="main">
              <div class="l1"><b>{{ scope === 'mine' ? kindOf(row).text : row.employee_name }}</b><template v-if="scope !== 'mine'"><span class="ac-note">{{ departmentLabel(row.department) }}</span><span :class="['ac-tag', rowKind(row)]">{{ kindOf(row).leaveType || kindOf(row).label }}</span></template></div>
              <div class="l2"><span class="when">{{ whenText(row) }}</span><span>{{ lengthText(row) }}</span></div>
              <div class="l3">{{ row.reason || row.subject }}</div>
            </div>
            <div class="side">
              <span v-if="statusInfo(row, scope, now, names).tag" :class="['ac-tag', statusInfo(row, scope, now, names).tag.tone]">{{ statusInfo(row, scope, now, names).tag.text }}</span>
              <span v-if="statusInfo(row, scope, now, names).sub" class="ac-note">{{ statusInfo(row, scope, now, names).sub }}</span>
            </div>
          </div>
        </div>
      </section>

      <AttendanceDetail v-if="current" :key="current.name" variant="panel" class="af-stick" :name="current.name" :hints="scope === 'todo' ? current.hints || [] : []" :origin="{ kind: 'list', scope, filter }" @open="emit('open', current)" @changed="emit('changed')" @navigate="(location) => emit('navigate', location)" />
      <div v-else class="ac-panel ac-empty">{{ ready ? '没有可看的申请' : '正在加载…' }}</div>
    </div>
  </div>
</template>
