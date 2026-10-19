# Frappe 管理员角色注入模板修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 恢复 Frappe 向 QIHENG Demo SPA 注入当前用户和角色，使 `admin@legacy-business.example.invalid` 以 System Manager 权限进入页面。

**Architecture:** 保留服务器端 `rayher.py` 生成 `context.boot`、Jinja 模板写入 `window.*`、SPA 从 `window.roles` 判权的既有数据流。只修复 HTML 模板的换行编码，并用源码测试保护该边界。

**Tech Stack:** Frappe/Jinja、Vue 3、Node.js `node:test`、Docker

## Global Constraints

- 不修改数据库、业务数据和角色配置。
- 只在 `feat/invoice-ocr-reimbursement` 分支提交。
- 线上部署只替换模板、清缓存并重启 Web 服务。

---

### Task 1: 模板换行回归测试与修复

**Files:**
- Create: `frontend/tests/rayher-template-source.test.js`
- Modify: `rayher_hr_payroll/www/rayher.html`

**Interfaces:**
- Consumes: `rayher.py` 提供的 `boot.user`、`boot.full_name` 和 `boot.roles`
- Produces: 浏览器可执行的 `window["user"]`、`window["full_name"]` 和 `window["roles"]`

- [ ] **Step 1: Write the failing test**

```js
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const template = readFileSync(
  new URL('../../rayher_hr_payroll/www/rayher.html', import.meta.url),
  'utf8',
);

test('QIHENG Demo page template uses real newlines so boot role injection executes', () => {
  assert.ok(template.includes('\n'));
  assert.ok(!template.includes('\\\\n'));
  assert.match(template, /for key in boot/);
  assert.match(template, /window\["\{\{ key \}\}"\]/);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node --test frontend/tests/rayher-template-source.test.js`

Expected: FAIL because the current template contains no real newline and contains literal `\\n`.

- [ ] **Step 3: Write minimal implementation**

Replace only literal `\\n` separators in `rayher_hr_payroll/www/rayher.html` with real UTF-8 line endings; keep the existing HTML, asset hashes and Jinja boot loop unchanged.

- [ ] **Step 4: Run focused and full frontend tests**

Run: `node --test frontend/tests/rayher-template-source.test.js`

Expected: 1 test passed, 0 failed.

Run: `node --test frontend/tests/*.test.js`

Expected: all frontend tests passed, 0 failed.

- [ ] **Step 5: Deploy and verify**

Copy the corrected template into `/workspace/development/frappe-bench/apps/rayher_hr_payroll/rayher_hr_payroll/www/rayher.html`, run `bench --site rayher.localhost clear-cache`, restart the Frappe bench service, then verify the served page has real line breaks, the boot script contains the administrator and `System Manager`, and the SPA no longer shows 普通账号或 403。

- [ ] **Step 6: Commit**

```text
git add frontend/tests/rayher-template-source.test.js rayher_hr_payroll/www/rayher.html
git commit -m "fix: restore portal role bootstrap"
```
