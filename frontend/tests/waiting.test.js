import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { STUCK_AFTER_DAYS, calendarDaysSince, isWaitingTooLong } from "../src/lib/waiting.js";
import { waitedDays as claimWaited } from "../src/lib/claimView.js";
import { waitedDays as paymentWaited } from "../src/lib/paymentView.js";
import { isSlow } from "../src/lib/attendanceFlow.js";
import { waitedDays as procurementWaited } from "../src/lib/procurementView.js";
import { todoRow, buildGroupHome } from "../src/lib/approvalGroup.js";

const at = (text) => Date.parse(text.replace(" ", "T"));
// 四个页面的单据起点字段写法一样：steps[].acted_on / submitted_on / creation。
const VIEWS = { claim: claimWaited, payment: paymentWaited, procurement: procurementWaited };
const since = (stamp) => ({ steps: [{ acted_on: stamp }] });

test("waiting days are calendar days: 10-09 23:30 to 10-12 00:30 is 3 days, not 2", () => {
  assert.equal(calendarDaysSince("2026-10-09 23:30:00", at("2026-10-12 00:30:00")), 3);
  assert.equal(calendarDaysSince("2026-10-09 00:30:00", at("2026-10-12 23:30:00")), 3);
  assert.equal(calendarDaysSince("2026-10-12 08:00:00", at("2026-10-12 23:59:00")), 0);
  assert.equal(calendarDaysSince("2026-10-12 23:59:00", at("2026-10-13 00:01:00")), 1);
  assert.equal(calendarDaysSince("2026-10-12T08:00:00", at("2026-10-12 23:59:00")), 0, "ISO strings work too");
  assert.equal(calendarDaysSince(at("2026-10-09 23:30:00"), at("2026-10-12 00:30:00")), 3, "so do timestamps");
});

test("waiting days are never negative and an unreadable start is null", () => {
  assert.equal(calendarDaysSince("2026-10-13 08:00:00", at("2026-10-12 10:00:00")), 0);
  assert.equal(calendarDaysSince("2027-01-01 08:00:00", at("2026-10-12 10:00:00")), 0);
  for (const bad of [undefined, null, "", "not a date"]) assert.equal(calendarDaysSince(bad, at("2026-10-12 10:00:00")), null);
});

test("waiting too long means strictly more than 3 days: exactly 3 is not, 4 is", () => {
  assert.equal(STUCK_AFTER_DAYS, 3);
  assert.deepEqual([0, 1, 2, 3].map(isWaitingTooLong), [false, false, false, false]);
  assert.deepEqual([4, 5, 30].map(isWaitingTooLong), [true, true, true]);
  for (const empty of [null, undefined, "", NaN]) assert.equal(isWaitingTooLong(empty), false);
  assert.equal(isWaitingTooLong("4"), true, "server numbers can arrive as strings");
  assert.equal(isWaitingTooLong("3"), false);
});

for (const [name, waitedDays] of Object.entries(VIEWS)) {
  test(`${name} page: same calendar rule, 3 days is not too long, 4 days is`, () => {
    // 正好 72 小时：3 天，不算等太久
    assert.equal(waitedDays(since("2026-10-09 12:00:00"), at("2026-10-12 12:00:00")), 3);
    assert.equal(isWaitingTooLong(waitedDays(since("2026-10-09 12:00:00"), at("2026-10-12 12:00:00"))), false);
    // 午夜前后：10-09 23:30 到 10-12 00:30 只隔 25 小时 + 两天，按日期算是 3 天
    const midnight = waitedDays(since("2026-10-09 23:30:00"), at("2026-10-12 00:30:00"));
    assert.equal(midnight, 3);
    assert.equal(isWaitingTooLong(midnight), false);
    // 差一个日历日就是 4 天，等太久
    const four = waitedDays(since("2026-10-08 23:30:00"), at("2026-10-12 00:30:00"));
    assert.equal(four, 4);
    assert.equal(isWaitingTooLong(four), true);
    // 满 24 小时的算法在这里会少算一天：10-08 20:00 到 10-12 10:00 只有 3 天 14 小时
    assert.equal(waitedDays(since("2026-10-08 20:00:00"), at("2026-10-12 10:00:00")), 4);
    assert.equal(waitedDays({ creation: "2026-10-13 08:00:00" }, at("2026-10-12 10:00:00")), 0, "never negative");
    assert.equal(waitedDays({}, at("2026-10-12 10:00:00")), null);
  });
}

test("the pages count the same document the same way", () => {
  const now = at("2026-10-12 00:30:00");
  const doc = { steps: [{ acted_on: "2026-10-09 23:30:00" }, { acted_on: null }], submitted_on: "2026-10-01 09:00:00" };
  assert.deepEqual(Object.values(VIEWS).map((fn) => fn(doc, now)), [3, 3, 3]);
});

test("the attendance centre flags a request after more than 3 calendar days, like every other page (leave, overtime, comp time and trips)", () => {
  const row = (stamp, extra = {}) => ({ name: "OA-1", steps: [{ acted_on: stamp }], ...extra });
  for (const type of ["请假申请", "加班申请", "调休申请", "出差申请"]) {
    assert.equal(isSlow(row("2026-10-09 12:00:00", { request_type: type }), at("2026-10-12 12:00:00")), false, `${type}: exactly 3 days`);
    assert.equal(isSlow(row("2026-10-09 23:30:00", { request_type: type }), at("2026-10-12 00:30:00")), false, `${type}: 10-09 23:30 to 10-12 00:30 is 3 days`);
    assert.equal(isSlow(row("2026-10-08 23:30:00", { request_type: type }), at("2026-10-12 00:30:00")), true, `${type}: 4 days`);
  }
  assert.equal(isSlow({ request_type: "请假申请" }, at("2026-10-12 12:00:00")), false, "no start time is never slow");
});

test("the approval-centre home flags a request only after more than 3 days", () => {
  const NOW = at("2026-10-12 10:00:00");
  const row = (modified) => ({ name: "OA-1", request_type: "购买申请", subject: "测试", workflow_status: "待审批", steps: [], modified, creation: modified });
  assert.equal(todoRow(row("2026-10-09 10:00:00"), { now: NOW }).warn, false, "3 days");
  assert.equal(todoRow(row("2026-10-08 23:00:00"), { now: NOW }).warn, true, "4 days");
  const stale = (pending) => buildGroupHome("request", { pending, now: NOW }).kpis.find((kpi) => kpi.key === "stale");
  assert.equal(stale({ 购买申请: [row("2026-10-09 10:00:00")] }).value, 0, "exactly 3 days is not counted");
  assert.equal(stale({ 购买申请: [row("2026-10-08 10:00:00")] }).value, 1);
  assert.equal(stale({}).label, "我这里卡住超过 3 天");
});

const SRC = fileURLToPath(new URL("../src", import.meta.url));
const walk = (dir) => readdirSync(dir).flatMap((entry) => {
  const full = join(dir, entry);
  return statSync(full).isDirectory() ? walk(full) : /\.(js|vue)$/.test(entry) ? [full] : [];
});
const sources = walk(SRC).map((file) => [file.slice(SRC.length + 1).replace(/\\/g, "/"), readFileSync(file, "utf8")]);

test("no page counts waiting days by 24-hour periods or compares them with a literal 3 (2026-10-13)", () => {
  assert.ok(sources.length > 100, "the scan found the source tree");
  const bad = [];
  for (const [file, text] of sources) {
    if (file === "lib/waiting.js") continue;
    const lines = text.split(/\r?\n/);
    lines.forEach((line, index) => {
      // 等待天数一律走 calendarDaysSince，不再自己 Math.floor((现在 - 起点) / 86400000)
      if (/waited|wait/i.test(line) && /\/\s*86400000/.test(line)) bad.push(`${file}:${index + 1} 24-hour wait ${line.trim()}`);
      // 等多久算久一律走 isWaitingTooLong / STUCK_AFTER_DAYS，不在页面里写 >= 3 / < 3
      if (/(waitedDays|approvalWait|waited_days|\bwait\b)/.test(line) && /(>=|<=|<|>)\s*3\b/.test(line)) bad.push(`${file}:${index + 1} literal 3 ${line.trim()}`);
    });
  }
  assert.deepEqual(bad, []);
});

test("every page that defines or shows waiting days takes the rule from waiting.js", () => {
  const text = (file) => sources.find(([name]) => name === file)[1];
  for (const file of ["lib/claimView.js", "lib/paymentView.js", "lib/procurementView.js"]) {
    assert.match(text(file), /import \{ calendarDaysSince \} from '\.\/waiting\.js'/, file);
    assert.match(text(file), /return calendarDaysSince\(since, now\)/, file);
  }
  for (const file of [
    "components/claim/ClaimWorkbench.vue", "components/procurement/PipelineBar.vue",
    "components/procurement/ProcHome.vue", "components/procurement/ProcList.vue", "components/procurement/PurchaseHome.vue",
    "pages/PaymentBoard.vue", "lib/approvalGroup.js", "lib/attendanceFlow.js",
  ]) assert.match(text(file), /isWaitingTooLong\(/, file);
  assert.match(text("components/attendance/AttendanceQueue.vue"), /isSlow\(row, props\.now\)/);
  assert.doesNotMatch(text("components/attendance/AttendanceQueue.vue"), /3 \* 1440/);
  assert.match(text("components/claim/ClaimWorkbench.vue"), /等超过 \{\{ STUCK_AFTER_DAYS \}\} 天/);
  // 催办的“至少等 3 天才能催”是另一条规则，不跟着改
  assert.match(text("lib/procurementView.js"), />= NUDGE_AFTER_DAYS/);
});
