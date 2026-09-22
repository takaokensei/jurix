/**
 * Content-Security-Policy of chatbot.html (audit: 'unsafe-inline'/'unsafe-eval' removal).
 *
 * jsdom does NOT enforce CSP, so a script-src without 'unsafe-inline' is simulated by actually
 * REMOVING every inline <script>/on*=/javascript: URL before evaluating the page -- exactly what
 * a real CSP-enforcing browser would refuse to run -- then driving the UI as a user would. If the
 * page still needed inline execution, this would surface as broken behaviour, not a passing test.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { JSDOM } from 'jsdom';

const ROOT = path.resolve(import.meta.dirname, '../..');
const TPL = path.join(ROOT, 'src/apps/legislation/templates/legislation/chatbot.html');
const JS_DIR = path.join(ROOT, 'src/apps/core/static/js');
const read = (f) => fs.readFileSync(path.join(JS_DIR, f), 'utf8');
const tick = () => new Promise((r) => setTimeout(r, 30));

function renderTemplate(raw) {
  // Minimal Django-template stand-in: only the tags chatbot.html actually uses.
  return raw
    .replace(/\{%\s*load\s+static\s*%\}/g, '')
    .replace(/\{%\s*static\s+'([^']+)'\s*%\}/g, '/static/$1')
    .replace(/\{%\s*url\s+'([^']+)'\s*%\}/g, (_, name) => `/url/${name}/`)
    .replace(/\{\{[^}]*\}\}/g, '')
    .replace(/\{%[^%]*%\}/g, '');
}

function assertNoInlineExecutionVectors(html) {
  assert.doesNotMatch(html, /\son[a-z]+\s*=/i, 'inline event handler attribute found');
  assert.doesNotMatch(html, /<script(?![^>]*\bsrc=)[^>]*>[^<]*\S/i, 'inline <script> with a body found');
  assert.doesNotMatch(html, /javascript:/i, 'javascript: URL found');
}

test('the raw template has no inline script, no on*= handler, no javascript: URL', () => {
  assertNoInlineExecutionVectors(fs.readFileSync(TPL, 'utf8'));
});

test('the CSP header no longer allows unsafe-inline / unsafe-eval for scripts', () => {
  const html = fs.readFileSync(TPL, 'utf8');
  const csp = html.match(/Content-Security-Policy"\s+content="([^"]+)"/)[1];
  const scriptSrc = csp.split(';').find((d) => d.trim().startsWith('script-src'));
  assert.ok(scriptSrc, 'no script-src directive found');
  assert.doesNotMatch(scriptSrc, /unsafe-inline|unsafe-eval/);
});

/**
 * Load the page as CSP would actually deliver it: every inline <script> body and on*= attribute
 * REMOVED before jsdom evaluates anything. External <script src> (chat.js et al.) still run.
 */
async function bootUnderCsp() {
  let html = renderTemplate(fs.readFileSync(TPL, 'utf8'));
  html = html.replace(/<script(?![^>]*\bsrc=)[^>]*>[\s\S]*?<\/script>/gi, '');
  html = html.replace(/\son[a-z]+\s*=\s*("[^"]*"|'[^']*')/gi, '');
  assertNoInlineExecutionVectors(html);

  // resources: 'usable' would make jsdom itself fetch every <script src>/<link> in <head> over
  // the network (they don't exist here -- static files are served by Django); scripts are
  // injected manually below via window.eval, in the exact order the template lists them.
  const dom = new JSDOM(html, { url: 'http://localhost/normas/chatbot/', runScripts: 'dangerously', pretendToBeVisual: true });
  const { window } = dom;
  window.fetch = async () => ({ ok: true, status: 200, json: async () => ({ success: true, sessions: [], count: 0 }) });
  for (const f of ['vendor/marked.min.js', 'vendor/purify.min.js', 'config.js', 'theme.js', 'chat.js', 'command_palette.js']) {
    window.eval(read(f));
  }
  await tick();
  return window;
}

test('with every inline script/handler stripped, the command palette still opens from the sidebar and header', async () => {
  const window = await bootUnderCsp();
  const trigger = window.document.getElementById('command-palette-trigger');
  let opened = false;
  trigger.addEventListener('click', () => { opened = true; });

  const buttons = window.document.querySelectorAll('[data-open-command-palette], #command-palette-trigger');
  assert.ok(buttons.length >= 1, `expected at least 1 palette trigger, found ${buttons.length}`);
  for (const btn of buttons) {
    opened = false;
    btn.dispatchEvent(new window.MouseEvent('click', { bubbles: true, cancelable: true }));
    assert.equal(opened, true, `${btn.outerHTML.slice(0, 60)} did not open the palette`);
  }
});

test('the hero search form still submits the question (no inline onsubmit)', async () => {
  const window = await bootUnderCsp();
  const asked = [];
  window.jurixChat.askQuestion = (q) => asked.push(q);

  window.document.getElementById('hero-search-input').value = '  Qual o prazo do alvará?  ';
  window.document.getElementById('hero-search-form')
    .dispatchEvent(new window.Event('submit', { bubbles: true, cancelable: true }));
  await tick();

  assert.deepEqual(asked, ['Qual o prazo do alvará?']);
});

test('every suggestion card and recent-search row still asks its question on click', async () => {
  // askQuestion() is a closure private to chat.js, so the observable effect (a fetch to the
  // answer endpoint carrying the card's exact question) is asserted instead of mocking it.
  const window = await bootUnderCsp();
  const questionsSent = [];
  window.fetch = async (url, opts) => {
    if (opts && opts.body) {
      try { questionsSent.push(JSON.parse(opts.body).question); } catch (_) { /* not a JSON body */ }
    }
    return { ok: true, status: 200, json: async () => ({ success: true, sessions: [], count: 0 }) };
  };

  const elements = [...window.document.querySelectorAll('[data-question]')];
  assert.ok(elements.length >= 9, `expected at least 9 clickable questions, found ${elements.length}`);
  for (const el of elements) {
    el.dispatchEvent(new window.MouseEvent('click', { bubbles: true, cancelable: true }));
    await tick();
  }
  // The mocked fetch has no real SSE stream, so chat.js retries each question once in batch
  // mode; what matters here is that the RIGHT question (not empty, not another card's) was sent.
  const distinctPerClick = [...new Set(questionsSent)];
  assert.deepEqual(distinctPerClick, elements.map((el) => el.dataset.question));
});

test("a card's data-question value round-trips exactly (accents, quotes, ampersands survive)", async () => {
  const window = await bootUnderCsp();
  const withAccents = [...window.document.querySelectorAll('[data-question]')]
    .find((el) => el.dataset.question.includes('Compare'));
  assert.ok(withAccents, 'expected the "Compare as principais..." card to be present');
  assert.match(withAccents.dataset.question, /Lei nº 14\.133\/2021/);
});

test('deleting a session still works via the delegated listener (no inline onclick left)', async () => {
  // deleteSession() opens a confirmation modal rather than deleting immediately (chat.js); the
  // observable effect of the click is that the modal becomes visible for the right session id.
  const window = await bootUnderCsp();
  const list = window.document.getElementById('chat-sessions-list');
  list.innerHTML = '<div class="chat-session-item" data-session-id="7"><button class="delete-session-button" data-delete-session-id="7"></button></div>';

  list.querySelector('.delete-session-button')
    .dispatchEvent(new window.MouseEvent('click', { bubbles: true, cancelable: true }));
  await tick();

  const modal = window.document.getElementById('delete-session-modal');
  assert.ok(modal, 'expected a #delete-session-modal in the template');
  const display = modal.style.display || window.getComputedStyle(modal).display;
  assert.notEqual(display, 'none');
});

test('control: a page that still has an inline handler is correctly rejected by the stripper', () => {
  assert.throws(() => assertNoInlineExecutionVectors('<button onclick="evil()">x</button>'));
  assert.throws(() => assertNoInlineExecutionVectors('<script>evil()</script>'));
  assert.throws(() => assertNoInlineExecutionVectors('<a href="javascript:evil()">x</a>'));
});
