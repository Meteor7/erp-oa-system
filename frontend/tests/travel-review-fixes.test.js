import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { canQuickReject } from "../src/lib/attendanceView.js";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");

// 出差的前台办理只能点“已办理”：待我审批的行内不给“驳回”（服务端 can_reject 也是 false）。
test("the attendance queue hides the inline reject on the travel front-desk step", () => {
  assert.equal(canQuickReject({ workflow_status: "待审批", can_reject: true, current_step_mode: "approve" }), true);
  assert.equal(canQuickReject({ workflow_status: "待审批" }), true, "rows without the flag keep the button");
  assert.equal(canQuickReject({ workflow_status: "待办理", can_reject: false, current_step_mode: "handle" }), false);
  assert.equal(canQuickReject({ workflow_status: "待办理", current_step_mode: "handle" }), false);
  assert.equal(canQuickReject({ workflow_status: "待审批", can_reject: false }), false);
  assert.equal(canQuickReject(null), false);
  const queue = read("../src/components/attendance/AttendanceQueue.vue");
  assert.match(queue, /<button v-if="canQuickReject\(row\)"[^>]*@click="startReject\(row\)">驳回<\/button>/);
  assert.match(queue, /canQuickApprove, canQuickReject,/);
});
