<script setup>
// 工时填报：个人工作表。顶部卡片 = 人员 + 保存按钮 + 已分配汇总 + 分段进度条，下面是工具栏和项目分配行（± 0.5 天微调、可直接输入）。
// 行数据由页面持有：这里不直接改 props，所有改动通过事件交给页面（change 带新数组，remove 带行号，save 通知页面保存）。
import { computed, ref } from 'vue';
import { Spinner } from 'frappe-ui';
import RdIcon from '../rd/RdIcon.vue';
import '../../styles/rdTimesheet.css';
import {
  DAY_STEP, HOURS_PER_DAY, averageFill, avatarText, canStepDown, defaultNewDays, deriveStatus, fmtDays, isValidDaysText,
  findProject, pickerOptions, projectCode, projectColor, projectName, projectOwner, remainingMeta, round2, rowFromProject, rowHours,
  sharePercent, stackedSegments, statusMeta, stepDays, sumDays, sumHours,
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
  // 保存按钮在这张卡片的右上角：页面决定能不能点（保存中 / 超上限 / 没有修改时不可点）
  dirty: { type: Boolean, default: false },
  saving: { type: Boolean, default: false },
  saveDisabled: { type: Boolean, default: false },
});
const emit = defineEmits(['change', 'remove', 'copy', 'import', 'remind', 'save']);

const used = computed(() => sumDays(props.rows));
const hours = computed(() => sumHours(props.rows));
const left = computed(() => round2(props.dayLimit - used.value));
const over = computed(() => used.value > props.dayLimit + 1e-6);
const status = computed(() => deriveStatus(used.value, props.dayLimit));
const meta = computed(() => statusMeta(status.value));
const remaining = computed(() => remainingMeta(used.value, props.dayLimit));
const segments = computed(() => stackedSegments(props.rows, props.dayLimit));
const average = computed(() => averageFill(props.rows, props.dayLimit));
const canRemindNow = computed(() => props.canRemind && (status.value === 'none' || status.value === 'part') && !props.editable);
const saveHint = computed(() => {
  if (props.saving) return '正在保存';
  if (over.value) return '超出本月上限，调整后才能保存';
  if (!props.dirty) return '没有需要保存的修改';
  return '';
});

// ---- 项目搜索 / 添加（搜索框常驻；聚焦时下拉出候选，回车添加高亮的那一项） ----
const addQuery = ref('');
const focused = ref(false);
const activeIndex = ref(0);
const searchInput = ref(null);
const usedIds = computed(() => props.rows.map((row) => row.project));
const picker = computed(() => pickerOptions(props.projects, { usedIds: usedIds.value, query: addQuery.value, recentIds: props.recentIds, limit: 8 }));
const available = computed(() => pickerOptions(props.projects, { usedIds: usedIds.value, limit: 0 }).total);
// 上月用过、本月还没加的项目：做成一键添加的小标签
const suggestions = computed(() => pickerOptions(props.projects, { usedIds: usedIds.value, recentIds: props.recentIds, limit: 500 })
  .items.filter((entry) => entry.recent).slice(0, 4).map((entry) => entry.project));

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
  addQuery.value = '';
  activeIndex.value = 0;
}

function onSearchKey(event) {
  const count = picker.value.items.length;
  if (event.key === 'ArrowDown') {
    event.preventDefault();
    focused.value = true;
    activeIndex.value = Math.min(Math.max(count - 1, 0), activeIndex.value + 1);
  } else if (event.key === 'ArrowUp') {
    event.preventDefault();
    activeIndex.value = Math.max(0, activeIndex.value - 1);
  } else if (event.key === 'Enter') {
    event.preventDefault();
    const entry = picker.value.items[activeIndex.value];
    if (entry) addProject(entry.project);
  } else if (event.key === 'Escape') {
    addQuery.value = '';
    focused.value = false;
    searchInput.value?.blur();
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
    <div v-if="over" class="note bad"><RdIcon name="alert" /><span class="grow">超出本月上限 {{ fmtDays(used - dayLimit, 1) }} 天（{{ fmtDays((used - dayLimit) * HOURS_PER_DAY, 0) }} 小时），请调整后再保存。</span></div>

    <div class="card ts-sheet">
      <div class="ts-top">
        <div class="ts-head">
          <span class="av lg" aria-hidden="true">{{ avatarText(person.name || person.employee) }}</span>
          <div style="min-width: 0">
            <div class="ts-name">
              {{ person.name || person.employee }}
              <span class="muted">{{ person.employee }}<template v-if="person.department"> · {{ person.department }}</template></span>
              <span class="tag" :class="meta.tone">{{ meta.label }}</span>
            </div>
            <div class="muted">{{ capLine }}</div>
          </div>
          <div v-if="editable" class="ts-save">
            <span v-if="dirty" class="tag warn">有未保存的修改</span>
            <span v-else class="tag ok">已保存</span>
            <button type="button" class="btn pri" :disabled="saveDisabled" :title="saveHint || undefined" @click="emit('save')">{{ saving ? '保存中…' : '保存' }}</button>
          </div>
        </div>

        <div>
          <div class="ts-total">
            <span class="big" :class="{ bad: over }">{{ fmtDays(used, 1) }}</span>
            <span class="muted">/ {{ fmtDays(dayLimit, 1) }} 天</span>
            <span class="muted" style="margin-left: 6px">{{ fmtDays(hours, 0) }} h</span>
            <span class="left" :class="remaining.tone" style="margin-left: auto">{{ remaining.text }}</span>
            <button v-if="editable && average.added > 0" type="button" class="ts-link" @click="fillEvenly">把剩余平均分给现有项目</button>
          </div>
          <div class="ts-meter" role="img" aria-label="各项目已分配天数占本月上限的比例">
            <i v-for="seg in segments" :key="seg.key" :style="{ width: seg.width + '%', background: seg.color }" :title="`${seg.code} ${seg.name} ${fmtDays(seg.days, 1)} 天`"></i>
          </div>
          <div v-if="segments.length" class="ts-legend">
            <span v-for="seg in segments" :key="seg.key"><i class="ts-dot" :style="{ background: seg.color }"></i>{{ seg.code }} {{ seg.pct }}%</span>
          </div>
        </div>
      </div>

      <div v-if="editable" class="ts-tools">
        <div class="ts-search">
          <label class="input">
            <RdIcon name="plus" />
            <input
              ref="searchInput"
              v-model="addQuery"
              role="combobox"
              aria-autocomplete="list"
              aria-controls="ts-project-list"
              :aria-expanded="focused"
              :aria-activedescendant="focused && picker.items.length ? `ts-project-opt-${activeIndex}` : undefined"
              placeholder="搜索项目名称、编号、负责人，回车添加"
              aria-label="搜索项目"
              @focus="focused = true"
              @blur="focused = false"
              @input="activeIndex = 0"
              @keydown="onSearchKey"
            />
          </label>
          <div v-if="focused" id="ts-project-list" class="ts-pop" role="listbox" aria-label="可添加的项目">
            <div
              v-for="(entry, i) in picker.items"
              :id="`ts-project-opt-${i}`"
              :key="entry.project.name"
              class="pitem"
              role="option"
              :aria-selected="i === activeIndex"
              @mousedown.prevent="addProject(entry.project)"
              @mousemove="activeIndex = i"
            >
              <span>
                <b style="font-weight: 500">{{ projectName(entry.project) }}</b>
                <span class="muted"> {{ projectCode(entry.project) }}<template v-if="projectOwner(entry.project)"> · {{ projectOwner(entry.project) }}</template></span>
              </span>
              <span v-if="entry.recent" class="tag">上月用过</span>
            </div>
            <div v-if="!picker.items.length" class="hint">{{ projects.length ? '没有匹配的项目' : '无匹配项目，请先在项目管理中新增' }}</div>
            <div v-else-if="picker.total > picker.items.length" class="hint">还有 {{ picker.total - picker.items.length }} 个，输入关键字缩小范围（共 {{ available }} 个进行中项目可选）</div>
          </div>
        </div>
        <template v-if="suggestions.length">
          <span class="muted">上月用过：</span>
          <button v-for="project in suggestions" :key="project.name" type="button" class="ts-suggest" @click="addProject(project)">＋ {{ projectCode(project) }} {{ projectName(project) }}</button>
        </template>
        <span class="quiets">
          <button type="button" class="btn quiet sm" @click="emit('copy')"><RdIcon name="copy" />复制上月</button>
          <button type="button" class="btn quiet sm" @click="emit('import')"><RdIcon name="upload" />批量导入…</button>
          <button type="button" class="btn quiet sm" :disabled="!rows.length" @click="emit('change', [])">清空</button>
        </span>
      </div>

      <div v-if="loading" style="display: flex; justify-content: center; padding: 36px"><Spinner class="h-6 w-6" /></div>
      <div v-else role="table" aria-label="项目分配">
        <div class="ts-tr th" role="row">
          <div role="columnheader">项目</div>
          <div role="columnheader">发生天数</div>
          <div role="columnheader">占本月</div>
          <div class="r" role="columnheader">工时</div>
          <div role="columnheader">备注</div>
          <div role="columnheader"></div>
        </div>
        <div v-for="(row, index) in rows" :key="row.key || row.monthly_entry_id || index" class="ts-tr" role="row">
          <div class="ts-proj" role="cell">
            <div><i class="ts-dot" :style="{ background: projectColor(index) }"></i><b>{{ row.project_name || row.project }}</b></div>
            <div class="muted">{{ row.project_code }}<template v-if="ownerOf(row)"> · {{ ownerOf(row) }}</template></div>
          </div>
          <div role="cell">
            <div class="step" :style="editable && !isValidDaysText(row.occurrence_days) ? { borderColor: 'var(--rd-bad)' } : null">
              <button type="button" :disabled="!editable || !canStepDown(row.occurrence_days)" :aria-label="`减 ${DAY_STEP} 天`" @click="step(index, -DAY_STEP)">−</button>
              <input :value="row.occurrence_days" inputmode="decimal" :disabled="!editable" :aria-label="`${row.project_name || row.project} 发生天数`" @input="setDays(index, $event.target.value)" />
              <button type="button" :disabled="!editable" :aria-label="`加 ${DAY_STEP} 天`" @click="step(index, DAY_STEP)">＋</button>
            </div>
          </div>
          <div class="ts-share" role="cell">
            <div class="ts-track"><i :style="{ width: Math.min(100, sharePercent(row.occurrence_days, dayLimit)) + '%', background: projectColor(index) }"></i></div>
            <span class="num">{{ sharePercent(row.occurrence_days, dayLimit) }}%</span>
          </div>
          <div class="num sub r" role="cell">{{ fmtDays(rowHours(row), 0) }} h</div>
          <div role="cell">
            <input v-if="editable" class="ts-remark" placeholder="备注" :value="row.remark" aria-label="备注" @input="patchRow(index, { remark: $event.target.value })" />
            <span v-else class="sub" style="min-width: 0">{{ row.remark || '-' }}</span>
          </div>
          <div role="cell">
            <button v-if="editable" type="button" class="btn quiet sm bad" :aria-label="`删除 ${row.project_name || row.project}`" @click="emit('remove', index)"><RdIcon name="trash" /></button>
          </div>
        </div>
        <div v-if="!rows.length" class="muted" style="padding: 30px; text-align: center">{{ editable ? '本月还没有工时记录。从上面搜索项目添加，或点“复制上月”、批量导入。' : '本月暂无工时记录' }}</div>
      </div>
      <div v-if="editable" class="ts-hint">保存按钮在右上角，随时能点；＋ / − 每次 0.5 天；超过本月上限时保存会置灰。</div>
    </div>
  </section>
</template>
