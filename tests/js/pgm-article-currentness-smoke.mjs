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
assert.ok(['8030', '8280', '8281', '8282', '8283', '8284'].includes(base.port));
assert.ok(qaRoot && evidenceDir, 'isolated QA root and evidence directory are required');

const tempRoot = await fs.realpath(os.tmpdir());
const resolvedQaRoot = await fs.realpath(qaRoot);
await fs.mkdir(evidenceDir, { recursive: true });
const resolvedEvidenceDir = await fs.realpath(evidenceDir);
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
  const page = await browser.newPage();
  await page.setViewport({ width: 1280, height: 900 });
  const pageErrors = [];
  page.on('pageerror', (error) => pageErrors.push(error.name));
  const response = await page.goto(new URL('/assistente/?new=1&corpus=archive-qa', baseUrl).href, {
    waitUntil: 'domcontentloaded',
    timeout: 20000,
  });
  assert.equal(response?.status(), 200);

  const question = 'O art. 18 da Lei Complementar nº 120/2010 foi alterado ou revogado? Identifique o ato modificador e compare a redação anterior e posterior, se houver evidência no acervo.';
  await page.$eval('#question-textarea', (input, value) => {
    input.value = value;
    input.dispatchEvent(new Event('input', { bubbles: true }));
  }, question);
  await page.$eval('#chat-form', (form) => form.requestSubmit());
  await page.waitForFunction(() => {
    const answers = [...document.querySelectorAll('.message-assistant .message-body')];
    const answer = answers.at(-1);
    const sendButton = document.getElementById('send-button');
    return answer?.textContent?.trim().length > 0
      && !answer.hasAttribute('data-streaming')
      && !answer.querySelector('.jurix-answer-pending')
      && sendButton && !sendButton.disabled;
  }, { timeout: 180000 });

  const answer = await page.$$eval('.message-assistant .message-body', (nodes) => nodes.at(-1)?.innerText || '');
  assert.match(
    answer,
    /^Com as evidências disponíveis, não foi possível confirmar se o dispositivo consultado foi alterado ou revogado\./i,
    'a currentness question must lead with the unresolved legal conclusion, not merely announce search results',
  );
  assert.match(answer, /pendente de revisão/i);
  assert.match(answer, /não comprovam promulgação ou vigência/i);
  assert.match(answer, /não demonstram, por si, aprovação, promulgação, vigência ou validade/i);
  assert.doesNotMatch(answer, /o art\. 18 (?:foi|está) (?:alterado|revogado)/i);

  const sourceData = await page.$$eval('.message-assistant [id^="sources-"]', (containers) => {
    const latest = containers.at(-1);
    return (latest?._sourcesData || []).map((item) => ({
      citationId: item.citation_id || '',
      sourceKind: item.source_kind || '',
      label: item.citation_label || '',
      relation: item.relation_label || '',
      href: item.source_url || item.sapl_url || '',
    }));
  });
  assert.ok(sourceData.some((source) => source.sourceKind === 'sapl_legislative_matter'),
    `the query should expose the official related matter as a distinct source: ${JSON.stringify(sourceData)}`);
  assert.ok(sourceData.some((source) => source.sourceKind === 'archive'),
    `the archived PDF should retain its structured archive source kind: ${JSON.stringify(sourceData)}`);
  assert.ok(sourceData.some((source) => source.citationId.startsWith('qa:')
    && /Lei Complementar nº 120\/2010, Art\. 18/i.test(source.label)),
    `the archived article source should be retained: ${JSON.stringify(sourceData)}`);

  const conversationUrl = page.url();
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => {
    const answers = [...document.querySelectorAll('.message-assistant .message-body')];
    const latest = answers.at(-1);
    const sources = latest?.closest('.message-content')?.querySelector('[id^="sources-"]');
    return latest?.textContent?.trim()
      && !latest.hasAttribute('data-streaming')
      && Array.isArray(sources?._sourcesData)
      && sources._sourcesData.length >= 2;
  }, { timeout: 15000 });
  assert.equal(page.url(), conversationUrl, 'refresh must preserve the conversation URL');
  const restoredSourceKinds = await page.$$eval('.message-assistant [id^="sources-"]', (containers) => {
    const latest = containers.at(-1);
    return (latest?._sourcesData || []).map((source) => source.source_kind || '');
  });
  assert.ok(restoredSourceKinds.includes('archive'),
    `refresh must restore the archived PDF source kind: ${JSON.stringify(restoredSourceKinds)}`);
  assert.ok(restoredSourceKinds.includes('sapl_legislative_matter'),
    `refresh must restore the SAPL matter source kind: ${JSON.stringify(restoredSourceKinds)}`);
  assert.deepEqual(pageErrors, []);

  const responsiveLayouts = [];
  for (const width of [320, 360, 768, 1280, 1920]) {
    await page.setViewport({ width, height: 900 });
    await page.$eval('#messages-container', (container) => { container.scrollTop = container.scrollHeight; });
    await new Promise((resolve) => setTimeout(resolve, 100));
    const layout = await page.evaluate(() => {
      const answer = [...document.querySelectorAll('.message-assistant .message-body')].at(-1);
      const composer = document.querySelector('#conversation-input-bar');
      const sources = [...document.querySelectorAll('.message-assistant .jurix-sources-pill-btn')].at(-1);
      return {
        viewportWidth: window.innerWidth,
        documentWidth: document.documentElement.scrollWidth,
        answerBottom: answer?.getBoundingClientRect().bottom ?? null,
        composerTop: composer?.getBoundingClientRect().top ?? null,
        sourcesBottom: sources?.getBoundingClientRect().bottom ?? null,
        sourceControlPresent: Boolean(sources?.getClientRects().length),
        messageScrollTop: document.querySelector('#messages-container')?.scrollTop ?? null,
      };
    });
    assert.ok(layout.documentWidth <= width,
      `currentness conversation must not overflow horizontally at ${width}px: ${JSON.stringify(layout)}`);
    assert.ok(layout.answerBottom <= layout.composerTop,
      `the final answer must be readable above the fixed composer at ${width}px: ${JSON.stringify(layout)}`);
    assert.equal(layout.sourceControlPresent, true,
      `the consulted-sources control must remain visible at ${width}px`);
    assert.ok(layout.sourcesBottom <= layout.composerTop,
      `the consulted-sources control must remain above the composer at ${width}px: ${JSON.stringify(layout)}`);
    responsiveLayouts.push(layout);
  }
  const answerEndLayout = responsiveLayouts.find((layout) => layout.viewportWidth === 1280);

  const screenshot = path.join(resolvedEvidenceDir, 'pgm-article-currentness.png');
  await page.screenshot({ path: screenshot, fullPage: false });
  const report = {
    status: 'passed',
    case: 'LC 120/2010, Art. 18 — currentness question; archived PDF remains unreviewed',
    conclusionStartsWithUncertainty: true,
    proposalNotPresentedAsPromulgatedLaw: true,
    sourceKinds: [...new Set(sourceData.map((source) => source.sourceKind))],
    sourceCount: sourceData.length,
    pageErrors: pageErrors.length,
    answerEndLayout,
    responsiveLayouts,
    screenshot,
  };
  const reportPath = path.join(resolvedEvidenceDir, 'pgm-article-currentness-report.json');
  await fs.writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`, { flag: 'wx' });
  process.stdout.write(`${JSON.stringify({ ...report, report: reportPath }, null, 2)}\n`);
} finally {
  await browser.close();
}
