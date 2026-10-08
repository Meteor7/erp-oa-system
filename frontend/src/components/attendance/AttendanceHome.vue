<script setup>
// 考勤中心首页：额度和待办一眼看到（年假 / 调休 / 我的申请 / 待我审批），待我审批的可以直接同意、驳回要进详情写原因，
// 我的申请看到卡在哪一步；右边是我的月历和本部门这两周谁不在（请假和调休，只显示日期）。
import { computed, ref } from 'vue';
import {
  TYPES, balanceKpis, byWait, canQuickApprove, effectLine, filterRows, kindOf, mineSummary, numText, personShort, requestTitle,
  returnedDrafts, rejectionOf, rowChips, statusTag, stepTracker, submittedText, teamAbsences, totalOf, typeChips, typeCounts, waitText,
} from '../../lib/attendanceView.js';
import AttendanceCalendar from './AttendanceCalendar.vue';

const props = defineProps({
  home: { type: Object, default: null },
  mine: { type: Object, required: true },
  review: { type: Object, required: true },
  loaded: { type: Object, required: true },
  now: { type: Number, default: () => Date.now() },
  busy: { type: Boolean, default: false },
  hasEmployee: { type: Boolean, default: false },
  isApprover: { type: Boolean, default: false },
  availableTypes: { type: Array, default: () => [] },
  period: { type: String, required: true },
  noEmployeeText: { type: String, default: '' },
});
const emit = defineEmits(['new', 'list', 'open', 'approve', 'reject', 'withdraw', 'continue', 'period']);

const chip = ref('all');
const kpi = computed(() => balanceKpis(props.home));
const counts = computed(() => typeCounts(props.review.items));
const chips = computed(() => typeChips(counts.value, chip.value, true));
const todoRows = computed(() => byWait(filterRows(props.review.items, chip.value), props.now).slice(0, 3));
const mineInfo = computed(() => mineSummary(props.mine.items));
const mineRows = computed(() => mineInfo.value.activeRows.slice(0, 3));
const returned = computed(() => returnedDrafts(props.mine.items));
const longest = computed(() => {
  const days = props.review.items.map((row) => waitText(row, props.now)).filter((text) => text.endsWith('天')).map((text) => parseInt(text, 10));
  return days.length ? Math.max(...days) : 0;
});
const todoHint = computed(() => {
  if (!props.review.items.length) return '全部处理完了';
  return longest.value ? `最久等了 ${longest.value} 天 · 现在处理 →` : '现在处理 →';
});
const absences = computed(() => (props.review.team || []).map((team) => ({ department: team.department, headcount: team.headcount, people: teamAbsences(team) })));

function rejectionText(row) {
  const rejection = rejectionOf(row);
  const who = props.mine.names[String(rejection?.actor || '').toLowerCase()] || String(rejection?.actor || '').split('@')[0];
  return `${who ? `${who}：` : ''}${rejection?.note || '请修改后重新提交'}`;
}
</script>

<template>
  <div class="at-page">
    <div class="ph">
      <div>
        <div class="crumb">审批中心</div>
        <h3>请假 · 加班 · 调休</h3>
        <div class="muted">看额度、批申请、跟进度都在这里；新建申请在单独的页面里填。</div>
      </div>
      <div v-if="hasEmployee" class="head-actions">
        <button v-for="(type, index) in availableTypes" :key="type" type="button" :class="['btn', { pri: index === 0 }]" @click="emit('new', TYPES[type].label)">＋ 新建{{ TYPES[type].label }}</button>
      </div>
    </div>

    <div v-if="loaded.home && home && !hasEmployee" class="banner err">{{ noEmployeeText }}</div>

    <section v-for="row in returned" :key="row.name" class="at-returned" aria-label="被退回的申请">
      <b>{{ row.subject || requestTitle(row) }}（{{ row.name }}）被退回了</b>
      <span class="grow-col">{{ rejectionText(row) }}</span>
      <button type="button" class="btn pri sm" @click="emit('continue', row)">修改后重新提交</button>
    </section>

    <div class="at-kpis">
      <template v-if="hasEmployee">
        <button type="button" class="at-kpi" @click="emit('list', 'mine', '请假')">
          <span class="l">年假可用</span>
          <span v-if="kpi.annual" class="v">{{ kpi.annual.days }}<small>天 · {{ kpi.annual.hours }} 小时</small></span>
          <span v-else class="v">—</span>
          <span class="s">{{ kpi.annual ? `已用 ${kpi.annual.used} 小时` : '暂无年假信息' }}</span>
        </button>
        <button type="button" class="at-kpi" @click="emit('list', 'mine', '调休')">
          <span class="l">调休可用</span>
          <span v-if="kpi.comp" class="v">{{ kpi.comp.hours }}<small>小时</small></span>
          <span v-else class="v">—</span>
          <span class="s">{{ kpi.comp ? `累计加班 ${kpi.comp.credit} 小时` : '暂无调休信息' }}</span>
        </button>
      </template>
      <button type="button" class="at-kpi" @click="emit('list', 'mine', 'all')">
        <span class="l">我的申请</span>
        <span class="v">{{ mineInfo.total }}<small>张</small></span>
        <span class="s">其中进行中 {{ mineInfo.active }} 张</span>
      </button>
      <button v-if="isApprover" type="button" class="at-kpi hot" @click="emit('list', 'todo', 'all')">
        <span class="l">待我审批</span>
        <span class="v">{{ review.items.length }}<small>张</small></span>
        <span class="s">{{ todoHint }}</span>
      </button>
    </div>

    <div class="at-grid2">
      <div class="at-col">
        <section v-if="isApprover" class="panel flush" aria-label="待我审批">
          <div class="at-hd">
            <b>待我审批</b><span class="at-cnt">{{ review.items.length }}</span>
            <span class="at-chips" role="group" aria-label="按类型筛选">
              <button v-for="item in chips" :key="item.key" type="button" :class="['chip', { on: item.on }]" :aria-pressed="item.on" @click="chip = item.key">{{ item.label }}</button>
            </span>
            <button type="button" class="link at-right" @click="emit('list', 'todo', chip)">全部 →</button>
          </div>
          <div v-if="!loaded.review" class="empty">正在加载…</div>
          <div v-else-if="!todoRows.length" class="empty">没有需要你审批的申请（到“我审批过的”里可以看处理记录）</div>
          <div v-for="row in todoRows" :key="row.name" class="at-item" role="button" tabindex="0" @click="emit('open', row)" @keydown.enter="emit('open', row)">
            <span class="at-av">{{ personShort(row.employee_name) }}</span>
            <div class="at-main">
              <div class="at-line">
                <b>{{ row.employee_name }}</b><span class="muted">{{ row.department }}</span>
                <span :class="['at-tag', kindOf(row).tone]">{{ kindOf(row).text }}</span>
                <span v-if="waitText(row, now)" class="at-tag warn">等你 {{ waitText(row, now) }}</span>
              </div>
              <div class="at-dchips">
                <span v-for="day in rowChips(row, 4).chips" :key="day.date + day.text" :class="['at-dchip', day.mode]">{{ day.text }}</span>
                <span v-if="rowChips(row, 4).more" class="at-dchip">… 共 {{ rowChips(row).chips.length }} 天</span>
              </div>
              <div class="muted">合计 {{ numText(totalOf(row)) }} 小时 · {{ effectLine(row) }}</div>
            </div>
            <div class="at-acts">
              <button type="button" class="btn sm danger" :disabled="busy" @click.stop="emit('reject', row)">驳回</button>
              <button v-if="canQuickApprove(row)" type="button" class="btn sm pri" :disabled="busy" @click.stop="emit('approve', row)">同意</button>
              <button v-else type="button" class="btn sm" @click.stop="emit('open', row)">去详情处理</button>
            </div>
          </div>
        </section>

        <section class="panel flush" aria-label="我的申请">
          <div class="at-hd">
            <b>我的申请 · 进行中</b><span class="at-cnt cobalt">{{ mineInfo.active }}</span>
            <button type="button" class="link at-right" @click="emit('list', 'mine', 'all')">全部 {{ mineInfo.total }} 张 →</button>
          </div>
          <div v-if="!loaded.mine" class="empty">正在加载…</div>
          <div v-else-if="!mineRows.length" class="empty">没有进行中的申请</div>
          <div v-for="row in mineRows" :key="row.name" class="at-item" role="button" tabindex="0" @click="emit('open', row)" @keydown.enter="emit('open', row)">
            <span :class="['at-av', 'kind', kindOf(row).tone]">{{ kindOf(row).label }}</span>
            <div class="at-main">
              <div class="at-line"><b>{{ requestTitle(row) }}</b><span :class="['at-tag', statusTag(row).tone]">{{ statusTag(row).text }}</span></div>
              <div v-if="row.workflow_status !== '草稿'" class="at-steps">
                <span v-for="(step, index) in stepTracker(row, mine.names)" :key="index" :class="['at-st', step.cls]"><i>{{ step.mark }}</i>{{ step.text }}</span>
              </div>
              <div class="muted">{{ numText(totalOf(row)) }} 小时 · {{ submittedText(row) }}<template v-if="waitText(row, now) && row.workflow_status !== '草稿'"> · 已等 {{ waitText(row, now) }}</template></div>
            </div>
            <div class="at-acts">
              <button v-if="row.workflow_status === '草稿'" type="button" class="btn sm pri" @click.stop="emit('continue', row)">继续填写</button>
              <template v-else>
                <button type="button" class="btn sm" @click.stop="emit('open', row)">查看</button>
                <button v-if="row.can_withdraw" type="button" class="btn sm" :disabled="busy" @click.stop="emit('withdraw', row)">撤回</button>
              </template>
            </div>
          </div>
        </section>
      </div>

      <div class="at-col">
        <AttendanceCalendar v-if="hasEmployee" :home="home" :period="period" @period="(value) => emit('period', value)" />
        <section v-if="absences.length" class="panel flush" aria-label="部门这两周谁不在">
          <div class="at-hd"><b>部门这两周谁不在</b></div>
          <template v-for="team in absences" :key="team.department">
            <div v-if="absences.length > 1" class="at-dept">{{ team.department }} · {{ team.headcount }} 人</div>
            <div v-for="person in team.people" :key="person.name" class="at-out"><span>{{ person.name }}</span><span class="muted">{{ person.text }}<template v-if="person.pending">（审批中）</template></span></div>
            <div v-if="!team.people.length" class="at-out"><span class="muted">这两周没有人请假或调休</span></div>
          </template>
          <div class="muted at-foot">请假和调休，不含加班；只显示日期。</div>
        </section>
      </div>
    </div>
  </div>
</template>
