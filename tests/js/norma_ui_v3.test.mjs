import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { test } from 'node:test';

const root = new URL('../../', import.meta.url);
const read = (path) => readFile(new URL(path, root), 'utf8');

test('chat no longer owns a hardcoded suggestion catalog', async () => {
  const source = await read('src/apps/core/static/js/chat.js');
  assert.equal(source.includes('SUGGESTION_QUESTIONS'), false);
  assert.equal(source.includes('renderFallbackChips'), false);
  assert.equal(source.includes('fetchDynamicSuggestions'), false);
});

test('dynamic suggestions controller uses the corpus API', async () => {
  const source = await read('src/apps/core/static/js/jurix-dynamic-suggestions.js');
  assert.match(source, /\/api\/v1\/suggestions\//);
  assert.match(source, /data-source=\"corpus\"/);
  assert.doesNotMatch(source, /14\.133\/2021/);
});

test('norma list controller persists the selected presentation mode', async () => {
  const source = await read('src/apps/core/static/js/jurix-norma-list.js');
  assert.match(source, /jurix:norma-view/);
  assert.match(source, /aria-pressed/);
  assert.match(source, /prefers-reduced-motion/);
});

test('norma list stylesheet contains mobile, reduced motion and print rules', async () => {
  const source = await read('src/apps/core/static/css/jurix-norma-list.css');
  assert.match(source, /@media \(max-width: 720px\)/);
  assert.match(source, /prefers-reduced-motion/);
  assert.match(source, /@media print/);
});

test('norma template exposes semantic filters and no hardcoded suggestion cards', async () => {
  const source = await read('src/apps/legislation/templates/legislation/norma_list.html');
  assert.match(source, /name="tipo"/);
  assert.match(source, /name="ano"/);
  assert.match(source, /name="ordenar"/);
  assert.match(source, /jurix-norma-grid/);
  assert.match(source, /jurix-norma-list.js/);
});

