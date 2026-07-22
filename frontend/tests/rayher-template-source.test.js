import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const template = readFileSync(
  new URL("../../rayher_hr_payroll/www/rayher.html", import.meta.url),
  "utf8",
);

test("Rayher page template uses real newlines so boot role injection executes", () => {
  assert.ok(template.includes("\n"));
  assert.ok(!template.includes("\\n"));
  assert.match(template, /for key in boot/);
  assert.match(template, /window\["\{\{ key \}\}"\]/);
});
