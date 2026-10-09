import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");
const page = read("../src/pages/Dashboard.vue");
const kpi = read("../src/components/dashboard/DashKpi.vue");
const todos = read("../src/components/dashboard/DashTodos.vue");
const alerts = read("../src/components/dashboard/DashAlerts.vue");
const block = read("../src/components/dashboard/DashBlock.vue");
const notes = read("../src/components/dashboard/DashNotifications.vue");
const css = read("../src/styles/dashboardUi.css");
const view = read("../src/lib/dashboardView.js");
const all = { page, kpi, todos, alerts, block, notes, view };

test("the page asks the server for the whole home page, for the shared period", () => {
  assert.match(page, /rayher_hr_payroll\.api\.dashboard_home\.get_home/);
  assert.match(page, /method: 'GET'/);
  assert.match(page, /import \{ period \} from '\.\.\/lib\/period'/);
  assert.match(page, /makeParams: \(\) => \(\{ period: isValidMonth\(period\.value\) \? period\.value : currentMonth\(\) \}\)/);
  assert.match(page, /watch\(period, \(\) => \{ if \(isValidMonth\(period\.value\)\) home\.reload\(\); \}\)/);
  // 右上角：月份输入框 + "本月"
  assert.match(page, /type="month"/);
  assert.match(page, /本月/);
  // an auto resource calls makeParams at once, so everything it reads must already be imported
  assert.ok(page.indexOf("import { period }") < page.indexOf("createResource({"));
});

test("the page no longer calls the old per-block endpoints", () => {
  for (const name of ["get_cost_overview", "get_hr_overview", "get_dashboard", "get_my_leave_summary", "get_my_approval_queue", "get_my_requests", "get_project_cost_detail"]) {
    assert.doesNotMatch(page, new RegExp(name), name);
  }
});

test("tabs come from the server, show only when there is more than one, and live in the address", () => {
  assert.match(page, /data\.value\?\.tabs/);
  assert.match(page, /v-if="tabs\.length > 1"/);
  assert.match(page, /role="tablist"/);
  assert.match(page, /role="tab"/);
  assert.match(page, /:aria-selected="activeKey === item\.key"/);
  assert.match(page, /resolveTabKey\(tabs\.value, route\.query\.tab\)/);
  assert.match(page, /router\.replace\(\{ path: route\.path, query: tabQuery\(route\.query, key\) \}\)/);
  assert.match(page, /@keydown\.right/);
  assert.match(page, /@keydown\.left/);
});

test("clicking through carries the current tab as the way back", () => {
  assert.match(page, /dashboardFrom\(activeKey\.value\)/);
  assert.match(page, /targetState\(target, \{ table, from: fromPath\.value, access \}\)/);
  assert.match(page, /router\.push\(to\)/);
  assert.match(page, /buildTargetTable\(targetsJson\)/);
  assert.match(page, /import targetsJson from '\.\.\/lib\/dashboardTargetsData'/);
  assert.match(page, /const access = \{ \.\.\.boardAccess\(\), canSee \}/);
});

test("the target table is the backend json, imported by a one-line module", () => {
  const data = read("../src/lib/dashboardTargetsData.js").trim().split("\n").filter(Boolean);
  assert.deepEqual(data, ["import raw from '../../../rayher_hr_payroll/dashboard/targets.json';", "export default raw;"]);
  assert.doesNotMatch(read("../src/lib/dashboardTargets.js"), /import .*targets\.json/, "the pure module does not import the json itself");
});

test("kpis come first, then todos beside alerts, then the blocks", () => {
  const kpis = page.indexOf('class="db-kpis"');
  const attention = page.indexOf('class="db-attn"');
  const blocks = page.indexOf('class="db-blocks"');
  assert.ok(kpis > -1 && attention > kpis && blocks > attention);
  assert.match(page, /<DashTodos v-if="page\.showTodos"/);
  assert.match(page, /<DashAlerts v-if="page\.showAlerts"/);
  // both live in the same container, so they share one screen row
  const container = page.slice(attention, blocks);
  assert.ok(container.indexOf("<DashTodos") > -1 && container.indexOf("<DashAlerts") > container.indexOf("<DashTodos"));
  assert.match(page, /v-if="page\.attention !== 'none'"/);
  assert.match(css, /\.db-attn\.is-both \{ grid-template-columns: minmax\(0, 1\.25fr\) minmax\(0, 1fr\); \}/);
  assert.match(css, /@media \(max-width: 1000px\)[\s\S]*\.db-attn\.is-both/);
});

test("empty and failing states are all spelled out", () => {
  assert.match(page, /firstLoad/);
  assert.match(page, /class="db-skel"/);
  assert.match(page, /role="status" aria-label="正在加载看板"/);
  assert.match(page, /看板加载失败：/);
  assert.match(page, /重新加载/);
  assert.match(page, /刷新失败，下面显示的是上一次的数据/);
  assert.match(page, /EMPTY_PAGE_TEXT/);
  assert.match(view, /没有需要你处理的事/);
  assert.match(view, /这一块暂时加载失败/);
  assert.match(todos, /EMPTY_TODO_TEXT/);
  assert.match(alerts, /EMPTY_ALERT_TEXT/);
  assert.match(block, /block\.failedText/);
  assert.match(block, /EMPTY_BLOCK_TEXT/);
  // the per-tab errors list is for logs, not for the user
  assert.doesNotMatch(page, /\.errors\b/);
  assert.doesNotMatch(Object.values(all).join("\n"), /message: ?'|\.errors\b/);
});

test("kpi cards: hint in a question mark, preview tag, grey-out for blocked or unknown targets", () => {
  assert.match(kpi, /class="db-q"[^>]*:title="kpi\.hint"/);
  assert.match(kpi, /v-if="kpi\.hint"/);
  assert.match(kpi, /v-if="kpi\.preview" class="db-pill"[^>]*>预览</);
  assert.match(kpi, /<component :is="clickable \? 'button' : 'div'"/);
  assert.match(kpi, /state\.state === 'link'/);
  assert.match(kpi, /props\.state\.state === 'denied' \|\| props\.state\.state === 'unknown'/);
  assert.match(kpi, /:aria-disabled="off \? 'true' : undefined"/);
  assert.match(kpi, /targetHint\(props\.state\.state\)/);
  assert.match(css, /\.db-kpi\.is-off \{[^}]*cursor: not-allowed/);
});

test("todos and alerts open their target only when it can be opened", () => {
  assert.match(todos, /resolve\(item\.target\)\.state === 'link'/);
  assert.match(todos, /disabled :title="targetHint/);
  assert.match(todos, /\{\{ item\.btn \}\}/);
  assert.match(alerts, /resolve\(item\.target\)\.state === 'link'/);
  assert.match(alerts, /\{\{ item\.go \}\} →/);
  assert.match(todos, /要我处理/);
  assert.match(alerts, /需要关注/);
});

test("the four block types are drawn with css only, no chart library", () => {
  for (const type of ["bars", "cols", "stack", "list"]) assert.match(block, new RegExp(`block\\.type === '${type}'`), type);
  assert.match(block, /class="db-trk"/);
  assert.match(block, /:style="\{ width: row\.width \+ '%' \}"/);
  assert.match(block, /:style="\{ height: row\.height \+ '%' \}"/);
  assert.match(block, /background: row\.color/);
  assert.match(block, /class="db-lg"/);
  for (const [name, text] of Object.entries(all)) assert.doesNotMatch(text, /from ['"]echarts|import\(.echarts/, name);
  // a block with its own link shows "more →"
  assert.match(block, /\{\{ block\.more \|\| '查看' \}\} →/);
});

test("notifications stay at the bottom of the overview, behaving as before", () => {
  assert.match(page, /import DashNotifications from '\.\.\/components\/dashboard\/DashNotifications\.vue'/);
  assert.ok(page.indexOf("<DashNotifications") > page.indexOf("<DashBlock"));
  assert.match(page, /activeKey\.value === 'overview'/);
  assert.match(notes, /get_my_notification_feed/);
  assert.match(notes, /mark_notifications_read/);
  assert.match(notes, /noteCategory/);
  assert.match(notes, /noteUnreadOnly/);
  assert.match(notes, /只看未读/);
  assert.match(notes, /该单据还有/);
  assert.match(notes, /本类全部已读/);
  assert.match(notes, /noteTarget\(item\)/);
  assert.match(notes, /watch\(\[noteCategory, noteUnreadOnly\], \(\) => notifications\.reload\(\)\)/);
  assert.match(notes, /markNoteRead\(item\);\s*const target = noteTarget\(item\);\s*if \(target\) router\.push\(target\);/);
  assert.match(notes, /这一类没有/);
});

test("nothing in the dashboard hard-codes a position or a role name", () => {
  const names = /总经理|副总|财务主管|人事经理|采购经理|PMC|出纳|生产主管|总账|general_manager|vice_manager|finance_|hr_manager|procurement_manager|pmc\b|production_asset_owner|dept_manager|System Manager|Accounts User|HR Manager/;
  for (const [name, text] of Object.entries(all)) {
    const withoutComments = text.replace(/\/\/.*$/gm, "").replace(/<!--[\s\S]*?-->/g, "");
    assert.doesNotMatch(withoutComments, names, name);
  }
});

test("every css rule is scoped under .db so no other page is touched", () => {
  const bare = css.replace(/\/\*[\s\S]*?\*\//g, "");
  const selectors = [...bare.matchAll(/([^{}]+)\{/g)].map((match) => match[1].trim()).filter((text) => text && !text.startsWith("@") && !/^(\d+%|from|to)$/.test(text));
  assert.ok(selectors.length > 60);
  for (const text of selectors) {
    for (const one of text.split(",")) assert.ok(one.trim().startsWith(".db"), `unscoped selector: ${one.trim()}`);
  }
});

test("motion respects reduced-motion and the page is usable on a phone", () => {
  assert.match(css, /prefers-reduced-motion: reduce[\s\S]*animation: none/);
  assert.match(css, /@media \(max-width: 1000px\)/);
  assert.match(css, /@media \(max-width: 480px\)/);
  assert.match(css, /\.db-tabs \{[^}]*overflow-x: auto/);
  assert.match(css, /:focus-visible/);
});

test("the old dashboard pieces are gone", () => {
  for (const text of ["月度核算流程", "数据完整度", "我的假期", "经营看板", "人事看板", "echarts"]) assert.doesNotMatch(page, new RegExp(text), text);
});
