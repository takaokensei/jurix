import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { JSDOM } from 'jsdom';

const ROOT = path.resolve(import.meta.dirname, '../..');
const HTML = path.join(ROOT, 'src/apps/legislation/templates/legislation/chatbot.html');
const JS = path.join(ROOT, 'src/apps/core/static/js/jurix-dynamic-suggestions.js');
const read = (file) => fs.readFileSync(file, 'utf8');

function renderTemplate(raw) {
  return raw
    .replace(/\{%\s*load\s+static\s*%\}/g, '')
    .replace(/\{%\s*static\s+'([^']+)'\s*%\}/g, '/static/$1')
    .replace(/\{%[^%]*%\}/g, '')
    .replace(/\{\{[^}]*\}\}/g, '');
}

test('welcome page contains no baked legal-question cards', () => {
  const html = read(HTML);
  assert.doesNotMatch(html, /Quais normas regulam a regularização/);
  assert.doesNotMatch(html, /14\.133\/2021/);
  assert.match(html, /jurix-dynamic-suggestions\.js/);
});

test('dynamic module renders API-provided questions', async () => {
  const dom = new JSDOM(renderTemplate(read(HTML)), {
    url: 'http://localhost/assistente/',
    runScripts: 'dangerously',
    pretendToBeVisual: true,
  });
  const { window } = dom;
  window.fetch = async () => ({
    ok: true,
    json: async () => ({
      success: true,
      count: 2,
      source: 'municipal_natal_corpus',
      suggestions: [
        {
          question: 'O que a Lei 123/2024 estabelece sobre transporte público?',
          title: 'Lei 123/2024',
          description: 'Ementa do corpus municipal.',
          identifier: 'Lei 123/2024',
        },
        {
          question: 'O que o Decreto 9/2023 estabelece sobre zoneamento?',
          title: 'Decreto 9/2023',
          description: 'Ementa do corpus municipal.',
          identifier: 'Decreto 9/2023',
        },
      ],
    }),
  });
  window.eval(read(JS));
  await window.JurixDynamicSuggestions.refresh({ force: true });
  const cards = [...window.document.querySelectorAll('#figma-suggestions-cards [data-question]')];
  assert.equal(cards.length, 2);
  assert.equal(cards[0].dataset.question, 'O que a Lei 123/2024 estabelece sobre transporte público?');
  dom.window.close();
});
