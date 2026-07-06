<script setup>
import { computed } from "vue";
import { useRoute } from "vue-router";
import { canSee, currentUser, roleLabel } from "./lib/access";

const groups = [
  { label: "总览", items: [{ to: "/dashboard", step: "", label: "数据看板" }] },
  { label: "人事中心", items: [
    { to: "/personnel", step: "01", label: "人事信息管理" },
    { to: "/accommodation", step: "02", label: "宿舍住宿费用" },
  ] },
  { label: "研发台账", items: [
    { to: "/projects", step: "03", label: "项目管理" },
    { to: "/entry", step: "04", label: "研发工时填报" },
    { to: "/timesheet", step: "05", label: "研发工时表" },
    { to: "/expense", step: "06", label: "财务费用导入" },
    { to: "/allocation", step: "07", label: "研发费用分摊表" },
  ] },
];

const route = useRoute();
const visibleGroups = computed(() =>
  groups
    .map((g) => ({ ...g, items: g.items.filter((n) => canSee(n.to)) }))
    .filter((g) => g.items.length)
);
const allowed = computed(() => canSee(route.path));

function logout() {
  window.location.href = "/?cmd=web_logout";
}
</script>
<template>
  <div class="flex min-h-screen bg-gray-50 text-gray-900">
    <aside class="w-60 bg-gray-900 text-gray-300 flex flex-col">
      <div class="px-5 py-5 border-b border-white/10">
        <div class="text-white font-semibold">研发成本管理</div>
        <div class="text-xs text-gray-500 mt-1">Rayher · frappe-ui</div>
      </div>
      <nav class="p-3 flex-1 overflow-y-auto">
        <div v-for="g in visibleGroups" :key="g.label" class="mb-3">
          <div class="px-3 py-1.5 text-[10px] uppercase tracking-wider text-gray-500 font-semibold">{{ g.label }}</div>
          <router-link v-for="n in g.items" :key="n.to" :to="n.to"
            class="flex items-center gap-2 px-3 py-2 rounded-md text-sm hover:bg-white/5"
            active-class="bg-white/10 text-white">
            <span class="w-5 text-[10px] text-gray-500 text-center">{{ n.step }}</span>{{ n.label }}
          </router-link>
        </div>
      </nav>
    </aside>
    <main class="flex-1 min-w-0 flex flex-col">
      <header class="h-14 bg-white border-b flex items-center px-6 gap-4">
        <div class="text-sm text-gray-500 flex-1">&#x7814;&#x53d1;&#x6210;&#x672c;&#x4e00;&#x4f53;&#x5316; &middot; &#x4eba;&#x4e8b; / &#x5de5;&#x65f6; / &#x8d39;&#x7528; / &#x85aa;&#x916c;</div>
        <div class="flex items-center gap-3 text-sm">
          <span class="inline-flex items-center rounded border border-gray-200 bg-gray-50 px-2 py-1 text-gray-700">{{ roleLabel() }}</span>
          <span class="text-gray-600 max-w-[220px] truncate">{{ currentUser() }}</span>
          <button type="button" class="rounded border border-gray-300 px-3 py-1.5 text-gray-700 hover:bg-gray-50" @click="logout">&#x9000;&#x51fa;&#x767b;&#x5f55;</button>
        </div>
      </header>
      <div class="p-7 max-w-6xl w-full mx-auto flex-1">
        <router-view v-if="allowed" />
        <div v-else class="flex flex-col items-center justify-center py-24 text-center">
          <div class="text-4xl mb-3">🔒</div>
          <div class="text-gray-700 font-medium">您没有访问该页面的权限</div>
          <div class="text-gray-400 text-sm mt-1">该模块仅对授权岗位开放，请联系系统管理员。</div>
        </div>
      </div>
    </main>
  </div>
</template>
