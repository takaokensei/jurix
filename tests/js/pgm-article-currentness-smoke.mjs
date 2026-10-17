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
assert.ok(['8030', '8280', '8281', '8282', '8283', '8284', '8287'].includes(base.port));
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

  let generationRequest = null;
  page.on('request', (request) => {
    if (new URL(request.url()).pathname !== '/api/v1/search/answer/stream/') return;
    if (generationRequest !== null) return;
    try {
      const body = JSON.parse(request.postData() || '{}');
      const providerConfig = body.llm_provider;
      generationRequest = {
        providerFieldPresent: Object.hasOwn(body, 'llm_provider'),
        providerConfigShape: providerConfig === null ? 'null'
          : Array.isArray(providerConfig) ? 'array'
            : typeof providerConfig,
        providerConfigKeys: providerConfig && typeof providerConfig === 'object'
          ? Object.keys(providerConfig)
          : [],
        provider: typeof providerConfig?.provider === 'string' ? providerConfig.provider : null,
        model: body.model || null,
        archiveQa: body.qa_archive_corpus === true,
      };
    } catch {
      generationRequest = {
        providerFieldPresent: false,
        providerConfigShape: 'invalid-json',
        providerConfigKeys: [],
        provider: null,
        model: null,
        archiveQa: false,
      };
    }
  });

  await page.evaluate(() => {
    window.__pgmStreamTrace = {
      submittedAt: null,
      sourcesAtMs: null,
      firstTextAtMs: null,
      completedAtMs: null,
      sendDisabledObserved: false,
    };
    const observer = new MutationObserver(() => {
      const trace = window.__pgmStreamTrace;
      if (trace.submittedAt === null) return;
      const elapsed = Math.round(performance.now() - trace.submittedAt);
      const answer = [...document.querySelectorAll('.message-assistant .message-body')].at(-1);
      const sources = answer?.closest('.message-content')?.querySelector('.jurix-sources-pill-btn');
      if (trace.sourcesAtMs === null && sources) trace.sourcesAtMs = elapsed;
      const hasFinalContent = Boolean(answer?.textContent?.trim())
        && !answer?.querySelector('.jurix-answer-pending');
      if (trace.firstTextAtMs === null && hasFinalContent && answer?.hasAttribute('data-streaming')) {
        trace.firstTextAtMs = elapsed;
      }
      const sendButton = document.getElementById('send-button');
      if (sendButton?.disabled) trace.sendDisabledObserved = true;
      if (trace.completedAtMs === null && hasFinalContent && answer
        && !answer.hasAttribute('data-streaming')) {
        trace.completedAtMs = elapsed;
      }
    });
    observer.observe(document.body, {
      subtree: true,
      childList: true,
      characterData: true,
      attributes: true,
    });
  });

  const question = 'O art. 18 da Lei Complementar nº 120/2010 foi alterado ou revogado por atos promulgados posteriores? Compare as redações somente se houver evidência revisada no acervo.';
  await page.$eval('#question-textarea', (input, value) => {
    input.value = value;
    input.dispatchEvent(new Event('input', { bubbles: true }));
  }, question);
  await page.evaluate(() => {
    window.__pgmStreamTrace.submittedAt = performance.now();
    document.getElementById('chat-form').requestSubmit();
  });
  await page.waitForFunction(() => {
    const answers = [...document.querySelectorAll('.message-assistant .message-body')];
    const answer = answers.at(-1);
    const sendButton = document.getElementById('send-button');
    return answer?.textContent?.trim().length > 0
      && !answer.hasAttribute('data-streaming')
      && !answer.querySelector('.jurix-answer-pending')
      && sendButton && !sendButton.disabled;
  }, { timeout: 180000 });
  await new Promise((resolve) => setTimeout(resolve, 100));

  const streaming = await page.evaluate(() => ({
    sourcesAtMs: window.__pgmStreamTrace.sourcesAtMs,
    firstTextAtMs: window.__pgmStreamTrace.firstTextAtMs,
    completedAtMs: window.__pgmStreamTrace.completedAtMs,
    sendDisabledObserved: window.__pgmStreamTrace.sendDisabledObserved,
  }));
  assert.ok(Number.isFinite(streaming.sourcesAtMs), 'the sources control must appear during the active answer');
  assert.ok(Number.isFinite(streaming.firstTextAtMs), 'answer text must be observed while the message is still streaming');
  assert.ok(Number.isFinite(streaming.completedAtMs), 'the stream completion must be observed');
  assert.ok(streaming.sourcesAtMs <= streaming.completedAtMs, 'sources must appear no later than stream completion');
  assert.ok(streaming.firstTextAtMs < streaming.completedAtMs, 'the answer must render incrementally before completion');
  assert.equal(streaming.sendDisabledObserved, true, 'the send control must indicate the active generation');
  assert.ok(
    generationRequest.provider === 'ollama'
      || (generationRequest.provider === null
        && (generationRequest.providerConfigShape === 'null'
          || (generationRequest.providerConfigShape === 'object'
            && !generationRequest.providerConfigKeys.includes('provider')))),
    'the request must select Ollama or omit the provider so the backend applies its Ollama default',
  );
  assert.equal(generationRequest.model, null, 'the live test should use the QA server model default');
  assert.equal(generationRequest.archiveQa, true, 'the live test must query the isolated QA archive');
  generationRequest.effectiveProvider = generationRequest.provider || 'ollama (backend default)';

  const answer = await page.$$eval('.message-assistant .message-body', (nodes) => nodes.at(-1)?.innerText || '');
  assert.match(
    answer,
    /^Com as evidências disponíveis, não foi possível confirmar se o dispositivo consultado foi alterado ou revogado(?:\.|,)/i,
    'a currentness question must lead with the unresolved legal conclusion, not merely announce search results',
  );
  assert.match(answer, /O PDF arquivado registra a redação de origem/i);
  assert.match(answer, /não está associada a uma cadeia de alterações e revogações vinculada e revisada/i);
  assert.doesNotMatch(answer, /o art\. 18 (?:foi|está) (?:alterado|revogado)/i);
  assert.doesNotMatch(answer, /projeto de lei|proposição|em tramitação/i);

  const sourceData = await page.$$eval('.message-assistant [id^="sources-"]', (containers) => {
    const latest = containers.at(-1);
    return (latest?._sourcesData || []).map((item) => ({
      citationId: item.citation_id || '',
      sourceKind: item.source_kind || '',
      label: item.citation_label || '',
      relation: item.relation_label || '',
      page: item.page || null,
      href: item.source_url || item.pdf_url || item.sapl_url || '',
    }));
  });
  assert.ok(sourceData.some((source) => source.sourceKind === 'archive'),
    `the archived PDF should retain its structured archive source kind: ${JSON.stringify(sourceData)}`);
  assert.ok(sourceData.some((source) => source.citationId.startsWith('qa:')
    && /Lei Complementar nº 120\/2010, Art\. 18/i.test(source.label)),
    `the archived article source should be retained: ${JSON.stringify(sourceData)}`);
  assert.equal(sourceData.some((source) =>
    ['sapl_legislative_matter', 'sapl_matter_original_pdf'].includes(source.sourceKind)), false,
  `projects of law are outside the enacted-norm RAG scope for this query: ${JSON.stringify(sourceData)}`);

  await page.click('.message-assistant .jurix-sources-pill-btn:last-of-type');
  await page.waitForFunction(() => {
    const panel = document.getElementById('jurix-sources-drawer-panel');
    return panel?.classList.contains('is-open');
  }, { timeout: 5000 });
  const archiveLink = await page.$eval(
    '#jurix-sources-drawer-panel a[aria-label*="Abrir PDF do acervo"]',
    (link) => ({ href: link.href, target: link.target, rel: link.rel, label: link.getAttribute('aria-label') }),
  );
  const renderedArchiveUrl = new URL(archiveLink.href);
  assert.equal(renderedArchiveUrl.origin, base.origin,
    'the archived law must open through the isolated local QA PDF route');
  assert.match(renderedArchiveUrl.pathname, /^\/normas\/documentos\/[^/]+\/pdf\/$/,
    'the cited archived law must resolve to its local PDF viewer');
  assert.equal(archiveLink.target, '_blank');
  assert.match(archiveLink.rel, /noopener/);
  assert.match(archiveLink.label, /^Abrir PDF do acervo:/);

  const conversationUrl = page.url();
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => {
    const answers = [...document.querySelectorAll('.message-assistant .message-body')];
    const latest = answers.at(-1);
    const sources = latest?.closest('.message-content')?.querySelector('[id^="sources-"]');
    return latest?.textContent?.trim()
      && !latest.hasAttribute('data-streaming')
      && Array.isArray(sources?._sourcesData)
      && sources._sourcesData.length >= 1;
  }, { timeout: 15000 });
  assert.equal(page.url(), conversationUrl, 'refresh must preserve the conversation URL');
  const restoredSourceKinds = await page.$$eval('.message-assistant [id^="sources-"]', (containers) => {
    const latest = containers.at(-1);
    return (latest?._sourcesData || []).map((source) => source.source_kind || '');
  });
  assert.ok(restoredSourceKinds.includes('archive'),
    `refresh must restore the archived PDF source kind: ${JSON.stringify(restoredSourceKinds)}`);
  assert.equal(restoredSourceKinds.some((kind) =>
    ['sapl_legislative_matter', 'sapl_matter_original_pdf'].includes(kind)), false,
  `refresh must not add project-of-law sources to the enacted-norm RAG: ${JSON.stringify(restoredSourceKinds)}`);

  const asOfDate = '2024-12-31';
  await page.$eval('[data-jurix-as-of]', (input, value) => {
    input.value = value;
    input.dispatchEvent(new Event('change', { bubbles: true }));
  }, asOfDate);
  assert.equal(await page.evaluate(() => window.JurixSearchControls.getPayload().as_of), asOfDate,
    'the visible historical-date control must set the request scope');
  await page.$eval('#question-textarea', (input, value) => {
    input.value = value;
    input.dispatchEvent(new Event('input', { bubbles: true }));
  }, question);
  const historicalTurnCount = await page.$$eval(
    '.message-assistant .message-body', (answers) => answers.length + 1,
  );
  await page.$eval('#chat-form', (form) => form.requestSubmit());
  await page.waitForFunction((turnCount) => {
    const answers = [...document.querySelectorAll('.message-assistant .message-body')];
    const answer = answers.at(-1);
    const sendButton = document.getElementById('send-button');
    return answers.length === turnCount && answer?.textContent?.trim()
      && !answer.hasAttribute('data-streaming')
      && !answer.querySelector('.jurix-answer-pending')
      && sendButton && !sendButton.disabled;
  }, { timeout: 180000 }, historicalTurnCount);
  const historicalAnswer = await page.$$eval(
    '.message-assistant .message-body', (nodes) => nodes.at(-1)?.innerText || '',
  );
  const historicalSourceData = await page.$$eval(
    '.message-assistant [id^="sources-"]', (containers) => {
      const latest = containers.at(-1);
      return (latest?._sourcesData || []).map((item) => ({
        sourceKind: item.source_kind || '',
        label: item.citation_label || '',
      }));
    },
  );
  assert.equal(historicalSourceData.some((source) => source.sourceKind === 'sapl_legislative_matter'), false,
    `the 2026 SAPL proposal must not be evidence as of 2024-12-31: ${JSON.stringify(historicalSourceData)}`);
  assert.match(historicalAnswer, /não foi possível confirmar|não encontrei evidências (?:históricas )?suficientes/i);
  assert.doesNotMatch(historicalAnswer, /não houve (?:altera[cç][aã]o|revoga[cç][aã]o)/i);
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

  await page.setViewport({ width: 640, height: 900 });
  await page.$eval('#messages-container', (container) => { container.scrollTop = container.scrollHeight; });
  await new Promise((resolve) => setTimeout(resolve, 150));
  const zoomEquivalentLayout = await page.evaluate(() => {
    const answer = [...document.querySelectorAll('.message-assistant .message-body')].at(-1);
    const composer = document.querySelector('#conversation-input-bar');
    const sources = [...document.querySelectorAll('.message-assistant .jurix-sources-pill-btn')].at(-1);
    return {
      method: 'half-width CSS viewport proxy; native browser zoom not exercised',
      viewportWidth: window.innerWidth,
      documentWidth: document.documentElement.scrollWidth,
      answerBottom: answer?.getBoundingClientRect().bottom ?? null,
      composerTop: composer?.getBoundingClientRect().top ?? null,
      sourcesBottom: sources?.getBoundingClientRect().bottom ?? null,
      sourceControlPresent: Boolean(sources?.getClientRects().length),
    };
  });
  assert.equal(zoomEquivalentLayout.viewportWidth, 640,
    `the zoom-equivalent test must use half the baseline CSS viewport: ${JSON.stringify(zoomEquivalentLayout)}`);
  assert.ok(zoomEquivalentLayout.documentWidth <= zoomEquivalentLayout.viewportWidth,
    `the conversation must reflow at the 200%-equivalent CSS viewport: ${JSON.stringify(zoomEquivalentLayout)}`);
  assert.ok(zoomEquivalentLayout.answerBottom <= zoomEquivalentLayout.composerTop,
    `the answer must remain visible above the composer at the 200%-equivalent viewport: ${JSON.stringify(zoomEquivalentLayout)}`);
  assert.equal(zoomEquivalentLayout.sourceControlPresent, true,
    'the sources control must remain available at the 200%-equivalent viewport');
  assert.ok(zoomEquivalentLayout.sourcesBottom <= zoomEquivalentLayout.composerTop,
    `the sources control must remain above the composer at the 200%-equivalent viewport: ${JSON.stringify(zoomEquivalentLayout)}`);

  const screenshot = path.join(resolvedEvidenceDir, 'pgm-article-currentness.png');
  await page.screenshot({ path: screenshot, fullPage: false });
  const report = {
    status: 'passed',
    case: 'LC 120/2010, Art. 18 — currentness question; archived PDF remains unreviewed',
    conclusionStartsWithUncertainty: true,
    proposalsExcludedFromEnactedNormQuery: true,
    generationRequest,
    streaming,
    sourceKinds: [...new Set(sourceData.map((source) => source.sourceKind))],
    sourceCount: sourceData.length,
    historicalQuery: {
      asOf: asOfDate,
      sourceKinds: [...new Set(historicalSourceData.map((source) => source.sourceKind))],
      historicalAnswerAbstains: /não foi possível confirmar|não encontrei evidências (?:históricas )?suficientes/i.test(historicalAnswer),
      projectSourcesExcluded: !historicalSourceData.some((source) =>
        ['sapl_legislative_matter', 'sapl_matter_original_pdf'].includes(source.sourceKind)),
    },
    pageErrors: pageErrors.length,
    answerEndLayout,
    responsiveLayouts,
    zoomEquivalentLayout,
    screenshot,
  };
  const reportPath = path.join(resolvedEvidenceDir, 'pgm-article-currentness-report.json');
  await fs.writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`, { flag: 'wx' });
  process.stdout.write(`${JSON.stringify({ ...report, report: reportPath }, null, 2)}\n`);
} finally {
  await browser.close();
}
