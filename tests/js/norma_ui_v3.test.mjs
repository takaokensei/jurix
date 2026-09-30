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
  assert.match(template, /<option value="compatible">Compatível \(LiteLLM, AirLLM, local\)<\/option>/);
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

test('light theme maps semantic tokens and workspace surfaces instead of leaving dark surfaces behind', async () => {
  const tokens = await read('src/apps/core/static/css/jurix-figma.css');
  const workspace = await read('src/apps/core/static/css/workspace.css');
  const detail = await read('src/apps/core/static/css/jurix-legal-detail.css');
  assert.match(tokens, /:root\[data-theme="light"\]\s*\{[\s\S]*?--figma-bg-root: #F7F9FC;[\s\S]*?--figma-text-white: #0F172A;[\s\S]*?--figma-text-on-accent: #FFFFFF;/);
  assert.match(workspace, /:root\[data-theme="light"\][\s\S]*?\.workspace-card[\s\S]*?background: var\(--figma-bg-surface\)/);
  assert.match(workspace, /\.workspace-button-primary[^}]*color: var\(--figma-text-on-accent\)/);
  assert.match(detail, /\.legal-detail-actions \.btn[^}]*color:var\(--figma-text-on-accent\)/);
  assert.match(tokens, /:root\[data-theme="light"\] \.figma-suggestion-card \{[^}]*background-color: var\(--figma-bg-surface\)/);
  assert.match(tokens, /:root\[data-theme="light"\] \.figma-suggestion-title \{ color: var\(--figma-text-white\); \}/);
  assert.match(tokens, /:root\[data-theme="light"\] \.jurix-suggestion-source-badge,[\s\S]*?color: var\(--figma-blue-dark\) !important/);
});

test('light theme gives the assistant source-summary control semantic foregrounds and surfaces', async () => {
  const source = await read('src/apps/core/static/css/jurix-figma.css');
  assert.match(source, /:root\[data-theme="light"\] \.jurix-sources-pill-btn\s*\{[^}]*background-color:\s*var\(--figma-bg-surface\)[^}]*color:\s*var\(--figma-text-body\)/);
  assert.match(source, /:root\[data-theme="light"\] \.jurix-sources-pill-badge\s*\{[^}]*color:\s*var\(--figma-blue-dark\)/);
  assert.match(source, /:root\[data-theme="light"\] \.jurix-sources-pill-action\s*\{[^}]*color:\s*var\(--figma-blue-primary\)/);
});

test('norm device expansion preserves full text and exposes a reversible accessible state', async () => {
  const template = await read('src/apps/legislation/templates/legislation/norma_detail.html');
  const controller = await read('src/apps/core/static/js/jurix-legal-detail.js');
  assert.match(template, /data-device-text-preview[^>]*>\s*\{\{ disp\.texto\|truncatewords:50 \}\}/);
  assert.match(template, /data-device-text-full hidden>\s*\{\{ disp\.texto \}\}/);
  assert.match(template, /data-expand-device aria-expanded="false" aria-controls="dispositivo-texto-\{\{ disp\.pk \}\}"/);
  assert.match(controller, /preview\.hidden = expanded;[\s\S]*full\.hidden = !expanded;[\s\S]*aria-expanded', String\(expanded\)[\s\S]*Recolher texto/);
  assert.match(controller, /querySelectorAll\('\[data-device-text-preview\], \[data-device-text-full\]'\)[\s\S]*element\.textContent = element\.textContent\.trim\(\)/);
});

test('workspace pages opt into document scrolling and icon-only navigation keeps accessible names', async () => {
  const base = await read('src/apps/legislation/templates/legislation/workspace/base.html');
  const topbar = await read('src/apps/legislation/templates/legislation/workspace/_topbar.html');
  const workspace = await read('src/apps/core/static/css/workspace.css');
  const detail = await read('src/apps/legislation/templates/legislation/norma_detail.html');
  assert.match(base, /class="figma-theme workspace-page workspace-document/);
  assert.match(workspace, /body\.figma-theme\.workspace-document[^}]*overflow-y:\s*auto/);
  assert.match(topbar, /data-workspace-toggle[\s\S]*aria-label="Recolher navegação"/);
  assert.match(workspace, /\.workspace-shell\.is-sidebar-collapsed\s*\{\s*grid-template-columns:\s*72px/);
  assert.match(base, /aria-label="Normas" title="Normas"/);
  assert.doesNotMatch(detail, /class="dispositivo-tipo badge"/);
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

test('norma list recognizes an exact number/year identifier as separate server filters', async () => {
  const source = await read('src/apps/core/static/js/jurix-norma-list.js');
  const template = await read('src/apps/legislation/templates/legislation/norma_list.html');
  assert.match(source, /function splitNormaIdentifier\(\)/);
  assert.match(source, /search\.value = match\[1\];[\s\S]*yearFilter\.value = match\[2\]/);
  assert.match(source, /splitNormaIdentifier\(\);[\s\S]*querySelector\('button\[type="submit"\]'\)/);
  assert.match(template, /jurix-norma-list\.js['"] %\}\?v=20260929-identifier-search1/);
});

test('norma list stylesheet contains mobile, reduced motion and print rules', async () => {
  const source = await read('src/apps/core/static/css/jurix-norma-list.css');
  assert.match(source, /\[data-theme="light"\] \.jurix-norma-status \{\s*color: var\(--figma-green\);/);
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
  assert.match(source, /placeholder="Número, tipo ou ementa…"/);
  assert.match(source, /jurix-norma-list\.js['"] %\}\?v=20260929-identifier-search1/);
  assert.match(source, /jurix-norma-list\.css['"] %\}\?v=20260930-mobile-title-rhythm1/);
});

test('legal search placeholder stays concise while examples remain available in the empty state', async () => {
  const template = await read('src/apps/legislation/templates/legislation/workspace/search.html');
  assert.match(template, /placeholder="Ex\.: zoneamento ou IPTU progressivo"/);
  assert.match(template, /Exemplos: “parcelamento do solo”, “licenciamento ambiental” ou “IPTU progressivo”/);
});

test('legal search follows query-filter-submit reading order and localizes result state', async () => {
  const template = await read('src/apps/legislation/templates/legislation/workspace/search.html');
  const styles = await read('src/apps/core/static/css/workspace.css');
  const queryIndex = template.indexOf('class="workspace-search-input"');
  const filtersIndex = template.indexOf('class="workspace-filter-row"');
  const submitIndex = template.indexOf('type="submit"');
  assert.ok(queryIndex >= 0 && queryIndex < filtersIndex && filtersIndex < submitIndex, 'Keyboard order must be query, filters, then submit');
  assert.match(template, /type="search" name="q" maxlength="200"/);
  assert.match(template, /aria-live="assertive"/);
  assert.match(template, /result_count == 1 %}resultado/);
  assert.match(template, /search_mode == 'semantic' %}Busca semântica/);
  assert.match(template, /search_mode == 'lexical' %}Busca textual/);
  assert.match(styles, /\.workspace-search-panel > \.workspace-button \{ grid-column:2; grid-row:1;/);
  assert.match(styles, /@media \(max-width:900px\)[\s\S]*?\.workspace-search-panel > \.workspace-button \{ grid-column:1; grid-row:3;/);
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

test('assistant recent-history empty-state link is styled and keeps visible keyboard focus', async () => {
  const template = await read('src/apps/legislation/templates/legislation/chatbot.html');
  const styles = await read('src/apps/core/static/css/jurix-figma.css');
  assert.match(template, /class="figma-recent-searches-empty"[\s\S]*id="figma-new-chat-link"/);
  assert.match(styles, /\.figma-recent-searches-empty a\s*\{[^}]*color:\s*var\(--figma-blue-light\)[^}]*text-decoration:\s*none/);
  assert.match(styles, /\.figma-recent-searches-empty a:focus-visible\s*\{[^}]*outline:\s*2px solid var\(--figma-blue-light\)/);
});

test('assistant landing copy describes verifiable legal-research capabilities without accuracy guarantees', async () => {
  const template = await read('src/apps/legislation/templates/legislation/chatbot.html');
  assert.match(template, /Pesquise normas municipais, compare versões e confira os dispositivos que fundamentam cada resposta/);
  assert.match(template, /CORPUS MUNICIPAL[\s\S]*RASTREABILIDADE[\s\S]*FONTES OFICIAIS/);
  assert.doesNotMatch(template, /fundamentação jurídica completa|PRECISÃO JURÍDICA|JURISPRUDÊNCIA|DOUTRINA/);
});

test('assistant sidebar keeps its utility footer fixed while the navigation region can scroll', async () => {
  const source = await read('src/apps/core/static/css/jurix-chat-shell.css');
  const template = await read('src/apps/legislation/templates/legislation/chatbot.html');
  assert.match(source, /\.figma-sidebar\s*\{[^}]*height:\s*auto;[^}]*overflow:\s*hidden;/);
  assert.match(source, /\.figma-sidebar-top\s*\{[^}]*min-height:\s*0;[^}]*overflow-y:\s*auto;/);
  assert.match(source, /\.figma-sidebar-footer\s*\{[^}]*flex:\s*0\s+0\s+auto;/);
  assert.match(template, /css\/jurix-chat-shell\.css['"] %\}\?v=20260929-sidebar-utilities1/);
});

test('workspace sidebar keeps utility actions visible while navigation can scroll', async () => {
  const source = await read('src/apps/core/static/css/workspace.css');
  const template = await read('src/apps/legislation/templates/legislation/workspace/base.html');
  assert.match(source, /\.workspace-sidebar\s*\{[^}]*box-sizing:\s*border-box;[^}]*overflow:\s*hidden;/);
  assert.match(source, /\.workspace-nav\s*\{[^}]*min-height:\s*0;[^}]*overflow-y:\s*auto;/);
  assert.match(source, /\.workspace-sidebar-bottom\s*\{[^}]*flex:\s*0\s+0\s+auto;/);
  assert.match(template, /css\/workspace\.css['"] %\}\?v=20260930-danger-tokens1/);
});

test('assistant and workspace navigation share accessible outline SVG icons', async () => {
  const workspace = await read('src/apps/legislation/templates/legislation/workspace/base.html');
  const assistant = await read('src/apps/legislation/templates/legislation/chatbot.html');
  const styles = await read('src/apps/core/static/css/workspace.css');
  const navigation = workspace.match(/<nav class="workspace-nav"[\s\S]*?<\/nav>/)?.[0] ?? '';
  assert.match(workspace, /class="workspace-nav-icon"[^>]+aria-hidden="true" focusable="false"/);
  assert.doesNotMatch(navigation, /<span aria-hidden="true">[◉⌕▤▱◷⚙⌘]/);
  assert.match(styles, /\.workspace-nav-icon \{[^}]*width: 18px;[^}]*height: 18px;[^}]*flex: 0 0 18px/);
  assert.match(assistant, /id="new-chat-button"[\s\S]*?<svg width="18" height="18"[^>]*aria-hidden="true"/);
  assert.match(assistant, /<path d="M12 20h9"><\/path>[\s\S]*?<path d="M16\.5 3\.5a2\.12 2\.12/);
});

test('command palette templates cache-bust the shared keyboard accessibility behavior', async () => {
  const chat = await read('src/apps/legislation/templates/legislation/chatbot.html');
  const workspace = await read('src/apps/legislation/templates/legislation/workspace/base.html');
  const palette = await read('src/apps/core/static/js/command_palette.js');
  assert.match(chat, /command-palette-results[^>]+role="listbox"/);
  assert.match(chat, /js\/command_palette\.js['"] %\}\?v=20260930-query-race1/);
  assert.match(workspace, /js\/command_palette\.js['"] %\}\?v=20260930-query-race1/);
  assert.match(palette, /setAttribute\('role', 'combobox'\)/);
  assert.match(palette, /aria-activedescendant/);
  assert.match(palette, /aria-selected/);
  assert.match(palette, /loadChatSessionsForSearch\(\)\.then\(\(\) => \{[\s\S]*?updateCommandPaletteResults\(input\.value\)/);
});

test('command palette prioritizes title matches above descriptive matches', async () => {
  const source = await read('src/apps/core/static/js/command_palette.js');
  const chat = await read('src/apps/legislation/templates/legislation/chatbot.html');
  const workspace = await read('src/apps/legislation/templates/legislation/workspace/base.html');
  assert.match(source, /title === queryLower\) return 0[\s\S]*title\.startsWith\(queryLower\)[\s\S]*title\.includes\(queryLower\)[\s\S]*description\.includes\(queryLower\)/);
  assert.match(chat, /js\/command_palette\.js['"] %\}\?v=20260930-query-race1/);
  assert.match(workspace, /js\/command_palette\.js['"] %\}\?v=20260930-query-race1/);
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
  assert.match(template, /norma_list' %\}\?q=\{\{ query\|urlencode \}\}&amp;tipo=\{\{ norma_type\|urlencode \}\}&amp;ano=\{\{ year\|default_if_none:''\|urlencode \}\}/);
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
  assert.match(chat, /css\/workspace\.css['"] %\}\?v=/);
  assert.match(workspace, /css\/workspace\.css['"] %\}\?v=/);
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
  assert.match(template, /css\/jurix-legal-detail\.css['"] %\}\?v=20260930-ementa-disclosure1/);
});

test('missing effective date is not presented as legal certainty in norm list or detail', async () => {
  const list = await read('src/apps/legislation/templates/legislation/norma_list.html');
  const detail = await read('src/apps/legislation/templates/legislation/norma_detail.html');
  assert.match(list, /data_vigencia\|date:'d\/m\/Y'\|default:'Não registrada no corpus'/);
  assert.match(detail, /badge badge-neutral">Data de vigência não registrada no corpus/);
  assert.match(detail, /Confirme a vigência na fonte oficial; o corpus não informa uma data específica\./);
  assert.match(detail, /elif not norma\.data_vigencia %\}badge-neutral/);
  assert.doesNotMatch(detail, /Vigente desde a publicação\*/);
});

test('norm consolidated text stays available but does not duplicate every device on initial view', async () => {
  const template = await read('src/apps/legislation/templates/legislation/norma_detail.html');
  const styles = await read('src/apps/core/static/css/jurix-legal-detail.css');
  assert.match(template, /<details class="legal-consolidated-details">\s*<summary>Exibir o texto completo da norma<\/summary>\s*<pre>\{\{ consolidated_text \}\}<\/pre>\s*<\/details>/);
  assert.match(styles, /\.legal-consolidated-details > summary\s*\{[^}]*min-height:44px/);
  assert.match(styles, /\.legal-consolidated-details > summary:focus-visible/);
});

test('long norm ementa uses a native disclosure while keeping a readable preview', async () => {
  const template = await read('src/apps/legislation/templates/legislation/norma_detail.html');
  const styles = await read('src/apps/core/static/css/jurix-legal-detail.css');
  assert.match(template, /norma\.ementa\|length > 220/);
  assert.match(template, /<details class="legal-detail-ementa legal-detail-ementa--expandable">[\s\S]*?<summary>[\s\S]*?\{\{ norma\.ementa\|truncatechars:180 \}\}[\s\S]*?Ler ementa completa[\s\S]*?<\/summary>[\s\S]*?\{\{ norma\.ementa \}\}[\s\S]*?<\/details>/);
  assert.match(styles, /\.legal-detail-ementa-preview[^}]*-webkit-line-clamp:3/);
  assert.match(styles, /\.legal-detail-ementa--expandable > summary:focus-visible/);
  assert.match(styles, /\.legal-detail-ementa--expandable\[open\] \.legal-detail-ementa-collapse-label/);
});

test('mobile norm detail keeps secondary metrics compact without squeezing text labels', async () => {
  const styles = await read('src/apps/core/static/css/jurix-legal-detail.css');
  const template = await read('src/apps/legislation/templates/legislation/norma_detail.html');
  assert.match(styles, /@media \(max-width:640px\)[\s\S]*?\.legal-detail-card \.stats-grid \{ grid-template-columns:repeat\(2,minmax\(0,1fr\)\); \}/);
  assert.match(styles, /\.legal-detail-card \.stats-grid \.stat-card:last-child \{ grid-column:1 \/ -1; \}/);
  assert.match(template, /css\/jurix-legal-detail\.css['"] %\}\?v=20260930-ementa-disclosure1/);
});

test('version comparison exposes both texts as labelled stacked evidence on mobile', async () => {
  const template = await read('src/apps/legislation/templates/legislation/norma_compare.html');
  const styles = await read('src/apps/core/static/css/jurix-legacy-shell.css');
  assert.match(template, /class="compare-original-text" role="cell" data-label="Original \(OCR\)"/);
  assert.match(template, /class="compare-consolidated-text" role="cell" data-label="Consolidado"/);
  assert.match(template, /class="compare-method-note" role="note"/);
  assert.match(template, /podem gerar diferenças sem representar uma alteração jurídica/);
  assert.match(styles, /\.compare-method-note \{[^}]*border-left:\s*3px solid/);
  assert.match(template, /class="compare-summary" role="group" aria-label="Resumo da comparação"/);
  assert.match(template, /class="compare-metric compare-metric-original"[\s\S]*?linhas no original OCR/);
  assert.match(template, /class="compare-metric compare-metric-consolidated"[\s\S]*?linhas no texto consolidado/);
  assert.match(template, /class="compare-metric compare-metric-events"[\s\S]*?eventos normativos aplicados/);
  assert.match(styles, /\.compare-metric \{[^}]*min-height: 66px/);
  assert.match(styles, /\.compare-metric-consolidated \{ border-inline-start: 3px solid var\(--figma-purple\); \}/);
  assert.match(styles, /@media \(max-width:720px\) \{ \.compare-summary \{ grid-template-columns: 1fr;/);
  assert.match(template, /css\/jurix-legacy-shell\.css['"] %\}\?v=20260930-compare-summary2/);
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
  assert.doesNotMatch(template, /Tipo: \{\{ node\.dispositivo\.get_tipo_display \}\}/);
  assert.match(template, /class="node-title">\{\{ node\.dispositivo \}\}/);
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

test('norma detail gives legal devices clear document hierarchy and readable body text', async () => {
  const template = await read('src/apps/legislation/templates/legislation/norma_detail.html');
  const styles = await read('src/apps/core/static/css/jurix-legal-detail.css');
  assert.match(template, /class="dispositivos-tree"[\s\S]*class="dispositivo-node" data-level=/);
  assert.match(styles, /\.dispositivo-node\s*\{[^}]*border-left:3px solid var\(--figma-blue-primary\)[^}]*border-radius:10px/);
  assert.match(styles, /\.dispositivo-text\s*\{[^}]*max-width:88ch[^}]*text-align:left[^}]*line-height:1\.75/);
  assert.match(styles, /\.dispositivo-node\[data-level="4"\]/);
  assert.match(styles, /@media \(max-width:640px\)[\s\S]*?\.dispositivo-node\[data-level="4"\]\s*\{[^}]*margin-inline-start:24px/);
});

test('norm list mobile title keeps comfortable line spacing when it wraps', async () => {
  const styles = await read('src/apps/core/static/css/jurix-norma-list.css');
  const template = await read('src/apps/legislation/templates/legislation/norma_list.html');
  assert.equal((styles.match(/\.jurix-norma-title \{ font-size: clamp\(30px, 11vw, 44px\); line-height: 1\.12; \}/g) || []).length, 2);
  assert.match(template, /jurix-norma-list\.css['"] %\}\?v=20260930-mobile-title-rhythm1/);
});

test('quill identity is cache-busted and source reveal animates only on expansion', async () => {
  const workspace = await read('src/apps/legislation/templates/legislation/workspace/base.html');
  const chatbot = await read('src/apps/legislation/templates/legislation/chatbot.html');
  const publicBase = await read('src/apps/legislation/templates/legislation/base.html');
  const styles = await read('src/apps/core/static/css/jurix-figma.css');
  assert.match(workspace, /logo-icon\.svg['"] %\}\?v=20260930-quill1/);
  assert.match(chatbot, /data-logo-icon-url="\{\% static 'img\/logo-icon\.svg' \%\}\?v=20260930-quill1/);
  assert.match(publicBase, /apple-touch-icon[^\n]*logo-icon\.png['"] %\}\?v=20260930-quill-png1/);
  assert.match(styles, /\.jurix-source-group\[open\] \.jurix-source-group__cards-inner \{ animation: jurix-evidence-reveal 180ms ease-out both; \}/);
});

test('apple touch icon is a compact transparent PNG rendered from the quill mark', async () => {
  const png = await readFile(new URL('src/apps/core/static/img/logo-icon.png', root));
  assert.deepEqual([...png.subarray(0, 8)], [137, 80, 78, 71, 13, 10, 26, 10]);
  assert.equal(png.readUInt32BE(16), 180);
  assert.equal(png.readUInt32BE(20), 180);
  assert.equal(png[25], 6, 'touch icon should retain RGBA transparency');
});

test('destructive workspace states use theme-aware semantic danger tokens', async () => {
  const tokens = await read('src/apps/core/static/css/jurix-figma.css');
  const workspaceStyles = await read('src/apps/core/static/css/workspace.css');
  const workspace = await read('src/apps/legislation/templates/legislation/workspace/base.html');
  assert.match(tokens, /--figma-red-action:\s*#B42332/);
  assert.match(tokens, /:root\[data-theme="light"\][\s\S]*?--figma-red-action:\s*#B42332/);
  assert.match(workspaceStyles, /\.workspace-history-delete[^}]*color:\s*var\(--figma-text-on-accent\)[^}]*background:\s*var\(--figma-red-action\)/);
  assert.match(workspaceStyles, /\.workspace-button-danger[^}]*background:\s*var\(--figma-red-action\)/);
  assert.match(workspaceStyles, /\.workspace-confirm-icon[^}]*color:\s*var\(--figma-red-soft\)/);
  assert.match(workspaceStyles, /\.workspace-confirm-error[^}]*color:\s*var\(--figma-red\)/);
  assert.match(workspace, /css\/workspace\.css['"] %\}\?v=20260930-danger-tokens1/);
  for (const value of ['#fff', '#b42332', '#a92332', '#fecaca', '#fca5a5']) {
    assert.doesNotMatch(workspaceStyles.toLowerCase(), new RegExp(value.replace('#', '\\#')));
  }
});

