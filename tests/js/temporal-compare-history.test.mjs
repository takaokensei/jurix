import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { test } from 'node:test';
import { JSDOM } from 'jsdom';

const root = new URL('../../', import.meta.url);
const read = (path) => readFile(new URL(path, root), 'utf8');

const html = `<!doctype html><form class="historical-date-form"
 data-default-from="" data-default-to="2026-10-04">
 <input id="from-as-of" name="from_as_of" type="date" value="">
 <input id="to-as-of" name="to_as_of" type="date" value="2026-10-04">
</form>`;

async function boot(url) {
  const dom = new JSDOM(html, { url, runScripts: 'outside-only' });
  dom.window.eval(await read('src/apps/core/static/js/jurix-temporal-compare.js'));
  return dom;
}

test('pageshow reapplies date fields from the restored URL after browser back', async () => {
  const dom = await boot('http://jurix.test/normas/3/compare/?history=1&from_as_of=2021-02-28&to_as_of=2021-03-01');
  const { document, PageTransitionEvent } = dom.window;
  const from = document.querySelector('#from-as-of');
  const to = document.querySelector('#to-as-of');
  to.value = '2021-03-02'; // Simulate the form value Chromium restored from the later entry.

  dom.window.dispatchEvent(new PageTransitionEvent('pageshow', { persisted: true }));

  assert.equal(from.value, '2021-02-28');
  assert.equal(to.value, '2021-03-01');
  dom.window.close();
});

test('popstate synchronizes date fields and absent query values use server defaults', async () => {
  const dom = await boot('http://jurix.test/normas/3/compare/?from_as_of=2021-02-28&to_as_of=2021-03-02');
  const { document, history, PopStateEvent } = dom.window;
  const from = document.querySelector('#from-as-of');
  const to = document.querySelector('#to-as-of');

  history.pushState({}, '', '/normas/3/compare/?history=1&from_as_of=2021-02-28&to_as_of=2021-03-01');
  dom.window.dispatchEvent(new PopStateEvent('popstate'));
  assert.equal(to.value, '2021-03-01');

  history.pushState({}, '', '/normas/3/compare/?history=1');
  dom.window.dispatchEvent(new PopStateEvent('popstate'));
  assert.equal(from.value, '');
  assert.equal(to.value, '2026-10-04');
  dom.window.close();
});

test('comparison template loads the external history synchronizer and server defaults', async () => {
  const template = await read('src/apps/legislation/templates/legislation/norma_compare.html');
  assert.match(template, /data-default-from="\{\{ from_as_of \}\}" data-default-to="\{\{ to_as_of \}\}"/);
  assert.match(template, /js\/jurix-temporal-compare\.js['"] %\}\?v=20261004-history-sync1/);
});
