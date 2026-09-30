import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import puppeteer from 'puppeteer-core';
import { test } from 'node:test';
import assert from 'node:assert/strict';

const ROOT_DIR = path.resolve(import.meta.dirname, '../../');
const STATIC_DIR = path.join(ROOT_DIR, 'src/apps/core/static');
const FIXTURES_DIR = path.join(import.meta.dirname, 'fixtures');

const browserPaths = [
  process.env.PUPPETEER_EXECUTABLE_PATH,
  process.env.CHROME_BIN,
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
  'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
  '/usr/bin/google-chrome',
  '/usr/bin/chromium',
  '/usr/bin/chromium-browser',
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
].filter(Boolean);

const executablePath = browserPaths.find((p) => fs.existsSync(p));

function createTestServer(handlers = {}) {
  const mimeTypes = {
    '.js': 'application/javascript; charset=utf-8',
    '.css': 'text/css; charset=utf-8',
    '.png': 'image/png',
    '.svg': 'image/svg+xml',
    '.json': 'application/json; charset=utf-8',
  };

  const server = http.createServer((req, res) => {
    const url = new URL(req.url, `http://${req.headers.host}`);

    // Custom API handler override
    if (handlers[url.pathname]) {
      return handlers[url.pathname](req, res, url);
    }

    // Dynamic router pattern matching for APIs
    for (const [pattern, handler] of Object.entries(handlers)) {
      if (pattern.includes('*') || pattern.includes(':')) {
        const regex = new RegExp('^' + pattern.replace(/:\w+/g, '([^/]+)').replace('*', '.*') + '$');
        if (regex.test(url.pathname)) {
          return handler(req, res, url);
        }
      }
    }

    // Static assets
    if (url.pathname.startsWith('/static/')) {
      const relPath = url.pathname.slice('/static/'.length);
      const filePath = path.join(STATIC_DIR, relPath);
      if (fs.existsSync(filePath) && fs.statSync(filePath).isFile()) {
        const ext = path.extname(filePath).toLowerCase();
        res.writeHead(200, { 'Content-Type': mimeTypes[ext] || 'application/octet-stream' });
        return fs.createReadStream(filePath).pipe(res);
      }
      res.writeHead(404);
      return res.end('Not found');
    }

    // Assistente Pages (HTML)
    if (url.pathname.startsWith('/assistente/')) {
      const isAuth = handlers.isAuthenticated ? handlers.isAuthenticated() : false;
      const fixtureFile = isAuth ? 'chatbot_auth.html' : 'chatbot_anon.html';
      const html = fs.readFileSync(path.join(FIXTURES_DIR, fixtureFile), 'utf8');
      res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
      return res.end(html);
    }

    if (url.pathname === '/workspace-shell-test/') {
      res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
      return res.end(`<!doctype html><html lang="pt-BR"><head>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <link rel="icon" href="data:,">
        <link rel="stylesheet" href="/static/css/jurix-figma.css">
        <link rel="stylesheet" href="/static/css/workspace.css">
      </head><body class="figma-theme workspace-page workspace-document"><div class="workspace-shell">
        <aside id="sidebar" class="workspace-sidebar" data-workspace-sidebar aria-label="Navegação principal">
          <div class="workspace-brand-block"><a class="workspace-brand" href="#home" aria-label="Jurix — Assistente"><span class="workspace-logo"><img src="/static/img/logo-icon.png" alt=""></span><span>Jurix</span></a><a class="workspace-new-action" href="#new" aria-label="Nova pesquisa"><svg class="workspace-nav-icon" aria-hidden="true"></svg><span>Nova pesquisa</span></a></div>
          <nav class="workspace-nav" aria-label="Menu principal">
            ${Array.from({ length: 12 }, (_, index) => { const label = index === 0 ? 'Assistente' : index === 1 ? 'Normas' : `Item de navegação ${index + 1}`; return `<a class="workspace-nav-item" href="#item-${index}" aria-label="${label}" title="${label}"><svg class="workspace-nav-icon" aria-hidden="true"></svg><span>${label}</span></a>`; }).join('')}
          </nav>
          <div class="workspace-sidebar-bottom"><a class="workspace-nav-item" href="/configuracoes/" aria-label="Configurações" title="Configurações"><svg class="workspace-nav-icon" aria-hidden="true"></svg><span>Configurações</span></a><button class="workspace-nav-item workspace-palette-trigger" data-open-command-palette aria-label="Busca rápida, Ctrl K" title="Busca rápida, Ctrl K"><svg class="workspace-nav-icon" aria-hidden="true"></svg><span>Busca rápida</span><kbd>Ctrl K</kbd></button></div>
        </aside><main class="workspace-main"><header class="workspace-topbar">
          <button id="toggle-sidebar" class="workspace-mobile-toggle" data-workspace-toggle aria-controls="sidebar" aria-expanded="false" aria-label="Recolher navegação">Menu</button>
        </header><div class="workspace-content" id="main-content"><a href="#content">Conteúdo</a><div style="height:1600px"></div></div></main>
      </div><script src="/static/js/workspace.js"></script></body></html>`);
    }

    if (url.pathname === '/settings-test/') {
      res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
      return res.end(`<!doctype html><html lang="pt-BR"><head>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <link rel="icon" href="data:,">
        <link rel="stylesheet" href="/static/css/jurix-figma.css">
        <link rel="stylesheet" href="/static/css/workspace.css">
      </head><body class="figma-theme workspace-page"><main class="workspace-content">
        <form class="workspace-stack" data-settings-form>
          <label class="workspace-field"><span>Provedor de geração</span><select name="llm_provider"><option value="ollama">Ollama local</option><option value="openai">OpenAI</option><option value="compatible">Compatível</option></select></label>
          <label class="workspace-field"><span>Modelo</span><select name="model" data-ollama-model><option value="qwen2.5">qwen2.5</option><option value="llama3" selected>llama3</option></select></label>
          <label class="workspace-field" data-external-llm-field hidden><span>Identificador do modelo remoto</span><input name="external_model" autocomplete="off"></label>
          <label class="workspace-field" data-compatible-endpoint-field hidden><span>Endpoint compatível (somente serviço local)</span><input name="llm_endpoint" inputmode="url"></label>
          <label class="workspace-field" data-external-llm-field hidden><span>Chave de API</span><input name="llm_api_key" type="password" autocomplete="new-password"></label>
          <label class="workspace-field"><span>Temperatura</span><input name="temperature" type="number" value="0.3"></label>
          <label class="workspace-field"><span>Fontes</span><input name="sources" type="number" value="5"></label>
          <fieldset><label><input type="radio" name="theme" value="dark" checked>Escuro</label><label><input type="radio" name="theme" value="light">Claro</label><label><input type="radio" name="theme" value="system">Sistema</label></fieldset>
          <fieldset><label><input type="radio" name="density" value="comfortable" checked>Confortável</label><label><input type="radio" name="density" value="compact">Compacta</label></fieldset>
          <button type="button" data-settings-reset>Restaurar padrão</button>
          <button type="submit">Salvar preferências</button><span data-settings-status role="status" aria-live="polite"></span>
        </form></main><script src="/static/js/workspace.js"></script></body></html>`);
    }

    if (url.pathname === '/theme-preference-test/') {
      res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
      return res.end(`<!doctype html><html lang="pt-BR" data-theme="dark"><head>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <link rel="stylesheet" href="/static/css/jurix-figma.css">
        <link rel="stylesheet" href="/static/css/workspace.css">
        <link rel="stylesheet" href="/static/css/jurix-legal-detail.css">
        <link rel="stylesheet" href="/static/css/jurix-chat-shell.css">
        <link rel="stylesheet" href="/static/css/jurix-rag.css">
        <link rel="stylesheet" href="/static/css/jurix-components.css">
      </head><body class="figma-theme workspace-page"><button id="theme-toggle" type="button" aria-pressed="false">Alternar tema</button>
        <section class="workspace-card"><h1>Superfície clara</h1><button class="workspace-button workspace-button-primary">Ação</button></section>
        <div class="legal-detail-actions"><a class="btn" href="#">Abrir norma</a></div>
        <div class="jurix-anonymous-banner">Consulta pública</div>
        <div class="message message-user"><div class="message-body">Pergunta do usuário</div></div>
        <aside class="jurix-sources-drawer-panel"><header class="jurix-sources-drawer-header"><div class="jurix-sources-drawer-title-group"><h3>Fontes Consultadas</h3></div></header><div class="jurix-rag-source__contribution"><span class="jurix-rag-source__contribution-label">Contribuição</span>Trecho de dispositivo</div></aside>
        <div class="sources-section"><button type="button" class="jurix-sources-pill-btn"><span>2 fontes consultadas</span><span class="jurix-sources-pill-badge">Boa correspondência</span><span class="jurix-sources-pill-action">Ver fontes →</span></button></div>
        <div class="messages-wrapper"><div class="message"><div class="message-body"><p>Texto de teste.</p></div></div></div>
        <script src="/static/js/theme.js"></script></body></html>`);
    }

    if (url.pathname === '/history-page-test/') {
      res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
      return res.end(`<!doctype html><html lang="pt-BR"><head>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <link rel="stylesheet" href="/static/css/jurix-figma.css">
        <link rel="stylesheet" href="/static/css/workspace.css">
      </head><body class="figma-theme workspace-page"><main class="workspace-content">
        <section class="workspace-empty-state" data-anonymous-history></section>
      </main><script src="/static/js/jurix-anonymous-history.js"></script>
        <script src="/static/js/jurix-anonymous-history-page.js"></script></body></html>`);
    }

    if (url.pathname === '/history-actions-test/') {
      res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
      return res.end(`<!doctype html><html lang="pt-BR"><head>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <link rel="icon" href="data:,">
        <link rel="stylesheet" href="/static/css/jurix-figma.css">
        <link rel="stylesheet" href="/static/css/workspace.css">
      </head><body class="figma-theme workspace-page"><main class="workspace-content">
        <section class="workspace-history-list" aria-label="Histórico local de teste">
          <article class="workspace-history-card" data-history-card data-session-id="local-a">
            <div class="workspace-history-card__surface"><a class="workspace-history-card__link" href="#a"><div class="workspace-history-main"><span class="workspace-eyebrow">Conversa</span><h2>Consulta sobre a Lei nº 8204/2026</h2></div></a></div>
            <button type="button" class="workspace-history-delete" data-history-delete aria-label="Excluir conversa: Lei nº 8204/2026">Excluir</button>
          </article>
          <article class="workspace-history-card" data-history-card data-session-id="local-b">
            <div class="workspace-history-card__surface"><a class="workspace-history-card__link" href="#b"><div class="workspace-history-main"><span class="workspace-eyebrow">Conversa</span><h2>Consulta sobre o Plano Diretor</h2></div></a></div>
            <button type="button" class="workspace-history-delete" data-history-delete aria-label="Excluir conversa: Plano Diretor">Excluir</button>
          </article>
        </section>
      </main></body></html>`);
    }

    if (url.pathname === '/collection-dialog-test/') {
      res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
      return res.end(`<!doctype html><html lang="pt-BR"><head>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <link rel="stylesheet" href="/static/css/jurix-figma.css">
        <link rel="stylesheet" href="/static/css/workspace.css">
      </head><body class="figma-theme workspace-page">
        <button id="open-collection" data-open-collection-form>Nova coleção</button>
        <dialog class="workspace-dialog" data-collection-dialog aria-labelledby="collection-dialog-title">
          <form class="workspace-form"><h2 id="collection-dialog-title">Nova coleção</h2>
            <label>Nome<input name="name" required></label>
            <div class="workspace-dialog-actions"><button type="button" data-close-collection-form>Cancelar</button><button type="submit">Salvar</button></div>
          </form>
        </dialog><script src="/static/js/jurix-collections.js"></script></body></html>`);
    }

    if (url.pathname === '/tree-test/') {
      res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
      return res.end(`<!doctype html><html lang="pt-BR"><head>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <link rel="icon" href="data:,">
        <link rel="stylesheet" href="/static/css/jurix-figma.css">
        <link rel="stylesheet" href="/static/css/jurix-legacy-shell.css">
      </head><body class="figma-theme"><main><div class="tree" role="tree" aria-label="Árvore de teste">
        <div id="article-1" class="tree-node level-0" role="treeitem" aria-level="1" aria-label="Artigo 1" tabindex="-1" aria-expanded="true">
          <div class="node-header"><span class="node-title">Artigo 1</span><button class="tree-node-toggle" type="button" data-tree-toggle aria-expanded="true" aria-label="Recolher Artigo 1" tabindex="-1"><span aria-hidden="true"></span></button></div>
          <div class="tree-node-children" role="group">
            <div id="article-2" class="tree-node level-1" role="treeitem" aria-level="2" aria-label="Artigo 2" tabindex="-1" aria-expanded="true">
              <div class="node-header"><span class="node-title">Artigo 2</span><button class="tree-node-toggle" type="button" data-tree-toggle aria-expanded="true" aria-label="Recolher Artigo 2" tabindex="-1"><span aria-hidden="true"></span></button></div>
              <div class="tree-node-children" role="group"><div id="item-I" class="tree-node level-2" role="treeitem" aria-level="3" aria-label="Inciso I" tabindex="-1"><div class="node-header"><span class="node-title">Inciso I</span></div></div></div>
            </div>
            <div id="article-3" class="tree-node level-1" role="treeitem" aria-level="2" aria-label="Artigo 3" tabindex="-1"><div class="node-header"><span class="node-title">Artigo 3</span></div></div>
          </div>
        </div>
        <div id="article-4" class="tree-node level-0" role="treeitem" aria-level="1" aria-label="Artigo 4" tabindex="-1"><div class="node-header"><span class="node-title">Artigo 4</span></div></div>
      </div></main><script src="/static/js/jurix-legal-tree.js"></script></body></html>`);
    }

    if (url.pathname === '/device-expansion-test/') {
      const fullText = 'Texto integral do dispositivo com fundamento, condições, prazos, sujeitos e exceções aplicáveis. '.repeat(8).trim();
      res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
      return res.end(`<!doctype html><html lang="pt-BR"><head><meta name="viewport" content="width=device-width, initial-scale=1">
        <link rel="stylesheet" href="/static/css/jurix-figma.css"><link rel="stylesheet" href="/static/css/jurix-legal-detail.css"></head><body class="figma-theme">
        <main class="card legal-detail-card"><div class="dispositivos-tree"><article class="dispositivo-node" data-level="2"><div class="dispositivo-header"><span class="dispositivo-label">Art. 2º &gt; Inciso I</span></div><div class="dispositivo-text" id="dispositivo-texto-fixture"><span data-device-text-preview>Texto resumido em cinquenta palavras.</span><span data-device-text-full hidden>${fullText}</span></div>
        <button type="button" data-expand-device aria-expanded="false" aria-controls="dispositivo-texto-fixture">Ver texto completo</button></article>
        </div></main><script src="/static/js/jurix-legal-detail.js"></script></body></html>`);
    }

    if (url.pathname === '/norma-search-test/') {
      const query = url.searchParams.get('q') || '';
      const type = url.searchParams.get('tipo') || '';
      const year = url.searchParams.get('ano') || '';
      const escapedQuery = query.replaceAll('&', '&amp;').replaceAll('"', '&quot;').replaceAll('<', '&lt;');
      const escapedType = type.replaceAll('&', '&amp;').replaceAll('"', '&quot;').replaceAll('<', '&lt;');
      res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
      return res.end(`<!doctype html><html lang="pt-BR"><head><meta name="viewport" content="width=device-width, initial-scale=1"></head><body>
        <section aria-label="Filtros de normas"><form method="get" id="norma-filter-form">
          <input id="norma-search-input" type="search" name="q" aria-label="Pesquisar normas" value="${escapedQuery}">
          <button id="norma-search-clear" type="button" aria-label="Limpar pesquisa" ${query ? '' : 'hidden'}>×</button>
          <select name="tipo" aria-label="Tipo"><option value="">Todos</option><option value="Lei" ${type === 'Lei' ? 'selected' : ''}>Lei</option></select>
          <select id="norma-ano" name="ano" aria-label="Ano"><option value="">Todos</option><option value="2025" ${year === '2025' ? 'selected' : ''}>2025</option><option value="2026" ${year === '2026' ? 'selected' : ''}>2026</option></select>
          <button type="submit">Pesquisar</button>
        </form></section><p id="results">${query ? '0 resultados' : '3 resultados'}</p>
        <script src="/static/js/jurix-norma-list.js"></script></body></html>`);
    }

    if (url.pathname === '/compare/') {
      res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
      return res.end(`<!doctype html><html lang="pt-BR"><head>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <link rel="stylesheet" href="/static/css/jurix-figma.css">
        <link rel="stylesheet" href="/static/css/jurix-legacy-shell.css">
      </head><body class="figma-theme"><main class="compare-container"><section class="compare-panel original-text">
        <h3>Diferenças linha a linha</h3><div class="compare-diff" role="table">
          <div class="compare-diff-header" role="row"><span role="columnheader">Original (OCR)</span><span role="columnheader">Consolidado</span></div>
          <div class="compare-diff-row compare-diff-changed" role="row">
            <span class="compare-line-number" aria-hidden="true">1</span>
            <code class="compare-original-text" role="cell" data-label="Original (OCR)" data-line="1">Texto original da norma</code>
            <span class="compare-diff-marker" aria-hidden="true">−</span>
            <span class="compare-line-number" aria-hidden="true">1</span>
            <code class="compare-consolidated-text" role="cell" data-label="Consolidado" data-line="1">Texto consolidado da norma</code>
          </div>
          <div class="compare-diff-row compare-diff-added" role="row">
            <span class="compare-line-number" aria-hidden="true"></span>
            <code class="compare-original-text" role="cell" data-label="Original (OCR)" data-line="—"><span class="compare-side-empty" role="note" aria-label="Sem linha correspondente" title="Sem linha correspondente">Sem correspondente</span></code>
            <span class="compare-diff-marker" aria-hidden="true">+</span>
            <span class="compare-line-number" aria-hidden="true">2</span>
            <code class="compare-consolidated-text" role="cell" data-label="Consolidado" data-line="2">Novo dispositivo</code>
          </div>
        </div></section></main></body></html>`);
    }

    res.writeHead(404);
    res.end('Not found');
  });

  // Chromium blocks a small set of otherwise valid HTTP ports (including
  // 1719). Keep browser fixtures in a high, safe range instead of allowing
  // listen(0) to occasionally select one of those ports.
  const nativeListen = server.listen.bind(server);
  let portOffset = 0;
  const safePortBase = 30000 + (process.pid % 10000);
  server.listen = (port, ...args) => nativeListen(
    port === 0 ? safePortBase + portOffset++ : port,
    ...args
  );
  return server;
}

test('real browser: closed mobile workspace navigation is removed from keyboard focus', async () => {
  const server = createTestServer();
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  const port = server.address().port;
  const browser = await puppeteer.launch({
    executablePath,
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'],
  });

  try {
    const page = await browser.newPage();
    const pageErrors = [];
    page.on('pageerror', (error) => pageErrors.push(error.message));
    await page.setViewport({ width: 390, height: 844 });
    await page.goto(`http://127.0.0.1:${port}/workspace-shell-test/`, { waitUntil: 'domcontentloaded' });
    const initialSidebarState = await page.evaluate(() => ({
      viewportWidth: innerWidth,
      inert: document.querySelector('#sidebar')?.inert,
      ariaHidden: document.querySelector('#sidebar')?.getAttribute('aria-hidden'),
      scriptLoaded: [...document.scripts].some((script) => script.src.endsWith('/static/js/workspace.js')),
    }));
    assert.equal(initialSidebarState.inert, true, JSON.stringify({ initialSidebarState, pageErrors }));
    assert.equal(await page.$eval('#sidebar', (sidebar) => sidebar.getAttribute('aria-hidden')), 'true');

    await page.focus('#toggle-sidebar');
    await page.keyboard.press('Tab');
    assert.equal(await page.evaluate(() => document.activeElement.textContent), 'Conteúdo', 'Tab must skip the offscreen sidebar and continue into the page');

    await page.click('#toggle-sidebar');
    await page.waitForFunction(() => document.activeElement?.getAttribute('aria-label') === 'Jurix — Assistente');
    assert.equal(await page.$eval('#sidebar', (sidebar) => sidebar.inert), false);
    assert.equal(await page.$eval('#sidebar', (sidebar) => sidebar.getAttribute('aria-hidden')), 'false');
    await page.keyboard.press('Tab');
    assert.equal(await page.evaluate(() => document.activeElement?.getAttribute('aria-label')), 'Nova pesquisa');
    await page.keyboard.press('Escape');
    assert.equal(await page.evaluate(() => document.activeElement.id), 'toggle-sidebar');
    assert.equal(await page.$eval('#sidebar', (sidebar) => sidebar.inert), true);

    await page.setViewport({ width: 1280, height: 800 });
    await page.waitForFunction(() => document.querySelector('#sidebar')?.inert === false);
    assert.equal(await page.$eval('#sidebar', (sidebar) => sidebar.getAttribute('aria-hidden')), 'false');
  } finally {
    await browser.close();
    server.close();
  }
});

test('real browser: collection dialog preserves focus for keyboard and mobile use', async () => {
  const server = createTestServer();
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  const port = server.address().port;
  const browser = await puppeteer.launch({
    executablePath,
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'],
  });

  try {
    const page = await browser.newPage();
    await page.setViewport({ width: 390, height: 844 });
    await page.goto(`http://127.0.0.1:${port}/collection-dialog-test/`, { waitUntil: 'domcontentloaded' });
    await page.click('#open-collection');
    await page.waitForFunction(() => document.querySelector('[data-collection-dialog]')?.open === true);
    const opened = await page.evaluate(() => ({
      focusedField: document.activeElement.getAttribute('name'),
      bounds: document.querySelector('[data-collection-dialog]').getBoundingClientRect().toJSON(),
      documentWidth: document.documentElement.scrollWidth,
      viewportWidth: document.documentElement.clientWidth,
    }));
    assert.equal(opened.focusedField, 'name');
    assert.ok(opened.bounds.left >= 0 && opened.bounds.right <= opened.viewportWidth, JSON.stringify(opened));
    assert.equal(opened.documentWidth, opened.viewportWidth);

    await page.keyboard.press('Escape');
    await page.waitForFunction(() => document.querySelector('[data-collection-dialog]')?.open === false);
    assert.equal(await page.evaluate(() => document.activeElement.id), 'open-collection');

    await page.click('#open-collection');
    await page.click('[data-close-collection-form]');
    await page.waitForFunction(() => document.querySelector('[data-collection-dialog]')?.open === false);
    assert.equal(await page.evaluate(() => document.activeElement.id), 'open-collection');
  } finally {
    await browser.close();
    server.close();
  }
});

test('real browser: delete confirmation traps focus, cancels safely, and announces request failure', async () => {
  const server = createTestServer({
    isAuthenticated: () => true,
    '/api/v1/chat/sessions/fixture-no-delete/': (req, res) => {
      if (req.method === 'DELETE') {
        res.writeHead(500, { 'Content-Type': 'application/json' });
        return res.end(JSON.stringify({ detail: 'Falha simulada para teste.' }));
      }
      res.writeHead(404);
      return res.end();
    },
  });
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  const port = server.address().port;
  const browser = await puppeteer.launch({
    executablePath,
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'],
  });

  try {
    const page = await browser.newPage();
    const deleteRequestTrace = [];
    page.on('request', (request) => {
      if (request.url().includes('/api/v1/chat/sessions/')) deleteRequestTrace.push(`${request.method()} ${request.url()}`);
    });
    page.on('console', (message) => {
      if (message.type() === 'error') deleteRequestTrace.push(`console: ${message.text()}`);
    });
    await page.setViewport({ width: 390, height: 844 });
    await page.goto(`http://127.0.0.1:${port}/assistente/`, { waitUntil: 'domcontentloaded' });
    await page.waitForFunction(() => typeof window.jurixChat?.deleteSession === 'function');
    await page.evaluate(() => {
      const trigger = document.createElement('button');
      trigger.id = 'test-delete-trigger';
      trigger.textContent = 'Deletar conversa de teste';
      document.querySelector('.figma-workspace').appendChild(trigger);
      trigger.focus();
      window.jurixChat.deleteSession('fixture-no-delete');
    });
    await page.waitForFunction(() => document.querySelector('#delete-session-modal')?.classList.contains('active'));

    const opened = await page.evaluate(() => ({
      role: document.querySelector('#delete-session-modal').getAttribute('role'),
      modal: document.querySelector('#delete-session-modal').getAttribute('aria-modal'),
      hidden: document.querySelector('#delete-session-modal').getAttribute('aria-hidden'),
      labelledBy: document.querySelector('#delete-session-modal').getAttribute('aria-labelledby'),
      describedBy: document.querySelector('#delete-session-modal').getAttribute('aria-describedby'),
      shellInert: document.querySelector('.figma-workspace').inert,
      focus: document.activeElement.id,
    }));
    assert.deepEqual(opened, {
      role: 'dialog',
      modal: 'true',
      hidden: 'false',
      labelledBy: 'delete-modal-title',
      describedBy: 'delete-modal-description',
      shellInert: true,
      focus: 'delete-modal-cancel',
    });

    await page.keyboard.press('Tab');
    assert.equal(await page.evaluate(() => document.activeElement.id), 'delete-modal-confirm');
    await page.keyboard.press('Tab');
    assert.equal(await page.evaluate(() => document.activeElement.id), 'delete-modal-cancel');
    await page.keyboard.down('Shift');
    await page.keyboard.press('Tab');
    await page.keyboard.up('Shift');
    assert.equal(await page.evaluate(() => document.activeElement.id), 'delete-modal-confirm');

    await page.keyboard.press('Escape');
    await page.waitForFunction(() => document.querySelector('#delete-session-modal')?.getAttribute('aria-hidden') === 'true');
    assert.equal(await page.evaluate(() => document.querySelector('.figma-workspace').inert), false);
    assert.equal(await page.evaluate(() => document.activeElement.id), 'test-delete-trigger');

    await page.evaluate(() => window.jurixChat.deleteSession('fixture-no-delete'));
    await page.waitForFunction(() => document.querySelector('#delete-session-modal')?.classList.contains('active'));
    await page.click('#delete-modal-cancel');
    assert.equal(await page.evaluate(() => document.activeElement.id), 'test-delete-trigger');
    assert.equal(await page.$eval('#delete-session-modal', (modal) => modal.inert), true);

    await page.evaluate(() => window.jurixChat.deleteSession('fixture-no-delete'));
    await page.waitForFunction(() => document.querySelector('#delete-session-modal')?.classList.contains('active'));
    await new Promise((resolve) => setTimeout(resolve, 450));
    await Promise.all([
      page.waitForFunction(() => document.querySelector('#chat-toast-notification')?.textContent.includes('Erro ao deletar conversa'), { timeout: 5000 }),
      page.click('#delete-modal-confirm'),
    ]).catch(async (error) => {
      const state = await page.evaluate(() => ({
        modal: document.querySelector('#delete-session-modal')?.className,
        focus: document.activeElement?.id,
        toast: document.querySelector('#chat-toast-notification')?.textContent,
      }));
      throw new Error(`${error.message}; delete state: ${JSON.stringify(state)}; trace: ${JSON.stringify(deleteRequestTrace)}`);
    });
    const failureNotice = await page.$eval('#chat-toast-notification', (toast) => ({
      role: toast.getAttribute('role'),
      live: toast.getAttribute('aria-live'),
      atomic: toast.getAttribute('aria-atomic'),
      text: toast.textContent,
    }));
    assert.deepEqual(failureNotice, {
      role: 'alert',
      live: 'assertive',
      atomic: 'true',
      text: 'Erro ao deletar conversa. Tente novamente.',
    });
  } finally {
    await browser.close();
    server.close();
  }
});

test('real browser: history deletion keeps keyboard focus on the next conversation', async () => {
  const server = createTestServer();
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const port = server.address().port;
  const browser = await puppeteer.launch({
    executablePath,
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'],
  });

  try {
    const page = await browser.newPage();
    await page.setViewport({ width: 390, height: 844 });
    const consoleErrors = [];
    page.on('pageerror', (error) => consoleErrors.push(error.message));
    page.on('console', (message) => {
      if (message.type() === 'error') consoleErrors.push(message.text());
    });
    const response = await page.goto(`http://127.0.0.1:${port}/history-actions-test/`, { waitUntil: 'domcontentloaded' });
    assert.equal(response.status(), 200);
    await page.evaluate(() => {
      window.__deleteRequests = [];
      window.JurixChatAPI = { deleteSession: async (id) => window.__deleteRequests.push(id) };
    });
    await page.addScriptTag({ url: `/static/js/jurix-history-actions.js?v=20260930-post-delete-focus1` });

    const trigger = '[data-history-card][data-session-id="local-a"] [data-history-delete]';
    await page.focus(trigger);
    await page.keyboard.press('Enter');
    await page.waitForFunction(() => document.querySelector('[role="dialog"][aria-hidden="false"]')
      && document.activeElement?.hasAttribute('data-history-cancel'));
    const dialog = await page.evaluate(() => ({
      modal: document.querySelector('[role="dialog"]').getAttribute('aria-modal'),
      label: document.querySelector('[role="dialog"]').getAttribute('aria-labelledby'),
      focus: document.activeElement.getAttribute('data-history-cancel') !== null,
    }));
    assert.deepEqual(dialog, { modal: 'true', label: 'history-delete-title', focus: true });

    await page.keyboard.press('Tab');
    assert.equal(await page.evaluate(() => document.activeElement.hasAttribute('data-history-confirm')), true);
    await page.keyboard.press('Tab');
    assert.equal(await page.evaluate(() => document.activeElement.hasAttribute('data-history-cancel')), true);
    await page.keyboard.down('Shift');
    await page.keyboard.press('Tab');
    await page.keyboard.up('Shift');
    assert.equal(await page.evaluate(() => document.activeElement.hasAttribute('data-history-confirm')), true);
    await page.keyboard.press('Escape');
    await page.waitForFunction(() => document.querySelector('[role="dialog"]')?.getAttribute('aria-hidden') === 'true');
    assert.equal(await page.evaluate(() => document.activeElement.matches('[data-history-card] [data-history-delete]')), true);

    await page.keyboard.press('Enter');
    await page.waitForFunction(() => document.querySelector('[role="dialog"][aria-hidden="false"]')
      && document.activeElement?.hasAttribute('data-history-cancel'));
    await page.click('[data-history-confirm]');
    await page.waitForFunction(() => document.querySelectorAll('[data-history-card]').length === 1);
    const afterDelete = await page.evaluate(() => ({
      remainingId: document.querySelector('[data-history-card]')?.dataset.sessionId,
      focusedTag: document.activeElement?.tagName,
      focusedText: document.activeElement?.textContent.trim(),
      focusedSessionId: document.activeElement?.closest('[data-history-card]')?.dataset.sessionId,
      dialogHidden: document.querySelector('[role="dialog"]').getAttribute('aria-hidden'),
      deleteRequests: window.__deleteRequests,
      viewportWidth: document.documentElement.clientWidth,
      documentWidth: document.documentElement.scrollWidth,
    }));
    assert.equal(afterDelete.remainingId, 'local-b');
    assert.equal(afterDelete.focusedTag, 'A');
    assert.equal(afterDelete.focusedSessionId, 'local-b');
    assert.equal(afterDelete.dialogHidden, 'true');
    assert.equal(afterDelete.viewportWidth, 390);
    assert.equal(afterDelete.documentWidth, 390);
    assert.deepEqual(afterDelete.deleteRequests, ['local-a']);
    assert.deepEqual(consoleErrors, []);
  } finally {
    await browser.close();
    server.close();
  }
});

test('real browser: reduced-motion preference suppresses assistant and workspace transitions', async () => {
  const server = createTestServer();
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  const port = server.address().port;
  const browser = await puppeteer.launch({
    executablePath,
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'],
  });

  try {
    const page = await browser.newPage();
    await page.setViewport({ width: 390, height: 844 });
    await page.emulateMediaFeatures([{ name: 'prefers-reduced-motion', value: 'reduce' }]);
    await page.goto(`http://127.0.0.1:${port}/assistente/`, { waitUntil: 'domcontentloaded' });
    await page.evaluate(() => {
      window.JurixRagUI.openSourcesDrawer([]);
      window.JurixRagUI.closeSourcesDrawer();
    });
    const assistantMotion = await page.$eval('#jurix-sources-drawer-panel', (element) => ({
      reduced: matchMedia('(prefers-reduced-motion: reduce)').matches,
      transition: getComputedStyle(element).transitionDuration,
      animation: getComputedStyle(element).animationDuration,
    }));
    assert.equal(assistantMotion.reduced, true);
    assert.ok(assistantMotion.transition.split(',').every((value) => parseFloat(value) < 0.001), JSON.stringify(assistantMotion));
    assert.ok(assistantMotion.animation.split(',').every((value) => parseFloat(value) < 0.001), JSON.stringify(assistantMotion));

    await page.goto(`http://127.0.0.1:${port}/workspace-shell-test/`, { waitUntil: 'domcontentloaded' });
    const workspaceMotion = await page.$eval('#sidebar', (element) => ({
      reduced: matchMedia('(prefers-reduced-motion: reduce)').matches,
      transition: getComputedStyle(element).transitionDuration,
      animation: getComputedStyle(element).animationDuration,
    }));
    assert.equal(workspaceMotion.reduced, true);
    assert.ok(workspaceMotion.transition.split(',').every((value) => parseFloat(value) < 0.001), JSON.stringify(workspaceMotion));
    assert.ok(workspaceMotion.animation.split(',').every((value) => parseFloat(value) < 0.001), JSON.stringify(workspaceMotion));
  } finally {
    await browser.close();
    server.close();
  }
});

test('real browser: settings report when browser storage rejects preferences', async () => {
  const server = createTestServer();
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  const port = server.address().port;
  const browser = await puppeteer.launch({
    executablePath,
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'],
  });

  try {
    const page = await browser.newPage();
    await page.setViewport({ width: 390, height: 844 });
    await page.goto(`http://127.0.0.1:${port}/settings-test/`, { waitUntil: 'domcontentloaded' });
    await page.evaluate(() => {
      localStorage.setItem('jurix-preferences', JSON.stringify({
        model: 'qwen2.5', temperature: 0.8, sources: 3, theme: 'light', density: 'compact',
      }));
      Storage.prototype.setItem = function setItem() {
        throw new DOMException('Storage quota exceeded', 'QuotaExceededError');
      };
    });
    await page.click('input[name="theme"][value="light"]');
    await page.click('button[type="submit"]');

    const result = await page.evaluate(() => ({
      theme: document.documentElement.dataset.theme,
      status: document.querySelector('[data-settings-status]').textContent,
      warning: document.querySelector('[data-settings-status]').classList.contains('is-warning'),
    }));
    assert.equal(result.theme, 'light', 'the selected theme still applies in the current page');
    assert.match(result.status, /aplicadas, mas não foi possível salvá-las/);
    assert.equal(result.warning, true);

    await page.evaluate(() => {
      Storage.prototype.removeItem = function removeItem() {
        throw new DOMException('Storage is blocked', 'SecurityError');
      };
    });
    await page.click('[data-settings-reset]');
    const reset = await page.evaluate(() => ({
      theme: document.documentElement.dataset.theme,
      checkedTheme: document.querySelector('input[name="theme"]:checked')?.value,
      model: document.querySelector('[name="model"]').value,
      status: document.querySelector('[data-settings-status]').textContent,
      warning: document.querySelector('[data-settings-status]').classList.contains('is-warning'),
      stored: JSON.parse(localStorage.getItem('jurix-preferences')),
    }));
    assert.equal(reset.theme, 'dark');
    assert.equal(reset.checkedTheme, 'dark');
    assert.equal(reset.model, 'llama3', 'reset must use the server-selected model, not the first option');
    assert.match(reset.status, /não foi possível remover as preferências salvas/);
    assert.equal(reset.warning, true);
    assert.equal(reset.stored.theme, 'light', 'failed removal must not pretend the stored preference was cleared');
    assert.equal(reset.stored.model, 'qwen2.5');
  } finally {
    await browser.close();
    server.close();
  }
});

test('real browser: provider settings expose a labelled keyboard path without hidden fields', async () => {
  const server = createTestServer();
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const port = server.address().port;
  const browser = await puppeteer.launch({
    executablePath,
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'],
  });

  try {
    const page = await browser.newPage();
    await page.setViewport({ width: 390, height: 844 });
    const consoleErrors = [];
    page.on('pageerror', (error) => consoleErrors.push(error.message));
    page.on('console', (message) => {
      if (message.type() === 'error') consoleErrors.push(message.text());
    });
    const response = await page.goto(`http://127.0.0.1:${port}/settings-test/`, { waitUntil: 'domcontentloaded' });
    assert.equal(response.status(), 200);

    await page.focus('select[name="llm_provider"]');
    await page.keyboard.press('End');
    await page.waitForFunction(() => document.querySelector('select[name="llm_provider"]')?.value === 'compatible'
      && !document.querySelector('[data-compatible-endpoint-field]')?.hidden);
    const compatibleState = await page.evaluate(() => ({
      ollamaHidden: document.querySelector('[name="model"]').closest('.workspace-field').hidden,
      remoteModelVisible: !document.querySelector('[name="external_model"]').closest('.workspace-field').hidden,
      endpointVisible: !document.querySelector('[name="llm_endpoint"]').closest('.workspace-field').hidden,
      apiKeyVisible: !document.querySelector('[name="llm_api_key"]').closest('.workspace-field').hidden,
      apiKeyType: document.querySelector('[name="llm_api_key"]').type,
      labels: ['external_model', 'llm_endpoint', 'llm_api_key'].map((name) => ({
        name,
        label: document.querySelector(`[name="${name}"]`).labels?.[0]?.innerText.trim(),
      })),
    }));
    assert.deepEqual(compatibleState, {
      ollamaHidden: true,
      remoteModelVisible: true,
      endpointVisible: true,
      apiKeyVisible: true,
      apiKeyType: 'password',
      labels: [
        { name: 'external_model', label: 'Identificador do modelo remoto' },
        { name: 'llm_endpoint', label: 'Endpoint compatível (somente serviço local)' },
        { name: 'llm_api_key', label: 'Chave de API' },
      ],
    });

    const keyboardOrder = [];
    for (let index = 0; index < 4; index += 1) {
      await page.keyboard.press('Tab');
      keyboardOrder.push(await page.evaluate(() => document.activeElement?.getAttribute('name')));
    }
    assert.deepEqual(keyboardOrder, ['external_model', 'llm_endpoint', 'llm_api_key', 'temperature']);

    await page.focus('select[name="llm_provider"]');
    await page.keyboard.press('Home');
    await page.waitForFunction(() => document.querySelector('select[name="llm_provider"]')?.value === 'ollama'
      && document.querySelector('[data-compatible-endpoint-field]')?.hidden);
    const ollamaState = await page.evaluate(() => ({
      modelVisible: !document.querySelector('[name="model"]').closest('.workspace-field').hidden,
      externalFieldsHidden: [...document.querySelectorAll('[data-external-llm-field]')].every((field) => field.hidden),
      endpointHidden: document.querySelector('[data-compatible-endpoint-field]').hidden,
      viewportWidth: document.documentElement.clientWidth,
      documentWidth: document.documentElement.scrollWidth,
    }));
    assert.deepEqual(ollamaState, {
      modelVisible: true,
      externalFieldsHidden: true,
      endpointHidden: true,
      viewportWidth: 390,
      documentWidth: 390,
    });
    assert.deepEqual(consoleErrors, []);
  } finally {
    await browser.close();
    server.close();
  }
});

test('real browser: theme preference stays synchronized with the legacy toggle', async () => {
  const server = createTestServer();
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  const port = server.address().port;
  const browser = await puppeteer.launch({
    executablePath,
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'],
  });

  try {
    const page = await browser.newPage();
    await page.emulateMediaFeatures([{ name: 'prefers-color-scheme', value: 'dark' }]);
    await page.goto(`http://127.0.0.1:${port}/theme-preference-test/`, { waitUntil: 'domcontentloaded' });
    await page.evaluate(() => {
      localStorage.setItem('jurix-preferences', JSON.stringify({ theme: 'light', density: 'compact' }));
      localStorage.setItem('jurix-theme', 'dark');
    });
    await page.reload({ waitUntil: 'domcontentloaded' });
    assert.equal(await page.evaluate(() => document.documentElement.dataset.theme), 'light');
    assert.equal(await page.evaluate(() => localStorage.getItem('jurix-theme')), 'light');
    const lightSurfaces = await page.evaluate(() => {
      const colors = (element) => ({
        color: getComputedStyle(element).color,
        background: getComputedStyle(element).backgroundColor,
      });
      return {
        body: getComputedStyle(document.body).backgroundColor,
        card: colors(document.querySelector('.workspace-card')),
        primary: colors(document.querySelector('.workspace-button-primary')),
        normAction: colors(document.querySelector('.legal-detail-actions .btn')),
        banner: colors(document.querySelector('.jurix-anonymous-banner')),
        userBubble: colors(document.querySelector('.message-user .message-body')),
        sourceHeader: colors(document.querySelector('.jurix-sources-drawer-header')),
        contribution: colors(document.querySelector('.jurix-rag-source__contribution')),
        sourcePill: colors(document.querySelector('.jurix-sources-pill-btn')),
        sourceBadge: colors(document.querySelector('.jurix-sources-pill-badge')),
        sourceAction: colors(document.querySelector('.jurix-sources-pill-action')),
      };
    });
    assert.equal(lightSurfaces.body, 'rgb(247, 249, 252)');
    assert.equal(lightSurfaces.card.background, 'rgb(255, 255, 255)');
    const contrast = (foreground, background) => {
      const luminance = (color) => {
        const channels = color.match(/\d+/g).slice(0, 3).map((channel) => Number(channel) / 255)
          .map((channel) => channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4);
        return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
      };
      const values = [luminance(foreground), luminance(background)].sort((a, b) => b - a);
      return (values[0] + 0.05) / (values[1] + 0.05);
    };
    assert.ok(contrast(lightSurfaces.primary.color, lightSurfaces.primary.background) >= 4.5, JSON.stringify(lightSurfaces.primary));
    assert.ok(contrast(lightSurfaces.normAction.color, lightSurfaces.normAction.background) >= 4.5, JSON.stringify(lightSurfaces.normAction));
    assert.ok(contrast(lightSurfaces.sourcePill.color, lightSurfaces.sourcePill.background) >= 4.5, JSON.stringify(lightSurfaces.sourcePill));
    assert.ok(contrast(lightSurfaces.sourceBadge.color, lightSurfaces.sourceBadge.background) >= 4.5, JSON.stringify(lightSurfaces.sourceBadge));
    // The action label has a transparent background; measure it against the
    // actual light page surface instead of treating rgba(0, 0, 0, 0) as black.
    assert.ok(contrast(lightSurfaces.sourceAction.color, lightSurfaces.body) >= 4.5, JSON.stringify(lightSurfaces.sourceAction));
    assert.equal(lightSurfaces.banner.background, 'rgb(255, 255, 255)');
    assert.equal(lightSurfaces.userBubble.color, 'rgb(15, 23, 42)');
    assert.equal(lightSurfaces.sourceHeader.background, 'rgb(255, 255, 255)');
    assert.equal(lightSurfaces.contribution.color, 'rgb(51, 65, 85)');
    assert.deepEqual(await page.evaluate(() => ({
      density: document.documentElement.dataset.density,
      bodyPadding: getComputedStyle(document.querySelector('.message-body')).padding,
    })), { density: 'compact', bodyPadding: '12px 16px' });

    await page.click('#theme-toggle');
    assert.deepEqual(await page.evaluate(() => ({
      theme: document.documentElement.dataset.theme,
      preference: JSON.parse(localStorage.getItem('jurix-preferences')).theme,
      legacy: localStorage.getItem('jurix-theme'),
    })), { theme: 'dark', preference: 'dark', legacy: 'dark' });

    await page.evaluate(() => {
      const settings = JSON.parse(localStorage.getItem('jurix-preferences'));
      settings.theme = 'system';
      settings.density = 'comfortable';
      localStorage.setItem('jurix-preferences', JSON.stringify(settings));
      localStorage.setItem('jurix-theme', 'light');
    });
    await page.reload({ waitUntil: 'domcontentloaded' });
    assert.deepEqual(await page.evaluate(() => ({
      theme: document.documentElement.dataset.theme,
      preference: JSON.parse(localStorage.getItem('jurix-preferences')).theme,
      density: document.documentElement.dataset.density,
      bodyPadding: getComputedStyle(document.querySelector('.message-body')).padding,
    })), { theme: 'dark', preference: 'system', density: 'comfortable', bodyPadding: '16px 20px' });
  } finally {
    await browser.close();
    server.close();
  }
});

test('real browser: anonymous history survives reload (F5) and direct URL navigation', async () => {
  const sseEvents = [
    { type: 'chunk', chunk: 'Resposta anônima persistida ' },
    { type: 'chunk', chunk: 'com sucesso.' },
    { type: 'done', answer: 'Resposta anônima persistida com sucesso.', session_id: null },
  ];

  const server = createTestServer({
    isAuthenticated: () => false,
    '/api/v1/search/answer/stream/': (req, res) => {
      res.writeHead(200, {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
      });
      for (const ev of sseEvents) {
        res.write(`data: ${JSON.stringify(ev)}\n\n`);
      }
      res.end();
    },
    '/api/v1/chat/sessions/': (req, res) => {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ success: true, sessions: [] }));
    },
  });

  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  const port = server.address().port;
  const baseUrl = `http://127.0.0.1:${port}/assistente/`;

  const browser = await puppeteer.launch({
    executablePath,
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'],
  });

  try {
    const page = await browser.newPage();
    await page.goto(baseUrl, { waitUntil: 'domcontentloaded' });

    // Type and send question via hero search input
    await page.waitForSelector('#hero-search-input');
    await page.type('#hero-search-input', 'Qual é a norma municipal?');
    await page.keyboard.press('Enter');

    // Wait for the assistant answer to finish streaming
    await page.waitForFunction(() => {
      const msgs = document.querySelectorAll('.message-assistant');
      return msgs.length > 0 && msgs[0].textContent.includes('Resposta anônima persistida com sucesso.');
    }, { timeout: 5000 });

    const currentUrl = page.url();
    assert.match(currentUrl, /\/assistente\/local-[a-f0-9-]+/);

    // Verify session stored in localStorage
    const storedHistory = await page.evaluate(() => localStorage.getItem('jurix:anonymous-history:v2'));
    assert.ok(storedHistory, 'O histórico anônimo deve estar salvo no localStorage');
    const parsed = JSON.parse(storedHistory);
    assert.equal(parsed.sessions.length, 1);
    assert.equal(parsed.sessions[0].messages.length, 2);

    const fixedMessageTimes = ['2020-01-02T03:04:00.000Z', '2020-01-02T03:05:00.000Z'];
    const expectedMessageTimes = await page.evaluate((times) => {
      const history = JSON.parse(localStorage.getItem('jurix:anonymous-history:v2'));
      history.sessions[0].messages.forEach((message, index) => {
        message.created_at = times[index];
      });
      localStorage.setItem('jurix:anonymous-history:v2', JSON.stringify(history));
      return times.map((time) => new Date(time).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' }));
    }, fixedMessageTimes);

    // 1. REAL F5 (Reload)
    await page.reload({ waitUntil: 'domcontentloaded' });

    // After reload, the messages must be restored on screen
    await page.waitForFunction(() => {
      const msgs = document.querySelectorAll('.message-assistant');
      return msgs.length > 0 && msgs[0].textContent.includes('Resposta anônima persistida com sucesso.');
    }, { timeout: 5000 });

    const restoredText = await page.$eval('.message-assistant', (el) => el.textContent);
    assert.ok(restoredText.includes('Resposta anônima persistida com sucesso.'));
    const restoredMessageTimes = await page.$$eval('.message-time', (nodes) => nodes.map((node) => node.textContent));
    assert.deepEqual(restoredMessageTimes, expectedMessageTimes, 'F5 must preserve original user and assistant message times');

    // 2. Direct URL navigation in a new tab
    const page2 = await browser.newPage();
    await page2.goto(currentUrl, { waitUntil: 'domcontentloaded' });

    await page2.waitForFunction(() => {
      const msgs = document.querySelectorAll('.message-assistant');
      return msgs.length > 0 && msgs[0].textContent.includes('Resposta anônima persistida com sucesso.');
    }, { timeout: 5000 });

    const directNavText = await page2.$eval('.message-assistant', (el) => el.textContent);
    assert.ok(directNavText.includes('Resposta anônima persistida com sucesso.'));
    const directNavMessageTimes = await page2.$$eval('.message-time', (nodes) => nodes.map((node) => node.textContent));
    assert.deepEqual(directNavMessageTimes, expectedMessageTimes, 'Direct URL restoration must preserve persisted times');
    await page2.close();
  } finally {
    await browser.close();
    server.close();
  }
});

test('real browser: keyboard navigation from anonymous history restores the selected chat', async () => {
  const server = createTestServer({ isAuthenticated: () => false });
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  const port = server.address().port;
  const browser = await puppeteer.launch({
    executablePath,
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'],
  });

  try {
    const page = await browser.newPage();
    await page.setViewport({ width: 390, height: 844 });
    await page.goto(`http://127.0.0.1:${port}/history-page-test/`, { waitUntil: 'domcontentloaded' });
    await page.evaluate(() => {
      const timestamp = new Date().toISOString();
      localStorage.setItem('jurix:anonymous-history:v2', JSON.stringify({
        schema: 2,
        sessions: [{
          id: 'local-keyboard-history-01',
          title: 'Prazo de licença municipal',
          created_at: timestamp,
          updated_at: timestamp,
          messages: [
            { role: 'user', content: 'Qual o prazo da licença?', created_at: timestamp, sources: [] },
            { role: 'assistant', content: 'A norma prevê 30 dias.', created_at: timestamp, sources: [] },
          ],
        }],
      }));
    });
    await page.reload({ waitUntil: 'domcontentloaded' });
    assert.equal(await page.$eval('.workspace-history-card h2', (el) => el.textContent), 'Prazo de licença municipal');
    assert.equal(await page.$eval('.workspace-history-card', (el) => el.getAttribute('href')), '/assistente/local-keyboard-history-01/');

    await page.focus('.workspace-history-card');
    await Promise.all([
      page.waitForNavigation({ waitUntil: 'domcontentloaded' }),
      page.keyboard.press('Enter'),
    ]);
    await page.waitForSelector('.message-assistant .message-body');
    const conversation = await page.evaluate(() => ({
      path: location.pathname,
      text: document.querySelector('#messages-container')?.innerText || '',
      width: document.documentElement.scrollWidth,
      viewport: innerWidth,
    }));
    assert.equal(conversation.path, '/assistente/local-keyboard-history-01/');
    assert.match(conversation.text, /Qual o prazo da licença\?/);
    assert.match(conversation.text, /A norma prevê 30 dias\./);
    assert.equal(conversation.width, conversation.viewport);

    await page.goBack({ waitUntil: 'domcontentloaded' });
    assert.equal(await page.$eval('.workspace-history-card h2', (el) => el.textContent), 'Prazo de licença municipal');
  } finally {
    await browser.close();
    server.close();
  }
});

test('real browser: authenticated history multi-page pagination and scroll retention', async () => {
  let requestedBeforeCursors = [];

  const server = createTestServer({
    isAuthenticated: () => true,
    '/api/v1/chat/sessions/': (req, res) => {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ success: true, sessions: [{ id: 10, slug: 'sessao-10', title: 'Sessão Longa' }] }));
    },
    '/api/v1/chat/sessions/10/': (req, res, url) => {
      const before = url.searchParams.get('before');
      requestedBeforeCursors.push(before);

      let messages = [];
      let hasMore = false;
      let nextCursor = null;

      if (!before) {
        // Page 1: messages 41 to 60 (20 msgs)
        messages = Array.from({ length: 20 }, (_, i) => ({
          id: 41 + i,
          role: (41 + i) % 2 === 1 ? 'user' : 'assistant',
          content: `Mensagem Real ${41 + i}`,
          created_at: new Date(1700000000000 + (41 + i) * 1000).toISOString(),
        }));
        hasMore = true;
        nextCursor = 'page1-cursor';
      } else if (before === 'page1-cursor') {
        // Page 2: messages 21 to 40 (20 msgs)
        messages = Array.from({ length: 20 }, (_, i) => ({
          id: 21 + i,
          role: (21 + i) % 2 === 1 ? 'user' : 'assistant',
          content: `Mensagem Real ${21 + i}`,
          created_at: new Date(1700000000000 + (21 + i) * 1000).toISOString(),
        }));
        hasMore = true;
        nextCursor = 'page2-cursor';
      } else if (before === 'page2-cursor') {
        // Page 3: messages 1 to 20 (20 msgs)
        messages = Array.from({ length: 20 }, (_, i) => ({
          id: 1 + i,
          role: (1 + i) % 2 === 1 ? 'user' : 'assistant',
          content: `Mensagem Real ${1 + i}`,
          created_at: new Date(1700000000000 + (1 + i) * 1000).toISOString(),
        }));
        hasMore = false;
        nextCursor = null;
      }

      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({
        success: true,
        session: { id: 10, slug: 'sessao-10', title: 'Sessão Longa' },
        messages,
        has_more: hasMore,
        next_cursor: nextCursor,
      }));
    },
    '/api/v1/chat/sessions/slug/sessao-10/': (req, res, url) => {
      // Forward to session 10 handler
      server.emit('request', Object.assign(req, { url: `/api/v1/chat/sessions/10/${url.search}` }), res);
    },
  });

  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  const port = server.address().port;
  const baseUrl = `http://127.0.0.1:${port}/assistente/`;

  const browser = await puppeteer.launch({
    executablePath,
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'],
  });

  try {
    const page = await browser.newPage();
    await page.goto(baseUrl, { waitUntil: 'domcontentloaded' });

    // Load session 10
    await page.evaluate(() => window.jurixChat.loadSession(10));

    await page.waitForSelector('.messages-load-more-indicator');
    await page.evaluate(() => document.fonts.ready);
    let count = await page.$$eval('#messages-wrapper .message', (els) => els.length);
    assert.equal(count, 20, 'Primeira página deve conter 20 mensagens');

    // Scroll container to top where pager button resides
    await page.evaluate(() => {
      const c = document.getElementById('messages-container');
      c.scrollTop = 0;
    });

    // Measure scroll position before loading page 2
    const beforeScroll1 = await page.evaluate(() => {
      const c = document.getElementById('messages-container');
      const anchor = document.querySelector('#messages-wrapper .message');
      return {
        top: c.scrollTop,
        height: c.scrollHeight,
        clientHeight: c.clientHeight,
        anchorTop: anchor?.getBoundingClientRect().top,
      };
    });

    // Click load more for page 2
    await page.click('.messages-load-more-indicator');
    await page.waitForFunction(() => document.querySelectorAll('#messages-wrapper .message').length === 40);
    // The chat renderer commits markdown in animation frames after the DOM
    // count changes. Measure only after that layout transaction settles.
    await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    await new Promise((resolve) => setTimeout(resolve, 100));
    await page.evaluate(() => new Promise((resolve) => {
      const container = document.getElementById('messages-container');
      let previousTop = null;
      let stableFrames = 0;
      const sample = () => {
        const currentTop = container.scrollTop;
        stableFrames = previousTop !== null && Math.abs(currentTop - previousTop) < 0.5
          ? stableFrames + 1
          : 0;
        previousTop = currentTop;
        if (stableFrames >= 3) resolve();
        else requestAnimationFrame(sample);
      };
      requestAnimationFrame(sample);
    }));

    // Measure scroll position after loading page 2
    const afterScroll1 = await page.evaluate(() => {
      const c = document.getElementById('messages-container');
      const anchor = [...document.querySelectorAll('#messages-wrapper .message')]
        .find((el) => el.textContent.includes('Mensagem Real 41'));
      return {
        top: c.scrollTop,
        height: c.scrollHeight,
        clientHeight: c.clientHeight,
        anchorTop: anchor?.getBoundingClientRect().top,
      };
    });

    assert.ok(
      Math.abs(afterScroll1.anchorTop - beforeScroll1.anchorTop) <= 8,
      `A primeira mensagem existente deve continuar na mesma posição visual; before=${JSON.stringify(beforeScroll1)}, after=${JSON.stringify(afterScroll1)}`
    );

    assert.ok(requestedBeforeCursors.includes('page1-cursor'), 'Requisição deve incluir cursor da página 1');

    // Click load more for page 3
    await page.click('.messages-load-more-indicator');
    await page.waitForFunction(() => document.querySelectorAll('#messages-wrapper .message').length === 60);

    assert.ok(requestedBeforeCursors.includes('page2-cursor'), 'Requisição deve incluir cursor da página 2');

    // Button should be removed after last page
    const pagerExists = await page.$('.messages-load-more-indicator');
    assert.equal(pagerExists, null, 'O botão deve ser removido após a última página');

    // Verify chronological order from 1 to 60
    const messageTexts = await page.$$eval('#messages-wrapper .message', (els) =>
      els.map((el) => {
        const m = el.textContent.match(/Mensagem Real \d+/);
        return m ? m[0] : '';
      })
    );
    const expected = Array.from({ length: 60 }, (_, i) => `Mensagem Real ${i + 1}`);
    assert.deepEqual(messageTexts, expected, 'A ordem de 1 a 60 deve estar rigorosamente correta');
    const firstHistoricalTime = await page.$eval('#messages-wrapper .message .message-time', (node) => node.textContent);
    const expectedHistoricalTime = await page.evaluate(() => new Date(1700000000000 + 1000).toLocaleTimeString('pt-BR', {
      hour: '2-digit',
      minute: '2-digit',
    }));
    assert.equal(firstHistoricalTime, expectedHistoricalTime, 'Authenticated history must render message.created_at');

    // Test that when a user manually scrolls up, scrollToBottomIfAtBottom does NOT yank scroll to bottom
    await page.evaluate(() => {
      const c = document.getElementById('messages-container');
      c.scrollTop = 100;
      window.scrollToBottomIfAtBottom();
    });
    const scrolledTop = await page.evaluate(() => document.getElementById('messages-container').scrollTop);
    assert.equal(scrolledTop, 100, 'scrollToBottomIfAtBottom deve preservar a posição quando o usuário subiu');
  } finally {
    await browser.close();
    server.close();
  }
});

test('real browser: back/forward navigation keeps URL and active session in sync', async () => {
  const server = createTestServer({
    isAuthenticated: () => true,
    '/api/v1/chat/sessions/': (req, res) => {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({
        success: true,
        sessions: [
          { id: 1, slug: 'conversa-um', title: 'Conversa Um' },
          { id: 2, slug: 'conversa-dois', title: 'Conversa Dois' },
        ],
      }));
    },
    '/api/v1/chat/sessions/1/': (req, res) => {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({
        success: true,
        session: { id: 1, slug: 'conversa-um', title: 'Conversa Um' },
        messages: [{ id: 101, role: 'user', content: 'Pergunta da Conversa Um' }],
        has_more: false,
        next_cursor: null,
      }));
    },
    '/api/v1/chat/sessions/2/': (req, res) => {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({
        success: true,
        session: { id: 2, slug: 'conversa-dois', title: 'Conversa Dois' },
        messages: [{ id: 201, role: 'user', content: 'Pergunta da Conversa Dois' }],
        has_more: false,
        next_cursor: null,
      }));
    },
    '/api/v1/chat/sessions/slug/conversa-um/': (req, res) => {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({
        success: true,
        session: { id: 1, slug: 'conversa-um', title: 'Conversa Um' },
        messages: [{ id: 101, role: 'user', content: 'Pergunta da Conversa Um' }],
        has_more: false,
        next_cursor: null,
      }));
    },
    '/api/v1/chat/sessions/slug/conversa-dois/': (req, res) => {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({
        success: true,
        session: { id: 2, slug: 'conversa-dois', title: 'Conversa Dois' },
        messages: [{ id: 201, role: 'user', content: 'Pergunta da Conversa Dois' }],
        has_more: false,
        next_cursor: null,
      }));
    },
  });

  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  const port = server.address().port;
  const baseUrl = `http://127.0.0.1:${port}/assistente/`;

  const browser = await puppeteer.launch({
    executablePath,
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'],
  });

  try {
    const page = await browser.newPage();
    await page.goto(baseUrl, { waitUntil: 'domcontentloaded' });

    // Load session 1
    await page.evaluate(() => window.jurixChat.loadSession(1));
    await page.waitForFunction(() => document.body.textContent.includes('Pergunta da Conversa Um'));
    assert.ok(page.url().includes('conversa-um'));
    let activeId = await page.evaluate(() => window.jurixChat.getCurrentSessionId());
    assert.equal(activeId, 1);

    // Load session 2
    await page.evaluate(() => window.jurixChat.loadSession(2));
    await page.waitForFunction(() => document.body.textContent.includes('Pergunta da Conversa Dois'));
    assert.ok(page.url().includes('conversa-dois'));
    activeId = await page.evaluate(() => window.jurixChat.getCurrentSessionId());
    assert.equal(activeId, 2);

    // Go Back -> returns to session 1
    await page.goBack();
    assert.ok(page.url().includes('conversa-um'), 'URL deve retornar para conversa-um');
    await page.waitForFunction(() => {
      const text = document.getElementById('messages-wrapper')?.textContent || '';
      return text.includes('Pergunta da Conversa Um') && !text.includes('Pergunta da Conversa Dois');
    });
    activeId = await page.evaluate(() => window.jurixChat.getCurrentSessionId());
    assert.equal(activeId, 1, 'O ID da sessão ativa após voltar deve ser 1');
    const activeSidebarId1 = await page.$eval('.chat-session-item.active', (el) => el.dataset.sessionId);
    assert.equal(activeSidebarId1, '1', 'O item ativo na barra lateral deve ser o da conversa 1');

    // Go Forward -> returns to session 2
    await page.goForward();
    assert.ok(page.url().includes('conversa-dois'), 'URL deve avançar para conversa-dois');
    await page.waitForFunction(() => {
      const text = document.getElementById('messages-wrapper')?.textContent || '';
      return text.includes('Pergunta da Conversa Dois') && !text.includes('Pergunta da Conversa Um');
    });
    activeId = await page.evaluate(() => window.jurixChat.getCurrentSessionId());
    assert.equal(activeId, 2, 'O ID da sessão ativa após avançar deve ser 2');
    const activeSidebarId2 = await page.$eval('.chat-session-item.active', (el) => el.dataset.sessionId);
    assert.equal(activeSidebarId2, '2', 'O item ativo na barra lateral deve ser o da conversa 2');

    // Go Back twice -> returns to initial root /assistente/
    await page.goBack();
    await page.goBack();
    await page.waitForFunction(() => {
      const welcome = document.getElementById('welcome-state');
      return welcome && getComputedStyle(welcome).display !== 'none';
    });
    activeId = await page.evaluate(() => window.jurixChat.getCurrentSessionId());
    assert.equal(activeId, null, 'O ID da sessão deve ser null na raiz');
  } finally {
    await browser.close();
    server.close();
  }
});

test('real browser: navigating back during active streaming aborts generation and synchronizes destination', async () => {
  let streamAborted = false;
  let sseResponse = null;

  const server = createTestServer({
    isAuthenticated: () => true,
    '/api/v1/chat/sessions/': (req, res) => {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({
        success: true,
        sessions: [
          { id: 1, slug: 'conversa-um', title: 'Conversa Um' },
          { id: 2, slug: 'conversa-dois', title: 'Conversa Dois' },
        ],
      }));
    },
    '/api/v1/chat/sessions/1/': (req, res) => {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({
        success: true,
        session: { id: 1, slug: 'conversa-um', title: 'Conversa Um' },
        messages: [{ id: 101, role: 'user', content: 'Pergunta da Conversa Um' }],
        has_more: false,
        next_cursor: null,
      }));
    },
    '/api/v1/chat/sessions/2/': (req, res) => {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({
        success: true,
        session: { id: 2, slug: 'conversa-dois', title: 'Conversa Dois' },
        messages: [{ id: 201, role: 'user', content: 'Pergunta da Conversa Dois' }],
        has_more: false,
        next_cursor: null,
      }));
    },
    '/api/v1/chat/sessions/slug/conversa-um/': (req, res) => {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({
        success: true,
        session: { id: 1, slug: 'conversa-um', title: 'Conversa Um' },
        messages: [{ id: 101, role: 'user', content: 'Pergunta da Conversa Um' }],
        has_more: false,
        next_cursor: null,
      }));
    },
    '/api/v1/chat/sessions/slug/conversa-dois/': (req, res) => {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({
        success: true,
        session: { id: 2, slug: 'conversa-dois', title: 'Conversa Dois' },
        messages: [{ id: 201, role: 'user', content: 'Pergunta da Conversa Dois' }],
        has_more: false,
        next_cursor: null,
      }));
    },
    '/api/v1/search/answer/stream/': (req, res) => {
      sseResponse = res;
      res.writeHead(200, {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
      });
      req.on('close', () => {
        streamAborted = true;
      });
      // Send initial chunk
      res.write(`data: ${JSON.stringify({ type: 'chunk', chunk: 'Gerando resposta em andamento...' })}\n\n`);
      // Keep connection open without ending to simulate long running generation
    },
  });

  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  const port = server.address().port;
  const baseUrl = `http://127.0.0.1:${port}/assistente/`;

  const browser = await puppeteer.launch({
    executablePath,
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'],
  });

  try {
    const page = await browser.newPage();
    await page.goto(baseUrl, { waitUntil: 'domcontentloaded' });

    // 1. Load session 1
    await page.evaluate(() => window.jurixChat.loadSession(1));
    await page.waitForFunction(() => document.body.textContent.includes('Pergunta da Conversa Um'));

    // 2. Load session 2
    await page.evaluate(() => window.jurixChat.loadSession(2));
    await page.waitForFunction(() => document.body.textContent.includes('Pergunta da Conversa Dois'));
    assert.ok(page.url().includes('conversa-dois'));

    // 3. In session 2, start asking a new question that triggers long streaming
    await page.evaluate(() => window.jurixChat.askQuestion('Pergunta que vai demorar'));

    // Wait until streaming starts in session 2
    await page.waitForFunction(() => document.body.textContent.includes('Gerando resposta em andamento...'), { timeout: 5000 });
    const isBusyBefore = await page.evaluate(() => window.JurixChatState?.isBusy?.());
    assert.equal(isBusyBefore, true, 'O chat deve estar ocupado durante o streaming');

    // 4. WHILE STREAMING IS ACTIVE, user hits browser Back button
    await page.goBack();

    // 5. The popstate MUST abort the stream, reconcile to conversa-um, and synchronize state
    assert.ok(page.url().includes('conversa-um'), 'URL deve retornar para conversa-um mesmo durante streaming');

    await page.waitForFunction(() => {
      const text = document.getElementById('messages-wrapper')?.textContent || '';
      return text.includes('Pergunta da Conversa Um') && !text.includes('Pergunta que vai demorar');
    }, { timeout: 5000 });

    const activeId = await page.evaluate(() => window.jurixChat.getCurrentSessionId());
    assert.equal(activeId, 1, 'O ID da sessão ativa após voltar durante streaming deve ser 1');

    const isBusyAfter = await page.evaluate(() => window.JurixChatState?.isBusy?.());
    assert.equal(isBusyAfter, false, 'O chat deve retornar ao estado idle');

    const activeSidebarId = await page.$eval('.chat-session-item.active', (el) => el.dataset.sessionId);
    assert.equal(activeSidebarId, '1', 'O item ativo na barra lateral deve ser o da conversa 1');

    // Verify socket was closed / stream was cancelled
    assert.ok(streamAborted, 'A requisição de stream deve ter sido abortada pelo cliente');
  } finally {
    if (sseResponse && !sseResponse.writableEnded) {
      try { sseResponse.end(); } catch (_) {}
    }
    await browser.close();
    server.close();
  }
});

test('real browser: out-of-order navigation responses do not overwrite active conversation or desynchronize state', async () => {
  let releaseSession1;
  const session1Promise = new Promise((resolve) => {
    releaseSession1 = resolve;
  });

  const server = createTestServer({
    isAuthenticated: () => true,
    '/api/v1/chat/sessions/': (req, res) => {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({
        success: true,
        sessions: [
          { id: 1, slug: 'conversa-um', title: 'Conversa Um' },
          { id: 2, slug: 'conversa-dois', title: 'Conversa Dois' },
        ],
      }));
    },
    '/api/v1/chat/sessions/1/': async (req, res) => {
      await session1Promise;
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({
        success: true,
        session: { id: 1, slug: 'conversa-um', title: 'Conversa Um' },
        messages: [{ id: 101, role: 'user', content: 'Pergunta da Conversa Um' }],
        has_more: false,
        next_cursor: null,
      }));
    },
    '/api/v1/chat/sessions/slug/conversa-um/': async (req, res) => {
      await session1Promise;
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({
        success: true,
        session: { id: 1, slug: 'conversa-um', title: 'Conversa Um' },
        messages: [{ id: 101, role: 'user', content: 'Pergunta da Conversa Um' }],
        has_more: false,
        next_cursor: null,
      }));
    },
    '/api/v1/chat/sessions/2/': (req, res) => {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({
        success: true,
        session: { id: 2, slug: 'conversa-dois', title: 'Conversa Dois' },
        messages: [{ id: 201, role: 'user', content: 'Pergunta da Conversa Dois' }],
        has_more: false,
        next_cursor: null,
      }));
    },
    '/api/v1/chat/sessions/slug/conversa-dois/': (req, res) => {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({
        success: true,
        session: { id: 2, slug: 'conversa-dois', title: 'Conversa Dois' },
        messages: [{ id: 201, role: 'user', content: 'Pergunta da Conversa Dois' }],
        has_more: false,
        next_cursor: null,
      }));
    },
    '/api/test/release-session-1/': (req, res) => {
      if (releaseSession1) releaseSession1();
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ released: true }));
    },
  });

  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  const port = server.address().port;
  const baseUrl = `http://127.0.0.1:${port}/assistente/`;

  const browser = await puppeteer.launch({
    executablePath,
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'],
  });

  try {
    const page = await browser.newPage();
    await page.goto(baseUrl, { waitUntil: 'domcontentloaded' });

    // 1. Trigger navigation to session 1 (delayed by server promise)
    page.evaluate(() => window.jurixChat.loadSession(1));

    // 2. Immediately trigger navigation to session 2 (resolves fast)
    await page.evaluate(() => window.jurixChat.loadSession(2));

    // Wait for session 2 to be rendered
    await page.waitForFunction(() => {
      const text = document.getElementById('messages-wrapper')?.textContent || '';
      return text.includes('Pergunta da Conversa Dois');
    });

    assert.ok(page.url().includes('conversa-dois'), 'URL deve ser conversa-dois');
    let activeId = await page.evaluate(() => window.jurixChat.getCurrentSessionId());
    assert.equal(activeId, 2, 'Sessão ativa deve ser 2');

    // 3. Now release the delayed response for session 1
    await page.evaluate(async () => {
      await fetch('/api/test/release-session-1/');
    });

    // Wait to allow any rogue delayed DOM updates to arrive
    await new Promise((r) => setTimeout(r, 400));

    // 4. Verify that session 2 remains completely intact and unsullied
    assert.ok(page.url().includes('conversa-dois'), 'URL não deve ser retrocedida pela resposta tardia da sessão 1');
    activeId = await page.evaluate(() => window.jurixChat.getCurrentSessionId());
    assert.equal(activeId, 2, 'ID da sessão não deve ser sobrescrito para 1');

    const messagesText = await page.evaluate(() => document.getElementById('messages-wrapper')?.textContent || '');
    assert.ok(messagesText.includes('Pergunta da Conversa Dois'), 'Mensagens da sessão 2 devem permanecer');
    assert.ok(!messagesText.includes('Pergunta da Conversa Um'), 'Mensagens tardias da sessão 1 devem ser descartadas');

    const activeSidebarId = await page.$eval('.chat-session-item.active', (el) => el.dataset.sessionId);
    assert.equal(activeSidebarId, '2', 'Card da sessão 2 deve continuar ativo na sidebar');
  } finally {
    if (releaseSession1) releaseSession1();
    await browser.close();
    server.close();
  }
});

test('real browser: streaming with complex markdown (tables, lists, code) and deferred sources with fade-in', async () => {
  const markdownChunk =
    '### Parecer Jurídico\n\n' +
    'Conforme a legislação vigente:\n\n' +
    '| Artigo | Status | Vigência |\n' +
    '|---|---|---|\n' +
    '| Art. 1º | Vigente | 2026 |\n' +
    '| Art. 2º | Revogado | 2020 |\n\n' +
    '* Item A: Observância obrigatória\n' +
    '* Item B: Prazos recursais\n\n' +
    '```python\n' +
    'def verificar_prazo(dias):\n' +
    '    return dias <= 15\n' +
    '```\n';

  let releaseDone = null;
  let releaseProgress = null;
  let receivedPayload = null;
  let resolvePayload = null;
  const payloadPromise = new Promise((resolve) => { resolvePayload = resolve; });
  const progressPromise = new Promise((resolve) => { releaseProgress = resolve; });
  const donePromise = new Promise((resolve) => {
    releaseDone = resolve;
  });

  const server = createTestServer({
    isAuthenticated: () => false,
    '/api/test/release-progress/': (req, res) => {
      if (releaseProgress) releaseProgress();
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ ok: true }));
    },
    '/api/test/release-done/': (req, res) => {
      if (releaseDone) releaseDone();
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ ok: true }));
    },
    '/api/v1/search/answer/stream/': async (req, res) => {
      let requestBody = '';
      req.on('data', (chunk) => { requestBody += chunk; });
      req.on('end', () => {
        receivedPayload = JSON.parse(requestBody);
        resolvePayload(receivedPayload);
      });
      res.writeHead(200, {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
      });

      res.write(`data: ${JSON.stringify({ type: 'status', status: 'retrieving' })}\n\n`);
      await progressPromise;
      for (const status of ['reranking', 'grounding', 'generating']) {
        res.write(`data: ${JSON.stringify({ type: 'status', status })}\n\n`);
      }

      // 1. Sources event arrives first
      res.write(
        `data: ${JSON.stringify({
          type: 'sources',
          sources: [{ id: 99, tipo: 'Lei', norma: 'Lei nº 8.206/2026', text: 'Texto integral da Lei 8206 de Natal.', similarity_score: 0.7 }],
        })}\n\n`
      );

      // 2. Chunks arrive
      res.write(`data: ${JSON.stringify({ type: 'chunk', chunk: markdownChunk })}\n\n`);

      // 3. Explicit test barrier: wait until the test finishes pre-inspection before releasing done!
      await donePromise;

      res.write(
        `data: ${JSON.stringify({
          type: 'done',
          answer: markdownChunk,
          session_id: null,
        })}\n\n`
      );
      res.end();
    },
    '/api/v1/chat/sessions/': (req, res) => {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ success: true, sessions: [] }));
    },
  });

  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  const port = server.address().port;
  const baseUrl = `http://127.0.0.1:${port}/assistente/`;

  const browser = await puppeteer.launch({
    executablePath,
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'],
  });

  try {
    const page = await browser.newPage();
    await page.setViewport({ width: 390, height: 844 });
    await page.goto(baseUrl, { waitUntil: 'domcontentloaded' });
    await page.evaluate(() => localStorage.setItem('jurix-preferences', JSON.stringify({
      model: 'llama3', sources: 3, temperature: 0.7, theme: 'dark', density: 'comfortable',
    })));
    await page.evaluate(() => {
      window.__pipelineStatuses = [];
      const indicator = document.getElementById('chat-state-indicator');
      new MutationObserver(() => {
        if (indicator.dataset.pipelineStatus) window.__pipelineStatuses.push(indicator.dataset.pipelineStatus);
      }).observe(indicator, { attributes: true, childList: true, characterData: true, subtree: true });
    });

    // Set up mutation observer to capture initial opacity on card insertion
    await page.evaluate(() => {
      window.__capturedOpacities = [];
      const obs = new MutationObserver(() => {
        const section = document.querySelector('.sources-section');
        if (section) {
          const op = parseFloat(window.getComputedStyle(section).opacity);
          window.__capturedOpacities.push(op);
        }
      });
      obs.observe(document.body, { childList: true, subtree: true, attributes: true });
    });

    await page.waitForSelector('#hero-search-input');
    await page.type('#hero-search-input', 'Gerar tabela e código');
    await page.keyboard.press('Enter');

    const retrievingIndicator = await page.waitForFunction(() => {
      const indicator = document.getElementById('chat-state-indicator');
      return indicator?.dataset.pipelineStatus === 'retrieving' ? {
        text: indicator.textContent,
        hidden: indicator.hidden,
        live: indicator.getAttribute('aria-live'),
      } : false;
    }, { timeout: 6000 });
    assert.deepEqual(await retrievingIndicator.jsonValue(), {
      text: 'Buscando normas relevantes…', hidden: false, live: 'polite',
    }, 'retrieval must be presented as a visible accessible pipeline state');
    assert.equal(await page.$$('.sources-section, .source-card, .evidence-card, .jurix-rag-source').then((els) => els.length), 0);
    await page.evaluate(() => fetch('/api/test/release-progress/'));
    const generatingIndicator = await page.waitForFunction(() => {
      const indicator = document.getElementById('chat-state-indicator');
      return indicator?.dataset.pipelineStatus === 'generating' ? indicator.textContent : false;
    }, { timeout: 6000 });
    assert.equal(await generatingIndicator.jsonValue(), 'Gerando resposta…');

    // Wait for markdown table to start rendering in the stream
    await page.waitForSelector('.message-assistant table', { timeout: 6000 });
    await page.waitForSelector('.message-assistant pre code', { timeout: 6000 });
    await page.waitForSelector('.message-assistant ul li', { timeout: 6000 });

    // VERIFICAÇÃO RIGOROSA 1: O stream está explicitamente pausado antes do done. Fontes DEVEM ser 0!
    const sourcesBeforeDone = await page.$$eval(
      '.sources-section, .source-card, .evidence-card, .jurix-rag-source',
      (els) => els.length
    );
    assert.equal(sourcesBeforeDone, 0, 'As fontes NÃO podem estar renderizadas antes do evento done');
    await payloadPromise;
    assert.deepEqual(
      { temperature: receivedPayload?.temperature, max_sources: receivedPayload?.max_sources, model: receivedPayload?.model },
      { temperature: 0.7, max_sources: 3, model: 'llama3' },
      `saved assistant preferences must reach the streaming API payload; received ${JSON.stringify(receivedPayload)}`
    );

    // Libera a barreira para o servidor emitir o done
    await page.evaluate(() => fetch('/api/test/release-done/'));

    // VERIFICAÇÃO RIGOROSA 2: Aguardar renderização das fontes
    await page.waitForSelector('.sources-section', { timeout: 6000 });
    await page.waitForFunction(() => document.getElementById('chat-state-indicator')?.hidden === true, { timeout: 6000 });
    assert.equal(await page.$eval('#chat-state-indicator', (el) => el.dataset.pipelineStatus || null), null);
    const observedStatuses = await page.evaluate(() => [...new Set(window.__pipelineStatuses)]);
    assert.deepEqual(observedStatuses, ['retrieving', 'reranking', 'grounding', 'generating']);
    const sourceTexts = await page.$$eval('.sources-section', (els) => els.map((el) => el.textContent));
    assert.ok(
      sourceTexts.some((t) => t.includes('fontes consultadas') || t.includes('Ver fontes')),
      'O chat deve exibir a affordance compacta para abrir as fontes'
    );
    await page.waitForFunction(
      () => document.querySelector('.jurix-sources-pill-btn')?._sourcesData?.length > 0,
      { timeout: 6000 }
    );
    const mobileSourcesLayout = await page.evaluate(() => {
      const rect = (selector) => {
        const element = document.querySelector(selector);
        const bounds = element?.getBoundingClientRect();
        return bounds ? { x: bounds.x, right: bounds.right, width: bounds.width, height: bounds.height } : null;
      };
      return {
        viewportWidth: innerWidth,
        button: rect('.jurix-sources-pill-btn'),
        count: rect('.jurix-sources-pill-btn > span:not(.jurix-sources-pill-badge):not(.jurix-sources-pill-action)'),
        confidence: rect('.jurix-sources-pill-badge'),
        action: rect('.jurix-sources-pill-action'),
      };
    });
    assert.ok(mobileSourcesLayout.count?.height < 22, `Source count should stay on one line on mobile: ${JSON.stringify(mobileSourcesLayout)}`);
    assert.ok(mobileSourcesLayout.action?.height < 22, `Source action should stay on one line on mobile: ${JSON.stringify(mobileSourcesLayout)}`);
    assert.ok(mobileSourcesLayout.confidence?.height < 22, `Confidence label should stay on one line on mobile: ${JSON.stringify(mobileSourcesLayout)}`);
    await page.evaluate(() => {
      window.__drawerOpenCalls = 0;
      const openDrawer = window.JurixRagUI.openSourcesDrawer;
      window.JurixRagUI.openSourcesDrawer = (...args) => {
        window.__drawerOpenCalls += 1;
        return openDrawer(...args);
      };
    });
    await page.click('.jurix-sources-pill-btn');
    try {
      await page.waitForSelector('.jurix-sources-drawer-panel.is-open .source-card, .jurix-sources-drawer-panel.is-open .jurix-rag-source', { timeout: 6000 });
    } catch (error) {
      const diagnostic = await page.evaluate(() => {
        const pill = document.querySelector('.jurix-sources-pill-btn');
        const rect = pill?.getBoundingClientRect();
        const hit = rect && document.elementFromPoint(rect.x + rect.width / 2, rect.y + rect.height / 2);
        const panel = document.querySelector('.jurix-sources-drawer-panel');
        return {
          drawerOpenCalls: window.__drawerOpenCalls,
          pillSources: pill?._sourcesData?.length,
          pillRect: rect && { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
          centerHit: hit?.outerHTML?.slice(0, 180),
          panelClass: panel?.className,
          panelBody: document.querySelector('#jurix-sources-drawer-body')?.innerHTML?.slice(0, 300),
        };
      });
      throw new Error(`${error.message}; drawer diagnostic: ${JSON.stringify(diagnostic)}`);
    }
    const drawerSourceTexts = await page.$$eval(
      '.jurix-sources-drawer-panel.is-open .source-card, .jurix-sources-drawer-panel.is-open .jurix-rag-source',
      (els) => els.map((el) => el.textContent)
    );
    assert.ok(
      drawerSourceTexts.some((t) => t.includes('8206') || t.includes('Texto integral da Lei 8206 de Natal.')),
      'O drawer deve conter o número ou texto específico da Lei 8206'
    );
    const visibleDrawerSources = await page.$$eval(
      '.jurix-sources-drawer-panel.is-open .source-card, .jurix-sources-drawer-panel.is-open .jurix-rag-source',
      (els) => els.filter((el) => {
        const style = window.getComputedStyle(el);
        const rect = el.getBoundingClientRect();
        return style.visibility !== 'hidden' && Number(style.opacity) >= 0.9 && rect.height > 0;
      }).length
    );
    assert.ok(visibleDrawerSources > 0, 'Os cards do drawer devem estar visualmente visíveis');

    // VERIFICAÇÃO RIGOROSA 3: Comprovação do fade-in (opacidade inicial < 0.5 e opacidade final >= 0.9)
    await page.waitForFunction(() => {
      const section = document.querySelector('.sources-section.source-section-visible');
      if (!section) return false;
      return parseFloat(window.getComputedStyle(section).opacity) >= 0.9;
    }, { timeout: 4000 });

    const capturedOpacities = await page.evaluate(() => window.__capturedOpacities || []);
    assert.ok(capturedOpacities.length > 0, 'Deve ter capturado mutações de estilo dos cards de fonte');
    assert.ok(
      Math.min(...capturedOpacities) < 0.5,
      `O fade-in deve ter iniciado com opacidade baixa (< 0.5), valor inicial: ${Math.min(...capturedOpacities)}`
    );

    const tableHeaders = await page.$$eval('.message-assistant table th', (els) => els.map((el) => el.textContent.trim()));
    assert.deepEqual(tableHeaders, ['Artigo', 'Status', 'Vigência']);

    const codeText = await page.$eval('.message-assistant pre code', (el) => el.textContent);
    assert.ok(codeText.includes('def verificar_prazo(dias):'));

    await page.keyboard.press('Escape');
    await page.waitForFunction(() => !document.querySelector('.jurix-sources-drawer-panel.is-open'));
    const modeControl = '#chat-form .figma-search-dropdown[data-control="mode"]';
    await page.focus(modeControl);
    await page.keyboard.press('Enter');
    await page.waitForSelector('#chat-form [data-jurix-control-menu]');
    const composerMenuBounds = await page.$eval(modeControl, (control) => {
      const button = control.getBoundingClientRect();
      const menu = control.querySelector('[data-jurix-control-menu]').getBoundingClientRect();
      return { button: { top: button.top, bottom: button.bottom }, menu: { top: menu.top, bottom: menu.bottom, left: menu.left, right: menu.right }, viewport: { width: innerWidth, height: innerHeight } };
    });
    assert.ok(composerMenuBounds.menu.bottom <= composerMenuBounds.button.top, `O menu do composer deve abrir acima do controle perto do rodapé: ${JSON.stringify(composerMenuBounds)}`);
    assert.ok(composerMenuBounds.menu.top >= 0 && composerMenuBounds.menu.right <= composerMenuBounds.viewport.width, JSON.stringify(composerMenuBounds));
  } finally {
    await browser.close();
    server.close();
  }
});

test('real browser: stream interruption preserves partial text and user question without wiping chat', async () => {
  let streamAttempts = 0;
  const server = createTestServer({
    isAuthenticated: () => false,
    '/api/v1/search/answer/stream/': (req, res) => {
      streamAttempts += 1;
      res.writeHead(200, {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
      });

      if (streamAttempts > 1) {
        const recoveredAnswer = 'Resposta recuperada com sucesso.';
        res.write(`data: ${JSON.stringify({ type: 'chunk', chunk: recoveredAnswer })}\n\n`);
        res.write(`data: ${JSON.stringify({ type: 'done', answer: recoveredAnswer, session_id: null })}\n\n`);
        res.end();
        return;
      }

      res.write(`data: ${JSON.stringify({ type: 'chunk', chunk: 'Texto inicial gerado antes da queda.' })}\n\n`);

      // Abruptly destroy socket to simulate connection failure mid-stream
      setTimeout(() => {
        req.socket.destroy();
      }, 100);
    },
    '/api/v1/chat/sessions/': (req, res) => {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ success: true, sessions: [] }));
    },
  });

  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  const port = server.address().port;
  const baseUrl = `http://127.0.0.1:${port}/assistente/`;

  const browser = await puppeteer.launch({
    executablePath,
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'],
  });

  try {
    const page = await browser.newPage();
    const pageErrors = [];
    page.on('pageerror', (error) => pageErrors.push(error.message));
    await page.goto(baseUrl, { waitUntil: 'domcontentloaded' });

    await page.waitForSelector('#hero-search-input');
    await page.type('#hero-search-input', 'Pergunta que vai falhar');
    await page.keyboard.press('Enter');

    // Wait for the partial text to be rendered
    await page.waitForFunction(() => {
      const el = document.querySelector('.message-assistant');
      return el && el.textContent.includes('Texto inicial gerado antes da queda.');
    }, { timeout: 5000 });

    // Wait for interruption notice to appear
    await page.waitForFunction(() => {
      const text = document.body.textContent;
      return text.includes('interrompida') || text.includes('Falha') || text.includes('Tentar novamente');
    }, { timeout: 5000 });

    // The user's original message must still be in the DOM
    const userMsg = await page.$eval('.message-user', (el) => el.textContent);
    assert.ok(userMsg.includes('Pergunta que vai falhar'), 'A pergunta do usuário não deve ser apagada');

    // The partial assistant text must still be in the DOM
    const asstMsg = await page.$eval('.message-assistant', (el) => el.textContent);
    assert.ok(asstMsg.includes('Texto inicial gerado antes da queda.'), 'O texto parcial deve ser preservado');

    const retryButton = await page.waitForSelector('.jurix-rag-retry', { timeout: 5000 });
    assert.ok(retryButton, 'O erro deve oferecer uma ação de retry funcional');
    const retryHitTarget = await page.$eval('.jurix-rag-retry', (button) => {
      const rect = button.getBoundingClientRect();
      const hit = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2);
      return {
        visible: rect.width > 0 && rect.height > 0 && rect.top >= 0 && rect.bottom <= innerHeight,
        receivesPointer: hit === button || button.contains(hit),
        rect: { top: rect.top, bottom: rect.bottom },
        viewportHeight: innerHeight,
      };
    });
    assert.ok(retryHitTarget.visible && retryHitTarget.receivesPointer, `A ação de retry deve estar visível e não obstruída: ${JSON.stringify(retryHitTarget)}`);
    await retryButton.click();
    try {
      await page.waitForFunction(() => document.body.textContent.includes('Resposta recuperada com sucesso.'), { timeout: 6000 });
    } catch (error) {
      const diagnostic = await page.evaluate(() => ({
        url: location.href,
        textarea: document.querySelector('#question-textarea')?.value,
        sendDisabled: document.querySelector('#send-button')?.disabled,
        state: window.JurixChatState?.snapshot?.(),
        messages: [...document.querySelectorAll('.message')].map((el) => ({ className: el.className, text: el.textContent.slice(0, 180) })),
        history: JSON.parse(localStorage.getItem('jurix:anonymous-history:v2') || '{"sessions":[]}'),
      }));
      throw new Error(`${error.message}; attempts=${streamAttempts}; pageErrors=${JSON.stringify(pageErrors)}; state=${JSON.stringify(diagnostic)}`);
    }
    const retryResult = await page.evaluate(() => ({
      userMessages: document.querySelectorAll('.message-user').length,
      assistantMessages: document.querySelectorAll('.message-assistant').length,
      response: [...document.querySelectorAll('.message-assistant')].map((el) => el.textContent).join(' '),
      persistedMessages: JSON.parse(localStorage.getItem('jurix:anonymous-history:v2') || '{"sessions":[]}').sessions[0]?.messages || [],
    }));
    assert.equal(streamAttempts, 2, 'A ação de retry deve disparar uma nova requisição de streaming');
    assert.equal(retryResult.userMessages, 1, 'Retry não deve duplicar a pergunta do usuário');
    assert.equal(retryResult.assistantMessages, 1, 'A tentativa parcial deve ser substituída, não acumulada');
    assert.ok(retryResult.response.includes('Resposta recuperada com sucesso.'));
    assert.equal(JSON.stringify(retryResult.persistedMessages.map((message) => message.role)), JSON.stringify(['user', 'assistant']));
    assert.equal(retryResult.persistedMessages[0].content, 'Pergunta que vai falhar');
    assert.equal(retryResult.persistedMessages[1].content, 'Resposta recuperada com sucesso.');
  } finally {
    await browser.close();
    server.close();
  }
});

test('real browser: workspace routes scroll naturally and desktop sidebar collapses to a persistent icon rail', async () => {
  const server = createTestServer();
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const port = server.address().port;
  const browser = await puppeteer.launch({
    executablePath,
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'],
  });

  try {
    const page = await browser.newPage();
    await page.setViewport({ width: 1280, height: 720 });
    await page.goto(`http://127.0.0.1:${port}/workspace-shell-test/`, { waitUntil: 'domcontentloaded' });
    const scrollState = await page.evaluate(() => ({
      overflowY: getComputedStyle(document.body).overflowY,
      scrollHeight: document.documentElement.scrollHeight,
      viewportHeight: innerHeight,
    }));
    assert.equal(scrollState.overflowY, 'auto');
    assert.ok(scrollState.scrollHeight > scrollState.viewportHeight, JSON.stringify(scrollState));
    await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
    assert.ok(await page.evaluate(() => window.scrollY > 0), 'workspace documents must reach content below the fold');

    await page.evaluate(() => window.scrollTo(0, 0));
    await page.click('#toggle-sidebar');
    await page.waitForFunction(() => document.querySelector('.workspace-shell')?.classList.contains('is-sidebar-collapsed'));
    await page.waitForFunction(() => Math.abs(document.querySelector('.workspace-sidebar')?.getBoundingClientRect().width - 72) < 1);
    const collapsed = await page.evaluate(() => {
      const sidebar = document.querySelector('.workspace-sidebar');
      const icon = sidebar.querySelector('.workspace-nav-item > .workspace-nav-icon');
      const label = sidebar.querySelector('.workspace-nav-item > span:not([aria-hidden="true"])');
      return {
        sidebarWidth: sidebar.getBoundingClientRect().width,
        iconDisplay: getComputedStyle(icon).display,
        labelDisplay: getComputedStyle(label).display,
        accessibleLabel: sidebar.querySelector('a[aria-label="Normas"]').getAttribute('aria-label'),
        toggleLabel: document.querySelector('#toggle-sidebar').getAttribute('aria-label'),
        documentWidth: document.documentElement.scrollWidth,
      };
    });
    assert.ok(Math.abs(collapsed.sidebarWidth - 72) < 1, `icon rail should be 72px wide (got ${collapsed.sidebarWidth})`);
    assert.notEqual(collapsed.iconDisplay, 'none');
    assert.equal(collapsed.labelDisplay, 'none');
    assert.equal(collapsed.accessibleLabel, 'Normas');
    assert.equal(collapsed.toggleLabel, 'Expandir navegação');
    assert.equal(collapsed.documentWidth, 1280);

    await page.reload({ waitUntil: 'domcontentloaded' });
    assert.ok(await page.$eval('.workspace-shell', (shell) => shell.classList.contains('is-sidebar-collapsed')),
      'icon-rail preference should survive navigation/reload');
    await page.click('#toggle-sidebar');
    await page.waitForFunction(() => !document.querySelector('.workspace-shell')?.classList.contains('is-sidebar-collapsed'));
    await page.waitForFunction(() => Math.abs(document.querySelector('.workspace-sidebar')?.getBoundingClientRect().width - 240) < 1);
    assert.ok(Math.abs(await page.$eval('.workspace-sidebar', (sidebar) => sidebar.getBoundingClientRect().width) - 240) < 1);
  } finally {
    await browser.close();
    server.close();
  }
});

test('real browser: sidebar items stay inside the shell and fully offscreen when collapsed on mobile', async () => {
  const server = createTestServer();
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  const port = server.address().port;
  const browser = await puppeteer.launch({
    executablePath,
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'],
  });

  try {
    const page = await browser.newPage();
    await page.setViewport({ width: 390, height: 844 });
    await page.goto(`http://127.0.0.1:${port}/assistente/`, { waitUntil: 'domcontentloaded' });
    await new Promise((resolve) => setTimeout(resolve, 300));

    await page.evaluate(() => {
      const message = document.createElement('div');
      message.className = 'message';
      message.innerHTML = '<div style="height: 900px"></div><div class="sources-section"><button type="button" class="jurix-sources-pill-btn">2 fontes consultadas · Ver fontes</button></div>';
      document.getElementById('welcome-state').remove();
      const wrapper = document.getElementById('messages-wrapper');
      wrapper.style.minHeight = '1000px';
      wrapper.append(message);
      const bar = document.getElementById('conversation-input-bar');
      bar.classList.remove('is-hidden');
      bar.style.display = 'flex';
      const scroll = document.getElementById('messages-container');
      scroll.scrollTop = scroll.scrollHeight;
    });
    const mobileComposer = await page.evaluate(() => {
      const bar = document.getElementById('conversation-input-bar').getBoundingClientRect();
      const form = document.getElementById('chat-form').getBoundingClientRect();
      const sources = document.querySelector('.jurix-sources-pill-btn').getBoundingClientRect();
      return { barLeft: bar.left, barRight: bar.right, barTop: bar.top, barWidth: bar.width, formLeft: form.left, formRight: form.right, formWidth: form.width, sourcesBottom: sources.bottom };
    });
    assert.equal(mobileComposer.barLeft, 0, `Composer mobile deve alinhar ao viewport: ${JSON.stringify(mobileComposer)}`);
    assert.equal(mobileComposer.barWidth, 390, `Composer mobile deve ocupar a largura útil: ${JSON.stringify(mobileComposer)}`);
    assert.ok(mobileComposer.formWidth >= 320 && mobileComposer.formRight <= 390, `Formulário mobile não pode ficar estreito ou sair do viewport: ${JSON.stringify(mobileComposer)}`);
    assert.ok(mobileComposer.sourcesBottom < mobileComposer.barTop, `O botão de fontes deve permanecer acessível acima do composer: ${JSON.stringify(mobileComposer)}`);

    for (const width of [320, 390, 640]) {
      await page.setViewport({ width, height: 844 });
      const mobileControls = await page.evaluate(() => {
        const filters = document.querySelector('.jurix-composer-filters');
        const controls = [...filters.children];
        const labels = [...filters.querySelectorAll('[data-control-label]')];
        return {
          columns: getComputedStyle(filters).gridTemplateColumns.split(' ').length,
          controls: controls.map((control) => {
            const rect = control.getBoundingClientRect();
            return { top: rect.top, bottom: rect.bottom, left: rect.left, right: rect.right, height: rect.height };
          }),
          labels: labels.map((label) => ({
            visibleWidth: label.getBoundingClientRect().width,
            overflow: getComputedStyle(label).textOverflow,
            whiteSpace: getComputedStyle(label).whiteSpace,
          })),
          documentWidth: document.documentElement.scrollWidth,
          viewportWidth: document.documentElement.clientWidth,
        };
      });
      assert.equal(mobileControls.columns, 2, `Controles do composer devem usar grid legível a ${width}px: ${JSON.stringify(mobileControls)}`);
      assert.equal(mobileControls.controls.length, 3);
      assert.equal(mobileControls.controls[2].top, mobileControls.controls[0].top + mobileControls.controls[0].height + 8);
      assert.ok(mobileControls.controls.every((control) => control.height >= 44));
      assert.ok(mobileControls.labels.every((label) => label.overflow === 'ellipsis' && label.whiteSpace === 'nowrap'));
      assert.equal(mobileControls.documentWidth, mobileControls.viewportWidth);
    }
    await page.setViewport({ width: 390, height: 844 });

    const measurements = await page.evaluate(() => {
      const sidebar = document.getElementById('sidebar');
      const sidebarBounds = sidebar.getBoundingClientRect();
      const navItems = [...sidebar.querySelectorAll('.figma-sidebar-item')];
      return {
        sidebarLeft: sidebarBounds.left,
        navItems: navItems.map((item) => {
          const bounds = item.getBoundingClientRect();
          return { left: bounds.left, right: bounds.right };
        }),
      };
    });

    assert.equal(measurements.sidebarLeft, -240, 'A sidebar deve iniciar totalmente fora da tela');
    assert.ok(
      measurements.navItems.every((item) => item.right <= 0),
      `Itens da sidebar fechada não devem vazar no viewport: ${JSON.stringify(measurements.navItems)}`
    );
    assert.equal(await page.$eval('#sidebar', (sidebar) => sidebar.inert), true, 'Links fora do viewport devem estar inertes no mobile');
    assert.equal(await page.$eval('#sidebar', (sidebar) => sidebar.getAttribute('aria-hidden')), 'true');
    await page.focus('#toggle-sidebar');
    await page.keyboard.press('Tab');
    assert.equal(await page.evaluate(() => document.activeElement.closest('#sidebar')), null, 'Tab não deve focar link invisível da sidebar');

    const toggle = page.locator('#toggle-sidebar');
    await toggle.click();
    await page.waitForFunction(() => {
      const sidebar = document.getElementById('sidebar');
      return sidebar?.classList.contains('is-open') && sidebar.getBoundingClientRect().right >= 239;
    });
    await page.waitForFunction(() => document.activeElement?.closest('#sidebar')?.getBoundingClientRect().left >= 0);
    const openState = await page.evaluate(() => ({
      sidebarRight: document.getElementById('sidebar').getBoundingClientRect().right,
      sidebarClasses: document.getElementById('sidebar').className,
      sidebarTransform: getComputedStyle(document.getElementById('sidebar')).transform,
      expanded: document.getElementById('toggle-sidebar').getAttribute('aria-expanded'),
      bodyBackdrop: getComputedStyle(document.getElementById('jurix-sidebar-backdrop')).display,
    }));
    assert.ok(openState.sidebarRight >= 239, JSON.stringify(openState));
    assert.equal(openState.expanded, 'true');
    assert.equal(openState.bodyBackdrop, 'block');
    assert.equal(await page.$eval('#sidebar', (sidebar) => sidebar.inert), false);
    assert.ok(await page.evaluate(() => document.activeElement.closest('#sidebar')), 'Abrir a sidebar deve levar o foco a um item visível');
    await page.keyboard.press('Escape');
    await page.waitForFunction(() => {
      const sidebar = document.getElementById('sidebar');
      return !sidebar?.classList.contains('is-open') && sidebar.getBoundingClientRect().right <= 0;
    });
    assert.equal(await page.$eval('#toggle-sidebar', (button) => button.getAttribute('aria-expanded')), 'false');
    assert.equal(await page.evaluate(() => document.activeElement.id), 'toggle-sidebar');
    assert.equal(await page.$eval('#sidebar', (sidebar) => sidebar.inert), true);

    await toggle.click();
    await page.waitForFunction(() => {
      const sidebar = document.getElementById('sidebar');
      return sidebar?.classList.contains('is-open') && sidebar.getBoundingClientRect().right >= 239;
    });
    await page.mouse.click(350, 200);
    const closedByBackdrop = await page.evaluate(() => ({
      open: document.getElementById('sidebar').classList.contains('is-open'),
      buttonExpanded: document.getElementById('toggle-sidebar').getAttribute('aria-expanded'),
    }));
    assert.equal(closedByBackdrop.open, false, JSON.stringify(closedByBackdrop));
    assert.equal(closedByBackdrop.buttonExpanded, 'false');

    await page.setViewport({ width: 1280, height: 800 });
    await page.waitForFunction(() => document.querySelector('#sidebar')?.inert === false);
    const desktopBounds = await page.evaluate(() => {
      const sidebar = document.getElementById('sidebar').getBoundingClientRect();
      const items = [...document.querySelectorAll('#sidebar .figma-sidebar-item')];
      const workspaceNavProbe = document.createElement('a');
      workspaceNavProbe.className = 'workspace-nav-item';
      document.body.append(workspaceNavProbe);
      const workspaceNavBoxSizing = getComputedStyle(workspaceNavProbe).boxSizing;
      workspaceNavProbe.remove();
      return {
        sidebarRight: sidebar.right,
        itemRights: items.map((item) => item.getBoundingClientRect().right),
        workspaceNavBoxSizing,
      };
    });
    assert.ok(
      desktopBounds.itemRights.every((right) => right <= desktopBounds.sidebarRight),
      'Os itens da sidebar não devem sobrepor a área principal no desktop'
    );
    assert.equal(
      desktopBounds.workspaceNavBoxSizing,
      'border-box',
      'A navegação do shell workspace também precisa incluir padding na largura declarada'
    );
    await page.click('#toggle-sidebar');
    await page.waitForFunction(() => {
      const sidebar = document.getElementById('sidebar');
      return sidebar.classList.contains('collapsed') && Math.round(sidebar.getBoundingClientRect().width) === 72;
    });
    const assistantRail = await page.evaluate(() => {
      const sidebar = document.getElementById('sidebar');
      const navLink = sidebar.querySelector('a[aria-label="Normas"]');
      return {
        width: sidebar.getBoundingClientRect().width,
        iconVisible: getComputedStyle(navLink.querySelector('svg')).display !== 'none',
        labelHidden: getComputedStyle(navLink.querySelector('span')).display === 'none',
        accessibleName: navLink.getAttribute('aria-label'),
        toggleLabel: document.getElementById('toggle-sidebar').getAttribute('aria-label'),
      };
    });
    assert.ok(Math.abs(assistantRail.width - 72) < 1, `icon rail should be 72px wide (got ${assistantRail.width})`);
    assert.equal(assistantRail.iconVisible, true);
    assert.equal(assistantRail.labelHidden, true);
    assert.equal(assistantRail.accessibleName, 'Normas');
    assert.equal(assistantRail.toggleLabel, 'Expandir navegação');
    await page.reload({ waitUntil: 'domcontentloaded' });
    assert.ok(await page.$eval('#sidebar', (sidebar) => sidebar.classList.contains('collapsed')),
      'A preferência do trilho de ícones deve persistir entre a navegação e o reload');
    await page.click('#toggle-sidebar');
    await page.waitForFunction(() => !document.getElementById('sidebar').classList.contains('collapsed'));
    const desktopComposer = await page.evaluate(() => {
      const bar = document.getElementById('conversation-input-bar').getBoundingClientRect();
      const form = document.getElementById('chat-form').getBoundingClientRect();
      return { barLeft: bar.left, barRight: bar.right, formWidth: form.width };
    });
    assert.ok(desktopComposer.barLeft >= 0 && desktopComposer.barRight <= 1280, JSON.stringify(desktopComposer));
    assert.ok(desktopComposer.formWidth <= 1200, JSON.stringify(desktopComposer));
  } finally {
    await browser.close();
    server.close();
  }
});

test('real browser: assistant utility navigation stays visible in a short desktop viewport', async () => {
  const server = createTestServer();
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  const port = server.address().port;
  const browser = await puppeteer.launch({
    executablePath,
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'],
  });

  try {
    const page = await browser.newPage();
    await page.setViewport({ width: 1280, height: 600 });
    await page.goto(`http://127.0.0.1:${port}/assistente/`, { waitUntil: 'domcontentloaded' });
    await page.evaluate(() => {
      const list = document.getElementById('chat-sessions-list');
      for (let index = 0; index < 12; index += 1) {
        const session = document.createElement('a');
        session.className = 'chat-session-item';
        session.textContent = `Conversa longa ${index + 1}`;
        list.append(session);
      }
      const quickSearch = document.createElement('button');
      quickSearch.className = 'figma-sidebar-item workspace-palette-trigger';
      quickSearch.dataset.openCommandPalette = '';
      quickSearch.textContent = 'Busca rápida';
      document.querySelector('.figma-sidebar-footer').append(quickSearch);
    });

    const layout = await page.evaluate(() => {
      const sidebar = document.querySelector('.figma-sidebar');
      const top = document.querySelector('.figma-sidebar-top');
      const footer = document.querySelector('.figma-sidebar-footer');
      const settings = footer.querySelector('a[href*="configuracoes"]');
      const quickSearch = footer.querySelector('[data-open-command-palette]');
      const rect = (element) => {
        const bounds = element.getBoundingClientRect();
        return { top: bounds.top, bottom: bounds.bottom };
      };
      return {
        viewportHeight: innerHeight,
        sidebar: rect(sidebar),
        sidebarScrollHeight: sidebar.scrollHeight,
        top: rect(top),
        topOverflowY: getComputedStyle(top).overflowY,
        topScrollHeight: top.scrollHeight,
        topClientHeight: top.clientHeight,
        settings: rect(settings),
        quickSearch: rect(quickSearch),
      };
    });

    assert.equal(layout.sidebar.top, 0, JSON.stringify(layout));
    assert.ok(layout.sidebar.bottom <= layout.viewportHeight, JSON.stringify(layout));
    assert.ok(layout.topScrollHeight > layout.topClientHeight, JSON.stringify(layout));
    assert.equal(layout.topOverflowY, 'auto', JSON.stringify(layout));
    assert.ok(layout.settings.top >= 0 && layout.settings.bottom <= layout.viewportHeight, JSON.stringify(layout));
    assert.ok(layout.quickSearch.top >= 0 && layout.quickSearch.bottom <= layout.viewportHeight, JSON.stringify(layout));
  } finally {
    await browser.close();
    server.close();
  }
});

test('real browser: workspace utility navigation stays visible in a short desktop viewport', async () => {
  const server = createTestServer();
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  const port = server.address().port;
  const browser = await puppeteer.launch({
    executablePath,
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'],
  });

  try {
    const page = await browser.newPage();
    await page.setViewport({ width: 1280, height: 600 });
    await page.goto(`http://127.0.0.1:${port}/workspace-shell-test/`, { waitUntil: 'domcontentloaded' });
    const layout = await page.evaluate(() => {
      const sidebar = document.querySelector('.workspace-sidebar');
      const nav = document.querySelector('.workspace-nav');
      const footer = document.querySelector('.workspace-sidebar-bottom');
      const rect = (element) => {
        const bounds = element.getBoundingClientRect();
        return { top: bounds.top, bottom: bounds.bottom };
      };
      return {
        viewportHeight: innerHeight,
        sidebar: rect(sidebar),
        nav: rect(nav),
        navScrollHeight: nav.scrollHeight,
        navClientHeight: nav.clientHeight,
        navOverflowY: getComputedStyle(nav).overflowY,
        footer: rect(footer),
        utilities: [...footer.querySelectorAll('a, button')].map(rect),
      };
    });

    assert.equal(layout.sidebar.top, 0, JSON.stringify(layout));
    assert.ok(layout.sidebar.bottom <= layout.viewportHeight, JSON.stringify(layout));
    assert.ok(layout.navScrollHeight > layout.navClientHeight, JSON.stringify(layout));
    assert.equal(layout.navOverflowY, 'auto', JSON.stringify(layout));
    assert.ok(layout.utilities.length >= 2, JSON.stringify(layout));
    assert.ok(layout.utilities.every((item) => item.top >= 0 && item.bottom <= layout.viewportHeight), JSON.stringify(layout));
  } finally {
    await browser.close();
    server.close();
  }
});

test('real browser: command palette keeps compact icons and focuses search on mobile', async () => {
  const server = createTestServer();
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  const port = server.address().port;
  const browser = await puppeteer.launch({
    executablePath,
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'],
  });

  try {
    const page = await browser.newPage();
    await page.setViewport({ width: 390, height: 844 });
    await page.goto(`http://127.0.0.1:${port}/assistente/`, { waitUntil: 'domcontentloaded' });
    const mobileSearchControls = await page.$$eval('#hero-search-form .figma-search-dropdown', (items) => items.map((item) => {
      const bounds = item.getBoundingClientRect();
      return { x: bounds.x, right: bounds.right, y: bounds.y, width: bounds.width, height: bounds.height };
    }));
    assert.equal(mobileSearchControls.length, 4);
    assert.ok(mobileSearchControls[0].y === mobileSearchControls[1].y, `Os dois primeiros filtros devem compartilhar a primeira linha: ${JSON.stringify(mobileSearchControls)}`);
    assert.ok(mobileSearchControls[2].y === mobileSearchControls[3].y, `Os dois últimos filtros devem compartilhar a segunda linha: ${JSON.stringify(mobileSearchControls)}`);
    assert.ok(mobileSearchControls.every(({ x, right, width }) => width >= 100 && x >= 0 && right <= 390), JSON.stringify(mobileSearchControls));
    const promptPlaceholder = await page.$eval('#hero-search-input', (input) => {
      const context = document.createElement('canvas').getContext('2d');
      context.font = getComputedStyle(input).font;
      const bounds = input.getBoundingClientRect();
      const style = getComputedStyle(input);
      const availableWidth = bounds.width - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
      return {
        text: input.placeholder,
        textWidth: context.measureText(input.placeholder).width,
        availableWidth,
        accessibleName: input.getAttribute('aria-label'),
      };
    });
    assert.ok(promptPlaceholder.textWidth <= promptPlaceholder.availableWidth, JSON.stringify(promptPlaceholder));
    assert.match(promptPlaceholder.accessibleName, /jurisprudência/);
    const scopeSelector = '#hero-search-form .figma-search-dropdown:nth-child(2)';
    await page.click(scopeSelector);
    await page.waitForSelector('#hero-search-form [data-jurix-control-menu] [role="menuitemradio"]');
    assert.equal(await page.$eval(scopeSelector, (element) => element.getAttribute('aria-expanded')), 'true');
    const filterMenuBounds = await page.$eval(scopeSelector, (control) => {
      const menu = control.querySelector('[data-jurix-control-menu]').getBoundingClientRect();
      return { left: menu.left, right: menu.right, width: menu.width, viewportWidth: innerWidth };
    });
    assert.ok(filterMenuBounds.left >= 0 && filterMenuBounds.right <= filterMenuBounds.viewportWidth, JSON.stringify(filterMenuBounds));
    await page.keyboard.press('Escape');
    await page.waitForFunction(() => !document.querySelector('#hero-search-form [data-jurix-control-menu]'));
    assert.equal(await page.$eval(scopeSelector, (element) => element.getAttribute('aria-expanded')), 'false');
    assert.equal(await page.evaluate(() => document.activeElement?.getAttribute('data-control')), 'source_scope');
    await page.click(scopeSelector);
    await page.waitForSelector('#hero-search-form [data-jurix-control-menu]');
    await page.click(scopeSelector);
    assert.equal(await page.$eval(scopeSelector, (element) => element.getAttribute('aria-expanded')), 'false', 'Clicar no filtro aberto deve recolher o menu');
    await page.click(scopeSelector);
    await page.click('#hero-search-form [role="menuitemradio"]:nth-child(2)');
    await page.waitForFunction(() => !document.querySelector('#hero-search-form [data-jurix-control-menu]'));
    const selectedScope = await page.evaluate(() => ({
      label: document.querySelector('#hero-search-form .figma-search-dropdown:nth-child(2) [data-control-label]')?.textContent,
      composerLabel: document.querySelector('#chat-form .figma-search-dropdown[data-control="source_scope"] [data-control-label]')?.textContent,
      focus: document.activeElement?.getAttribute('data-control'),
      expanded: document.querySelector('#hero-search-form .figma-search-dropdown:nth-child(2)')?.getAttribute('aria-expanded'),
      status: JSON.parse(localStorage.getItem('jurix:search-options:v1') || '{}').source_scope,
    }));
    assert.deepEqual(selectedScope, {
      label: 'Todas as fontes',
      composerLabel: 'Todas as fontes',
      focus: 'source_scope',
      expanded: 'false',
      status: 'all',
    });
    const focusBeforePalette = await page.evaluate(() => document.activeElement?.id || document.activeElement?.getAttribute('data-control'));
    await page.keyboard.down('Control');
    await page.keyboard.press('k');
    await page.keyboard.up('Control');
    await page.waitForFunction(() => {
      const overlay = document.getElementById('command-palette-overlay');
      return overlay?.getAttribute('aria-hidden') === 'false' &&
        document.activeElement?.id === 'command-palette-input';
    });

    const palette = await page.evaluate(() => {
      const overlay = document.getElementById('command-palette-overlay');
      const dialog = document.querySelector('.command-palette');
      const items = [...document.querySelectorAll('.command-palette-item')];
      const icons = [...document.querySelectorAll('.command-palette-item-icon svg')];
      return {
        hidden: overlay.getAttribute('aria-hidden'),
        focus: document.activeElement.id,
        role: document.getElementById('command-palette-input').getAttribute('role'),
        expanded: document.getElementById('command-palette-input').getAttribute('aria-expanded'),
        controls: document.getElementById('command-palette-input').getAttribute('aria-controls'),
        activeDescendant: document.getElementById('command-palette-input').getAttribute('aria-activedescendant'),
        selectedOptions: items.filter((item) => item.getAttribute('aria-selected') === 'true').length,
        itemCount: items.length,
        iconBounds: icons.map((icon) => {
          const bounds = icon.getBoundingClientRect();
          return { width: bounds.width, height: bounds.height };
        }),
        itemHeights: items.map((item) => item.getBoundingClientRect().height),
        dialogWidth: dialog.getBoundingClientRect().width,
        svgMarkupVisible: document.getElementById('command-palette-results').innerText.includes('viewBox'),
      };
    });

    assert.equal(palette.hidden, 'false');
    assert.equal(palette.focus, 'command-palette-input');
    assert.equal(palette.role, 'combobox');
    assert.equal(palette.expanded, 'true');
    assert.equal(palette.controls, 'command-palette-results');
    assert.ok(palette.activeDescendant?.startsWith('command-palette-option-'));
    assert.equal(palette.selectedOptions, 1);
    assert.ok(palette.itemCount >= 8, 'A busca rápida deve exibir os comandos de navegação e ação');
    assert.ok(palette.iconBounds.every(({ width, height }) => width <= 20 && height <= 20));
    assert.ok(palette.itemHeights.every((height) => height < 80));
    assert.ok(palette.dialogWidth <= 358, 'A paleta deve caber na largura mobile com gutters laterais');
    assert.equal(palette.svgMarkupVisible, false, 'O SVG deve ser renderizado como ícone, nunca como texto');

    await page.keyboard.press('Tab');
    assert.equal(await page.evaluate(() => document.activeElement?.id), 'command-palette-input', 'Tab must stay within the command palette');
    await page.keyboard.down('Shift');
    await page.keyboard.press('Tab');
    await page.keyboard.up('Shift');
    assert.equal(await page.evaluate(() => document.activeElement?.id), 'command-palette-input', 'Shift+Tab must stay within the command palette');

    await page.keyboard.press('ArrowDown');
    const movedSelection = await page.evaluate(() => {
      const input = document.getElementById('command-palette-input');
      const selected = [...document.querySelectorAll('.command-palette-item[aria-selected="true"]')];
      return { active: input.getAttribute('aria-activedescendant'), selectedId: selected[0]?.id };
    });
    assert.ok(movedSelection.active);
    assert.equal(movedSelection.active, movedSelection.selectedId);

    await page.locator('#command-palette-input').fill('normas');
    const rankedNorms = await page.evaluate(() => ({
      firstId: document.querySelector('.command-palette-item')?.dataset.commandId,
      selectedId: document.querySelector('.command-palette-item[aria-selected="true"]')?.dataset.commandId,
    }));
    assert.deepEqual(rankedNorms, { firstId: 'norms', selectedId: 'norms' });

    await page.locator('#command-palette-input').fill('jurix-sem-resultado-xyz');
    const emptySelection = await page.evaluate(() => ({
      active: document.getElementById('command-palette-input').getAttribute('aria-activedescendant'),
      options: document.querySelectorAll('.command-palette-item').length,
      expanded: document.getElementById('command-palette-input').getAttribute('aria-expanded'),
    }));
    assert.equal(emptySelection.active, null);
    assert.equal(emptySelection.options, 0);
    assert.equal(emptySelection.expanded, 'true');

    await page.keyboard.press('Escape');
    await page.waitForFunction(() => document.getElementById('command-palette-overlay')?.getAttribute('aria-hidden') === 'true');
    await page.waitForFunction((expected) => {
      const active = document.activeElement;
      return (active?.id || active?.getAttribute('data-control')) === expected;
    }, {}, focusBeforePalette);
  } finally {
    await browser.close();
    server.close();
  }
});

test('real browser: command palette keeps the user query while recent-history search is pending', async () => {
  const server = createTestServer();
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const port = server.address().port;
  const browser = await puppeteer.launch({
    executablePath,
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'],
  });

  try {
    const page = await browser.newPage();
    await page.setViewport({ width: 1280, height: 800 });
    await page.goto(`http://127.0.0.1:${port}/assistente/`, { waitUntil: 'domcontentloaded' });
    await page.setRequestInterception(true);
    page.on('request', (request) => {
      if (new URL(request.url()).pathname === '/api/v1/chat/sessions/') {
        setTimeout(() => request.respond({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ success: true, sessions: [], count: 0 }),
        }), 350);
      } else {
        request.continue();
      }
    });

    const historyResponse = page.waitForResponse((response) => (
      new URL(response.url()).pathname === '/api/v1/chat/sessions/'
    ));
    await page.click('#command-palette-trigger');
    await page.waitForFunction(() => document.activeElement?.id === 'command-palette-input');
    await page.locator('#command-palette-input').fill('normas');
    await historyResponse;
    await page.waitForFunction(() => (
      document.querySelector('.command-palette-item[data-command-id="norms"][aria-selected="true"]')
    ));
    const result = await page.evaluate(() => ({
      firstId: document.querySelector('.command-palette-item')?.dataset.commandId,
      selectedId: document.querySelector('.command-palette-item[aria-selected="true"]')?.dataset.commandId,
      visibleCount: document.querySelectorAll('.command-palette-item').length,
    }));
    assert.equal(result.firstId, 'norms');
    assert.equal(result.selectedId, 'norms');
    assert.ok(result.visibleCount < 8, JSON.stringify(result));
  } finally {
    await browser.close();
    server.close();
  }
});

test('real browser: legal device tree supports keyboard and pointer expansion', async () => {
  const server = createTestServer();
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  const port = server.address().port;
  const browser = await puppeteer.launch({
    executablePath,
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'],
  });

  try {
    const page = await browser.newPage();
    const browserErrors = [];
    page.on('pageerror', (error) => browserErrors.push(error.message));
    page.on('console', (message) => {
      if (message.type() === 'error') browserErrors.push(message.text());
    });
    await page.setViewport({ width: 390, height: 844 });
    await page.goto(`http://127.0.0.1:${port}/tree-test/`, { waitUntil: 'domcontentloaded' });
    await page.evaluate(() => document.querySelector('#article-1').focus());

    await page.keyboard.press('ArrowRight');
    assert.equal(await page.evaluate(() => document.activeElement.id), 'article-2');
    await page.keyboard.press('ArrowRight');
    assert.equal(await page.evaluate(() => document.activeElement.id), 'item-I');
    await page.keyboard.press('ArrowLeft');
    assert.equal(await page.evaluate(() => document.activeElement.id), 'article-2');
    await page.keyboard.press('ArrowLeft');
    const collapsedChild = await page.evaluate(() => ({
      focused: document.activeElement.id,
      expanded: document.querySelector('#article-2').getAttribute('aria-expanded'),
      hidden: document.querySelector('#article-2 > [role="group"]').hidden,
      label: document.querySelector('#article-2 [data-tree-toggle]').getAttribute('aria-label'),
    }));
    assert.deepEqual(collapsedChild, {
      focused: 'article-2',
      expanded: 'false',
      hidden: true,
      label: 'Expandir Artigo 2',
    });

    await page.keyboard.press('ArrowLeft');
    assert.equal(await page.evaluate(() => document.activeElement.id), 'article-1');
    await page.keyboard.press('End');
    assert.equal(await page.evaluate(() => document.activeElement.id), 'article-4');
    await page.keyboard.press('Home');
    assert.equal(await page.evaluate(() => document.activeElement.id), 'article-1');

    const touchTarget = await page.$eval('#article-1 [data-tree-toggle]', (button) => {
      const rect = button.getBoundingClientRect();
      return { width: rect.width, height: rect.height };
    });
    assert.deepEqual(touchTarget, { width: 44, height: 44 });
    await page.emulateMediaFeatures([{ name: 'prefers-reduced-motion', value: 'reduce' }]);
    const reducedMotionDurations = await page.$eval('#article-1 [data-tree-toggle]', (button) => [
      getComputedStyle(button).transitionDuration,
      getComputedStyle(button.querySelector('span')).transitionDuration,
    ]);
    assert.ok(reducedMotionDurations.every((duration) => Number.parseFloat(duration) <= 0.00001));
    await page.emulateMediaFeatures([{ name: 'prefers-reduced-motion', value: 'no-preference' }]);
    await page.click('#article-1 [data-tree-toggle]');
    const collapsedRoot = await page.evaluate(() => ({
      focused: document.activeElement.id,
      expanded: document.querySelector('#article-1').getAttribute('aria-expanded'),
      hidden: document.querySelector('#article-1 > [role="group"]').hidden,
    }));
    assert.deepEqual(collapsedRoot, { focused: 'article-1', expanded: 'false', hidden: true });
    assert.deepEqual(browserErrors, []);
  } finally {
    await browser.close();
    server.close();
  }
});

test('real browser: norm comparison stacks both labelled versions on mobile without overflow', async () => {
  const server = createTestServer();
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  const port = server.address().port;
  const browser = await puppeteer.launch({
    executablePath,
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'],
  });

  try {
    const page = await browser.newPage();
    await page.setViewport({ width: 390, height: 844 });
    await page.goto(`http://127.0.0.1:${port}/compare/`, { waitUntil: 'domcontentloaded' });
    await page.waitForFunction(() =>
      window.matchMedia('(max-width: 720px)').matches &&
      getComputedStyle(document.querySelector('.compare-diff-header')).display === 'none'
    );
    const mobile = await page.evaluate(() => ({
      viewportWidth: document.documentElement.clientWidth,
      documentWidth: document.documentElement.scrollWidth,
      headerDisplay: getComputedStyle(document.querySelector('.compare-diff-header')).display,
      gridColumns: getComputedStyle(document.querySelector('.compare-diff-row')).gridTemplateColumns,
      legalTextSize: getComputedStyle(document.querySelector('.compare-diff-row code')).fontSize,
      legalLabelSize: getComputedStyle(document.querySelector('.compare-diff-row code'), '::before').fontSize,
      labels: [...document.querySelectorAll('.compare-diff-row code')].map((cell) =>
        getComputedStyle(cell, '::before').content
      ),
      versions: [...document.querySelectorAll('.compare-diff-row code')].map((cell) => cell.innerText),
      missingSide: {
        label: document.querySelector('.compare-side-empty')?.getAttribute('aria-label'),
        visibleText: document.querySelector('.compare-side-empty')?.innerText,
        fontSize: getComputedStyle(document.querySelector('.compare-side-empty')).fontSize,
        whiteSpace: getComputedStyle(document.querySelector('.compare-side-empty')).whiteSpace,
      },
    }));
    assert.equal(mobile.documentWidth, mobile.viewportWidth);
    assert.equal(mobile.headerDisplay, 'none');
    assert.equal(mobile.gridColumns.split(' ').length, 1);
    assert.equal(mobile.legalTextSize, '14px');
    assert.equal(mobile.legalLabelSize, '10px');
    assert.deepEqual(mobile.labels, [
      '"Original (OCR) · linha 1"',
      '"Consolidado · linha 1"',
      '"Original (OCR) · linha —"',
      '"Consolidado · linha 2"',
    ]);
    assert.ok(mobile.versions.every((text) => text.length > 0));
    assert.equal(mobile.missingSide.label, 'Sem linha correspondente');
    assert.equal(mobile.missingSide.visibleText, 'Sem correspondente');
    assert.equal(mobile.missingSide.whiteSpace, 'nowrap');
    assert.ok(Number.parseFloat(mobile.missingSide.fontSize) < 12);

    await page.setViewport({ width: 1280, height: 800 });
    await page.waitForFunction(() => !window.matchMedia('(max-width: 720px)').matches);
    const desktop = await page.evaluate(() => ({
      headerDisplay: getComputedStyle(document.querySelector('.compare-diff-header')).display,
      columnCount: getComputedStyle(document.querySelector('.compare-diff-row')).gridTemplateColumns.split(' ').length,
      legalTextSize: getComputedStyle(document.querySelector('.compare-diff-row code')).fontSize,
    }));
    assert.notEqual(desktop.headerDisplay, 'none');
    assert.equal(desktop.columnCount, 5);
    assert.equal(desktop.legalTextSize, '12px');
  } finally {
    await browser.close();
    server.close();
  }
});

test('real browser: evidence drawer groups same-norm citations without hiding article detail', async () => {
  const server = createTestServer();
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  const port = server.address().port;
  const browser = await puppeteer.launch({
    executablePath,
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'],
  });

  try {
    const page = await browser.newPage();
    const browserErrors = [];
    page.on('pageerror', (error) => browserErrors.push(error.message));
    page.on('console', (message) => {
      if (message.type() === 'error') browserErrors.push(message.text());
    });
    await page.setViewport({ width: 390, height: 844 });
    await page.evaluateOnNewDocument(() => {
      window.JurixDynamicSuggestions = { refresh: async () => {} };
    });
    await page.goto(`http://127.0.0.1:${port}/assistente/`, { waitUntil: 'domcontentloaded' });
    await page.evaluate(() => {
      window.JurixRagUI.openSourcesDrawer([]);
      window.JurixRagUI.closeSourcesDrawer();
    });
    const closedDrawer = await page.evaluate(() => {
      const panel = document.getElementById('jurix-sources-drawer-panel');
      const closeButton = document.getElementById('jurix-sources-drawer-close');
      closeButton.focus();
      return {
        inert: panel.inert,
        hidden: panel.getAttribute('aria-hidden'),
        modal: panel.getAttribute('aria-modal'),
        closeButtonReceivedFocus: document.activeElement === closeButton,
      };
    });
    assert.deepEqual(closedDrawer, {
      inert: true,
      hidden: 'true',
      modal: 'false',
      closeButtonReceivedFocus: false,
    }, 'A closed evidence drawer must not expose its controls to keyboard focus');
    await page.evaluate(() => {
      const trigger = document.createElement('button');
      trigger.id = 'test-source-trigger';
      trigger.textContent = 'Ver fontes';
      document.body.appendChild(trigger);
      trigger.focus();
      window.JurixRagUI.openSourcesDrawer([
        { norma: 'Lei nº 8206/2026', dispositivo_ref: 'Art. 8º', text: 'Vigência na publicação.', similarity_score: 0.98 },
        { norma: 'Lei nº 8.206/2026', dispositivo_ref: 'Art. 7º', text: 'Execução orçamentária.', similarity_score: 0.97 },
        { norma: 'Lei nº 8205/2026', dispositivo_ref: 'Art. 1º', text: 'Outra norma.', similarity_score: 0.83 },
      ]);
    });
    await new Promise((resolve) => setTimeout(resolve, 350));

    const mobile = await page.evaluate(() => {
      const panel = document.getElementById('jurix-sources-drawer-panel');
      const rect = (element) => {
        const box = element.getBoundingClientRect();
        return { left: box.left, right: box.right, width: box.width };
      };
      return {
        groups: [...panel.querySelectorAll('.jurix-source-group')].map((group) => ({
          title: group.querySelector('h4')?.textContent,
          open: group.open,
          cards: group.querySelectorAll('.source-card').length,
          ranks: [...group.querySelectorAll('[data-evidence-rank]')].map((card) => card.dataset.evidenceRank),
          scores: [...group.querySelectorAll('.jurix-rag-score-meter')].map((meter) => meter.value),
          scoreHeights: [...group.querySelectorAll('.jurix-rag-score-text')].map((text) => text.getBoundingClientRect().height),
          bounds: rect(group),
        })),
        toggleBounds: rect(panel.querySelector('.jurix-source-group-toggle-all')),
        panelBounds: rect(panel),
        subtitle: panel.querySelector('#sources-drawer-subtitle')?.textContent,
        width: innerWidth,
      };
    });
    assert.equal(mobile.groups.length, 2);
    assert.equal(mobile.groups[0].cards, 2);
    assert.equal(mobile.groups[0].open, false, 'Multiple references to the same law should initially be grouped');
    assert.deepEqual(mobile.groups[0].ranks, ['1', '2']);
    assert.deepEqual(mobile.groups[0].scores, [98, 97]);
    assert.deepEqual(mobile.groups[1].scores, [83]);
    assert.ok(mobile.groups.every((group) => group.scoreHeights.every((height) => height < 24)), 'Relevance labels must stay on one line');
    assert.match(mobile.subtitle, /3 evidências em 2 normas/);
    assert.ok(mobile.groups.every((group) => group.bounds.left >= 0 && group.bounds.right <= mobile.width));
    assert.ok(
      mobile.toggleBounds.left >= mobile.panelBounds.left
        && mobile.toggleBounds.right <= mobile.panelBounds.right
        && mobile.toggleBounds.right <= mobile.width,
      'Expand/collapse control must remain fully visible inside the phone-sized source drawer'
    );
    await page.evaluate(() => window.JurixRagUI.focusEvidence(1));
    assert.equal(await page.$eval('[data-evidence-rank="1"]', (card) => card.closest('details').open), true, 'Following an in-answer citation should reveal its collapsed source group');
    await page.waitForFunction(() => document.querySelector('.jurix-source-group-toggle-all')?.textContent === 'Expandir restantes (1 de 2 abertas)');
    assert.equal(await page.$eval('.jurix-source-group-toggle-all', (button) => button.dataset.state), 'partially-open', 'Opening a single law group must expose the partial-expansion state');
    await page.click('.jurix-source-group-toggle-all');
    assert.deepEqual(await page.$$eval('.jurix-source-group', (groups) => groups.map((group) => group.open)), [true, true]);
    assert.equal(await page.$eval('.jurix-source-group-toggle-all', (button) => button.textContent), 'Recolher todas as evidências');
    await page.click('.jurix-source-group__header');
    await page.waitForFunction(() => document.querySelector('.jurix-source-group-toggle-all')?.textContent === 'Expandir restantes (1 de 2 abertas)');
    assert.deepEqual(await page.$$eval('.jurix-source-group', (groups) => groups.map((group) => group.open)), [false, true]);
    await page.evaluate(() => window.JurixRagUI.focusEvidence(1));
    assert.equal(await page.$eval('[data-evidence-rank="1"]', (card) => card.closest('details').open), true);
    await page.waitForFunction(() => document.querySelector('.jurix-source-group-toggle-all')?.textContent === 'Recolher todas as evidências');

    await page.setViewport({ width: 1440, height: 900 });
    const desktopBounds = await page.$eval('.jurix-sources-drawer-panel.is-open .jurix-source-group', (group) => {
      const { left, right } = group.getBoundingClientRect();
      return { left, right, width: innerWidth };
    });
    assert.ok(desktopBounds.left >= 0 && desktopBounds.right <= desktopBounds.width);

    await page.click('.jurix-source-group-toggle-all');
    assert.deepEqual(await page.$$eval('.jurix-source-group', (groups) => groups.map((group) => group.open)), [false, false]);
    await page.focus('#jurix-sources-drawer-close');
    await page.keyboard.down('Shift');
    await page.keyboard.press('Tab');
    await page.keyboard.up('Shift');
    const focusAfterWrap = await page.evaluate(() => {
      const panel = document.getElementById('jurix-sources-drawer-panel');
      const candidates = [...panel.querySelectorAll('button:not([disabled]), a[href], summary')].filter((element) => {
        let ancestor = element.parentElement;
        while (ancestor && ancestor !== panel) {
          if (ancestor.matches('details:not([open])') && ancestor.querySelector(':scope > summary') !== element) return false;
          ancestor = ancestor.parentElement;
        }
        return element.getClientRects().length > 0;
      });
      return {
        isFinalLawSummary: document.activeElement?.matches('.jurix-source-group:last-of-type > summary'),
        active: `${document.activeElement?.tagName}.${document.activeElement?.className}#${document.activeElement?.id}`,
        candidates: candidates.map((element) => `${element.tagName}.${element.className}:${element.textContent.trim().slice(0, 16)}`),
      };
    });
    assert.equal(focusAfterWrap.isFinalLawSummary, true, `Shift+Tab should wrap to the last disclosure: ${JSON.stringify(focusAfterWrap)}`);
    await page.keyboard.press('Tab');
    assert.equal(
      await page.evaluate(() => document.activeElement?.id),
      'jurix-sources-drawer-close',
      'Tab from the final disclosure must wrap to the first drawer control'
    );
    await page.keyboard.press('Escape');
    assert.equal(await page.evaluate(() => document.activeElement?.id), 'test-source-trigger');
    assert.equal(await page.$eval('#jurix-sources-drawer-panel', (panel) => panel.inert), true);

    await page.evaluate(() => {
      document.getElementById('test-source-trigger').focus();
      window.JurixRagUI.openSourcesDrawer([
        { norma: 'Lei nº 8206/2026', dispositivo_ref: 'Art. 8º', text: 'Vigência na publicação.', similarity_score: 0.98 },
      ]);
    });
    await page.waitForFunction(() => document.activeElement?.id === 'jurix-sources-drawer-close');
    await page.click('#jurix-sources-drawer-close');
    assert.equal(await page.evaluate(() => document.activeElement?.id), 'test-source-trigger');
    assert.equal(await page.$eval('#jurix-sources-drawer-panel', (panel) => panel.inert), true);
    assert.deepEqual(browserErrors, [], `Evidence drawer should not produce browser errors: ${browserErrors.join('; ')}`);
  } finally {
    await browser.close();
    server.close();
  }
});

test('real browser: clearing a norma search refreshes results and preserves other filters', async () => {
  const server = createTestServer();
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const port = server.address().port;
  const browser = await puppeteer.launch({
    executablePath,
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'],
  });

  try {
    const page = await browser.newPage();
    const errors = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.goto(`http://127.0.0.1:${port}/norma-search-test/?q=sem-resultados&tipo=Lei`, { waitUntil: 'domcontentloaded' });
    await page.click('#norma-search-clear');
    await page.waitForFunction(() => location.search === '?tipo=Lei&ano=');
    assert.equal(await page.$eval('#norma-search-input', (input) => input.value), '');
    assert.equal(await page.$eval('#results', (node) => node.textContent), '3 resultados');

    await page.goto(`http://127.0.0.1:${port}/norma-search-test/?q=sem-resultados&tipo=Lei`, { waitUntil: 'domcontentloaded' });
    await page.focus('#norma-search-input');
    await page.keyboard.press('Escape');
    await page.waitForFunction(() => location.search === '?tipo=Lei&ano=');
    assert.equal(await page.$eval('#norma-search-input', (input) => input.value), '');
    assert.equal(await page.$eval('#results', (node) => node.textContent), '3 resultados');
    assert.deepEqual(errors, []);
  } finally {
    await browser.close();
    server.close();
  }
});

test('real browser: legal device full text expands, collapses, and keeps keyboard focus', async () => {
  const server = createTestServer();
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const port = server.address().port;
  const browser = await puppeteer.launch({
    executablePath,
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'],
  });

  try {
    const page = await browser.newPage();
    await page.setViewport({ width: 390, height: 844 });
    const errors = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.goto(`http://127.0.0.1:${port}/device-expansion-test/`, { waitUntil: 'domcontentloaded' });
    const layout = await page.$eval('.dispositivo-node', (node) => ({
      width: document.documentElement.scrollWidth,
      viewport: innerWidth,
      radius: getComputedStyle(node).borderRadius,
      indent: getComputedStyle(node).marginInlineStart,
      bodyLineHeight: getComputedStyle(node.querySelector('.dispositivo-text')).lineHeight,
      bodyAlignment: getComputedStyle(node.querySelector('.dispositivo-text')).textAlign,
    }));
    assert.equal(layout.width, layout.viewport, 'legal-device reading cards must not overflow on mobile');
    assert.equal(layout.radius, '10px');
    assert.equal(layout.indent, '12px', 'nested devices should retain a compact, visible mobile hierarchy');
    assert.equal(layout.bodyAlignment, 'left', 'legal text should follow a stable left-aligned reading edge');
    assert.notEqual(layout.bodyLineHeight, 'normal');
    const fullText = await page.$eval('[data-device-text-full]', (node) => node.textContent.trim());
    await page.focus('[data-expand-device]');
    await page.keyboard.press('Enter');
    assert.equal(await page.$eval('[data-expand-device]', (node) => node.getAttribute('aria-expanded')), 'true');
    assert.equal(await page.$eval('[data-device-text-preview]', (node) => node.hidden), true);
    assert.equal(await page.$eval('[data-device-text-full]', (node) => node.hidden), false);
    assert.equal(await page.$eval('[data-device-text-full]', (node) => node.textContent.trim()), fullText);
    assert.equal(await page.$eval('[data-expand-device]', (node) => document.activeElement === node), true, 'focus must remain on the reversible toggle');
    assert.equal(await page.$eval('[data-expand-device]', (node) => node.innerText), 'Recolher texto');

    await page.keyboard.press('Enter');
    assert.equal(await page.$eval('[data-expand-device]', (node) => node.getAttribute('aria-expanded')), 'false');
    assert.equal(await page.$eval('[data-device-text-preview]', (node) => node.hidden), false);
    assert.equal(await page.$eval('[data-device-text-full]', (node) => node.hidden), true);
    assert.equal(await page.$eval('[data-expand-device]', (node) => node.innerText), 'Ver texto completo');
    assert.deepEqual(errors, []);
  } finally {
    await browser.close();
    server.close();
  }
});

test('real browser: exact norm number/year searches map to the number and year filters', async () => {
  const server = createTestServer();
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const port = server.address().port;
  const browser = await puppeteer.launch({
    executablePath,
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'],
  });

  try {
    const page = await browser.newPage();
    const errors = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.goto(`http://127.0.0.1:${port}/norma-search-test/`, { waitUntil: 'domcontentloaded' });
    await page.focus('#norma-search-input');
    await page.keyboard.type('Lei nº 8205/2026');
    await page.click('button[type="submit"]');
    await page.waitForFunction(() => location.search === '?q=8205&tipo=&ano=2026');
    assert.equal(await page.$eval('#norma-search-input', (input) => input.value), '8205');
    assert.equal(await page.$eval('#norma-ano', (select) => select.value), '2026');
    assert.deepEqual(errors, []);
  } finally {
    await browser.close();
    server.close();
  }
});

test('real browser: collection removal requires confirmation, traps focus, and respects reduced motion', async () => {
  let postCount = 0;
  let submittedForm = '';
  const server = createTestServer({
    '/collection-remove-test/': (req, res) => {
      if (req.method === 'POST') {
        postCount += 1;
        req.setEncoding('utf8');
        req.on('data', (chunk) => { submittedForm += chunk; });
        req.on('end', () => {
          res.writeHead(204);
          res.end();
        });
        return;
      }
      res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
      res.end(`<!doctype html><html lang="pt-BR" data-theme="dark"><head>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <link rel="stylesheet" href="/static/css/jurix-figma.css">
        <link rel="stylesheet" href="/static/css/workspace.css">
        <link rel="stylesheet" href="/static/css/jurix-components.css">
      </head><body class="figma-theme workspace-page workspace-document"><main class="workspace-content">
        <article class="workspace-card"><h2><a href="#norm">Lei nº 8.204/2026</a></h2>
          <form method="post" action="/collection-remove-test/" data-collection-remove-form>
            <input type="hidden" name="norma_id" value="204"><input type="hidden" name="action" value="remove">
            <button class="workspace-button workspace-button-ghost" type="submit" data-collection-norm="Lei nº 8.204/2026" aria-label="Remover Lei nº 8.204/2026 da coleção">Remover</button>
          </form>
        </article></main><script src="/static/js/jurix-collections.js"></script></body></html>`);
    },
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const port = server.address().port;
  const browser = await puppeteer.launch({
    executablePath,
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'],
  });

  try {
    const page = await browser.newPage();
    const errors = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.setViewport({ width: 390, height: 844 });
    await page.goto(`http://127.0.0.1:${port}/collection-remove-test/`, { waitUntil: 'domcontentloaded' });
    await page.focus('[data-collection-remove-form] button[type="submit"]');
    await page.keyboard.press('Enter');
    await page.waitForFunction(() => document.querySelector('[role="dialog"]')?.classList.contains('is-open'));

    const opened = await page.evaluate(() => {
      const dialog = document.querySelector('[role="dialog"]');
      const buttons = [...dialog.querySelectorAll('button')];
      const rect = dialog.querySelector('.workspace-confirm-dialog').getBoundingClientRect();
      return {
        hidden: dialog.getAttribute('aria-hidden'),
        inert: dialog.inert,
        focus: document.activeElement.dataset.collectionRemoveCancel !== undefined,
        label: dialog.getAttribute('aria-labelledby'),
        description: dialog.getAttribute('aria-describedby'),
        text: dialog.innerText,
        buttonHeights: buttons.map((button) => ({
          rect: button.getBoundingClientRect().height,
          minHeight: getComputedStyle(button).minHeight,
          height: getComputedStyle(button).height,
        })),
        viewportWidth: document.documentElement.clientWidth,
        documentWidth: document.documentElement.scrollWidth,
        animation: getComputedStyle(dialog.querySelector('.workspace-confirm-dialog')).animationName,
        rectRight: Math.round(rect.right),
      };
    });
    assert.equal(opened.hidden, 'false');
    assert.equal(opened.inert, false);
    assert.equal(opened.focus, true, 'focus should land on the safe cancel action');
    assert.equal(opened.label, 'collection-remove-title');
    assert.equal(opened.description, 'collection-remove-description');
    assert.match(opened.text, /Lei nº 8\.204\/2026/);
    assert.ok(opened.buttonHeights.every((size) => size.rect >= 44), JSON.stringify(opened));
    assert.equal(opened.documentWidth, opened.viewportWidth);
    assert.ok(opened.rectRight <= opened.viewportWidth);
    assert.equal(opened.animation, 'history-dialog-in');
    assert.equal(postCount, 0, 'opening confirmation must not submit the removal');

    await page.keyboard.press('Tab');
    assert.equal(await page.evaluate(() => document.activeElement.dataset.collectionRemoveConfirm !== undefined), true);
    await page.keyboard.press('Tab');
    assert.equal(await page.evaluate(() => document.activeElement.dataset.collectionRemoveCancel !== undefined), true);
    await page.keyboard.down('Shift');
    await page.keyboard.press('Tab');
    await page.keyboard.up('Shift');
    assert.equal(await page.evaluate(() => document.activeElement.dataset.collectionRemoveConfirm !== undefined), true);
    await page.keyboard.press('Escape');
    await page.waitForFunction(() => document.querySelector('[role="dialog"]')?.getAttribute('aria-hidden') === 'true');
    assert.equal(await page.evaluate(() => document.activeElement.matches('[data-collection-remove-form] button')), true);
    assert.equal(postCount, 0, 'Escape must cancel without a POST');

    await page.emulateMediaFeatures([{ name: 'prefers-reduced-motion', value: 'reduce' }]);
    await page.keyboard.press('Enter');
    await page.waitForFunction(() => document.querySelector('[role="dialog"]')?.classList.contains('is-open'));
    assert.equal(await page.$eval('.workspace-confirm-dialog', (node) => getComputedStyle(node).animationName), 'none');
    const responsePromise = page.waitForResponse((response) => response.url().endsWith('/collection-remove-test/') && response.request().method() === 'POST');
    await page.click('[data-collection-remove-confirm]');
    assert.equal((await responsePromise).status(), 204);
    assert.equal(postCount, 1, 'only explicit confirmation may submit the removal');
    assert.match(submittedForm, /norma_id=204/);
    assert.match(submittedForm, /action=remove/);
    assert.deepEqual(errors, []);
  } finally {
    await browser.close();
    server.close();
  }
});
