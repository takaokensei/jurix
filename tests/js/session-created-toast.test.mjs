import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';

const ROOT = path.resolve(import.meta.dirname, '../..');
const template = fs.readFileSync(
  path.join(ROOT, 'src/apps/legislation/templates/legislation/chatbot.html'),
  'utf8',
);
const stylesheet = fs.readFileSync(
  path.join(ROOT, 'src/apps/core/static/css/jurix-chat.css'),
  'utf8',
);
const chatScript = fs.readFileSync(
  path.join(ROOT, 'src/apps/core/static/js/chat.js'),
  'utf8',
);

test('chat session confirmation uses a loaded, viewport-safe stylesheet', () => {
  assert.match(
    template,
    /static 'css\/jurix-chat\.css' %\}\?v=20261007-session-toast-layout2/,
    'the active chat stylesheet cache key must change with the toast styles',
  );
  assert.match(
    template,
    /static 'js\/chat\.js' %\}\?v=20261007-answer-pending1/,
    'the active chat script cache key must change with toast positioning',
  );
  assert.match(stylesheet, /\.session-created-toast\s*\{[^}]*position:\s*fixed/s);
  assert.match(stylesheet, /inset-inline-end:/);
  assert.match(stylesheet, /--session-created-toast-bottom/);
  assert.match(stylesheet, /\.session-created-toast\.show\s*\{[^}]*visibility:\s*visible/s);
  assert.match(stylesheet, /max-width:\s*min\(calc\(100vw\s*-\s*2rem\)/);
  assert.match(stylesheet, /@media\s*\(prefers-reduced-motion:\s*reduce\)\s*\{[\s\S]*?\.session-created-toast/);
  assert.match(chatScript, /window\.innerHeight - composerTop \+ 24/);
  assert.match(chatScript, /new ResizeObserver\(positionAboveComposer\)/);
});
