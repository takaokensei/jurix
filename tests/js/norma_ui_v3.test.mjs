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

test('settings select the server-configured model and reset to that exact option', async () => {
  const template = await read('src/apps/legislation/templates/legislation/workspace/settings.html');
  const workspace = await read('src/apps/core/static/js/workspace.js');
  assert.match(template, /option value="\{\{ model \}\}"\{% if model == default_model %\} selected\{% endif %\}/);
  assert.match(workspace, /querySelector\('option\[selected\]'\)/);
});

test('theme preference is applied from the document head before page styles paint', async () => {
  for (const path of [
    'src/apps/legislation/templates/legislation/chatbot.html',
    'src/apps/legislation/templates/legislation/workspace/base.html',
  ]) {
    const template = await read(path);
    const headEnd = template.indexOf('</head>');
    const themeScript = template.indexOf("js/theme.js");
    const firstStylesheet = template.indexOf('css/');
    assert.ok(themeScript >= 0 && themeScript < firstStylesheet && themeScript < headEnd, `${path} must apply theme before styles`);
    assert.equal(template.indexOf("js/theme.js", themeScript + 1), -1, `${path} should load the controller once`);
  }
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
  assert.match(source, /function submitSearchReset\(\)/);
  assert.match(source, /search\.disabled = true;[\s\S]*filterForm\.requestSubmit\(\)/);
});

test('norma list stylesheet contains mobile, reduced motion and print rules', async () => {
  const source = await read('src/apps/core/static/css/jurix-norma-list.css');
  assert.match(source, /@media \(max-width: 720px\)/);
  assert.match(source, /prefers-reduced-motion/);
  assert.match(source, /@media print/);
  assert.match(source, /\.jurix-norma-clear\[hidden\] \{ display: none !important; \}/);
});

test('norma template exposes semantic filters and no hardcoded suggestion cards', async () => {
  const source = await read('src/apps/legislation/templates/legislation/norma_list.html');
  assert.match(source, /name="tipo"/);
  assert.match(source, /name="ano"/);
  assert.match(source, /name="ordenar"/);
  assert.match(source, /jurix-norma-grid/);
  assert.match(source, /jurix-norma-list\.js['"] %\}\?v=20260929-search-reset1/);
  assert.match(source, /jurix-norma-list\.css['"] %\}\?v=20260929-metadata-hierarchy1/);
});

test('chat sidebar exposes the same quick-search action as the workspace shell', async () => {
  const source = await read('src/apps/legislation/templates/legislation/chatbot.html');
  const workspace = await read('src/apps/legislation/templates/legislation/workspace/base.html');
  const topbar = await read('src/apps/legislation/templates/legislation/workspace/_topbar.html');
  assert.match(source, /class="figma-sidebar-item workspace-palette-trigger" data-open-command-palette/);
  assert.match(source, /Busca rápida/);
  assert.match(source, /workspace:settings/);
  assert.match(source, /<aside[^>]+id="sidebar"/);
  const nav = source.slice(source.indexOf('class="figma-nav-list"'), source.indexOf('<!-- Sidebar Footer -->'));
  assert.ok(nav.indexOf("workspace:legal_search") < nav.indexOf("legislation:norma_list"), 'Chat navigation should follow the shared shell order');
  assert.match(workspace, /<aside class="workspace-sidebar" id="sidebar"/);
  assert.match(topbar, /aria-controls="sidebar"[\s\S]*aria-expanded="false"/);
});

test('command palette templates cache-bust the shared keyboard accessibility behavior', async () => {
  const chat = await read('src/apps/legislation/templates/legislation/chatbot.html');
  const workspace = await read('src/apps/legislation/templates/legislation/workspace/base.html');
  const palette = await read('src/apps/core/static/js/command_palette.js');
  assert.match(chat, /command-palette-results[^>]+role="listbox"/);
  assert.match(chat, /js\/command_palette\.js['"] %\}\?v=20260929-combobox-a11y/);
  assert.match(workspace, /js\/command_palette\.js['"] %\}\?v=20260929-combobox-a11y/);
  assert.match(palette, /setAttribute\('role', 'combobox'\)/);
  assert.match(palette, /aria-activedescendant/);
  assert.match(palette, /aria-selected/);
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
  assert.match(template, /class="workspace-search-caveat" role="note"/);
  assert.match(template, /não uma conclusão jurídica/);
  assert.match(styles, /\.workspace-search-caveat \{[^}]*font-size: 12px;[^}]*line-height: 1\.6/);
  assert.match(template, /Buscar no acervo normativo/);
  assert.match(template, /norma_list' %\}\?q=\{\{ query\|urlencode \}\}&amp;tipo=\{\{ norma_type\|urlencode \}\}&amp;ano=\{\{ year\|urlencode \}\}/);
  assert.match(styles, /\.workspace-button-secondary \{[^}]*background: rgba\(255,255,255,\.035\);[^}]*color: var\(--figma-text-body\);/);
  assert.match(styles, /\.workspace-button-secondary:hover \{[^}]*border-color: var\(--figma-blue-light\);/);
  assert.match(styles, /\.workspace-search-empty \{ padding: 28px 20px; \}/);
  assert.match(styles, /\.workspace-field input, \.workspace-field select, \.workspace-search-panel input, \.workspace-search-panel select \{ box-sizing: border-box;/);
  assert.match(styles, /\.workspace-dialog input, \.workspace-dialog textarea \{ box-sizing: border-box;/);
});

test('mobile workspace search stays a compact 44px icon button when its label is hidden', async () => {
  const styles = await read('src/apps/core/static/css/workspace.css');
  const chat = await read('src/apps/legislation/templates/legislation/chatbot.html');
  const workspace = await read('src/apps/legislation/templates/legislation/workspace/base.html');
  assert.match(styles, /@media \(max-width:\s*640px\)[\s\S]*?\.workspace-topbar \.workspace-top-search\s*\{[^}]*flex:\s*0 0 44px;[^}]*width:\s*44px;[^}]*min-width:\s*44px;/);
  assert.match(chat, /css\/workspace\.css['"] %\}\?v=20260929-mobile-search/);
  assert.match(workspace, /css\/workspace\.css['"] %\}\?v=20260929-error-state-layout1/);
});

test('workspace selects use a clearly visible chevron and norm facts stay secondary', async () => {
  const workspaceStyles = await read('src/apps/core/static/css/workspace.css');
  const normaStyles = await read('src/apps/core/static/css/jurix-norma-list.css');
  assert.match(workspaceStyles, /linear-gradient\(45deg, transparent 50%, var\(--figma-blue-light\) 50%\)/);
  assert.match(normaStyles, /\.jurix-norma-fact-label\s*\{[\s\S]*?font-size: 10px;[\s\S]*?letter-spacing: 0\.08em;/);
  assert.match(normaStyles, /\.jurix-norma-fact-value\s*\{[\s\S]*?font-size: 13px;[\s\S]*?font-weight: 600;/);
  assert.match(normaStyles, /\.jurix-norma-card-title[\s\S]*?font: 700 clamp\(18px/);
});

test('workspace sidebar groups primary navigation below branding and anchors utility links at the bottom', async () => {
  const styles = await read('src/apps/core/static/css/workspace.css');
  assert.match(styles, /\.workspace-sidebar \{[^}]*justify-content:\s*flex-start/);
  assert.match(styles, /\.workspace-nav \{[^}]*flex:\s*1;[^}]*align-content:\s*start/);
  assert.match(styles, /\.workspace-sidebar-bottom \{[^}]*margin-top:\s*auto/);
});

test('production error pages are human-readable, recoverable and do not expose exception details', async () => {
  const notFound = await read('src/apps/core/templates/404.html');
  const serverError = await read('src/apps/core/templates/500.html');
  const styles = await read('src/apps/core/static/css/workspace.css');
  assert.match(notFound, /extends "legislation\/workspace\/base\.html"/);
  assert.match(notFound, /Não encontramos esta página/);
  assert.match(notFound, /legislation:norma_list/);
  assert.match(notFound, /workspace:assistant/);
  assert.match(serverError, /Não foi possível carregar esta página/);
  assert.match(serverError, /workspace:assistant/);
  assert.doesNotMatch(serverError, /request\.path|extends "legislation\/workspace\/base\.html"/);
  assert.doesNotMatch(`${notFound}\n${serverError}`, /\{\{\s*exception|technical_500|Request URL|Traceback/);
  assert.match(styles, /\.error-page-content \{[^}]*min-height:\s*100vh;[^}]*place-items:\s*center/);
});

test('norm actions use a responsive grid instead of stranding the official source link', async () => {
  const styles = await read('src/apps/core/static/css/jurix-legal-detail.css');
  const template = await read('src/apps/legislation/templates/legislation/norma_detail.html');
  assert.match(styles, /\.legal-detail-actions\s*\{[^}]*display:\s*grid/);
  assert.match(styles, /grid-template-columns:\s*repeat\(auto-fit,\s*minmax\(min\(100%,\s*15rem\),\s*1fr\)\)/);
  assert.match(styles, /\.legal-detail-actions \.btn\s*\{[^}]*justify-content:\s*center/);
  assert.match(styles, /\.legal-detail-actions \.btn\s*\{[^}]*min-height:\s*44px/);
  assert.match(template, /css\/jurix-legal-detail\.css['"] %\}\?v=20260929-detail-collapsible-text1/);
});

test('norm consolidated text stays available but does not duplicate every device on initial view', async () => {
  const template = await read('src/apps/legislation/templates/legislation/norma_detail.html');
  const styles = await read('src/apps/core/static/css/jurix-legal-detail.css');
  assert.match(template, /<details class="legal-consolidated-details">\s*<summary>Exibir o texto completo da norma<\/summary>\s*<pre>\{\{ consolidated_text \}\}<\/pre>\s*<\/details>/);
  assert.match(styles, /\.legal-consolidated-details > summary\s*\{[^}]*min-height:44px/);
  assert.match(styles, /\.legal-consolidated-details > summary:focus-visible/);
});

test('mobile norm detail keeps secondary metrics compact without squeezing text labels', async () => {
  const styles = await read('src/apps/core/static/css/jurix-legal-detail.css');
  const template = await read('src/apps/legislation/templates/legislation/norma_detail.html');
  assert.match(styles, /@media \(max-width:640px\)[\s\S]*?\.legal-detail-card \.stats-grid \{ grid-template-columns:repeat\(2,minmax\(0,1fr\)\); \}/);
  assert.match(styles, /\.legal-detail-card \.stats-grid \.stat-card:last-child \{ grid-column:1 \/ -1; \}/);
  assert.match(template, /css\/jurix-legal-detail\.css['"] %\}\?v=20260929-detail-collapsible-text1/);
});

test('version comparison exposes both texts as labelled stacked evidence on mobile', async () => {
  const template = await read('src/apps/legislation/templates/legislation/norma_compare.html');
  const styles = await read('src/apps/core/static/css/jurix-legacy-shell.css');
  assert.match(template, /class="compare-original-text" role="cell" data-label="Original \(OCR\)"/);
  assert.match(template, /class="compare-consolidated-text" role="cell" data-label="Consolidado"/);
  assert.match(template, /class="compare-method-note" role="note"/);
  assert.match(template, /podem gerar diferenças sem representar uma alteração jurídica/);
  assert.match(styles, /\.compare-method-note \{[^}]*border-left:\s*3px solid/);
  assert.match(template, /data-line="\{\{ row\.original_number\|default:'—' \}\}"/);
  assert.match(template, /data-line="\{\{ row\.consolidated_number\|default:'—' \}\}"/);
  const missingSideMarkup = template.match(
    /class="compare-side-empty" role="note" aria-label="Sem linha correspondente" title="Sem linha correspondente">Sem correspondente<\/span>/g,
  );
  assert.equal(missingSideMarkup?.length, 2);
  assert.match(styles, /\.compare-side-empty \{[^}]*font: 600 \.68rem\/1\.4 Inter, system-ui, sans-serif/);
  assert.match(styles, /@media \(max-width:720px\)[\s\S]*?\.compare-diff-header \{ display: none; \}/);
  assert.match(styles, /\.compare-diff-row > code::before \{ content: attr\(data-label\) " · linha " attr\(data-line\)/);
});

test('public device tree does not present internal extraction confidence as legal certainty', async () => {
  const template = await read('src/apps/legislation/templates/legislation/tree_node.html');
  const page = await read('src/apps/legislation/templates/legislation/norma_tree.html');
  const behavior = await read('src/apps/core/static/js/jurix-legal-tree.js');
  assert.match(template, /Tipo: \{\{ node\.dispositivo\.get_tipo_display \}\}/);
  assert.match(template, /aria-expanded="true"/);
  assert.match(template, /role="group"/);
  assert.match(template, /data-tree-toggle/);
  assert.match(page, /js\/jurix-legal-tree\.js/);
  for (const key of ['ArrowDown', 'ArrowUp', 'ArrowLeft', 'ArrowRight', 'Home', 'End']) {
    assert.ok(behavior.includes(`'${key}'`), `tree keyboard behavior must include ${key}`);
  }
  assert.doesNotMatch(template, /segmentation_confidence|Confiança:/);
  assert.doesNotMatch(template, /Ordem: \{\{ node\.dispositivo\.ordem \}\}/);
});

