import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { JSDOM } from 'jsdom';

const root = new URL('../../', import.meta.url);
const read = path => fs.readFileSync(new URL(path, root), 'utf8');

test('assistant and documents include one canonical sidebar', () => {
  for (const path of ['chatbot.html', 'workspace/base.html']) {
    const html = read(`src/apps/legislation/templates/legislation/${path}`);
    assert.match(html, /include 'legislation\/workspace\/_sidebar.html'/);
    assert.doesNotMatch(html, /<aside[^>]*id="sidebar"/);
    assert.match(html, /jurix-sidebar.css/);
    assert.match(html, /jurix-sidebar.js/);
  }
  const sidebar = read('src/apps/legislation/templates/legislation/workspace/_sidebar.html');
  assert.match(sidebar, /data-search-conversations/);
  assert.match(sidebar, /chat-sessions-list/);
  assert.doesNotMatch(sidebar, /M12 2v2m0 16v2/);
});

test('sidebar and conversation search include anonymous history without leaking HTML', async () => {
  const dom = new JSDOM(`<body data-chatbot-url="/assistente/">
    <button data-search-conversations>Pesquisar</button><div id="chat-sessions-list"></div>
    <div id="command-palette-overlay"><input id="command-palette-input"><div id="command-palette-results"></div></div>
  </body>`, { url: 'http://localhost/configuracoes/', runScripts: 'dangerously' });
  const { window } = dom;
  window.HTMLElement.prototype.scrollIntoView = () => {};
  window.JurixAnonymousHistory = {
    isAnonymous: () => true,
    list: () => [{ id: 'local-test', title: 'Cadastro protetor <img src=x>', slug: 'local-test' }],
    get: () => ({ messages: [{ content: 'animais domésticos' }] }),
  };
  window.fetch = () => { throw new Error('Anonymous history must not fetch private sessions'); };
  window.eval(read('src/apps/core/static/js/command_palette.js'));
  window.eval(read('src/apps/core/static/js/jurix-sidebar.js'));
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(window.document.querySelector('.jurix-recent-chat').getAttribute('href'), '/assistente/local-test/');
  assert.equal(window.document.querySelector('#chat-sessions-list img'), null);
  window.document.querySelector('[data-search-conversations]').click();
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(window.document.querySelectorAll('.command-palette-item').length, 1);
  const input = window.document.querySelector('input');
  input.value = 'domésticos';
  input.dispatchEvent(new window.Event('input'));
  assert.equal(window.document.querySelectorAll('.command-palette-item').length, 1);
  assert.equal(window.document.querySelector('#command-palette-results img'), null);
  window.jurixCommandPalette.close();
  dom.window.close();
});

test('assistant uses the same safe recent-chat renderer with deterministic order and native links', () => {
  const dom = new JSDOM(`<body class="figma-workspace" data-chatbot-url="/assistente/">
    <div id="chat-sessions-list"><div class="chat-session-item session-card-new" data-session-id="temp-1">pending</div></div>
  </body>`, { url: 'http://localhost/assistente/', runScripts: 'dangerously' });
  const { window } = dom;
  window.eval(read('src/apps/core/static/js/jurix-sidebar.js'));
  window.JurixSidebar.render([
    { id: 3, title: 'Mais recente <img>', updated_at: '2026-10-01T12:00:00Z' },
    { id: 2, title: 'Antiga', updated_at: '2026-09-30T12:00:00Z' },
  ], { activeSessionId: 3, preserveTemporary: true });
  const cards = [...window.document.querySelectorAll('#chat-sessions-list .chat-session-item')];
  assert.equal(cards[0].dataset.sessionId, 'temp-1');
  assert.equal(cards[1].dataset.sessionId, '3');
  assert.equal(cards[1].querySelector('a').textContent, 'Mais recente <img>');
  assert.equal(cards[1].querySelector('img'), null);
  assert.equal(cards[1].querySelector('a').getAttribute('aria-current'), 'page');
  assert.equal(cards[1].getAttribute('role'), null, 'a native link remains a link, not a synthetic nested button');
  assert.equal(cards[2].dataset.sessionId, '2');
  assert.equal(cards[2].querySelector('a').href, 'http://localhost/assistente/2/');
  dom.window.close();
});
