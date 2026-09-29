import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { JSDOM } from 'jsdom';

const ROOT = path.resolve(import.meta.dirname, '../..');
const SCRIPT = path.join(ROOT, 'src/apps/core/static/js/jurix-search-controls.js');

test('search option menu toggles, closes with Escape, and returns keyboard focus', () => {
  const dom = new JSDOM(`<!doctype html><html><body>
    <div class="figma-search-dropdown" data-control="norma_status" tabindex="0">
      <span data-control-label>Pesquisa normativa</span>
    </div>
  </body></html>`, {
    url: 'http://localhost/assistente/',
    runScripts: 'dangerously',
    pretendToBeVisual: true,
  });
  const { window } = dom;
  window.eval(fs.readFileSync(SCRIPT, 'utf8'));
  window.document.dispatchEvent(new window.Event('DOMContentLoaded', { bubbles: true }));

  const control = window.document.querySelector('.figma-search-dropdown');
  control.focus();
  control.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }));
  assert.equal(control.getAttribute('aria-expanded'), 'true');
  assert.equal(control.getAttribute('aria-haspopup'), 'menu');
  assert.equal(window.document.querySelector('[role="menuitemradio"]')?.getAttribute('aria-checked'), 'true');
  assert.equal(window.document.activeElement, window.document.querySelector('.jurix-control-option'));

  window.document.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
  assert.equal(window.document.querySelector('[data-jurix-control-menu]'), null);
  assert.equal(control.getAttribute('aria-expanded'), 'false');
  assert.equal(window.document.activeElement, control);

  control.click();
  assert.equal(control.getAttribute('aria-expanded'), 'true');
  control.click();
  assert.equal(control.getAttribute('aria-expanded'), 'false');
  assert.equal(window.document.querySelector('[data-jurix-control-menu]'), null);
  dom.window.close();
});
