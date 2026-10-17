import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import puppeteer from 'puppeteer-core';

const baseUrl = process.env.JURIX_BASE_URL || '';
const qaRoot = process.env.JURIX_QA_ROOT || '';
const evidenceDir = process.env.JURIX_EVIDENCE_DIR || '';
const base = new URL(baseUrl);
assert.equal(base.protocol, 'http:');
assert.ok(['127.0.0.1', 'localhost'].includes(base.hostname));
assert.ok(['8280', '8281', '8282', '8283', '8287'].includes(base.port));
assert.ok(qaRoot && evidenceDir, 'isolated QA root and evidence directory are required');

const tempRoot = await fs.realpath(os.tmpdir());
const resolvedQaRoot = await fs.realpath(qaRoot);
const requestedEvidenceDir = path.resolve(evidenceDir);
await fs.mkdir(requestedEvidenceDir, { recursive: true });
const resolvedEvidenceDir = await fs.realpath(requestedEvidenceDir);
assert.ok(resolvedQaRoot.toLowerCase().startsWith(`${tempRoot.toLowerCase()}${path.sep}`));
assert.ok(resolvedEvidenceDir.toLowerCase().startsWith(`${resolvedQaRoot.toLowerCase()}${path.sep}`));

const browserCandidates = [
  process.env.PUPPETEER_EXECUTABLE_PATH,
  process.env.CHROME_BIN,
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
  'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
].filter(Boolean);
let executablePath;
for (const candidate of browserCandidates) {
  try {
    await fs.access(candidate);
    executablePath = candidate;
    break;
  } catch {
    // Only use an already-installed local browser.
  }
}
assert.ok(executablePath, 'an installed Chrome or Edge executable is required');

const browser = await puppeteer.launch({
  executablePath,
  headless: true,
  args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'],
});
try {
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  const pageErrors = [];
  page.on('pageerror', (error) => pageErrors.push(error.name));
  const response = await page.goto(new URL('/assistente/?new=1&corpus=archive-qa', baseUrl).href, {
    waitUntil: 'domcontentloaded',
    timeout: 20000,
  });
  assert.equal(response?.status(), 200);

  const question = 'Houve proposta legislativa no SAPL para alterar o Art. 59 da Lei Complementar nº 258/2024? Localize registros oficiais que citem expressamente esse dispositivo e diga se as evidências confirmam que a alteração foi promulgada ou está vigente.';
  const inputSelector = await page.$('#question-textarea') ? '#question-textarea' : '#hero-search-input';
  const formSelector = inputSelector === '#question-textarea' ? '#chat-form' : '#hero-search-form';
  await page.$eval(inputSelector, (input, value) => {
    input.value = value;
    input.dispatchEvent(new Event('input', { bubbles: true }));
  }, question);
  await page.$eval(formSelector, (form) => form.requestSubmit());
  await page.waitForFunction(() => {
    const answer = [...document.querySelectorAll('.message-assistant .message-body')].at(-1);
    const sendButton = document.getElementById('send-button');
    return answer?.textContent?.trim().length > 0
      && !answer.hasAttribute('data-streaming')
      && !answer.querySelector('.jurix-answer-pending')
      && sendButton && !sendButton.disabled;
  }, { timeout: 180000 });

  const answer = await page.$eval('.message-assistant .message-body:last-of-type', (node) => node.innerText)
    .catch(async () => page.$$eval('.message-assistant .message-body', (nodes) => nodes.at(-1)?.innerText || ''));
  assert.match(answer, /Projeto de Lei Complementar nº 12\/2025/i);
  assert.match(answer, /o cadastro de uma proposição não comprova, por si, que o texto foi aprovado, promulgado ou entrou em vigor/i);
  assert.match(answer, /Transcrição automática; metadados e segmentação ainda estão sob revisão/i);

  const sources = await page.$$eval('.message-assistant [id^="sources-"]', (containers) => {
    const latest = containers.at(-1);
    return (latest?._sourcesData || []).map((item) => ({
      citationId: item.citation_id || '',
      sourceKind: item.source_kind || '',
      label: item.citation_label || '',
      sourceUrl: item.source_url || item.sapl_url || '',
    }));
  });
  const proposal = sources.find((item) =>
    item.sourceKind === 'sapl_legislative_matter' && item.citationId === 'sapl:materia:48759');
  assert.ok(proposal, `expected the exact official PLC source; received ${JSON.stringify(sources)}`);
  assert.equal(new URL(proposal.sourceUrl).hostname, 'sapl.natal.rn.leg.br');

  const trigger = (await page.$$('.message-assistant .jurix-sources-pill-btn')).at(-1);
  assert.ok(trigger, 'the answer must expose the evidence drawer control');
  await trigger.click();
  await page.waitForFunction(() =>
    document.getElementById('jurix-sources-drawer-panel')?.getAttribute('aria-hidden') === 'false');
  const expandAll = await page.$('#jurix-sources-drawer-panel .jurix-source-group-toggle-all');
  assert.ok(expandAll, 'the drawer must offer its expand-all control');
  const expandState = await expandAll.evaluate((button) => {
    const rect = button.getBoundingClientRect();
    return {
      visible: rect.width > 0 && rect.height > 0 && getComputedStyle(button).visibility !== 'hidden',
      ariaHidden: document.getElementById('jurix-sources-drawer-panel')?.getAttribute('aria-hidden'),
      label: button.innerText,
    };
  });
  assert.ok(expandState.visible && expandState.ariaHidden === 'false', 'expand-all must be visible in the open drawer');
  await page.$eval('#jurix-sources-drawer-panel .jurix-source-group-toggle-all', (button) => button.click());
  await page.waitForFunction(() =>
    document.querySelector('#jurix-sources-drawer-panel .jurix-source-group-toggle-all')
      ?.getAttribute('aria-expanded') === 'true');

  const card = await page.$$eval('#jurix-sources-drawer-panel .jurix-rag-source', (cards) => {
    const match = cards.find((item) => /Altera o art\. 59 da Lei Complementar nº 258/i.test(item.innerText));
    return match ? {
      text: match.innerText,
      href: match.querySelector('.jurix-rag-source__open')?.href || '',
      openLabel: match.querySelector('.jurix-rag-source__open')?.innerText || '',
      target: match.querySelector('.jurix-rag-source__open')?.target || '',
    } : null;
  });
  assert.ok(card, 'the drawer must display the SAPL ementa tied to the requested article');
  assert.match(card.text, /Registro de matéria legislativa/i);
  assert.match(card.openLabel, /Abrir matéria no SAPL/i);
  assert.equal(new URL(card.href).hostname, 'sapl.natal.rn.leg.br');
  assert.equal(card.target, '_blank');
  assert.deepEqual(pageErrors, []);

  const responsiveDrawerLayouts = [];
  for (const width of [320, 360, 768, 1280]) {
    await page.setViewport({ width, height: 900 });
    await new Promise((resolve) => setTimeout(resolve, 400));
    const layout = await page.evaluate(() => {
      const panel = document.getElementById('jurix-sources-drawer-panel');
      const panelRect = panel?.getBoundingClientRect();
      const body = document.getElementById('jurix-sources-drawer-body');
      const toggle = panel?.querySelector('.jurix-source-group-toggle-all');
      const sourceLink = panel?.querySelector('.jurix-rag-source__open');
      const rect = (element) => {
        const box = element?.getBoundingClientRect();
        return box ? { left: box.left, right: box.right, width: box.width, height: box.height } : null;
      };
      return {
        viewportWidth: window.innerWidth,
        documentWidth: document.documentElement.scrollWidth,
        panel: rect(panel),
        bodyClientWidth: body?.clientWidth ?? null,
        bodyScrollWidth: body?.scrollWidth ?? null,
        expandAll: rect(toggle),
        sourceLink: rect(sourceLink),
      };
    });
    assert.ok(layout.documentWidth <= width,
      `the open sources drawer must not cause page overflow at ${width}px: ${JSON.stringify(layout)}`);
    assert.ok(layout.panel && layout.panel.left >= -1 && layout.panel.right <= width + 1,
      `the drawer must stay within the viewport at ${width}px: ${JSON.stringify(layout)}`);
    assert.ok(layout.bodyClientWidth > 0 && layout.bodyScrollWidth <= layout.bodyClientWidth + 1,
      `source evidence must reflow without horizontal drawer scrolling at ${width}px: ${JSON.stringify(layout)}`);
    assert.ok(layout.expandAll?.height >= 44 && layout.expandAll.right <= layout.panel.right,
      `expand-all must remain a usable visible target at ${width}px: ${JSON.stringify(layout)}`);
    assert.ok(layout.sourceLink?.height >= 44 && layout.sourceLink.right <= layout.panel.right,
      `the official SAPL source action must remain usable at ${width}px: ${JSON.stringify(layout)}`);
    responsiveDrawerLayouts.push(layout);
  }
  await page.setViewport({ width: 1280, height: 900 });

  const screenshot = path.join(resolvedEvidenceDir, 'pgm-sapl-related-matter-drawer.png');
  await page.screenshot({ path: screenshot, fullPage: false });
  const result = {
    status: 'passed',
    question: 'article-currentness lookup for LC 258/2024, Art. 59',
    officialMatter: proposal.label,
    sourceCount: sources.length,
    proposalCaveatShown: /não comprova, por si, que o texto foi aprovado, promulgado ou entrou em vigor/i.test(answer),
    drawerLinkHost: new URL(card.href).hostname,
    responsiveDrawerLayouts,
    pageErrors: pageErrors.length,
    screenshot,
  };
  const reportPath = path.join(resolvedEvidenceDir, 'pgm-sapl-related-matter-report.json');
  await fs.writeFile(reportPath, `${JSON.stringify(result, null, 2)}\n`, 'utf8');
  process.stdout.write(`${JSON.stringify({ ...result, report: reportPath }, null, 2)}\n`);
} finally {
  await browser.close();
}
