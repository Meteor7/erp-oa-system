<script setup>
// 图表块：bars 横条 / cols 竖柱 / stack 堆叠条 / list 列表 / calendar 团队日历（行 = 人，列 = 天），纯 CSS，不用 echarts。
// 块自己出错时（block.error）只显示"这一块暂时加载失败"，不影响别的块。
import { computed } from 'vue';
import { EMPTY_BLOCK_TEXT } from '../../lib/dashboardView.js';
import { targetHint } from '../../lib/dashboardTargets.js';

const props = defineProps({
  block: { type: Object, required: true },
  resolve: { type: Function, required: true },
});
const emit = defineEmits(['go']);

const link = computed(() => props.resolve(props.block.target));
const stackSegments = computed(() => props.block.rows.filter((row) => row.width > 0));
</script>

<template>
  <section class="db-card db-block" :class="{ 'is-failed': block.failed, 'is-wide': block.wide }" :data-block="block.key" :aria-label="block.title">
    <div class="db-hd db-hd-block">
      <h2>{{ block.title }}</h2>
      <span v-if="block.sub" class="db-mut">{{ block.sub }}</span>
      <span v-if="block.hint" class="db-q" role="img" :aria-label="block.hint" :title="block.hint">?</span>
      <button v-if="link.state === 'link'" type="button" class="db-link" @click="emit('go', link.to)">{{ block.more || '查看' }} →</button>
      <span v-else-if="link.state !== 'none'" class="db-mut db-off-link" :title="targetHint(link.state)">{{ block.more || '查看' }}</span>
    </div>

    <p v-if="block.failed" class="db-empty db-failed">{{ block.failedText }}</p>
    <p v-else-if="block.empty" class="db-empty">{{ EMPTY_BLOCK_TEXT }}</p>

    <div v-else-if="block.type === 'bars'" class="db-bars">
      <div v-for="(row, index) in block.rows" :key="index" class="db-br">
        <span class="db-br-n" :title="row.label">{{ row.label }}</span>
        <span class="db-trk" aria-hidden="true"><i :class="row.toneClass" :style="{ width: row.width + '%' }"></i></span>
        <span class="db-br-v">{{ row.value }}</span>
      </div>
    </div>

    <div v-else-if="block.type === 'cols'" class="db-cols">
      <div v-for="(row, index) in block.rows" :key="index" class="db-cl" :class="{ last: row.last }">
        <span class="db-cl-v">{{ row.value }}</span>
        <i aria-hidden="true" :style="{ height: row.height + '%' }"></i>
        <span class="db-cl-n" :title="row.label">{{ row.label }}</span>
      </div>
    </div>

    <div v-else-if="block.type === 'stack'" class="db-stackwrap">
      <div class="db-stack" aria-hidden="true"><i v-for="(row, index) in stackSegments" :key="index" :style="{ width: row.width + '%', background: row.color }"></i></div>
      <ul class="db-lg">
        <li v-for="(row, index) in block.rows" :key="index"><em :style="{ background: row.color }"></em>{{ row.label }} <b>{{ row.value }}</b></li>
      </ul>
    </div>

    <div v-else-if="block.type === 'calendar'" class="db-calbox">
      <div class="db-calwrap">
        <div class="db-cal" :style="{ '--cols': block.calendar.days.length }" role="table" :aria-label="block.title">
          <span></span>
          <div v-for="(day, index) in block.calendar.days" :key="day.date" class="db-cal-h" :class="{ we: day.off, t0: index === 0 }">{{ day.weekday }}<b>{{ day.day }}</b></div>
          <template v-for="person in block.calendar.people" :key="person.name">
            <span class="db-cal-n" :title="person.name">{{ person.name }}</span>
            <i v-for="(cell, index) in person.cells" :key="index" class="db-cal-c" :class="[cell ? `k-${cell.kind}` : '', { we: block.calendar.days[index].off, pend: cell && cell.pending }]" :title="cell ? cell.title : undefined"></i>
          </template>
          <span class="db-cal-l">在岗人数</span>
          <b v-for="(total, index) in block.calendar.totals" :key="index" class="db-cal-s" :class="[total.level ? `is-${total.level}` : '', { we: total.present === null }]" :title="total.title">{{ total.present === null ? '—' : total.present }}</b>
        </div>
      </div>
      <ul class="db-lg db-cal-lg">
        <li v-for="item in block.calendar.legend" :key="item.kind"><em :class="`k-${item.kind}`"></em>{{ item.label }}</li>
        <li class="db-mut">下方数字 = 当天在岗人数（共 {{ block.calendar.headcount }} 人）；<b class="is-low-t">红</b> 缺 4 人以上或占 40%，<b class="is-mid-t">橙</b> 缺 3 人以上</li>
      </ul>
    </div>

    <ul v-else-if="block.type === 'list'" class="db-lrows">
      <li v-for="(row, index) in block.rows" :key="index">
        <component :is="resolve(row.target).state === 'link' ? 'button' : 'div'" class="db-lr"
          :class="{ 'is-link': resolve(row.target).state === 'link', 'is-off': ['denied', 'unknown'].includes(resolve(row.target).state) }"
          :type="resolve(row.target).state === 'link' ? 'button' : undefined"
          :title="targetHint(resolve(row.target).state) || undefined"
          @click="resolve(row.target).state === 'link' && emit('go', resolve(row.target).to)">
          <span class="db-lr-main">{{ row.label }}<span v-if="row.sub" class="db-mut"> {{ row.sub }}</span></span>
          <span v-if="row.value" class="db-tag" :class="row.toneClass">{{ row.value }}</span>
        </component>
      </li>
    </ul>
  </section>
</template>
