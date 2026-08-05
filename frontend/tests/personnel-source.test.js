import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const source = readFileSync(new URL("../src/pages/Personnel.vue", import.meta.url), "utf8");

test("employee table uses fixed twenty-row pagination", () => {
  assert.match(source, /const PAGE_SIZE\s*=\s*20/);
  assert.match(source, /const pagedRows\s*=\s*computed/);
  assert.match(source, /filteredRows\.value\.slice/);
  assert.match(source, /v-for="\(e,index\) in pagedRows"/);
  assert.doesNotMatch(source, /pageSize/);
});

test("filters reset employee pagination", () => {
  assert.match(source, /companyFilter/);
  assert.match(source, /departmentFilter/);
  assert.match(source, /keyword/);
  assert.match(source, /watch\(\[companyFilter,\s*departmentFilter,\s*keyword\]/);
});

test("employee table freezes header and first column", () => {
  assert.match(source, /employee-table/);
  assert.match(source, /position:sticky/);
  assert.match(source, /top:0/);
  assert.match(source, /left:0/);
});

test("household and contribution data are explicit", () => {
  assert.match(source, /get_household_options/);
  assert.match(source, /<select v-model="form\.household_registration"/);
  assert.match(source, /系统判断/);
  assert.match(source, /社保基数/);
  assert.match(source, /公积金基数/);
  assert.match(source, /未维护/);
});


test("department classification shows grouped nonempty cards with counts and click filtering", () => {
  assert.match(source, /const DEPARTMENT_GROUP_ORDER/);
  assert.match(source, /const departmentGroups\s*=\s*computed/);
  assert.match(source, /employee_count/);
  assert.match(source, /v-for="group in departmentGroups"/);
  assert.match(source, /v-for="department in group\.departments"/);
  assert.match(source, /@click="departmentFilter=department\.name"/);
  assert.match(source, /department-card-active/);
});

test("employee form limits department ids to the selected company", () => {
  assert.match(source, /const formDepartmentOptions\s*=\s*computed/);
  assert.match(source, /x\.company===form\.company/);
  assert.match(source, /v-for="x in formDepartmentOptions"/);
});


test("company changes clear a department filter that is no longer available", () => {
  assert.match(source, /watch\(companyFilter/);
  assert.match(source, /!departmentOptions\.value\.includes\(departmentFilter\.value\)/);
});


test("personnel errors hide internal API method names", () => {
  assert.match(source, /import \{ extractFrappeError \}/);
  assert.match(source, /extractFrappeError\(e,"保存失败"\)/);
  assert.match(source, /extractFrappeError\(e,"删除失败"\)/);
});
