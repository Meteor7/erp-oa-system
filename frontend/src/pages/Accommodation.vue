<script setup>
// 月度费用登记：列表一页，新增 / 编辑单独一页（内页），用查询参数区分，和报销、考勤、采购一样。
//   ?view=list（默认）  ?view=new&period=YYYY-MM  ?view=edit&room=<房间号>&period=YYYY-MM
//   内页带 from=list（连同列表当时的月份 / 筛选）或 from=<站内路径>（看板、数据看板），返回 / 保存后回到来的地方。
// 地址解析、返回目标、"下一间"的选择都在 lib/accommodationFees.js；表单本身在 components/accommodation/FeeForm.vue。
import { ref, computed, watch, onBeforeUnmount } from "vue";
import { useRoute, useRouter } from "vue-router";
import { Card, Button, createResource } from "frappe-ui";
import AccommodationTabs from "../components/AccommodationTabs.vue";
import FeeForm from "../components/accommodation/FeeForm.vue";
import { period, periodRouteSpec } from "../lib/period";
import { bindRouteFilters, queryText } from "../lib/urlFilterState";
import { extractFrappeError } from "../lib/frappeError";
import { splitPath } from "../lib/navContext.js";
import {
  FEE_PATH, editQuery, feeBackText, feeCells, feeListState, feeReturnTarget, findRoom, listQuery, newQuery, nextQuery,
  nextUnregistered, parseFeeLocation, rememberSaved, savedText, takeSaved, unregisteredRooms, visibleRooms,
} from "../lib/accommodationFees.js";

const EXPENSE_ACCOUNT_CATEGORIES = ["研发费用", "管理费用", "销售费用", "生产成本"];
const SPECIAL_OCCUPANTS = ["空", "客房", "午休室"];
// 从宿舍看板点"登记费用"、或从数据看板点进来时，地址带 ?period=YYYY-MM（可再带 room=、status=open）：
// 先读好月份，再建数据请求。status=open：只看在住但本期还没登记费用的房间。
const route = useRoute();
const router = useRouter();
const statusFilter = ref("");
bindRouteFilters({
  route,
  router,
  specs: [periodRouteSpec(), {
    keys: ["status"],
    read: (query) => ({ status: queryText(query, "status") === "open" ? "open" : "" }),
    snapshot: () => ({ status: statusFilter.value }),
    apply: (state) => { statusFilter.value = state.status; },
    toQuery: (state) => (state.status === "open" ? { status: "open" } : {}),
    sources: [statusFilter],
  }],
});

const options = createResource({ url: "rayher_hr_payroll.api.accommodation_entry.get_emp_options", method: "GET", auto: true });
const roomOptions = createResource({
  url: "rayher_hr_payroll.api.accommodation_entry.get_room_options",
  method: "GET",
  auto: true,
});
const rows = createResource({ url: "rayher_hr_payroll.api.accommodation_entry.list_accommodation", method: "GET", makeParams: () => ({ period: period.value }), auto: true });
const summary = createResource({ url: "rayher_hr_payroll.api.accommodation_entry.get_accommodation_summary", method: "GET", makeParams: () => ({ period: period.value }), auto: true });
// 房间一览（含「是否在住」「本期是否已登记」「个人 / 公司 / 合计」）直接用宿舍看板的接口，权限相同（人事）；
// 列表上每间房的登记情况、"只看未登记"和"保存并登记下一间"都用它。
const board = createResource({
  url: "rayher_hr_payroll.api.dormitory_board.get_dormitory_board",
  method: "GET",
  makeParams: () => ({ period: period.value }),
  auto: true,
});
const remover = createResource({ url: "rayher_hr_payroll.api.accommodation_entry.delete_accommodation" });

const errMsg = ref("");
const notice = ref("");
let noticeTimer = null;

const loc = computed(() => parseFeeLocation(route.query));
const view = computed(() => loc.value.view);
// 列表当前的状态：点进内页时带上，返回时原样恢复。
const listState = computed(() => feeListState({ period: period.value, status: statusFilter.value, origin: loc.value.origin }));

const fmt = (n) => Number(n || 0).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const num = (v) => Number(v || 0);
const defaultSummaryRows = computed(() => EXPENSE_ACCOUNT_CATEGORIES.map((category) => ({
  expense_account_category: category, company_rent_amount: 0, company_water_amount: 0,
  company_electricity_amount: 0, company_total_amount: 0,
})));
const summaryRows = computed(() => (summary.data && summary.data.length ? summary.data : defaultSummaryRows.value));
const summaryTotal = computed(() => ({
  company_rent_amount: summaryRows.value.reduce((total, row) => total + num(row.company_rent_amount), 0),
  company_water_amount: summaryRows.value.reduce((total, row) => total + num(row.company_water_amount), 0),
  company_electricity_amount: summaryRows.value.reduce((total, row) => total + num(row.company_electricity_amount), 0),
  company_total_amount: summaryRows.value.reduce((total, row) => total + num(row.company_total_amount), 0),
}));
const empName = (name) => (options.data || []).find((item) => item.name === name)?.employee_name || name;
const occupantName = (row) => SPECIAL_OCCUPANTS.includes(row.occupant_type) ? row.occupant_type : empName(row.employee);
const sumField = (field) => (rows.data || []).reduce((sum, row) => sum + Number(row[field] || 0), 0);
const isSysMgr = typeof window !== "undefined" && Array.isArray(window.roles) && window.roles.includes("System Manager");

// 在住（房间状态「入住」）但本期还没有任何费用记录的房间；口径和后端 alert.dorm_register 一致（见 lib）。
const openRooms = computed(() => unregisteredRooms(board.data?.rooms));
const listRooms = computed(() => visibleRooms(board.data?.rooms, statusFilter.value));

function reloadPeriodData() {
  rows.reload();
  summary.reload();
  board.reload();
}

async function del(name) {
  errMsg.value = "";
  try { await remover.submit({ name }); reloadPeriodData(); }
  catch (error) { errMsg.value = extractFrappeError(error, "删除失败"); }
}

// ---------------------------------------------------------------- 跳转
const newTo = computed(() => ({ path: FEE_PATH, query: newQuery(listState.value) }));
const editTo = (roomNo) => ({ path: FEE_PATH, query: editQuery(roomNo, listState.value) });
const backTarget = () => {
  const target = feeReturnTarget(route.query, period.value);
  return { path: target.path || FEE_PATH, query: target.query };
};
const backText = computed(() => feeBackText(route.query));
const toOrigin = () => router.push({ path: splitPath(loc.value.from).path, query: splitPath(loc.value.from).query });
const goBack = () => router.push(backTarget());
const goList = () => router.push({ path: FEE_PATH, query: listQuery(listState.value) });
const goBoard = () => router.push({ path: "/accommodation" });

// ---------------------------------------------------------------- 提示
function showNotice(text) {
  notice.value = text;
  clearTimeout(noticeTimer);
  noticeTimer = text ? setTimeout(() => { notice.value = ""; }, 5000) : null;
}
onBeforeUnmount(() => clearTimeout(noticeTimer));
// 别的页面（内页保存后回到来源）留下的"已保存"提示，回到这里时显示。
watch(() => route.fullPath, () => {
  // 离开本页的那一刻 route 已经是别的页面，提示留给那个页面取。
  if (route.path !== FEE_PATH) return;
  const text = takeSaved();
  if (text) showNotice(text);
}, { immediate: true });

// ---------------------------------------------------------------- 内页
const roomsReady = computed(() => Array.isArray(roomOptions.data));
const currentRoom = computed(() => findRoom(roomOptions.data || [], loc.value.room));
const roomMissing = computed(() => view.value === "edit" && roomsReady.value && !currentRoom.value);
const loadError = computed(() => roomOptions.error || options.error || rows.error);
const formReady = computed(() => roomsReady.value && Array.isArray(options.data) && Array.isArray(rows.data) && !rows.loading);
const formKey = computed(() => `${view.value}|${loc.value.room}|${period.value}`);
const crumbTitle = computed(() => (view.value === "new" ? "新增登记" : `编辑 ${currentRoom.value?.room_no || loc.value.room || ""}`.trim()));

function finish(text, target) {
  if (target.path !== route.path) rememberSaved(text);
  else showNotice(text);
  return router.push(target);
}

// 保存成功：回到来的地方并提示；"保存并登记下一间"跳到本月下一间在住但未登记的房间，没有了就回去并说明。
async function onSaved({ data, room, next }) {
  rows.data = data;
  summary.reload();
  const label = findRoom(roomOptions.data || [], room)?.room_no || room;
  if (!next) {
    board.reload();
    return finish(savedText(label), backTarget());
  }
  let fresh = null;
  try { fresh = await board.reload(); } catch (error) { fresh = null; }
  const target = fresh ? nextUnregistered(fresh.rooms, room) : null;
  if (target) {
    showNotice(savedText(label));
    return router.push({ path: route.path, query: nextQuery(route.query, target.room_no || target.name) });
  }
  return finish(fresh ? savedText(label, { allDone: true }) : `${savedText(label)}，下一间读取失败，请回到列表继续`, backTarget());
}

watch(period, reloadPeriodData);
watch(statusFilter, (value) => { if (value === "open") board.reload(); });
</script>

<template>
  <div class="space-y-4">
    <div v-if="notice" class="flex items-center justify-between rounded border border-green-200 bg-green-50 px-3 py-2 text-sm text-green-800" role="status" data-fee-notice>
      <span>{{ notice }}</span>
      <button type="button" class="text-xs text-green-700 hover:underline" @click="showNotice('')">关闭</button>
    </div>

    <!-- 内页：新增 / 编辑某个房间某个月的费用 -->
    <template v-if="view !== 'list'">
      <div class="flex flex-wrap items-center justify-between gap-2" data-fee-head>
        <nav aria-label="面包屑" class="text-xs text-gray-500">
          <button type="button" class="hover:underline" @click="goBoard">宿舍信息管理</button>
          <span class="mx-1">›</span>
          <button type="button" class="hover:underline" data-crumb-list @click="goList">月度登记</button>
          <span class="mx-1">›</span>
          <span class="text-gray-800">{{ crumbTitle }}</span>
        </nav>
        <Button variant="subtle" data-fee-back @click="goBack">← {{ backText }}</Button>
      </div>
      <Card v-if="loadError" title="加载失败" data-fee-error>
        <p class="text-sm text-red-600">房间或本期数据加载失败，请稍后重试。</p>
      </Card>
      <Card v-else-if="roomMissing" title="找不到这个房间" data-fee-missing>
        <p class="mb-3 text-sm text-gray-600">没有找到房间「{{ route.query.room }}」，它可能已停用或地址有误。</p>
        <Button variant="solid" @click="goBack">{{ backText }}</Button>
      </Card>
      <p v-else-if="!formReady" class="text-sm text-gray-500">加载中...</p>
      <FeeForm
        v-else :key="formKey" :period="period" :room="loc.room" :mode="view" :rooms="roomOptions.data"
        :employees="options.data" :records="rows.data" @saved="onSaved" @cancel="goBack"
      />
    </template>

    <!-- 列表 -->
    <template v-else>
      <AccommodationTabs />
      <div v-if="loc.from && !loc.fromList" class="text-xs">
        <button type="button" class="text-gray-600 hover:underline" data-list-origin @click="toOrigin">← {{ backText }}</button>
      </div>
      <Card v-if="statusFilter === 'open'" :title="`${period} 在住但还没登记费用的房间`" data-open-rooms>
        <template #actions><Button variant="subtle" data-open-clear @click="statusFilter = ''">显示全部</Button></template>
        <p v-if="board.loading && !board.data" class="text-sm text-gray-500">加载中...</p>
        <p v-else-if="board.error" class="text-sm text-red-600">房间状态加载失败，请稍后重试。</p>
        <p v-else-if="!openRooms.length" class="text-sm text-gray-500">本期在住的房间都已登记费用。</p>
        <template v-else>
          <p class="mb-2 text-xs text-gray-500">共 {{ openRooms.length }} 间；点房间号进入该房间的登记页，登记完可以直接「保存并登记下一间」。</p>
          <div class="flex flex-wrap gap-2">
            <router-link v-for="room in openRooms" :key="room.name" :to="editTo(room.room_no)" class="rounded border border-amber-200 bg-amber-50 px-3 py-1.5 text-sm text-amber-800 no-underline hover:bg-amber-100">
              {{ room.room_no }}<span v-if="room.employee_name" class="ml-1 text-xs text-amber-700">{{ room.employee_name }}</span>
            </router-link>
          </div>
        </template>
      </Card>
      <div class="grid gap-4 xl:grid-cols-[minmax(0,1fr)_420px]">
        <Card title="当月费用管理" subtitle="按基础信息中的有效入住关系登记费用；个人承担与公司承担相加后自动形成房间总费用">
          <div class="flex flex-wrap items-center gap-2 mb-4">
            <span class="text-sm text-gray-500">会计期间</span>
            <input type="month" v-model="period" class="border border-gray-300 rounded px-3 py-1.5 text-sm" />
            <span class="flex-1"></span>
            <router-link :to="newTo" class="rounded bg-[#1A2130] px-3 py-1.5 text-sm text-white no-underline hover:bg-[#2B3445]" data-fee-new>新增登记</router-link>
          </div>
          <div v-if="board.loading && !board.data" class="text-gray-500 text-sm py-4">加载中...</div>
          <p v-else-if="board.error" class="py-4 text-sm text-red-600">房间状态加载失败，请稍后重试。</p>
          <div v-else class="overflow-x-auto">
            <table class="w-full min-w-[640px] text-sm" data-fee-rooms>
              <thead class="text-gray-500 border-b"><tr>
                <th class="text-left px-3 py-2">房间号</th><th class="text-left px-3 py-2">房型</th><th class="text-left px-3 py-2">状态</th><th class="text-left px-3 py-2">入住人</th>
                <th class="text-right px-3 py-2">个人承担</th><th class="text-right px-3 py-2">公司承担</th><th class="text-right px-3 py-2">合计</th><th class="text-right px-3 py-2">操作</th>
              </tr></thead>
              <tbody>
                <tr v-for="room in listRooms" :key="room.name" class="border-b last:border-0 hover:bg-gray-50">
                  <td class="px-3 py-2 font-medium">{{ room.room_no }}</td>
                  <td class="px-3 py-2">{{ room.room_type || "—" }}</td>
                  <td class="px-3 py-2">{{ room.status }}</td>
                  <td class="px-3 py-2">{{ room.employee_name || "—" }}</td>
                  <template v-if="feeCells(room).registered">
                    <td class="text-right px-3 py-2 tabular-nums">{{ fmt(feeCells(room).personal) }}</td>
                    <td class="text-right px-3 py-2 tabular-nums">{{ fmt(feeCells(room).company) }}</td>
                    <td class="text-right px-3 py-2 font-medium tabular-nums">{{ fmt(feeCells(room).total) }}</td>
                  </template>
                  <td v-else class="text-center px-3 py-2 text-amber-700" colspan="3" data-unregistered>未登记</td>
                  <td class="text-right px-3 py-2"><router-link :to="editTo(room.room_no)" class="text-xs text-blue-600 hover:underline" data-fee-edit>{{ room.registered ? "编辑" : "登记" }}</router-link></td>
                </tr>
                <tr v-if="!listRooms.length"><td colspan="8" class="text-center text-gray-400 py-6">{{ statusFilter === "open" ? "本期在住的房间都已登记费用" : "还没有房间" }}</td></tr>
              </tbody>
            </table>
          </div>
        </Card>

        <Card title="公司承担费用科目汇总" subtitle="按人员信息中的费用科目汇总本期公司承担部分">
          <div v-if="summary.loading" class="text-gray-500 text-sm py-4">加载中...</div>
          <table v-else class="w-full text-sm">
            <thead class="text-gray-500 border-b"><tr>
              <th class="text-left px-3 py-2">费用科目</th><th class="text-right px-3 py-2">房租</th>
              <th class="text-right px-3 py-2">水费</th><th class="text-right px-3 py-2">电费</th><th class="text-right px-3 py-2">小计</th>
            </tr></thead>
            <tbody>
              <tr v-for="s in summaryRows" :key="s.expense_account_category" class="border-b last:border-0">
                <td class="px-3 py-2">{{ s.expense_account_category }}</td>
                <td class="text-right px-3 py-2 tabular-nums">{{ fmt(s.company_rent_amount) }}</td>
                <td class="text-right px-3 py-2 tabular-nums">{{ fmt(s.company_water_amount) }}</td>
                <td class="text-right px-3 py-2 tabular-nums">{{ fmt(s.company_electricity_amount) }}</td>
                <td class="text-right px-3 py-2 font-medium tabular-nums">{{ fmt(s.company_total_amount) }}</td>
              </tr>
            </tbody>
            <tfoot><tr class="border-t bg-gray-50 font-semibold">
              <td class="px-3 py-2">合计</td>
              <td class="text-right px-3 py-2 tabular-nums">{{ fmt(summaryTotal.company_rent_amount) }}</td>
              <td class="text-right px-3 py-2 tabular-nums">{{ fmt(summaryTotal.company_water_amount) }}</td>
              <td class="text-right px-3 py-2 tabular-nums">{{ fmt(summaryTotal.company_electricity_amount) }}</td>
              <td class="text-right px-3 py-2 tabular-nums">{{ fmt(summaryTotal.company_total_amount) }}</td>
            </tr></tfoot>

          </table>
        </Card>
      </div>

      <Card title="本期宿舍费用明细">
        <p v-if="errMsg" class="mb-2 text-red-600 text-xs" role="alert">{{ errMsg }}</p>
        <div v-if="rows.loading" class="text-gray-500 text-sm py-4">加载中...</div>
        <div v-else class="overflow-x-auto">
          <table class="w-full min-w-[1280px] text-sm">
            <thead class="text-gray-500 border-b"><tr>
              <th class="text-left px-3 py-2">房间号</th><th class="text-left px-3 py-2">入住人</th><th class="text-left px-3 py-2">费用科目</th>
              <th class="text-right px-3 py-2">个人房租</th><th class="text-right px-3 py-2">个人水费</th><th class="text-right px-3 py-2">个人电费</th><th class="text-right px-3 py-2">个人承担费用</th>
              <th class="text-right px-3 py-2">公司房租</th><th class="text-right px-3 py-2">公司水费</th><th class="text-right px-3 py-2">公司电费</th><th class="text-right px-3 py-2">公司承担费用</th>
              <th class="text-right px-3 py-2">总费用</th><th class="text-right px-3 py-2">操作</th>
            </tr></thead>
            <tbody>
              <tr v-for="d in rows.data || []" :key="d.name" class="border-b last:border-0 hover:bg-gray-50">
                <td class="px-3 py-2">{{ d.room_no }}</td>
                <td class="px-3 py-2">{{ occupantName(d) }}</td>
                <td class="px-3 py-2">{{ d.expense_account_category || "未设置" }}</td>
                <td class="text-right px-3 py-2 tabular-nums">{{ fmt(d.personal_rent_amount) }}</td>
                <td class="text-right px-3 py-2 tabular-nums">{{ fmt(d.personal_water_amount) }}</td>
                <td class="text-right px-3 py-2 tabular-nums">{{ fmt(d.personal_electricity_amount) }}</td>
                <td class="text-right px-3 py-2 font-medium tabular-nums">{{ fmt(d.personal_total_amount) }}</td>
                <td class="text-right px-3 py-2 tabular-nums">{{ fmt(d.company_rent_amount) }}</td>
                <td class="text-right px-3 py-2 tabular-nums">{{ fmt(d.company_water_amount) }}</td>
                <td class="text-right px-3 py-2 tabular-nums">{{ fmt(d.company_electricity_amount) }}</td>
                <td class="text-right px-3 py-2 font-medium tabular-nums">{{ fmt(d.company_total_amount) }}</td>
                <td class="text-right px-3 py-2 font-medium tabular-nums">{{ fmt(d.total_amount) }}</td>
                <td class="text-right px-3 py-2 whitespace-nowrap">
                  <router-link :to="editTo(d.room_no)" class="mr-3 text-xs text-blue-600 hover:underline">编辑</router-link>
                  <button v-if="isSysMgr" @click="del(d.name)" class="text-red-600 hover:underline text-xs">删除</button>
                </td>
              </tr>
              <tr v-if="!(rows.data || []).length"><td colspan="13" class="text-center text-gray-400 py-6">本期暂无宿舍费用，点「新增登记」或上方房间的「登记」开始</td></tr>
            </tbody>
            <tfoot v-if="(rows.data || []).length"><tr class="border-t font-medium">
              <td class="px-3 py-2" colspan="3">合计</td>
              <td class="text-right px-3 py-2 tabular-nums">{{ fmt(sumField("personal_rent_amount")) }}</td>
              <td class="text-right px-3 py-2 tabular-nums">{{ fmt(sumField("personal_water_amount")) }}</td>
              <td class="text-right px-3 py-2 tabular-nums">{{ fmt(sumField("personal_electricity_amount")) }}</td>
              <td class="text-right px-3 py-2 tabular-nums">{{ fmt(sumField("personal_total_amount")) }}</td>
              <td class="text-right px-3 py-2 tabular-nums">{{ fmt(sumField("company_rent_amount")) }}</td>
              <td class="text-right px-3 py-2 tabular-nums">{{ fmt(sumField("company_water_amount")) }}</td>
              <td class="text-right px-3 py-2 tabular-nums">{{ fmt(sumField("company_electricity_amount")) }}</td>
              <td class="text-right px-3 py-2 tabular-nums">{{ fmt(sumField("company_total_amount")) }}</td>
              <td class="text-right px-3 py-2 tabular-nums">{{ fmt(sumField("total_amount")) }}</td>
              <td></td>
            </tr></tfoot>
          </table>
        </div>
      </Card>
    </template>
  </div>
</template>
