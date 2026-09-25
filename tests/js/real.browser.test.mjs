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
      return { top: c.scrollTop, height: c.scrollHeight, clientHeight: c.clientHeight };
    });

    // Click load more for page 2
    await page.click('.messages-load-more-indicator');
    await page.waitForFunction(() => document.querySelectorAll('#messages-wrapper .message').length === 40);

    // Measure scroll position after loading page 2
    const afterScroll1 = await page.evaluate(() => {
      const c = document.getElementById('messages-container');
      return { top: c.scrollTop, height: c.scrollHeight, clientHeight: c.clientHeight };
    });

    // Exact retention formula check: newScrollTop === oldScrollTop + deltaHeight
    const deltaHeight1 = afterScroll1.height - beforeScroll1.height;
    assert.equal(
      afterScroll1.top,
      beforeScroll1.top + deltaHeight1,
      'A posição de scroll deve ser ajustada rigorosamente pela altura das novas mensagens prepended'
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
          sources: [{ id: 99, tipo: 'Lei', norma: 'Lei nº 8.206/2026', text: 'Texto integral da Lei 8206 de Natal.' }],
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
    await page.goto(baseUrl, { waitUntil: 'domcontentloaded' });

    // Set up mutation observer to capture initial opacity on card insertion
    await page.evaluate(() => {
      window.__capturedOpacities = [];
      const obs = new MutationObserver(() => {
        const card = document.querySelector('.source-card, .jurix-rag-source');
        if (card) {
          const op = parseFloat(window.getComputedStyle(card).opacity);
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
    await page.waitForSelector('.sources-section, .source-card, .evidence-card, .jurix-rag-source', { timeout: 6000 });
    const sourceTexts = await page.$$eval(
      '.sources-section, .source-card, .evidence-card, .jurix-rag-source',
      (els) => els.map((el) => el.textContent)
    );
    assert.ok(
      sourceTexts.some((t) => t.includes('8206') || t.includes('Texto integral da Lei 8206 de Natal.')),
      'As fontes devem conter o número ou texto específico da Lei 8206'
    );

    // VERIFICAÇÃO RIGOROSA 3: Comprovação do fade-in (opacidade inicial < 0.5 e opacidade final >= 0.9)
    await page.waitForFunction(() => {
      const card = document.querySelector('.source-card, .jurix-rag-source');
      if (!card) return false;
      return parseFloat(window.getComputedStyle(card).opacity) >= 0.9;
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
  } finally {
    await browser.close();
    server.close();
  }
});

test('real browser: stream interruption preserves partial text and user question without wiping chat', async () => {
  const server = createTestServer({
    isAuthenticated: () => false,
    '/api/v1/search/answer/stream/': (req, res) => {
      res.writeHead(200, {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
      });

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
  } finally {
    await browser.close();
    server.close();
  }
});
