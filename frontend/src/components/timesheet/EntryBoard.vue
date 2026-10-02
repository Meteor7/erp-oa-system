<script setup>
// 工时填报进度看板：截止倒计时、4 张指标卡、各部门完成情况、需要跟进的人（单人催办 / 一键催办 / 导出名单）。
// 数据全部来自 get_fill_progress，页面负责请求；这里只展示，并把动作用事件交出去。
import { computed } from 'vue';
import { Spinner } from 'frappe-ui';
import RdIcon from '../rd/RdIcon.vue';
import RdKpi from '../rd/RdKpi.vue';
import {
  boardKindLabel, daysLeft, deadlineLabel, deadlineTone, fmtDays, followUpList, groupByDepartment, lastRemindedText,
  namesText, progressPercent, statusFill, statusMeta, summarizeProgress,
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
const todo = computed(() => followUpList(employees.value));
const departments = computed(() => groupByDepartment(employees.value));
const complete = computed(() => summary.value.total > 0 && summary.value.full >= summary.value.total);
const left = computed(() => daysLeft(props.progress?.deadline));
const monthNo = computed(() => Number(String(props.progress?.period || '').slice(5, 7)) || '');
const showDepartment = computed(() => kind.value === 'all');
const fills = [
  { key: 'full', label: '已填满' },
  { key: 'part', label: '未填满' },
  { key: 'none', label: '未填' },
  { key: 'over', label: '超上限' },
];

function slice(group, key) {
  return group.total ? (group[key] / group.total) * 100 : 0;
}
</script>

<template>
  <div v-if="loading && !progress" style="display: flex; justify-content: center; padding: 48px"><Spinner class="h-6 w-6" /></div>
  <div v-else-if="error && !progress" class="note bad">
    <RdIcon name="alert" /><span class="grow">{{ error }}</span>
    <button type="button" class="btn sm" @click="emit('retry')"><RdIcon name="refresh" />重试</button>
  </div>
  <div v-else-if="progress">
    <div class="note" :class="deadlineTone(left, complete)">
      <RdIcon name="clock" />
      <span class="grow">
        <b>{{ monthNo }} 月工时填报截止：{{ progress.deadline }}</b>，{{ deadlineLabel(left) }}。填报范围：{{ boardKindLabel(kind) }}，共 {{ summary.total }} 人。
      </span>
    </div>

    <div class="kpis">
      <RdKpi label="填报完成率" :value="`${summary.rate}%`" :sub="`${summary.full} / ${summary.total} 人已填满`" :tone="summary.rate < 60 ? 'warn' : ''" />
      <RdKpi label="未填" :value="summary.none" :sub="namesText(byStatus('none'))" :tone="summary.none ? 'bad' : ''" />
      <RdKpi label="未填满" :value="summary.part" :sub="namesText(byStatus('part'))" :tone="summary.part ? 'warn' : ''" />
      <RdKpi label="超上限" :value="summary.over" :sub="namesText(byStatus('over'))" :tone="summary.over ? 'bad' : ''" />
    </div>

    <div class="grid12">
      <div class="card">
        <div class="hd"><b>{{ showDepartment ? '各部门完成情况' : '部门成员完成情况' }}</b><span class="muted">按人数占比</span></div>
        <div class="bd">
          <template v-if="showDepartment">
            <div v-for="group in departments" :key="group.department" style="margin: 12px 0">
              <div class="row between" style="margin-bottom: 5px">
                <span><b style="font-weight: 600">{{ group.department }}</b> <span class="muted">{{ group.total }} 人</span></span>
                <span class="num"><b>{{ group.rate }}%</b> <span class="muted">已填满</span></span>
              </div>
              <div class="meter big">
                <template v-for="item in fills" :key="item.key">
                  <i v-if="group[item.key]" :style="{ width: slice(group, item.key) + '%', background: statusFill(item.key) }" :title="`${group.department} · ${item.label} ${group[item.key]} 人`"></i>
                </template>
              </div>
            </div>
          </template>
          <div v-else class="meter big">
            <template v-for="item in fills" :key="item.key">
              <i v-if="summary[item.key]" :style="{ width: (summary.total ? (summary[item.key] / summary.total) * 100 : 0) + '%', background: statusFill(item.key) }" :title="`${item.label} ${summary[item.key]} 人`"></i>
            </template>
          </div>
          <div class="legend" style="margin-top: 12px">
            <span v-for="item in fills" :key="item.key"><i class="dot" :style="{ background: statusFill(item.key) }"></i>{{ item.label }}</span>
          </div>
        </div>
      </div>

      <div class="card">
        <div class="hd">
          <b>{{ todo.length ? '需要跟进的人' : '全部已填满' }}</b>
          <span class="row" style="gap: 6px">
            <button type="button" class="btn sm" :disabled="!todo.length" @click="emit('export-list', todo)"><RdIcon name="download" />导出名单</button>
            <button v-if="canRemind" type="button" class="btn sm pri" :disabled="!todo.length || reminding" @click="emit('remind', todo.map((item) => item.employee))"><RdIcon name="bell" />一键催办 {{ todo.length }} 人</button>
          </span>
        </div>
        <div class="tbl">
          <table>
            <thead>
              <tr>
                <th>姓名</th>
                <th v-if="showDepartment">部门</th>
                <th>已填 / 上限（天）</th>
                <th>填报进度</th>
                <th>状态</th>
                <th v-if="canRemind" class="r">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in todo" :key="item.employee">
                <td><button type="button" class="btn quiet sm" style="font-weight: 600" @click="emit('open', item.employee)">{{ item.employee_name || item.employee }}</button></td>
                <td v-if="showDepartment" class="sub">{{ item.department || '-' }}</td>
                <td class="num">{{ fmtDays(item.used_days, 1) }} / {{ fmtDays(item.limit_days, 1) }}</td>
                <td style="min-width: 120px"><div class="meter"><i :style="{ width: progressPercent(item.used_days, item.limit_days) + '%', background: statusFill(item.status) }"></i></div></td>
                <td><span class="tag" :class="statusMeta(item.status).tone">{{ statusMeta(item.status).label }}</span></td>
                <td v-if="canRemind" class="r nw">
                  <span v-if="item.last_reminded" class="muted">{{ lastRemindedText(item.last_reminded) }} 已催办 </span>
                  <button type="button" class="btn sm" :disabled="reminding" @click="emit('remind', [item.employee])"><RdIcon name="bell" />催办</button>
                </td>
              </tr>
              <tr v-if="!todo.length">
                <td :colspan="3 + (showDepartment ? 1 : 0) + (canRemind ? 1 : 0) + 1" class="muted" style="text-align: center; padding: 28px">{{ summary.over ? '没有人需要催办，但有人超上限' : '本月所有人都已填满，没有需要催办的人。' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</template>
