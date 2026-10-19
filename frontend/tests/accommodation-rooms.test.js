import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import {
  NOTICE_MS, ROOMS_PATH, boardEditLocation, findRoom, noticeRemaining, parseRoomFilters, parseRoomsLocation, roomBackLabel,
  roomFilterQuery, roomFormLocation, roomFormQuery, roomListQuery, roomOrigin, roomReturnLocation, roomTitle, roomViewState, savedText,
} from "../src/lib/accommodationRooms.js";
import { allowLeave } from "../src/lib/leaveConfirm.js";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");
const targets = JSON.parse(readFileSync(new URL("../../rayher_hr_payroll/dashboard/targets.json", import.meta.url), "utf8")).targets;

const ROOMS = [{ name: "RM-0001", room_no: "A-302" }, { name: "RM-0002", room_no: "B-101" }];

// ---------------------------------------------------------------- 地址解析
test("rooms location: list by default, new, edit with a room, legacy ?room= opens the editor", () => {
  assert.equal(parseRoomsLocation({}).view, "list");
  assert.equal(parseRoomsLocation({ view: "list" }).view, "list");
  assert.equal(parseRoomsLocation({ view: "new" }).view, "new");
  assert.deepEqual(
    (({ view, room }) => ({ view, room }))(parseRoomsLocation({ view: "edit", room: "RM-0001" })),
    { view: "edit", room: "RM-0001" },
  );
  // 旧链接 /accommodation/master?room=RM-0001 仍然打开编辑页；明写 view=list 就是列表
  assert.deepEqual((({ view, room }) => ({ view, room }))(parseRoomsLocation({ room: "RM-0001" })), { view: "edit", room: "RM-0001" });
  assert.equal(parseRoomsLocation({ view: "list", room: "RM-0001" }).view, "list");
  assert.equal(parseRoomsLocation({ view: "nonsense" }).view, "list");
  // 数组参数取第一个；room 只在编辑页有意义
  assert.equal(parseRoomsLocation({ view: ["edit", "new"], room: ["RM-2", "RM-3"] }).room, "RM-2");
  assert.equal(parseRoomsLocation({ view: "new", room: "RM-0001" }).room, "");
});

test("list filters come from the address: lease=expiring, leaver=1, q, status; junk is dropped", () => {
  assert.deepEqual(parseRoomFilters({ lease: "expiring", leaver: "1", q: " A-3 ", status: "空置" }), { lease: true, leaver: true, q: "A-3", status: "空置" });
  assert.deepEqual(parseRoomFilters({ lease: "yes", leaver: "0", status: "随便" }), { lease: false, leaver: false, q: "", status: "" });
  assert.deepEqual(roomFilterQuery({ lease: true, leaver: false, q: "", status: "有人" }), { lease: "expiring", status: "有人" });
  assert.deepEqual(roomFilterQuery(parseRoomFilters({})), {});
});

test("dashboard dorm targets still land on filters the rooms page reads", () => {
  assert.equal(targets["dorm.lease"].path, ROOMS_PATH);
  assert.equal(targets["dorm.leaver"].path, ROOMS_PATH);
  assert.deepEqual(parseRoomFilters(targets["dorm.lease"].query), { lease: true, leaver: false, q: "", status: "" });
  assert.deepEqual(parseRoomFilters(targets["dorm.leaver"].query), { lease: false, leaver: true, q: "", status: "" });
  assert.equal(parseRoomsLocation(targets["dorm.lease"].query).view, "list");
  assert.equal(parseRoomsLocation(targets["dorm.leaver"].query).view, "list");
});

// ---------------------------------------------------------------- 内页地址与返回
test("opening a form from the list carries the list filter and the list's own origin", () => {
  assert.deepEqual(roomFormQuery("new", "", {}), { view: "new", from: "list" });
  assert.deepEqual(roomFormQuery("edit", "RM-0001", { leaver: "1" }), { view: "edit", room: "RM-0001", from: "list", leaver: "1" });
  assert.deepEqual(
    roomFormQuery("edit", "RM-0001", { lease: "expiring", q: "A", status: "空置", from: "/accommodation", junk: "x", view: "list" }),
    { view: "edit", room: "RM-0001", from: "list", lease: "expiring", q: "A", status: "空置", origin: "/accommodation" },
  );
  assert.deepEqual(roomFormLocation("edit", "RM-0002", { lease: "expiring" }), { path: ROOMS_PATH, query: { view: "edit", room: "RM-0002", from: "list", lease: "expiring" } });
  // 外站链接不能当来源
  assert.equal(roomOrigin({ from: "https://evil.example/x" }), "");
  assert.equal(roomOrigin({ from: "//evil.example" }), "");
  assert.deepEqual(roomFormQuery("new", "", { from: "//evil.example" }), { view: "new", from: "list" });
});

test("save / cancel from a list-origin form goes back to the same filtered list", () => {
  const query = roomFormQuery("edit", "RM-0001", { leaver: "1", q: "A", from: "/dashboard?tab=dorm" });
  assert.deepEqual(roomReturnLocation(query), { path: ROOMS_PATH, query: { from: "/dashboard?tab=dorm", leaver: "1", q: "A" } });
  // 没有任何筛选就是干净的列表地址
  assert.deepEqual(roomReturnLocation(roomFormQuery("new", "", {})), { path: ROOMS_PATH, query: {} });
  // 往返一次不丢：返回的列表再点编辑，筛选和来源页都还在
  const back = roomReturnLocation(query);
  assert.deepEqual(roomFormQuery("edit", "RM-0002", back.query), { view: "edit", room: "RM-0002", from: "list", leaver: "1", q: "A", origin: "/dashboard?tab=dorm" });
});

test("save / cancel from the board or the dashboard goes back there", () => {
  assert.deepEqual(boardEditLocation("RM-0001"), { path: ROOMS_PATH, query: { view: "edit", room: "RM-0001", from: "/accommodation" } });
  assert.deepEqual(roomReturnLocation(boardEditLocation("RM-0001").query), { path: "/accommodation", query: {} });
  assert.deepEqual(
    roomReturnLocation({ view: "edit", room: "RM-0001", from: "/dashboard?tab=dorm" }),
    { path: "/dashboard", query: { tab: "dorm" } },
  );
  assert.equal(roomBackLabel(boardEditLocation("RM-0001").query), "宿舍看板");
  assert.equal(roomBackLabel({ from: "/dashboard?tab=dorm" }), "数据看板");
  assert.equal(roomBackLabel({ from: "/dashboard" }), "首页");
  assert.equal(roomBackLabel({ from: "list" }), "房间管理");
  assert.equal(roomBackLabel({}), "房间管理");
  // 打开的内页没有来源（直接输入地址）：回到列表
  assert.deepEqual(roomReturnLocation({ view: "new" }), { path: ROOMS_PATH, query: {} });
});

test("list address carries filters and origin only (no view / room / form leftovers)", () => {
  assert.deepEqual(roomListQuery({ view: "edit", room: "RM-0001", from: "list", lease: "expiring", origin: "/accommodation", junk: "1" }), { from: "/accommodation", lease: "expiring" });
  assert.deepEqual(roomListQuery({}), {});
});

test("titles name the room being edited", () => {
  assert.equal(roomTitle("new"), "新增房间");
  assert.equal(roomTitle("edit", "A-302"), "编辑 A-302");
  assert.equal(roomTitle("edit"), "编辑房间");
});

// ---------------------------------------------------------------- 找不到房间不白屏
test("view state: unknown or missing rooms resolve to 'missing', not a blank page", () => {
  const edit = (room) => ({ view: "edit", room });
  assert.equal(roomViewState({ view: "list", room: "" }, null), "list");
  assert.equal(roomViewState({ view: "new", room: "" }, null, { loading: true }), "new");
  assert.equal(roomViewState(edit("RM-0001"), null, { loading: true }), "loading");
  assert.equal(roomViewState(edit("RM-0001"), undefined), "loading");
  assert.equal(roomViewState(edit("RM-0001"), ROOMS), "edit");
  assert.equal(roomViewState(edit("不存在的"), ROOMS), "missing");
  assert.equal(roomViewState(edit(""), ROOMS), "missing");
  assert.equal(roomViewState(edit("RM-0001"), null, { failed: true }), "missing");
  assert.equal(roomViewState(edit("不存在的"), []), "missing");
  assert.equal(findRoom(ROOMS, "RM-0002").room_no, "B-101");
  assert.equal(findRoom(ROOMS, "B-101"), null);
});

// ---------------------------------------------------------------- 保存提示
test("saved notice text and lifetime", () => {
  assert.equal(savedText("A-302"), "已保存 A-302");
  assert.equal(savedText(" A-302 "), "已保存 A-302");
  assert.equal(noticeRemaining({ text: "已保存 A-302", at: 1000 }, 1000), NOTICE_MS);
  assert.equal(noticeRemaining({ text: "已保存 A-302", at: 1000 }, 1000 + NOTICE_MS - 1), 1);
  assert.equal(noticeRemaining({ text: "已保存 A-302", at: 1000 }, 1000 + NOTICE_MS + 5), 0);
  assert.equal(noticeRemaining({ text: "", at: 1000 }, 1000), 0);
});

test("leaving a dirty form asks first, a clean one does not", () => {
  let asked = 0;
  assert.equal(allowLeave(false, () => { asked += 1; return false; }), true);
  assert.equal(asked, 0);
  assert.equal(allowLeave(true, () => { asked += 1; return false; }), false);
  assert.equal(allowLeave(true, () => true), true);
  assert.equal(asked, 1);
});

// ---------------------------------------------------------------- 页面接线（读源码）
const master = read("../src/pages/AccommodationMaster.vue");
const board = read("../src/pages/AccommodationBoard.vue");

test("master page: the form is its own page, the list no longer expands it in place", () => {
  assert.doesNotMatch(master, /v-if="editing"/);
  assert.doesNotMatch(master, /openedFromBoard/);
  assert.match(master, /parseRoomsLocation\(route\.query\)/);
  assert.match(master, /roomViewState\(location\.value, rows\.data/);
  assert.match(master, /<template v-if="isList">/);
  // 新增 / 编辑用 push 进内页，列表上改筛选仍是 replace（bindRouteFilters）
  assert.match(master, /router\.push\(roomFormLocation\('new', '', route\.query\)\)/);
  assert.match(master, /<router-link :to="editLocation\(row\)"[^>]*data-room-edit>编辑<\/router-link>/);
  assert.match(master, /roomFormLocation\('edit', row\.name, route\.query\)/);
  assert.match(master, /data-room-new @click="openNew">新增房间/);
  assert.doesNotMatch(master, /router\.replace/);
  assert.match(master, /bindRouteFilters\(/);
});

test("master page: breadcrumb, back, cancel, missing room, leave confirm, saved notice", () => {
  assert.match(master, /宿舍信息管理<\/router-link>/);
  assert.match(master, /data-room-crumb-list @click="goList">房间管理/);
  assert.match(master, /data-room-back @click="goBack">← 返回\{\{ backLabel \}\}/);
  assert.match(master, /data-room-cancel @click="goBack">取消/);
  assert.match(master, /data-room-missing/);
  assert.match(master, /找不到这个房间/);
  assert.match(master, /useLeaveConfirm\(isDirty\)/);
  assert.match(master, /announceRoomSaved\(form\.room_no\)/);
  assert.match(master, /router\.push\(roomReturnLocation\(route\.query\)\)/);
  assert.match(master, /data-saved-notice/);
  // 保存前先把"没有改动"记下，返回时不会再被拦下问一遍
  assert.match(master, /baseline\.value = snapshot\(\);\n\s+announceRoomSaved/);
});

test("master page keeps the list features and the saved API call", () => {
  assert.match(master, /rayher_hr_payroll\.api\.accommodation_master_entry\.save_room/);
  assert.match(master, /rayher_hr_payroll\.api\.accommodation_master_entry\.list_rooms/);
  assert.match(master, /rayher_hr_payroll\.api\.accommodation_master_entry\.list_checkout_history/);
  assert.match(master, /await saver\.submit\(\{ \.\.\.form \}\)/);
  assert.match(master, /errMsg\.value = '请填写房号'/);
  assert.match(master, /已演示员工166员工还登记在住/);
  assert.match(master, /已退宿记录/);
  assert.match(master, /<AccommodationTabs \/>/);
  assert.match(master, /keys: \['q', 'status'\]/);
});

test("board: 编辑房间 opens the room page and shows the saved notice on return", () => {
  assert.match(board, /router\.push\(boardEditLocation\(item\.name\)\)/);
  assert.match(board, /useRoomNotice\(\)/);
  assert.match(board, /data-saved-notice/);
  assert.doesNotMatch(board, /path: '\/accommodation\/master', query: \{ room: item\.name \}/);
});
