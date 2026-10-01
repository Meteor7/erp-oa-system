<script setup>
// 一张价格审批单的详情：头部（状态、金额、操作）、比价矩阵、商务条件、采购比价总结、需求内容、审批轨迹。
// 采购能编辑的只有草稿；副总经理只有"选一家成交 + 审批通过"，没有退回 / 拒绝。
import { computed, ref, watch } from 'vue';
import PriceMatrix from './PriceMatrix.vue';
import {
  approvalGuide, approvalTimeline, approvalTone, chosenGroup, money, pillClass, posForApproval, quantity,
  selectionConsequence, splitList, submitBlockers,
} from '../../lib/priceView.js';

const props = defineProps({
  approval: { type: Object, required: true },
  pos: { type: Array, default: () => [] },
  canEdit: { type: Boolean, default: false },
  busy: { type: Boolean, default: false },
});
const emit = defineEmits([
  'back', 'open-po', 'save-summary', 'submit', 'cancel', 'withdraw', 'approve', 'select', 'edit', 'delete',
]);

const summaryDraft = ref(props.approval.summary || '');
const confirming = ref('');
const confirmDelete = ref('');
const showRequirement = ref(false);

// 注意用"一组 getter"的写法：只有名字 / 总结 / 状态真的变了才重置，别的刷新（比如保存供应商）不会冲掉正在输入的总结。
watch([() => props.approval.name, () => props.approval.summary], () => { summaryDraft.value = props.approval.summary || ''; });
watch([() => props.approval.name, () => props.approval.status], () => { confirming.value = ''; confirmDelete.value = ''; });

const status = computed(() => props.approval.status);
const isDraft = computed(() => status.value === '草稿');
const editable = computed(() => props.canEdit && isDraft.value);
const canDecide = computed(() => Boolean(props.approval.can_select_quote) && status.value === '待审批');
const canWithdraw = computed(() => props.canEdit && status.value === '待审批');
const canCancel = computed(() => props.canEdit && ['草稿', '待审批'].includes(status.value));
const chosen = computed(() => chosenGroup(props.approval));
const consequence = computed(() => selectionConsequence(props.approval, chosen.value));
const guide = computed(() => approvalGuide(props.approval, { canEdit: props.canEdit }));
const blockers = computed(() => submitBlockers(props.approval, summaryDraft.value));
const linkedPos = computed(() => posForApproval(props.pos, props.approval.name));
const timeline = computed(() => approvalTimeline(props.approval));
const lines = computed(() => props.approval.lines || []);
const totalLabel = computed(() => (chosen.value ? '成交总额' : '已选报价总额'));
const totalText = computed(() => (chosen.value ? money(props.approval.total_amount) : '—'));
const sourceLine = computed(() => {
  const a = props.approval;
  const people = [a.source_requesters, a.source_departments].filter(Boolean).join(' · ');
  const requests = splitList(a.source_requests).join('、');
  const projects = splitList(a.source_projects).join('、');
  return [
    a.source_prs ? `来源 ${a.source_prs}` : '',
    requests ? `${requests}${people ? `（${people}）` : ''}` : '',
    projects ? `项目 ${projects}` : '',
    `${lines.value.length} 项物料（一张价格审批单可以跨 PR / OA / 项目）`,
  ].filter(Boolean).join(' · ');
});
const confirmText = computed(() => {
  if (confirming.value === 'cancel') return '取消后将终止价格审批单并释放 PR 数量，是否继续？';
  if (confirming.value === 'withdraw') return '撤回后价格审批单回到草稿，已占用的 PR 数量会释放，是否继续？';
  if (confirming.value === 'approve' && consequence.value) {
    const info = consequence.value;
    return `确认审批通过？成交供应商 ${info.supplier}，成交总额 ${money(info.total)}，将生成 1 张 PO 草稿。${info.returned ? `它没报价的 ${info.returned} 项物料会退回 PR。` : ''}PO 生成后系统不提供取消。`;
  }
  return '';
});

function runConfirmed() {
  const key = confirming.value;
  confirming.value = '';
  if (key === 'cancel') emit('cancel');
  else if (key === 'withdraw') emit('withdraw');
  else if (key === 'approve') emit('approve');
}
</script>

<template>
  <div class="pa-detail">
    <div class="crumb"><button type="button" class="link" @click="emit('back')">价格审批单</button> › {{ approval.name }}</div>

    <section class="panel pa-head">
      <div class="detail-head">
        <div class="grow-col">
          <div class="title-line"><h3 class="num">{{ approval.name }}</h3><span :class="pillClass(approvalTone(status))">{{ status === '待审批' ? '待审批 · 副总经理' : status }}</span></div>
          <div class="muted">{{ sourceLine }}</div>
        </div>
        <div class="amount-block"><span class="muted">{{ totalLabel }}</span><b>{{ totalText }}</b></div>
        <div class="head-buttons">
          <template v-if="canCancel && isDraft">
            <button type="button" class="btn" :disabled="busy" @click="confirming = 'cancel'">取消价格审批</button>
          </template>
          <button v-if="editable" type="button" class="btn pri lg" :disabled="busy || blockers.length > 0" @click="emit('submit', summaryDraft)">提交价格审批</button>
          <template v-if="canWithdraw">
            <button type="button" class="btn" :disabled="busy" @click="confirming = 'withdraw'">撤回修改</button>
            <button type="button" class="btn" :disabled="busy" @click="confirming = 'cancel'">取消价格审批</button>
          </template>
          <button v-if="canDecide" type="button" class="btn pri lg" :disabled="busy || !chosen" :aria-describedby="!chosen ? 'pa-approve-hint' : undefined" @click="confirming = 'approve'">审批通过，生成 PO</button>
        </div>
      </div>

      <div v-if="confirming" class="pa-confirm" role="alertdialog" aria-label="确认操作">
        <span>{{ confirmText }}</span>
        <button type="button" class="btn sm pri" :disabled="busy" @click="runConfirmed">确认</button>
        <button type="button" class="btn sm" @click="confirming = ''">返回</button>
      </div>

      <div v-if="guide" id="pa-approve-hint" :class="['pa-guide', `g-${guide.tone}`]" role="status">{{ guide.text }}</div>
      <div v-if="editable && blockers.length" class="pa-guide g-sun">提交前还差：{{ blockers.join('；') }}。</div>
      <div v-if="linkedPos.length" class="pa-guide g-jade">
        已生成 PO：
        <button v-for="po in linkedPos" :key="po.name" type="button" class="link strong pa-po-link" @click="emit('open-po', po.name)">{{ po.name }}（{{ po.status }}）</button>
      </div>
    </section>

    <PriceMatrix
      :approval="approval" :can-edit="editable" :can-select="canDecide" :busy="busy" :confirm-delete="confirmDelete"
      @select="emit('select', $event)" @edit="emit('edit', $event)"
      @ask-delete="confirmDelete = $event" @cancel-delete="confirmDelete = ''" @delete="emit('delete', $event)"
    />

    <div class="detail-grid">
      <section class="panel pa-summary">
        <div class="pt"><span>采购比价总结</span><span class="muted">{{ editable ? '推荐供应商、价格、交期、付款方式及选择依据（必填）' : '只读' }}</span></div>
        <template v-if="editable">
          <div class="f"><textarea v-model="summaryDraft" rows="4" maxlength="2000" placeholder="填写综合比较结论和推荐理由" aria-label="采购比价总结"></textarea></div>
          <div class="actions"><button type="button" class="btn" :disabled="busy" @click="emit('save-summary', summaryDraft)">保存总结</button></div>
        </template>
        <p v-else class="pa-summary-text">{{ approval.summary || '未填写' }}</p>

        <div class="pa-req-toggle">
          <button type="button" class="chip" :aria-expanded="showRequirement" @click="showRequirement = !showRequirement">需求内容（只读）{{ showRequirement ? ' · 收起' : ' · 展开' }}</button>
          <span class="muted">需求单号、来源 PR、使用部门、需求人、项目，以及每项物料的规格参数、品牌、OA 预计交期</span>
        </div>
        <div v-if="showRequirement" class="pa-requirement">
          <div class="kv">
            <div><span>需求单号</span>{{ approval.source_requests || '—' }}</div>
            <div><span>来源 PR</span>{{ approval.source_prs || '—' }}</div>
            <div><span>使用部门</span>{{ approval.source_departments || '—' }}</div>
            <div><span>需求人</span>{{ approval.source_requesters || '—' }}</div>
            <div><span>项目</span>{{ approval.source_projects || '—' }}</div>
          </div>
          <div class="tbl">
            <table>
              <thead><tr><th>序号</th><th>物料流水号</th><th>物料编号</th><th>物料名称</th><th>规格参数</th><th>产品描述</th><th>品牌</th><th class="r">数量</th><th>单位</th><th>OA 预计交期</th><th>项目</th></tr></thead>
              <tbody>
                <tr v-for="(line, index) in lines" :key="line.name">
                  <td>{{ index + 1 }}</td><td class="num">{{ line.material_serial }}</td><td class="num">{{ line.material_code || '—' }}</td>
                  <td><b>{{ line.item_name || '—' }}</b></td><td>{{ line.specification || '—' }}</td><td>{{ line.product_desc || '—' }}</td>
                  <td>{{ line.brand || '—' }}</td><td class="r num">{{ quantity(line.quantity) }}</td><td>{{ line.unit || '—' }}</td>
                  <td class="num">{{ line.expected_delivery_date || '—' }}</td><td>{{ line.project || approval.source_projects || '—' }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </section>

      <section class="panel pa-trail">
        <div class="pt"><span>审批轨迹</span></div>
        <div v-for="(item, index) in timeline" :key="item.key" :class="['tl', item.state]">
          <div class="rail"><i></i><span v-if="index < timeline.length - 1"></span></div>
          <div class="body"><b>{{ item.label }}</b><span class="muted">{{ item.sub }}</span><span v-if="item.note" class="note">{{ item.note }}</span></div>
        </div>
        <p class="muted foot">副总经理在这里只有"选一家成交并通过"，没有退回或拒绝；不满意就请采购撤回修改。</p>
      </section>
    </div>
  </div>
</template>
