<script setup>
// 图表面板：一块面板里三栏，按身份换内容，纯 SVG / CSS，不引图表库。
//   employee：额度条 + 我今年请假构成（环形图）+ 近 6 个月请假（柱状图）；
//   approver：待我审批等了多久（分档条）+ 团队 14 天每日不在岗（堆叠柱）+ 团队请假类型（环形图）；
//   company ：各部门本月请假（含人均）+ 全公司 14 天（堆叠柱）+ 请假类型（环形图）；
//   dept    ：人事 / 领导点进某个部门后，同 approver 的三栏，只统计这个部门。
// 数据都由服务端按身份范围算好，这里只画；员工的 personal 里没有任何同事的数据。
import { computed } from 'vue';
import { hoursByKind, monthBars, quotaRows, topDepartments, totalHours, waitBuckets } from '../../lib/attendanceCharts.js';
import AttendanceDayStack from './AttendanceDayStack.vue';
import AttendanceDonut from './AttendanceDonut.vue';

const props = defineProps({
  kind: { type: String, required: true },
  home: { type: Object, default: null },
  personal: { type: Object, default: null },
  // 团队 / 部门 / 全公司的统计：{days, month: {hours, per_capita, by_kind}, ...}
  stats: { type: Object, default: null },
  departments: { type: Array, default: () => [] },
  reviewRows: { type: Array, default: () => [] },
  now: { type: Number, default: () => Date.now() },
  scopeLabel: { type: String, default: '' },
});

const quota = computed(() => quotaRows(props.home));
const yearItems = computed(() => hoursByKind(props.personal?.year_by_kind));
const months = computed(() => monthBars(props.personal?.months));
const teamItems = computed(() => hoursByKind(props.stats?.month?.by_kind));
const wait = computed(() => waitBuckets(props.reviewRows, props.now));
const waitMax = computed(() => Math.max(1, ...wait.value.buckets.map((item) => item.count)));
const ranked = computed(() => topDepartments(props.departments));
const deptMax = computed(() => Math.max(1, ...ranked.value.map((item) => item.month_hours)));
const waitColors = ['k-annual', 'k-ot', 'k-sick'];
const round = (value) => Math.round(value * 10) / 10;
</script>

<template>
  <section class="ac-panel ac-charts" aria-label="图表">
    <template v-if="kind === 'employee'">
      <div class="ac-cc">
        <h3>我的额度<span>{{ personal?.year || '' }} 年</span></h3>
        <div v-if="quota.length" class="ac-quota">
          <div v-for="row in quota" :key="row.key" class="row">
            <div><span>{{ row.label }}</span><b>{{ row.right }}</b></div>
            <div v-if="row.bar" class="ac-bar2"><i v-for="(piece, index) in row.bar" :key="index" :class="['k-' + row.kind, { faded: piece.faded }]" :style="{ width: piece.pct + '%' }"></i></div>
            <div v-else class="ac-note">{{ row.note }}</div>
          </div>
        </div>
        <div v-else class="ac-note">暂无额度信息</div>
      </div>
      <div class="ac-cc">
        <h3>我今年的请假构成<span>共 {{ round(totalHours(yearItems)) }} 小时</span></h3>
        <AttendanceDonut v-if="yearItems.length" :items="yearItems" label="我今年的请假构成" />
        <div v-else class="ac-note">今年还没有请假记录</div>
      </div>
      <div class="ac-cc">
        <h3>近 6 个月请假<span>小时</span></h3>
        <div class="ac-cols"><div v-for="item in months" :key="item.period" class="d" :title="item.label + ' ' + item.hours + ' 小时'"><i class="k-personal" :style="{ height: item.height + 'px' }"></i></div></div>
        <div class="ac-axis"><span v-for="item in months" :key="item.period">{{ item.label }}<br /><b>{{ item.hours }}</b></span></div>
      </div>
    </template>

    <template v-else>
      <div v-if="kind === 'company'" class="ac-cc">
        <h3>各部门本月请假<span>小时 · 人均</span></h3>
        <div class="ac-hb">
          <div v-for="item in ranked" :key="item.department" class="r">
            <span :title="item.label">{{ item.label }}</span>
            <div class="t"><i class="k-personal" :style="{ width: item.month_hours / deptMax * 100 + '%' }"></i></div>
            <span><b>{{ item.month_hours }}</b> <span class="ac-note">{{ item.per_capita }}</span></span>
          </div>
        </div>
        <div v-if="departments.length > ranked.length" class="ac-note">只列本月请假最多的 {{ ranked.length }} 个部门，全部在下面的部门概况里</div>
      </div>
      <div v-else class="ac-cc">
        <h3>{{ kind === 'dept' ? '这个部门待审批等了多久' : '待我审批等了多久' }}<span>平均 {{ wait.average }} 天</span></h3>
        <div class="ac-hb">
          <div v-for="(bucket, index) in wait.buckets" :key="bucket.key" class="r">
            <span>{{ bucket.label }}</span>
            <div class="t"><i :class="waitColors[index]" :style="{ width: bucket.count / waitMax * 100 + '%' }"></i></div>
            <span><b>{{ bucket.count }}</b> 张</span>
          </div>
        </div>
        <div class="ac-note">{{ wait.late ? `有 ${wait.late} 张超过 3 天，建议优先处理` : '没有超过 3 天的' }}</div>
      </div>
      <div class="ac-cc">
        <h3>{{ scopeLabel }} 14 天<span>每天不在岗的人数</span></h3>
        <AttendanceDayStack :days="stats?.days || []" />
      </div>
      <div class="ac-cc">
        <h3>{{ scopeLabel }}本月请假类型<span>共 {{ round(totalHours(teamItems)) }} 小时</span></h3>
        <AttendanceDonut v-if="teamItems.length" :items="teamItems" label="本月请假类型" />
        <div v-else class="ac-note">本月还没有请假</div>
      </div>
    </template>
  </section>
</template>
