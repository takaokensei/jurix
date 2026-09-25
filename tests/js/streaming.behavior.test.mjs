import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { JSDOM } from 'jsdom';

const JS_DIR = path.resolve(import.meta.dirname, '../../src/apps/core/static/js');
const read = (file) => fs.readFileSync(path.join(JS_DIR, file), 'utf8');

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
    { type: 'done', answer: 'Resposta final.', session_id: null },
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
  assert.notEqual(messages[1].content, '[object Object]');
  dom.window.close();
});

test('sources are deferred until the done callback and scroll is wired after render', () => {
  const chat = read('chat.js');
  const sourceCallback = chat.indexOf('(sources) => {');
  const doneCallback = chat.indexOf('async (doneData) => {', sourceCallback);
  assert.ok(sourceCallback > 0 && doneCallback > sourceCallback);
  assert.equal(chat.slice(sourceCallback, doneCallback).includes('showSourcesGradually'), false);
  assert.ok(chat.slice(doneCallback, doneCallback + 1800).includes('showSourcesGradually'));

  const rag = read('jurix-rag.js');
  assert.match(rag, /window\.scrollToBottomIfAtBottom\(\)/);
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

test('EOF without done reports interruption and preserves guest partial text', async () => {
  const w = guestWindow(null, [{ type: 'chunk', chunk: 'Parcial' }]);
  try {
    let error;
    await assert.rejects(w.JurixChatAPI.streamAnswer('Pergunta', null, { onError: e => { error = e; } }), /interrompida/);
    assert.equal(error.code, 'INCOMPLETE_STREAM');
    const id = w.JurixAnonymousHistory.list()[0].id;
    assert.equal((await w.JurixChatAPI.getSession(id)).messages[1].content, 'Parcial');
  } finally { w.close(); }
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
