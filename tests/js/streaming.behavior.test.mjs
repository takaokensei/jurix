import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { JSDOM } from 'jsdom';

const JS_DIR = path.resolve(import.meta.dirname, '../../src/apps/core/static/js');
const TEMPLATE_DIR = path.resolve(import.meta.dirname, '../../src/apps/legislation/templates/legislation/workspace');
const read = (file) => fs.readFileSync(path.join(JS_DIR, file), 'utf8');
const readTemplate = (file) => fs.readFileSync(path.join(TEMPLATE_DIR, file), 'utf8');

test('anonymous stream persists the final answer after the API overlay is installed', async () => {
  const dom = new JSDOM(
    '<!doctype html><html><body><meta name="jurix-authenticated" content="false"></body></html>',
    { url: 'http://localhost/assistant/', runScripts: 'dangerously' },
  );
  const { window } = dom;
  window.TextDecoder = TextDecoder;
  const events = [
    { type: 'sources', sources: [{ id: 1 }], confidence: 0.9 },
    { type: 'chunk', chunk: 'Resposta ' },
    { type: 'chunk', chunk: 'final.' },
    { type: 'done', answer: 'Resposta final.', grounded: true, session_id: null },
  ];
  const encoded = events.map((event) => new TextEncoder().encode(`data: ${JSON.stringify(event)}\n\n`));
  let index = 0;
  window.fetch = async () => ({
    ok: true,
    status: 200,
    body: {
      getReader() {
        return {
          async read() {
            if (index >= encoded.length) return { done: true, value: undefined };
            return { done: false, value: encoded[index++] };
          },
        };
      },
    },
  });

  window.eval(read('jurix-anonymous-history.js'));
  window.eval(read('jurix-chat-api.js'));
  window.eval(read('jurix-api-reliability-overlay.js'));

  await window.JurixChatAPI.streamAnswer('Pergunta', null, {});

  const stored = JSON.parse(window.localStorage.getItem('jurix:anonymous-history:v2'));
  const messages = stored.sessions[0].messages;
  assert.equal(messages[0].role, 'user');
  assert.equal(messages[1].role, 'assistant');
  assert.equal(messages[1].content, 'Resposta final.');
  assert.equal(messages[1].grounded, true);
  assert.deepEqual(messages[1].sources, [{ id: 1 }]);
  assert.notEqual(messages[1].content, '[object Object]');
  dom.window.close();
});

test('anonymous history never restores evidence rejected by the final grounding decision', async () => {
  const dom = new JSDOM(
    '<!doctype html><html><body><meta name="jurix-authenticated" content="false"></body></html>',
    { url: 'http://localhost/assistant/', runScripts: 'dangerously' },
  );
  const { window } = dom;
  window.TextDecoder = TextDecoder;
  const events = [
    { type: 'sources', sources: [{ id: 7, text: 'Evidência não validada' }], confidence: 0.9 },
    { type: 'chunk', chunk: 'Rascunho da resposta.' },
    { type: 'done', answer: 'Resposta insuficientemente fundamentada.', grounded: false },
  ];
  const encoded = events.map((event) => new TextEncoder().encode(`data: ${JSON.stringify(event)}\n\n`));
  let index = 0;
  window.fetch = async () => ({
    ok: true,
    status: 200,
    body: { getReader: () => ({ async read() {
      if (index >= encoded.length) return { done: true, value: undefined };
      return { done: false, value: encoded[index++] };
    } }) },
  });

  window.eval(read('jurix-anonymous-history.js'));
  window.eval(read('jurix-chat-api.js'));
  window.eval(read('jurix-api-reliability-overlay.js'));
  await window.JurixChatAPI.streamAnswer('Pergunta', null, {});

  const sessionId = window.JurixAnonymousHistory.list()[0].id;
  const restored = await window.JurixChatAPI.getSession(sessionId);
  assert.equal(restored.messages[1].grounded, false);
  assert.deepEqual(Array.from(restored.messages[1].sources), []);
  const stored = JSON.parse(window.localStorage.getItem('jurix:anonymous-history:v2'));
  assert.deepEqual(Array.from(stored.sessions[0].messages[1].sources), []);
  dom.window.close();
});

test('legacy anonymous evidence without an explicit grounded marker is hidden on restore', () => {
  const dom = new JSDOM('<!doctype html><html><body data-authenticated="false"></body></html>', {
    url: 'http://localhost/assistente/',
    runScripts: 'dangerously',
  });
  const { window } = dom;
  window.localStorage.setItem('jurix:anonymous-history:v2', JSON.stringify({
    schema: 2,
    sessions: [{ id: 'local-old', messages: [{
      role: 'assistant', content: 'Resposta antiga', sources: [{ id: 9 }],
    }] }],
  }));
  window.eval(read('jurix-anonymous-history.js'));
  assert.deepEqual(Array.from(window.JurixAnonymousHistory.get('local-old').messages[0].sources), []);
  dom.window.close();
});

test('sources are deferred until the done callback and scroll is wired after render', () => {
  const chat = read('chat.js');
  const sourceCallback = chat.indexOf('(sources) => {');
  const doneCallback = chat.indexOf('async (doneData) => {', sourceCallback);
  assert.ok(sourceCallback > 0 && doneCallback > sourceCallback);
  assert.equal(chat.slice(sourceCallback, doneCallback).includes('showSourcesGradually'), false);
  const completion = chat.slice(doneCallback, doneCallback + 2200);
  assert.match(completion, /doneData\.grounded === true \? finalSources : \[\]/);
  assert.match(completion, /linkLegalReferences\(streamElements\.messageBody, answerSources\)/);
  assert.match(completion, /sourcesContainer && answerSources\.length > 0/);
  assert.match(completion, /insuficientes para fundamentar a resposta/);

  const regeneration = chat.slice(chat.indexOf('async function regenerateLastResponse'), chat.indexOf('function copyResponseToClipboard'));
  assert.match(regeneration, /data\.grounded === true && Array\.isArray\(data\.sources\)/);
  assert.match(regeneration, /if \(answerSources\.length > 0\)/);

  const rag = read('jurix-rag.js');
  assert.match(rag, /window\.scrollToBottomIfAtBottom\(\)/);
});

test('copy answer falls back when Clipboard API is unavailable and announces success', async () => {
  const dom = new JSDOM('<!doctype html><html><body><button class="copy-response-button" aria-label="Copiar resposta em Markdown" title="Copiar resposta"><svg class="copy-icon"></svg><svg class="check-icon is-hidden"></svg></button></body></html>', {
    url: 'http://localhost/assistente/', runScripts: 'dangerously', pretendToBeVisual: true,
  });
  const { window: w } = dom;
  let copiedText = '';
  w.document.execCommand = (command) => {
    assert.equal(command, 'copy');
    copiedText = w.document.querySelector('.jurix-clipboard-fallback')?.value || '';
    return true;
  };
  w.eval(read('jurix-chat-renderer.js'));
  const button = w.document.querySelector('.copy-response-button');
  button.focus();
  const copied = await w.JurixChatRenderer.copyResponseToClipboard('Art. 8º entra em vigor na publicação.', button);
  assert.equal(copied, true);
  assert.equal(copiedText, 'Art. 8º entra em vigor na publicação.');
  assert.equal(button.getAttribute('aria-label'), 'Resposta copiada');
  assert.equal(button.getAttribute('title'), 'Resposta copiada');
  assert.equal(w.document.activeElement, button);
  assert.ok(button.classList.contains('copied'));
  assert.equal(button.querySelector('.check-icon').classList.contains('is-hidden'), false);
  assert.equal(w.document.querySelector('.jurix-clipboard-fallback'), null);
  w.close();
});

test('restored user-message renderer uses the persisted creation time', () => {
  const dom = new JSDOM('<!doctype html><html><body><div id="messages-wrapper"></div></body></html>', {
    url: 'http://localhost/assistente/',
    runScripts: 'dangerously',
    pretendToBeVisual: true,
  });
  const { window: w } = dom;
  w.eval(read('jurix-chat-renderer.js'));
  const createdAt = '2020-01-02T03:04:00.000Z';
  const expected = new Date(createdAt).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });

  const message = w.JurixChatRenderer.addUserMessage('Pergunta restaurada', { createdAt });
  assert.equal(message.querySelector('.message-time')?.textContent, expected);
  assert.equal(w.JurixChatRenderer.formatTimestamp('not-a-date'), w.JurixChatRenderer.formatTimestamp());
  w.close();
});

test('anonymous retry replaces the partial assistant answer without duplicating the question', () => {
  const dom = new JSDOM('<!doctype html><html><body data-authenticated="false"></body></html>', {
    url: 'http://localhost/assistente/', runScripts: 'dangerously',
  });
  const { window: w } = dom;
  w.eval(read('jurix-anonymous-history.js'));
  const question = 'O que prevê o art. 8º?';
  const sessionId = w.JurixAnonymousHistory.ensureSession(null, question);
  w.JurixAnonymousHistory.addMessage(sessionId, 'user', question, []);
  w.JurixAnonymousHistory.updateLastAssistant(sessionId, 'Resposta parcial', []);

  assert.equal(w.JurixAnonymousHistory.prepareRetry(sessionId, question), true);
  const retried = w.JurixAnonymousHistory.get(sessionId);
  assert.equal(retried.messages.length, 1);
  assert.equal(retried.messages[0].role, 'user');
  assert.equal(retried.messages[0].content, question);
  w.JurixAnonymousHistory.updateLastAssistant(sessionId, 'Resposta completa', []);
  const completed = w.JurixAnonymousHistory.get(sessionId);
  assert.equal(JSON.stringify(completed.messages.map(message => message.role)), JSON.stringify(['user', 'assistant']));
  assert.equal(completed.messages[0].content, question);
  assert.equal(completed.messages[1].content, 'Resposta completa');
  w.close();
});

test('interrupted assistant messages are visibly labelled when history is restored', () => {
  const chat = read('chat.js');
  assert.match(chat, /metadata\.interrupted === true/);
  assert.match(chat, /Resposta interrompida/);
  assert.match(chat, /message-assistant--interrupted/);
});

test('source drawer keeps keyboard focus inside the modal', () => {
  const rag = read('jurix-rag.js');
  assert.match(rag, /event\.key !== 'Tab'/);
  assert.match(rag, /event\.shiftKey && document\.activeElement === first/);
  assert.match(rag, /!event\.shiftKey && document\.activeElement === last/);
});

test('empty source drawer has a focusable dialog fallback', () => {
  const dom = new JSDOM('<!doctype html><html><body></body></html>', {
    url: 'http://localhost/assistente/',
    runScripts: 'dangerously',
    pretendToBeVisual: true,
  });
  const { window: w } = dom;
  w.eval(read('jurix-rag.js'));
  w.JurixRagUI.openSourcesDrawer([]);
  const panel = w.document.getElementById('jurix-sources-drawer-panel');
  assert.equal(panel?.getAttribute('tabindex'), '-1');
  assert.equal(panel?.getAttribute('aria-hidden'), 'false');
  assert.equal(panel?.inert, false);
  assert.match(panel?.textContent || '', /evidências não estão disponíveis/i);
  assert.ok(panel?.querySelector('.jurix-sources-empty-retry'));
  w.JurixRagUI.closeSourcesDrawer();
  assert.equal(panel?.inert, true);
  assert.equal(panel?.getAttribute('aria-modal'), 'false');
  dom.window.close();
});

test('source drawer groups repeated norms without merging article evidence or citation targets', () => {
  const dom = new JSDOM('<!doctype html><html><body><button id="open-sources">Ver fontes</button></body></html>', {
    url: 'http://localhost/assistente/',
    runScripts: 'dangerously',
    pretendToBeVisual: true,
  });
  const { window: w } = dom;
  w.eval(read('jurix-rag.js'));
  w.document.getElementById('open-sources').focus();
  w.JurixRagUI.openSourcesDrawer([
    { norma: 'Lei nº 8206/2026', dispositivo_ref: 'Art. 8º', text: 'Vigência na publicação.', similarity_score: 0.98 },
    { norma: 'Lei nº 8.206/2026', dispositivo_ref: 'Art. 7º', text: 'Execução orçamentária.', similarity_score: 0.97 },
    { norma: 'Lei nº 8205/2026', dispositivo_ref: 'Art. 1º', text: 'Outra norma.', similarity_score: 0.83 },
  ]);

  const panel = w.document.getElementById('jurix-sources-drawer-panel');
  const groups = [...panel.querySelectorAll('.jurix-source-group')];
  assert.equal(groups.length, 2, 'Equivalent number formatting should group the same norm');
  assert.equal(groups[0].querySelectorAll('.source-card').length, 2);
  assert.equal(groups[0].querySelectorAll('[data-evidence-rank]').length, 2);
  assert.deepEqual([...groups[0].querySelectorAll('.jurix-rag-score-meter')].map((meter) => meter.value), [98, 97]);
  assert.match(groups[0].textContent, /Art\. 8º[\s\S]*Art\. 7º/);
  assert.equal(panel.querySelectorAll('.source-title').length, 0, 'The norm title should appear once in its group heading');
  assert.match(panel.querySelector('#sources-drawer-subtitle').textContent, /3 evidências em 2 normas/);
  assert.match(groups[0].querySelector('h4')?.textContent || '', /Lei nº 8206\/2026/);
  assert.equal(groups[1].querySelector('.jurix-rag-score-meter')?.value, 83);
  const zeroScore = w.document.createElement('div');
  zeroScore.innerHTML = w.JurixRagUI.renderEvidenceCard({ norma: 'Lei nº 1/2000', similarity_score: 0 }, 3);
  assert.equal(zeroScore.querySelector('.jurix-rag-score-meter')?.value, 0);

  w.JurixRagUI.closeSourcesDrawer();
  dom.window.close();
});

test('generic fetch failures do not claim the user has lost internet connectivity', () => {
  const dom = new JSDOM('<!doctype html><html><body><div id="error"></div></body></html>', {
    url: 'http://localhost/assistente/', runScripts: 'dangerously',
  });
  const { window: w } = dom;
  Object.defineProperty(w.navigator, 'onLine', { configurable: true, value: true });
  w.eval(read('jurix-rag.js'));
  w.JurixRagUI.renderErrorState(w.document.querySelector('#error'), new TypeError('Failed to fetch'));
  assert.match(w.document.querySelector('[role="alert"]').textContent, /Falha na comunicação/);
  assert.doesNotMatch(w.document.querySelector('[role="alert"]').textContent, /Sem conexão com a internet|Conexão indisponível/);

  Object.defineProperty(w.navigator, 'onLine', { configurable: true, value: false });
  w.JurixRagUI.renderErrorState(w.document.querySelector('#error'), new TypeError('Failed to fetch'));
  assert.match(w.document.querySelector('[role="alert"]').textContent, /Sem conexão com a internet/);
  w.close();
});

function guestWindow(saved, events = []) {
  const dom = new JSDOM('<body data-authenticated="false"><div id="messages-container"><div id="messages-wrapper"><div id="welcome-state"></div></div></div><div id="chat-sessions-list"></div><form id="chat-form"><textarea id="question-textarea"></textarea><button id="send-button"></button></form>', {
    url: 'http://localhost/assistente/', runScripts: 'dangerously', pretendToBeVisual: true,
  });
  const w = dom.window;
  w.TextDecoder = TextDecoder;
  if (saved) w.localStorage.setItem('jurix:anonymous-history:v2', saved);
  let reads = 0;
  w.fetch = async () => ({ ok: true, status: 200, body: { getReader: () => ({
    read: async () => reads < events.length
      ? { done: false, value: new TextEncoder().encode(`data: ${JSON.stringify(events[reads++])}\n\n`) }
      : { done: true },
  }) } });
  for (const file of ['jurix-anonymous-history.js', 'jurix-chat-api.js', 'jurix-api-reliability-overlay.js']) w.eval(read(file));
  return w;
}

test('guest identity and message contract survive a fresh page', async () => {
  const w = guestWindow(null, [{ type: 'chunk', chunk: 'Primeira' }, { type: 'done', answer: 'Primeira' }]);
  try {
    let id;
    await w.JurixChatAPI.streamAnswer('Pergunta', null, { onDone: data => { id = data.session_id; } });
    assert.match(id, /^local-/);
    const saved = w.localStorage.getItem('jurix:anonymous-history:v2');
    const reload = guestWindow(saved);
    try {
      const data = await reload.JurixChatAPI.getSessionBySlug(id);
      assert.equal(data.messages.length, 2);
      assert.equal(data.messages[1].content, 'Primeira');
      reload.history.replaceState({}, '', `/assistente/${id}/`);
      for (const file of ['vendor/marked.min.js', 'vendor/purify.min.js', 'jurix-markdown.js', 'jurix-rag.js', 'jurix-chat-state.js', 'jurix-chat-sessions.js', 'chat.js']) reload.eval(read(file));
      await new Promise(resolve => setTimeout(resolve, 60));
      assert.match(reload.document.getElementById('messages-wrapper').textContent, /Primeira/);
      assert.equal(reload.JurixChatState.snapshot().sessionId, id);
    } finally { reload.close(); }
  } finally { w.close(); }
});

test('EOF without done preserves verified guest partial text', async () => {
  const w = guestWindow(null, [{ type: 'chunk', chunk: 'Parcial' }]);
  try {
    let error;
    await assert.rejects(w.JurixChatAPI.streamAnswer('Pergunta', null, { onError: e => { error = e; } }), /interrompida/);
    assert.equal(error.code, 'INCOMPLETE_STREAM');
    const id = w.JurixAnonymousHistory.list()[0].id;
    assert.equal((await w.JurixChatAPI.getSession(id)).messages[1].content, 'Parcial');
  } finally { w.close(); }
});

test('unverified streaming draft is not persisted as a guest answer after interruption', async () => {
  const w = guestWindow(null, [{ type: 'chunk', chunk: 'Rascunho não verificado', provisional: true }]);
  try {
    await assert.rejects(w.JurixChatAPI.streamAnswer('Pergunta', null, {}), /interrompida/);
    const session = w.JurixAnonymousHistory.list()[0];
    const restored = await w.JurixChatAPI.getSession(session.id);
    assert.equal(restored.messages.length, 1, 'Only the user message should remain; no ungrounded assistant draft is stored');
  } finally { w.close(); }
});

test('history swipe reveals a delete action and deletion waits for confirmation', async () => {
  const dom = new JSDOM('<!doctype html><html><body><article class="workspace-history-card" data-history-card data-session-id="17"><div class="workspace-history-card__surface"><a href="/assistente/17/">Consulta</a></div><button data-history-delete>Excluir</button></article><article data-history-card data-session-id="18"></article></body></html>', {
    url: 'http://localhost/historico/', runScripts: 'dangerously',
  });
  const { window } = dom;
  let deleted = false;
  window.requestAnimationFrame = (callback) => callback();
  window.JurixChatAPI = { deleteSession: async (id) => { assert.equal(id, '17'); deleted = true; } };
  window.eval(read('jurix-history-actions.js'));
  const card = window.document.querySelector('[data-history-card]');
  const pointer = (type, x) => {
    const event = new window.MouseEvent(type, { bubbles: true, clientX: x, clientY: 20 });
    card.querySelector('.workspace-history-card__surface').dispatchEvent(event);
  };
  pointer('pointerdown', 160);
  pointer('pointermove', 90);
  assert.equal(card.classList.contains('is-delete-revealed'), true);
  window.document.querySelector('[data-history-delete]').click();
  assert.equal(deleted, false, 'The swipe action must not immediately delete the conversation');
  window.document.querySelector('[data-history-confirm]').click();
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.equal(deleted, true);
  assert.equal(window.document.querySelector('[data-session-id="17"]'), null);
  dom.window.close();
});

test('anonymous history distinguishes a genuinely empty history from a search with no matches', () => {
  const dom = new JSDOM('<!doctype html><html><body><form data-history-search><input name="q"></form><section data-anonymous-history></section></body></html>', {
    url: 'http://localhost/historico/', runScripts: 'dangerously',
  });
  const { window } = dom;
  window.eval(read('jurix-anonymous-history.js'));
  window.eval(read('jurix-anonymous-history-page.js'));
  const root = window.document.querySelector('[data-anonymous-history]');
  assert.match(root.textContent, /Histórico vazio/);
  assert.match(root.textContent, /Suas pesquisas aparecerão aqui/);
  assert.equal(root.querySelector('a[href="/assistente/"]')?.textContent.trim(), 'Abrir Assistente');
  assert.doesNotMatch(root.textContent, /Nenhuma conversa encontrada/);

  const input = window.document.querySelector('input[name="q"]');
  input.value = 'lei inexistente';
  input.dispatchEvent(new window.Event('input', { bubbles: true }));
  assert.match(root.textContent, /Nenhuma conversa encontrada/);
  assert.doesNotMatch(root.textContent, /Suas pesquisas aparecerão aqui/);

  input.value = '';
  input.dispatchEvent(new window.Event('search', { bubbles: true }));
  assert.match(root.textContent, /Suas pesquisas aparecerão aqui/);
  dom.window.close();
});

test('history search stays inline on desktop and anonymous result cards use the shared card interior', () => {
  const template = readTemplate('history.html');
  const renderer = read('jurix-anonymous-history-page.js');
  assert.match(template, /class="workspace-field" for="history-query"/);
  assert.doesNotMatch(template, /class="workspace-field workspace-field-wide" for="history-query"/);
  assert.match(renderer, /class="workspace-history-card__surface"><div class="workspace-history-card__link">/);
  assert.match(renderer, /workspace-history-meta/);
});

test('history delete failure does not incorrectly claim the connection is unavailable', async () => {
  const dom = new JSDOM('<!doctype html><html><body><article data-history-card data-session-id="17"><button data-history-delete>Excluir</button></article></body></html>', {
    url: 'http://localhost/historico/', runScripts: 'dangerously',
  });
  const { window } = dom;
  window.requestAnimationFrame = (callback) => callback();
  window.JurixChatAPI = { deleteSession: async () => { throw new Error('403 Forbidden'); } };
  window.eval(read('jurix-history-actions.js'));
  window.document.querySelector('[data-history-delete]').click();
  window.document.querySelector('[data-history-confirm]').click();
  await new Promise((resolve) => setTimeout(resolve, 0));
  const error = window.document.querySelector('.workspace-confirm-error');
  assert.equal(error.hidden, false);
  assert.match(error.textContent, /A exclusão não foi concluída/);
  assert.doesNotMatch(error.textContent, /conexão|offline|internet/i);
  assert.equal(window.document.querySelector('[data-history-card]') !== null, true);
  dom.window.close();
});

test('SSE parser accepts fragmented data, done before title, and terminal event without a blank line', async () => {
  const dom = new JSDOM('<!doctype html><html><body></body></html>', {
    url: 'http://localhost/assistente/', runScripts: 'dangerously',
  });
  const { window } = dom;
  window.TextDecoder = TextDecoder;
  const terminal = `data: {"type":"done","answer":"Resposta final."}\r\n\r\n`;
  const chunks = [
    new TextEncoder().encode('data: {"type":"chunk","chunk":"Res'),
    new TextEncoder().encode('posta","provisional":true}\r\n\r\n'),
    new TextEncoder().encode(terminal),
    new TextEncoder().encode('data: {"type":"title","title":"Pesquisa jurídica"}'),
  ];
  let index = 0;
  window.fetch = async () => ({
    ok: true,
    status: 200,
    body: { getReader: () => ({
      read: async () => index < chunks.length
        ? { done: false, value: chunks[index++] }
        : { done: true },
    }) },
  });
  window.eval(read('jurix-chat-api.js'));
  const received = [];
  const provisionalStates = [];
  let done;
  let title;
  await window.JurixChatAPI.streamAnswer('Pergunta', null, {
    onChunk: (chunk, metadata) => { received.push(chunk); provisionalStates.push(metadata.provisional); },
    onDone: (event) => { done = event.answer; },
    onTitle: (event) => { title = event.title; },
  });
  assert.deepEqual(received, ['Resposta']);
  assert.deepEqual(provisionalStates, [true]);
  assert.equal(done, 'Resposta final.');
  assert.equal(title, 'Pesquisa jurídica');
  dom.window.close();
});

test('post-completion UI callback failures never become connection errors', async () => {
  const dom = new JSDOM('<!doctype html><html><body></body></html>', {
    url: 'http://localhost/assistente/', runScripts: 'dangerously',
  });
  const { window } = dom;
  window.TextDecoder = TextDecoder;
  const chunks = [new TextEncoder().encode('data: {"type":"done","answer":"Resposta final."}\n\n')];
  let index = 0;
  window.fetch = async () => ({
    ok: true,
    status: 200,
    body: { getReader: () => ({
      read: async () => index < chunks.length ? { done: false, value: chunks[index++] } : { done: true },
    }) },
  });
  window.eval(read('jurix-chat-api.js'));
  let errors = 0;
  await window.JurixChatAPI.streamAnswer('Pergunta', null, {
    onDone: async () => { throw new TypeError('Falha numa atualização local do histórico'); },
    onError: () => { errors += 1; },
  });
  assert.equal(errors, 0);
  dom.window.close();
});

test('blocked storage keeps an in-memory conversation and displays warning', () => {
  const w = guestWindow();
  try {
    w.Storage.prototype.setItem = () => { throw new Error('quota'); };
    const id = w.JurixAnonymousHistory.ensureSession(null, 'Teste');
    w.JurixAnonymousHistory.addMessage(id, 'user', 'Pergunta', []);
    assert.equal(w.JurixAnonymousHistory.get(id).messages.length, 1);
    assert.ok(w.document.getElementById('jurix-storage-warning'));
  } finally { w.close(); }
});

test('renderer follows large growth only when already at bottom; citations stay within their answer', () => {
  const w = guestWindow();
  try {
    w.eval(read('jurix-rag.js'));
    const container = w.document.getElementById('messages-container');
    const body = w.document.createElement('div');
    container.append(body);
    Object.defineProperty(container, 'clientHeight', { value: 100 });
    Object.defineProperty(container, 'scrollHeight', { get: () => body.textContent.length > 10 ? 1000 : 100 });
    w.JurixRagUI.flushRender(body, 'x'.repeat(100));
    assert.equal(container.scrollTop, 1000);
    container.scrollTop = 0;
    w.JurixRagUI.flushRender(body, 'y'.repeat(100));
    assert.equal(container.scrollTop, 0);
    const first = w.document.createElement('div'), second = w.document.createElement('div');
    first.innerHTML = w.JurixRagUI.renderEvidenceCard({}, 0);
    second.innerHTML = w.JurixRagUI.renderEvidenceCard({}, 0);
    w.document.body.append(first, second);
    let focused = false;
    second.firstElementChild.scrollIntoView = () => { focused = true; };
    w.JurixRagUI.focusEvidence(1, second);
    assert.equal(focused, true);
    assert.notEqual(first.firstElementChild.id, second.firstElementChild.id);
  } finally { w.close(); }
});

test('citation click opens the global evidence drawer and focuses the matching source', async () => {
  const w = guestWindow();
  try {
    w.eval(read('jurix-rag.js'));
    const message = w.document.createElement('div');
    message.className = 'message message-assistant';
    message.innerHTML = '<div class="message-body"><a class="jurix-citation" href="#jurix-evidence-1" data-source-index="1">[[1]]</a></div><div id="sources-test"></div>';
    const sources = [{ norma: 'Lei nº 8.206/2026', text: 'Trecho verificável.' }];
    message.querySelector('#sources-test')._sourcesData = sources;
    w.document.body.append(message);

    message.querySelector('.jurix-citation').dispatchEvent(new w.MouseEvent('click', { bubbles: true, cancelable: true }));
    await new Promise((resolve) => w.requestAnimationFrame(resolve));

    const panel = w.document.getElementById('jurix-sources-drawer-panel');
    assert.equal(panel.classList.contains('is-open'), true);
    assert.equal(panel.querySelector('[data-evidence-rank="1"]')?.classList.contains('is-citation-target'), true);
  } finally { w.close(); }
});
