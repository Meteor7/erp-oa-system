// 看板数字和点进去的页面对齐（人事 / 考勤 / 团队 / 个人 / 工时，2026-10-13）：前端这一半。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { awayToday } from "../src/lib/attendanceView.js";
import { staffLevel } from "../src/lib/dashboardView.js";
import {
  PERSONNEL_QUERY_KEYS, REMINDER_KINDS, decorateEmployees, departmentGroupMap, filterByUrlExtras, parsePersonnelQuery, personnelQueryOf,
} from "../src/lib/personnelView.js";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");
const TODAY = "2026-10-13";

// ---------------------------------------------------------------- 今天不在岗：服务端按今天查，一人一行
test("今天不在岗的列表一人一行：同一个人两张单只留一张，出差、审批中的不算", () => {
  const row = (extra) => ({ name: "OA-1", employee: "E1", employee_name: "南通工厂9", request_type: "请假申请", workflow_status: "已完成",
    from_date: "2026-10-12", to_date: "2026-10-14", ...extra });
  const rows = [
    row(),
    row({ name: "OA-2", request_type: "调休申请", from_date: "2026-10-13", to_date: "2026-10-13" }),   // 同一个人第二张：不重复
    row({ name: "OA-3", employee: "E2", employee_name: "演示员工146" }),
    row({ name: "OA-4", employee: "E3", request_type: "出差申请" }),                                   // 出差不算不在岗
    row({ name: "OA-5", employee: "E4", workflow_status: "待审批" }),
  ];
  assert.deepEqual(awayToday(rows, TODAY).map((item) => item.name), ["OA-1", "OA-3"]);
});

test("考勤中心的“今天不在岗”用服务端按今天查好的那批人，不再从最近 100 张里筛", () => {
  const view = read("../src/lib/attendanceView.js");
  assert.match(view, /today: \(\) => callApi\('attendance_entry\.list_attendance_away_today'/);
  const center = read("../src/pages/AttendanceCenter.vue");
  assert.match(center, /const loadToday = \(\) => guarded\('today', \(\) => api\.today\(\)/);
  assert.match(center, /all: everyone\.items, today: awayNow\.items/);
  assert.match(center, /if \(view\.value === 'list' && page\.value\.today && canViewAll\.value\) loadToday\(\);/);
  const list = read("../src/components/attendance/AttendanceList.vue");
  assert.match(list, /const base = computed\(\(\) => \(todayOnly\.value \? props\.sets\.today : props\.sets\[scope\.value\]\) \|\| \[\]\);/);
  assert.match(list, /todayOnly\.value \? props\.loaded\.today/);
});

// ---------------------------------------------------------------- 本月请假：按天，只算请假，调休单独
test("考勤中心首页的「N 月」按天、请假和调休分开两格，数字是服务端 month_hours 加起来（和看板同一个算法）", () => {
  // 2026-10-14：原来指标栏里的“本月请假”换成「N 月」概览的四格（请假 / 调休 / 加班 / 出差）
  const home = read("../src/components/attendance/AttendanceHome.vue");
  assert.doesNotMatch(home, /monthItem|data\.month\.hours|人天/);
  const lib = read("../src/lib/attendanceHome.js");
  assert.match(lib, /monthRows\(rows, item\.key, month\)\.reduce\(\(sum, row\) => sum \+ Number\(row\.month_hours \|\| 0\), 0\)/);
  // 看板卡片上的天数用同一个写法（四舍五入一位小数）
  assert.match(lib, /Math\.round\(Number\(hours \|\| 0\) \/ HOURS_PER_DAY \* 10\) \/ 10/);
  const dashboard = readFileSync(new URL("../../rayher_hr_payroll/dashboard/attendance.py", import.meta.url), "utf8");
  assert.match(dashboard, /ROUND_HALF_UP/);
  assert.match(dashboard, /_d1\(stats\["leave_days"\]\)/);
  assert.match(dashboard, /另有调休 \{_d1\(stats\['comp_days'\]\)\} 天/);
});

// ---------------------------------------------------------------- 团队日历的图例
test("团队日历图例和标色规则一致：至少 3 人且占 20% 橙，占 40% 红；出差不算缺人", () => {
  const block = read("../src/components/dashboard/DashBlock.vue");
  assert.match(block, /出差不算缺人/);
  assert.match(block, /至少 3 个且占 20% 以上标<b class="is-mid-t">橙<\/b>，占 40% 以上标<b class="is-low-t">红<\/b>/);
  assert.doesNotMatch(block, /缺 4 人以上/);
  // 规则本身：15 人缺 3 人 = 20% → 橙；缺 6 人 = 40% → 红；10 人缺 2 人不到 3 人 → 不标
  assert.equal(staffLevel(3, 15), "mid");
  assert.equal(staffLevel(6, 15), "low");
  assert.equal(staffLevel(2, 10), "");
});

// ---------------------------------------------------------------- 员工页：试用期 / 合同分开看
const ROWS = [
  { name: "E1", employee_name: "试用", department: "研发一部 - RAY", status: "Active", probation_end_date: "2026-10-20", archive_status: "已归档" },
  { name: "E2", employee_name: "合同", department: "研发一部 - RAY", status: "Active", first_contract_end_date: "2026-11-01", archive_status: "已归档" },
  { name: "E3", employee_name: "两样", department: "研发一部 - RAY", status: "Active", probation_end_date: "2026-10-25", first_contract_end_date: "2026-10-30", archive_status: "已归档" },
  { name: "E4", employee_name: "都不", department: "研发一部 - RAY", status: "Active", archive_status: "已归档" },
];
const ITEMS = decorateEmployees(ROWS, { today: TODAY, groupOf: departmentGroupMap([{ department_name: "研发一部 - RAY", group_name: "研发" }]) });
const names = (list) => list.map((item) => item.row.employee_name);

test("reminder=probation / contract 只列那一种到期，expiring 两种都列", () => {
  assert.deepEqual(REMINDER_KINDS, ["expiring", "probation", "contract"]);
  assert.deepEqual(names(filterByUrlExtras(ITEMS, { reminder: "expiring" }, TODAY)), ["试用", "合同", "两样"]);
  assert.deepEqual(names(filterByUrlExtras(ITEMS, { reminder: "probation" }, TODAY)), ["试用", "两样"]);
  assert.deepEqual(names(filterByUrlExtras(ITEMS, { reminder: "contract" }, TODAY)), ["合同", "两样"]);
  for (const reminder of REMINDER_KINDS) {
    assert.equal(parsePersonnelQuery({ reminder }).reminder, reminder);
    assert.deepEqual(personnelQueryOf(parsePersonnelQuery({ reminder })), { reminder });
  }
  assert.equal(parsePersonnelQuery({ reminder: "乱写" }).reminder, "");
  assert.ok(PERSONNEL_QUERY_KEYS.includes("reminder"));
});

test("员工页把 reminder 的种类接到筛选和地址上；总经理、副总经理只能看，新增、编辑只给人事", () => {
  const page = read("../src/pages/Personnel.vue");
  assert.match(page, /const reminderKind=ref\(""\);/);
  assert.match(page, /\{reminder:expiringOnly\.value\?reminderKind\.value:""\},today\)/);
  assert.match(page, /reminder:expiringOnly\.value\?\(reminderKind\.value\|\|"expiring"\):""/);
  assert.match(page, /reminderKind\.value=state\.reminder==="expiring"\?"":state\.reminder;/);
  assert.match(page, /watch\(expiringOnly,on=>\{if\(!on\)reminderKind\.value=""\}\);/);
  assert.match(page, /const canEdit=.*\["System Manager","HR User","HR Manager"\]/);
  assert.match(page, /<button v-if="canEdit" type="button" class="btn pri" data-new-emp/);
  assert.match(page, /<button v-if="canEdit&&!editing&&current"/);
});

// ---------------------------------------------------------------- 宿舍：续租清单只看在用的房间
test("续租清单、已离职仍占房只看在用的房间（和宿舍看板、看板卡片同一批）", () => {
  const page = read("../src/pages/AccommodationMaster.vue");
  assert.match(page, /\.filter\(\(row\) => !\(filters\.lease \|\| filters\.leaver\) \|\| inUse\(row\)\)\);/);
  assert.match(page, /function inUse\(row\) \{\n  return Number\(row\.is_active \?\? 1\) === 1;/);
  assert.match(page, /只显示在用房间里 60 天内到期或已过期的租约/);
});
