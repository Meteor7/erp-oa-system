
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const page = readFileSync(new URL('../src/pages/ForeignRD.vue', import.meta.url), 'utf8');

test('overseas page has line-style entry rows and batch import controls', () => {
  assert.ok(page.includes('parseForeignRdPaste'));
  assert.ok(page.includes('importForeignRdWorkbookFile'));
  assert.ok(page.includes('foreign-rd-entry'));
  assert.ok(page.includes('foreign-rd-batch-import'));
  assert.ok(page.includes('appendBatchRows'));
  assert.ok(page.includes('batchRows'));
  assert.match(page, /class="line"/);
  assert.doesNotMatch(page, /foreign-rd-entry-row rounded-lg/);
});

test('overseas batch import lives in a right drawer teleported to the body', () => {
  assert.match(page, /<Teleport to="body">/);
  assert.match(page, /class="rd foreign-rd-batch-import"/);
  assert.match(page, /class="rd-drawer"/);
  assert.match(page, /@click="previewBatchPaste"/);
  assert.match(page, /@click="appendBatchRows"/);
  assert.match(page, /accept="\.xlsx,\.xls"/);
  assert.match(page, /整批不会导入/);
  assert.equal(page.indexOf('foreign-expense-sources'), -1);
});
