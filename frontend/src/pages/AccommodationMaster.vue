<script setup>
import { computed, reactive, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { Badge, Button, Card, createResource } from 'frappe-ui';
import AccommodationTabs from '../components/AccommodationTabs.vue';
import { extractFrappeError } from '../lib/frappeError';
import { isFormDirty, useLeaveConfirm } from '../lib/leaveConfirm.js';
import { canEditHr } from '../lib/access.js';
import { bindRouteFilters, queryText } from '../lib/urlFilterState.js';
import {
  ROOMS_PATH, announceRoomSaved, findRoom, parseRoomFilters, parseRoomsLocation, roomBackLabel, roomFilterQuery,
  roomFormLocation, roomListQuery, roomReturnLocation, roomTitle, roomViewState, useRoomNotice,
} from '../lib/accommodationRooms.js';

// 房间管理：列表一页，新增 / 编辑单独一页（内页）。地址约定见 lib/accommodationRooms.js：
//   ?view=list（默认） | ?view=new | ?view=edit&room=<房间记录名>，内页带 from=list（回到同一个筛选的列表）或 from=<站内路径>。
const FILE_ACCEPT = '.pdf,.doc,.docx,.xls,.xlsx,.jpg,.jpeg,.png';
const PURPOSES = ['', '空', '客房', '午休室'];
const rows = createResource({
  url: 'rayher_hr_payroll.api.accommodation_master_entry.list_rooms',
  method: 'GET',
  auto: true,
});
const checkoutHistory = createResource({
  url: 'rayher_hr_payroll.api.accommodation_master_entry.list_checkout_history',
  method: 'GET',
  auto: true,
});
// 总经理、副总经理只读打开本页：不显示新增 / 编辑，也不取员工下拉（那个接口只给人事，取了会报没有权限）。
const canEdit = canEditHr();
const employees = createResource({
  url: 'rayher_hr_payroll.api.accommodation_entry.get_emp_options',
  method: 'GET',
  auto: canEdit,
});
const saver = createResource({ url: 'rayher_hr_payroll.api.accommodation_master_entry.save_room' });

const blank = () => ({
  room_no: '', room_type: '', lease_start_date: '', lease_end_date: '',
  monthly_rent: 0, paid_deposit: 0,
  rent_contract_attachment: '', deposit_attachment: '',
  employee: '', start_date: '', end_date: '',
  room_purpose: '', occupant_label: '', remark: '', is_active: 1,
});
const form = reactive(blank());
// 离职员工不能新安排入住；正在编辑的房间原入住人即使已离职也保留，方便填写退宿日期。
const originalEmployee = ref('');
const originalRoomNo = ref('');
const employeeChoices = computed(() => (employees.data || [])
  .filter((employee) => employee.status !== 'Left' || employee.name === originalEmployee.value));
const leftStillRegistered = computed(() => (rows.data || []).filter((row) => row.employee_left));
const saving = ref(false);
const leaving = ref(false);
const uploadingField = ref('');
const errMsg = ref('');
const route = useRoute();
const router = useRouter();
const savedNotice = useRoomNotice();

// ---------------------------------------------------------------- 地址 → 视图
const location = computed(() => parseRoomsLocation(route.query));
const viewState = computed(() => roomViewState(location.value, rows.data, { loading: rows.loading, failed: Boolean(rows.error) }));
// 保存成功后正在等列表刷新、回到来的地方：这段时间表单保持原样，不闪"找不到"。
const state = computed(() => (leaving.value ? (location.value.view === 'new' ? 'new' : 'edit') : viewState.value));
// 只读的人打开 ?view=new / edit 的地址也只看到列表。
const isList = computed(() => !canEdit || state.value === 'list');
const isForm = computed(() => canEdit && (state.value === 'new' || state.value === 'edit'));
const title = computed(() => roomTitle(location.value.view, originalRoomNo.value));
const backLabel = computed(() => roomBackLabel(route.query));
const loadError = computed(() => (rows.error ? extractFrappeError(rows.error, '房间资料加载失败') : ''));

// ---------------------------------------------------------------- 列表筛选（都在地址里：看板、数据看板的链接共用，刷新还在）
// ?lease=expiring 只看 60 天内到期或已过期的租约（宿舍看板"查看续租清单"、数据看板），
// ?leaver=1 只看已离职员工仍占房的房间（数据看板）；?q= 搜索词、?status= 房间状态。改了筛选地址跟着变（replace），点编辑进内页后回来还是同一个筛选。
const filters = reactive({ keyword: '', status: '', lease: false, leaver: false });
bindRouteFilters({
  route,
  router,
  specs: [{
    keys: ['lease', 'leaver'],
    read: (query) => ({ lease: queryText(query, 'lease') === 'expiring', leaver: queryText(query, 'leaver') === '1' }),
    snapshot: () => ({ lease: filters.lease, leaver: filters.leaver }),
    apply: (next) => { filters.lease = next.lease; filters.leaver = next.leaver; },
    toQuery: (next) => ({ ...(next.lease ? { lease: 'expiring' } : {}), ...(next.leaver ? { leaver: '1' } : {}) }),
    sources: [() => filters.lease, () => filters.leaver],
  }, {
    keys: ['q', 'status'],
    read: (query) => { const parsed = parseRoomFilters(query); return { q: parsed.q, status: parsed.status }; },
    snapshot: () => ({ q: filters.keyword, status: filters.status }),
    apply: (next) => { filters.keyword = next.q; filters.status = next.status; },
    toQuery: (next) => roomFilterQuery({ q: next.q, status: next.status }),
    sources: [() => filters.keyword, () => filters.status],
  }],
});
function leaseSoon(row) {
  if (!row.lease_end_date) return false;
  const days = (new Date(`${row.lease_end_date}T00:00:00`) - new Date(new Date().toDateString())) / 86400000;
  return days <= 60;
}
const filteredRows = computed(() => (rows.data || []).filter((row) => {
  const keyword = filters.keyword.trim().toLowerCase();
  const matchesKeyword = !keyword || [row.room_no, row.room_type, row.employee_name, row.room_purpose]
    .some((value) => String(value || '').toLowerCase().includes(keyword));
  return matchesKeyword && (!filters.status || row.occupancy_status === filters.status) && (!filters.lease || leaseSoon(row)) && (!filters.leaver || row.employee_left);
}).filter((row) => !(filters.lease || filters.leaver) || inUse(row)));
// 续租清单、已离职仍占房只看在用的房间：停用的房间宿舍看板不算，看板上的间数 / 人数也不算它（2026-10-13）。
function inUse(row) {
  return Number(row.is_active ?? 1) === 1;
}
const roomStats = computed(() => {
  const all = rows.data || [];
  return [
    { label: '房间总数', value: all.length, tone: 'text-gray-900' },
    { label: '有人入住', value: all.filter((row) => row.occupancy_status === '有人').length, tone: 'text-emerald-600' },
    { label: '当前空置', value: all.filter((row) => row.occupancy_status === '空置').length, tone: 'text-amber-600' },
    { label: '特殊用途', value: all.filter((row) => ['客房', '午休室'].includes(row.occupancy_status)).length, tone: 'text-blue-600' },
  ];
});

// ---------------------------------------------------------------- 内页：表单
const ready = ref(false);
const baseline = ref('');
const snapshot = () => JSON.stringify(form);
const isDirty = () => isForm.value && ready.value && !leaving.value && isFormDirty(snapshot(), baseline.value);
// 有改动时：取消 / 返回 / 面包屑 / 侧栏 / 浏览器后退、关闭刷新标签页，先确认。
useLeaveConfirm(isDirty);

function newRoom() {
  Object.assign(form, blank());
  originalEmployee.value = '';
  originalRoomNo.value = '';
  errMsg.value = '';
  baseline.value = snapshot();
  ready.value = true;
}

function edit(row) {
  Object.assign(form, blank(), {
    ...row,
    lease_start_date: row.lease_start_date || '',
    lease_end_date: row.lease_end_date || '',
    start_date: row.start_date || '',
    end_date: row.end_date || '',
    employee: row.employee || '',
    room_purpose: row.room_purpose || '',
  });
  originalEmployee.value = row.employee || '';
  originalRoomNo.value = row.room_no || '';
  errMsg.value = '';
  baseline.value = snapshot();
  ready.value = true;
}

// 进入内页（新增 / 编辑某个房间）时初始化表单一次；房间列表重新加载不会覆盖正在填的内容。
let initKey = '';
watch([state, () => location.value.view, () => location.value.room, () => rows.data], () => {
  if (leaving.value) return;
  const current = state.value;
  if (current === 'list' || current === 'missing') {
    initKey = '';
    ready.value = false;
    return;
  }
  if (current === 'loading') return;
  const key = current === 'new' ? 'new' : `edit:${location.value.room}`;
  if (key === initKey) return;
  initKey = key;
  if (current === 'new') newRoom();
  else edit(findRoom(rows.data, location.value.room));
}, { immediate: true });

// ---------------------------------------------------------------- 跳转（进内页用 push，浏览器返回键回到列表）
function openNew() {
  router.push(roomFormLocation('new', '', route.query));
}

function editLocation(row) {
  return roomFormLocation('edit', row.name, route.query);
}

function goBack() {
  router.push(roomReturnLocation(route.query));
}

function goList() {
  router.push({ path: ROOMS_PATH, query: roomListQuery(route.query) });
}

function selectEmployee() {
  if (form.employee) form.room_purpose = '';
}

function selectPurpose() {
  if (form.room_purpose) form.employee = '';
}

function money(value) {
  return Number(value || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function fileName(url) {
  if (!url) return '';
  const clean = String(url).split('?')[0];
  return decodeURIComponent(clean.split('/').pop() || clean);
}

function statusTheme(status) {
  if (status === '有人') return 'green';
  if (status === '空置') return 'gray';
  return 'blue';
}

async function uploadPrivateFile(fieldName, event) {
  const input = event.target;
  const file = input.files?.[0];
  input.value = '';
  if (!file) return;
  uploadingField.value = fieldName;
  errMsg.value = '';
  try {
    const body = new FormData();
    body.append('file', file);
    body.append('is_private', '1');
    const headers = {};
    if (window.csrf_token) headers['X-Frappe-CSRF-Token'] = window.csrf_token;
    const response = await fetch('/api/method/upload_file', {
      method: 'POST', credentials: 'same-origin', headers, body,
    });
    const payload = await response.json();
    const fileUrl = payload?.message?.file_url;
    if (!response.ok || !fileUrl) throw new Error(payload?.message || '文件上传失败');
    form[fieldName] = fileUrl;
  } catch (error) {
    errMsg.value = error?.message || '文件上传失败';
  } finally {
    uploadingField.value = '';
  }
}

async function save() {
  errMsg.value = '';
  if (!String(form.room_no || '').trim()) {
    errMsg.value = '请填写房号';
    return;
  }
  saving.value = true;
  let saved = false;
  try {
    await saver.submit({ ...form });
    saved = true;
  } catch (error) {
    errMsg.value = error?.messages?.[0] || error?.message || '保存失败';
  } finally {
    saving.value = false;
  }
  if (!saved) return;
  // 保存成功：表单算"没有改动"，刷新列表后回到来的地方，并在那里显示"已保存 房号"。
  leaving.value = true;
  baseline.value = snapshot();
  announceRoomSaved(form.room_no);
  await Promise.allSettled([rows.reload(), checkoutHistory.reload()]);
  try {
    await router.push(roomReturnLocation(route.query));
  } finally {
    leaving.value = false;
  }
}
</script>

<template>
  <div class="space-y-4">
    <AccommodationTabs />

    <template v-if="isList">
      <div v-if="savedNotice" class="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800" role="status" data-saved-notice>{{ savedNotice }}</div>
      <Card title="宿舍基本信息管理">
        <template v-if="canEdit" #actions><Button variant="solid" data-room-new @click="openNew">新增房间</Button></template>
        <p class="mb-4 text-sm text-gray-500">统一维护房间租赁、押金、附件及入住关系；每月租金是整套房间的总租金。退宿后记录进入下方历史，不会被新入住人覆盖。</p>
        <div v-if="filters.lease" class="mb-4 flex flex-wrap items-center gap-3 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          <span>续租清单：只显示在用房间里 60 天内到期或已过期的租约（{{ filteredRows.length }} 间）。</span>
          <button type="button" class="text-blue-600 hover:underline" @click="filters.lease = false">显示全部房间</button>
        </div>
        <div v-if="filters.leaver" class="mb-4 flex flex-wrap items-center gap-3 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800" data-leaver-filter>
          <span>已离职仍占房：只显示登记的入住人已离职的房间（{{ filteredRows.length }} 间），请核实后编辑并填写退宿日期。</span>
          <button type="button" class="text-blue-600 hover:underline" @click="filters.leaver = false">显示全部房间</button>
        </div>
        <div class="mb-4 grid grid-cols-2 gap-3 xl:grid-cols-4">
          <div v-for="stat in roomStats" :key="stat.label" class="rounded-xl border border-gray-200 bg-gradient-to-br from-white to-gray-50 px-4 py-3">
            <div class="text-xs text-gray-500">{{ stat.label }}</div><div class="mt-1 text-2xl font-semibold tabular-nums" :class="stat.tone">{{ stat.value }}</div>
          </div>
        </div>
        <div v-if="leftStillRegistered.length" class="mb-4 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          {{ leftStillRegistered.length }} 位已离职员工还登记在住：{{ leftStillRegistered.map((row) => `${row.room_no} ${row.employee_name}`).join('、') }}。<template v-if="canEdit">请核实后点"编辑"填写退宿日期。</template>
        </div>
        <div class="mb-4 flex flex-col gap-2 rounded-lg border border-gray-200 bg-gray-50 p-3 md:flex-row">
          <input v-model="filters.keyword" class="min-w-0 flex-1 rounded border border-gray-300 bg-white px-3 py-2 text-sm" placeholder="搜索房号、房型或入住人" />
          <select v-model="filters.status" class="rounded border border-gray-300 bg-white px-3 py-2 text-sm md:w-40"><option value="">全部状态</option><option value="有人">有人</option><option value="空置">空置</option><option value="客房">客房</option><option value="午休室">午休室</option></select>
        </div>

        <p v-if="loadError" class="mb-3 text-sm text-red-600">{{ loadError }}</p>
        <div v-if="rows.loading" class="py-6 text-center text-sm text-gray-500">加载中…</div>
        <div v-else class="max-h-[620px] overflow-auto rounded border border-gray-200">
          <table class="w-full min-w-[1850px] text-sm">
            <thead class="sticky top-0 z-20 bg-gray-50 text-gray-500 shadow-sm"><tr>
              <th class="sticky left-0 top-0 z-30 bg-gray-50 px-3 py-2 text-left">房号</th><th class="px-3 py-2 text-left">房型</th><th class="px-3 py-2 text-left">状态</th>
              <th class="px-3 py-2 text-left">承租日</th><th class="px-3 py-2 text-left">到期日</th><th class="px-3 py-2 text-right">每月租金</th><th class="px-3 py-2 text-right">已付押金</th>
              <th class="px-3 py-2 text-left">房租合同</th><th class="px-3 py-2 text-left">押金附件</th><th class="px-3 py-2 text-left">入住人</th><th class="px-3 py-2 text-left">入住日期</th><th class="px-3 py-2 text-left">退宿日期</th><th class="px-3 py-2 text-left">备注</th><th class="px-3 py-2 text-right">操作</th>
            </tr></thead>
            <tbody>
              <tr v-for="row in filteredRows" :key="row.name" class="border-t hover:bg-gray-50">
                <td class="sticky left-0 z-10 whitespace-nowrap bg-white px-3 py-2 font-semibold text-gray-900">{{ row.room_no }}</td><td class="whitespace-nowrap px-3 py-2">{{ row.room_type || '-' }}</td><td class="px-3 py-2"><Badge :theme="statusTheme(row.occupancy_status)">{{ row.occupancy_status }}</Badge></td>
                <td class="whitespace-nowrap px-3 py-2">{{ row.lease_start_date || '-' }}</td><td class="whitespace-nowrap px-3 py-2">{{ row.lease_end_date || '-' }}</td><td class="px-3 py-2 text-right">{{ money(row.monthly_rent) }}</td><td class="px-3 py-2 text-right">{{ money(row.paid_deposit) }}</td>
                <td class="max-w-[150px] px-3 py-2"><a v-if="row.rent_contract_attachment" :href="row.rent_contract_attachment" target="_blank" rel="noopener" class="block truncate text-xs text-blue-600">查看合同</a><span v-else class="text-gray-400">-</span></td>
                <td class="max-w-[150px] px-3 py-2"><a v-if="row.deposit_attachment" :href="row.deposit_attachment" target="_blank" rel="noopener" class="block truncate text-xs text-blue-600">查看附件</a><span v-else class="text-gray-400">-</span></td>
                <td class="whitespace-nowrap px-3 py-2">{{ row.employee_name || row.room_purpose || '-' }}<span v-if="row.employee_left" class="ml-1 rounded bg-amber-100 px-1.5 py-0.5 text-[11px] text-amber-700">已离职</span></td><td class="whitespace-nowrap px-3 py-2">{{ row.start_date || '-' }}</td><td class="whitespace-nowrap px-3 py-2">{{ row.end_date || '-' }}</td><td class="max-w-[220px] px-3 py-2">{{ row.remark || '-' }}</td><td class="px-3 py-2 text-right"><template v-if="canEdit"><router-link :to="editLocation(row)" class="text-xs text-blue-600 hover:underline" data-room-edit>编辑</router-link></template><span v-else class="text-xs text-gray-400">只读</span></td>
              </tr>
              <tr v-if="!filteredRows.length"><td colspan="14" class="py-8 text-center text-gray-400">暂无宿舍基础资料</td></tr>
            </tbody>
          </table>
        </div>
      </Card>

      <Card title="已退宿记录" subtitle="历史入住关系只读保留；同一房间再次入住会新增记录，不覆盖原记录">
        <div v-if="checkoutHistory.loading" class="py-6 text-center text-sm text-gray-500">加载中…</div>
        <div v-else class="max-h-[420px] overflow-auto rounded border border-gray-200">
          <table class="w-full min-w-[850px] text-sm">
            <thead class="sticky top-0 z-20 bg-gray-50 text-gray-500 shadow-sm"><tr>
              <th class="sticky left-0 top-0 z-30 bg-gray-50 px-3 py-2 text-left">房号</th><th class="px-3 py-2 text-left">入住人</th><th class="px-3 py-2 text-left">入住日期</th><th class="px-3 py-2 text-left">退宿日期</th><th class="px-3 py-2 text-left">备注</th>
            </tr></thead>
            <tbody>
              <tr v-for="record in checkoutHistory.data || []" :key="record.name" class="border-t hover:bg-gray-50">
                <td class="sticky left-0 z-10 bg-white px-3 py-2 font-semibold">{{ record.room }}</td><td class="px-3 py-2">{{ record.employee_name || record.employee }}</td><td class="px-3 py-2">{{ record.start_date || '-' }}</td><td class="px-3 py-2">{{ record.end_date }}</td><td class="px-3 py-2">{{ record.remark || '-' }}</td>
              </tr>
              <tr v-if="!(checkoutHistory.data || []).length"><td colspan="5" class="py-8 text-center text-gray-400">暂无已退宿记录</td></tr>
            </tbody>
          </table>
        </div>
      </Card>
    </template>

    <!-- 内页：新增 / 编辑房间 -->
    <template v-else>
      <div class="flex flex-wrap items-center gap-2 text-sm text-gray-500" data-room-crumbs>
        <router-link to="/accommodation" class="text-blue-600 hover:underline">宿舍信息管理</router-link>
        <span>›</span>
        <button type="button" class="text-blue-600 hover:underline" data-room-crumb-list @click="goList">房间管理</button>
        <span>›</span>
        <span class="text-gray-900">{{ title }}</span>
        <button type="button" class="ml-auto text-blue-600 hover:underline" data-room-back @click="goBack">← 返回{{ backLabel }}</button>
      </div>

      <div v-if="state === 'loading'" class="rounded-xl border border-gray-200 bg-white px-4 py-10 text-center text-sm text-gray-500">加载中…</div>
      <div v-else-if="state === 'missing'" class="space-y-3 rounded-xl border border-gray-200 bg-white px-4 py-10 text-center" data-room-missing>
        <div class="text-sm text-gray-700">{{ loadError || '找不到这个房间，可能已被删除或地址不对。' }}</div>
        <Button variant="solid" @click="goBack">返回{{ backLabel }}</Button>
      </div>

      <Card v-else :title="title">
        <div class="space-y-4" data-room-form>
          <div class="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
            <label class="flex flex-col"><span class="mb-1 text-xs text-gray-500">房号 *</span><input v-model="form.room_no" class="rounded border border-gray-300 px-3 py-2 text-sm" /></label>
            <label class="flex flex-col"><span class="mb-1 text-xs text-gray-500">房型</span><input v-model="form.room_type" class="rounded border border-gray-300 px-3 py-2 text-sm" /></label>
            <label class="flex flex-col"><span class="mb-1 text-xs text-gray-500">承租日</span><input v-model="form.lease_start_date" type="date" class="rounded border border-gray-300 px-3 py-2 text-sm" /></label>
            <label class="flex flex-col"><span class="mb-1 text-xs text-gray-500">到期日</span><input v-model="form.lease_end_date" type="date" class="rounded border border-gray-300 px-3 py-2 text-sm" /></label>
            <label class="flex flex-col"><span class="mb-1 text-xs text-gray-500">每月租金（房间总租金）</span><input v-model.number="form.monthly_rent" type="number" min="0" step="0.01" class="rounded border border-gray-300 px-3 py-2 text-sm" /></label>
            <label class="flex flex-col"><span class="mb-1 text-xs text-gray-500">已付押金</span><input v-model.number="form.paid_deposit" type="number" min="0" step="0.01" class="rounded border border-gray-300 px-3 py-2 text-sm" /></label>
            <label class="flex flex-col"><span class="mb-1 text-xs text-gray-500">入住人</span><select v-model="form.employee" class="rounded border border-gray-300 px-3 py-2 text-sm" @change="selectEmployee"><option value="">未关联员工</option><option v-for="employee in employeeChoices" :key="employee.name" :value="employee.name">{{ employee.employee_name }} · {{ employee.name }}{{ employee.status === 'Left' ? '（已离职）' : '' }}</option></select></label>
            <label class="flex flex-col"><span class="mb-1 text-xs text-gray-500">房间用途</span><select v-model="form.room_purpose" class="rounded border border-gray-300 px-3 py-2 text-sm" @change="selectPurpose"><option v-for="purpose in PURPOSES" :key="purpose || 'normal'" :value="purpose">{{ purpose || '普通员工宿舍' }}</option></select></label>
            <label class="flex flex-col"><span class="mb-1 text-xs text-gray-500">入住日期</span><input v-model="form.start_date" type="date" class="rounded border border-gray-300 px-3 py-2 text-sm" /></label>
            <label class="flex flex-col"><span class="mb-1 text-xs text-gray-500">退宿日期</span><input v-model="form.end_date" type="date" class="rounded border border-gray-300 px-3 py-2 text-sm" /></label>
            <label class="flex flex-col xl:col-span-2"><span class="mb-1 text-xs text-gray-500">备注</span><input v-model="form.remark" class="rounded border border-gray-300 px-3 py-2 text-sm" /></label>
          </div>

          <div class="grid grid-cols-1 gap-3 md:grid-cols-2">
            <div v-for="fileField in [{ key: 'rent_contract_attachment', label: '房租合同' }, { key: 'deposit_attachment', label: '押金附件' }]" :key="fileField.key" class="rounded border border-gray-200 bg-white p-3">
              <div class="mb-2 text-xs font-medium text-gray-600">{{ fileField.label }}</div>
              <div class="flex flex-wrap items-center gap-2">
                <a v-if="form[fileField.key]" :href="form[fileField.key]" target="_blank" rel="noopener" class="max-w-[260px] truncate text-xs text-blue-600 hover:underline">{{ fileName(form[fileField.key]) }}</a>
                <span v-else class="text-xs text-gray-400">未上传</span>
                <label class="cursor-pointer rounded border border-gray-300 px-2 py-1 text-xs hover:bg-gray-50">{{ uploadingField === fileField.key ? '上传中…' : '上传' }}<input type="file" class="hidden" :accept="FILE_ACCEPT" :disabled="Boolean(uploadingField)" @change="uploadPrivateFile(fileField.key, $event)" /></label>
                <button v-if="form[fileField.key]" type="button" class="text-xs text-red-600" @click="form[fileField.key] = ''">清除</button>
              </div>
            </div>
          </div>

          <p v-if="errMsg" class="text-sm text-red-600">{{ errMsg }}</p>
          <div class="flex gap-2"><Button variant="solid" :loading="saving" data-room-save @click="save">保存</Button><Button variant="subtle" data-room-cancel @click="goBack">取消</Button></div>
        </div>
      </Card>
    </template>
  </div>
</template>
