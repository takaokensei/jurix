import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { JSDOM } from 'jsdom';

const script = readFileSync(new URL('../../src/apps/core/static/js/jurix-foundation-check.js', import.meta.url), 'utf8');
const formMarkup = (id = 'job-1') => `<section id="foundation-workspace"><h1>Conferir fundamentação</h1>
<form method="post" action="/conferir/" data-foundation-form data-status-url="/conferir/status/${id}/" data-result-url="/conferir/resultado/${id}/" data-cancel-url="/conferir/${id}/cancelar/" data-job-status="">
<input type="hidden" name="csrfmiddlewaretoken" value="csrf"/><input type="hidden" name="job_id" value="${id}"/>
<textarea name="text" required>Art. 1º da Lei nº 10/2020</textarea><input name="from_date" type="date" value="2020-01-01"/><input name="to_date" type="date" value="2021-01-01"/>
<button type="submit" name="action" value="review">Identificar referências</button><button type="submit" name="action" value="compare" data-foundation-compare>Conferir dispositivos</button>
<button type="button" data-foundation-cancel hidden>Cancelar conferência</button><div data-foundation-progress role="status" aria-live="polite"></div></form></section>`;
const settle = () => new Promise((resolve) => setTimeout(resolve, 10));

async function mount(fetchImpl) {
  const dom = new JSDOM(formMarkup(), { url: 'https://jurix.test/conferir/', runScripts: 'outside-only' });
  dom.window.fetch = fetchImpl;
  dom.window.scrollTo = () => {};
  dom.window.eval(script);
  return dom;
}

test('envia comparação uma vez, acompanha progresso e substitui resultado mantendo novo formulário', async () => {
  let postCount = 0;
  let progressCount = 0;
  const dom = await mount(async (url, options = {}) => {
    if (String(url).includes('/status/')) {
      progressCount += 1;
      return { ok: true, json: async () => ({ status: 'completed', completed: 2, total: 2 }) };
    }
    if (String(url).includes('/resultado/')) return { ok: true, url: '/conferir/', text: async () => formMarkup('job-2').replace('<h1>Conferir fundamentação</h1>', '<h1>Conferir fundamentação</h1><section data-foundation-summary tabindex="-1">Resumo</section>') };
    assert.equal(options.method, 'POST');
    assert.equal(options.body.get('csrfmiddlewaretoken'), 'csrf');
    assert.equal(options.body.get('action'), 'compare');
    postCount += 1;
    return { ok: true, url: '/conferir/', text: async () => formMarkup('job-2').replace('data-job-status=""', 'data-job-status="queued"') };
  });
  const form = dom.window.document.querySelector('form');
  const compare = form.querySelector('[data-foundation-compare]');
  form.dispatchEvent(new dom.window.SubmitEvent('submit', { bubbles: true, cancelable: true, submitter: compare }));
  await settle();
  await settle();
  assert.equal(postCount, 1);
  assert.ok(progressCount >= 1);
  assert.equal(dom.window.document.querySelector('#foundation-workspace [data-foundation-summary]').textContent, 'Resumo');
  assert.equal(dom.window.document.activeElement, dom.window.document.querySelector('[data-foundation-summary]'));
  assert.ok(dom.window.document.querySelector('#foundation-workspace [data-foundation-form]'));
  dom.window.close();
});

test('identifica referências sem exigir datas e só exige intervalo válido na comparação', async () => {
  let postCount = 0;
  const dom = await mount(async (_url, options = {}) => {
    postCount += 1;
    assert.equal(options.body.get('action'), 'review');
    return { url: '/conferir/', text: async () => `${formMarkup('job-2')}` };
  });
  const form = dom.window.document.querySelector('form');
  const fromDate = form.elements.namedItem('from_date');
  const toDate = form.elements.namedItem('to_date');
  fromDate.value = '';
  toDate.value = '';
  const review = form.querySelector('[value="review"]');
  form.dispatchEvent(new dom.window.SubmitEvent('submit', { bubbles: true, cancelable: true, submitter: review }));
  await settle();
  assert.equal(postCount, 1);

  const compareForm = dom.window.document.querySelector('form');
  compareForm.elements.namedItem('from_date').value = '2021-01-01';
  compareForm.elements.namedItem('to_date').value = '2020-01-01';
  const compare = compareForm.querySelector('[data-foundation-compare]');
  compareForm.dispatchEvent(new dom.window.SubmitEvent('submit', { bubbles: true, cancelable: true, submitter: compare }));
  await settle();
  assert.equal(postCount, 1, 'intervalo invertido não deve gerar POST');
  assert.match(compareForm.elements.namedItem('to_date').validationMessage, /posterior/);
  dom.window.close();
});
test('posta na URL do formulário mesmo quando o botão name=action sombreia form.action', async () => {
  let requestedUrl;
  const dom = await mount(async (url) => {
    requestedUrl = String(url);
    return { url: '/conferir/', text: async () => `${formMarkup('job-2')}` };
  });
  const form = dom.window.document.querySelector('form');
  const review = form.querySelector('[value="review"]');
  // JSDOM does not model the native named-property collision consistently;
  // reproduce the Chromium behavior observed in the live QA browser.
  Object.defineProperty(form, 'action', { configurable: true, value: review });
  assert.equal(form.action.toString(), '[object HTMLButtonElement]');
  form.dispatchEvent(new dom.window.SubmitEvent('submit', { bubbles: true, cancelable: true, submitter: review }));
  await settle();
  assert.equal(requestedUrl, '/conferir/');
  dom.window.close();
});

// End of the real-form interaction regressions.
test('cancelamento envia POST com CSRF e mantém o texto no fragmento devolvido', async () => {
  let cancelPosted = false;
  let statusPolls = 0;
  const dom = await mount(async (url, options = {}) => {
    if (String(url).includes('/status/')) {
      statusPolls += 1;
      return { ok: true, json: async () => ({ status: statusPolls > 1 ? 'cancelled' : 'running' }) };
    }
    if (String(url).includes('/resultado/')) return { ok: true, url: '/conferir/', text: async () => `${formMarkup('job-2')}<p role="status">Conferência interrompida</p>` };
    if (String(url).includes('/cancelar/')) {
      cancelPosted = true;
      assert.equal(options.method, 'POST');
      assert.equal(options.headers['X-CSRFToken'], 'csrf');
      return { ok: true, json: async () => ({ status: 'cancelling' }) };
    }
    return { ok: true, url: '/conferir/', text: async () => formMarkup('job-1').replace('data-job-status=""', 'data-job-status="queued"') };
  });
  const form = dom.window.document.querySelector('form');
  const compare = form.querySelector('[data-foundation-compare]');
  form.dispatchEvent(new dom.window.SubmitEvent('submit', { bubbles: true, cancelable: true, submitter: compare }));
  await settle();
  const cancel = dom.window.document.querySelector('[data-foundation-cancel]');
  assert.equal(cancel.hidden, false);
  cancel.click();
  await settle();
  assert.equal(cancelPosted, true);
  await new Promise((resolve) => setTimeout(resolve, 850));
  assert.match(dom.window.document.querySelector('textarea').value, /Lei nº 10\/2020/);
  assert.ok(statusPolls >= 2);
  await settle();
  dom.window.close();
});

// End of the real-form interaction regressions.

