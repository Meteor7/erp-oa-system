<script setup>
// 工时填报：个人工作表。上方是人员与上限卡片，下方是项目分配（± 0.5 天微调、可直接输入）。
// 行数据由页面持有：这里不直接改 props，所有改动通过事件交给页面（change 带新数组，remove 带行号）。
import { computed, nextTick, ref } from 'vue';
import { Spinner } from 'frappe-ui';
import RdIcon from '../rd/RdIcon.vue';
import {
  DAY_STEP, HOURS_PER_DAY, averageFill, canStepDown, defaultNewDays, deriveStatus, fmtDays, isValidDaysText,
  findProject, pickerOptions, projectCode, projectName, projectOwner, round2, rowFromProject, rowHours, statusMeta, stepDays,
  sumDays, sumHours,
} from '../../lib/timesheetEntryView.js';

const props = defineProps({
  rows: { type: Array, default: () => [] },
  person: { type: Object, default: () => ({ employee: '', name: '', department: '' }) },
  dayLimit: { type: Number, default: 0 },
  hourLimit: { type: Number, default: 0 },
  capLine: { type: String, default: '' },
  editable: { type: Boolean, default: false },
  readOnlyNote: { type: String, default: '' },
  legacy: { type: Boolean, default: false },
  weekdayFallback: { type: Boolean, default: false },
  projects: { type: Array, default: () => [] },
  recentIds: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  canRemind: { type: Boolean, default: false },
  reminding: { type: Boolean, default: false },
});
const emit = defineEmits(['change', 'remove', 'copy', 'import', 'remind']);

const used = computed(() => sumDays(props.rows));
const hours = computed(() => sumHours(props.rows));
const left = computed(() => round2(props.dayLimit - used.value));
const over = computed(() => used.value > props.dayLimit + 1e-6);
const status = computed(() => deriveStatus(used.value, props.dayLimit));
const meta = computed(() => statusMeta(status.value));
const fillWidth = computed(() => `${Math.min(100, (used.value / Math.max(props.dayLimit, used.value, 0.01)) * 100)}%`);
const average = computed(() => averageFill(props.rows, props.dayLimit));
const canRemindNow = computed(() => props.canRemind && (status.value === 'none' || status.value === 'part') && !props.editable);

const addOpen = ref(false);
const addQuery = ref('');
const searchInput = ref(null);
const picker = computed(() => pickerOptions(props.projects, {
  usedIds: props.rows.map((row) => row.project),
  query: addQuery.value,
  recentIds: props.recentIds,
  limit: 8,
}));
const available = computed(() => pickerOptions(props.projects, { usedIds: props.rows.map((row) => row.project), limit: 0 }).total);

function ownerOf(row) {
  return projectOwner(findProject(props.projects, row.project));
}

function patchRow(index, patch) {
  emit('change', props.rows.map((row, i) => (i === index ? { ...row, ...patch } : row)));
}

function setDays(index, text) {
  patchRow(index, { occurrence_days: text, hours: rowHours({ occurrence_days: text }) });
}

function step(index, delta) {
  const next = stepDays(props.rows[index].occurrence_days, delta);
  patchRow(index, { occurrence_days: next, hours: rowHours({ occurrence_days: next }) });
}

function addProject(project) {
  const days = defaultNewDays(left.value);
  emit('change', [...props.rows, rowFromProject(project, props.person.employee, days)]);
  addOpen.value = false;
  addQuery.value = '';
}

async function togglePicker() {
  addOpen.value = !addOpen.value;
  if (addOpen.value) {
    await nextTick();
    searchInput.value?.focus();
  } else {
    addQuery.value = '';
  }
}

function fillEvenly() {
  if (average.value.added > 0) emit('change', average.value.rows);
}
</script>

<template>
  <section>
    <div v-if="readOnlyNote" class="note info">
      <RdIcon name="lock" /><span class="grow">{{ readOnlyNote }}</span>
      <button v-if="canRemindNow" type="button" class="btn sm" :disabled="reminding" @click="emit('remind', person.employee)"><RdIcon name="bell" />催办</button>
    </div>
    <div v-if="legacy" class="note warn"><RdIcon name="alert" /><span class="grow">历史按日记录不能在月度视图中直接修改</span></div>
    <div v-if="weekdayFallback" class="note warn"><RdIcon name="info" /><span class="grow">未配置假日表，当前按周一至周五计算</span></div>

    <div class="card">
      <div class="bd">
        <div class="row between" style="align-items: flex-start">
          <div style="min-width: 0">
            <div style="font-size: 18px; font-weight: 700">
              {{ person.name || person.employee }}
              <span class="muted" style="font-weight: 400">{{ person.employee }}<template v-if="person.department"> · {{ person.department }}</template></span>
              <span class="tag" :class="meta.tone">{{ meta.label }}</span>
            </div>
            <div class="muted">{{ capLine }}</div>
          </div>
          <div class="row" style="gap: 24px; flex-wrap: nowrap">
            <div>
              <div class="muted">已分配</div>
              <div class="num" :style="{ fontSize: '26px', fontWeight: 700, color: over ? 'var(--rd-bad)' : '' }">{{ fmtDays(used, 1) }}<small class="muted"> 天</small></div>
            </div>
            <div>
              <div class="muted">{{ over ? '超出' : '剩余' }}</div>
              <div class="num" :style="{ fontSize: '26px', fontWeight: 700, color: over ? 'var(--rd-bad)' : left < 0.01 ? 'var(--rd-ok)' : '' }">{{ fmtDays(Math.abs(left), 1) }}<small class="muted"> 天</small></div>
            </div>
            <div>
              <div class="muted">工时</div>
              <div class="num" style="font-size: 26px; font-weight: 700">{{ fmtDays(hours, 0) }}<small class="muted"> h</small></div>
            </div>
          </div>
        </div>
        <div class="meter big" style="margin-top: 14px"><i :style="{ width: fillWidth, background: over ? 'var(--rd-bad)' : 'var(--rd-blue)' }"></i></div>
      </div>
    </div>

    <div v-if="over" class="note bad"><RdIcon name="alert" /><span class="grow">超出本月上限 {{ fmtDays(used - dayLimit, 1) }} 天（{{ fmtDays((used - dayLimit) * HOURS_PER_DAY, 0) }} 小时），请调整后再保存。</span></div>

    <div class="card">
      <div class="hd">
        <b>项目分配</b>
        <span v-if="editable" class="row" style="gap: 2px">
          <button type="button" class="btn quiet sm" @click="emit('copy')"><RdIcon name="copy" />复制上月</button>
          <button type="button" class="btn quiet sm" :disabled="average.added <= 0" @click="fillEvenly">把剩余平均分给现有项目</button>
          <button type="button" class="btn quiet sm" :disabled="!rows.length" @click="emit('change', [])">清空</button>
        </span>
      </div>

      <div v-if="loading" style="display: flex; justify-content: center; padding: 36px"><Spinner class="h-6 w-6" /></div>
      <template v-else>
        <div v-for="(row, index) in rows" :key="row.key || row.monthly_entry_id || index" class="line">
          <div style="min-width: 0">
            <div style="font-weight: 500">{{ row.project_name || row.project }}</div>
            <div class="muted">{{ row.project_code }}<template v-if="ownerOf(row)"> · {{ ownerOf(row) }}</template></div>
          </div>
          <div class="step" :style="editable && !isValidDaysText(row.occurrence_days) ? { borderColor: 'var(--rd-bad)' } : null">
            <button type="button" :disabled="!editable || !canStepDown(row.occurrence_days)" :aria-label="`减 ${DAY_STEP} 天`" @click="step(index, -DAY_STEP)">−</button>
            <input :value="row.occurrence_days" inputmode="decimal" :disabled="!editable" aria-label="发生天数" @input="setDays(index, $event.target.value)" />
            <button type="button" :disabled="!editable" :aria-label="`加 ${DAY_STEP} 天`" @click="step(index, DAY_STEP)">＋</button>
          </div>
          <div class="num sub" style="text-align: right">{{ fmtDays(rowHours(row), 0) }} h</div>
          <input v-if="editable" class="field" placeholder="备注" :value="row.remark" aria-label="备注" @input="patchRow(index, { remark: $event.target.value })" />
          <span v-else class="sub" style="min-width: 0">{{ row.remark || '-' }}</span>
          <button v-if="editable" type="button" class="btn quiet sm bad" aria-label="删除" @click="emit('remove', index)"><RdIcon name="trash" /></button>
          <span v-else></span>
        </div>
        <div v-if="!rows.length" class="muted" style="padding: 30px; text-align: center">{{ editable ? '本月还没有工时记录。从下面选一个项目开始，或批量导入。' : '本月暂无工时记录' }}</div>
      </template>

      <div v-if="editable" class="addp">
        <div v-if="addOpen" style="margin-bottom: 10px">
          <label class="input"><RdIcon name="search" /><input ref="searchInput" v-model="addQuery" :placeholder="`搜索项目名称、编号或负责人（共 ${available} 个进行中项目可选）`" aria-label="搜索项目" @keydown.esc="togglePicker" /></label>
          <div class="plist">
            <button v-for="entry in picker.items" :key="entry.project.name" type="button" class="pitem" @click="addProject(entry.project)">
              <span>
                <b style="font-weight: 500">{{ projectName(entry.project) }}</b>
                <span class="muted"> {{ projectCode(entry.project) }}<template v-if="projectOwner(entry.project)"> · {{ projectOwner(entry.project) }}</template></span>
              </span>
              <span v-if="entry.recent" class="tag">上月用过</span>
            </button>
            <div v-if="!picker.items.length" class="muted" style="padding: 12px">{{ projects.length ? '没有匹配的项目' : '无匹配项目，请先在项目管理中新增' }}</div>
          </div>
          <div v-if="picker.total > picker.items.length" class="muted" style="margin-top: 6px">还有 {{ picker.total - picker.items.length }} 个，输入关键字缩小范围</div>
        </div>
        <div class="row between">
          <button type="button" class="btn sm" @click="togglePicker"><RdIcon :name="addOpen ? 'x' : 'plus'" />{{ addOpen ? '收起' : '添加项目' }}</button>
          <button type="button" class="btn quiet sm" @click="emit('import')"><RdIcon name="upload" />批量导入…</button>
        </div>
      </div>
    </div>
  </section>
</template>
