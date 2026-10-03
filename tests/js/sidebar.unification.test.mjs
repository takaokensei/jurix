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

test('pending assistant session reconciles in place into the canonical native-link row', () => {
  const dom = new JSDOM(`<body class="figma-workspace" data-chatbot-url="/assistente/">
    <div id="chat-sessions-list"><div class="history-empty">Nenhuma conversa ainda</div></div>
  </body>`, { url: 'http://localhost/assistente/', runScripts: 'dangerously' });
  const { window } = dom;
  window.eval(read('src/apps/core/static/js/jurix-sidebar.js'));
  const clientSessionId = 'client-session-test';
  const pendingRow = window.JurixSidebar.addPending({
    clientSessionId,
    question: 'Consulta sobre proteção animal',
    title: 'Consulta sobre proteção animal',
  });
  assert.ok(pendingRow);
  assert.equal(pendingRow.dataset.sessionPending, 'true');
  assert.equal(pendingRow.querySelector('[role="button"]'), null);
  assert.equal(pendingRow.querySelector('button button'), null);
  assert.equal(pendingRow.querySelector('.chat-session-main').getAttribute('href'), '/assistente/');
  assert.equal(pendingRow.querySelector('[data-session-menu-trigger]').disabled, true);
  assert.equal(window.document.querySelector('.history-empty'), null);
  assert.equal(window.JurixSidebar.markPendingFailed(clientSessionId), true);
  assert.equal(pendingRow.querySelector('[data-session-menu-trigger]').disabled, false);
  assert.equal(window.JurixSidebar.markPendingRunning(clientSessionId), true);
  assert.equal(pendingRow.querySelector('[data-session-menu-trigger]').disabled, true);
  assert.equal(window.JurixSidebar.reconcilePending(clientSessionId, { session_id: 3, session_slug: 'session-3' }), pendingRow);
  assert.equal(pendingRow.dataset.sessionId, '3');

  window.JurixSidebar.render([
    { id: 3, slug: 'session-3', title: 'Mais recente <img>', updated_at: '2026-10-01T12:00:00Z' },
    { id: 2, title: 'Antiga', updated_at: '2026-09-30T12:00:00Z' },
  ], { activeSessionId: 3, preserveTemporary: true });
  const cards = [...window.document.querySelectorAll('#chat-sessions-list .chat-session-item')];
  assert.equal(cards[0], pendingRow, 'the same row DOM node must survive session reconciliation');
  assert.equal(cards.filter(row => row.dataset.sessionId === '3').length, 1);
  assert.equal(cards[0].dataset.sessionPending, undefined);
  assert.equal(cards[0].querySelector('.chat-session-main').textContent, 'Mais recente <img>');
  assert.equal(cards[0].querySelector('img'), null);
  assert.equal(cards[0].querySelector('.chat-session-main').getAttribute('aria-current'), 'page');
  assert.equal(cards[0].getAttribute('role'), null, 'a native link remains a link, not a synthetic nested button');
  assert.equal(cards[0].querySelector('.chat-session-main').nextElementSibling.matches('button'), true);
  assert.equal(cards[1].dataset.sessionId, '2');
  assert.equal(cards[1].querySelector('a').href, 'http://localhost/assistente/2/');
  dom.window.close();
});

test('failed local pending session can be resumed and removed without nested controls', () => {
  const dom = new JSDOM('<body data-chatbot-url="/assistente/"><div id="chat-sessions-list"></div></body>', {
    url: 'http://localhost/assistente/', runScripts: 'dangerously',
  });
  const { window } = dom;
  window.HTMLDialogElement.prototype.showModal = function showModal() { this.open = true; };
  window.HTMLDialogElement.prototype.close = function close() { this.open = false; };
  window.eval(read('src/apps/core/static/js/jurix-sidebar.js'));
  const row = window.JurixSidebar.addPending({ clientSessionId: 'client-failed', question: 'Retomar minha pergunta' });
  window.JurixSidebar.markPendingFailed('client-failed');
  row.querySelector('.chat-session-main').click();
  const trigger = row.querySelector('[data-session-menu-trigger]');
  trigger.click();
  const removeAction = window.document.querySelector('[role="menuitem"]');
  assert.equal(removeAction.textContent, 'Remover pesquisa pendente');
  removeAction.click();
  assert.equal(window.document.querySelector('#jurix-session-dialog').open, true);
  window.document.querySelector('.jurix-session-dialog__confirm').click();
  assert.equal(window.document.querySelector('.chat-session-item'), null);
  assert.equal(window.document.querySelector('#chat-sessions-list').textContent, 'Nenhuma conversa ainda');
  dom.window.close();
});

test('recent conversations keep row actions outside the scroll edge and sort pinned chats first', () => {
  const dom = new JSDOM(`<body class="figma-workspace" data-chatbot-url="/assistente/">
    <div id="chat-sessions-list"></div>
  </body>`, { url: 'http://localhost/assistente/', runScripts: 'dangerously' });
  const { window } = dom;
  window.eval(read('src/apps/core/static/js/jurix-sidebar.js'));
  window.JurixSidebar.render([
    { id: 1, title: 'Conversa recente', updated_at: '2026-10-02T12:00:00Z' },
    { id: 2, title: 'Conversa fixada', updated_at: '2026-09-01T12:00:00Z', is_pinned: true },
  ]);
  const rows = [...window.document.querySelectorAll('.chat-session-item')];
  assert.deepEqual(rows.map(row => row.dataset.sessionId), ['2', '1']);
  assert.ok(rows[0].querySelector('[aria-label="Conversa fixada"] svg'));
  const trigger = rows[0].querySelector('[data-session-menu-trigger]');
  trigger.click();
  const menu = window.document.querySelector('[role="menu"]');
  assert.ok(menu);
  assert.deepEqual(
    [...menu.querySelectorAll('[role="menuitem"]')].map(item => item.textContent),
    ['Renomear', 'Desafixar', 'Excluir conversa'],
  );
  window.document.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  assert.equal(window.document.querySelector('[role="menu"]'), null);
  assert.equal(window.document.activeElement, trigger);
  dom.window.close();
});

test('anonymous conversation pin state persists in local history', () => {
  const dom = new JSDOM('<body data-authenticated="false"></body>', {
    url: 'http://localhost/assistente/', runScripts: 'dangerously',
  });
  const { window } = dom;
  window.eval(read('src/apps/core/static/js/jurix-anonymous-history.js'));
  const sessionId = window.JurixAnonymousHistory.ensureSession(null, 'Pergunta inicial');
  assert.equal(window.JurixAnonymousHistory.setPinned(sessionId, true), true);
  assert.equal(window.JurixAnonymousHistory.list()[0].is_pinned, true);
  dom.window.close();
});
