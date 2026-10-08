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
    { type: 'sources', sources: [{ id: 1 }, { id: 2 }], confidence: 0.9 },
    { type: 'chunk', chunk: 'Rascunho provisório.', provisional: true },
    { type: 'chunk', chunk: 'Resposta final.', provisional: false, replace: true },
    { type: 'done', answer: 'Resposta final.', sources: [{ id: 2 }], grounded: true, session_id: null },
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
  assert.deepEqual(messages[1].sources, [{ id: 2 }]);
  assert.notEqual(messages[1].content, '[object Object]');
  dom.window.close();
});

test('anonymous follow-up keeps an older explicit norm in bounded conversation context', async () => {
  const dom = new JSDOM(
    '<!doctype html><html><body><meta name="jurix-authenticated" content="false"></body></html>',
    { url: 'http://localhost/assistente/', runScripts: 'dangerously' },
  );
  const { window } = dom;
  window.TextDecoder = TextDecoder;
  window.eval(read('jurix-anonymous-history.js'));
  const sessionId = window.JurixAnonymousHistory.ensureSession('local-context-window', 'Conversa de teste');
  window.JurixAnonymousHistory.addMessage(sessionId, 'user', 'O que prevê a LC nº 120/2010?', []);
  for (let index = 0; index < 8; index += 1) {
    window.JurixAnonymousHistory.addMessage(sessionId, 'user', `E qual detalhe ${index + 1}?`, []);
    window.JurixAnonymousHistory.addMessage(sessionId, 'assistant', 'Resposta de QA.', []);
  }
  window.JurixAnonymousHistory.addMessage(sessionId, 'user', 'O que prevê o Art. 18 da LC nº 120/2010?', []);
  window.JurixAnonymousHistory.addMessage(sessionId, 'assistant', 'Resposta fundamentada.', []);
  window.JurixAnonymousHistory.updateLastAssistant(sessionId, 'Resposta fundamentada.', [{
    norma_ref: 'Lei Complementar nº 120/2010',
    dispositivo_ref: 'Art. 18',
  }], true);

  let sentPayload;
  const encoded = new TextEncoder().encode(`data: ${JSON.stringify({
    type: 'done', answer: 'Resposta curta.', grounded: false,
  })}\n\n`);
  let eventConsumed = false;
  window.fetch = async (_url, options) => {
    sentPayload = JSON.parse(options.body);
    return {
      ok: true,
      status: 200,
      body: { getReader: () => ({ async read() {
        if (eventConsumed) return { done: true, value: undefined };
        eventConsumed = true;
        return { done: false, value: encoded };
      } }) },
    };
  };
  window.eval(read('jurix-chat-api.js'));
  window.eval(read('jurix-api-reliability-overlay.js'));

  await window.JurixChatAPI.streamAnswer('E qual artigo trata do vencimento básico?', sessionId, {});

  assert.match(sentPayload.previous_question, /LC nº 120\/2010/);
  assert.match(sentPayload.previous_question, /Lei Complementar nº 120\/2010, Art\. 18º/);
  assert.ok(sentPayload.previous_question.length <= 10000);
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

test('legacy numeric anonymous session ids migrate to isolated local ids without losing old URLs', () => {
  const dom = new JSDOM('<!doctype html><html><body data-authenticated="false"></body></html>', {
    url: 'http://localhost/assistente/2/', runScripts: 'dangerously',
  });
  const { window: w } = dom;
  w.localStorage.setItem('jurix:anonymous-history:v2', JSON.stringify({
    schema: 2,
    sessions: [{
      id: '2', title: 'Conversa antiga', created_at: '2026-10-06T10:00:00.000Z',
      updated_at: '2026-10-06T10:00:00.000Z',
      messages: [{ role: 'user', content: 'Pergunta preservada' }],
    }],
  }));
  w.eval(read('jurix-anonymous-history.js'));

  const [listed] = w.JurixAnonymousHistory.list();
  assert.match(listed.id, /^local-/);
  assert.equal(listed.title, 'Pergunta preservada');
  assert.equal(w.JurixAnonymousHistory.get('2').messages[0].content, 'Pergunta preservada');
  assert.equal(w.JurixAnonymousHistory.ensureSession('2', 'Follow-up'), listed.id);
  assert.equal(w.JurixAnonymousHistory.list().length, 1);

  const persisted = JSON.parse(w.localStorage.getItem('jurix:anonymous-history:v2'));
  assert.equal(persisted.sessions[0].id, listed.id);
  assert.equal(persisted.sessions[0].legacy_id, '2');
  assert.equal(persisted.sessions[0].legacy_title, 'Conversa antiga');
  assert.equal(w.JurixAnonymousHistory.exportData().sessions[0].id, listed.id);
  assert.equal(Object.hasOwn(w.JurixAnonymousHistory.exportData().sessions[0], 'legacy_id'), false);
  dom.window.close();
});

test('SSE sources render immediately as pending and completion updates the same affordance', () => {
  const chat = read('chat.js');
  const sourceCallback = chat.indexOf('(sources, _confidence, sourceMetadata = {}) => {');
  const doneCallback = chat.indexOf('async (doneData) => {', sourceCallback);
  assert.ok(sourceCallback > 0 && doneCallback > sourceCallback);
  assert.match(chat.slice(sourceCallback, doneCallback), /showSourcesGradually\(/);
  assert.match(chat.slice(sourceCallback, doneCallback), /pending: true/);
  assert.match(chat, /Never rank-sort the rendered evidence/);
  const completion = chat.slice(doneCallback, doneCallback + 5000);
  assert.match(completion, /Array\.isArray\(doneData\.sources\) \? doneData\.sources : finalSources/);
  assert.match(completion, /finalSources\.length > 0[\s\S]*As fontes localizadas não foram suficientes para confirmar a resposta\.[\s\S]*Não localizei fontes correspondentes no acervo consultado\./);
  assert.match(completion, /showSourcesGradually\([\s\S]*answerSources[\s\S]*finalSourceMeta/);
  assert.match(completion, /source\?\.synthetic_fixture === true/);
  assert.match(completion, /Fixture sintética de QA/);
  assert.match(chat, /updateSourcesDrawerMetadata\?\.\(\{ pending: false \}\)/);
  assert.match(chat.slice(doneCallback), /reconcileSourcesDrawer\?\.\(/);
  const doneSessionUrl = chat.slice(chat.indexOf('const sessionUrl = `${config.chatbotUrl}${doneData.session_slug}/`;'));
  assert.match(doneSessionUrl, /document\.body\?\.dataset\.qaArchiveCorpus === 'true'[\s\S]*new URLSearchParams\(window\.location\.search\)\.get\('corpus'\) === 'archive-qa'/);
  assert.match(doneSessionUrl, /archiveQa \? `\$\{sessionUrl\}\?corpus=archive-qa` : sessionUrl/);
  assert.match(completion, /linkLegalReferences\(streamElements\.messageBody, answerSources\)/);
  assert.match(completion, /renderedCitationCount < expectedCitationCount/);
  assert.match(completion, /setCitationSources\(streamElements\.messageBody, answerSources\)/);
  assert.match(chat, /Never expose unverified model output/);
  const sourcePill = chat.slice(chat.indexOf('function showSourcesGradually'), chat.indexOf('function createSourceCard'));
  assert.match(sourcePill, /aria-label="Abrir painel com \$\{orderedSources\.length\} \$\{orderedSources\.length === 1 \? 'fonte consultada' : 'fontes consultadas'\}"/);
  assert.match(sourcePill, /Verificação em andamento/);
  assert.match(sourcePill, /Keep the trigger node stable/);
  assert.doesNotMatch(sourcePill, /topRawScore|Alta correspondência|Boa correspondência|Correspondência parcial/);

  const regeneration = chat.slice(chat.indexOf('async function regenerateLastResponse'), chat.indexOf('function copyResponseToClipboard'));
  assert.match(regeneration, /data\.grounded === true && Array\.isArray\(data\.sources\)/);
  assert.match(regeneration, /if \(answerSources\.length > 0\)/);

  const rag = read('jurix-rag.js');
  assert.match(rag, /window\.scrollToBottomIfAtBottom\(\)/);
});

test('cancelling a stream marks already retrieved sources as unvalidated, not answer support', () => {
  const chat = read('chat.js');
  const cancelHandler = chat.slice(
    chat.indexOf("sendButton.addEventListener('click'"),
    chat.indexOf("chatForm.addEventListener('submit'"),
  );
  assert.match(cancelHandler, /markStreamEvidenceCancelled\(elements\)/);
  assert.match(cancelHandler, /if \(state\?\.status !== 'streaming'\) return/);
  assert.match(chat, /if \(status === 'finalizing'\)\s*\{\s*chatState\?\.transition\?\.\('finalizing', \{ question \}\)/);
  const cancelledPresentation = chat.slice(
    chat.indexOf('function markStreamEvidenceCancelled'),
    chat.indexOf('function appendNormLookupActions'),
  );
  assert.match(cancelledPresentation, /Não validadas — geração cancelada/);
  assert.match(cancelledPresentation, /pending: false,\s*cancelled: true/);
  assert.match(cancelledPresentation, /updateSourcesDrawerMetadata\?\.\(\{\s*pending: false,\s*cancelled: true/);
  assert.match(cancelledPresentation, /copyButton\?\.classList\.remove\('show'\)/);
  assert.match(chat, /if \(streamElements\?\.cancelledByUser\) return;/);
  assert.match(chat, /if \(streamElements\?\.cancelledByUser\) \{\s*markStreamEvidenceCancelled\(streamElements\);/);
  const rag = read('jurix-rag.js');
  assert.match(rag, /A geração foi interrompida; estas fontes não foram validadas como suporte da resposta/);
});

test('interrupted-turn retry remains visible without a completed-answer action', () => {
  const styles = fs.readFileSync(
    path.resolve(import.meta.dirname, '../../src/apps/core/static/css/jurix-chat-renderer.css'),
    'utf8',
  );
  assert.match(styles, /\.message-actions:not\(:has\(\.show\)\):not\(:has\(\.jurix-interrupted-retry\)\)\s*\{\s*display:\s*none;/);
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

test('copy preserves structured citation markers as Markdown links to official evidence', async () => {
  const dom = new JSDOM('<!doctype html><html><body><article class="message"><div class="message-body"></div><button class="copy-response-button"><svg class="copy-icon"></svg><svg class="check-icon"></svg></button></article><article class="message"><div class="message-body"><a class="jurix-legal-reference-link" href="https://sapl.natal.rn.leg.br/norma/normajuridica/94/">Lei nº 8.206/2026, Art. 2º</a></div><button class="copy-response-button"><svg class="copy-icon"></svg><svg class="check-icon"></svg></button></article></body></html>', {
    url: 'http://localhost/assistente/', runScripts: 'dangerously', pretendToBeVisual: true,
  });
  const { window: w } = dom;
  let copiedText = '';
  w.document.execCommand = () => {
    copiedText = w.document.querySelector('.jurix-clipboard-fallback')?.value || '';
    return true;
  };
  w.JurixRagUI = { buildSourceUrl: () => 'https://sapl.natal.rn.leg.br/norma/normajuridica/93/' };
  w.eval(read('jurix-chat-renderer.js'));
  const button = w.document.querySelector('.copy-response-button');
  button.closest('.message').querySelector('.message-body')._citationSources = [{
    citation_index: 1, citation_label: 'Lei nº 8.206/2026, Art. 1º',
  }];
  button.closest('.message').querySelector('.message-body').innerHTML = '<a class="jurix-legal-reference-link" href="https://sapl.natal.rn.leg.br/norma/normajuridica/93/">Lei nº 8.206/2026, Art. 1º</a>';
  await w.JurixChatRenderer.copyResponseToClipboard(
    'A norma institui o programa [[1]] e também se refere à Lei nº 8.206/2026, Art. 1º.',
    button
  );
  assert.equal(
    copiedText,
    'A norma institui o programa [Lei nº 8.206/2026, Art. 1º](<https://sapl.natal.rn.leg.br/norma/normajuridica/93/>) e também se refere à [Lei nº 8.206/2026, Art. 1º](<https://sapl.natal.rn.leg.br/norma/normajuridica/93/>).'
  );
  const secondButton = w.document.querySelectorAll('.copy-response-button')[1];
  await w.JurixChatRenderer.copyResponseToClipboard('Conforme Lei nº 8.206/2026, Art. 2º.', secondButton);
  assert.equal(
    copiedText,
    'Conforme [Lei nº 8.206/2026, Art. 2º](<https://sapl.natal.rn.leg.br/norma/normajuridica/94/>).'
  );
  w.close();
});

test('copy keeps multi-article citations as separate non-nested Markdown links', async () => {
  const dom = new JSDOM(
    '<!doctype html><html><body><article class="message"><div class="message-body">' +
      '<a class="jurix-legal-reference-link" href="https://local.test/norma/120/">Lei Complementar nº 120/2010</a>' +
      '<a class="jurix-legal-reference-link" href="https://local.test/norma/120/#:~:text=Art.17">Art. 17</a>' +
      '<a class="jurix-legal-reference-link" href="https://local.test/norma/120/#:~:text=Art.18">Art. 18</a>' +
      '</div><button class="copy-response-button"></button></article></body></html>',
    { url: 'http://localhost/assistente/', runScripts: 'dangerously', pretendToBeVisual: true },
  );
  const { window: w } = dom;
  let copiedText = '';
  w.document.execCommand = () => {
    copiedText = w.document.querySelector('.jurix-clipboard-fallback')?.value || '';
    return true;
  };
  w.JurixRagUI = { buildSourceUrl: (source) => source.official_url };
  w.eval(read('jurix-chat-renderer.js'));
  const button = w.document.querySelector('.copy-response-button');
  button._citationSources = [
    {
      citation_index: 1,
      citation_label: 'Lei Complementar nº 120/2010, Art. 17',
      official_url: 'https://local.test/norma/120/#:~:text=Art.17',
    },
    {
      citation_index: 2,
      citation_label: 'Lei Complementar nº 120/2010, Art. 18',
      official_url: 'https://local.test/norma/120/#:~:text=Art.18',
    },
  ];
  const copied = await w.JurixChatRenderer.copyResponseToClipboard(
    'Nos trechos de Lei Complementar nº 120/2010, os dispositivos dizem:\n\n' +
      '- Art. 17: atribuições no Anexo III [[1]]\n' +
      '- Art. 18: vencimento mínimo [[2]]',
    button,
  );

  assert.equal(copied, true);
  assert.match(copiedText, /\[Lei Complementar nº 120\/2010\]\(<https:\/\/local\.test\/norma\/120\/>\)/);
  assert.match(copiedText, /\[Lei Complementar nº 120\/2010, Art\. 17\]\(<https:\/\/local\.test\/norma\/120\/#:~:text=Art\.17>\)/);
  assert.match(copiedText, /\[Lei Complementar nº 120\/2010, Art\. 18\]\(<https:\/\/local\.test\/norma\/120\/#:~:text=Art\.18>\)/);
  assert.doesNotMatch(copiedText, /\]\(<[^>]+>\)\s*,\s*\[/);
  assert.equal((copiedText.match(/\]\(<https:\/\/local\.test\/norma\/120\//g) || []).length, 5);
  w.close();
});

test('Markdown citation markers render using readable labels from structured sources', () => {
  const dom = new JSDOM('<!doctype html><html><body></body></html>', {
    url: 'http://localhost/assistente/', runScripts: 'dangerously',
  });
  const { window: w } = dom;
  w.eval(read('jurix-markdown.js'));
  const html = w.JurixMarkdown.normalize('A regra consta em [[1]].', [{
    citation_index: 1, citation_id: 'jurix:norma:3:dispositivo:12', citation_label: 'Lei nº 8.206/2026, Art. 1º',
  }]);
  assert.match(html, /href="#jurix-evidence-1"/);
  assert.match(html, /data-citation-id="jurix:norma:3:dispositivo:12"/);
  assert.match(html, />\[1\]<\/a>/);
  assert.match(html, /aria-label="Ver Lei nº 8\.206\/2026, Art\. 1º"/);
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

test('an open source drawer reconciles to terminal citations and restores focus to its original trigger', () => {
  const dom = new JSDOM('<!doctype html><html><body><button id="open-sources">Ver fontes</button></body></html>', {
    url: 'http://localhost/assistente/',
    runScripts: 'dangerously',
    pretendToBeVisual: true,
  });
  const { window: w } = dom;
  w.eval(read('jurix-rag.js'));
  const trigger = w.document.getElementById('open-sources');
  trigger.focus();
  w.JurixRagUI.openSourcesDrawer([
    { norma: 'Lei nº 1/2020', dispositivo_ref: 'Art. 1º', text: 'Recuperado, não citado.' },
    { norma: 'Lei nº 2/2020', dispositivo_ref: 'Art. 2º', text: 'Citado e fundamentado.' },
  ]);

  w.JurixRagUI.reconcileSourcesDrawer([
    { norma: 'Lei nº 2/2020', dispositivo_ref: 'Art. 2º', text: 'Citado e fundamentado.' },
  ], 'Fontes Consultadas', { pending: false });
  const panel = w.document.getElementById('jurix-sources-drawer-panel');
  assert.equal(panel.querySelectorAll('.source-card').length, 1);
  assert.match(panel.textContent, /Citado e fundamentado/);
  assert.doesNotMatch(panel.textContent, /Recuperado, não citado/);
  w.JurixRagUI.closeSourcesDrawer();
  assert.equal(w.document.activeElement, trigger);
  dom.window.close();
});

test('source drawer labels QA evidence and omits article coverage when counts are absent', () => {
  const dom = new JSDOM('<!doctype html><html><body></body></html>', {
    url: 'http://localhost/assistente/',
    runScripts: 'dangerously',
    pretendToBeVisual: true,
  });
  const { window: w } = dom;
  w.eval(read('jurix-rag.js'));
  w.JurixRagUI.openSourcesDrawer(
    [{ norma: 'Lei nº 6.021/2009', dispositivo_ref: 'Art. 1º', text: 'Trecho de teste.' }],
    'Fontes Consultadas',
    { coverage: { corpus: 'acervo histórico local (lote de 40 documentos)', sources_retrieved: 1 } },
  );

  const subtitle = w.document.querySelector('#sources-drawer-subtitle')?.textContent || '';
  assert.match(subtitle, /acervo histórico local/);
  assert.match(subtitle, /extração e os metadados ainda estão sob revisão/);
  assert.doesNotMatch(subtitle, /undefined|Amostra distribuída/);

  w.JurixRagUI.closeSourcesDrawer();
  dom.window.close();
});

test('source drawer keeps QA warning when restored sources lack stream metadata', () => {
  const dom = new JSDOM('<!doctype html><html><body></body></html>', {
    url: 'http://localhost/assistente/',
    runScripts: 'dangerously',
    pretendToBeVisual: true,
  });
  const { window: w } = dom;
  w.eval(read('jurix-rag.js'));
  w.JurixRagUI.openSourcesDrawer([
    {
      norma: 'Lei nº 6.021/2009',
      dispositivo_ref: 'Art. 1º',
      text: 'Trecho de teste.',
      evidence_scope: 'isolated_qa_archive',
      source_type: 'Acervo histórico local — extração pendente de revisão',
    },
  ]);

  const subtitle = w.document.querySelector('#sources-drawer-subtitle')?.textContent || '';
  assert.match(subtitle, /acervo histórico local/);
  assert.match(subtitle, /extração e os metadados ainda estão sob revisão/);
  assert.doesNotMatch(subtitle, /corpus municipal de Natal/);

  w.JurixRagUI.closeSourcesDrawer();
  dom.window.close();
});

test('unreviewed archive evidence does not present retrieval score as legal confidence', () => {
  const dom = new JSDOM('<!doctype html><html><body></body></html>', {
    url: 'http://localhost/assistente/',
    runScripts: 'dangerously',
  });
  const { window: w } = dom;
  w.eval(read('jurix-rag.js'));
  const holder = w.document.createElement('div');
  holder.innerHTML = w.JurixRagUI.renderEvidenceCard({
    norma: 'Lei Complementar nº 120/2010',
    dispositivo_ref: 'Art. 17',
    text: 'Trecho extraído do PDF.',
    evidence_scope: 'isolated_qa_archive',
    source_type: 'Acervo histórico local — extração pendente de revisão',
    similarity_score: 1,
  });

  assert.match(holder.textContent, /Trecho recuperado/);
  assert.match(holder.textContent, /extração pendente de revisão/);
  assert.doesNotMatch(holder.innerHTML, /100%|Alta correspondência|Pontuação técnica/);
  assert.equal(holder.querySelector('.jurix-rag-score-meter'), null);
  dom.window.close();
});

test('source drawer clearly identifies synthetic legal fixtures and never calls them municipal corpus', () => {
  const dom = new JSDOM('<!doctype html><html><body></body></html>', {
    url: 'http://localhost/assistente/',
    runScripts: 'dangerously',
    pretendToBeVisual: true,
  });
  const { window: w } = dom;
  w.eval(read('jurix-rag.js'));
  w.JurixRagUI.openSourcesDrawer([
    {
      norma_ref: 'Lei nº 9.001/2020',
      dispositivo_ref: 'Art. 1º',
      text: 'Fixture de teste.',
      synthetic_fixture: true,
      source_type: 'Fixture sintética de QA — não representa legislação real',
    },
  ]);

  const subtitle = w.document.querySelector('#sources-drawer-subtitle')?.textContent || '';
  assert.match(subtitle, /fixtures sintéticas de QA/);
  assert.match(subtitle, /não representam normas reais/);
  assert.doesNotMatch(subtitle, /corpus municipal de Natal/);
  const card = w.JurixRagUI.renderEvidenceCard({
    norma_ref: 'Lei nº 9.001/2020',
    dispositivo_ref: 'Art. 1º',
    synthetic_fixture: true,
    source_type: 'Fixture sintética de QA — não representa legislação real',
  });
  assert.match(card, /Fixture sintética de QA/);
  assert.match(card, /não representa legislação real/);

  w.JurixRagUI.closeSourcesDrawer();
  dom.window.close();
});

test('source drawer reports a sampled whole-norm count only when both counts are available', () => {
  const dom = new JSDOM('<!doctype html><html><body></body></html>', {
    url: 'http://localhost/assistente/',
    runScripts: 'dangerously',
    pretendToBeVisual: true,
  });
  const { window: w } = dom;
  w.eval(read('jurix-rag.js'));
  w.JurixRagUI.openSourcesDrawer(
    [{ norma: 'Lei nº 9.001/2020', dispositivo_ref: 'Art. 1º', text: 'Trecho de teste.' }],
    'Fontes Consultadas',
    { coverage: { complete: false, selected_articles: 3, total_articles: 8 } },
  );

  const subtitle = w.document.querySelector('#sources-drawer-subtitle')?.textContent || '';
  assert.match(subtitle, /Amostra distribuída: 3 de 8 artigos/);

  w.JurixRagUI.closeSourcesDrawer();
  dom.window.close();
});

test('whole-norm evidence is shown as coverage, not as a fabricated similarity score', () => {
  const dom = new JSDOM('<!doctype html><html><body></body></html>', {
    url: 'http://localhost/assistente/', runScripts: 'dangerously',
  });
  const { window: w } = dom;
  w.eval(read('jurix-rag.js'));
  const holder = w.document.createElement('div');
  holder.innerHTML = w.JurixRagUI.renderEvidenceCard({
    norma_ref: 'Lei nº 8.206/2026',
    dispositivo_ref: 'Art. 1º',
    retrieval_strategy: 'whole_norma',
    evidence_scope: 'sampled',
    similarity_score: 0,
  }, 0);
  assert.match(holder.textContent, /Amostra da norma/);
  assert.doesNotMatch(holder.innerHTML, /jurix-rag-score-meter|Baixa correspondência/);
  w.close();
});

test('an exact normative reference is labeled without presenting similarity as confidence', () => {
  const dom = new JSDOM('<!doctype html><html><body></body></html>', {
    url: 'http://localhost/assistente/', runScripts: 'dangerously',
  });
  const { window: w } = dom;
  w.eval(read('jurix-rag.js'));
  const holder = w.document.createElement('div');
  holder.innerHTML = w.JurixRagUI.renderEvidenceCard({
    norma_ref: 'Lei nº 8.206/2026',
    dispositivo_ref: 'Art. 1º',
    match_kind: 'explicit_reference',
    similarity_score: 0,
  }, 0);

  assert.match(holder.textContent, /Dispositivo identificado/);
  assert.doesNotMatch(holder.innerHTML, /jurix-rag-score-meter|correspondência|\b0%/i);
  w.close();
});

test('graph-linked evidence is labeled as a normative relation, not low semantic relevance', () => {
  const dom = new JSDOM('<!doctype html><html><body></body></html>', {
    url: 'http://localhost/assistente/', runScripts: 'dangerously',
  });
  const { window: w } = dom;
  w.eval(read('jurix-rag.js'));
  const holder = w.document.createElement('div');
  holder.innerHTML = w.JurixRagUI.renderEvidenceCard({
    norma_ref: 'Lei nº 9.002/2021',
    dispositivo_ref: 'Art. 1º',
    evidence_scope: 'relation_context',
    similarity_score: 0,
    graph_relation: { label: 'relação normativa alteracao' },
  }, 0);

  assert.match(holder.textContent, /Relação normativa/);
  assert.match(holder.textContent, /relação normativa alteracao/);
  assert.match(holder.innerHTML, /jurix-rag-source--relation/);
  assert.doesNotMatch(holder.innerHTML, /jurix-rag-score-meter|Baixa correspondência|Pontuação técnica/);
  w.close();
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

test('archive QA corpus scope survives anonymous history and conversation reload links', async () => {
  const w = guestWindow(null, [{ type: 'done', answer: 'Resposta do arquivo.', grounded: false }]);
  try {
    let id;
    await w.JurixChatAPI.streamAnswer('Pergunta sobre PDF local', null, {
      searchOptions: { qa_archive_corpus: true },
      onDone: data => { id = data.session_id; },
    });
    const session = w.JurixAnonymousHistory.get(id);
    assert.equal(session.corpus, 'archive-qa');
    assert.equal(w.JurixAnonymousHistory.list()[0].corpus, 'archive-qa');
    assert.equal(w.JurixAnonymousHistory.exportData().sessions[0].corpus, 'archive-qa');

    const reload = guestWindow(w.localStorage.getItem('jurix:anonymous-history:v2'));
    try {
      const restored = await reload.JurixChatAPI.getSessionBySlug(id);
      assert.equal(restored.session.corpus, 'archive-qa');
      reload.document.body.innerHTML = '<form data-history-search><input name="q"></form><section data-anonymous-history></section>';
      reload.eval(read('jurix-anonymous-history-page.js'));
      assert.equal(
        reload.document.querySelector('.workspace-history-card__link')?.getAttribute('href'),
        `/assistente/${encodeURIComponent(id)}/?corpus=archive-qa`,
      );
    } finally { reload.close(); }
  } finally { w.close(); }
});

test('legacy anonymous sessions with a grounded local PDF source restore the archive corpus link', () => {
  const w = guestWindow();
  try {
    const id = w.JurixAnonymousHistory.ensureSession('local-legacy-pdf', 'Lei Complementar 120');
    w.JurixAnonymousHistory.addMessage(id, 'user', 'Art. 18 da LC 120/2010', []);
    w.JurixAnonymousHistory.updateLastAssistant(id, 'Resposta fundamentada [[1]]', [{
      id: 'evidence-1',
      local_pdf_url: '/normas/documentos/f4a5c8f6-7ca2-4b5c-935e-033572a33510/pdf/',
    }], true);
    assert.equal(w.JurixAnonymousHistory.list()[0].corpus, 'archive-qa');
    assert.equal(w.JurixAnonymousHistory.get(id).corpus, 'archive-qa');
    assert.equal(w.JurixAnonymousHistory.exportData().sessions[0].corpus, 'archive-qa');
    w.document.body.innerHTML = '<form data-history-search><input name="q"></form><section data-anonymous-history></section>';
    w.eval(read('jurix-anonymous-history-page.js'));
    assert.equal(
      w.document.querySelector('.workspace-history-card__link')?.getAttribute('href'),
      `/assistente/${encodeURIComponent(id)}/?corpus=archive-qa`,
    );
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

test('anonymous history renders a clean distinct preview and supports confirmed local deletion', async () => {
  const dom = new JSDOM('<!doctype html><html><body><form data-history-search><input name="q"></form><section data-anonymous-history></section></body></html>', {
    url: 'http://localhost/historico/', runScripts: 'dangerously', pretendToBeVisual: true,
  });
  const { window } = dom;
  const sessions = [
    { id: 'local-a', title: 'Educação popular', corpus: 'archive-qa', updated_at: '2026-10-01T12:00:00Z', messages_count: 2 },
    { id: 'local-b', title: 'Normas municipais', updated_at: '2026-10-01T11:00:00Z', messages_count: 1 },
  ];
  const details = {
    'local-a': { messages: [
      { role: 'user', content: 'Educação popular' },
      { role: 'assistant', content: '### Educação popular\n\nA **Lei nº 8205/2026** institui [a data](https://sapl.invalid).' },
    ] },
    'local-b': { messages: [{ role: 'user', content: 'Lei municipal' }] },
  };
  window.JurixAnonymousHistory = {
    list: () => sessions,
    get: id => details[id],
    remove: id => { sessions.splice(sessions.findIndex(session => session.id === id), 1); return true; },
  };
  let authenticatedDeleteCalls = 0;
  window.JurixChatAPI = { deleteSession: async () => { authenticatedDeleteCalls += 1; throw new Error('local id must never call authenticated API'); } };
  window.eval(read('jurix-anonymous-history-page.js'));
  const card = window.document.querySelector('[data-history-card][data-session-id="local-a"]');
  assert.ok(card);
  assert.equal(card.querySelector('h2').textContent, 'Educação popular');
  assert.equal(card.querySelector('p').textContent, 'A Lei nº 8205/2026 institui a data.');
  assert.equal(card.querySelector('.workspace-history-card__link').getAttribute('href'), '/assistente/local-a/?corpus=archive-qa');
  assert.equal(card.querySelector('a').contains(card.querySelector('[data-history-delete]')), false);

  window.requestAnimationFrame = callback => callback();
  window.eval(read('jurix-history-actions.js'));
  card.querySelector('[data-history-delete]').click();
  assert.ok(window.document.querySelector('[role="dialog"]'));
  window.document.querySelector('[data-history-confirm]').click();
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(window.document.querySelector('[data-session-id="local-a"]'), null);
  assert.ok(window.document.querySelector('[data-session-id="local-b"]'));
  assert.deepEqual(sessions.map(session => session.id), ['local-b']);
  assert.equal(authenticatedDeleteCalls, 0);
  dom.window.close();
});

test('anonymous history export uses an allowlist and clear reports persistence status', () => {
  const dom = new JSDOM('<!doctype html><html><body data-authenticated="false"></body></html>', {
    url: 'http://localhost/assistente/', runScripts: 'dangerously',
  });
  const { window } = dom;
  window.eval(read('jurix-anonymous-history.js'));
  const sessionId = window.JurixAnonymousHistory.ensureSession(null, 'Pergunta');
  window.JurixAnonymousHistory.addMessage(sessionId, 'user', 'Pergunta', []);
  window.JurixAnonymousHistory.addMessage(sessionId, 'assistant', 'Resposta', [{
    norma_ref: 'Lei nº 1/2026', text: 'Trecho', citation_id: 'jurix:norma:1:dispositivo:2',
    citation_index: 1, citation_label: 'Lei nº 1/2026, Art. 1º', api_key: 'must-not-export', provider_secret: 'must-not-export',
  }]);
  // Only explicitly grounded assistant sources belong in a user export.
  window.JurixAnonymousHistory.updateLastAssistant(sessionId, 'Resposta fundamentada', [{
    norma_ref: 'Lei nº 1/2026', text: 'Trecho', citation_id: 'jurix:norma:1:dispositivo:2',
    citation_index: 1, citation_label: 'Lei nº 1/2026, Art. 1º', api_key: 'must-not-export', provider_secret: 'must-not-export',
  }], true);
  const exported = window.JurixAnonymousHistory.exportData();
  const serialized = JSON.stringify(exported);
  assert.equal(exported.schema, 'jurix-anonymous-history-export/v1');
  assert.equal(exported.sessions.length, 1);
  assert.match(serialized, /Lei nº 1\/2026/);
  assert.match(serialized, /jurix:norma:1:dispositivo:2/);
  assert.match(serialized, /citation_index/);
  assert.doesNotMatch(serialized, /must-not-export|api_key|provider_secret/);
  assert.equal(window.JurixAnonymousHistory.clear(), true);
  assert.equal(window.JurixAnonymousHistory.list().length, 0);
  dom.window.close();
});

test('history search stays inline on desktop and anonymous result cards use the shared card interior', () => {
  const template = readTemplate('history.html');
  const renderer = read('jurix-anonymous-history-page.js');
  assert.match(template, /class="workspace-field" for="history-query"/);
  assert.doesNotMatch(template, /class="workspace-field workspace-field-wide" for="history-query"/);
  assert.match(renderer, /class="workspace-history-card__surface"><a class="workspace-history-card__link"/);
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
    new TextEncoder().encode('data: {"type":"sources","sources":[{"citation_index":1}],"retrieval_strategy":"whole_norma"}\r\n\r\n'),
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
  let sourceEvent;
  await window.JurixChatAPI.streamAnswer('Pergunta', null, {
    onChunk: (chunk, metadata) => { received.push(chunk); provisionalStates.push(metadata.provisional); },
    onSources: (sources, confidence, metadata) => { sourceEvent = { sources, confidence, metadata }; },
    onDone: (event) => { done = event.answer; },
    onTitle: (event) => { title = event.title; },
  });
  assert.deepEqual(received, ['Resposta']);
  assert.deepEqual(provisionalStates, [true]);
  assert.equal(sourceEvent.metadata.retrieval_strategy, 'whole_norma');
  assert.equal(sourceEvent.sources[0].citation_index, 1);
  assert.equal(done, 'Resposta final.');
  assert.equal(title, 'Pesquisa jurídica');
  dom.window.close();
});

test('stream retries get a new turn UUID linked to the previous failed attempt', async () => {
  const dom = new JSDOM('<!doctype html><html><body></body></html>', {
    url: 'http://localhost/assistente/', runScripts: 'dangerously',
  });
  const { window } = dom;
  window.TextDecoder = TextDecoder;
  const requests = [];
  let first = true;
  window.fetch = async (_url, options) => {
    requests.push(JSON.parse(options.body));
    if (first) {
      first = false;
      return { ok: false, status: 503, body: null };
    }
    const bytes = new TextEncoder().encode('data: {"type":"done","answer":"Resposta"}\n\n');
    let consumed = false;
    return {
      ok: true,
      status: 200,
      body: { getReader: () => ({ read: async () => consumed ? { done: true } : (consumed = true, { done: false, value: bytes }) }) },
    };
  };
  window.eval(read('jurix-chat-api.js'));
  await assert.rejects(window.JurixChatAPI.streamAnswer('Pergunta original', 12, {}), /HTTP 503/);
  await window.JurixChatAPI.streamAnswer('Pergunta original', 12, { retryExistingQuestion: true });

  const [initial, retry] = requests;
  assert.match(initial.client_session_id, /^[0-9a-f-]{36}$/i);
  assert.match(initial.client_turn_id, /^[0-9a-f-]{36}$/i);
  assert.match(retry.client_turn_id, /^[0-9a-f-]{36}$/i);
  assert.notEqual(retry.client_turn_id, initial.client_turn_id);
  assert.equal(retry.retry_of_client_turn_id, initial.client_turn_id);
  assert.equal(retry.client_session_id, initial.client_session_id);
  dom.window.close();
});

test('stream serializes numeric session ids from restored conversation URLs as numbers', async () => {
  const dom = new JSDOM('<!doctype html><html><body></body></html>', {
    url: 'http://localhost/assistente/', runScripts: 'dangerously',
  });
  const { window } = dom;
  window.TextDecoder = TextDecoder;
  let sentPayload;
  const bytes = new TextEncoder().encode('data: {"type":"done","answer":"Resposta"}\n\n');
  let consumed = false;
  window.fetch = async (_url, options) => {
    sentPayload = JSON.parse(options.body);
    return {
      ok: true,
      status: 200,
      body: { getReader: () => ({ read: async () => consumed ? { done: true } : (consumed = true, { done: false, value: bytes }) }) },
    };
  };
  window.eval(read('jurix-chat-api.js'));

  await window.JurixChatAPI.streamAnswer('Pergunta', '2', {
    searchOptions: { session_id: 'local-stale-session-id' },
  });

  assert.equal(sentPayload.session_id, 2);
  assert.equal(typeof sentPayload.session_id, 'number');
  dom.window.close();
});

test('chat controller exposes an enabled and accessible Stop action only while generating', () => {
  const dom = new JSDOM('<!doctype html><html><body><form id="chat-form"><textarea id="question-textarea"></textarea><button id="send-button" type="submit">send</button></form><div id="chat-state-indicator" hidden></div><div id="conversation-input-bar"></div></body></html>', {
    url: 'http://localhost/assistente/', runScripts: 'dangerously', pretendToBeVisual: true,
  });
  const { window } = dom;
  let waitCallback = null;
  let intervalCallback = null;
  let requestedDelay = null;
  let now = 1000;
  window.Date.now = () => now;
  window.setTimeout = (callback, delay) => { waitCallback = callback; requestedDelay = delay; return 1; };
  window.clearTimeout = () => {};
  window.setInterval = (callback) => { intervalCallback = callback; return 2; };
  window.clearInterval = () => {};
  window.eval(read('jurix-chat-state.js'));
  window.eval(read('jurix-chat-controller.js'));
  window.document.dispatchEvent(new window.Event('DOMContentLoaded'));
  const input = window.document.getElementById('question-textarea');
  const button = window.document.getElementById('send-button');
  input.value = 'Pergunta';
  input.dispatchEvent(new window.Event('input', { bubbles: true }));

  window.JurixChatState.transition('submitting');
  assert.equal(requestedDelay, 10000, 'the wait clock starts only after ten seconds');
  assert.equal(button.disabled, true, 'button is not a stop control before a stream can be aborted');
  window.JurixChatState.transition('streaming');
  assert.equal(button.disabled, false);
  assert.equal(button.getAttribute('aria-label'), 'Parar geração');
  assert.equal(button.dataset.action, 'stop');
  assert.match(button.innerHTML, /<rect/);

  window.JurixChatController.setPipelineStatus('retrieving');
  assert.equal(window.document.querySelector('.jurix-chat-state-label').textContent, 'Buscando normas relevantes…');
  now = 11000;
  waitCallback();
  assert.equal(window.document.querySelector('.jurix-chat-state-elapsed').textContent, '· 10 s');
  assert.equal(window.document.querySelector('.jurix-chat-state-elapsed').getAttribute('aria-hidden'), 'true');
  now = 14000;
  intervalCallback();
  assert.equal(window.document.querySelector('.jurix-chat-state-elapsed').textContent, '· 13 s');
  window.JurixChatController.setPipelineStatus('grounding');
  assert.equal(window.document.querySelector('.jurix-chat-state-label').textContent, 'Conferindo as referências…');

  window.JurixChatState.transition('finalizing');
  assert.equal(button.disabled, true, 'the stop action is unavailable after the stream enters finalization');
  assert.equal(button.getAttribute('aria-label'), 'Pesquisa em andamento');
  assert.equal(button.dataset.action, 'send');

  window.JurixChatState.transition('cancelled');
  assert.equal(button.getAttribute('aria-label'), 'Enviar pergunta');
  assert.equal(button.dataset.action, 'send');
  assert.equal(window.document.querySelector('.jurix-chat-state-elapsed').textContent, '');
  dom.window.close();
});

test('restored interrupted authenticated question exposes one explicit retry action', () => {
  const dom = new JSDOM('<!doctype html><html><body><div id="messages-wrapper"></div></body></html>', {
    url: 'http://localhost/assistente/', runScripts: 'dangerously', pretendToBeVisual: true,
  });
  const { window } = dom;
  window.eval(read('jurix-chat-renderer.js'));
  let retried = null;
  const message = window.JurixChatRenderer.addUserMessage('Pergunta ainda não respondida', {
    retryContext: { state: 'interrupted', clientTurnId: '81a3119b-0fb4-42f8-b1ef-d1890563cb38' },
    onRetry: (...args) => { retried = args; },
  });
  const retry = message.querySelector('.jurix-interrupted-retry');
  assert.ok(retry);
  retry.click();
  assert.deepEqual(retried, ['Pergunta ainda não respondida', '81a3119b-0fb4-42f8-b1ef-d1890563cb38']);
  assert.equal(window.document.querySelectorAll('.jurix-interrupted-retry').length, 1);
  dom.window.close();
});

test('pending assistant answer gives accessible progress feedback and clears without retaining draft text', () => {
  const dom = new JSDOM('<!doctype html><html><body><div id="messages-wrapper"><div id="answer" class="message-body"></div></div></body></html>', {
    url: 'http://localhost/assistente/', runScripts: 'dangerously',
  });
  const { window } = dom;
  window.eval(read('jurix-chat-renderer.js'));
  const body = window.document.getElementById('answer');
  const pending = window.JurixChatRenderer.showPendingAnswer(body);
  assert.equal(pending.getAttribute('role'), 'status');
  assert.equal(pending.getAttribute('aria-live'), 'polite');
  assert.match(pending.textContent, /Organizando as evidências/);
  assert.equal(body.querySelectorAll('.jurix-answer-pending').length, 1);

  window.JurixChatRenderer.clearPendingAnswer(pending);
  assert.equal(body.textContent, '');
  assert.equal(body.querySelector('.jurix-answer-pending'), null);
  dom.window.close();
});

test('stream cancellation requests server cancellation before aborting the local reader', async () => {
  const dom = new JSDOM('<!doctype html><html><body></body></html>', {
    url: 'http://localhost/assistente/', runScripts: 'dangerously',
  });
  const { window } = dom;
  window.TextDecoder = TextDecoder;
  let rejectRead;
  const events = [];
  let cancelPayload = null;
  window.fetch = async (url, options) => {
    if (url === '/api/v1/search/cancel/') {
      events.push('server-cancel');
      cancelPayload = JSON.parse(options.body);
      return { ok: true, json: async () => ({ success: true, cancelled: true }) };
    }
    options.signal.addEventListener('abort', () => {
      events.push('local-abort');
      const error = new Error('aborted');
      error.name = 'AbortError';
      rejectRead(error);
    }, { once: true });
    const encoder = new TextEncoder();
    let sentStatus = false;
    return {
      ok: true,
      status: 200,
      body: { getReader: () => ({ read: () => {
        if (!sentStatus) {
          sentStatus = true;
          return Promise.resolve({
            done: false,
            value: encoder.encode('data: {"type":"status","status":"queued","cancel_token":"signed-turn-token"}\n\n'),
          });
        }
        return new Promise((_resolve, reject) => { rejectRead = reject; });
      } }) },
    };
  };
  window.eval(read('jurix-chat-api.js'));
  let failureCallbacks = 0;
  const pending = window.JurixChatAPI.streamAnswer('Pergunta', null, {
    onError: () => { failureCallbacks += 1; },
  });
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(window.JurixChatAPI.cancelStream(), true);
  await assert.rejects(pending, { name: 'AbortError' });
  assert.equal(failureCallbacks, 0);
  assert.deepEqual(cancelPayload, { cancel_token: 'signed-turn-token' });
  assert.deepEqual(events, ['server-cancel', 'local-abort']);
  assert.equal(window.JurixChatAPI.cancelStream(), false);
  dom.window.close();
});

test('a generation already finalizing wins the cancellation race and is allowed to complete', async () => {
  const dom = new JSDOM('<!doctype html><html><body></body></html>', {
    url: 'http://localhost/assistente/', runScripts: 'dangerously',
  });
  const { window } = dom;
  window.TextDecoder = TextDecoder;
  let resolveRead;
  let aborted = false;
  let readCount = 0;
  const encoder = new TextEncoder();
  window.fetch = async (url, options) => {
    if (url === '/api/v1/search/cancel/') {
      return { ok: true, json: async () => ({ success: true, state: 'finalizing' }) };
    }
    options.signal.addEventListener('abort', () => { aborted = true; }, { once: true });
    return {
      ok: true,
      status: 200,
      body: { getReader: () => ({ read: () => {
        readCount += 1;
        if (readCount === 1) {
          return Promise.resolve({
            done: false,
            value: encoder.encode('data: {"type":"status","status":"queued","cancel_token":"signed-turn-token"}\n\n'),
          });
        }
        if (readCount > 2) return Promise.resolve({ done: true });
        return new Promise((resolve) => { resolveRead = resolve; });
      } }) },
    };
  };
  window.eval(read('jurix-chat-api.js'));
  let finalAnswer = null;
  const pending = window.JurixChatAPI.streamAnswer('Pergunta', null, {
    onDone: (event) => { finalAnswer = event.answer; },
  });
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(window.JurixChatAPI.cancelStream(), true);
  await new Promise((resolve) => setImmediate(resolve));
  resolveRead({
    done: false,
    value: encoder.encode('data: {"type":"done","answer":"Resposta concluída."}\n\n'),
  });
  await pending;
  assert.equal(finalAnswer, 'Resposta concluída.');
  assert.equal(aborted, false);
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
