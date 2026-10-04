import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { test } from 'node:test';
import { JSDOM } from 'jsdom';

const source = await readFile(new URL('../../src/apps/core/static/js/jurix-archive-candidate-filter.js', import.meta.url), 'utf8');
const html = `<!doctype html><section>
  <input id="archive-candidate-search">
  <select id="archive-candidate-identity"><option value="all">Todas</option><option value="resolved">Reconhecida</option><option value="unresolved">Precisa identificar</option></select>
  <select id="archive-candidate-status"><option value="all">Todos</option><option value="pending">Pendente</option><option value="in_review">Em revisão</option></select>
  <select id="archive-candidate-extraction"><option value="all">Todos</option><option value="complete">Completa</option><option value="partial">Parcial</option><option value="unreadable">Ilegível</option><option value="none">Sem extração</option></select>
  <p id="archive-candidate-filter-summary" role="status" aria-live="polite"></p>
  <div id="archive-candidates-list">
    <article class="jurix-archive-candidate" data-search="Lei Complementar nº 120/2010 LeiComplementar20101203_120.pdf 0" data-identity="resolved" data-review-status="pending" data-extraction-status="complete"></article>
    <article class="jurix-archive-candidate" data-search="Decreto nº 12887/2022 Decreto_20230831_12887_.pdf 4" data-identity="unresolved" data-review-status="pending" data-extraction-status="partial"></article>
    <article class="jurix-archive-candidate" data-search="Lei Ordinária nº 55/2024 Lei_55.pdf 7" data-identity="resolved" data-review-status="in_review" data-extraction-status="none"></article>
  </div>
  <p id="archive-candidates-no-results" hidden></p>
</section>`;

function boot(initialSearch = '') {
  const dom = new JSDOM(html, { runScripts: 'outside-only' });
  dom.window.document.getElementById('archive-candidate-search').value = initialSearch;
  dom.window.eval(source);
  const { document } = dom.window;
  return {
    dom,
    document,
    cards: [...document.querySelectorAll('.jurix-archive-candidate')],
    search: document.getElementById('archive-candidate-search'),
    identity: document.getElementById('archive-candidate-identity'),
    status: document.getElementById('archive-candidate-status'),
    extraction: document.getElementById('archive-candidate-extraction'),
  };
}

test('aplica a consulta da busca normativa ao abrir a lista do acervo histórico', () => {
  const ui = boot('Lei Complementar 120/2010');
  assert.deepEqual(ui.cards.map((card) => card.hidden), [false, true, true]);
  assert.equal(ui.document.getElementById('archive-candidate-filter-summary').textContent, 'Exibindo 1 de 3 documentos.');
});

test('busca candidatos por número/ano sem diferenciar acentos ou caixa', () => {
  const ui = boot();
  ui.search.value = 'lei complementar 120/2010';
  ui.search.dispatchEvent(new ui.dom.window.Event('input', { bubbles: true }));
  assert.deepEqual(ui.cards.map((card) => card.hidden), [false, true, true]);
  assert.equal(ui.document.getElementById('archive-candidate-filter-summary').textContent, 'Exibindo 1 de 3 documentos.');
});

test('combina filtro de identidade e status sem alterar os cartões de origem', () => {
  const ui = boot();
  ui.identity.value = 'resolved';
  ui.identity.dispatchEvent(new ui.dom.window.Event('change', { bubbles: true }));
  assert.deepEqual(ui.cards.map((card) => card.hidden), [false, true, false]);
  ui.status.value = 'pending';
  ui.status.dispatchEvent(new ui.dom.window.Event('change', { bubbles: true }));
  assert.deepEqual(ui.cards.map((card) => card.hidden), [false, true, true]);
});

test('anuncia filtro sem resultados e mantém a explicação acessível', () => {
  const ui = boot();
  ui.search.value = 'norma que não existe';
  ui.search.dispatchEvent(new ui.dom.window.Event('input', { bubbles: true }));
  assert.equal(ui.document.getElementById('archive-candidates-no-results').hidden, false);
  assert.match(ui.document.getElementById('archive-candidate-filter-summary').textContent, /0 de 3/);
});

test('filtra separadamente o estado técnico do texto extraído', () => {
  const ui = boot();
  ui.extraction.value = 'partial';
  ui.extraction.dispatchEvent(new ui.dom.window.Event('change', { bubbles: true }));
  assert.deepEqual(ui.cards.map((card) => card.hidden), [true, false, true]);
  assert.equal(ui.document.getElementById('archive-candidate-filter-summary').textContent, 'Exibindo 1 de 3 documentos.');
});
