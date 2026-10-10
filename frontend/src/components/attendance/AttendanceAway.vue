<script setup>
// 进入某个部门后（人事 / 领导）：近 5 天不在岗的人。名字来自服务端已校验范围的部门明细。
import { avatarKind, kindLabel } from '../../lib/attendanceCharts.js';
import { personShort } from '../../lib/attendanceView.js';

defineProps({
  rows: { type: Array, default: () => [] },
});
</script>

<template>
  <section class="ac-panel" aria-label="近 5 天不在岗">
    <div class="ac-hd"><h2>近 5 天不在岗</h2><span class="ac-cnt">{{ rows.length }}</span></div>
    <div v-if="!rows.length" class="ac-empty">近 5 天全员在岗</div>
    <div v-for="item in rows" :key="item.id" class="ac-p">
      <span :class="['ac-av', avatarKind(item.name)]">{{ personShort(item.name) }}</span>
      <b>{{ item.name }}</b>
      <span><span v-for="kind in item.kinds" :key="kind" :class="['ac-tag', kind]" style="margin-right: 4px">{{ kindLabel(kind) }}</span><span class="ac-note">{{ item.days }} 天</span></span>
    </div>
  </section>
</template>
