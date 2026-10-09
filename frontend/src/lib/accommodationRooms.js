// 房间管理（/accommodation/master）的地址约定：列表一页，新增 / 编辑单独一页（内页）。
// 这里只放不依赖界面的纯逻辑，方便单元测试：地址解析、内页地址、返回目标、页面该显示哪个状态。
//
// 地址：
//   /accommodation/master                         列表（view=list 可省略），筛选 lease=expiring / leaver=1 / q=<搜索词> / status=<状态>
//   /accommodation/master?view=new                新增房间
//   /accommodation/master?view=edit&room=<记录名>  编辑房间（room 是房间记录名，宿舍看板里房间的 name）
//   内页再带 from=：
//     from=list           从本页列表来：同时带着列表当时的筛选，返回 / 保存后回到同一个筛选的列表
//     from=<站内路径>      从别的页面来（/accommodation、/dashboard?tab=dorm）：返回 / 保存后回到那个页面
//   origin=<站内路径>     列表自己是从别的页面点进来的（列表地址里的 from），内页往返时保存下来，返回列表时还原
//   旧链接 ?room=<记录名>（没有 view）仍然打开该房间的编辑页。
import { onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue';
import { firstValue, isInternalPath, originLabel, splitPath } from './navContext.js';

export const ROOMS_PATH = '/accommodation/master';
export const VIEWS = Object.freeze(['list', 'new', 'edit']);
export const ROOM_STATUSES = Object.freeze(['有人', '空置', '客房', '午休室']);
export const ROOM_FILTER_KEYS = Object.freeze(['lease', 'leaver', 'q', 'status']);

function text(value) {
  const first = firstValue(value);
  return first === undefined || first === null ? '' : String(first).trim();
}

// 列表筛选：地址 → 规范化状态（不认识的值丢掉）。
export function parseRoomFilters(query = {}) {
  const status = text(query?.status);
  return {
    lease: text(query?.lease) === 'expiring',
    leaver: text(query?.leaver) === '1',
    q: text(query?.q),
    status: ROOM_STATUSES.includes(status) ? status : '',
  };
}

// 筛选状态 → 地址参数（缺省值不写）。
export function roomFilterQuery(filters = {}) {
  return {
    ...(filters.lease ? { lease: 'expiring' } : {}),
    ...(filters.leaver ? { leaver: '1' } : {}),
    ...(text(filters.q) ? { q: text(filters.q) } : {}),
    ...(ROOM_STATUSES.includes(filters.status) ? { status: filters.status } : {}),
  };
}

// 地址里的 from：'list' 或站内路径，别的值忽略。
export function roomFrom(query = {}) {
  const from = text(query?.from);
  return from === 'list' || isInternalPath(from) ? from : '';
}

// 列表自己的来源页：列表地址里的 from=<路径>，或内页里记着的 origin=<路径>。
export function roomOrigin(query = {}) {
  const from = roomFrom(query);
  if (from && from !== 'list') return from;
  const origin = text(query?.origin);
  return from === 'list' && isInternalPath(origin) ? origin : '';
}

// 路由查询 → 页面状态。
export function parseRoomsLocation(query = {}) {
  const viewText = text(query?.view);
  const room = text(query?.room);
  let view = 'list';
  if (viewText === 'new') view = 'new';
  else if (viewText === 'edit') view = 'edit';
  else if (!viewText && room) view = 'edit';
  return { view, room: view === 'edit' ? room : '', from: roomFrom(query), origin: roomOrigin(query), filters: parseRoomFilters(query) };
}

// 列表地址（不写 view=list；筛选和来源页原样带上）。
export function roomListQuery(query = {}) {
  const origin = roomOrigin(query);
  return { ...(origin ? { from: origin } : {}), ...roomFilterQuery(parseRoomFilters(query)) };
}

// 从列表点进内页：带上列表当时的筛选和列表自己的来源，返回时原样恢复。
export function roomFormQuery(view, room, listQuery = {}) {
  const origin = roomOrigin(listQuery);
  return {
    view: view === 'edit' ? 'edit' : 'new',
    ...(view === 'edit' && room ? { room: String(room) } : {}),
    from: 'list',
    ...roomFilterQuery(parseRoomFilters(listQuery)),
    ...(origin ? { origin } : {}),
  };
}

export function roomFormLocation(view, room, listQuery = {}) {
  return { path: ROOMS_PATH, query: roomFormQuery(view, room, listQuery) };
}

// 宿舍看板的「编辑房间」：进房间内页，保存 / 返回回到宿舍看板。
export function boardEditLocation(room) {
  return { path: ROOMS_PATH, query: { view: 'edit', room: String(room || ''), from: '/accommodation' } };
}

// 内页「返回」/ 保存后去哪：from=list → 同一个筛选的列表；from=站内路径 → 那个页面；没有 from → 列表。
export function roomReturnLocation(query = {}) {
  const from = roomFrom(query);
  if (from && from !== 'list') {
    const { path, query: target } = splitPath(from);
    return { path, query: target };
  }
  return { path: ROOMS_PATH, query: roomListQuery(query) };
}

const BACK_LABELS = Object.freeze({
  '/accommodation': '宿舍看板',
  '/accommodation/monthly': '月度费用登记',
  '/accommodation/master': '房间管理',
});

// 「← 返回 xxx」里的名字。
export function roomBackLabel(query = {}) {
  const from = roomFrom(query);
  if (!from || from === 'list') return '房间管理';
  const known = BACK_LABELS[splitPath(from).path];
  if (known) return known;
  const { path, query: target } = splitPath(from);
  if (path === '/dashboard') return target.tab ? '数据看板' : '首页';
  return originLabel({ from }) || '上一页';
}

export function roomTitle(view, roomNo = '') {
  if (view === 'new') return '新增房间';
  return roomNo ? `编辑 ${roomNo}` : '编辑房间';
}

export function findRoom(rows, name) {
  const key = String(name || '');
  if (!key) return null;
  return (rows || []).find((row) => row.name === key) || null;
}

// 页面该显示什么：list / new / loading（房间列表还没加载完）/ missing（找不到这个房间）/ edit。
export function roomViewState(location, rows, { loading = false, failed = false } = {}) {
  if (location.view === 'list') return 'list';
  if (location.view === 'new') return 'new';
  if (!location.room) return 'missing';
  if (rows && findRoom(rows, location.room)) return 'edit';
  if (loading || (!rows && !failed)) return 'loading';
  return 'missing';
}

// ---------------------------------------------------------------- 保存成功提示
// 保存后回到来的地方（可能是别的页面），提示放在这个小的共享状态里，来源页读到后显示几秒。
export const NOTICE_MS = 4000;
export const roomNotice = reactive({ text: '', at: 0 });

export function savedText(roomNo) {
  return `已保存 ${String(roomNo || '').trim()}`.trim();
}

export function announceRoomSaved(roomNo, now = Date.now()) {
  roomNotice.text = savedText(roomNo);
  roomNotice.at = now;
}

export function clearRoomNotice() {
  roomNotice.text = '';
  roomNotice.at = 0;
}

// 提示还剩几毫秒；已经过期（或没有）是 0。
export function noticeRemaining(notice, now = Date.now(), ttl = NOTICE_MS) {
  if (!notice || !notice.text) return 0;
  return Math.max(0, ttl - (now - Number(notice.at || 0)));
}

// 页面里用：返回当前要显示的提示文字（几秒后自动清掉）。
export function useRoomNotice() {
  const shown = ref('');
  let timer = null;
  function sync() {
    if (timer) window.clearTimeout(timer);
    timer = null;
    const left = noticeRemaining(roomNotice);
    shown.value = left > 0 ? roomNotice.text : '';
    if (left > 0) timer = window.setTimeout(() => { clearRoomNotice(); shown.value = ''; }, left);
    else if (roomNotice.text) clearRoomNotice();
  }
  onMounted(sync);
  watch(() => roomNotice.at, sync);
  onBeforeUnmount(() => { if (timer) window.clearTimeout(timer); });
  return shown;
}
