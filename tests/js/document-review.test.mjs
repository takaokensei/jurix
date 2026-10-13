import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { test } from 'node:test';
import { JSDOM } from 'jsdom';

const source = await readFile(
  new URL('../../src/apps/core/static/js/jurix-document-review.js', import.meta.url),
  'utf8',
);

function boot({ withError = false } = {}) {
  const html = `<!doctype html><form data-document-review-form>
    ${withError ? '<div role="alert" tabindex="-1">Revise os campos</div>' : ''}
    <button type="submit" data-document-review-submit data-submitting-label="Salvando revisão…">Confirmar</button>
  </form>`;
  const dom = new JSDOM(html, { runScripts: 'outside-only' });
  dom.window.eval(source);
  const form = dom.window.document.querySelector('form');
  const button = form.querySelector('button');
  return { dom, form, button };
}

test('leva o foco ao alerta quando a ficha retorna com erro de validação', () => {
  const { dom, form } = boot({ withError: true });
  const alert = form.querySelector('[role="alert"]');
  assert.equal(dom.window.document.activeElement, alert);
});

test('não envia e não mostra estado de salvamento quando a validação nativa falha', () => {
  const { dom, form, button } = boot();
  form.reportValidity = () => false;
  const event = new dom.window.Event('submit', { bubbles: true, cancelable: true });

  form.dispatchEvent(event);

  assert.equal(event.defaultPrevented, true);
  assert.equal(form.dataset.submitting, undefined);
  assert.equal(form.getAttribute('aria-busy'), null);
  assert.equal(button.disabled, false);
});

test('mostra estado ocupado e impede o segundo envio', () => {
  const { dom, form, button } = boot();
  form.reportValidity = () => true;
  const first = new dom.window.Event('submit', { bubbles: true, cancelable: true });
  form.dispatchEvent(first);

  assert.equal(first.defaultPrevented, false);
  assert.equal(form.dataset.submitting, 'true');
  assert.equal(form.getAttribute('aria-busy'), 'true');
  assert.equal(button.disabled, true);
  assert.equal(button.textContent, 'Salvando revisão…');

  const duplicate = new dom.window.Event('submit', { bubbles: true, cancelable: true });
  form.dispatchEvent(duplicate);
  assert.equal(duplicate.defaultPrevented, true);
});
