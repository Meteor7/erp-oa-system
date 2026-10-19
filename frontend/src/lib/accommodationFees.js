// 宿舍「月度费用登记」(/accommodation/monthly) 的地址约定和纯逻辑：列表 / 新增 / 编辑三个视图，
// 新增 / 编辑是单独的内页（和报销、考勤、采购一样），返回回到来的地方。不依赖页面，方便单元测试。
//
// 地址：
//   ?view=list（默认，可省略）  &period=YYYY-MM  &status=open（只看在住但未登记的房间）
//   ?view=new&period=YYYY-MM
//   ?view=edit&room=<房间号 room_no>&period=YYYY-MM
//   内页带 from=：list = 从本页列表来（连同列表当时的 period / status 一起带着走）；站内路径 = 从那个页面来
//   （/accommodation 宿舍看板、/dashboard?tab=dorm 数据看板……）。列表自己的来源页记在 origin 里，内页往回走时带回去。
//   旧链接 ?room=A-302（没有 view）当作 view=edit 处理。
import { cleanQuery, fromValue, isInternalPath, originLabel, originOf, splitPath } from './navContext.js';
import { parsePeriodParam } from './period.js';

export const FEE_PATH = '/accommodation/monthly';
export const FEE_VIEWS = Object.freeze(['list', 'new', 'edit']);

const first = (value) => (Array.isArray(value) ? value[0] : value);
const text = (value) => String(first(value) ?? '').trim();

// ---------------------------------------------------------------- 地址解析
export function parseFeeLocation(query = {}) {
  const q = query || {};
  const room = text(q.room);
  const rawView = text(q.view);
  let view = FEE_VIEWS.includes(rawView) ? rawView : '';
  if (!view) view = room ? 'edit' : 'list';
  return {
    view,
    room: view === 'edit' ? room : '',
    period: parsePeriodParam(q.period),
    status: text(q.status) === 'open' ? 'open' : '',
    from: fromValue(q),
    fromList: fromValue(q) === 'list',
    // 列表自己的来源页：列表上记在 from 里，内页里记在 origin 里。
    origin: isInternalPath(text(q.origin)) ? text(q.origin) : originOf(q),
  };
}

// 列表当前的状态（月份、只看未登记、列表自己的来源页）：点进内页时带上，返回时原样恢复。
export function feeListState({ period = '', status = '', origin = '' } = {}) {
  return { period: parsePeriodParam(period), status: status === 'open' ? 'open' : '', origin: origin || '' };
}

function carried(state) {
  const { period, status, origin } = feeListState(state);
  return cleanQuery({ period, status, origin });
}

// 列表地址（返回列表、保存后回列表用）。
export function listQuery(state = {}) {
  const { period, status, origin } = feeListState(state);
  return cleanQuery({ view: 'list', period, status, from: origin });
}

// 列表 → 新增登记。
export function newQuery(state = {}) {
  return { view: 'new', from: 'list', ...carried(state) };
}

// 列表 → 编辑 / 登记某个房间；room 是房间号 room_no。
export function editQuery(room, state = {}) {
  return { view: 'edit', room: String(room), from: 'list', ...carried(state) };
}

// 内页里继续登记下一间：来源 / 筛选原样保留，只换房间。
export function nextQuery(query, room) {
  return { ...cleanQuery(query), view: 'edit', room: String(room) };
}

// 内页的"返回 / 取消 / 保存后"回到哪里：{ query }（留在本页）或 { path, query }（去别的页面）。
// from=list 回到同一个月份 / 筛选的列表；from=站内路径回到那里；没有来源回到该月份的列表。
export function feeReturnTarget(query = {}, fallbackPeriod = '') {
  const loc = parseFeeLocation(query);
  if (loc.fromList) return { query: listQuery({ period: loc.period || fallbackPeriod, status: loc.status, origin: loc.origin }) };
  if (loc.from) {
    const { path, query: target } = splitPath(loc.from);
    return { path, query: target };
  }
  return { query: listQuery({ period: loc.period || fallbackPeriod, status: loc.status }) };
}

const ORIGIN_NAMES = Object.freeze({ '/accommodation': '宿舍看板', '/dashboard': '首页' });

// "← 返回……"上的文字（内页和从别的页面点进来的列表都用）。
export function feeBackText(query = {}) {
  const loc = parseFeeLocation(query);
  if (loc.fromList || !loc.from) return '返回月度登记';
  const name = ORIGIN_NAMES[splitPath(loc.from).path] || originLabel({ from: loc.from });
  return name ? `返回${name}` : '返回上一页';
}

// ---------------------------------------------------------------- 房间：未登记口径、顺序、下一间
// 与后端 dashboard/people.py 的 alert.dorm_register（_unregistered_rooms）同口径：房间状态「入住」且本期没有任何费用记录。
export function isUnregistered(room) {
  return room?.status === '入住' && !room?.registered;
}

// 房号的排序：A-302、A609、B101 按字母再按数字（A609 < A1001），不是纯字符串比较。
export function compareRoomNo(a, b) {
  return String(a ?? '').localeCompare(String(b ?? ''), 'zh-Hans-CN', { numeric: true, sensitivity: 'base' });
}

export function sortRooms(rooms = []) {
  return [...(rooms || [])].sort((a, b) => compareRoomNo(a?.room_no ?? a?.name, b?.room_no ?? b?.name));
}

export function unregisteredRooms(rooms = []) {
  return sortRooms((rooms || []).filter(isUnregistered));
}

// 保存完某一间后的"下一间"：按房号排序，取排在它后面的第一间在住未登记的房间；后面没有了就从头找；都登记完返回 null。
// current 是刚保存的房间（房间记录名 = 房间号），无论看板数据里它是否已算登记演示员工177会再选它。
export function nextUnregistered(rooms = [], current = '') {
  const pending = unregisteredRooms(rooms).filter((room) => room.name !== current && room.room_no !== current);
  if (!pending.length) return null;
  const after = pending.find((room) => compareRoomNo(room.room_no ?? room.name, current) > 0);
  return after || pending[0];
}

export function findRoom(rooms = [], key = '') {
  const wanted = String(key ?? '');
  return (rooms || []).find((room) => room?.name === wanted || room?.room_no === wanted) || null;
}

// 列表里每一间房的费用格：已登记显示个人 / 公司 / 合计，未登记标「未登记」。
export function feeCells(room) {
  if (!room?.registered) return { registered: false, personal: null, company: null, total: null };
  return { registered: true, personal: Number(room.personal || 0), company: Number(room.company || 0), total: Number(room.total || 0) };
}

export function visibleRooms(rooms = [], status = '') {
  return status === 'open' ? unregisteredRooms(rooms) : sortRooms(rooms);
}

// ---------------------------------------------------------------- 表单：已有记录带出、入住人键
export const SPECIAL_OCCUPANTS = Object.freeze(['空', '客房', '午休室']);
export const AMOUNT_FIELDS = Object.freeze([
  'personal_rent_amount', 'personal_water_amount', 'personal_electricity_amount',
  'company_rent_amount', 'company_water_amount', 'company_electricity_amount',
]);

// 费用记录对应的入住人选项值（和 get_room_occupants 返回的 value 同一套："employee:<员工>" / "special:<类型>"）。
export function occupantKey(record) {
  if (!record) return '';
  return record.employee ? `employee:${record.employee}` : `special:${record.occupant_type || ''}`;
}

export function recordFor(records = [], room = '', selection = '') {
  if (!room || !selection) return null;
  return (records || []).find((record) => String(record?.room_no ?? '').trim() === room && occupantKey(record) === selection) || null;
}

// 本房间本期已有的记录（编辑时据此带出入住人和金额）。
export function recordsOfRoom(records = [], room = '') {
  return (records || []).filter((record) => String(record?.room_no ?? '').trim() === room);
}

// 带进表单的金额：0 显示为空（和空白表单一样）。
export function amountsOf(record) {
  const out = {};
  for (const field of AMOUNT_FIELDS) out[field] = Number(record?.[field] || 0) || '';
  return out;
}

// ---------------------------------------------------------------- 保存后的提示
export function savedText(roomNo, { allDone = false } = {}) {
  const base = `已保存 ${roomNo}`;
  return allDone ? `${base}，本月在住的房间都已登记` : base;
}

// 跨页面传一条"已保存"提示：内页保存后回到列表（或看板）时在那里显示，过一会儿过期，不会在以后的某次打开时冒出来。
export const NOTICE_TTL_MS = 15000;
let pending = null;

export function rememberSaved(message, now = Date.now()) {
  pending = message ? { message: String(message), at: now } : null;
}

export function takeSaved(now = Date.now()) {
  const current = pending;
  pending = null;
  return current && now - current.at <= NOTICE_TTL_MS ? current.message : '';
}
