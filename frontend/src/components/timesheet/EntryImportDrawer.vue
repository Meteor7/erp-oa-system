<script setup>
// 工时填报：批量粘贴 / Excel 导入抽屉。逐行校验沿用 lib/timesheetImport.js；整批通过才能「加入表格」，
// 而且只收当前所选研发人员的行。
import { computed, nextTick, ref, watch } from 'vue';
import RdIcon from '../rd/RdIcon.vue';
import { importTimesheetWorkbookFile, parseTimesheetPaste } from '../../lib/timesheetImport.js';
import { serverMessage } from '../../lib/timesheetEntryView.js';

const props = defineProps({
  open: { type: Boolean, default: false },
  // { employees, projects, period, existingRows }：交给 timesheetImport.js 校验用
  importOptions: { type: Object, required: true },
  employee: { type: String, default: '' },
});
const emit = defineEmits(['close', 'add']);

const pasteText = ref('');
const errors = ref([]);
const rows = ref([]);
const previewed = ref(false);
const workbookInput = ref(null);
const textarea = ref(null);

const canAdd = computed(() => previewed.value && !errors.value.length && rows.value.length > 0);

function reset() {
  pasteText.value = '';
  errors.value = [];
  rows.value = [];
  previewed.value = false;
}

function applyResult(result) {
  previewed.value = true;
  errors.value = result.errors || [];
  rows.value = [];
  if (errors.value.length) return;
  const imported = result.rows || [];
  if (imported.some((row) => row.employee !== props.employee)) {
    errors.value = ['导入文件中的研发人员必须与当前选择一致'];
    return;
  }
  rows.value = imported;
}

function previewPaste() {
  applyResult(parseTimesheetPaste(pasteText.value, props.importOptions));
}

function chooseWorkbook() {
  workbookInput.value?.click();
}

async function onWorkbook(event) {
  const file = event.target.files?.[0];
  event.target.value = '';
  if (!file) return;
  try {
    applyResult(await importTimesheetWorkbookFile(file, props.importOptions));
  } catch (error) {
    previewed.value = true;
    rows.value = [];
    errors.value = [serverMessage(error, 'Excel 导入失败')];
  }
}

function addRows() {
  if (!canAdd.value) return;
  emit('add', rows.value);
  reset();
  emit('close');
}

watch(() => props.open, async (open) => {
  if (!open) return;
  reset();
  await nextTick();
  textarea.value?.focus();
});
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="rd" @keydown.esc="emit('close')">
      <div class="rd-drawer-bg" @click="emit('close')"></div>
      <aside class="rd-drawer" role="dialog" aria-modal="true" aria-label="批量导入">
        <header>批量导入工时<button type="button" class="btn quiet sm" aria-label="关闭" @click="emit('close')"><RdIcon name="x" /></button></header>
        <div class="body">
          <div class="muted">每行一条：研发人员、项目代码、项目名称、工时（小时）、备注。支持制表符、逗号或多个空格分隔。老模板里的“发生天数”也能导入，按 1 天 = 8 小时换算。只能导入当前所选研发人员的记录。</div>
          <textarea ref="textarea" v-model="pasteText" class="field" placeholder="研发人员　项目代码　项目名称　工时（小时）　备注"></textarea>
          <div class="row">
            <button type="button" class="btn" @click="chooseWorkbook"><RdIcon name="upload" />选择 Excel</button>
            <input ref="workbookInput" type="file" accept=".xlsx,.xls" style="display: none" @change="onWorkbook" />
            <button type="button" class="btn pri" :disabled="!pasteText.trim()" @click="previewPaste">预览</button>
          </div>
          <div v-if="!previewed" class="muted">预览后在这里显示校验结果。</div>
          <template v-else>
            <div v-if="errors.length">
              <div v-for="message in errors" :key="message" class="row between" style="padding: 7px 0; border-bottom: 1px solid var(--rd-line)">
                <span style="color: var(--rd-bad)">{{ message }}</span>
              </div>
              <div class="note bad" style="margin-top: 10px"><RdIcon name="alert" /><span>有 {{ errors.length }} 处错误，整批不会导入，请改正后重新预览。</span></div>
            </div>
            <div v-else>
              <div v-for="(row, index) in rows" :key="index" class="row between" style="padding: 7px 0; border-bottom: 1px solid var(--rd-line)">
                <span>{{ row.employee_name }} · {{ row.project_code }} · <b class="num">{{ row.hours }}</b> 小时 <span class="muted">约 {{ row.occurrence_days }} 天</span></span>
                <span class="tag ok">通过</span>
              </div>
              <div class="note ok" style="margin-top: 10px"><RdIcon name="check" /><span>共 {{ rows.length }} 行，全部通过。</span></div>
            </div>
          </template>
        </div>
        <footer>
          <button type="button" class="btn" @click="emit('close')">关闭</button>
          <button type="button" class="btn pri" :disabled="!canAdd" @click="addRows">加入表格</button>
        </footer>
      </aside>
    </div>
  </Teleport>
</template>
