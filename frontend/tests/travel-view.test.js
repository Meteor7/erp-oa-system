import assert from "node:assert/strict";
import test from "node:test";
import {
  approveArgs, canPushTravel, canSeeAllTravel, dateRange, emptyTravelForm, isStaleError, normalizeScope, pushTarget, rejectProblem,
  rowAction, showMissing, travelBlockers, travelBucketOf, travelBuckets, travelFormFrom, travelScopes, travelStats, travelTimeline,
  travelView, tripDays, waitText, waitedDays,
} from "../src/lib/travelView.js";

test("the page is query driven like the claim pages: home, list, detail, new", () => {
  assert.equal(travelView({}), "home");
  assert.equal(travelView({ view: "list", scope: "todo" }), "list");
  assert.equal(travelView({ view: "new" }), "new");
  assert.equal(travelView({ draft: "OA-1" }), "new");
  assert.equal(travelView({ request: "OA-1" }), "detail");
  assert.equal(travelView({ request: "OA-1", view: "list" }), "detail", "notification links always open the document");
});

test("trip days count both ends and reject a return before the departure", () => {
  assert.equal(tripDays("2026-10-08", "2026-10-10"), 3);
  assert.equal(tripDays("2026-10-08", "2026-10-08"), 1);
  assert.equal(tripDays("2026-10-10", "2026-10-08"), 0);
  assert.equal(tripDays("", "2026-10-08"), 0);
});

test("the 还差 list names what is missing and only shows once the user started typing or tried to submit", () => {
  const form = emptyTravelForm();
  assert.equal(showMissing(form, false), false);
  assert.equal(showMissing(form, true), true);
  assert.equal(showMissing({ ...form, subject: "上海客户拜访" }, false), true);
  assert.deepEqual(travelBlockers(form), ["主题", "出差地点", "出发和返回日期", "出差事由"]);
  assert.deepEqual(travelBlockers({ ...form, subject: "a", travel_destination: "b", reason: "c", travel_start_date: "2026-10-10", travel_end_date: "2026-10-08" }), ["返回日期不能早于出发日期"]);
  assert.deepEqual(travelBlockers({ subject: "a", travel_destination: "b", reason: "c", travel_start_date: "2026-10-08", travel_end_date: "2026-10-10" }), []);
  assert.equal(showMissing({ ...form, project: "P1" }, false), false, "choosing only a project is not 'started typing'");
});

test("a draft fills the form back in", () => {
  assert.deepEqual(travelFormFrom({ subject: "北京参展", travel_destination: "北京", travel_start_date: "2026-10-20", travel_end_date: "2026-10-23", reason: "展会", project: "P1", extra: "x" }), {
    subject: "北京参展", travel_destination: "北京", travel_start_date: "2026-10-20", travel_end_date: "2026-10-23", reason: "展会", project: "P1",
  });
  assert.deepEqual(travelFormFrom(), emptyTravelForm());
});

test("home cards: 待我审批 / 草稿 / 审批中 / 已通过 with the longest wait", () => {
  const now = Date.parse("2026-10-01T08:00:00");
  const todo = [
    { name: "A", workflow_status: "待审批", submitted_on: "2026-09-29 09:00:00" },
    { name: "B", workflow_status: "待审批", submitted_on: "2026-09-30 09:00:00" },
  ];
  const mine = [
    { name: "C", workflow_status: "草稿" },
    { name: "D", workflow_status: "待审批", current_step_label: "副总经理" },
    { name: "E", workflow_status: "已完成" }, { name: "F", workflow_status: "已完成" },
  ];
  const cards = travelStats(todo, mine, now);
  assert.deepEqual(cards.map((card) => [card.key, card.count]), [["todo", 2], ["draft", 1], ["review", 1], ["approved", 2]]);
  assert.equal(cards[0].hint, "最久等了 2 天", "09-29 09:00 到 10-01 08:00 是两个日历日（原来按满 24 小时只算 1 天）");
  assert.equal(cards[2].hint, "在 副总经理");
  assert.deepEqual(cards[0].query, { view: "list", scope: "todo" });
  assert.equal(travelStats([], [], now)[0].hint, "没有要审批的");
  assert.deepEqual(travelBuckets(mine).map((bucket) => [bucket.key, bucket.count]), [["draft", 1], ["review", 1], ["approved", 2], ["back", 0]]);
  assert.equal(travelBucketOf({ workflow_status: "已拒绝" }), "back");
  assert.equal(waitText(0), "今天");
  assert.equal(waitText(2), "等了 2 天");
  assert.equal(waitedDays({ steps: [{ acted_on: "2026-09-30 10:00:00" }], submitted_on: "2026-09-20 10:00:00" }, now), 1, "the last action counts, not the submit date; 09-30 10:00 to 10-01 08:00 is one calendar day");
  // 按日历日期算，和数据看板同一个口径：10-09 23:30 到 10-12 00:30 是 3 天（满 24 小时只有 2 天），不会是负数
  assert.equal(waitedDays({ submitted_on: "2026-10-09 23:30:00" }, Date.parse("2026-10-12T00:30:00")), 3);
  assert.equal(waitedDays({ submitted_on: "2026-10-13 09:00:00" }, Date.parse("2026-10-12T10:00:00")), 0);
});

test("approvers get a 待我审批 list; 全部 is only for people who can see other people's documents", () => {
  assert.deepEqual(travelScopes({ canAll: false, todoCount: 2 }).map((item) => item.key), ["mine", "todo"]);
  assert.deepEqual(travelScopes({ canAll: true }).map((item) => item.key), ["mine", "todo", "all"]);
  assert.equal(normalizeScope("all", false), "mine");
  assert.equal(normalizeScope("all", true), "all");
  assert.equal(normalizeScope("todo"), "todo");
  assert.equal(normalizeScope(undefined), "mine");
  assert.equal(canSeeAllTravel(["Employee"], {}), false);
  assert.equal(canSeeAllTravel(["Employee", "Department Manager"], {}), false);
  assert.equal(canSeeAllTravel(["Employee"], { vice_manager: true }), false);
  assert.equal(canSeeAllTravel(["Employee", "Rayher Business Executive"], {}), true);
  assert.equal(canSeeAllTravel(["System Manager"], {}), true);
});

test("each list row offers one action: edit a draft, withdraw while approving, push when completed", () => {
  assert.equal(rowAction({ workflow_status: "草稿" }, true), "edit");
  assert.equal(rowAction({ workflow_status: "草稿" }, false), "detail");
  assert.equal(rowAction({ workflow_status: "已完成" }, true), "push");
  assert.equal(rowAction({ workflow_status: "已完成" }, false), "detail", "only the applicant pushes");
  assert.equal(rowAction({ workflow_status: "待审批", can_withdraw: true }, true), "withdraw");
  assert.equal(rowAction({ workflow_status: "待审批" }, true), "detail");
  assert.equal(canPushTravel({ workflow_status: "已完成" }, true), true);
  assert.equal(canPushTravel({ workflow_status: "待审批" }, true), false);
  assert.equal(pushTarget("claim"), "/approval/claim");
  assert.equal(pushTarget("payment"), "/approval/payment");
  assert.equal(dateRange({ travel_start_date: "2026-10-08", travel_end_date: "2026-10-10" }), "10-08 ~ 10-10");
});

test("approval timeline shows who acted when, and the note", () => {
  const timeline = travelTimeline({
    workflow_status: "待审批", current_step_index: 2,
    steps: [
      { step_index: 1, label: "直属主管", status: "已通过", mode: "approve", action_by: "u1", acted_on: "2026-09-30 10:20:33", note: "同意" },
      { step_index: 2, label: "副总经理", status: "待审批", mode: "approve" },
    ],
  });
  assert.deepEqual(timeline.map((item) => item.state), ["done", "now"]);
  assert.equal(timeline[0].sub, "已同意 · u1 · 2026-09-30 10:20");
  assert.equal(timeline[0].note, "同意");
  assert.equal(timeline[1].sub, "等待处理");
  const named = travelTimeline({ workflow_status: "已完成", steps: [
    { step_index: 1, label: "会签", status: "已通过", mode: "approve", action_by: "a@tests-x.example.invalid", action_by_name: "演示员工129", approved_by: ["a@tests-x.example.invalid"], approved_by_names: ["演示员工129"] },
    { step_index: 2, label: "会签", status: "已通过", mode: "approve", action_by: "", approved_by: ["b@tests-x.example.invalid", "history.2e7d2c03a9@tests-x.example.invalid"], approved_by_names: ["演示员工146", "演示员工157"] },
  ] });
  assert.equal(named[0].who, "演示员工129");
  assert.equal(named[1].who, "演示员工146、演示员工157");
  assert.equal(travelTimeline({ workflow_status: "已拒绝", steps: [{ step_index: 1, label: "直属主管", status: "已拒绝", note: "改期" }] })[0].state, "rejected");
});

test("approve / reject arguments carry the step the page saw; reject needs a reason", () => {
  assert.deepEqual(approveArgs({ name: "OA-1", current_step_key: "k1" }, "approve"), { name: "OA-1", action: "approve", note: "", reject_target: undefined, expected_step_key: "k1" });
  assert.deepEqual(approveArgs({ name: "OA-1", current_step_key: "k1" }, "reject", " 改期 "), { name: "OA-1", action: "reject", note: "改期", reject_target: "applicant", expected_step_key: "k1" });
  assert.equal(rejectProblem("  "), "请填写驳回原因");
  assert.equal(rejectProblem("改期"), "");
  assert.equal(isStaleError(new Error("单据已经变化，请刷新")), true);
  assert.equal(isStaleError(new Error("页面版本过旧")), true);
  assert.equal(isStaleError(new Error("别的错误")), false);
});
