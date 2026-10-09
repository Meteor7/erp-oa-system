import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import {
  amountsOf, compareRoomNo, editQuery, feeBackText, feeCells, feeListState, feeReturnTarget, findRoom, isUnregistered, listQuery,
  newQuery, nextQuery, nextUnregistered, occupantKey, parseFeeLocation, recordFor, recordsOfRoom, rememberSaved, savedText,
  sortRooms, takeSaved, unregisteredRooms, visibleRooms, NOTICE_TTL_MS,
} from "../src/lib/accommodationFees.js";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");
const targets = JSON.parse(read("../../rayher_hr_payroll/dashboard/targets.json")).targets;

const room = (no, status = "入住", registered = false, extra = {}) => ({ name: no, room_no: no, status, registered, ...extra });

// ---------------------------------------------------------------- 地址
test("address: list by default, new / edit by view, room is the room_no", () => {
  assert.deepEqual(parseFeeLocation({}), { view: "list", room: "", period: "", status: "", from: "", fromList: false, origin: "" });
  assert.equal(parseFeeLocation({ view: "list" }).view, "list");
  assert.equal(parseFeeLocation({ view: "new", period: "2026-10" }).view, "new");
  assert.equal(parseFeeLocation({ view: "new", period: "2026-10" }).period, "2026-10");
  const edit = parseFeeLocation({ view: "edit", room: "A-302", period: "2026-09" });
  assert.deepEqual([edit.view, edit.room, edit.period], ["edit", "A-302", "2026-09"]);
  // 不认识的 view 退回列表；列表和新增里的 room 不起作用
  assert.equal(parseFeeLocation({ view: "bogus" }).view, "list");
  assert.equal(parseFeeLocation({ view: "list", room: "A-302" }).room, "");
  assert.equal(parseFeeLocation({ view: "new", room: "A-302" }).room, "");
  // edit 没带房间：仍然是 edit（页面显示"找不到这个房间"），不是白屏
  assert.deepEqual([parseFeeLocation({ view: "edit" }).view, parseFeeLocation({ view: "edit" }).room], ["edit", ""]);
});

test("address: the old ?room= link from the board (no view) opens that room's inner page", () => {
  const legacy = parseFeeLocation({ period: "2026-10", room: "A-302" });
  assert.deepEqual([legacy.view, legacy.room, legacy.period], ["edit", "A-302", "2026-10"]);
});

test("address: only a valid month, status=open and internal sources are accepted", () => {
  assert.equal(parseFeeLocation({ period: "2026-13" }).period, "");
  assert.equal(parseFeeLocation({ period: "abc" }).period, "");
  assert.equal(parseFeeLocation({ status: "open" }).status, "open");
  assert.equal(parseFeeLocation({ status: "closed" }).status, "");
  assert.equal(parseFeeLocation({ view: "edit", room: "A1", from: "https://evil.example/x" }).from, "");
  assert.equal(parseFeeLocation({ view: "edit", room: "A1", from: "//evil.example" }).from, "");
  assert.equal(parseFeeLocation({ view: "edit", room: "A1", from: "/accommodation" }).from, "/accommodation");
  assert.equal(parseFeeLocation({ view: "edit", room: ["A-302", "B1"] }).room, "A-302");
});

test("address: the list's own source page is `from` on the list and `origin` on the inner page", () => {
  assert.equal(parseFeeLocation({ from: "/dashboard?tab=dorm" }).origin, "/dashboard?tab=dorm");
  assert.equal(parseFeeLocation({ view: "edit", room: "A1", from: "list", origin: "/dashboard?tab=dorm" }).origin, "/dashboard?tab=dorm");
  assert.equal(parseFeeLocation({ view: "edit", room: "A1", from: "list", origin: "https://x.example" }).origin, "");
  assert.equal(parseFeeLocation({ view: "edit", room: "A1", from: "list" }).fromList, true);
});

test("links from the list carry the month, the open filter and the list's own source", () => {
  const state = feeListState({ period: "2026-10", status: "open", origin: "/dashboard?tab=dorm" });
  assert.deepEqual(newQuery(state), { view: "new", from: "list", period: "2026-10", status: "open", origin: "/dashboard?tab=dorm" });
  assert.deepEqual(editQuery("A-302", state), { view: "edit", room: "A-302", from: "list", period: "2026-10", status: "open", origin: "/dashboard?tab=dorm" });
  assert.deepEqual(editQuery("B101", { period: "2026-09" }), { view: "edit", room: "B101", from: "list", period: "2026-09" });
  assert.deepEqual(listQuery(state), { view: "list", period: "2026-10", status: "open", from: "/dashboard?tab=dorm" });
  assert.deepEqual(listQuery({}), { view: "list" });
  // 脏数据不进地址
  assert.deepEqual(feeListState({ period: "x", status: "zzz", origin: "" }), { period: "", status: "", origin: "" });
});

// ---------------------------------------------------------------- 返回
test("return target: back to the same month / filter list, or the page it came from", () => {
  const fromList = { view: "edit", room: "A-302", from: "list", period: "2026-10", status: "open", origin: "/dashboard?tab=dorm" };
  assert.deepEqual(feeReturnTarget(fromList), { query: { view: "list", period: "2026-10", status: "open", from: "/dashboard?tab=dorm" } });
  assert.deepEqual(feeReturnTarget({ view: "edit", room: "A-302", from: "list" }, "2026-08"), { query: { view: "list", period: "2026-08" } });
  assert.deepEqual(feeReturnTarget({ view: "edit", room: "A-302", period: "2026-10", from: "/accommodation" }), { path: "/accommodation", query: {} });
  assert.deepEqual(feeReturnTarget({ view: "edit", room: "A-302", from: "/dashboard?tab=dorm" }), { path: "/dashboard", query: { tab: "dorm" } });
  // 没有来源（直接打开 / 旧链接）：回到那个月份的列表
  assert.deepEqual(feeReturnTarget({ view: "edit", room: "A-302", period: "2026-10" }), { query: { view: "list", period: "2026-10" } });
  assert.deepEqual(feeReturnTarget({ view: "edit", room: "不存在的" }, "2026-10"), { query: { view: "list", period: "2026-10" } });
});

test("back button text names the place it goes to", () => {
  assert.equal(feeBackText({ view: "edit", room: "A1", from: "list" }), "返回月度登记");
  assert.equal(feeBackText({ view: "edit", room: "A1" }), "返回月度登记");
  assert.equal(feeBackText({ view: "edit", room: "A1", from: "/accommodation" }), "返回宿舍看板");
  assert.equal(feeBackText({ view: "edit", room: "A1", from: "/dashboard?tab=dorm" }), "返回首页");
  assert.equal(feeBackText({ view: "edit", room: "A1", from: "/somewhere-else" }), "返回上一页");
});

test("dashboard targets still open the list: month + only-unregistered, nothing else needed", () => {
  const target = targets["dorm.monthly"];
  assert.equal(target.path, "/accommodation/monthly");
  const loc = parseFeeLocation({ ...target.query, period: "2026-10", status: "open" });
  assert.deepEqual([loc.view, loc.period, loc.status], ["list", "2026-10", "open"]);
});

// ---------------------------------------------------------------- 房间、下一间
test("unregistered = room status 入住 and no fee record yet (same as alert.dorm_register)", () => {
  assert.equal(isUnregistered(room("A1", "入住", false)), true);
  assert.equal(isUnregistered(room("A1", "入住", true)), false);
  assert.equal(isUnregistered(room("A1", "空置", false)), false);
  assert.equal(isUnregistered(room("A1", "客房", false)), false);
  assert.equal(isUnregistered(room("A1", "午休室", false)), false);
  assert.equal(isUnregistered(null), false);
});

test("rooms sort by building letter then room number, numerically", () => {
  assert.ok(compareRoomNo("A609", "A1001") < 0);
  assert.deepEqual(sortRooms([room("B101"), room("A1001"), room("A609"), room("A302")]).map((item) => item.room_no), ["A302", "A609", "A1001", "B101"]);
  assert.deepEqual(unregisteredRooms([room("B101"), room("A609", "入住", true), room("A302", "空置"), room("A1001")]).map((item) => item.room_no), ["A1001", "B101"]);
  assert.deepEqual(unregisteredRooms(undefined), []);
});

test("next room: the next unregistered occupied room after this one, wrapping, never the one just saved", () => {
  const rooms = [room("A302"), room("A609"), room("A1001"), room("B101", "入住", true), room("B205"), room("C1", "空置")];
  assert.equal(nextUnregistered(rooms, "A302").room_no, "A609");
  assert.equal(nextUnregistered(rooms, "A609").room_no, "A1001");
  assert.equal(nextUnregistered(rooms, "A1001").room_no, "B205");
  // B101 刚保存（看板数据里已登记）：往后找
  assert.equal(nextUnregistered(rooms, "B101").room_no, "B205");
  // 排在最后一间之后：从头找
  assert.equal(nextUnregistered(rooms, "B205").room_no, "A302");
  // 刚保存的房间在看板数据里还没算登记（数据没刷新）也不会再选它
  assert.equal(nextUnregistered([room("A302"), room("A609")], "A302").room_no, "A609");
  // 都登记完了
  assert.equal(nextUnregistered([room("A302", "入住", true), room("C1", "空置")], "A302"), null);
  assert.equal(nextUnregistered([room("A302")], "A302"), null);
  assert.equal(nextUnregistered([], "A302"), null);
  assert.equal(nextUnregistered(undefined, "A302"), null);
});

test("list rows: registered rooms show amounts, unregistered ones are marked; open filter keeps only 在住未登记", () => {
  assert.deepEqual(feeCells(room("A1", "入住", true, { personal: 100, company: 250.5, total: 350.5 })), { registered: true, personal: 100, company: 250.5, total: 350.5 });
  assert.deepEqual(feeCells(room("A2", "入住", false)), { registered: false, personal: null, company: null, total: null });
  const rooms = [room("B1", "空置", false), room("A2", "入住", false), room("A1", "入住", true)];
  assert.deepEqual(visibleRooms(rooms, "").map((item) => item.room_no), ["A1", "A2", "B1"]);
  assert.deepEqual(visibleRooms(rooms, "open").map((item) => item.room_no), ["A2"]);
  assert.equal(findRoom([room("A-302")], "A-302").room_no, "A-302");
  assert.equal(findRoom([room("A-302")], "不存在的"), null);
  assert.equal(findRoom(undefined, "A-302"), null);
});

// ---------------------------------------------------------------- 编辑：带出已登记的内容
test("editing a registered room picks up its record by occupant", () => {
  const records = [
    { name: "D1", room_no: "A302", employee: "EMP-1", occupant_type: "员工", personal_rent_amount: 300, personal_water_amount: 0, company_rent_amount: 700 },
    { name: "D2", room_no: "A302", employee: "EMP-2", occupant_type: "员工", company_water_amount: 20 },
    { name: "D3", room_no: "B101", employee: null, occupant_type: "空", company_rent_amount: 1500 },
  ];
  assert.equal(occupantKey(records[0]), "employee:EMP-1");
  assert.equal(occupantKey(records[2]), "special:空");
  assert.equal(occupantKey(null), "");
  assert.equal(recordFor(records, "A302", "employee:EMP-2").name, "D2");
  assert.equal(recordFor(records, "B101", "special:空").name, "D3");
  assert.equal(recordFor(records, "A302", "employee:EMP-9"), null);
  assert.equal(recordFor(records, "", "employee:EMP-1"), null);
  assert.deepEqual(recordsOfRoom(records, "A302").map((item) => item.name), ["D1", "D2"]);
  assert.deepEqual(amountsOf(records[0]), {
    personal_rent_amount: 300, personal_water_amount: "", personal_electricity_amount: "",
    company_rent_amount: 700, company_water_amount: "", company_electricity_amount: "",
  });
  assert.deepEqual(Object.values(amountsOf(null)), ["", "", "", "", "", ""]);
});

// ---------------------------------------------------------------- 提示
test("saved notice text and the cross-page hand-off expires", () => {
  assert.equal(savedText("A-302"), "已保存 A-302");
  assert.equal(savedText("A-302", { allDone: true }), "已保存 A-302，本月在住的房间都已登记");
  rememberSaved("已保存 A-302", 1000);
  assert.equal(takeSaved(1000 + 5), "已保存 A-302");
  assert.equal(takeSaved(1000 + 6), "", "shown once");
  rememberSaved("已保存 B101", 1000);
  assert.equal(takeSaved(1000 + NOTICE_TTL_MS + 1), "", "a stale notice never shows up later");
  rememberSaved("");
  assert.equal(takeSaved(), "");
});

// ---------------------------------------------------------------- 页面结构
const page = read("../src/pages/Accommodation.vue");
const form = read("../src/components/accommodation/FeeForm.vue");

test("monthly page: list + inner page by ?view, the form is no longer expanded in place", () => {
  assert.match(page, /parseFeeLocation\(route\.query\)/);
  assert.match(page, /<template v-if="view !== 'list'">/);
  assert.match(page, /<FeeForm\s+v-else :key="formKey"/);
  assert.match(page, /<AccommodationTabs \/>/);
  // 表单字段和保存接口都在内页组件里，列表页不再有
  assert.doesNotMatch(page, /v-model="form\./);
  assert.doesNotMatch(page, /save_accommodation/);
  assert.match(form, /save_accommodation/);
  assert.match(form, /get_room_occupants/);
  // 新增 / 编辑用 push（浏览器返回键回到列表），列表上改筛选仍由 bindRouteFilters 用 replace
  assert.match(page, /router\.push\(/);
  assert.doesNotMatch(page, /router\.replace\(/);
  assert.match(page, /bindRouteFilters\(\{\s*route,\s*router,\s*specs: \[periodRouteSpec\(\)/);
});

test("monthly page: list shows every room's registration, links into the inner page", () => {
  assert.match(page, /data-fee-rooms/);
  assert.match(page, /feeCells\(room\)\.registered/);
  assert.ok(page.includes("未登记"));
  assert.match(page, /data-fee-new>新增登记/);
  assert.match(page, /editQuery\(roomNo, listState\.value\)/);
  assert.match(page, /newQuery\(listState\.value\)/);
  // 原有的卡片、汇总、明细、删除都在
  assert.match(page, /data-open-rooms/);
  assert.match(page, /data-open-clear @click="statusFilter = ''"/);
  assert.ok(page.includes("公司承担费用科目汇总"));
  assert.ok(page.includes("本期宿舍费用明细"));
  assert.match(page, /remover = createResource\(\{ url: "rayher_hr_payroll\.api\.accommodation_entry\.delete_accommodation"/);
  assert.match(page, /get_dormitory_board/);
});

test("monthly inner page: breadcrumb, back, missing room, save / save-and-next / cancel", () => {
  assert.ok(page.includes("宿舍信息管理"));
  assert.ok(page.includes("月度登记"));
  assert.match(page, /aria-label="面包屑"/);
  assert.match(page, /data-fee-back @click="goBack"/);
  assert.ok(page.includes("找不到这个房间"));
  assert.match(page, /data-fee-missing/);
  assert.match(page, /roomMissing = computed\(\(\) => view\.value === "edit" && roomsReady\.value && !currentRoom\.value\)/);
  assert.match(form, /data-fee-save @click="save\(false\)">保存</);
  assert.match(form, /data-fee-save-next @click="save\(true\)">保存并登记下一间/);
  assert.match(form, /data-fee-cancel @click="emit\('cancel'\)">取消/);
  // 保存后：回来源并提示 / 下一间 / 都登记完回去并提示
  assert.match(page, /nextUnregistered\(fresh\.rooms, room\)/);
  assert.match(page, /savedText\(label, \{ allDone: true \}\)/);
  assert.match(page, /data-fee-notice/);
  assert.match(page, /setTimeout\(\(\) => \{ notice\.value = ""; \}, 5000\)/);
});

test("monthly inner form: unsaved changes are confirmed before leaving; a successful save marks it clean first", () => {
  assert.match(form, /useLeaveConfirm\(\(\) => isFormDirty\(fingerprint\(\), baseline\.value\)\)/);
  assert.match(form, /markClean\(\);\s*emit\("saved"/, "the snapshot is refreshed before the page navigates away");
  // 校验和提示文字原样
  assert.ok(form.includes("请先选择房间号"));
  assert.ok(form.includes("请选择入住人"));
  assert.ok(form.includes("保存失败"));
  assert.ok(form.includes("个人承担费用") && form.includes("公司承担费用") && form.includes("总费用"));
  // 编辑时房间固定在地址里，不能在表单里改
  assert.match(form, /:disabled="mode === 'edit'"/);
});
