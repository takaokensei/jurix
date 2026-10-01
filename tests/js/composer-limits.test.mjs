import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { JSDOM } from 'jsdom';

const jsRoot = path.resolve(import.meta.dirname, '../../src/apps/core/static/js');
const read = (name) => fs.readFileSync(path.join(jsRoot, name), 'utf8');

test('composer follows the server limit and resets its live counter after script changes', () => {
  const dom = new JSDOM(
    '<!doctype html><body data-question-max-length="7"><form id="chat-form"><textarea id="question-textarea"></textarea></form></body>',
    { url: 'http://localhost/assistente/', runScripts: 'dangerously', pretendToBeVisual: true },
  );
  const { window } = dom;
  window.eval(read('jurix-chat-shell.js'));
  window.document.dispatchEvent(new window.Event('DOMContentLoaded', { bubbles: true }));

  const composer = window.document.getElementById('question-textarea');
  const counter = window.document.getElementById('jurix-composer-counter');
  assert.equal(composer.maxLength, 7);
  assert.equal(counter.textContent, '0/7');

  composer.value = 'abcdefghij';
  composer.dispatchEvent(new window.Event('input', { bubbles: true }));
  assert.equal(composer.value, 'abcdefg');
  assert.equal(counter.textContent, '7/7');

  composer.value = '';
  window.JurixChatShell.updateCounter();
  assert.equal(counter.textContent, '0/7');

  dom.window.close();
});
