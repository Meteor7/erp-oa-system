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

const router = useRouter();
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
  period, label: monthLabel(period), registered: Boolean(trendByPeriod.value[period]?.registered),
})));
const uses = computed(() => useRows(cost.value));
const subjects = computed(() => subjectRows(cost.value));
const vacantUse = computed(() => uses.value.find((use) => use.key === '空'));
const trend = computed(() => trendBars(data.value?.trend));
const unregisteredMonths = computed(() => trend.value.filter((month) => !month.registered).map((month) => month.label));
const chips = computed(() => ['全部', ...STATUS_ORDER].map((status) => ({
  status, label: `${status} ${status === '全部' ? occupancy.value.total || 0 : occupancy.value[status] || 0}`,
})));
const buildings = computed(() => groupByBuilding(data.value?.rooms));
const vacantRooms = computed(() => (data.value?.rooms || []).filter((room) => room.status === '空置'));
const room = computed(() => (data.value?.rooms || []).find((item) => item.name === selectedRoom.value) || null);
const errorText = computed(() => (board.error ? extractFrappeError(board.error, '宿舍看板加载失败') : ''));

function pickPeriod(period) {
  if (period === selectedPeriod.value) return;
  selectedPeriod.value = period;
  board.reload();
}

function tileStyle(item) {
  const style = STATUS_STYLE[item.status];
  const dim = filter.value !== '全部' && filter.value !== item.status;
  return {
    background: style.bg,
    border: `1.5px ${style.line} ${style.border}`,
    color: style.text,
    opacity: dim ? 0.28 : 1,
    boxShadow: item.name === selectedRoom.value ? '0 0 0 3px #1A2130' : 'none',
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
  router.push({ path: '/accommodation/master', query: { room: item.name } });
}

function registerFee(item) {
  router.push({ path: '/accommodation/monthly', query: { period: data.value.period, ...(item ? { room: item.name } : {}) } });
}
</script>

<template>
  <div class="dorm-board space-y-5 tabular-nums">
    <div class="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
      <div>
        <div class="text-[13px] text-[#5B6475]">人事中心 · 宿舍</div>
        <h1 class="mt-1 text-2xl font-bold text-[#1A2130] md:text-[28px]">宿舍看板</h1>
      </div>
      <div class="flex flex-col gap-3 md:flex-row md:items-center">
        <AccommodationTabs />
        <div v-if="months.length" class="flex items-center gap-2">
          <span class="shrink-0 text-[13px] text-[#5B6475]">费用月份</span>
          <div class="flex gap-1 overflow-x-auto">
            <button
              v-for="month in months" :key="month.period" type="button"
              class="shrink-0 rounded-lg border px-3 py-1.5 text-[13px]"
              :class="month.period === data?.period ? 'border-[#E8730C] bg-[#FFF4E6] text-[#8A3D00]' : month.registered ? 'border-[#D5DAE2] bg-white text-[#3D4555]' : 'border-[#D5DAE2] bg-white text-[#A34700]'"
              @click="pickPeriod(month.period)"
            >{{ month.label }}{{ month.registered ? '' : ' ·未登记' }}</button>
          </div>
        </div>
      </div>
    </div>

    <div v-if="errorText" class="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{{ errorText }}</div>
    <div v-else-if="!data" class="rounded-xl border border-[#E3E6EC] bg-white px-4 py-10 text-center text-sm text-gray-400">加载中…</div>

    <template v-if="data">
      <div v-if="lease" role="status" class="flex flex-col gap-2 rounded-xl border border-[#F5C28A] bg-[#FFF4E6] px-5 py-3.5 md:flex-row md:items-center md:gap-3.5">
        <svg class="hidden shrink-0 md:block" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#C25E00" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9"></circle><path d="M12 7v5l3 2"></path></svg>
        <div class="flex-1 text-[15px] text-[#6B3300]"><b>{{ lease.title }}</b> {{ lease.detail }}</div>
        <router-link :to="{ path: '/accommodation/master', query: { lease: 'expiring' } }" class="text-sm font-semibold text-[#C25E00] hover:text-[#8A3D00]">查看续租清单</router-link>
      </div>
      <div v-if="leavers.length" role="status" class="flex flex-col gap-2 rounded-xl border border-[#F5C28A] bg-[#FFF4E6] px-5 py-3.5 md:flex-row md:items-center md:gap-3.5">
        <div class="flex-1 text-[15px] text-[#6B3300]"><b>{{ leavers.length }} 位已离职员工还登记在住：</b>{{ leavers.map((item) => `${item.room_no} ${item.employee_name}`).join('、') }}。</div>
        <router-link to="/accommodation/master" class="text-sm font-semibold text-[#C25E00] hover:text-[#8A3D00]">去填写退宿日期</router-link>
      </div>

      <div class="grid gap-5 lg:grid-cols-3">
        <section class="dorm-card">
          <div class="flex items-baseline justify-between"><h2 class="dorm-title">入住情况</h2><span class="text-xs text-[#5B6475]">当前 · 共 {{ occupancy.total }} 间</span></div>
          <div class="flex items-center gap-4 md:gap-6">
            <div class="flex h-28 w-28 shrink-0 items-center justify-center rounded-full md:h-[148px] md:w-[148px]" :style="{ background: donutGradient(occupancy) }">
              <div class="flex h-[78px] w-[78px] flex-col items-center justify-center rounded-full bg-white md:h-[104px] md:w-[104px]">
                <div class="text-[22px] font-bold text-[#1E3A8A] md:text-[30px]">{{ percent(occupancy['入住'], occupancy.residential, 0) }}</div>
                <div class="text-[10px] text-[#5B6475] md:text-xs"><span class="hidden md:inline">住宿用房</span>入住率</div>
              </div>
            </div>
            <div class="flex flex-1 flex-col gap-2.5">
              <div v-for="item in legend" :key="item.status" class="flex items-center gap-2 text-sm">
                <span class="h-2.5 w-2.5 rounded-[3px]" :style="{ background: item.color }"></span>
                <span class="flex-1">{{ item.label }}</span>
                <b :class="item.status === '空置' ? 'text-[#A34700]' : ''">{{ item.count }} 间</b>
              </div>
            </div>
          </div>
          <div class="dorm-note">空置 {{ occupancy['空置'] }} 间，租金合计 <b>{{ whole(occupancy.vacant_rent) }} 元/月</b>。住宿用房 {{ occupancy.residential }} 间（不含客房、午休室），住了 {{ occupancy['入住'] }} 间。</div>
        </section>

        <section class="dorm-card">
          <div class="flex items-baseline justify-between"><h2 class="dorm-title">费用：公司 vs 个人</h2><span class="text-xs text-[#5B6475]">{{ title }}</span></div>
          <div v-if="registered" class="flex flex-col gap-4">
            <div><div class="text-xs text-[#5B6475]">本月宿舍总费用</div><div class="text-[26px] font-bold md:text-[30px]">¥ {{ money(cost.total) }}</div></div>
            <div class="flex flex-col gap-2">
              <div class="flex h-[18px] overflow-hidden rounded-md"><div :style="{ width: ratioWidth(cost.company, cost.total), background: COLORS.company }"></div><div :style="{ width: ratioWidth(cost.personal, cost.total), background: COLORS.personal }"></div></div>
              <div class="flex flex-wrap justify-between gap-1 text-[13px]">
                <span><span class="font-semibold text-[#1E3A8A]">公司承担 {{ percent(cost.company, cost.total) }}</span> · {{ money(cost.company) }}</span>
                <span><span class="font-semibold text-[#8A4B00]">个人承担 {{ percent(cost.personal, cost.total) }}</span> · {{ money(cost.personal) }}</span>
              </div>
            </div>
            <div class="flex flex-col gap-2.5 border-t border-[#EEF0F4] pt-1">
              <div v-for="item in cost.components" :key="item.key" class="grid grid-cols-[44px_minmax(0,1fr)_96px] items-center gap-2.5 text-[13px]">
                <span class="text-[#3D4555]">{{ item.label }}</span>
                <div class="flex h-2 overflow-hidden rounded" :style="splitBar(item)"><div :style="{ width: ratioWidth(item.company, item.total), background: COLORS.company }"></div></div>
                <span class="text-right">{{ money(item.total) }}</span>
              </div>
              <div v-if="cost.per_person.people" class="text-xs text-[#5B6475]">人均每月：个人 {{ whole(cost.per_person.personal) }} 元 · 公司补贴 {{ whole(cost.per_person.company) }} 元（{{ cost.per_person.people }} 人）。</div>
            </div>
          </div>
          <div v-else class="dorm-empty">
            <div>{{ title }}还没有登记宿舍费用</div>
            <button type="button" class="font-semibold text-[#C25E00] hover:text-[#8A3D00]" @click="registerFee(null)">去登记本月费用</button>
          </div>
        </section>

        <section class="dorm-card">
          <div class="flex items-baseline justify-between"><h2 class="dorm-title">公司承担的钱花在哪</h2><span class="text-xs text-[#5B6475]">{{ title }}</span></div>
          <div v-if="registered" class="flex flex-col gap-3.5">
            <div class="flex h-[18px] overflow-hidden rounded-md bg-[#EEF1F6]"><div v-for="use in uses" :key="use.key" :style="{ width: use.width, background: use.color }"></div></div>
            <div v-for="use in uses" :key="use.key" class="flex items-center gap-2.5 text-sm">
              <span class="h-2.5 w-2.5 shrink-0 rounded-[3px]" :style="{ background: use.color }"></span>
              <span class="flex-1">{{ use.text }}</span>
              <span class="w-[52px] text-right text-[#5B6475]">{{ use.share }}</span>
              <b class="w-24 text-right" :class="use.key === '空' ? 'text-[#A34700]' : ''">{{ money(use.amount) }}</b>
            </div>
            <div v-if="vacantUse && vacantUse.amount" class="dorm-note">空置房每月让公司多付 <b>{{ whole(vacantUse.amount) }} 元</b>，占公司承担的 {{ vacantUse.share }}。</div>
          </div>
          <div v-else class="dorm-empty">登记费用后自动汇总</div>
        </section>
      </div>

      <div class="lg:hidden">
      <section class="dorm-card">
        <div class="flex items-baseline justify-between"><h2 class="dorm-title">空置房间</h2><span class="text-xs text-[#5B6475]">{{ vacantRooms.length }} 间 · 点开可登记或安排入住</span></div>
        <button
          v-for="item in vacantRooms" :key="item.name" type="button"
          class="flex min-h-[44px] items-center gap-3 rounded-[10px] border-[1.5px] border-[#F5C28A] bg-[#FFF4E6] px-3 py-2.5 text-left"
          @click="pickRoom(item)"
        >
          <b class="w-[52px] text-[15px]">{{ item.room_no }}</b>
          <span class="flex-1 text-[13px] text-[#5B6475]">{{ item.room_type || '未设置房型' }}</span>
          <span class="text-[13px]">{{ whole(item.monthly_rent) }} 元/月</span>
        </button>
        <div v-if="!vacantRooms.length" class="text-sm text-[#5B6475]">没有空置房间。</div>
      </section>
      </div>

      <section class="dorm-card">
        <div class="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div class="flex items-baseline gap-3"><h2 class="dorm-title">房间一览</h2><span class="text-xs text-[#5B6475]">按楼栋排列 · 点房间看详情</span></div>
          <div role="group" aria-label="按状态筛选" class="flex flex-wrap gap-1.5">
            <button
              v-for="chip in chips" :key="chip.status" type="button"
              class="rounded-full border px-3.5 py-1.5 text-[13px]"
              :class="filter === chip.status ? 'border-[#1A2130] bg-[#1A2130] text-white' : 'border-[#D5DAE2] bg-white text-[#3D4555]'"
              @click="filter = chip.status"
            >{{ chip.label }}</button>
          </div>
        </div>
        <div class="flex flex-col gap-5 lg:flex-row lg:items-start">
          <div class="flex min-w-0 flex-1 flex-col gap-4">
            <div v-for="building in buildings" :key="building.name" class="flex flex-col gap-2.5">
              <div class="flex items-baseline gap-2.5"><b class="text-[15px]">{{ building.name }}</b><span class="text-xs text-[#5B6475]">{{ building.summary }}</span></div>
              <div class="grid grid-cols-5 gap-1.5 sm:grid-cols-6 md:gap-2 2xl:grid-cols-8">
                <button
                  v-for="item in building.rooms" :key="item.name" type="button"
                  :aria-label="`${item.room_no} ${item.status}`"
                  class="flex min-h-[64px] flex-col gap-1.5 rounded-[10px] px-2 pb-2 pt-2.5 text-left md:min-h-[76px] md:px-2.5"
                  :style="tileStyle(item)"
                  @click="pickRoom(item)"
                >
                  <div class="flex w-full items-baseline justify-between gap-1"><span class="truncate text-[13px] font-bold md:text-[15px]">{{ item.room_no }}</span><span class="hidden shrink-0 whitespace-nowrap text-[11px] md:inline">{{ item.status }}</span></div>
                  <div class="hidden w-full truncate text-[11px] text-[#5B6475] md:block">{{ item.room_type || '—' }} · {{ whole(item.monthly_rent) }}</div>
                  <div class="relative mt-auto h-[5px] w-full overflow-hidden rounded-[3px]" :style="splitBar(item)">
                    <div class="h-full" :style="{ width: ratioWidth(item.company, item.total), background: COLORS.company }"></div>
                  </div>
                  <span v-if="item.employee_left" class="text-[10px] font-semibold text-[#A34700]">已离职</span>
                </button>
              </div>
            </div>
            <div class="flex flex-wrap items-center gap-4 text-xs text-[#5B6475]">
              <span>房间底部细条：</span>
              <span class="flex items-center gap-1.5"><span class="h-1.5 w-4 rounded-[3px]" :style="{ background: COLORS.company }"></span>公司承担</span>
              <span class="flex items-center gap-1.5"><span class="h-1.5 w-4 rounded-[3px]" :style="{ background: COLORS.personal }"></span>个人承担</span>
              <span>（所选月份）</span>
              <span class="lg:hidden">虚线框：午休室</span>
            </div>
          </div>

          <aside v-if="room" ref="detailPanel" aria-label="房间详情" class="flex w-full shrink-0 scroll-mt-4 flex-col gap-3.5 rounded-xl border border-[#E3E6EC] bg-[#FBFCFD] p-5 lg:w-[340px]">
            <div class="flex items-center justify-between">
              <span class="text-[22px] font-bold">{{ room.room_no }}</span>
              <span class="rounded-full border px-2.5 py-1 text-[13px] font-semibold" :style="{ background: STATUS_STYLE[room.status].bg, color: STATUS_STYLE[room.status].text, borderColor: STATUS_STYLE[room.status].border }">{{ room.status }}</span>
            </div>
            <div class="grid grid-cols-[76px_minmax(0,1fr)] gap-y-2.5 text-sm">
              <span class="text-[#5B6475]">房型</span><span>{{ room.room_type || '—' }}</span>
              <span class="text-[#5B6475]">月租</span><span>{{ whole(room.monthly_rent) }} 元</span>
              <span class="text-[#5B6475]">租约</span><span :class="room.lease_days_left !== null && room.lease_days_left <= 60 ? 'text-[#A34700]' : ''">{{ leaseText(room) }}</span>
              <span class="text-[#5B6475]">入住人</span>
              <span>{{ room.employee_name || '—' }}<span v-if="room.employee_left" class="ml-1.5 rounded bg-amber-100 px-1.5 py-0.5 text-[11px] text-amber-700">已离职</span></span>
            </div>
            <div class="flex flex-col gap-2.5 border-t border-[#EEF0F4] pt-3.5">
              <div class="flex justify-between text-[13px]"><span class="text-[#5B6475]">{{ title }}费用</span><b>{{ room.total > 0 ? `¥ ${money(room.total)}` : '未登记' }}</b></div>
              <div class="h-2.5 overflow-hidden rounded-[5px]" :style="splitBar(room)"><div class="h-full" :style="{ width: ratioWidth(room.company, room.total), background: COLORS.company }"></div></div>
              <div class="flex justify-between text-[13px]"><span class="text-[#1E3A8A]">公司 {{ money(room.company) }}</span><span class="text-[#8A4B00]">个人 {{ money(room.personal) }}</span></div>
              <div class="text-[13px] leading-relaxed text-[#3D4555]">{{ roomNote(room) }}</div>
            </div>
            <div class="mt-1 flex gap-2">
              <button type="button" class="flex-1 rounded-lg border border-[#D5DAE2] bg-white py-2.5 text-sm text-[#1A2130]" @click="editRoom(room)">编辑房间</button>
              <button type="button" class="flex-1 rounded-lg bg-[#E8730C] py-2.5 text-sm text-white" @click="registerFee(room)">登记费用</button>
            </div>
          </aside>
        </div>
      </section>

      <div class="grid gap-5 lg:grid-cols-2">
        <section class="dorm-card">
          <div class="flex flex-wrap items-baseline justify-between gap-1"><h2 class="dorm-title">公司承担按费用科目</h2><span class="text-xs text-[#5B6475]">{{ title }} · 按入住人所在部门的科目</span></div>
          <div v-if="registered" class="flex flex-col gap-3">
            <div v-for="subject in subjects" :key="subject.label" class="grid grid-cols-[72px_minmax(0,1fr)_140px] items-center gap-3 text-sm">
              <span>{{ subject.label }}</span>
              <div class="h-3 overflow-hidden rounded-md bg-[#EEF1F6]"><div class="h-full rounded-md" :style="{ width: subject.width, background: COLORS.company }"></div></div>
              <span class="text-right"><b>{{ money(subject.amount) }}</b> <span class="text-[#5B6475]">{{ subject.share }}</span></span>
            </div>
            <div v-if="cost.management_includes.length" class="text-xs text-[#5B6475]">管理费用里包含{{ cost.management_includes.map((item) => `${item.label} ${money(item.amount)} 元`).join('和') }}。</div>
          </div>
          <div v-else class="dorm-empty min-h-[150px]">登记费用后自动汇总</div>
        </section>

        <section class="dorm-card">
          <div class="flex items-baseline justify-between"><h2 class="dorm-title">每月费用</h2><span class="text-xs text-[#5B6475]">{{ monthLabel(data.periods[0]) }}起在系统登记</span></div>
          <div class="overflow-x-auto">
            <div class="flex h-[190px] min-w-full items-end gap-4 border-b border-[#E3E6EC] px-3 md:gap-6" :style="{ width: `${Math.max(trend.length * 80, 320)}px` }">
              <button v-for="month in trend" :key="month.period" type="button" class="flex flex-1 flex-col items-center gap-1.5" :aria-label="`${month.label} ${month.registered ? money(month.total) : '未登记'}`" @click="pickPeriod(month.period)">
                <template v-if="month.registered">
                  <span class="text-xs font-semibold">{{ whole(month.total) }}</span>
                  <div class="flex w-14 flex-col" :class="month.period === data.period ? 'ring-2 ring-[#1A2130] ring-offset-2' : ''">
                    <div class="rounded-t-md" :style="{ height: `${month.personalHeight}px`, background: COLORS.personal }"></div>
                    <div :style="{ height: `${month.companyHeight}px`, background: COLORS.company }"></div>
                  </div>
                </template>
                <template v-else>
                  <span class="text-xs text-[#A34700]">未登记</span>
                  <div class="box-border h-40 w-14 rounded-t-md border-[1.5px] border-b-0 border-dashed border-[#F5C28A]"></div>
                </template>
              </button>
            </div>
            <div class="flex gap-4 px-3 pt-2 text-center text-[13px] text-[#3D4555] md:gap-6" :style="{ width: `${Math.max(trend.length * 80, 320)}px` }">
              <span v-for="month in trend" :key="month.period" class="flex-1">{{ month.label }}</span>
            </div>
          </div>
          <div class="flex flex-wrap gap-4 text-xs text-[#5B6475]">
            <span class="flex items-center gap-1.5"><span class="h-2.5 w-2.5 rounded-[3px]" :style="{ background: COLORS.company }"></span>公司承担</span>
            <span class="flex items-center gap-1.5"><span class="h-2.5 w-2.5 rounded-[3px]" :style="{ background: COLORS.personal }"></span>个人承担</span>
            <span v-if="unregisteredMonths.length" class="text-[#A34700]">{{ unregisteredMonths.join('、') }}还没登记，看板会一直提醒</span>
          </div>
        </section>
      </div>
    </template>
  </div>
</template>

<style scoped>
.dorm-board { color: #1A2130; }
.dorm-card { display: flex; min-width: 0; flex-direction: column; gap: 16px; border: 1px solid #E3E6EC; border-radius: 14px; background: #FFFFFF; padding: 16px; }
@media (min-width: 768px) { .dorm-card { padding: 22px 24px; } }
.dorm-title { margin: 0; font-size: 16px; font-weight: 600; }
.dorm-note { border-radius: 10px; background: #FFF4E6; padding: 12px 14px; font-size: 13px; line-height: 1.6; color: #6B3300; }
.dorm-empty { display: flex; min-height: 220px; flex-grow: 1; flex-direction: column; align-items: center; justify-content: center; gap: 12px; border: 1.5px dashed #D5DAE2; border-radius: 12px; font-size: 14px; color: #5B6475; }
</style>
