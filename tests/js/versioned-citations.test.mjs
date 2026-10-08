import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { JSDOM } from 'jsdom';

const JS_DIR = path.resolve(import.meta.dirname, '../../src/apps/core/static/js');
const read = (file) => fs.readFileSync(path.join(JS_DIR, file), 'utf8');

function boot() {
  const dom = new JSDOM(
    '<!doctype html><html><body><div class="message"><div class="message-body"></div><button class="copy-response-button"></button></div></body></html>',
    { url: 'https://jurix.local/assistente/', runScripts: 'dangerously', pretendToBeVisual: true },
  );
  const { window } = dom;
  window.eval(read('jurix-markdown.js'));
  window.eval(read('jurix-rag.js'));
  window.eval(read('jurix-chat-renderer.js'));
  return window;
}

const historicalSource = {
  citation_index: 1,
  citation_id: `jurix:norma:31:version:${'b'.repeat(64)}:device:${'a'.repeat(64)}`,
  citation_label: 'Lei nº 8.205/2026, Art. 1º (redação projetada pelo Jurix em 2026-05-01)',
  pdf_url: 'https://sapl.natal.rn.leg.br/media/lei.pdf#:~:text=truncated-old-marker',
  full_text: 'Redação histórica completa.',
  temporal_version: { as_of: '2026-05-01', version_hash: 'b'.repeat(64) },
};

test('an invalid citation marker never falls through to a different source', () => {
  const window = boot();
  const html = window.JurixMarkdown.normalize('[[2]]', [historicalSource]);

  assert.equal(html, '[[2]]');
  assert.doesNotMatch(html, /jurix-citation/);
  window.close();
});

test('legacy sources without citation indexes retain their array-order contract', () => {
  const window = boot();
  const html = window.JurixMarkdown.normalize('[[1]]', [
    { citation_label: 'Lei nº 8.205/2026, Art. 1º' },
  ]);

  assert.match(html, /data-source-index="1"/);
  assert.match(html, /Lei nº 8\.205\/2026/);
  window.close();
});

test('inline bullet normalization does not turn a legal hyphen into a new list item', () => {
  const window = boot();
  const clause = 'Parágrafo Único - As demais gratificações permanecem regidas por lei específica.';
  const inlineBullets = '• primeira hipótese • segunda hipótese';

  assert.equal(window.JurixMarkdown.normalize(clause), clause);
  assert.equal(
    window.JurixMarkdown.normalize(inlineBullets),
    '• primeira hipótese\n• segunda hipótese',
  );
  window.close();
});

test('historical source navigation opens the official base without a text fragment', () => {
  const window = boot();
  const href = window.JurixRagUI.buildSourceUrl(historicalSource);

  assert.equal(href, 'https://sapl.natal.rn.leg.br/media/lei.pdf');
  window.close();
});

test('copied response retains a Markdown citation to the unmarked official source', async () => {
  const window = boot();
  const copied = [];
  Object.defineProperty(window.navigator, 'clipboard', {
    configurable: true,
    value: { writeText: async (value) => copied.push(value) },
  });
  const button = window.document.querySelector('.copy-response-button');
  button._citationSources = [historicalSource];

  await window.JurixChatRenderer.copyResponseToClipboard(
    'Conforme [[1]], aplica-se a redação histórica.',
    button,
  );

  assert.equal(copied.length, 1);
  assert.match(copied[0], /\[Lei nº 8\.205\/2026, Art\. 1º \(redação projetada pelo Jurix em 2026-05-01\)\]/);
  assert.match(copied[0], /<https:\/\/sapl\.natal\.rn\.leg\.br\/media\/lei\.pdf>/);
  assert.doesNotMatch(copied[0], /#:~:text=/);
  window.close();
});

test('anonymous local history preserves safe versioned citation DTOs and strips unknown secrets', () => {
  const dom = new JSDOM(
    '<!doctype html><html><body data-authenticated="false"></body></html>',
    { url: 'https://jurix.local/assistente/', runScripts: 'dangerously', pretendToBeVisual: true },
  );
  const { window } = dom;
  window.eval(read('jurix-anonymous-history.js'));
  const history = window.JurixAnonymousHistory;
  const sessionId = history.ensureSession('local-citation-test');
  history.addMessage(sessionId, 'user', 'O que prevê a versão histórica?');
  history.updateLastAssistant(sessionId, 'Resposta [[1]].', [{
    ...historicalSource,
    dispositivo_structural_key: 'a'.repeat(64),
    graph_relation: { action: 'ALTERA', quote: 'Trecho validado.', api_key: 'do-not-export' },
    private_token: 'do-not-export',
  }], true);

  const restored = history.get(sessionId).messages.at(-1).sources[0];
  const exported = history.exportData().sessions[0].messages.at(-1).sources[0];
  assert.equal(restored.temporal_version.version_hash, 'b'.repeat(64));
  assert.equal(exported.dispositivo_structural_key, 'a'.repeat(64));
  assert.equal(exported.graph_relation.action, 'ALTERA');
  assert.equal(exported.graph_relation.api_key, undefined);
  assert.equal(exported.private_token, undefined);
  assert.equal(exported.pdf_url.includes('#:~:text='), true);
  window.close();
});
