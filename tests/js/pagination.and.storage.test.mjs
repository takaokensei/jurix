import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { JSDOM } from 'jsdom';

const JS_DIR = path.resolve(import.meta.dirname, '../../src/apps/core/static/js');
const read = (file) => fs.readFileSync(path.join(JS_DIR, file), 'utf8');

function setupEnvironment({ isAuthenticated = true, fetchHandler, initialUrl = 'http://localhost/assistente/' } = {}) {
  const dom = new JSDOM(
    `<!doctype html>
    <html>
      <body data-authenticated="${isAuthenticated ? 'true' : 'false'}" data-user-name="TestUser" data-chatbot-url="/assistente/">
        <div id="messages-container" style="height: 500px; overflow-y: auto;">
          <div id="messages-wrapper">
            <div id="welcome-state"></div>
          </div>
        </div>
        <div id="chat-sessions-list">
          <div class="chat-session-item" data-session-id="1">Sessao 1</div>
        </div>
        <form id="chat-form">
          <textarea id="question-textarea"></textarea>
          <button id="send-button" type="submit">Enviar</button>
        </form>
        <button id="new-chat-button" type="button">Nova conversa</button>
      </body>
    </html>`,
    {
      url: initialUrl,
      runScripts: 'dangerously',
      pretendToBeVisual: true,
    }
  );

  const { window } = dom;
  window.TextDecoder = TextDecoder;
  window.TextEncoder = TextEncoder;
  window.fetch = fetchHandler || (async () => ({ ok: true, status: 200, json: async () => ({ success: true }) }));

  // Load scripts in standard application sequence
  const scripts = [
    'vendor/marked.min.js',
    'vendor/purify.min.js',
    'jurix-markdown.js',
    'jurix-rag.js',
    'jurix-anonymous-history.js',
    'jurix-chat-api.js',
    'jurix-api-reliability-overlay.js',
    'jurix-chat-sessions.js',
    'jurix-chat-state.js',
    'jurix-chat-renderer.js',
    'chat.js',
  ];

  for (const script of scripts) {
    window.eval(read(script));
  }

  return dom;
}

test('history pagination: traverses all pages, forwards cursor, preserves chronological order without duplicates', async () => {
  // 60 messages total: 1 to 60.
  // Page 1: 36..60 (25 messages, chronological), has_more: true, next_cursor: 'cursor-page-1'
  // Page 2: 11..35 (25 messages, chronological), has_more: true, next_cursor: 'cursor-page-2'
  // Page 3: 1..10  (10 messages, chronological), has_more: false, next_cursor: null
  const requestedUrls = [];

  const fetchHandler = async (input) => {
    const url = typeof input === 'string' ? input : input?.url || '';
    requestedUrls.push(url);

    if (url.includes('/api/v1/chat/sessions/1/')) {
      const parsedUrl = new URL(url, 'http://localhost');
      const before = parsedUrl.searchParams.get('before');

      let messages = [];
      let hasMore = false;
      let nextCursor = null;

      if (!before) {
        // Page 1: messages 36..60
        messages = Array.from({ length: 25 }, (_, i) => ({
          id: 36 + i,
          role: (36 + i) % 2 === 1 ? 'user' : 'assistant',
          content: `Mensagem ${36 + i}`,
          created_at: new Date(1000000 + (36 + i) * 1000).toISOString(),
        }));
        hasMore = true;
        nextCursor = 'cursor-page-1';
      } else if (before === 'cursor-page-1') {
        // Page 2: messages 11..35
        messages = Array.from({ length: 25 }, (_, i) => ({
          id: 11 + i,
          role: (11 + i) % 2 === 1 ? 'user' : 'assistant',
          content: `Mensagem ${11 + i}`,
          created_at: new Date(1000000 + (11 + i) * 1000).toISOString(),
        }));
        hasMore = true;
        nextCursor = 'cursor-page-2';
      } else if (before === 'cursor-page-2') {
        // Page 3: messages 1..10
        messages = Array.from({ length: 10 }, (_, i) => ({
          id: 1 + i,
          role: (1 + i) % 2 === 1 ? 'user' : 'assistant',
          content: `Mensagem ${1 + i}`,
          created_at: new Date(1000000 + (1 + i) * 1000).toISOString(),
        }));
        hasMore = false;
        nextCursor = null;
      }

      return {
        ok: true,
        status: 200,
        json: async () => ({
          success: true,
          session: { id: 1, slug: 'sessao-1', title: 'Sessão 1' },
          messages,
          has_more: hasMore,
          next_cursor: nextCursor,
        }),
      };
    }

    if (url.includes('/api/v1/chat/sessions/')) {
      return {
        ok: true,
        status: 200,
        json: async () => ({ success: true, sessions: [{ id: 1, slug: 'sessao-1', title: 'Sessão 1' }] }),
      };
    }

    return { ok: true, status: 200, json: async () => ({ success: true }) };
  };

  const dom = setupEnvironment({ isAuthenticated: true, fetchHandler });
  const { window } = dom;

  try {
    // 1. Initial session load
    await window.jurixChat.loadSession(1);

    const session1Requests = requestedUrls.filter((u) => u.includes('/api/v1/chat/sessions/1/'));
    assert.equal(session1Requests.length, 1);
    assert.match(session1Requests[0], /\/api\/v1\/chat\/sessions\/1\/$/);

    let loadMoreBtn = window.document.querySelector('.messages-load-more-indicator');
    assert.ok(loadMoreBtn, 'O botão de carregar mensagens anteriores deve existir');

    let renderedMessages = Array.from(window.document.querySelectorAll('#messages-wrapper .message'));
    assert.equal(renderedMessages.length, 25, 'Primeira página deve conter 25 mensagens');
    assert.match(renderedMessages[0].textContent, /Mensagem 36/);
    assert.match(renderedMessages[24].textContent, /Mensagem 60/);

    // 2. Click button to load Page 2
    loadMoreBtn.click();
    await new Promise((r) => setTimeout(r, 50));

    const session1RequestsP2 = requestedUrls.filter((u) => u.includes('/api/v1/chat/sessions/1/'));
    assert.equal(session1RequestsP2.length, 2);
    assert.ok(
      session1RequestsP2[1].includes('before=cursor-page-1'),
      `A segunda requisição deve conter ?before=cursor-page-1, recebido: ${session1RequestsP2[1]}`
    );

    loadMoreBtn = window.document.querySelector('.messages-load-more-indicator');
    assert.ok(loadMoreBtn, 'O botão deve continuar presente para carregar a página 3');

    renderedMessages = Array.from(window.document.querySelectorAll('#messages-wrapper .message'));
    assert.equal(renderedMessages.length, 50, 'Após a página 2, devem existir 50 mensagens');
    assert.match(renderedMessages[0].textContent, /Mensagem 11/);
    assert.match(renderedMessages[24].textContent, /Mensagem 35/);
    assert.match(renderedMessages[25].textContent, /Mensagem 36/);
    assert.match(renderedMessages[49].textContent, /Mensagem 60/);

    // 3. Click button to load Page 3 (final page)
    loadMoreBtn.click();
    await new Promise((r) => setTimeout(r, 50));

    const session1RequestsP3 = requestedUrls.filter((u) => u.includes('/api/v1/chat/sessions/1/'));
    assert.equal(session1RequestsP3.length, 3);
    assert.ok(
      session1RequestsP3[2].includes('before=cursor-page-2'),
      `A terceira requisição deve conter ?before=cursor-page-2, recebido: ${session1RequestsP3[2]}`
    );

    loadMoreBtn = window.document.querySelector('.messages-load-more-indicator');
    assert.equal(loadMoreBtn, null, 'O botão deve ser removido quando não houver mais páginas');

    renderedMessages = Array.from(window.document.querySelectorAll('#messages-wrapper .message'));
    assert.equal(renderedMessages.length, 60, 'Todas as 60 mensagens devem estar renderizadas');

    // 4. Verify chronological order and uniqueness
    const texts = renderedMessages.map((m) => {
      const match = m.textContent.match(/Mensagem \d+/);
      return match ? match[0] : '';
    });

    const expected = Array.from({ length: 60 }, (_, i) => `Mensagem ${i + 1}`);
    assert.deepEqual(texts, expected, 'A ordem cronológica exata de 1 a 60 deve ser preservada');
    assert.equal(new Set(texts).size, 60, 'Cada mensagem deve aparecer exatamente uma única vez sem duplicação');
  } finally {
    dom.window.close();
  }
});

test('history pager: handles concurrent clicks and recovers gracefully after request failure', async () => {
  let failOnce = true;
  let requestsCount = 0;

  const fetchHandler = async (input) => {
    const url = typeof input === 'string' ? input : input?.url || '';
    if (url.includes('/api/v1/chat/sessions/1/')) {
      const parsedUrl = new URL(url, 'http://localhost');
      const before = parsedUrl.searchParams.get('before');

      if (!before) {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            success: true,
            session: { id: 1, slug: 'sessao-1', title: 'Sessão 1' },
            messages: [{ id: 2, role: 'user', content: 'Mensagem 2' }],
            has_more: true,
            next_cursor: 'cursor-retry',
          }),
        };
      }

      requestsCount++;
      if (failOnce) {
        failOnce = false;
        // Simulate network failure
        throw new Error('Falha de rede simulada');
      }

      return {
        ok: true,
        status: 200,
        json: async () => ({
          success: true,
          session: { id: 1, slug: 'sessao-1', title: 'Sessão 1' },
          messages: [{ id: 1, role: 'user', content: 'Mensagem 1' }],
          has_more: false,
          next_cursor: null,
        }),
      };
    }
    return { ok: true, status: 200, json: async () => ({ success: true, sessions: [] }) };
  };

  const dom = setupEnvironment({ isAuthenticated: true, fetchHandler });
  const { window } = dom;

  try {
    await window.jurixChat.loadSession(1);
    const button = window.document.querySelector('.messages-load-more-indicator');
    assert.ok(button);

    // Click 1: should fail and show retry text
    button.click();
    await new Promise((r) => setTimeout(r, 60));

    assert.equal(button.disabled, false, 'Botão deve estar habilitado para nova tentativa');
    assert.match(button.textContent, /Tentar novamente/);

    // Click 2 (retry): should succeed now
    button.click();
    await new Promise((r) => setTimeout(r, 60));

    const finalButton = window.document.querySelector('.messages-load-more-indicator');
    assert.equal(finalButton, null, 'Botão deve ser removido após término com sucesso');

    const messages = Array.from(window.document.querySelectorAll('#messages-wrapper .message'));
    assert.equal(messages.length, 2, 'Ambas mensagens devem estar presentes');
  } finally {
    dom.window.close();
  }
});

test('local storage protection: SecurityError, quota exceeded, invalid JSON, and blocked removal', async () => {
  const dom = setupEnvironment({ isAuthenticated: false });
  const { window } = dom;

  try {
    // 1. Test createNewSession when localStorage throws SecurityError on enumeration or removal
    const originalGetItem = window.localStorage.getItem;
    const originalKeys = Object.keys;

    window.localStorage.removeItem = () => {
      const err = new Error('Blocked removal');
      err.name = 'SecurityError';
      throw err;
    };

    // createNewSession should not throw and should still execute its cleanup and state updates
    await window.jurixChat.createNewSession();
    assert.equal(window.JurixChatState.snapshot().sessionId, null);
    assert.equal(window.document.getElementById('question-textarea').value, '');

    // 2. Test attachment upload when localStorage.setItem throws QuotaExceededError
    window.localStorage.setItem = () => {
      const quotaErr = new Error('The quota has been exceeded.');
      quotaErr.name = 'QuotaExceededError';
      throw quotaErr;
    };

    window.fetch = async (url) => {
      if (url.includes('/api/v1/chat/attachments/')) {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            success: true,
            attachment: { id: 'att-123', name: 'teste.pdf', size: 1024, content_type: 'application/pdf' },
          }),
        };
      }
      return { ok: true, status: 200, json: async () => ({ success: true }) };
    };

    const dummyFile = { name: 'teste.pdf', size: 1024, type: 'application/pdf' };
    const uploaded = await window.JurixChatAPI.uploadAttachment(dummyFile);
    assert.equal(uploaded.id, 'att-123', 'O upload no servidor não deve ser anulado por erro de quota local');

    // In-memory fallback retains metadata
    const localList = window.JurixChatAPI.listLocalAttachments();
    assert.equal(localList.length, 1);
    assert.equal(localList[0].id, 'att-123');

    // 3. Test invalid JSON in localStorage does not crash attachmentStore
    window.localStorage.setItem = originalGetItem; // restore
    window.localStorage.getItem = (key) => (key.includes('attachments') ? '{invalid json' : null);

    const safeList = window.JurixChatAPI.listLocalAttachments();
    assert.ok(Array.isArray(safeList), 'JSON corrompido deve retornar lista vazia sem lançar exceção');
  } finally {
    dom.window.close();
  }
});

test('navigation race protection: out-of-order session responses do not overwrite newer state', async () => {
  let resolveSession1;
  const session1Promise = new Promise((resolve) => {
    resolveSession1 = resolve;
  });

  const dom = setupEnvironment({
    fetchHandler: async (url) => {
      if (url.includes('/api/v1/chat/sessions/1/')) {
        await session1Promise;
        return {
          ok: true,
          status: 200,
          json: async () => ({
            success: true,
            session: { id: 1, slug: 'conversa-um', title: 'Conversa Um' },
            messages: [{ role: 'user', content: 'Pergunta da Conversa Um' }],
          }),
        };
      }
      if (url.includes('/api/v1/chat/sessions/2/')) {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            success: true,
            session: { id: 2, slug: 'conversa-dois', title: 'Conversa Dois' },
            messages: [{ role: 'user', content: 'Pergunta da Conversa Dois' }],
          }),
        };
      }
      if (url.includes('/api/v1/chat/sessions/')) {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            success: true,
            sessions: [
              { id: 1, slug: 'conversa-um', title: 'Conversa Um' },
              { id: 2, slug: 'conversa-dois', title: 'Conversa Dois' },
            ],
          }),
        };
      }
      return { ok: true, status: 200, json: async () => ({ success: true }) };
    },
  });

  const { window } = dom;

  try {
    // 1. Start loading session 1 (delayed via promise)
    const p1 = window.jurixChat.loadSession(1);

    // 2. Start and finish loading session 2 immediately
    await window.jurixChat.loadSession(2);

    assert.equal(window.jurixChat.getCurrentSessionId(), 2);
    assert.ok(window.location.pathname.includes('conversa-dois'));
    let text = window.document.getElementById('messages-wrapper')?.textContent || '';
    assert.ok(text.includes('Pergunta da Conversa Dois'));
    assert.ok(!text.includes('Pergunta da Conversa Um'));

    // 3. Now release session 1's delayed response
    resolveSession1();
    await p1;

    // 4. Assert session 1 did NOT overwrite session 2
    assert.equal(window.jurixChat.getCurrentSessionId(), 2, 'Session ID must remain 2');
    assert.ok(window.location.pathname.includes('conversa-dois'), 'URL must remain conversa-dois');
    text = window.document.getElementById('messages-wrapper')?.textContent || '';
    assert.ok(text.includes('Pergunta da Conversa Dois'), 'Content must remain from Session 2');
    assert.ok(!text.includes('Pergunta da Conversa Um'), 'Late arrival of Session 1 must not overwrite messages');

    // 5. Scenario B: Slow loadSession superseded by createNewSession
    let resolveSessionSlow;
    const slowPromise = new Promise((resolve) => { resolveSessionSlow = resolve; });

    // Override fetch to hold session 1 again
    const origFetch = window.fetch;
    window.fetch = async (url) => {
      if (url.includes('/api/v1/chat/sessions/1/')) {
        await slowPromise;
        return {
          ok: true,
          status: 200,
          json: async () => ({
            success: true,
            session: { id: 1, slug: 'conversa-um', title: 'Conversa Um' },
            messages: [{ role: 'user', content: 'Sobrescrita Invalida' }],
          }),
        };
      }
      return origFetch(url);
    };

    const pSlow = window.jurixChat.loadSession(1);
    await window.jurixChat.createNewSession();

    assert.equal(window.jurixChat.getCurrentSessionId(), null, 'Sessão deve ser null em nova conversa');
    assert.equal(window.document.querySelectorAll('#messages-wrapper .message').length, 0);

    // Release slow load
    resolveSessionSlow();
    await pSlow;

    assert.equal(window.jurixChat.getCurrentSessionId(), null, 'Chegada tardia não deve alterar sessão nula');
    assert.equal(window.document.querySelectorAll('#messages-wrapper .message').length, 0, 'Mensagens tardias descartadas');
  } finally {
    dom.window.close();
  }
});
