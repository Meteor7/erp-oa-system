import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const personnel = readFileSync(new URL("../src/pages/Personnel.vue", import.meta.url), "utf8");
// 月度费用登记拆成列表页（pages/Accommodation.vue）和内页表单（components/accommodation/FeeForm.vue）：字段、接口、校验两处合起来断言
const accommodation = ["../src/pages/Accommodation.vue", "../src/components/accommodation/FeeForm.vue"]
  .map((path) => readFileSync(new URL(path, import.meta.url), "utf8")).join("\n");

test("personnel page manages employee expense account category", () => {
  assert.match(personnel, /EXPENSE_ACCOUNT_CATEGORIES/);
  assert.match(personnel, /expense_account_category/);
  assert.ok(personnel.includes("费用科目"));
  assert.ok(personnel.includes("研发费用"));
  assert.ok(personnel.includes("管理费用"));
  assert.ok(personnel.includes("销售费用"));
  assert.ok(personnel.includes("生产成本"));
  assert.match(personnel, /relieving_date/);
  assert.ok(personnel.includes("演示员工166时间"));
  assert.match(personnel, /designation/);
  assert.ok(personnel.includes("部门"));
  assert.ok(personnel.includes("职位"));
  // 列表只留 部门 · 岗位 等非敏感列；费用科目、演示员工166时间在员工详情抽屉里维护和查看
  const tableHead = personnel.match(/<table class="pl-table"[\s\S]*?<\/thead>/)?.[0] || "";
  assert.ok(tableHead.includes("部门 · 岗位"));
  assert.ok(!tableHead.includes("费用科目"));
  assert.match(personnel, /key:"expense_account_category",label:"费用科目"/);
  assert.match(personnel, /key:"relieving_date",label:"演示员工166时间"/);
  assert.match(personnel, /key:"designation",label:"职位"/);
  assert.match(personnel, /key:"department",label:"部门"/);
});

test("accommodation page captures room, total fees, personal fees, company fees, and category summary", () => {
  assert.match(accommodation, /get_accommodation_summary/);
  assert.match(accommodation, /room_no/);
  assert.match(accommodation, /personal_rent_amount/);
  assert.match(accommodation, /personal_water_amount/);
  assert.match(accommodation, /personal_electricity_amount/);
  assert.match(accommodation, /company_rent_amount/);
  assert.match(accommodation, /company_water_amount/);
  assert.match(accommodation, /company_electricity_amount/);
  assert.ok(accommodation.includes("房间号"));
  assert.ok(accommodation.includes("总费用"));
  assert.ok(accommodation.includes("个人承担费用"));
  assert.ok(accommodation.includes("公司承担费用"));
  assert.ok(accommodation.includes("公司承担费用科目汇总"));
  assert.ok(accommodation.includes("研发费用"));
  assert.ok(accommodation.includes("管理费用"));
  assert.ok(accommodation.includes("销售费用"));
  assert.ok(accommodation.includes("生产成本"));
  assert.match(accommodation, /{{\s*d\.room_no\s*}}/);
  assert.ok(accommodation.includes("入住人"));
  assert.match(accommodation, /SPECIAL_OCCUPANTS/);
  assert.ok(accommodation.includes("空"));
  assert.ok(accommodation.includes("客房"));
  assert.ok(accommodation.includes("午休室"));
  assert.match(accommodation, /get_room_options/);
  assert.match(accommodation, /<select v-model="form.room_no"/);
  assert.match(accommodation, /occupant_type/);
});
