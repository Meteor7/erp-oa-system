import assert from "node:assert/strict";
import test from "node:test";

import {
  costPreviewTag,
  dashboardStatusTag,
  formatPreviewMonths,
  isPreviewMonth,
  previewMonthCount,
  yearPreviewNote,
} from "../src/lib/previewTags.js";

test("formatPreviewMonths lists months sorted, de-duplicated, and drops junk", () => {
  assert.equal(formatPreviewMonths(["2026-04", "2026-03", "2026-04"]), "3 月、4 月");
  assert.equal(formatPreviewMonths(["2026-10", "2026-9"]), "9 月、10 月");
  assert.equal(formatPreviewMonths(["", null, "abc", "2026-13", "2026-00"]), "");
  assert.equal(formatPreviewMonths(undefined), "");
  assert.equal(formatPreviewMonths("2026-03"), "");
});

test("previewMonthCount counts distinct valid months", () => {
  assert.equal(previewMonthCount(["2026-03", "2026-03", "2026-04", "x"]), 2);
  assert.equal(previewMonthCount(null), 0);
});

test("month scope shows the amber preview tag with the hint", () => {
  const tag = dashboardStatusTag({ preview: true, finalized: false }, "month");
  assert.deepEqual(tag, { text: "预览 · 未定版", cls: "warn", hint: "本月还没有定版，数字是按当前费用和工时算出的预览。" });
});

test("month scope shows the green finalized tag without a hint", () => {
  const tag = dashboardStatusTag({ preview: false, finalized: true }, "month");
  assert.deepEqual(tag, { text: "已定版", cls: "ok", hint: "" });
});

test("preview wins over finalized and absent keys show nothing", () => {
  assert.equal(dashboardStatusTag({ preview: true, finalized: true }, "month").cls, "warn");
  assert.equal(dashboardStatusTag({}, "month"), null);
  assert.equal(dashboardStatusTag({ total_amount: 1 }, "month"), null);
  assert.equal(dashboardStatusTag(null, "month"), null);
  assert.equal(dashboardStatusTag(undefined), null);
});

test("year scope never shows the month tag", () => {
  assert.equal(dashboardStatusTag({ preview: true, finalized: true }, "year"), null);
});

test("yearPreviewNote spells out the count and months", () => {
  const note = yearPreviewNote({ has_preview: true, preview_months: ["2026-09", "2026-10"], finalized_months: ["2026-08"] });
  assert.equal(note, "全年数字包含 2 个月的预览（9 月、10 月），这些月份定版后可能有变化。");
});

test("yearPreviewNote falls back to a generic line when the month list is missing", () => {
  assert.equal(yearPreviewNote({ has_preview: true }), "全年数字包含未定版月份的预览，这些月份定版后可能有变化。");
});

test("yearPreviewNote uses the month list even when has_preview is absent", () => {
  assert.match(yearPreviewNote({ preview_months: ["2026-10"] }), /^全年数字包含 1 个月的预览（10 月）/);
});

test("yearPreviewNote is empty without any preview", () => {
  assert.equal(yearPreviewNote({ has_preview: false, preview_months: [] }), "");
  assert.equal(yearPreviewNote({}), "");
  assert.equal(yearPreviewNote(null), "");
});

test("isPreviewMonth matches month keys loosely", () => {
  const payload = { preview_months: ["2026-03", "2026-10"] };
  assert.equal(isPreviewMonth(payload, "2026-03"), true);
  assert.equal(isPreviewMonth(payload, "2026-3"), true);
  assert.equal(isPreviewMonth(payload, "2026-04"), false);
  assert.equal(isPreviewMonth({}, "2026-03"), false);
  assert.equal(isPreviewMonth(payload, "bad"), false);
});

test("home cost tag appears for a month preview or for preview months", () => {
  assert.deepEqual(costPreviewTag({ preview: true }), { text: "含预览", title: "包含未定版月份的预览数字" });
  assert.deepEqual(costPreviewTag({ preview_months: ["2026-09"] }), { text: "含预览", title: "包含未定版月份的预览数字（9 月）" });
  assert.equal(costPreviewTag({ preview: true, preview_months: ["2026-03", "2026-04"] }).title, "包含未定版月份的预览数字（3 月、4 月）");
});

test("home cost tag shows nothing when the payload lacks the keys", () => {
  assert.equal(costPreviewTag({ visible: true, totals: {} }), null);
  assert.equal(costPreviewTag({ preview: false, preview_months: [] }), null);
  assert.equal(costPreviewTag(null), null);
  assert.equal(costPreviewTag(undefined), null);
});
