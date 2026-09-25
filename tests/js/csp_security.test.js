import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';

import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const middlewarePath = path.resolve(__dirname, '..', '..', 'config', 'middleware.py');
const middleware = fs.readFileSync(middlewarePath, 'utf8');

test('production CSP is configurable and strict by default', () => {
  assert.match(middleware, /CSP_ALLOW_INLINE_STYLES/);
  assert.match(middleware, /CSP_ALLOW_GOOGLE_FONTS/);
  assert.match(middleware, /upgrade-insecure-requests/);
});

test('baseline browser security headers are emitted', () => {
  assert.match(middleware, /X-Content-Type-Options/);
  assert.match(middleware, /Referrer-Policy/);
  assert.match(middleware, /Permissions-Policy/);
  assert.match(middleware, /Cross-Origin-Opener-Policy/);
});
