import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { JSDOM } from 'jsdom';
import { test } from 'node:test';

const ROOT = path.resolve(import.meta.dirname, '../..');
const read = relativePath => fs.readFileSync(path.join(ROOT, relativePath), 'utf8');
const template = read('src/apps/legislation/templates/legislation/chatbot.html');
const chatStyles = read('src/apps/core/static/css/jurix-chat.css');
const sidebarStyles = read('src/apps/core/static/css/jurix-sidebar.css');
const chatScript = read('src/apps/core/static/js/chat.js');
const sidebarScript = read('src/apps/core/static/js/jurix-sidebar.js');

test('new conversation feedback highlights its sidebar row without covering the answer', () => {
  assert.match(template, /static 'css\/jurix-chat\.css' %\}\?v=20261009-session-feedback-sidebar1/);
  assert.match(template, /static 'css\/jurix-sidebar\.css' %\}\?v=20261009-short-viewport-history2/);
  assert.match(template, /static 'js\/chat\.js' %\}\?v=20261013-no-source-answer-scroll1/);
  assert.match(template, /static 'js\/jurix-sidebar\.js' %\}\?v=20261009-session-feedback-sidebar1/);
  assert.doesNotMatch(chatScript, /session-created-toast|animateSessionCreated/);
  assert.doesNotMatch(chatStyles, /\.session-created-toast/, 'the chat must not load floating success-toast styles');
  assert.match(sidebarStyles, /\.chat-session-item\.session-created-highlight\s*\{/);
  assert.match(
    sidebarStyles,
    /@media \(prefers-reduced-motion:\s*reduce\)[\s\S]*?\.chat-session-item\.session-created-highlight\s*\{\s*transition:\s*none/,
  );
  assert.match(
    chatScript,
    /await loadChatSessions\(\);\s*if \(wasNewSession\)\s*\{\s*window\.JurixSidebar\?\.highlightSessionCreated/,
    'highlight only after the saved session has been rendered in the sidebar',
  );

  const dom = new JSDOM(`<body data-chatbot-url="/assistente/">
    <div id="chat-sessions-list" aria-live="polite"></div>
    <main id="answer">Resposta longa que não deve ser coberta.</main>
  </body>`, { url: 'http://localhost/assistente/', runScripts: 'dangerously' });
  const { window } = dom;
  window.eval(sidebarScript);
  const row = window.JurixSidebar.addPending({
    clientSessionId: 'client-session-created',
    title: 'Consulta normativa',
    question: 'Consulta normativa',
  });
  window.JurixSidebar.reconcilePending('client-session-created', { session_id: 42, session_slug: 'consulta' });
  window.JurixSidebar.render([
    { id: 42, slug: 'consulta', title: 'Consulta normativa', updated_at: '2026-10-09T12:00:00Z' },
  ], { activeSessionId: 42, preserveTemporary: true });

  assert.equal(window.JurixSidebar.highlightSessionCreated(42), true);
  assert.equal(row.classList.contains('session-created-highlight'), true);
  assert.equal(window.document.querySelector('.session-created-toast'), null);
  assert.equal(window.document.querySelector('#answer').textContent, 'Resposta longa que não deve ser coberta.');
  dom.window.close();
});
