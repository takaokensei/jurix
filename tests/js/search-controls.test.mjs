import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { JSDOM } from 'jsdom';

const ROOT = path.resolve(import.meta.dirname, '../..');
const SCRIPT = path.join(ROOT, 'src/apps/core/static/js/jurix-search-controls.js');

test('search controls preserve keyboard semantics and handle attachment lifecycle safely', async () => {
  const dom = new JSDOM(`<!doctype html><html><body>
    <div class="figma-search-dropdown" data-control="norma_status" tabindex="0">
      <span data-control-label>Pesquisa normativa</span>
    </div>
    <div class="jurix-temporal-filter">
      <label for="jurix-as-of">Redação normativa em</label>
      <input id="jurix-as-of" data-jurix-as-of type="date">
      <button type="button" data-jurix-as-of-clear hidden>Limpar</button>
    </div>
    <input id="jurix-as-of-secondary" data-jurix-as-of type="date">
    <span data-jurix-temporal-active hidden></span>
    <div id="jurix-attachment-previews" hidden></div>
    <span class="jurix-attachment-count"></span>
    <div class="figma-search-dropdown" data-control="attachment" tabindex="0">
      <span data-control-label>Anexar documento</span>
    </div>
    <div class="figma-search-dropdown" data-control="norma_status" tabindex="0">
      <span data-control-label>Pesquisa normativa</span>
    </div>
  </body></html>`, {
    url: 'http://localhost/assistente/',
    runScripts: 'dangerously',
    pretendToBeVisual: true,
  });
  const { window } = dom;
  window.localStorage.setItem('jurix:search-options:v1', JSON.stringify({ as_of: '2021-02-29' }));
  window.eval(fs.readFileSync(SCRIPT, 'utf8'));
  window.document.dispatchEvent(new window.Event('DOMContentLoaded', { bubbles: true }));

  const asOf = window.document.getElementById('jurix-as-of');
  let changedPayload = null;
  window.addEventListener('jurix:search-options-changed', (event) => { changedPayload = event.detail; });
  assert.equal(window.JurixSearchControls.getPayload().as_of, null);
  assert.equal(asOf.value, '', 'An invalid persisted date must not silently become a historical scope');
  asOf.value = '2021-02-28';
  asOf.dispatchEvent(new window.Event('change', { bubbles: true }));
  assert.equal(window.JurixSearchControls.getPayload().as_of, '2021-02-28');
  assert.equal(window.document.getElementById('jurix-as-of-secondary').value, '2021-02-28');
  assert.equal(changedPayload.as_of, '2021-02-28');
  assert.equal(window.document.querySelector('[data-jurix-temporal-active]').textContent, 'Data histórica ativa: 28/02/2021');
  assert.equal(window.document.querySelector('[data-jurix-as-of-clear]').hidden, false);
  assert.equal(JSON.parse(window.localStorage.getItem('jurix:search-options:v1')).as_of, '2021-02-28');
  window.document.querySelector('[data-jurix-as-of-clear]').click();
  assert.equal(window.JurixSearchControls.getPayload().as_of, null);
  assert.equal(window.document.getElementById('jurix-as-of-secondary').value, '');
  assert.equal(window.document.querySelector('[data-jurix-temporal-active]').hidden, true);
  assert.equal(window.document.activeElement, asOf);

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

  control.click();
  const allNorms = [...window.document.querySelectorAll('.jurix-control-option')].find((item) => item.textContent === 'Todas as normas indexadas');
  allNorms.click();
  assert.equal(control.getAttribute('aria-expanded'), 'false');
  assert.equal(window.document.activeElement, control);
  assert.equal(control.querySelector('[data-control-label]').textContent, 'Todas as normas');
  assert.equal(window.document.querySelectorAll('[data-control="norma_status"] [data-control-label]')[1].textContent, 'Todas as normas');
  assert.equal(window.JurixSearchControls.getPayload().norma_status, 'all');
  assert.equal(changedPayload.norma_status, 'all');
  assert.equal(JSON.parse(window.localStorage.getItem('jurix:search-options:v1')).norma_status, 'all');

  const fileInput = window.document.getElementById('jurix-document-input');
  assert.equal(fileInput.accept, '.pdf,.txt,.md,.csv,.json,.docx');
  assert.equal(fileInput.multiple, true);
  const attachmentControl = window.document.querySelector('[data-control="attachment"]');
  assert.equal(attachmentControl.getAttribute('role'), 'button');
  assert.equal(attachmentControl.hasAttribute('aria-haspopup'), false);
  assert.equal(attachmentControl.hasAttribute('aria-expanded'), false);
  assert.equal(attachmentControl.hasAttribute('aria-controls'), false);
  let pickerRequests = 0;
  fileInput.addEventListener('click', () => { pickerRequests += 1; });
  attachmentControl.click();
  assert.equal(pickerRequests, 1, 'The attachment control opens the chooser without uploading a file');
  attachmentControl.focus();
  attachmentControl.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }));
  assert.equal(pickerRequests, 2, 'Enter also opens the attachment chooser');
  assert.equal(window.document.activeElement, attachmentControl, 'The ordinary button keeps its focus after chooser activation');

  const uploadCalls = [];
  const deletedIds = [];
  let failCleanupFor = null;
  window.JurixChatAPI = {
    async uploadAttachment(file) {
      uploadCalls.push(file.name);
      if (file.name === 'fail.txt') throw new Error('Falha simulada de upload');
      return { id: `fake-${file.name}`, name: file.name, size: file.size, content_type: file.type };
    },
    async deleteAttachment(id) {
      if (id === failCleanupFor) {
        failCleanupFor = null;
        throw new Error('Falha simulada de limpeza');
      }
      deletedIds.push(id);
    },
  };
  const sixFiles = Array.from({ length: 6 }, (_, index) => new window.File(['x'], `file-${index}.pdf`, { type: 'application/pdf' }));
  await assert.rejects(window.JurixSearchControls.upload(sixFiles), /até 5 documentos/i);
  assert.equal(uploadCalls.length, 0, 'A seleção acima do limite deve ser recusada antes de qualquer upload');

  await assert.rejects(window.JurixSearchControls.upload([
    new window.File(['x'], 'first.pdf', { type: 'application/pdf' }),
    new window.File(['x'], 'fail.txt', { type: 'text/plain' }),
  ]), /Falha simulada/);
  assert.deepEqual(deletedIds, ['fake-first.pdf'], 'Uploads parciais devem ser removidos se um arquivo posterior falhar');
  assert.deepEqual([...window.JurixSearchControls.getPayload().attachment_ids], []);

  failCleanupFor = 'fake-orphan.pdf';
  await assert.rejects(window.JurixSearchControls.upload([
    new window.File(['x'], 'orphan.pdf', { type: 'application/pdf' }),
    new window.File(['x'], 'fail.txt', { type: 'text/plain' }),
  ]), /permaneceram vinculados/i);
  assert.deepEqual([...window.JurixSearchControls.getPayload().attachment_ids], ['fake-orphan.pdf'], 'Uploads que não puderam ser removidos continuam visíveis para recuperação');
  window.document.querySelector('.jurix-attachment-remove').click();
  await new Promise(resolve => window.setTimeout(resolve, 0));
  assert.deepEqual([...window.JurixSearchControls.getPayload().attachment_ids], []);

  await window.JurixSearchControls.upload([new window.File(['x'], 'ok.pdf', { type: 'application/pdf' })]);
  assert.deepEqual([...window.JurixSearchControls.getPayload().attachment_ids], ['fake-ok.pdf']);
  const removeButton = window.document.querySelector('.jurix-attachment-remove');
  removeButton.click();
  await new Promise(resolve => window.setTimeout(resolve, 0));
  assert.deepEqual([...window.JurixSearchControls.getPayload().attachment_ids], []);
  assert.deepEqual(deletedIds, ['fake-first.pdf', 'fake-orphan.pdf', 'fake-ok.pdf']);

  window.JurixSearchControls.setAttachments([{ id: 'conversation-file', name: 'temporary.pdf' }]);
  window.document.dispatchEvent(new window.CustomEvent('jurix:new-conversation'));
  await new Promise(resolve => window.setTimeout(resolve, 0));
  assert.deepEqual([...window.JurixSearchControls.getPayload().attachment_ids], []);
  assert.deepEqual(deletedIds, ['fake-first.pdf', 'fake-orphan.pdf', 'fake-ok.pdf', 'conversation-file']);
  dom.window.close();
});
