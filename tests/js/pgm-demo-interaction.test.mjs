import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { JSDOM } from 'jsdom';

const script = fs.readFileSync(new URL('../../src/apps/core/static/js/jurix-pgm-demo.js', import.meta.url), 'utf8');

function mountGraph() {
  const targets = [
    ...Array.from({ length: 7 }, (_, index) => `<li data-graph-target="repeal-${index}" data-graph-relation-target="express"></li>`),
    '<li data-graph-target="amendment-1" data-graph-relation-target="amendment"></li>',
    '<li data-graph-target="generic-1" data-graph-relation-target="generic"></li>',
  ].join('');
  const relations = ['express', 'amendment', 'generic']
    .map((kind) => `<div data-graph-relation="${kind}"></div>`).join('');
  const filters = ['all', 'express', 'amendment', 'generic']
    .map((kind) => `<button type="button" data-graph-filter="${kind}" aria-pressed="${kind === 'all'}"></button>`)
    .join('');
  const dom = new JSDOM(`<section class="pgm-demo__network">
    <svg class="pgm-demo__edges" aria-hidden="true"></svg>
    <article class="pgm-demo__source-node"></article>${relations}<ol>${targets}</ol>
    <div>${filters}</div><p data-graph-live role="status" aria-live="polite"></p>
  </section>`, { runScripts: 'outside-only' });
  dom.window.requestAnimationFrame = (callback) => callback();
  dom.window.eval(script);
  return dom;
}

test('selecionar uma cadeia fecha o menu sticky e abre a seção de destino', async () => {
  const dom = new JSDOM(`<div class="pgm-demo">
    <nav class="pgm-demo__case-nav">
      <details class="pgm-demo__case-nav-more" open>
        <summary>Outras cadeias</summary>
        <div class="pgm-demo__case-nav-menu"><a href="#case-target">Histórico da norma</a></div>
      </details>
    </nav>
    <details data-case-disclosure><summary>Cotejo principal</summary><h2 id="primary-target">Cotejo</h2></details>
    <details data-case-disclosure><summary>Outras cadeias</summary><h2 id="case-target">Histórico</h2></details>
    <section class="pgm-demo__network"></section>
  </div>`, { url: 'https://jurix.test/', runScripts: 'outside-only' });
  dom.window.eval(script);

  const [primaryDisclosure, secondaryDisclosure] = dom.window.document.querySelectorAll('[data-case-disclosure]');
  assert.equal(primaryDisclosure.open, false);
  assert.equal(secondaryDisclosure.open, false);
  dom.window.document.querySelector('.pgm-demo__case-nav-menu a').click();
  await new Promise((resolve) => dom.window.setTimeout(resolve, 0));

  assert.equal(dom.window.document.querySelector('.pgm-demo__case-nav-more').open, false);
  assert.equal(primaryDisclosure.open, false, 'unrelated collapsed case remains closed');
  assert.equal(secondaryDisclosure.open, true, 'the anchored case opens on demand');
  assert.equal(dom.window.location.hash, '#case-target');
  dom.window.close();
});

test('grafo destaca as sete revogações expressas sem esconder as outras relações', () => {
  const dom = mountGraph();
  const { document } = dom.window;

  document.querySelector('[data-graph-filter="express"]').click();

  assert.equal(document.querySelector('[data-graph-filter="express"]').getAttribute('aria-pressed'), 'true');
  assert.equal(document.querySelector('[data-graph-filter="all"]').getAttribute('aria-pressed'), 'false');
  assert.equal(document.querySelectorAll('[data-graph-target][data-graph-emphasis="active"]').length, 7);
  assert.equal(document.querySelectorAll('[data-graph-target][data-graph-emphasis="muted"]').length, 2);
  assert.equal(document.querySelectorAll('[data-graph-target][aria-hidden="true"]').length, 0);
  assert.match(document.querySelector('[data-graph-live]').textContent, /seis leis e um artigo/i);
  dom.window.close();
});

test('grafo diferencia alteração e cláusula geral e permite restaurar a visão completa', () => {
  const dom = mountGraph();
  const { document } = dom.window;

  document.querySelector('[data-graph-filter="amendment"]').click();
  assert.equal(document.querySelectorAll('[data-graph-target][data-graph-emphasis="active"]').length, 1);
  assert.match(document.querySelector('[data-graph-live]').textContent, /não é uma revogação/i);

  document.querySelector('[data-graph-filter="generic"]').click();
  assert.equal(document.querySelectorAll('[data-graph-target][data-graph-emphasis="active"]').length, 1);
  assert.match(document.querySelector('[data-graph-live]').textContent, /sem individualizar outras leis/i);

  document.querySelector('[data-graph-filter="all"]').click();
  assert.equal(document.querySelectorAll('[data-graph-target][data-graph-emphasis="active"]').length, 9);
  assert.equal(document.querySelectorAll('[data-graph-target][data-graph-emphasis="muted"]').length, 0);
  assert.match(document.querySelector('[data-graph-live]').textContent, /visão completa/i);
  dom.window.close();
});
