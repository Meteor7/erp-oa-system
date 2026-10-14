<script setup>
// 「N 月」概览（2026-10-14 按确认的 demo，替换原来的图表面板）：四个页签 请假 / 调休 / 加班 / 出差，各写这个月的合计天数
// （一位小数，和数据看板的“本月请假 / 本月加班 / 另有调休”同一个数）。下面两张能点的横条图：
//   全公司：按部门 + 构成；部门 / 团队：构成 + 按周（加班、调休的构成本来就是按周，只放这一张）。
//   构成：请假按假别，出差按去哪里，加班 / 调休按哪一周。最多 6 条，其余的“其余 N 个”。
// 两张图互相筛（选了部门，构成图只算这个部门，反过来也一样；选中的高亮，其余变淡），下面的明细跟着所有选择，一张申请一行，
// 超过 8 行折叠，点一行进那张申请。只算已批准的。没有“最多的人”排行（用户不要）。
import { computed, reactive, ref, watch } from 'vue';
import { BAR_LIMIT, fold, kindText, lengthText, monthTitle, overviewView, spanText, statusOf } from '../../lib/attendanceHome.js';

const props = defineProps({
  rows: { type: Array, default: () => [] },
  month: { type: String, default: '' },
  today: { type: String, default: '' },
  metric: { type: String, default: 'leave' },
  // 图上点选的：{dept, part, week}（都在地址里）。
  sel: { type: Object, default: () => ({}) },
  // 全公司（有“按部门”）还是部门 / 团队（有“按周”）。
  company: { type: Boolean, default: true },
  showDept: { type: Boolean, default: true },
});
const emit = defineEmits(['metric', 'select', 'clear', 'month', 'open']);

const view = computed(() => overviewView(props.rows, { metric: props.metric, month: props.month, company: props.company, sel: props.sel }));
const title = computed(() => monthTitle(props.month, props.today) || '本月');
const current = computed(() => !props.month || !props.today || props.month === props.today.slice(0, 7));
const listOpen = ref(false);
const barsOpen = reactive({});
const listed = computed(() => fold(view.value.list, listOpen.value));

function bars(chart) {
  return fold(chart.items, Boolean(barsOpen[chart.key]), BAR_LIMIT);
}

function pick(chart, key) {
  emit('select', chart.field, chart.selected === key ? '' : key);
}

watch(() => [props.metric, props.month, props.sel?.dept, props.sel?.part, props.sel?.week], () => { listOpen.value = false; });
watch(() => [props.metric, props.month], () => { Object.keys(barsOpen).forEach((key) => { barsOpen[key] = false; }); });
</script>

<template>
  <section id="ac-month" class="ac-panel" aria-label="月概览">
    <div class="ac-hd">
      <h2>{{ title }}</h2><span class="ac-note">已批准 · 和数据看板同一个数 · 点任何一条看是谁</span>
      <button v-if="!current" type="button" class="ac-link ac-right" @click="emit('month', '')">回到本月</button>
    </div>
    <div class="ac-body">
      <div class="ac-mts">
        <button v-for="tab in view.tabs" :key="tab.key" type="button" :class="['ac-mt', tab.key, { on: tab.on }]" :aria-pressed="tab.on" @click="emit('metric', tab.key)">
          <span>{{ tab.label }}</span><b>{{ tab.days }}<small>天</small></b>
        </button>
      </div>

      <div :class="['ac-ovg', { one: view.charts.length === 1 }]">
        <div v-for="chart in view.charts" :key="chart.key" class="ac-ovc">
          <h3>{{ chart.title }}<span>天</span></h3>
          <div v-if="!chart.items.length" class="ac-empty sm">没有</div>
          <template v-else>
            <div class="ac-hbars">
              <button
                v-for="item in bars(chart).shown" :key="item.key" type="button"
                :class="['ac-hbr', { on: chart.selected === item.key, off: chart.selected && chart.selected !== item.key }]" :aria-pressed="chart.selected === item.key"
                @click="pick(chart, item.key)">
                <span class="l" :title="item.label">{{ item.label }}</span>
                <span class="t"><i :class="'k-' + item.color" :style="{ width: item.pct + '%' }"></i></span>
                <span class="v">{{ item.days }}</span>
              </button>
            </div>
            <button v-if="bars(chart).rest" type="button" class="ac-more" @click="barsOpen[chart.key] = !barsOpen[chart.key]">
              {{ barsOpen[chart.key] ? '收起' : `其余 ${bars(chart).rest} 个` }}
            </button>
          </template>
        </div>
      </div>

      <div class="ac-ovl">
        <div class="ac-ovlh">
          <h3>明细</h3>
          <button v-for="chip in view.chips" :key="chip.field" type="button" class="ac-fchip" :title="'去掉“' + chip.label + '”这个筛选'" @click="emit('select', chip.field, '')">{{ chip.label }} ✕</button>
          <span class="ac-note">{{ view.list.length }} 张 · {{ view.listDays }} 天</span>
          <button v-if="view.chips.length" type="button" class="ac-link ac-right" @click="emit('clear')">清除筛选</button>
        </div>
        <div v-if="!view.list.length" class="ac-empty sm">没有</div>
        <template v-else>
          <div class="ac-tblwrap">
            <table class="ac-t">
              <thead><tr><th>姓名</th><th v-if="showDept">部门</th><th>类型</th><th>日期</th><th class="n">本月</th><th></th><th></th></tr></thead>
              <tbody>
                <tr
                  v-for="row in listed.shown" :key="row.name" class="go" tabindex="0" role="link" :aria-label="'打开 ' + row.employee_name + ' 的' + kindText(row) + '申请'"
                  @click="emit('open', row)" @keydown.enter="emit('open', row)">
                  <td><b>{{ row.employee_name }}</b></td>
                  <td v-if="showDept">{{ row.department_label }}</td>
                  <td><span :class="['ac-tag', row.kind]">{{ kindText(row) }}</span></td>
                  <td class="dt">{{ spanText(row.from_date, row.to_date) }}<span v-if="row.travel_destination" class="ac-note"> {{ row.travel_destination }}</span></td>
                  <td class="n">{{ lengthText(row, row.month_hours) }}</td>
                  <td><span v-if="statusOf(row)" :class="['ac-st', statusOf(row).tone]">{{ statusOf(row).text }}</span></td>
                  <td class="ac-go">›</td>
                </tr>
              </tbody>
            </table>
          </div>
          <button v-if="listed.rest" type="button" class="ac-more" :aria-expanded="listOpen" @click="listOpen = !listOpen">{{ listOpen ? '收起' : `展开其余 ${listed.rest} 条` }}</button>
        </template>
      </div>
    </div>
  </section>
</template>
