// 总经理、副总经理只读打开看板数字背后的页面（决定 2026-10-13）；能改的仍然只有人事 / 财务角色。
import assert from "node:assert/strict";
import test from "node:test";
import { canEditHr, canSee } from "../src/lib/access.js";

const as = ({ roles = ["Employee"], positions = {} } = {}) => { globalThis.window = { roles, position_access: positions, oa_access: {} }; };
const READ = ["/personnel", "/payroll", "/social-insurance", "/housing-fund", "/accommodation", "/accommodation/master", "/allocation-dashboard"];

test("the general and vice manager can open the pages behind their numbers but not change them", () => {
  for (const position of ["general_manager", "vice_manager"]) {
    as({ positions: { [position]: true } });
    for (const path of READ) assert.equal(canSee(path), true, `${position} ${path}`);
    assert.equal(canSee("/allocation"), false, "定版的那一页不放开");
    assert.equal(canEditHr(), false);
  }
});

test("other positions do not get these pages, HR roles can edit", () => {
  as({ positions: { pmc: true } });
  assert.equal(canSee("/payroll"), false);
  as({ roles: ["HR Manager"] });
  assert.equal(canEditHr(), true);
});
