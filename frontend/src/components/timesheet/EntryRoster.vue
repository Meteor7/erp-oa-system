<script setup>
// 工时填报：左侧名单（搜索 + 部门 + 全部 / 未填满 / 超上限 + 每人一条细进度条 + 已填 / 上限）。只负责选人，不改数据。
import { computed, ref } from 'vue';
import RdIcon from '../rd/RdIcon.vue';
import '../../styles/rdTimesheet.css';
import { avatarText, barColor, departmentsOf, filterRoster, fmtDaysExact, fmtHours, progressPercent, rosterCounts } from '../../lib/timesheetEntryView.js';

const props = defineProps({
  items: { type: Array, default: () => [] },
  selected: { type: String, default: '' },
  // 'team' 本部门成员；'all' 全公司（可按部门筛选，列表里显示部门）
  kind: { type: String, default: 'team' },
});
const emit = defineEmits(['select']);

const query = ref('');
const filter = ref('all');
const department = ref('all');

const counts = computed(() => rosterCounts(props.items));
const departments = computed(() => (props.kind === 'all' ? departmentsOf(props.items) : []));
const visible = computed(() => filterRoster(props.items, { query: query.value, filter: filter.value, department: department.value }));
const chips = computed(() => [
  { key: 'all', label: '全部', count: counts.value.all },
  { key: 'todo', label: '未填满', count: counts.value.todo },
  { key: 'over', label: '超上限', count: counts.value.over },
]);
const hasProgress = computed(() => props.items.some((item) => item.status));
</script>

<template>
  <aside class="card roster ts-roster">
    <div class="hd">
      <b>{{ kind === 'all' ? '研发人员' : '本部门成员' }}</b>
      <span v-if="hasProgress" class="muted">{{ counts.full }} / {{ counts.all }} 人已填满</span>
      <span v-else class="muted">{{ counts.all }} 人</span>
    </div>
    <div class="bd">
      <label class="input"><RdIcon name="search" /><input v-model="query" placeholder="搜索姓名或工号" aria-label="搜索研发人员" /></label>
      <select v-if="departments.length > 1" v-model="department" class="field" style="margin-top: 8px" aria-label="按部门筛选">
        <option value="all">全部部门</option>
        <option v-for="name in departments" :key="name" :value="name">{{ name }}</option>
      </select>
      <div v-if="hasProgress" class="chips" style="margin: 10px 0 6px">
        <button v-for="chip in chips" :key="chip.key" type="button" class="chip" :aria-pressed="filter === chip.key" @click="filter = chip.key">{{ chip.label }}<small>{{ chip.count }}</small></button>
      </div>
      <div v-else style="height: 8px"></div>
      <button v-for="item in visible" :key="item.employee" type="button" class="r-item" :aria-current="item.employee === selected" @click="emit('select', item.employee)">
        <span class="av">{{ avatarText(item.name) }}</span>
        <span style="min-width: 0">
          <b style="font-weight: 500">{{ item.name }}</b>
          <span class="muted"> {{ kind === 'all' && item.department ? item.department : item.employee }}</span>
          <div v-if="item.status" class="meter"><i :style="{ width: progressPercent(item.used, item.limit) + '%', background: barColor(item.status) }"></i></div>
        </span>
        <span v-if="item.status" class="num muted" style="text-align: right; font-size: 12px" :title="`约 ${fmtDaysExact(item.usedDays)} / ${fmtDaysExact(item.limitDays)} 天`">{{ fmtHours(item.used) }}<br />/ {{ fmtHours(item.limit) }} h</span>
        <span v-else></span>
      </button>
      <div v-if="!visible.length" class="muted" style="padding: 20px; text-align: center">没有符合条件的员工</div>
    </div>
  </aside>
</template>
