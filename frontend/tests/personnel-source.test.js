import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const source = readFileSync(new URL("../src/pages/Personnel.vue", import.meta.url), "utf8");
const template = source.match(/<template>[\s\S]*<\/template>\s*<style/)?.[0] || "";
const script = source.match(/<script setup>[\s\S]*?<\/script>/)?.[0] || "";
const style = source.match(/<style scoped>[\s\S]*<\/style>/)?.[0] || "";

test("employee table uses fixed twenty-row pagination", () => {
  assert.match(source, /const PAGE_SIZE\s*=\s*20/);
  assert.match(source, /pageSlice\(filteredItems\.value,\s*currentPage\.value,\s*PAGE_SIZE\)/);
  assert.match(source, /v-for="item in pagedItems"/);
  assert.match(source, /currentPage--/);
  assert.match(source, /currentPage\+\+/);
  assert.doesNotMatch(source, /pageSize/);
});

test("the R&D type follows the department: group header shows who fills the timesheet, new employees get a default, gaps are flagged", () => {
  // 研发分组旁边写「填工时 N」，只在看在职时显示（其他分组里有不用填工时的特例，不写）
  assert.match(template, /group\.total\}\} 人<template v-if="statusFilter==='active'&&group\.name==='研发'&&group\.fill"> · 填工时 \{\{group\.fill\}\}/);
  // 列表按部门分组判断「研发部门没设类型」
  assert.match(script, /decorateEmployees\(rows\.data\|\|\[\],\{today,sensitiveHidden,groupOf:groupOf\.value\}\)/);
  assert.match(template, /研发部门未设类型 \$\{kpi\.rdGap\}/);
  // 新增员工选部门后自动带出类型，只覆盖空值和自己带出的值，已有员工不动
  assert.match(script, /watch\(\(\)=>form\.department,department=>\{\s*if\(!editing\.value\|\|form\.name\)return;/);
  assert.match(script, /form\.rd_personnel_type!==autoRdType\.value\)return;/);
  assert.match(script, /defaultRdType\(meta\?\.group_name\)/);
});

test("every filter resets employee pagination", () => {
  assert.match(source, /watch\(\[companyFilter,departmentFilter,keyword,statusFilter,rdFilter,archiveFilter,alertOnly,sortMode\]/);
  assert.match(source, /watch\(pageCount/);
});

test("employee table freezes the header row and the first column, including its header cell", () => {
  assert.match(template, /<th class="c1"/);
  assert.match(template, /<td class="c1"/);
  assert.match(style, /\.pl-table th\.c1, \.rd \.pl-table td\.c1 \{[^}]*position: sticky; left: 0;[^}]*border-right/);
  assert.match(style, /\.pl-table td\.c1 \{[^}]*background: var\(--rd-surface\)/);
  assert.match(style, /\.pl-table th\.c1 \{[^}]*z-index: 4/);
});

test("list columns follow the approved prototype", () => {
  const head = template.match(/<table class="pl-table"[\s\S]*?<\/thead>/)?.[0] || "";
  const labels = [...head.matchAll(/<th[^>]*>([^<]+)<\/th>/g)].map((match) => match[1]);
  assert.deepEqual(labels, ["员工", "员工号", "部门 · 岗位", "直属主管", "入职 · 司龄", "研发类型", "档案", "提醒"]);
  assert.match(template, /supervisorName\(item\.row\)/);
  assert.match(template, /rows\.loading&&!loaded/);
});

test("the list never carries salary, id number, bank or insurance data", () => {
  const body = template.match(/<table class="pl-table"[\s\S]*<\/table>/)?.[0] || "";
  assert.ok(body.length > 200);
  for (const field of [
    "default_monthly_salary", "salary_months", "id_card_number_cn", "bank_name", "bank_ac_no",
    "social_insurance_number", "housing_fund_number", "default_social_insurance_base", "default_housing_fund_base",
  ]) {
    assert.ok(!body.includes(field), `${field} must not be rendered in the list`);
  }
  assert.ok(template.includes("敏感信息不在列表里显示"));
});

test("household data keeps its explicit options and free text entry", () => {
  assert.match(source, /get_household_options/);
  assert.match(source, /list="household-options"/);
  assert.match(source, /<datalist id="household-options">/);
  assert.match(source, /非深农村/);
});

test("department panel shows grouped nonempty departments with counts and click filtering", () => {
  assert.match(source, /departmentGroups\(items\.value,depts\.data\|\|\[\]/);
  assert.match(source, /v-for="group in groups"/);
  assert.match(source, /v-for="department in group\.departments"/);
  assert.match(source, /departmentFilter=department\.name/);
  assert.match(source, /employee_count/);
  assert.match(source, /id="pl-company" v-model="companyFilter"/);
});

test("employee form limits department ids to the selected company and keeps the current one", () => {
  assert.match(source, /const formDepartmentOptions\s*=\s*computed/);
  assert.match(source, /x\.company===form\.company/);
  assert.match(source, /clearDepartmentIfOutsideCompany/);
  assert.match(source, /@change="clearDepartmentIfOutsideCompany"/);
});

test("company or status changes clear a department filter that is no longer available", () => {
  assert.match(source, /watch\(\[companyFilter,statusFilter\]/);
  assert.match(source, /!departmentOptions\.value\.includes\(departmentFilter\.value\)/);
});

test("personnel errors hide internal API method names", () => {
  assert.match(source, /import \{ extractFrappeError \}/);
  assert.match(source, /extractFrappeError\(e,"保存失败"\)/);
  assert.match(source, /extractFrappeError\(e,"删除失败"\)/);
  assert.match(source, /请填写姓名并选择所属单位/);
});

test("every employee field is still editable in the drawer", () => {
  const fields = [
    "company", "employee_number", "employee_name", "english_name", "date_of_birth", "gender", "cell_number", "household_registration",
    "id_type_cn", "id_card_number_cn", "date_of_joining", "relieving_date", "department", "designation", "reports_to", "employment_type",
    "rd_personnel_type", "expense_account_category", "archive_status",
    "labour_contract_start_date", "probation_months", "probation_end_date", "first_contract_period_years", "first_contract_end_date",
    "contract_renewal_status", "second_contract_period_years", "second_contract_end_date",
    "first_education_level", "first_education_school", "first_education_major", "education_level_cn", "degree_cn",
    "education_completion_type", "graduation_school", "major_cn",
    "default_monthly_salary", "salary_months", "default_social_insurance_base", "default_housing_fund_base",
    "social_insurance_number", "housing_fund_number", "bank_name", "bank_ac_no",
  ];
  for (const field of fields) assert.ok(script.includes(`key:"${field}"`), `${field} is missing from the drawer form`);
  assert.match(script, /const blank=\(\)=>/);
  assert.match(script, /api\+"save_employee"/);
  assert.match(script, /api\+"delete_employee"/);
  assert.match(script, /saver\.submit\(\{\.\.\.form\}\)/);
});

test("saving reloads the list and keeps the drawer on the saved record in view mode", () => {
  assert.match(script, /await rows\.reload\(\)/);
  assert.match(script, /drawerName\.value=savedName/);
  assert.match(script, /editing\.value=false/);
  assert.match(script, /flashSuccess\("已保存/);
  assert.match(template, /role="status"/);
});

test("new employees open the drawer directly in edit mode", () => {
  assert.match(script, /function newEmp\(\)\{[\s\S]*editing\.value=true/);
  assert.match(template, /data-new-emp @click="newEmp"/);
});

test("delete keeps the role rule and asks for confirmation", () => {
  assert.match(script, /\["System Manager","HR Manager"\]/);
  assert.match(template, /canDelete&&form\.name/);
  assert.match(template, /确认删除/);
  assert.match(template, /askDelete=true/);
});

test("sensitive tabs are hidden for restricted accounts and masked otherwise", () => {
  assert.match(source, /isHrSensitiveHidden/);
  assert.match(script, /const tabs=visibleTabs\(\{sensitiveHidden\}\)/);
  assert.match(script, /decorateEmployees\(rows\.data\|\|\[\],\{today,sensitiveHidden,groupOf:groupOf\.value\}\)/);
  assert.match(script, /displayFieldValue\(key,value,\{reveal:!!reveal\[key\]\}\)/);
  assert.match(template, /viewCell\(current,field\)\.shown\?'隐藏':'显示'/);
  assert.match(script, /function setTab\(key\)\{drawerTab\.value=key;resetReveal\(\)\}/);
});

test("drawer is an accessible dialog: Esc closes, focus is trapped and returned", () => {
  assert.match(template, /role="dialog" aria-modal="true"/);
  assert.match(template, /role="tablist"/);
  assert.match(template, /role="tab"/);
  assert.match(script, /event\.key==="Escape"/);
  assert.match(script, /event\.key!=="Tab"/);
  assert.match(script, /addEventListener\("keydown",onKeydown\)/);
  assert.match(script, /removeEventListener\("keydown",onKeydown\)/);
  assert.match(script, /openerSelector/);
  assert.match(template, /:data-emp="item\.row\.name"/);
  assert.match(template, /aria-label="关闭"/);
  assert.match(template, /放弃未保存的修改/);
});

test("narrow screens: table scrolls sideways and the drawer goes full width", () => {
  assert.match(template, /class="tbl pl-tbl"/);
  assert.match(style, /\.pl-table \{ min-width: 1000px/);
  assert.match(style, /\.pd-drawer \{[^}]*width: min\(600px, 100%\)/);
  assert.match(style, /@media \(max-width: 900px\)/);
  assert.match(style, /@media \(max-width: 640px\)/);
});

test("header has 导入 and 导出 menus; import is limited to roles that can save employees", () => {
  assert.match(template, /<template #ctl>[\s\S]*data-import-btn[\s\S]*导入 ▾[\s\S]*data-export-btn[\s\S]*导出 ▾[\s\S]*data-new-emp/);
  assert.match(template, /<div v-if="canImport" ref="importWrap" class="pi-menuwrap">/);
  assert.match(script, /const canImport=canImportEmployees\(typeof window!=="undefined"\?window\.roles:\[\]\)/);
  assert.match(template, /下载导入模板/);
  assert.match(template, /选择 Excel 文件/);
  assert.match(template, /导出当前筛选结果/);
  assert.match(template, /导出全部在职/);
  assert.match(template, /aria-haspopup="menu"/);
  assert.match(template, /role="menuitem"/);
  assert.match(script, /closeMenus\(true\)/);
});

test("import: parse in the browser, ask the server for a read-only preview, confirm to write, then reload", () => {
  assert.match(script, /createResource\(\{url:api\+"preview_employee_import"\}\)/);
  assert.match(script, /createResource\(\{url:api\+"import_employees"\}\)/);
  assert.match(script, /importEmployeeWorkbookFile\(file\)/);
  assert.match(script, /previewer\.submit\(\{rows:JSON\.stringify\(parsed\.rows\)\}\)/);
  assert.match(script, /importer\.submit\(\{rows:JSON\.stringify\(state\.parsed\.rows\)\}\)/);
  assert.match(script, /await Promise\.all\(\[rows\.reload\(\),depts\.reload\(\)\]\)/);
  assert.match(script, /importResultText\(result\)/);
  // the preview is never skipped: the file input only parses + previews; writing is only in confirmImport
  const onFile = script.match(/async function onFile[\s\S]*?\n\}\n/)?.[0] || "";
  assert.ok(onFile.includes("previewer.submit"));
  assert.ok(!onFile.includes("importer.submit"));
  assert.match(template, /aria-label="Excel 导入预览"/);
  assert.match(template, /确认导入/);
  assert.match(template, /data-import-confirm :disabled="importState\.stage!=='ready'\|\|!importPreview\|\|!importPreview\.canConfirm"/);
  assert.match(template, /新增 <b class="num">\{\{importPreview\.create\}\}/);
  assert.match(template, /无变化/);
  assert.match(template, /有问题/);
  assert.match(template, /importPreview\.problemsShown/);
  assert.match(template, /还有 \{\{importPreview\.problemsMore\}\} 条/);
  assert.match(template, /describeChange\(change\)/);
  assert.match(script, /extractFrappeError\(e,"导入失败，本次没有写入任何数据"\)/);
  assert.match(template, /accept="\.xlsx,\.xls"/);
});

test("export: current filter or all active, sensitive checkbox only when the page may see and received those fields", () => {
  assert.match(script, /pickExportRows\(mode,\{filtered:filteredItems\.value,all:items\.value,company:companyFilter\.value\}\)/);
  assert.match(script, /canOfferSensitiveExport\(\{sensitiveHidden,rows:rows\.data\|\|\[\]\}\)/);
  assert.match(script, /const withSensitive=sensitiveOffer\.value&&includeSensitive\.value/);
  assert.match(script, /employeeExportFilename\(today,withSensitive\)/);
  assert.match(script, /includeSensitive\.value=false/);
  assert.match(template, /<template v-if="sensitiveOffer">[\s\S]*data-export-sensitive/);
  assert.match(template, /SENSITIVE_EXPORT_LABEL/);
  assert.match(template, /doExport\('current'\)/);
  assert.match(template, /doExport\('active'\)/);
});

test("transfer menus close on Escape and outside clicks, and listeners are removed", () => {
  assert.match(script, /document\.addEventListener\("mousedown",onPointerDown\)/);
  assert.match(script, /document\.removeEventListener\("mousedown",onPointerDown\)/);
  assert.match(script, /event\.key==="Escape"&&\(importMenuOpen\.value\|\|exportMenuOpen\.value\)/);
});
