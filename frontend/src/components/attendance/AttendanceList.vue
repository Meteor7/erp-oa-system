<script setup>
// 申请列表：按范围（待我审批 / 我的 / 我审批过的 / 全部）和类型筛选，点任意一行看详情；
// 只有"待我审批"的行可以勾选批量同意。页面标题和主按钮跟着类型走。
import { computed, ref, watch } from 'vue';
import {
  SCOPES, byWait, canQuickApprove, departmentLabel, filterRows, kindOf, listTitle, newButtonLabel, nodeText, numText, personShort,
  rowChips, scopeTabs, statusTag, submittedText, totalOf, typeChips, waitText,
} from '../../lib/attendanceView.js';

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
const emit = defineEmits(['home', 'scope', 'filter', 'new', 'open', 'approve-many']);

const picked = ref([]);
const scope = computed(() => props.page.scope);
const filter = computed(() => props.page.filter);
const title = computed(() => listTitle(filter.value));
const tabs = computed(() => scopeTabs({ sets: props.sets, filter: filter.value, isApprover: props.isApprover, canViewAll: props.canViewAll, allLoaded: props.loaded.all }));
const chips = computed(() => typeChips({}, filter.value));
const ready = computed(() => ({ todo: props.loaded.review, mine: props.loaded.mine, done: props.loaded.reviewed, all: props.loaded.all })[scope.value] ?? false);
const rows = computed(() => {
  const list = filterRows(props.sets[scope.value] || [], filter.value);
  return scope.value === 'todo' ? byWait(list, props.now) : list;
});
const selectable = computed(() => (scope.value === 'todo' ? rows.value.filter(canQuickApprove) : []));
const chosen = computed(() => selectable.value.filter((row) => picked.value.includes(row.name)));
const allChosen = computed(() => selectable.value.length > 0 && chosen.value.length === selectable.value.length);

watch([scope, filter], () => { picked.value = []; });
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

const scopeLabel = computed(() => SCOPES.find((item) => item.key === scope.value)?.label || '');
const subtitle = computed(() => (scope.value === 'all' ? '只读：所有人已提交的请假、加班、调休（最近 100 张）。' : '按范围、类型筛选；点任意一行看详情。'));
</script>

<template>
  <div class="at-page">
    <div class="ph">
      <div>
        <div class="crumb"><button type="button" class="link" @click="emit('home')">考勤中心</button> › {{ title }}</div>
        <h3>{{ title }}</h3>
        <div class="muted">{{ subtitle }}</div>
      </div>
      <button v-if="hasEmployee" type="button" class="btn pri lg" @click="emit('new', filter)">{{ newButtonLabel(filter) }}</button>
    </div>

    <div class="at-scopes seg" role="tablist" aria-label="范围">
      <button v-for="tab in tabs" :key="tab.key" type="button" role="tab" :aria-selected="scope === tab.key" :aria-pressed="scope === tab.key" @click="emit('scope', tab.key)">
        {{ tab.label }}<small v-if="tab.count !== null">{{ tab.count }}</small>
      </button>
    </div>

    <section class="panel flush" :aria-label="scopeLabel">
      <div class="at-bar">
        <button v-for="item in chips" :key="item.key" type="button" :class="['chip', { on: item.on }]" :aria-pressed="item.on" @click="emit('filter', item.key)">{{ item.label }}</button>
        <span v-if="scope === 'todo'" class="at-right at-batch">
          <span class="muted">已选 {{ chosen.length }} 张</span>
          <button type="button" class="btn sm pri" :disabled="!chosen.length || busy" @click="approveChosen">批量同意</button>
        </span>
      </div>
      <div class="tbl">
        <table class="at-table" aria-label="申请列表">
          <thead>
            <tr>
              <th v-if="scope === 'todo'" class="at-check"><input type="checkbox" aria-label="全选" :checked="allChosen" :disabled="!selectable.length" @change="toggleAll" /></th>
              <th>申请人</th><th>类型</th><th>日期与时段</th><th class="r">时长</th><th>状态 · 当前节点</th><th>提交</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="!scope || !ready"><td :colspan="scope === 'todo' ? 7 : 6" class="empty">正在加载…</td></tr>
            <tr v-else-if="!rows.length"><td :colspan="scope === 'todo' ? 7 : 6" class="empty">这个范围里没有申请</td></tr>
            <tr v-for="row in ready ? rows : []" :key="row.name + String(row.acted_on || '')" class="row-sel" tabindex="0" @click="emit('open', row)" @keydown.enter="emit('open', row)">
              <td v-if="scope === 'todo'" class="at-check" @click.stop>
                <input type="checkbox" :aria-label="'选择 ' + row.name" :checked="picked.includes(row.name)" :disabled="!canQuickApprove(row)" :title="canQuickApprove(row) ? '' : '这一步要进详情页处理'" @change="toggle(row)" />
              </td>
              <td>
                <div class="at-who"><span class="at-av">{{ personShort(row.employee_name) }}</span><div><b>{{ row.employee_name }}</b><div class="muted">{{ departmentLabel(row.department) }}</div></div></div>
              </td>
              <td><span :class="['at-tag', kindOf(row).tone]">{{ kindOf(row).text }}</span></td>
              <td>
                <div class="at-dchips">
                  <span v-for="day in rowChips(row, 3).chips" :key="day.date + day.text" :class="['at-dchip', day.mode]">{{ day.text }}</span>
                  <span v-if="rowChips(row, 3).more" class="at-dchip">… 共 {{ rowChips(row).chips.length }} 天</span>
                </div>
              </td>
              <td class="r num"><b>{{ numText(totalOf(row)) }}</b> h</td>
              <td>
                <span :class="['at-tag', statusTag(row).tone]">{{ statusTag(row).text }}</span>
                <div class="muted">{{ nodeText(row, names) }}</div>
              </td>
              <td class="num muted">{{ submittedText(row) }}<div v-if="scope !== 'done' && waitText(row, now) && ['待审批', '待办理'].includes(row.workflow_status)">已等 {{ waitText(row, now) }}</div></td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="muted at-foot">显示 {{ ready ? rows.length : 0 }} 张</div>
    </section>
  </div>
</template>
