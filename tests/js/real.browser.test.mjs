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
            <code class="compare-original-text" role="cell" data-label="Original (OCR)">Texto original da norma</code>
            <span class="compare-diff-marker" aria-hidden="true">−</span>
            <span class="compare-line-number" aria-hidden="true">1</span>
            <code class="compare-consolidated-text" role="cell" data-label="Consolidado">Texto consolidado da norma</code>
          </div>
        </div></section></main></body></html>`);
    }

    res.writeHead(404);
    res.end('Not found');
  });

  return server;
}

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

    // 1. REAL F5 (Reload)
    await page.reload({ waitUntil: 'domcontentloaded' });

    // After reload, the messages must be restored on screen
    await page.waitForFunction(() => {
      const msgs = document.querySelectorAll('.message-assistant');
      return msgs.length > 0 && msgs[0].textContent.includes('Resposta anônima persistida com sucesso.');
    }, { timeout: 5000 });

    const restoredText = await page.$eval('.message-assistant', (el) => el.textContent);
    assert.ok(restoredText.includes('Resposta anônima persistida com sucesso.'));

    // 2. Direct URL navigation in a new tab
    const page2 = await browser.newPage();
    await page2.goto(currentUrl, { waitUntil: 'domcontentloaded' });

    await page2.waitForFunction(() => {
      const msgs = document.querySelectorAll('.message-assistant');
      return msgs.length > 0 && msgs[0].textContent.includes('Resposta anônima persistida com sucesso.');
    }, { timeout: 5000 });

    const directNavText = await page2.$eval('.message-assistant', (el) => el.textContent);
    assert.ok(directNavText.includes('Resposta anônima persistida com sucesso.'));
    await page2.close();
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
  const donePromise = new Promise((resolve) => {
    releaseDone = resolve;
  });

  const server = createTestServer({
    isAuthenticated: () => false,
    '/api/test/release-done/': (req, res) => {
      if (releaseDone) releaseDone();
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ ok: true }));
    },
    '/api/v1/search/answer/stream/': async (req, res) => {
      res.writeHead(200, {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
      });

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

    // Libera a barreira para o servidor emitir o done
    await page.evaluate(() => fetch('/api/test/release-done/'));

    // VERIFICAÇÃO RIGOROSA 2: Aguardar renderização das fontes
    await page.waitForSelector('.sources-section', { timeout: 6000 });
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

    const toggle = page.locator('#toggle-sidebar');
    await toggle.click();
    await page.waitForFunction(() => {
      const sidebar = document.getElementById('sidebar');
      return sidebar?.classList.contains('is-open') && sidebar.getBoundingClientRect().right >= 239;
    });
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
    await page.keyboard.press('Escape');
    await page.waitForFunction(() => {
      const sidebar = document.getElementById('sidebar');
      return !sidebar?.classList.contains('is-open') && sidebar.getBoundingClientRect().right <= 0;
    });
    assert.equal(await page.$eval('#toggle-sidebar', (button) => button.getAttribute('aria-expanded')), 'false');

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
    assert.ok(palette.itemCount >= 8, 'A busca rápida deve exibir os comandos de navegação e ação');
    assert.ok(palette.iconBounds.every(({ width, height }) => width <= 20 && height <= 20));
    assert.ok(palette.itemHeights.every((height) => height < 80));
    assert.ok(palette.dialogWidth <= 358, 'A paleta deve caber na largura mobile com gutters laterais');
    assert.equal(palette.svgMarkupVisible, false, 'O SVG deve ser renderizado como ícone, nunca como texto');

    await page.keyboard.press('Escape');
    await page.waitForFunction(() => document.getElementById('command-palette-overlay')?.getAttribute('aria-hidden') === 'true');
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
      labels: [...document.querySelectorAll('.compare-diff-row code')].map((cell) =>
        getComputedStyle(cell, '::before').content
      ),
      versions: [...document.querySelectorAll('.compare-diff-row code')].map((cell) => cell.innerText),
    }));
    assert.equal(mobile.documentWidth, mobile.viewportWidth);
    assert.equal(mobile.headerDisplay, 'none');
    assert.equal(mobile.gridColumns.split(' ').length, 1);
    assert.deepEqual(mobile.labels, ['"Original (OCR)"', '"Consolidado"']);
    assert.ok(mobile.versions.every((text) => text.length > 0));

    await page.setViewport({ width: 1280, height: 800 });
    await page.waitForFunction(() => !window.matchMedia('(max-width: 720px)').matches);
    const desktop = await page.evaluate(() => ({
      headerDisplay: getComputedStyle(document.querySelector('.compare-diff-header')).display,
      columnCount: getComputedStyle(document.querySelector('.compare-diff-row')).gridTemplateColumns.split(' ').length,
    }));
    assert.notEqual(desktop.headerDisplay, 'none');
    assert.equal(desktop.columnCount, 5);
  } finally {
    await browser.close();
    server.close();
  }
});
