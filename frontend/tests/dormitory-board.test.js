import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import {
  donutGradient, groupByBuilding, leaseMessage, leaseText, percent, roomNote, subjectRows, trendBars, useRows,
} from "../src/lib/dormitoryBoard.js";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");

test("lease alert reads like the demo and asks for a decision a week ahead", () => {
  const alert = { count: 35, expired_count: 0, same_date: true, earliest_date: "2026-10-14", days_left: 15 };
  assert.deepEqual(leaseMessage(alert, 35), {
    title: "35 间房的租约都在 2026-10-14 到期，还剩 15 天。",
    detail: "需要续租、退租的房间请在 10 月 7 日前定下来。",
  });
  const mixed = leaseMessage({ count: 2, expired_count: 1, same_date: false, earliest_date: "2026-10-03", days_left: 4 }, 35);
  assert.equal(mixed.title, "2 间房的租约在 60 天内到期，最早 2026-10-03（还剩 4 天）。另有 1 间房的租约已过期。");
  assert.equal(mixed.detail, "请尽快确定续租或退租。");
  assert.equal(leaseMessage(null, 35), null);
  assert.equal(leaseText({ lease_end_date: "2026-10-14", lease_days_left: 15 }), "2026-10-14 到期（剩 15 天）");
});

test("occupancy donut covers occupied, vacant, guest and nap rooms in order", () => {
  const gradient = donutGradient({ total: 35, 入住: 22, 空置: 8, 客房: 2, 午休室: 3 });
  assert.equal(gradient, "conic-gradient(#5470C6 0.0deg 226.3deg, #D98C4A 226.3deg 308.6deg, #8C96A8 308.6deg 329.1deg, #C3CAD6 329.1deg 360.0deg)");
  assert.equal(percent(22, 30, 0), "73%");
  assert.equal(percent(34483.6, 52765.6), "65.4%");
});

test("company-use and subject rows carry shares of what the company pays", () => {
  const cost = {
    company: 34483.6,
    uses: [
      { key: "员工", label: "员工住宿补贴", count: 21, unit: "人", amount: 21017.6 },
      { key: "空", label: "空置房间", count: 8, unit: "间", amount: 7996 },
    ],
    subjects: [{ label: "研发费用", amount: 16352 }, { label: "管理费用", amount: 14522.4 }],
  };
  const uses = useRows(cost);
  assert.equal(uses[0].text, "员工住宿补贴（21 人）");
  assert.equal(uses[1].share, "23%");
  const subjects = subjectRows(cost);
  assert.equal(subjects[0].width, "100.0%");
  assert.equal(subjects[1].share, "42%");
});

test("rooms group by building and notes explain who pays", () => {
  const groups = groupByBuilding([
    { building: "B 栋", status: "入住" }, { building: "其他", status: "空置" }, { building: "A 栋", status: "空置" },
  ]);
  assert.deepEqual(groups.map((group) => group.name), ["A 栋", "B 栋", "其他"]);
  assert.equal(groups[0].summary, "1 间 · 入住 0 · 空置 1");
  assert.equal(roomNote({ status: "入住", total: 2000, company: 1000, personal: 1000 }), "个人承担 50%，公司承担 50%。");
  assert.equal(roomNote({ status: "入住", total: 0 }), "所选月份还没有登记这间房的费用。");
  assert.equal(roomNote({ status: "午休室" }), "午休室是功能用房，费用全部由公司承担。");
});

test("monthly bars scale to the largest month", () => {
  const bars = trendBars([
    { period: "2026-06", registered: true, company: 30000, personal: 10000, total: 40000 },
    { period: "2026-07", registered: false, company: 0, personal: 0, total: 0 },
  ], 160);
  assert.deepEqual(bars.map((bar) => [bar.label, bar.companyHeight, bar.personalHeight]), [["6 月", 120, 40], ["7 月", 0, 0]]);
});

test("the dormitory board is the first dormitory page and links to the other two", () => {
  const router = read("../src/router.js");
  const app = read("../src/App.vue");
  const board = read("../src/pages/AccommodationBoard.vue");
  const master = read("../src/pages/AccommodationMaster.vue");
  const monthly = read("../src/pages/Accommodation.vue");
  assert.match(router, /path: '\/accommodation', component: \(\) => import\('\.\/pages\/AccommodationBoard\.vue'\)/);
  assert.match(app, /\{ to: '\/accommodation', label: '宿舍看板' \}/);
  assert.match(board, /get_dormitory_board/);
  assert.match(board, /query: \{ room: item\.name \}/);
  assert.match(board, /lease: 'expiring'/);
  for (const page of [board, master, monthly]) assert.match(page, /<AccommodationTabs \/>/);
  assert.match(master, /route\.query\.room/);
  // 租约到期清单 / 已离职仍占房、月份：都从地址读（bindRouteFilters），看板链接和数据看板链接共用
  assert.match(master, /queryText\(query, 'lease'\) === 'expiring'/);
  assert.match(monthly, /periodRouteSpec\(\)/);
  assert.match(monthly, /route\.query\.room/);
});
