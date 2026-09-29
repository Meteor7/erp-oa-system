<script setup>
// 待我审批：三类申请放在一起，批之前就能看到影响（额度、月度上限、同期缺勤）；上面是本部门未来两周谁不在。
import { reactive, ref } from 'vue';
import { HOURS_PER_DAY, TYPES, api, dayLabel, departmentLabel, numText, rangeText, teamBars, typeBadge } from '../../lib/attendanceView.js';

const props = defineProps({
  data: { type: Object, default: () => ({ items: [], team: [] }) },
});
const emit = defineEmits(['acted']);

const state = reactive({});
const error = ref('');

function of(row) {
  if (!state[row.name]) state[row.name] = { rejecting: false, note: '', target: row.rejection_targets?.[0]?.target || 'applicant', busy: false, result: '' };
  return state[row.name];
}

function daysText(row) {
  const hours = Number(row.duration_hours || 0);
  return row.request_type === '加班申请' ? `${numText(hours)} 小时` : `${numText(hours / HOURS_PER_DAY)} 天 · ${numText(hours)} 小时`;
}

async function act(row, action) {
  const item = of(row);
  error.value = '';
  if (action === 'reject' && !item.note.trim()) {
    error.value = '驳回原因必填';
    return;
  }
  item.busy = true;
  try {
    const params = { name: row.name, action, note: item.note.trim() };
    if (action === 'reject') params.reject_target = item.target || 'applicant';
    await api.act(params);
    item.result = action === 'approve' ? 'ok' : 'no';
    item.rejecting = false;
    emit('acted', row.name);
  } catch (failure) {
    error.value = String(failure?.message || failure || '处理失败');
  } finally {
    item.busy = false;
  }
}

const detailPath = (row) => `${TYPES[row.request_type]?.path || '/approval/leave'}/${encodeURIComponent(row.name)}`;
</script>

<template>
  <div>
    <section v-for="team in data.team" :key="team.department" class="at-panel at-team" style="margin-bottom:14px" :aria-label="`${team.department}未来两周谁不在`">
      <div class="at-label">
        <h4>{{ team.department }} · 未来两周谁不在</h4>
        <div class="at-legend">
          <span><i style="background:#FF8F00"></i>已通过</span>
          <span><i style="background:repeating-linear-gradient(45deg,#FF8F00 0 3px,#fff 3px 6px);border:1px solid #FF8F00;box-sizing:border-box"></i>审批中</span>
          <span>部门 {{ team.headcount }} 人</span>
        </div>
      </div>
      <div class="at-bars">
        <div v-for="day in teamBars(team)" :key="day.date" class="at-bar" :class="{ off: day.off_day, crowded: day.crowded }" :title="[...day.approved, ...day.pending].join('、')">
          <div class="c">{{ day.label }}</div>
          <div class="col"><i v-for="name in day.pending" :key="'p' + name" class="pending"></i><i v-for="name in day.approved" :key="'a' + name"></i></div>
          <div class="date" :style="{ color: day.off_day ? '#8A919C' : '' }">{{ day.date.slice(5).replace('-', '/') }}</div>
          <div class="wd">周{{ day.weekday }}</div>
        </div>
      </div>
      <div v-if="team.note" class="at-sub">{{ team.note }}</div>
    </section>

    <section class="at-panel" aria-label="待我审批">
      <div class="at-label"><h4>待我审批</h4><span class="at-sub">最早提交的在前</span></div>
      <div v-if="!data.items.length" class="empty">没有需要你审批的请假、加班、调休。</div>
      <div v-if="error" class="err" role="alert">{{ error }}</div>
      <div v-for="row in data.items" :key="row.name" class="at-review" :class="{ done: of(row).result }">
        <span class="at-badge" :class="typeBadge(row).tone">{{ typeBadge(row).text }}</span>
        <div class="who"><b>{{ row.employee_name }}</b><span class="muted">{{ departmentLabel(row.department) }}<template v-if="row.creation"> · 提交于 {{ dayLabel(String(row.creation).slice(0, 10)) }}</template></span></div>
        <div class="when"><b class="num">{{ daysText(row) }}</b><div class="muted num">{{ rangeText(row.from_date, row.to_date) }}</div></div>
        <div class="why">
          <div>{{ row.reason || '（没有写事由）' }}</div>
          <div class="hints"><span v-for="hint in row.hints" :key="hint.text" class="at-hint" :class="hint.tone">{{ hint.text }}</span></div>
        </div>
        <div v-if="of(row).result" class="pill" :class="of(row).result === 'ok' ? 'p-jade' : 'p-red'">{{ of(row).result === 'ok' ? '已通过，转给下一步' : '已驳回' }}</div>
        <div v-else style="display:flex;gap:8px;flex-shrink:0">
          <router-link class="btn" :to="detailPath(row)">详情</router-link>
          <button type="button" class="btn" :disabled="of(row).busy" @click="of(row).rejecting = !of(row).rejecting">驳回</button>
          <button type="button" class="btn pri" :disabled="of(row).busy" @click="act(row, 'approve')">通过</button>
        </div>
        <div v-if="of(row).rejecting && !of(row).result" class="at-reject">
          <textarea v-model="of(row).note" placeholder="驳回原因（必填），申请人会看到" aria-label="驳回原因"></textarea>
          <select v-if="row.rejection_targets?.length" v-model="of(row).target" aria-label="驳回给谁">
            <option v-for="target in row.rejection_targets" :key="target.target" :value="target.target">驳回至：{{ target.label }}</option>
          </select>
          <button type="button" class="btn danger" :disabled="of(row).busy" @click="act(row, 'reject')">确认驳回</button>
        </div>
      </div>
      <div v-if="data.items.length" class="at-sub">通过时意见可以不填；驳回必须写原因，申请人会看到。</div>
    </section>
  </div>
</template>
