
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const page = readFileSync(new URL('../src/pages/ForeignRD.vue', import.meta.url), 'utf8');

test('overseas page has a wide table editor and batch import controls', () => {
  assert.ok(page.includes('parseForeignRdPaste'));
  assert.ok(page.includes('importForeignRdWorkbookFile'));
  assert.ok(page.includes('foreign-rd-entry-table'));
  assert.ok(page.includes('foreign-rd-batch-import'));
  assert.ok(page.includes('appendBatchRows'));
  assert.ok(page.includes('batchRows'));
  assert.doesNotMatch(page, /foreign-rd-entry-row rounded-lg/);
});


test('overseas batch import sits below the entry table and no source table is rendered', () => {
  const entryStart = page.indexOf('foreign-rd-entry-table');
  const batchStart = page.indexOf('foreign-rd-batch-import', entryStart);
  assert.ok(entryStart > 0);
  assert.ok(batchStart > entryStart);
  assert.equal(page.indexOf('foreign-expense-sources'), -1);
  assert.doesNotMatch(page, /xl:grid-cols-\[1\.55fr_0\.9fr\]/);
});
