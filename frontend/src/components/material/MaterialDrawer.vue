<script setup>
// 物料看板右侧抽屉："明细 ›" 打开。上面是这条物料的基本信息，中间嵌入原来的执行进度组件
// （PR → 价格审批 → PO → 到货验收 → 付款的分支），下面是"标记为取消"（原因必填，不再用浏览器弹窗）。
import { computed, ref, watch } from 'vue';
import MaterialExecutionProgress from '../MaterialExecutionProgress.vue';
import { cancelReasonProblem, statusPill } from '../../lib/materialView.js';

const props = defineProps({
  line: { type: Object, default: null },
  row: { type: Object, default: null },
  busy: { type: Boolean, default: false },
});
const emit = defineEmits(['close', 'cancel']);

const reason = ref('');
const touched = ref(false);
const problem = computed(() => cancelReasonProblem(reason.value));
const cancelled = computed(() => props.row?.record_status === '已取消');
const quantityText = computed(() => (props.row ? [props.row.quantity, props.row.unit].filter((part) => part !== undefined && part !== '').join(' ') : ''));

watch(() => [props.line?.source_request, props.line?.source_line], () => { reason.value = ''; touched.value = false; });

function submitCancel() {
  touched.value = true;
  if (problem.value) return;
  emit('cancel', reason.value.trim());
}
</script>

<template>
  <div v-if="line" class="mp-mask" @click.self="emit('close')">
    <aside class="mp-drawer" role="dialog" aria-modal="true" aria-label="物料明细" @keydown.esc="emit('close')">
      <header class="mp-drawer-head">
        <div class="grow-col">
          <span class="muted">物料明细 · 来源 {{ line.source_request }}</span>
          <b class="mp-drawer-title">{{ row?.item_name || row?.material_serial || '物料拆分明细' }}</b>
        </div>
        <button type="button" class="mp-x" aria-label="关闭明细" @click="emit('close')">×</button>
      </header>

      <div class="mp-drawer-body">
        <div v-if="row" class="mp-drawer-kv">
          <div><small>流水号</small><span>{{ row.material_serial || '—' }}</span></div>
          <div><small>规格</small><span>{{ row.specification || '—' }}</span></div>
          <div><small>申请数量</small><span>{{ quantityText || '—' }}</span></div>
          <div><small>主状态</small><span><b v-if="row.progress_status" :class="statusPill(row.progress_status)">{{ row.progress_status }}</b><template v-else>—</template></span></div>
        </div>

        <div class="mp-drawer-block">
          <b class="mp-drawer-sub">执行分支</b>
          <MaterialExecutionProgress :key="line.source_request + ':' + (line.source_line || '')" :request="line.source_request" :source-line="line.source_line" expanded />
          <span class="muted">供应商、单价和金额只有采购、PMC、副总经理、财务能看到，其他人这里只有数量和状态。</span>
        </div>

        <div v-if="row" class="mp-drawer-block mp-cancel">
          <b class="mp-drawer-sub">取消这条物料记录</b>
          <template v-if="cancelled">
            <span class="muted">这条记录已经标记为取消。</span>
          </template>
          <template v-else>
            <label class="f">
              <textarea v-model="reason" class="mp-reason" rows="2" maxlength="500" placeholder="取消原因（必填，不超过 500 字）" aria-label="取消原因"></textarea>
            </label>
            <span v-if="touched && problem" class="err" role="alert">{{ problem }}</span>
            <span class="mp-warn">只是把看板上这条记录标成"已取消"并通知相关人员；不会取消已经生成的 PR / 价格审批 / PO，也不会释放 PR 数量。</span>
            <button type="button" class="btn danger mp-cancel-btn" :disabled="busy" @click="submitCancel">标记为取消</button>
          </template>
        </div>
      </div>
    </aside>
  </div>
</template>
