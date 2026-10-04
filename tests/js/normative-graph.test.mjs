import test from 'node:test';
import assert from 'node:assert/strict';
import fs, { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { JSDOM } from 'jsdom';
import puppeteer from 'puppeteer-core';

const js = readFileSync(new URL('../../src/apps/core/static/js/jurix-normative-graph.js', import.meta.url), 'utf8');
const testDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(testDir, '../..');
const browserPath = [
  process.env.PUPPETEER_EXECUTABLE_PATH,
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
].find((candidate) => candidate && fs.existsSync(candidate));
const html = `<section data-normative-relations data-api-url="/api/norma/42/relations/">
<details data-relations-disclosure><summary data-relations-toggle>Relações</summary><div>
<label for="filter">Filtro</label><select id="filter" data-relations-action><option value="">Todas</option><option value="REFERENCIA">Referência</option><option value="ALTERA">Altera</option></select>
<button data-relations-retry hidden>Tentar novamente</button><p data-relations-status role="status" aria-live="polite"></p><p data-relations-truncated hidden></p>
<div data-relations-graph-wrap hidden><svg data-relations-svg aria-hidden="true"></svg></div><ul data-relations-list></ul>
<aside data-relations-panel hidden><button data-relations-close>Fechar</button><div data-relations-panel-content></div></aside>
</div></details></section>`;

const fixture = {
  success: true,
  norma: { id: 42 },
  nodes: [
    { id: 'norma:42', kind: 'norma', label: 'Lei Ordinária nº 10/2020', url: '/normas/42/' },
    { id: 'norma:43', kind: 'norma', label: 'Lei Complementar nº 5/2021', url: '/normas/43/' },
  ],
  edges: [
    { id: 'event:1', source: 'norma:42', target: 'norma:43', action: 'REFERENCIA', source_device: { label: 'Art. 2º, inciso I', structural_key: 'sha256-a' }, review_status: 'confirmed', effective_status: 'not_applicable', publication_on: '2020-02-01', evidence: { quote: '<script>trecho de evidência</script>' }, official_url: 'javascript:alert(1)' },
    { id: 'event:2', source: 'norma:42', target: 'norma:43', action: 'REFERENCIA', source_device: { label: 'Art. 4º', structural_key: 'sha256-b' }, review_status: 'confirmed', effective_status: 'not_applicable', publication_on: '2020-02-01', evidence: { quote: 'Outro trecho' }, official_url: 'https://sapl.example/norma.pdf' },
  ],
};
const settle = () => new Promise((resolve) => setTimeout(resolve, 10));

async function boot(fetchImpl = async () => ({ ok: true, json: async () => fixture })) {
  const dom = new JSDOM(html, { url: 'http://jurix.test/normas/42/', runScripts: 'outside-only' });
  dom.window.matchMedia = () => ({ matches: true });
  dom.window.HTMLElement.prototype.scrollIntoView = function () {};
  dom.window.fetch = fetchImpl;
  dom.window.eval(js);
  return dom;
}

function open(dom) {
  const details = dom.window.document.querySelector('[data-relations-disclosure]');
  details.open = true;
  return details;
}

test('carrega sob demanda, agrupa vínculos e fornece uma lista HTML com painel detalhado', async () => {
  let requests = 0;
  const dom = await boot(async () => { requests += 1; return { ok: true, json: async () => fixture }; });
  assert.equal(requests, 0);
  open(dom);
  await settle();
  assert.equal(requests, 1);
  const doc = dom.window.document;
  assert.equal(doc.querySelectorAll('[data-relations-list] > li').length, 1);
  assert.match(doc.querySelector('.normative-relations__group-count').textContent, /2 vínculos/);
  assert.equal(doc.querySelector('[data-relations-svg]').getAttribute('aria-hidden'), 'true');
  doc.querySelector('.normative-relations__group-button').click();
  assert.equal(doc.querySelector('[data-relations-panel]').hidden, false);
  assert.equal(doc.querySelectorAll('.normative-relations__event').length, 2);
  assert.match(doc.querySelector('.normative-relations__event').textContent, /Art\. 2º, inciso I/);
  assert.match(doc.querySelector('.normative-relations__event').textContent, /Esta relação não afirma alteração ou revogação/);
  assert.match(doc.querySelector('blockquote').textContent, /<script>/);
  assert.equal(doc.querySelector('blockquote script'), null);
  assert.equal(doc.querySelectorAll('a[href^="javascript:"]').length, 0);
  dom.window.close();
});

test('Escape fecha painel e devolve foco ao controle de origem', async () => {
  const dom = await boot();
  open(dom);
  await settle();
  const trigger = dom.window.document.querySelector('.normative-relations__group-button');
  trigger.focus();
  trigger.click();
  assert.equal(dom.window.document.activeElement, dom.window.document.querySelector('[data-relations-close]'));
  dom.window.document.querySelector('[data-normative-relations]').dispatchEvent(new dom.window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  assert.equal(dom.window.document.querySelector('[data-relations-panel]').hidden, true);
  assert.equal(dom.window.document.activeElement, trigger);
  dom.window.close();
});

test('filtro local sincroniza SVG/lista e mantém o filtro quando a API falha e há retry', async () => {
  let calls = 0;
  const dom = await boot(async () => {
    calls += 1;
    if (calls === 1) return { ok: false, status: 503 };
    return { ok: true, json: async () => fixture };
  });
  const filter = dom.window.document.querySelector('[data-relations-action]');
  filter.value = 'ALTERA';
  open(dom);
  await settle();
  const doc = dom.window.document;
  assert.match(doc.querySelector('[data-relations-status]').textContent, /Tente novamente/);
  doc.querySelector('[data-relations-retry]').click();
  await settle();
  assert.equal(doc.querySelector('[data-relations-action]').value, 'ALTERA');
  assert.match(doc.querySelector('[data-relations-status]').textContent, /Nenhuma relação corresponde/);
  assert.equal(doc.querySelectorAll('[data-relations-list] > li').length, 0);
  assert.equal(calls, 2);
  dom.window.close();
});

test('estado vazio é explícito e SVG não recebe conteúdo como HTML', async () => {
  const empty = { ...fixture, edges: [] };
  const dom = await boot(async () => ({ ok: true, json: async () => empty }));
  open(dom);
  await settle();
  const doc = dom.window.document;
  assert.match(doc.querySelector('[data-relations-status]').textContent, /não possui relações públicas/);
  assert.equal(doc.querySelector('[data-relations-svg]').innerHTML, '');
  assert.doesNotMatch(js, /\.innerHTML\s*=/);
  dom.window.close();
});

test('real browser: grafo normativo agrupado, painel acessível e reflow; salva screenshots temáticas', {
  skip: !process.env.JURIX_QA_BASE_URL || !browserPath,
}, async () => {
  const browser = await puppeteer.launch({
    executablePath: browserPath,
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'],
  });
  const evidenceDir = path.join(repoRoot, 'docs', 'research', 'screenshots');
  fs.mkdirSync(evidenceDir, { recursive: true });
  const graphFixture = {
    success: true,
    norma: { id: 7, ref: 'Lei Complementar nº 198/2021' },
    scope: { as_of: '2026-10-03', depth: 1 },
    truncated: false,
    nodes: [
      { id: 'norma:7', kind: 'norma', label: 'Lei Complementar nº 198/2021', url: '/normas/7/' },
      { id: 'norma:5', kind: 'norma', label: 'Lei Complementar nº 55/2004', url: '/normas/5/' },
    ],
    edges: [
      { id: 'event:qa-1', source: 'norma:7', target: 'norma:5', action: 'REFERENCIA', source_device: { label: 'Art. 3º, inciso II' }, review_status: 'confirmed', effective_status: 'not_applicable', publication_on: '2021-05-04', evidence: { quote: 'Trecho sintético de referência entre normas.' }, official_url: 'https://sapl.example.test/lei-complementar.pdf' },
      { id: 'event:qa-2', source: 'norma:7', target: 'norma:5', action: 'REFERENCIA', source_device: { label: 'Art. 8º' }, review_status: 'confirmed', effective_status: 'not_applicable', publication_on: '2021-05-04', evidence: { quote: 'Outro trecho sintético de referência.' }, official_url: null },
    ],
  };
  try {
    const page = await browser.newPage();
    await page.setViewport({ width: 1440, height: 1000 });
    const browserDiagnostics = [];
    page.on('console', (message) => { if (message.type() === 'error') browserDiagnostics.push(`console:${message.text()}`); });
    page.on('requestfailed', (request) => browserDiagnostics.push(`request:${request.url()} ${request.failure()?.errorText || ''}`));
    await page.setRequestInterception(true);
    page.on('request', (request) => {
      if (request.url().includes('/api/v1/normas/7/relations/')) {
        browserDiagnostics.push(`mock:${request.url()}`);
        request.respond({ status: 200, contentType: 'application/json', body: JSON.stringify(graphFixture) });
      } else request.continue();
    });
    await page.goto(`${process.env.JURIX_QA_BASE_URL.replace(/\/$/, '')}/normas/7/`, { waitUntil: 'networkidle0' });
    assert.equal(await page.$$eval('[data-normative-relations]', (items) => items.length), 1);
    await page.click('[data-relations-toggle]');
    try {
      await page.waitForSelector('.normative-relations__group-button', { timeout: 5000 });
    } catch {
      const diagnostics = await page.evaluate(() => ({
        url: location.href,
        detailsOpen: document.querySelector('[data-relations-disclosure]')?.open,
        status: document.querySelector('[data-relations-status]')?.textContent,
        script: [...document.scripts].map((script) => script.src).filter((src) => src.includes('normative-graph')),
      }));
      throw new Error(`UI grafo não carregou: ${JSON.stringify(diagnostics)}; ${browserDiagnostics.join(' | ')}`);
    }
    assert.match(await page.$eval('.normative-relations__group-count', (node) => node.textContent), /2 vínculos/);
    assert.equal(await page.$eval('[data-relations-svg]', (svg) => svg.getAttribute('aria-hidden')), 'true');
    await page.click('.normative-relations__group-button');
    assert.equal(await page.$eval('[data-relations-close]', (node) => document.activeElement === node), true);
    assert.equal(await page.$$eval('.normative-relations__event', (items) => items.length), 2);
    assert.equal(await page.$$eval('.normative-relations__event a', (links) => links.some((link) => link.textContent.includes('https://'))), false);
    const motionDuration = await page.$eval('[data-relations-panel]', (node) => getComputedStyle(node).animationDuration);
    assert.notEqual(motionDuration, '0s');
    await (await page.$('[data-normative-relations]')).screenshot({ path: path.join(evidenceDir, 't017-relations-dark.png') });
    await page.keyboard.press('Escape');
    assert.equal(await page.$eval('.normative-relations__group-button', (node) => document.activeElement === node), true);

    await page.evaluate(() => document.documentElement.setAttribute('data-theme', 'light'));
    const contrast = await page.evaluate(() => {
      const color = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
      const rgb = (value) => {
        const channels = value.startsWith('#')
          ? value.length === 4 ? [...value.slice(1)].map((digit) => parseInt(digit + digit, 16)) : value.slice(1).match(/.{2}/g).map((channel) => parseInt(channel, 16))
          : value.match(/[\d.]+/g).slice(0, 3).map(Number);
        return channels.map((part) => {
        const channel = part / 255;
        return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
        });
      };
      const luminance = (value) => { const [r, g, b] = rgb(value); return .2126 * r + .7152 * g + .0722 * b; };
      const a = luminance(color('--jurix-text-muted'));
      const b = luminance(color('--jurix-surface'));
      return (Math.max(a, b) + .05) / (Math.min(a, b) + .05);
    });
    assert.ok(contrast >= 4.5, `contraste dos metadados no tema claro: ${contrast.toFixed(2)}:1`);
    await (await page.$('[data-normative-relations]')).screenshot({ path: path.join(evidenceDir, 't017-relations-light.png') });

    await page.setViewport({ width: 360, height: 800 });
    await page.emulateMediaFeatures([{ name: 'prefers-reduced-motion', value: 'reduce' }]);
    const reducedMotionDuration = await page.$eval('[data-relations-panel]', (node) => getComputedStyle(node).animationDuration);
    assert.ok(parseFloat(reducedMotionDuration) <= 0.01, `reduced motion usa ${reducedMotionDuration}`);
    await new Promise((resolve) => setTimeout(resolve, 250));
    const mobile = await page.$eval('[data-normative-relations]', (root) => ({
      componentWidth: root.clientWidth,
      componentScrollWidth: root.scrollWidth,
      graphDisplay: getComputedStyle(root.querySelector('[data-relations-graph-wrap]')).display,
      listCount: root.querySelectorAll('[data-relations-list] > li').length,
      targetHeight: root.querySelector('.normative-relations__group-button').getBoundingClientRect().height,
    }));
    assert.equal(mobile.graphDisplay, 'none');
    assert.equal(mobile.listCount, 1);
    assert.ok(mobile.targetHeight >= 44);
    assert.ok(mobile.componentScrollWidth <= mobile.componentWidth + 1);
    await (await page.$('[data-normative-relations]')).screenshot({ path: path.join(evidenceDir, 't017-relations-mobile-360.png') });

    await page.setViewport({ width: 320, height: 800 });
    const narrowWidth = await page.$eval('[data-normative-relations]', (root) => root.scrollWidth - root.clientWidth);
    assert.ok(narrowWidth <= 1, `overflow interno em 320px: ${narrowWidth}px`);
    await page.evaluate(() => { document.documentElement.style.zoom = '2'; });
    const zoomed = await page.$eval('[data-normative-relations]', (root) => ({
      overflow: root.scrollWidth - root.clientWidth,
      listVisible: getComputedStyle(root.querySelector('[data-relations-list]')).display !== 'none',
      offenders: [...root.querySelectorAll('*')].filter((node) => node.getBoundingClientRect().right > root.getBoundingClientRect().right + 1).map((node) => `${node.className?.baseVal || node.className}:${Math.round(node.getBoundingClientRect().right - root.getBoundingClientRect().right)}`).slice(0, 8),
      scrollables: [root, ...root.querySelectorAll('*')].filter((node) => node.scrollWidth > node.clientWidth + 1).map((node) => `${node.className?.baseVal || node.className || node.tagName}:${node.scrollWidth - node.clientWidth}`).slice(0, 8),
    }));
    assert.ok(zoomed.overflow <= 1, `overflow interno em 320px/200%: ${zoomed.overflow}px (${zoomed.offenders.join(', ')}; ${zoomed.scrollables.join(', ')})`);
    assert.equal(zoomed.listVisible, true);
    await page.evaluate(() => { document.documentElement.style.zoom = ''; });
    await page.setViewport({ width: 768, height: 900 });
    assert.equal(await page.$eval('[data-relations-graph-wrap]', (node) => getComputedStyle(node).display), 'none');
    assert.equal(await page.$$eval('[data-relations-list] > li', (items) => items.length), 1);
    await page.setViewport({ width: 1280, height: 900 });
    assert.notEqual(await page.$eval('[data-relations-graph-wrap]', (node) => getComputedStyle(node).display), 'none');
    await page.setViewport({ width: 1920, height: 1080 });
    assert.equal(await page.$eval('[data-relations-list] > li', (item) => item.isConnected), true);
    await page.close();
  } finally {
    await browser.close();
  }
});
