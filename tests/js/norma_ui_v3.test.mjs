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

test('chat sidebar exposes the same quick-search action as the workspace shell', async () => {
  const source = await read('src/apps/legislation/templates/legislation/chatbot.html');
  const workspace = await read('src/apps/legislation/templates/legislation/workspace/base.html');
  const topbar = await read('src/apps/legislation/templates/legislation/workspace/_topbar.html');
  assert.match(source, /class="figma-sidebar-item workspace-palette-trigger" data-open-command-palette/);
  assert.match(source, /Busca rápida/);
  assert.match(source, /workspace:settings/);
  assert.match(source, /<aside[^>]+id="sidebar"/);
  assert.match(workspace, /<aside class="workspace-sidebar" id="sidebar"/);
  assert.match(topbar, /aria-controls="sidebar"[\s\S]*aria-expanded="false"/);
});

test('norm catalog uses the shared workspace shell instead of the legacy navbar', async () => {
  const template = await read('src/apps/legislation/templates/legislation/norma_list.html');
  const workspace = await read('src/apps/legislation/templates/legislation/workspace/base.html');
  assert.match(template, /extends ['"]legislation\/workspace\/base\.html['"]/);
  assert.match(template, /block topbar/);
  assert.match(workspace, /workspace-nav-item\{% if active_nav == 'normas' %\} is-active/);
  assert.doesNotMatch(template, /navbar-container|theme-toggle-navbar/);
});

test('changed assistant and workspace visual assets use cache-busted URLs', async () => {
  const chat = await read('src/apps/legislation/templates/legislation/chatbot.html');
  const workspace = await read('src/apps/legislation/templates/legislation/workspace/base.html');
  assert.match(chat, /css\/jurix-figma\.css['"] %\}\?v=/);
  assert.match(chat, /css\/jurix-rag\.css['"] %\}\?v=/);
  assert.match(chat, /js\/jurix-rag\.js['"] %\}\?v=/);
  assert.match(chat, /js\/jurix-chat-renderer\.js['"] %\}\?v=/);
  assert.match(chat, /js\/chat\.js['"] %\}\?v=/);
  assert.match(workspace, /css\/jurix-figma\.css['"] %\}\?v=/);
});

test('collection empty state separates account limitation from public exploration', async () => {
  const source = await read('src/apps/legislation/templates/legislation/workspace/collections.html');
  assert.match(source, /workspace-auth-notice/);
  assert.match(source, /Criação de coleções indisponível/);
  assert.match(source, /Explorar normas/);
  assert.doesNotMatch(source, /Entre na sua conta/);
});

test('legal search does not force mobile autofocus and uses a compact empty state', async () => {
  const template = await read('src/apps/legislation/templates/legislation/workspace/search.html');
  const styles = await read('src/apps/core/static/css/workspace.css');
  assert.doesNotMatch(template, /autofocus/);
  assert.match(template, /workspace-empty-state workspace-search-empty/);
  assert.match(styles, /\.workspace-search-empty \{ padding: 28px 20px; \}/);
  assert.match(styles, /\.workspace-field input, \.workspace-field select, \.workspace-search-panel input, \.workspace-search-panel select \{ box-sizing: border-box;/);
  assert.match(styles, /\.workspace-dialog input, \.workspace-dialog textarea \{ box-sizing: border-box;/);
});

test('workspace selects use a clearly visible chevron and norm facts stay secondary', async () => {
  const workspaceStyles = await read('src/apps/core/static/css/workspace.css');
  const normaStyles = await read('src/apps/core/static/css/jurix-norma-list.css');
  assert.match(workspaceStyles, /linear-gradient\(45deg, transparent 50%, var\(--figma-blue-light\) 50%\)/);
  assert.match(normaStyles, /\.jurix-norma-fact-label[\s\S]*?font-size: 9px/);
  assert.match(normaStyles, /\.jurix-norma-fact-value[\s\S]*?font-size: 12px/);
  assert.match(normaStyles, /\.jurix-norma-card-title[\s\S]*?font: 700 clamp\(18px/);
});

test('version comparison exposes both texts as labelled stacked evidence on mobile', async () => {
  const template = await read('src/apps/legislation/templates/legislation/norma_compare.html');
  const styles = await read('src/apps/core/static/css/jurix-legacy-shell.css');
  assert.match(template, /class="compare-original-text" role="cell" data-label="Original \(OCR\)"/);
  assert.match(template, /class="compare-consolidated-text" role="cell" data-label="Consolidado"/);
  assert.match(template, /Sem linha correspondente/);
  assert.match(styles, /@media \(max-width:720px\)[\s\S]*?\.compare-diff-header \{ display: none; \}/);
  assert.match(styles, /\.compare-diff-row > code::before \{ content: attr\(data-label\)/);
});

test('public device tree does not present internal extraction confidence as legal certainty', async () => {
  const template = await read('src/apps/legislation/templates/legislation/tree_node.html');
  assert.match(template, /Tipo: \{\{ node\.dispositivo\.get_tipo_display \}\}/);
  assert.doesNotMatch(template, /segmentation_confidence|Confiança:/);
  assert.doesNotMatch(template, /Ordem: \{\{ node\.dispositivo\.ordem \}\}/);
});

