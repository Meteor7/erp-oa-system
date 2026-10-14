<script setup>
// 员工首页的图表面板：一块面板里三栏 —— 额度条 + 我今年请假构成（环形图）+ 近 6 个月请假（柱状图），纯 SVG / CSS，不引图表库。
// 数据由服务端按身份范围算好，这里只画；员工的 personal 里没有任何同事的数据。
// （2026-10-14：部门主管、人事和管理层的首页换成「谁不在」「未来 14 天」「N 月」几块，原来给他们的三栏去掉了，这里只剩员工的。）
import { computed } from 'vue';
import { hoursByKind, monthBars, quotaRows, totalHours } from '../../lib/attendanceCharts.js';
import AttendanceDonut from './AttendanceDonut.vue';

const props = defineProps({
  home: { type: Object, default: null },
  personal: { type: Object, default: null },
});

const quota = computed(() => quotaRows(props.home));
const yearItems = computed(() => hoursByKind(props.personal?.year_by_kind));
const months = computed(() => monthBars(props.personal?.months));
const round = (value) => Math.round(value * 10) / 10;
</script>

<template>
  <section class="ac-panel ac-charts" aria-label="图表">
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
  </section>
</template>
