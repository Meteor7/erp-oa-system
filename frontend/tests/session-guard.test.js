import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const source = readFileSync(new URL('../src/lib/sessionGuard.js', import.meta.url), 'utf8');
const mainSource = readFileSync(new URL('../src/main.js', import.meta.url), 'utf8');

test('local development traffic is normalized to the canonical Frappe site host', () => {
  assert.match(source, /window\.location\.hostname !== 'localhost'/);
  assert.match(source, /CANONICAL_LOCAL_HOST = 'rayher\.localhost'/);
  assert.match(mainSource, /enforceCanonicalLocalHost\(\)/);
});

test('resource requests verify the live browser session after authentication errors', () => {
  assert.match(source, /frappe\.auth\.get_logged_user/);
  assert.match(source, /status === 401 \|\| status === 403/);
  assert.match(source, /serverUser !== pageUser/);
  assert.match(source, /window\.location\.reload\(\)/);
  assert.match(source, /redirect-to=/);
  assert.match(mainSource, /setConfig\("resourceFetcher", guardedFrappeRequest\)/);
});

test('returning to a stale tab verifies its session before more work', () => {
  assert.match(source, /window\.addEventListener\('focus', checkWhenActive\)/);
  assert.match(source, /document\.addEventListener\('visibilitychange', checkWhenActive\)/);
  assert.match(mainSource, /installSessionGuard\(\)/);
});
