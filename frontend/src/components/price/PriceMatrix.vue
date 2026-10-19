<script setup>
// 供应商比价矩阵 + 商务条件对比。矩阵只读；采购在草稿状态下通过"编辑此供应商"打开右侧抽屉修改。
import { computed } from 'vue';
import {
  MIN_SUPPLIER_SLOTS, amountText, buildMatrix, latestDelivery, quantity, shortDate, supplierQuoteLabel, supplierTotalNote,
} from '../../lib/priceView.js';

const props = defineProps({
  approval: { type: Object, required: true },
  canEdit: { type: Boolean, default: false },
  canSelect: { type: Boolean, default: false },
  busy: { type: Boolean, default: false },
  confirmDelete: { type: String, default: '' },
});
const emit = defineEmits(['select', 'edit', 'delete', 'ask-delete', 'cancel-delete']);

const matrix = computed(() => buildMatrix(props.approval));
const lines = computed(() => props.approval.lines || []);
const placeholders = computed(() => (props.canEdit ? Math.max(0, MIN_SUPPLIER_SLOTS - matrix.value.suppliers.length) : 0));
const hasSuppliers = computed(() => matrix.value.suppliers.length > 0);

// PMC 看不到金额（服务端去掉了，amounts_hidden）：显示“—”
const cash = (value) => amountText(value, props.approval.amounts_hidden);

function planText(row) {
  return `${row.installment_name || `第${row.installment_no || ''}期`} · ${row.payment_stage} ${Number(row.percentage || 0)}% · ${cash(row.amount)} · ${row.trigger_condition || '—'} · 发票${row.invoice_requirement || '—'}`;
}
</script>

<template>
  <section class="panel pa-matrix-panel">
    <div class="pt">
      <span>供应商比价 <span class="muted">{{ matrix.suppliers.length }} 家 · 没报价的物料留空 · 每家的商务条件对整张单一致</span></span>
      <button v-if="canEdit" type="button" class="btn sm" @click="emit('edit', '')">＋ 新增供应商</button>
    </div>

    <div class="tbl pa-matrix-wrap">
      <table class="pa-matrix">
        <thead>
          <tr>
            <th class="pa-mat-col">物料（{{ lines.length }} 项）</th>
            <th v-for="item in matrix.suppliers" :key="item.supplier" :class="['pa-sup-head', { chosen: item.isSelected }]">
              <div class="pa-sup-name">
                <b>{{ item.supplier }}</b>
                <span v-if="item.isRecommended" class="pill p-jade">采购推荐</span>
                <span v-if="item.isSelected" class="pill p-brand pa-chosen">已选成交</span>
              </div>
              <div class="pa-sup-sub">
                <span :class="item.complete ? 'muted' : 'warn'">{{ supplierQuoteLabel(item) }}</span>
                <button v-if="canSelect && !item.isSelected" type="button" class="btn sm" :disabled="busy" @click="emit('select', item.supplier)">选择成交供应商</button>
                <button v-else-if="canEdit" type="button" class="link" @click="emit('edit', item.supplier)">编辑</button>
              </div>
            </th>
            <th v-for="n in placeholders" :key="`empty-${n}`" class="pa-sup-head pa-empty-head">
              <button type="button" class="link" @click="emit('edit', '')">＋ 添加供应商 {{ matrix.suppliers.length + n }}</button>
              <div class="muted">还没有录入</div>
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in matrix.rows" :key="row.line.name">
            <td class="pa-mat-col">
              <b>{{ row.line.item_name }}</b>
              <div class="muted">{{ row.line.specification || '—' }} · {{ quantity(row.line.quantity) }} {{ row.line.unit }}</div>
              <div class="muted num">{{ row.line.material_serial }}<template v-if="row.line.source_request"> · {{ row.line.source_request }}</template></div>
            </td>
            <td v-for="cell in row.cells" :key="cell.supplier" :class="{ chosen: cell.chosen }">
              <template v-if="cell.quoted">
                <div class="pa-price num">{{ cash(cell.total) }}</div>
                <div class="muted">单价 {{ cash(cell.unit) }} · 货期 {{ shortDate(cell.delivery) }}<template v-if="cell.best"> · <b class="pa-best">本项最低</b></template></div>
              </template>
              <template v-else>
                <div class="pa-none">未报价</div>
                <div v-if="!canEdit" class="muted">选它则退回 PR</div>
              </template>
            </td>
            <td v-for="n in placeholders" :key="`empty-cell-${n}`" class="pa-empty-cell"></td>
          </tr>
          <tr v-if="!hasSuppliers && !placeholders">
            <td :colspan="1 + Math.max(1, matrix.suppliers.length)" class="empty">还没有供应商报价</td>
          </tr>
        </tbody>
        <tfoot v-if="hasSuppliers || placeholders">
          <tr>
            <th class="pa-mat-col">报价合计</th>
            <th v-for="item in matrix.suppliers" :key="item.supplier" :class="['pa-total', { chosen: item.isSelected }]">
              <div class="num">{{ cash(item.total) }}</div>
              <div :class="['pa-total-note', item.complete ? 'ok' : 'warn']">{{ supplierTotalNote(item) }}</div>
            </th>
            <th v-for="n in placeholders" :key="`empty-total-${n}`" class="pa-empty-cell"></th>
          </tr>
        </tfoot>
      </table>
    </div>
    <p class="muted foot">总价只在"每家都报了全部物料"时才比较；只报了一部分的，不会被标成最低价。选了这家之后，它没报价的物料会退回 PR，重新比价。</p>
  </section>

  <section class="panel pa-terms-panel">
    <div class="pt"><span>商务条件对比 <span class="muted">只读对照；采购在草稿状态下点"编辑此供应商"修改</span></span></div>
    <div v-if="!hasSuppliers" class="empty">录入供应商后在这里对照付款方式、付款计划等商务条件</div>
    <div v-else class="tbl">
      <table class="pa-terms">
        <tbody>
          <tr>
            <th scope="row">付款方式</th>
            <td v-for="item in matrix.suppliers" :key="item.supplier" :class="{ chosen: item.isSelected }">{{ item.group.payment_method || '—' }}</td>
          </tr>
          <tr>
            <th scope="row">付款计划</th>
            <td v-for="item in matrix.suppliers" :key="item.supplier" :class="{ chosen: item.isSelected }">
              <div v-for="(row, index) in item.group.payment_plan || []" :key="index" class="pa-plan-line">{{ planText(row) }}</div>
              <span v-if="!(item.group.payment_plan || []).length">—</span>
            </td>
          </tr>
          <tr>
            <th scope="row">币种 / 税率</th>
            <td v-for="item in matrix.suppliers" :key="item.supplier" :class="{ chosen: item.isSelected }">{{ item.group.currency || 'CNY' }} / {{ Number(item.group.tax_rate || 0) }}%</td>
          </tr>
          <tr>
            <th scope="row">演示员工116主体</th>
            <td v-for="item in matrix.suppliers" :key="item.supplier" :class="{ chosen: item.isSelected }">{{ item.group.contract_entity || '—' }}</td>
          </tr>
          <tr>
            <th scope="row">最晚货期</th>
            <td v-for="item in matrix.suppliers" :key="item.supplier" :class="{ chosen: item.isSelected }">{{ shortDate(latestDelivery(item.group)) }}</td>
          </tr>
          <tr>
            <th scope="row">报价说明</th>
            <td v-for="item in matrix.suppliers" :key="item.supplier" :class="{ chosen: item.isSelected }">{{ item.group.note || '—' }}</td>
          </tr>
          <tr v-if="canEdit">
            <th scope="row"></th>
            <td v-for="item in matrix.suppliers" :key="item.supplier" class="pa-term-actions">
              <template v-if="confirmDelete === item.supplier">
                <span class="pa-confirm-text">删除 {{ item.supplier }} 对整张单的报价？</span>
                <button type="button" class="btn sm danger" :disabled="busy" @click="emit('delete', item.supplier)">确认删除</button>
                <button type="button" class="btn sm" @click="emit('cancel-delete')">返回</button>
              </template>
              <template v-else>
                <button type="button" class="link" @click="emit('edit', item.supplier)">编辑此供应商</button>
                <button type="button" class="link pa-danger" @click="emit('ask-delete', item.supplier)">删除</button>
              </template>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>
