<script setup>
// 出差申请列表（首页底部和列表页共用）：每行一个操作——继续编辑 / 撤回 / 下推报销、下推付款 / 详情。
// 撤回的原因在这一行下面直接填，不弹浏览器窗口。
import { ref } from 'vue';
import { displayStatus, pillClass } from '../../lib/expenseClaims.js';
import { dateRange, rowAction } from '../../lib/travelView.js';

const props = defineProps({
  rows: { type: Array, default: () => [] },
  own: { type: Function, default: () => true },
  loading: { type: Boolean, default: false },
  busy: { type: Boolean, default: false },
  empty: { type: String, default: '这里没有出差申请' },
  showApplicant: { type: Boolean, default: false },
  approvable: { type: Boolean, default: false },
});
const emit = defineEmits(['open', 'edit', 'push', 'withdraw', 'approve']);

const asking = ref('');
const note = ref('');

function ask(row) {
  asking.value = asking.value === row.name ? '' : row.name;
  note.value = '';
}
function confirmWithdraw(row) {
  emit('withdraw', row, note.value.trim());
  asking.value = '';
}
const action = (row) => rowAction(row, props.own(row));
const cols = () => (props.showApplicant ? 7 : 6);
</script>

<template>
  <div class="tbl tv-table">
    <table>
      <thead>
        <tr>
          <th>主题 / 单号</th><th v-if="showApplicant">出差人</th><th>出差地点</th><th>日期</th><th>项目</th><th>状态</th><th class="r">操作</th>
        </tr>
      </thead>
      <tbody>
        <template v-for="row in rows" :key="row.name">
          <tr>
            <td>
              <button type="button" class="link strong" @click="emit('open', row)">{{ row.subject || '（无主题）' }}</button>
              <div class="muted num">{{ row.name }}<template v-if="row.workflow_status === '草稿'">（草稿）</template></div>
            </td>
            <td v-if="showApplicant">{{ row.employee_name }}<div class="muted">{{ row.department }}</div></td>
            <td>{{ row.travel_destination }}</td>
            <td class="num">{{ dateRange(row) }}<span class="muted"> · {{ row.travel_days || 0 }} 天</span></td>
            <td>{{ row.project || '非项目' }}</td>
            <td><span :class="pillClass(displayStatus(row))">{{ displayStatus(row) }}</span></td>
            <td class="r tv-ops">
              <button v-if="approvable && row.can_approve" type="button" class="btn sm dark" :disabled="busy" @click="emit('approve', row)">同意</button>
              <template v-if="action(row) === 'edit'"><button type="button" class="btn sm" :disabled="busy" @click="emit('edit', row)">继续编辑</button></template>
              <template v-else-if="action(row) === 'push'">
                <button type="button" class="btn sm" @click="emit('push', row, 'claim')">下推报销</button>
                <button type="button" class="btn sm" @click="emit('push', row, 'payment')">下推付款</button>
              </template>
              <template v-else-if="action(row) === 'withdraw'">
                <button type="button" class="btn sm" :disabled="busy" @click="ask(row)">撤回</button>
                <button type="button" class="btn sm" @click="emit('open', row)">详情</button>
              </template>
              <button v-else type="button" class="btn sm" @click="emit('open', row)">详情</button>
            </td>
          </tr>
          <tr v-if="asking === row.name" class="tv-ask-row">
            <td :colspan="cols()">
              <div class="tv-ask">
                <input v-model="note" :aria-label="'撤回原因 ' + row.name" placeholder="撤回原因（可选）" @keyup.enter="confirmWithdraw(row)" />
                <button type="button" class="btn sm pri" :disabled="busy" @click="confirmWithdraw(row)">确认撤回</button>
                <button type="button" class="btn sm" @click="asking = ''">取消</button>
              </div>
            </td>
          </tr>
        </template>
        <tr v-if="!rows.length"><td :colspan="cols()" class="empty">{{ loading ? '正在加载…' : empty }}</td></tr>
      </tbody>
    </table>
  </div>
</template>
