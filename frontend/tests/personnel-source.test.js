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
