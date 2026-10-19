<script setup>
// 一条差异的详情：申报和后台复算逐项对比、原因、处理方式。处理只有两种有记录的结果（确认纳入 / 忽略），
// 其余选项是引导去"基数与金额"里补齐再回来重新核对。
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { comparisonLines, drawerOptions, kindOf, money, STATUS_LABEL } from '../../lib/contributionView.js';
import { displayCompany } from '../../lib/displayBrand.js';

const props = defineProps({
  kind: { type: String, required: true },
  item: { type: Object, required: true },
  employees: { type: Array, default: () => [] },
  busy: { type: Boolean, default: false },
  error: { type: String, default: '' },
  readonly: { type: Boolean, default: false },   // 只读（总经理、演示员工113经理）：不给处理选项和提交按钮
});
const emit = defineEmits(['close', 'confirm', 'ignore', 'fix']);

const options = computed(() => drawerOptions(props.kind, props.item));
const choice = ref(0);
const note = ref(props.item.remark || '');
const linked = ref(props.item.employee || '');
const lines = computed(() => comparisonLines(props.kind, props.item.raw));
const choices = computed(() => options.value.map((option, index) => ({ ...option, index })));
const picked = computed(() => options.value[choice.value] || options.value[0]);
const employeeChoices = computed(() => props.employees.filter((employee) => !props.item.company || employee.company === props.item.company));
const canSubmit = computed(() => {
  const option = picked.value;
  if (!option || props.busy) return false;
  if (option.key === 'fix') return true;
  if (option.key === 'link' && !linked.value) return false;
  return Boolean(note.value.trim());
});
const submitText = computed(() => ({ fix: '去补齐', link: '确认纳入', confirm: '确认纳入', ignore: '忽略这一行' }[picked.value?.key] || '确认'));

watch(() => props.item.id, () => { choice.value = 0; note.value = props.item.remark || ''; linked.value = props.item.employee || ''; });
choice.value = Math.max(options.value.findIndex((option) => option.recommended), 0);

function submit() {
  const option = picked.value;
  if (!canSubmit.value) return;
  const remark = (option.note || '') + note.value.trim();
  if (option.key === 'fix') emit('fix');
  else if (option.key === 'ignore') emit('ignore', { row: props.item.id, remark });
  else emit('confirm', { row: props.item.id, employee: option.key === 'link' ? linked.value : props.item.employee, remark });
}
function onKey(event) { if (event.key === 'Escape') emit('close'); }
onMounted(() => document.addEventListener('keydown', onKey));
onBeforeUnmount(() => document.removeEventListener('keydown', onKey));
const cell = (value) => (value == null ? '—' : money(value));
</script>

<template>
  <div class="cw-scrim" @click="emit('close')"></div>
  <aside class="cw-drawer" role="dialog" aria-modal="true" :aria-label="`${item.name} 差异明细`">
    <header>
      <div>
        <h4>{{ item.name }} · {{ kindOf(kind).name }}</h4>
        <div class="muted">{{ displayCompany(item.company) }}<template v-if="item.identity"> · {{ item.identity }}</template> · <span :class="['pill', item.resolved ? 'p-jade' : 'p-sun']">{{ item.resolved ? (STATUS_LABEL[item.status] || item.status) : '待处理' }}</span></div>
      </div>
      <button type="button" class="btn sm" @click="emit('close')">关闭</button>
    </header>
    <div class="body">
      <div style="display:grid;gap:4px">
        <div v-for="type in item.types" :key="type.label + type.text"><span :class="['pill', type.tone === 'bad' ? 'p-red' : 'p-sun']">{{ type.label }}</span> <span>{{ type.text }}</span></div>
      </div>
      <div v-if="item.rowType !== 'missing'" class="tbl narrow">
        <table class="cw-cmp">
          <thead><tr><th>项目</th><th class="r">申报（Excel）</th><th class="r">后台复算</th></tr></thead>
          <tbody>
            <tr v-for="line in lines" :key="line.field"><td>{{ line.label }}</td><td :class="['r', 'num', { diff: line.differs }]">{{ cell(line.excel) }}</td><td :class="['r', 'num', { diff: line.differs }]">{{ cell(line.calc) }}</td></tr>
          </tbody>
        </table>
      </div>
      <div v-else class="muted">档案里这个人有{{ kindOf(kind).name }}基数，本月申报表却没有他。</div>
      <div v-if="readonly && !item.resolved" class="muted" data-cw-drawer-readonly>待人事处理。</div>
      <template v-else-if="!item.resolved">
        <b>怎么处理</b>
        <label v-for="option in choices" :key="option.index" class="cw-opt">
          <input v-model.number="choice" type="radio" name="cw-choice" :value="option.index">
          <span>{{ option.label }}<span v-if="option.recommended" class="rec">建议</span><div v-if="option.hint" class="muted">{{ option.hint }}</div></span>
        </label>
        <label v-if="picked && picked.key === 'link'" class="muted">关联员工
          <select v-model="linked" aria-label="关联员工"><option value="">请选择员工</option><option v-for="employee in employeeChoices" :key="employee.name" :value="employee.name">{{ employee.employee_name }}</option></select>
        </label>
        <label v-if="picked && picked.key !== 'fix'" class="muted">备注（必填，之后查账能看到）
          <textarea v-model="note" placeholder="写明原因"></textarea>
        </label>
      </template>
      <div v-else class="muted">已处理：{{ STATUS_LABEL[item.status] || item.status }}<template v-if="item.remark">，备注：{{ item.remark }}</template></div>
      <div v-if="error" class="err" role="alert">{{ error }}</div>
    </div>
    <footer>
      <button type="button" class="btn" @click="emit('close')">关闭</button>
      <button v-if="!readonly && !item.resolved" type="button" class="btn pri" :disabled="!canSubmit" @click="submit">{{ submitText }}</button>
    </footer>
  </aside>
</template>
