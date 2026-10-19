<script setup>
import { computed, nextTick, ref } from 'vue';
import { useRouter } from 'vue-router';
import { createResource } from 'frappe-ui';
import AccommodationTabs from '../components/AccommodationTabs.vue';
import { extractFrappeError } from '../lib/frappeError';
import {
  COLORS, STATUS_ORDER, STATUS_STYLE, donutGradient, groupByBuilding, leaseMessage, leaseText,
  money, monthLabel, monthTitle, percent, ratioWidth, roomNote, subjectRows, trendBars, useRows, whole,
} from '../lib/dormitoryBoard';
import { boardEditLocation, useRoomNotice } from '../lib/accommodationRooms.js';
import { FEE_PATH, takeSaved } from '../lib/accommodationFees.js';
import { canEditHr } from '../lib/access.js';

const router = useRouter();
// 总经理、演示员工113经理只读打开：不显示编辑房间、登记费用（服务端也会拒绝）。
const canEdit = canEditHr();
// 在房间内页或费用登记内页保存后回到本页：显示一条"已保存 A-302"，几秒后消失。
const roomNotice = useRoomNotice();
const feeNotice = takeSaved();
const savedNotice = computed(() => roomNotice.value || feeNotice);
const selectedPeriod = ref('');
const filter = ref('全部');
const selectedRoom = ref('');
const detailPanel = ref(null);

const board = createResource({
  url: 'rayher_hr_payroll.api.dormitory_board.get_dormitory_board',
  method: 'GET',
  makeParams: () => (selectedPeriod.value ? { period: selectedPeriod.value } : {}),
  auto: true,
  onSuccess(data) {
    if (!selectedPeriod.value) selectedPeriod.value = data.period;
    if (!data.rooms.some((room) => room.name === selectedRoom.value)) {
      selectedRoom.value = (data.rooms.find((room) => room.status === '空置') || data.rooms[0] || {}).name || '';
    }
  },
});

const data = computed(() => board.data || null);
const cost = computed(() => data.value?.cost || {});
const registered = computed(() => Boolean(cost.value.registered));
const occupancy = computed(() => data.value?.occupancy || {});
const title = computed(() => (data.value ? monthTitle(data.value.period) : ''));
const lease = computed(() => leaseMessage(data.value?.lease_alert, occupancy.value.total));
const leavers = computed(() => data.value?.leavers_in_rooms || []);
const legend = computed(() => STATUS_ORDER.map((status) => ({
  status, label: status === '入住' ? '有人入住' : status, count: occupancy.value[status] || 0, color: STATUS_STYLE[status].dot,
})));
const trendByPeriod = computed(() => Object.fromEntries((data.value?.trend || []).map((month) => [month.period, month])));
const months = computed(() => (data.value?.periods || []).map((period) => ({
  period, registered: Boolean(trendByPeriod.value[period]?.registered),
})).reverse());
const uses = computed(() => useRows(cost.value));
const subjects = computed(() => subjectRows(cost.value));
const vacantUse = computed(() => uses.value.find((use) => use.key === '空'));
const trend = computed(() => trendBars(data.value?.trend, 140));
const unregisteredMonths = computed(() => trend.value.filter((month) => !month.registered).map((month) => month.label));
const chips = computed(() => ['全部', ...STATUS_ORDER].map((status) => ({
  status, label: `${status} ${status === '全部' ? occupancy.value.total || 0 : occupancy.value[status] || 0}`,
})));
const buildings = computed(() => groupByBuilding(data.value?.rooms));
const vacantRooms = computed(() => (data.value?.rooms || []).filter((room) => room.status === '空置'));
const room = computed(() => (data.value?.rooms || []).find((item) => item.name === selectedRoom.value) || null);
const errorText = computed(() => (board.error ? extractFrappeError(board.error, '宿舍看板加载失败') : ''));

function pickPeriod(period) {
  selectedPeriod.value = period;
  board.reload();
}

function tileStyle(item) {
  const style = STATUS_STYLE[item.status];
  const dim = filter.value !== '全部' && filter.value !== item.status;
  return {
    border: `1px ${style.line} #E3E6EC`,
    borderLeft: `3px solid ${item.employee_left ? COLORS.leaver : style.dot}`,
    opacity: dim ? 0.3 : 1,
    boxShadow: item.name === selectedRoom.value ? '0 0 0 2px #1A2130' : 'none',
  };
}

function splitBar(item) {
  return { background: item.total > 0 ? COLORS.personal : COLORS.empty };
}

async function pickRoom(item) {
  selectedRoom.value = item.name;
  if (typeof window !== 'undefined' && window.innerWidth < 1024) {
    await nextTick();
    detailPanel.value?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
}

function editRoom(item) {
  router.push(boardEditLocation(item.name));
}

// 去月度登记的内页（登记 / 新增），带上来源：保存或取消后回到本看板；「保存并登记下一间」也照样可用。
function registerFee(item) {
  const room = item ? (item.room_no || item.name) : '';
  router.push({
    path: FEE_PATH,
    query: { view: room ? 'edit' : 'new', ...(room ? { room } : {}), period: data.value.period, from: '/accommodation' },
  });
}
</script>

<template>
  <div class="dorm-board space-y-4 tabular-nums">
    <div class="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
      <div>
        <div class="text-xs text-[#6B7385]">人事中心 · 宿舍</div>
        <h1 class="mt-1 text-[22px] font-semibold text-[#1A2130]">宿舍看板</h1>
      </div>
      <div class="flex flex-wrap items-center gap-3">
        <AccommodationTabs />
        <label v-if="months.length" class="flex items-center gap-2 text-[13px] text-[#6B7385]">
          费用月份
          <select
            :value="data?.period" class="rounded-lg border border-[#D5DAE2] bg-white px-2.5 py-1.5 text-[13px] text-[#1A2130]"
            @change="pickPeriod($event.target.value)"
          >
            <option v-for="month in months" :key="month.period" :value="month.period">{{ monthTitle(month.period) }}{{ month.registered ? '' : '（未登记）' }}</option>
          </select>
        </label>
      </div>
    </div>

    <div v-if="savedNotice" class="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800" role="status" data-saved-notice>{{ savedNotice }}</div>
    <div v-if="errorText" class="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{{ errorText }}</div>
    <div v-else-if="!data" class="rounded-xl border border-[#E3E6EC] bg-white px-4 py-10 text-center text-sm text-gray-400">加载中…</div>

    <template v-if="data">
      <div v-if="lease || leavers.length" role="status" class="divide-y divide-[#F1E0C6] rounded-xl border border-[#F1E0C6] bg-[#FFFAF2] text-[13px] text-[#6E4718]">
        <div v-if="lease" class="flex flex-col gap-1 px-4 py-2.5 md:flex-row md:items-center md:gap-3">
          <span class="hidden h-1.5 w-1.5 shrink-0 rounded-full bg-[#4B9E91] md:block"></span>
          <span class="flex-1"><b class="font-semibold">{{ lease.title }}</b> {{ lease.detail }}</span>
          <router-link :to="{ path: '/accommodation/master', query: { lease: 'expiring' } }" class="shrink-0 font-medium text-[#0E615B] hover:underline">查看续租清单 →</router-link>
        </div>
        <div v-if="leavers.length" class="flex flex-col gap-1 px-4 py-2.5 md:flex-row md:items-center md:gap-3">
          <span class="hidden h-1.5 w-1.5 shrink-0 rounded-full md:block" :style="{ background: COLORS.leaver }"></span>
          <span class="flex-1"><b class="font-semibold">{{ leavers.length }} 位已演示员工166员工还登记在住：</b>{{ leavers.map((item) => `${item.room_no} ${item.employee_name}`).join('、') }}</span>
          <router-link :to="{ path: '/accommodation/master', query: { leaver: '1' } }" class="shrink-0 font-medium text-[#0E615B] hover:underline">{{ canEdit ? '去填写退宿日期 →' : '查看这些房间 →' }}</router-link>
        </div>
      </div>

      <div class="grid gap-4 lg:grid-cols-3">
        <section class="dorm-card">
          <div class="dorm-head"><h2 class="dorm-title">入住情况</h2><span class="dorm-sub">当前 · 共 {{ occupancy.total }} 间</span></div>
          <div class="flex items-center gap-5">
            <div class="flex h-[112px] w-[112px] shrink-0 items-center justify-center rounded-full md:h-[128px] md:w-[128px]" :style="{ background: donutGradient(occupancy) }">
              <div class="flex h-[84px] w-[84px] flex-col items-center justify-center rounded-full bg-white md:h-[96px] md:w-[96px]">
                <div class="text-[22px] font-semibold text-[#1A2130] md:text-[26px]">{{ percent(occupancy['入住'], occupancy.residential, 0) }}</div>
                <div class="text-[11px] text-[#6B7385]">入住率</div>
              </div>
            </div>
            <div class="flex flex-1 flex-col gap-2">
              <div v-for="item in legend" :key="item.status" class="flex items-center gap-2 text-[13px] text-[#3D4555]">
                <span class="h-2 w-2 rounded-full" :style="{ background: item.color }"></span>
                <span class="flex-1">{{ item.label }}</span>
                <span class="font-semibold text-[#1A2130]">{{ item.count }} 间</span>
              </div>
            </div>
          </div>
          <div class="dorm-note">住宿用房 {{ occupancy.residential }} 间（不含客房、午休室），住了 {{ occupancy['入住'] }} 间；空置 {{ occupancy['空置'] }} 间，租金合计 <b>{{ whole(occupancy.vacant_rent) }} 元/月</b>。</div>
        </section>

        <section class="dorm-card">
          <div class="dorm-head"><h2 class="dorm-title">费用：公司 vs 个人</h2><span class="dorm-sub">{{ title }}</span></div>
          <div v-if="registered" class="flex flex-col gap-3.5">
            <div><div class="dorm-sub">本月宿舍总费用</div><div class="mt-0.5 text-[26px] font-semibold text-[#1A2130]">¥ {{ money(cost.total) }}</div></div>
            <div class="flex flex-col gap-1.5">
              <div class="flex h-2.5 overflow-hidden rounded-full"><div :style="{ width: ratioWidth(cost.company, cost.total), background: COLORS.company }"></div><div :style="{ width: ratioWidth(cost.personal, cost.total), background: COLORS.personal }"></div></div>
              <div class="flex flex-wrap justify-between gap-1 text-[13px] text-[#3D4555]">
                <span><span class="font-semibold" :style="{ color: COLORS.companyText }">公司 {{ percent(cost.company, cost.total) }}</span> · {{ money(cost.company) }}</span>
                <span><span class="font-semibold" :style="{ color: COLORS.personalText }">个人 {{ percent(cost.personal, cost.total) }}</span> · {{ money(cost.personal) }}</span>
              </div>
            </div>
            <div class="flex flex-col gap-2 border-t border-[#EEF0F4] pt-3">
              <div v-for="item in cost.components" :key="item.key" class="grid grid-cols-[36px_minmax(0,1fr)_88px] items-center gap-2.5 text-[13px] text-[#3D4555]">
                <span>{{ item.label }}</span>
                <div class="flex h-1.5 overflow-hidden rounded-full" :style="splitBar(item)"><div :style="{ width: ratioWidth(item.company, item.total), background: COLORS.company }"></div></div>
                <span class="text-right">{{ money(item.total) }}</span>
              </div>
              <div v-if="cost.per_person.people" class="text-xs text-[#6B7385]">人均每月：个人 {{ whole(cost.per_person.personal) }} 元 · 公司补贴 {{ whole(cost.per_person.company) }} 元（{{ cost.per_person.people }} 人）</div>
            </div>
          </div>
          <div v-else class="dorm-empty">
            <div>{{ title }}还没有登记宿舍费用</div>
            <button v-if="canEdit" type="button" class="font-medium text-[#0E615B] hover:underline" data-board-register @click="registerFee(null)">去登记本月费用 →</button>
          </div>
        </section>

        <section class="dorm-card">
          <div class="dorm-head"><h2 class="dorm-title">公司承担的钱花在哪</h2><span class="dorm-sub">{{ title }}</span></div>
          <div v-if="registered" class="flex flex-col gap-3">
            <div class="flex h-2.5 overflow-hidden rounded-full bg-[#EEF1F6]"><div v-for="use in uses" :key="use.key" :style="{ width: use.width, background: use.color }"></div></div>
            <div v-for="use in uses" :key="use.key" class="flex items-center gap-2 text-[13px] text-[#3D4555]">
              <span class="h-2 w-2 shrink-0 rounded-full" :style="{ background: use.color }"></span>
              <span class="flex-1">{{ use.text }}</span>
              <span class="w-10 text-right text-[#6B7385]">{{ use.share }}</span>
              <span class="w-24 text-right font-semibold text-[#1A2130]">{{ money(use.amount) }}</span>
            </div>
            <div v-if="vacantUse && vacantUse.amount" class="dorm-note">空置房让公司每月多付 <b>{{ whole(vacantUse.amount) }} 元</b>，占公司承担的 {{ vacantUse.share }}。</div>
          </div>
          <div v-else class="dorm-empty">登记费用后自动汇总</div>
        </section>
      </div>

      <div class="lg:hidden">
        <section class="dorm-card">
          <div class="dorm-head"><h2 class="dorm-title">空置房间</h2><span class="dorm-sub">{{ vacantRooms.length }} 间 · 点开看详情</span></div>
          <button
            v-for="item in vacantRooms" :key="item.name" type="button"
            class="flex min-h-[44px] items-center gap-3 rounded-lg border border-[#E3E6EC] bg-white px-3 py-2 text-left"
            :style="{ borderLeft: `3px solid ${COLORS.vacant}` }"
            @click="pickRoom(item)"
          >
            <b class="w-[52px] text-sm font-semibold">{{ item.room_no }}</b>
            <span class="flex-1 text-[13px] text-[#6B7385]">{{ item.room_type || '未设置房型' }}</span>
            <span class="text-[13px] text-[#3D4555]">{{ whole(item.monthly_rent) }} 元/月</span>
          </button>
          <div v-if="!vacantRooms.length" class="text-sm text-[#6B7385]">没有空置房间。</div>
        </section>
      </div>

      <section class="dorm-card">
        <div class="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div class="flex items-baseline gap-2.5"><h2 class="dorm-title">房间一览</h2><span class="dorm-sub">按楼栋排列 · 点房间看详情</span></div>
          <div role="group" aria-label="按状态筛选" class="flex flex-wrap gap-1.5">
            <button
              v-for="chip in chips" :key="chip.status" type="button"
              class="rounded-full border px-3 py-1 text-xs"
              :class="filter === chip.status ? 'border-[#1A2130] bg-[#1A2130] text-white' : 'border-[#D5DAE2] bg-white text-[#3D4555] hover:border-[#9AA3B2]'"
              @click="filter = chip.status"
            >{{ chip.label }}</button>
          </div>
        </div>
        <div class="flex flex-col gap-4 lg:flex-row lg:items-start">
          <div class="flex min-w-0 flex-1 flex-col gap-3.5">
            <div v-for="building in buildings" :key="building.name" class="flex flex-col gap-2">
              <div class="flex items-baseline gap-2"><b class="text-sm font-semibold text-[#1A2130]">{{ building.name }}</b><span class="dorm-sub">{{ building.summary }}</span></div>
              <div class="grid grid-cols-4 gap-1.5 sm:grid-cols-6 md:grid-cols-8 lg:grid-cols-6 xl:grid-cols-8 2xl:grid-cols-10">
                <button
                  v-for="item in building.rooms" :key="item.name" type="button"
                  :aria-label="`${item.room_no} ${item.status}`"
                  class="flex min-h-[58px] flex-col gap-1 rounded-md bg-white px-2 py-1.5 text-left hover:bg-[#F8F9FB]"
                  :style="tileStyle(item)"
                  @click="pickRoom(item)"
                >
                  <span class="truncate text-[13px] font-semibold text-[#1A2130]">{{ item.room_no }}</span>
                  <span class="truncate text-[11px]" :style="{ color: item.employee_left ? COLORS.leaver : STATUS_STYLE[item.status].text }">{{ item.employee_left ? '已演示员工166在住' : item.status }}</span>
                  <div class="mt-auto h-1 w-full overflow-hidden rounded-full" :style="splitBar(item)">
                    <div class="h-full" :style="{ width: ratioWidth(item.company, item.total), background: COLORS.company }"></div>
                  </div>
                </button>
              </div>
            </div>
            <div class="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-[#6B7385]">
              <span v-for="item in legend" :key="item.status" class="flex items-center gap-1.5"><span class="h-2.5 w-[3px] rounded-sm" :style="{ background: item.color }"></span>{{ item.status }}</span>
              <span class="flex items-center gap-1.5"><span class="h-2.5 w-[3px] rounded-sm" :style="{ background: COLORS.leaver }"></span>已演示员工166在住</span>
              <span class="text-[#9AA3B2]">|</span>
              <span>底部细条：<span :style="{ color: COLORS.companyText }">公司</span> / <span :style="{ color: COLORS.personalText }">个人</span>承担（所选月份）</span>
            </div>
          </div>

          <aside v-if="room" ref="detailPanel" aria-label="房间详情" class="flex w-full shrink-0 scroll-mt-4 flex-col gap-3 rounded-lg border border-[#E3E6EC] bg-[#FAFBFC] p-4 lg:w-[300px]">
            <div class="flex items-center justify-between">
              <span class="text-lg font-semibold text-[#1A2130]">{{ room.room_no }}</span>
              <span class="flex items-center gap-1.5 text-[13px]" :style="{ color: STATUS_STYLE[room.status].text }"><span class="h-2 w-2 rounded-full" :style="{ background: STATUS_STYLE[room.status].dot }"></span>{{ room.status }}</span>
            </div>
            <div class="grid grid-cols-[64px_minmax(0,1fr)] gap-y-2 text-[13px]">
              <span class="text-[#6B7385]">房型</span><span>{{ room.room_type || '—' }}</span>
              <span class="text-[#6B7385]">月租</span><span>{{ whole(room.monthly_rent) }} 元</span>
              <span class="text-[#6B7385]">租约</span><span :class="room.lease_days_left !== null && room.lease_days_left <= 60 ? 'text-[#0E615B]' : ''">{{ leaseText(room) }}</span>
              <span class="text-[#6B7385]">入住人</span>
              <span>{{ room.employee_name || '—' }}<span v-if="room.employee_left" class="ml-1.5 text-xs" :style="{ color: COLORS.leaver }">已演示员工166</span></span>
            </div>
            <div class="flex flex-col gap-2 border-t border-[#EEF0F4] pt-3">
              <div class="flex justify-between text-[13px]"><span class="text-[#6B7385]">{{ title }}费用</span><b class="font-semibold">{{ room.total > 0 ? `¥ ${money(room.total)}` : '未登记' }}</b></div>
              <div class="h-1.5 overflow-hidden rounded-full" :style="splitBar(room)"><div class="h-full" :style="{ width: ratioWidth(room.company, room.total), background: COLORS.company }"></div></div>
              <div class="flex justify-between text-xs"><span :style="{ color: COLORS.companyText }">公司 {{ money(room.company) }}</span><span :style="{ color: COLORS.personalText }">个人 {{ money(room.personal) }}</span></div>
              <div class="text-xs leading-relaxed text-[#3D4555]">{{ roomNote(room) }}</div>
            </div>
            <div v-if="canEdit" class="flex gap-2" data-board-actions>
              <button type="button" class="flex-1 rounded-md border border-[#D5DAE2] bg-white py-2 text-[13px] text-[#1A2130] hover:bg-[#F3F4F6]" @click="editRoom(room)">编辑房间</button>
              <button type="button" class="flex-1 rounded-md bg-[#1A2130] py-2 text-[13px] text-white hover:bg-[#2B3445]" @click="registerFee(room)">登记费用</button>
            </div>
          </aside>
        </div>
      </section>

      <div class="grid gap-4 lg:grid-cols-2">
        <section class="dorm-card">
          <div class="dorm-head"><h2 class="dorm-title">公司承担按费用科目</h2><span class="dorm-sub">{{ title }} · 按入住人部门的科目</span></div>
          <div v-if="registered" class="flex flex-col gap-2.5">
            <div v-for="subject in subjects" :key="subject.label" class="grid grid-cols-[64px_minmax(0,1fr)_128px] items-center gap-3 text-[13px] text-[#3D4555]">
              <span>{{ subject.label }}</span>
              <div class="h-2 overflow-hidden rounded-full bg-[#EEF1F6]"><div class="h-full rounded-full" :style="{ width: subject.width, background: COLORS.company }"></div></div>
              <span class="text-right"><span class="font-semibold text-[#1A2130]">{{ money(subject.amount) }}</span> <span class="text-[#6B7385]">{{ subject.share }}</span></span>
            </div>
            <div v-if="cost.management_includes.length" class="text-xs text-[#6B7385]">管理费用里包含{{ cost.management_includes.map((item) => `${item.label} ${money(item.amount)} 元`).join('和') }}。</div>
          </div>
          <div v-else class="dorm-empty min-h-[140px]">登记费用后自动汇总</div>
        </section>

        <section class="dorm-card">
          <div class="dorm-head"><h2 class="dorm-title">每月费用</h2><span class="dorm-sub">{{ monthLabel(data.periods[0]) }}起在系统登记</span></div>
          <div class="overflow-x-auto">
            <div class="flex items-end gap-3 border-b border-[#E3E6EC] px-2" :style="{ minWidth: `${trend.length * 64}px`, height: '176px' }">
              <button v-for="month in trend" :key="month.period" type="button" class="flex flex-1 flex-col items-center gap-1" :aria-label="`${month.label} ${month.registered ? money(month.total) : '未登记'}`" @click="pickPeriod(month.period)">
                <template v-if="month.registered">
                  <span class="text-[11px] text-[#3D4555]">{{ whole(month.total) }}</span>
                  <div class="flex w-9 flex-col overflow-hidden rounded-t" :style="{ opacity: month.period === data.period ? 1 : 0.55 }">
                    <div :style="{ height: `${month.personalHeight}px`, background: COLORS.personal }"></div>
                    <div :style="{ height: `${month.companyHeight}px`, background: COLORS.company }"></div>
                  </div>
                </template>
                <template v-else>
                  <span class="text-[11px] text-[#9AA3B2]">未登记</span>
                  <div class="box-border h-[140px] w-9 rounded-t border border-b-0 border-dashed border-[#CBD2DD]"></div>
                </template>
              </button>
            </div>
            <div class="flex gap-3 px-2 pt-1.5 text-center text-xs text-[#6B7385]" :style="{ minWidth: `${trend.length * 64}px` }">
              <span v-for="month in trend" :key="month.period" class="flex-1" :class="month.period === data.period ? 'font-semibold text-[#1A2130]' : ''">{{ month.label }}</span>
            </div>
          </div>
          <div class="flex flex-wrap gap-x-4 gap-y-1 text-xs text-[#6B7385]">
            <span class="flex items-center gap-1.5"><span class="h-2 w-2 rounded-full" :style="{ background: COLORS.company }"></span>公司承担</span>
            <span class="flex items-center gap-1.5"><span class="h-2 w-2 rounded-full" :style="{ background: COLORS.personal }"></span>个人承担</span>
            <span v-if="unregisteredMonths.length" class="text-[#0E615B]">{{ unregisteredMonths.join('、') }}还没登记</span>
          </div>
        </section>
      </div>
    </template>
  </div>
</template>

<style scoped>
.dorm-board { color: #1A2130; }
.dorm-card { display: flex; min-width: 0; flex-direction: column; gap: 14px; border: 1px solid #E6E9EF; border-radius: 12px; background: #FFFFFF; padding: 16px; }
@media (min-width: 768px) { .dorm-card { padding: 18px 20px; } }
.dorm-head { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; }
.dorm-title { margin: 0; font-size: 15px; font-weight: 600; color: #1A2130; }
.dorm-sub { font-size: 12px; color: #6B7385; }
.dorm-note { border-radius: 8px; background: #F6F7F9; padding: 10px 12px; font-size: 12.5px; line-height: 1.6; color: #3D4555; }
.dorm-empty { display: flex; min-height: 200px; flex-grow: 1; flex-direction: column; align-items: center; justify-content: center; gap: 10px; border: 1px dashed #D5DAE2; border-radius: 10px; font-size: 13px; color: #6B7385; }
</style>
