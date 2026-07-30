import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const source = readFileSync(new URL('../src/router.js', import.meta.url), 'utf8');

test('router registers project management page', () => {
  assert.match(source, /path:\s*['\"]\/projects['\"]/);
  assert.match(source, /\.\/pages\/Projects\.vue/);
});

test('router registers split approval pages', () => {
  assert.match(source, /path:\s*['\"]\/approval\/leave['\"]/);
  assert.match(source, /path:\s*['\"]\/approval\/purchase['\"]/);
  assert.match(source, /path:\s*['\"]\/oa['\"],\s*redirect:\s*['\"]\/approval\/leave['\"]/);
  assert.match(source, /OAApprovals\.vue/);
});

test('router stops loading the removed personnel ledger page', () => {
  assert.doesNotMatch(source, /\.\/pages\/Ledger\.vue/);
  assert.match(source, /path:\s*['\"]\/ledger['\"],\s*redirect:\s*['\"]\/entry['\"]/);
});


test('router registers overseas commissioned R&D page', () => {
  assert.match(source, /path:\s*['"]\/foreign-rd['"]/);
  assert.match(source, /\.\/pages\/ForeignRD\.vue/);
});

test('router registers allocation dashboard page after the allocation table', () => {
  assert.match(source, /path:\s*['"]\/allocation-dashboard['"]/);
  assert.match(source, /\.\/pages\/AllocationDashboard\.vue/);
  assert.ok(source.indexOf("path: '/allocation'") < source.indexOf("path: '/allocation-dashboard'"));
});


test('router registers the independent foreign R&D timesheet report', () => {
  assert.match(source, /path:\s*['"]\/foreign-rd-timesheet['"]/);
  assert.match(source, /\.\/pages\/ForeignRDTimesheet\.vue/);
});