<script setup>
// 我的申请 · 进行中：卡在哪一步、已等多久；草稿可以继续填写，审批中的可以撤回。审批人放在右栏，只有申请的人放在主栏。
import { computed } from 'vue';
import { kindOf, mineSummary, requestTitle, sizeText, statusTag, stepTracker, submittedText, waitText } from '../../lib/attendanceView.js';

const props = defineProps({
  mine: { type: Object, required: true },
  loaded: { type: Boolean, default: false },
  now: { type: Number, default: () => Date.now() },
  busy: { type: Boolean, default: false },
});
const emit = defineEmits(['list', 'open', 'withdraw', 'continue']);

const info = computed(() => mineSummary(props.mine.items));
const rows = computed(() => info.value.activeRows.slice(0, 3));
</script>

<template>
  <section class="panel flush" aria-label="我的申请">
    <div class="at-hd">
      <b>我的申请 · 进行中</b><span class="at-cnt cobalt">{{ info.active }}</span>
      <button type="button" class="link at-right" @click="emit('list', 'mine', 'all')">全部 {{ info.total }} 张 →</button>
    </div>
    <div v-if="!loaded" class="empty">正在加载…</div>
    <div v-else-if="!rows.length" class="empty">没有进行中的申请</div>
    <div v-for="row in rows" :key="row.name" class="at-item" role="button" tabindex="0" @click="emit('open', row)" @keydown.enter="emit('open', row)">
      <span :class="['at-av', 'kind', kindOf(row).tone]">{{ kindOf(row).label }}</span>
      <div class="at-main">
        <div class="at-line"><b>{{ requestTitle(row) }}</b><span :class="['at-tag', statusTag(row).tone]">{{ statusTag(row).text }}</span></div>
        <div v-if="row.workflow_status !== '草稿'" class="at-steps">
          <span v-for="(step, index) in stepTracker(row, mine.names)" :key="index" :class="['at-st', step.cls]"><i>{{ step.mark }}</i>{{ step.text }}</span>
        </div>
        <div class="muted">{{ sizeText(row) }} · {{ submittedText(row) }}<template v-if="waitText(row, now) && row.workflow_status !== '草稿'"> · 已等 {{ waitText(row, now) }}</template></div>
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
</template>
