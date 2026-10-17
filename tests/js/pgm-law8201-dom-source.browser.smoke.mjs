import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import puppeteer from 'puppeteer-core';

const baseUrl = process.env.JURIX_BASE_URL || 'http://127.0.0.1:8287';
const qaRoot = process.env.JURIX_QA_ROOT || '';
const parsedBase = new URL(baseUrl);
assert.equal(parsedBase.protocol, 'http:');
assert.ok(['127.0.0.1', 'localhost'].includes(parsedBase.hostname));
assert.equal(parsedBase.port, '8287', 'this smoke is restricted to the local normative QA web app');
assert.ok(qaRoot, 'JURIX_QA_ROOT is required for screenshots');

const tempRoot = await fs.realpath(os.tmpdir());
const resolvedRoot = await fs.realpath(qaRoot);
assert.ok(resolvedRoot.toLowerCase().startsWith(tempRoot.toLowerCase() + path.sep));
const evidenceDir = path.join(resolvedRoot, `law8201-dom-source-${Date.now()}`);
await fs.mkdir(evidenceDir, { recursive: true });

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
    // Try only known, already-installed browser locations.
  }
}
assert.ok(executablePath, 'an installed Chrome or Edge executable is required');

const question = 'O que prevê o Art. 1º da Lei Ordinária nº 8.201/2026? Cite o dispositivo e mostre as fontes usadas.';
const officialPdf = 'https://www2.natal.rn.gov.br/_anexos/publicacao/dom/dom_20260910_075f1b50bbc0e389191c154d55d35862.pdf';
const browser = await puppeteer.launch({
  executablePath,
  headless: true,
  args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'],
});

try {
  const page = await browser.newPage();
  const failures = [];
  let streamStatus = null;
  page.on('pageerror', (error) => failures.push(error.name));
  page.on('response', (response) => {
    if (new URL(response.url()).pathname === '/api/v1/search/answer/stream/') {
      streamStatus = response.status();
    }
  });

  await page.setViewport({ width: 1440, height: 1000 });
  const response = await page.goto(new URL('/assistente/?corpus=archive-qa', baseUrl).href, {
    waitUntil: 'domcontentloaded',
    timeout: 20000,
  });
  assert.equal(response?.status(), 200);
  assert.equal(await page.$eval('meta[name="jurix-authenticated"]', (meta) => meta.content), 'false');
  assert.equal(await page.$eval('body', (body) => body.dataset.qaArchiveCorpus), 'true');

  await page.$eval('#question-textarea', (input, value) => {
    input.value = value;
    input.dispatchEvent(new Event('input', { bubbles: true }));
  }, question);
  await page.evaluate(() => document.getElementById('chat-form').requestSubmit());
  try {
    await page.waitForFunction(() => {
      const answers = [...document.querySelectorAll('.message-assistant .message-body')];
      const latest = answers.at(-1);
      const sources = latest?.closest('.message-content')?.querySelector('[id^="sources-"]');
      const sourceCount = Array.isArray(sources?._sourcesData) ? sources._sourcesData.length : 0;
      const answerText = (latest?.innerText || '').replace(/\s+/g, ' ');
      return /Cadastro Municipal de Protetores de Animais/i.test(answerText)
        && /plataforma digital/i.test(answerText)
        && sourceCount >= 1
        && !latest?.hasAttribute('data-streaming')
        && !latest?.classList.contains('is-streaming');
    }, { timeout: 30000 });
  } catch (error) {
    const diagnostics = await page.evaluate(() => ({
      answerCount: document.querySelectorAll('.message-assistant .message-body').length,
      answerText: [...document.querySelectorAll('.message-assistant .message-body')].at(-1)?.innerText || '',
      buttonDisabled: document.getElementById('send-button')?.disabled ?? null,
      streamingAttr: [...document.querySelectorAll('.message-assistant .message-body')].at(-1)?.hasAttribute('data-streaming') ?? null,
      streamingClass: [...document.querySelectorAll('.message-assistant .message-body')].at(-1)?.classList.contains('is-streaming') ?? null,
      sources: [...document.querySelectorAll('.message-assistant .message-body')].at(-1)?.closest('.message-content')?.querySelector('[id^="sources-"]')?._sourcesData?.length ?? null,
      streamStatusText: document.getElementById('rag-stream-status')?.innerText || '',
      pageText: document.body.innerText.slice(-1200),
    }));
    throw new Error(`assistant UI did not render the expected law article (HTTP ${streamStatus}): ${JSON.stringify(diagnostics)}`, { cause: error });
  }

  const answer = await page.evaluate(() => {
    const body = [...document.querySelectorAll('.message-assistant .message-body')].at(-1);
    const container = body?.closest('.message-content')?.querySelector('[id^="sources-"]');
    const pill = container?.querySelector('.jurix-sources-pill-btn');
    const sources = Array.isArray(container?._sourcesData) ? container._sourcesData : [];
    return {
      text: body?.innerText || '',
      streaming: body?.hasAttribute('data-streaming') || false,
      streamingClass: body?.classList.contains('is-streaming') || false,
      pillText: pill?.innerText || '',
      sources: sources.map((source) => ({
        kind: source.source_kind,
        label: source.citation_label,
        url: source.pdf_url || source.source_url || source.url || null,
        page: source.page || null,
      })),
    };
  });
  const normalizedAnswer = answer.text.replace(/\s+/g, ' ');
  assert.equal(streamStatus, 200, 'the anonymous archive-QA stream must succeed');
  assert.match(normalizedAnswer, /Art\. 1/i);
  assert.match(normalizedAnswer, /Cadastro Municipal de Protetores de Animais/i);
  assert.match(normalizedAnswer, /plataforma digital/i);
  assert.match(normalizedAnswer, /participa[cç][aã]o em programas, a[cç][oõ]es e benef[ií]cios/i);
  assert.equal(answer.streaming || answer.streamingClass, false, 'the completed answer must leave streaming state');
  assert.match(answer.text, /transcri[cç][aã]o.*n[aã]o passou por revis[aã]o humana/i);
  assert.doesNotMatch(answer.text, /N[aã]o localizei uma evid[eê]ncia leg[ií]vel/i);
  assert.match(answer.pillText, /DOM oficial.*extra[cç][aã]o n[aã]o revisada/i);
  const domSource = answer.sources.find((source) => source.kind === 'official_gazette_extraction');
  assert.ok(domSource, 'the consulted-sources state must retain the official gazette evidence');
  assert.equal(domSource.url, officialPdf);
  assert.equal(domSource.page, 1);

  await page.screenshot({ path: path.join(evidenceDir, 'answer-desktop.png'), fullPage: true });
  await page.click('.message-assistant .jurix-sources-pill-btn');
  await page.waitForFunction(() => document.querySelector('#jurix-sources-drawer-panel')?.getAttribute('aria-hidden') === 'false');
  const drawerEvidence = await page.evaluate((expectedPdf) => {
    const drawer = document.getElementById('jurix-sources-drawer-panel');
    const title = document.getElementById('sources-drawer-title')?.textContent || '';
    const link = [...drawer.querySelectorAll('.jurix-rag-source__open')]
      .find((anchor) => anchor.href.startsWith(expectedPdf));
    return {
      title,
      links: [...drawer.querySelectorAll('.jurix-rag-source__open')].map((anchor) => ({ href: anchor.href, text: anchor.textContent.trim() })),
      cards: [...drawer.querySelectorAll('.jurix-rag-source')].map((card) => card.innerText.slice(0, 180)),
      linkFound: Boolean(link),
      linkText: link?.textContent?.trim() || '',
      target: link?.target || '',
      rel: link?.rel || '',
      href: link?.href || '',
    };
  }, officialPdf);
  assert.match(drawerEvidence.title, /Fontes Consultadas/i);
  assert.equal(drawerEvidence.linkFound, true, `the drawer must expose the official DOM PDF: ${JSON.stringify(drawerEvidence)}`);
  assert.equal(new URL(drawerEvidence.href).hash, '#page=1');
  assert.match(drawerEvidence.linkText, /Di[aá]rio Oficial/i);
  assert.equal(drawerEvidence.target, '_blank');
  assert.match(drawerEvidence.rel, /noopener/);

  await page.setViewport({ width: 390, height: 844, isMobile: true, hasTouch: true });
  if (await page.$eval('#jurix-sources-drawer-panel', (panel) => panel.getAttribute('aria-hidden') !== 'false')) {
    await page.click('.message-assistant .jurix-sources-pill-btn');
    await page.waitForFunction(() => document.querySelector('#jurix-sources-drawer-panel')?.getAttribute('aria-hidden') === 'false');
  }
  const mobileLayout = await page.evaluate(() => ({
    viewportWidth: innerWidth,
    documentWidth: document.documentElement.scrollWidth,
    drawerWidth: Math.round(document.getElementById('jurix-sources-drawer-panel').getBoundingClientRect().width),
    drawerVisible: document.getElementById('jurix-sources-drawer-panel')?.getAttribute('aria-hidden') === 'false',
  }));
  assert.ok(mobileLayout.documentWidth <= mobileLayout.viewportWidth, `mobile layout must not overflow horizontally: ${JSON.stringify(mobileLayout)}`);
  assert.equal(mobileLayout.drawerVisible, true);
  await page.screenshot({ path: path.join(evidenceDir, 'sources-mobile.png'), fullPage: true });

  await page.setViewport({ width: 1440, height: 1000 });
  if (await page.$eval('#jurix-sources-drawer-panel', (panel) => panel.getAttribute('aria-hidden') !== 'false')) {
    await page.click('.message-assistant .jurix-sources-pill-btn');
    await page.waitForFunction(() => document.querySelector('#jurix-sources-drawer-panel')?.getAttribute('aria-hidden') === 'false');
  }
  let popup;
  const sourceGroup = await page.$('#jurix-sources-drawer-body details.jurix-source-group');
  assert.ok(sourceGroup, 'the sources drawer must group the official evidence');
  if (!(await sourceGroup.evaluate((group) => group.open))) {
    await sourceGroup.$eval('summary', (summary) => summary.click());
  }
  await page.waitForFunction((url) => {
    const link = [...document.querySelectorAll('#jurix-sources-drawer-body .jurix-rag-source__open')]
      .find((item) => item.href.startsWith(url));
    return Boolean(link && link.getClientRects().length);
  }, {}, officialPdf);
  await page.evaluate((url) => {
    const link = [...document.querySelectorAll('#jurix-sources-drawer-body .jurix-rag-source__open')]
      .find((item) => item.href.startsWith(url));
    link?.scrollIntoView({ block: 'center', inline: 'nearest' });
  }, officialPdf);
  await new Promise((resolve) => setTimeout(resolve, 350));
  const popupPromise = new Promise((resolve, reject) => {
    const timeout = setTimeout(() => reject(new Error('official PDF link did not open a new tab')), 15000);
    page.once('popup', (opened) => {
      clearTimeout(timeout);
      popup = opened;
      resolve(opened);
    });
  });
  const officialLink = await page.$(`#jurix-sources-drawer-body .jurix-rag-source__open[href^="${officialPdf}"]`);
  assert.ok(officialLink, 'official gazette link must be present');
  await officialLink.click({ delay: 20 });
  await popupPromise;
  await popup.waitForFunction((url) => location.href.startsWith(url), { timeout: 15000 }, officialPdf);
  const pdfCheck = await fetch(popup.url(), { headers: { Range: 'bytes=0-2047' } });
  assert.ok([200, 206].includes(pdfCheck.status), 'the official source must return PDF bytes when opened');
  assert.match(pdfCheck.headers.get('content-type') || '', /application\/pdf/i);
  assert.deepEqual(failures, [], 'the page must not emit uncaught JavaScript errors');

  const report = {
    status: 'passed',
    scenario: 'law_8201_2026_official_dom_article_source_ui',
    authenticated: false,
    stream_status: streamStatus,
    stream_state_still_active_after_completion: answer.streaming || answer.streamingClass,
    reason: 'official DOM extraction is surfaced as unreviewed and not currentness-certified',
    answer_excerpt: answer.text,
    source: domSource,
    drawer: drawerEvidence,
    mobile: mobileLayout,
    opened_pdf_status: pdfCheck.status,
    opened_pdf_content_type: pdfCheck.headers.get('content-type'),
    page_errors: failures,
    evidence_dir: evidenceDir,
  };
  await fs.writeFile(path.join(evidenceDir, 'report.json'), JSON.stringify(report, null, 2));
  process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
  await popup.close();
  await page.close();
} finally {
  await browser.close();
}
