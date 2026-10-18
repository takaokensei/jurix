import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import puppeteer from 'puppeteer-core';

const baseUrl = process.env.JURIX_BASE_URL || '';
const qaRoot = process.env.JURIX_QA_ROOT || '';
const evidenceDir = process.env.JURIX_EVIDENCE_DIR || '';
const allowUnversionedLocalQa = process.env.JURIX_ALLOW_UNVERSIONED_LOCAL_QA === '1';
const includeProposalRagSmoke = process.env.JURIX_INCLUDE_PROPOSAL_RAG_SMOKE === '1';
const base = new URL(baseUrl);
assert.equal(base.protocol, 'http:');
assert.ok(['127.0.0.1', 'localhost'].includes(base.hostname));
assert.ok(['8010', '8011', '8016', '8017', '8028', '8029', '8030', '8040', '8280', '8281', '8282', '8283', '8284', '8285', '8286', '8287', '8289', '8291', '8292'].includes(base.port), 'PGM workflow smoke is restricted to isolated QA servers :8010/:8011/:8016/:8017/:8028/:8029/:8030/:8040/:8280/:8281/:8282/:8283/:8284/:8285/:8286/:8287/:8289/:8291/:8292');
assert.ok(qaRoot && evidenceDir, 'QA root and evidence directory are required');

const tempRoot = await fs.realpath(os.tmpdir());
const resolvedQaRoot = await fs.realpath(qaRoot);
const requestedEvidenceDir = path.resolve(evidenceDir);
await fs.mkdir(requestedEvidenceDir, { recursive: true });
const resolvedEvidenceDir = await fs.realpath(requestedEvidenceDir);
assert.ok(resolvedQaRoot.toLowerCase().startsWith(`${tempRoot.toLowerCase()}${path.sep}`));
assert.ok(
  resolvedEvidenceDir.toLowerCase().startsWith(`${resolvedQaRoot.toLowerCase()}${path.sep}`),
  'screenshots and report must remain under the isolated QA root',
);

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
    // Only consider already-installed local Chrome/Edge binaries.
  }
}
assert.ok(executablePath, 'an already-installed Chrome or Edge executable is required');

const browser = await puppeteer.launch({
  executablePath,
  headless: true,
  args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'],
});
const page = await browser.newPage();
const pageErrors = [];
page.on('pageerror', (error) => pageErrors.push(error.name));
const report = {
  baseUrl,
  environment: 'isolated QA; real local archived PDFs; pending human review; not legal adjudication',
  checks: [],
  evidence: [],
};

async function submitQuestion(question) {
  const priorCount = await page.$$eval('.message-assistant .message-body', (items) => items.length);
  const inputSelector = await page.$('#question-textarea') ? '#question-textarea' : '#hero-search-input';
  const formSelector = inputSelector === '#question-textarea' ? '#chat-form' : '#hero-search-form';
  await page.$eval(inputSelector, (input, value) => {
    input.value = value;
    input.dispatchEvent(new Event('input', { bubbles: true }));
  }, question);
  await page.$eval(formSelector, (form) => form.requestSubmit());
  await page.waitForFunction((previousCount) => {
    const answers = [...document.querySelectorAll('.message-assistant .message-body')];
    const button = document.getElementById('send-button');
    const answer = answers.at(-1);
    return answers.length > previousCount && button && !button.disabled
      && answer?.textContent?.trim().length > 0
      && !answer.hasAttribute('data-streaming')
      && !answer.querySelector('.jurix-answer-pending');
  }, { timeout: 180000 }, priorCount);
  return page.$$eval('.message-assistant .message-body', (answers) => answers.at(-1).innerText);
}

try {
  const viewportChecks = [];
  // 640 CSS px approximates a 1280 px desktop at 200% browser zoom.
  for (const width of [320, 360, 640, 768, 1280, 1920]) {
    await page.setViewport({ width, height: 900 });
    const response = await page.goto(new URL('/assistente/?corpus=archive-qa', baseUrl).href, {
      waitUntil: 'domcontentloaded',
      timeout: 20000,
    });
    const layout = await page.evaluate(() => ({
      width: document.documentElement.clientWidth,
      scrollWidth: document.documentElement.scrollWidth,
      hasMain: Boolean(document.querySelector('main')),
      outOfViewportFocusableControls: [...document.querySelectorAll('a,button,input,select,textarea,[tabindex]')]
        .filter((element) => element.getClientRects().length && element.tabIndex >= 0)
        .filter((element) => {
          const rect = element.getBoundingClientRect();
          return (rect.left < -2 || rect.right > document.documentElement.clientWidth + 2)
            && !element.closest('[inert]')
            && element.closest('[aria-hidden="true"]') === null;
        }).length,
    }));
    assert.equal(response?.status(), 200, `assistant route failed at ${width}px`);
    assert.equal(layout.width, width);
    assert.ok(layout.hasMain, 'assistant page must expose its main landmark');
    assert.ok(layout.scrollWidth <= width, `horizontal overflow at ${width}px`);
    assert.equal(layout.outOfViewportFocusableControls, 0, `offscreen focusable control at ${width}px`);
    viewportChecks.push({ width, ...layout });
    if (width === 320) {
      const screenshot = path.join(resolvedEvidenceDir, 'pgm-assistant-320px.png');
      await page.screenshot({ path: screenshot, fullPage: false });
      report.evidence.push(screenshot);
    }
  }
  report.checks.push({ id: 'responsive-assistant', status: 'passed', viewports: viewportChecks });

  await page.setViewport({ width: 1280, height: 900 });
  const archiveSearchUrl = new URL('/pesquisa/', baseUrl);
  archiveSearchUrl.searchParams.set('q', 'resíduos sólidos');
  archiveSearchUrl.searchParams.set('corpus', 'archive-qa');
  const archiveSearchResponse = await page.goto(archiveSearchUrl.href, {
    waitUntil: 'domcontentloaded',
    timeout: 20000,
  });
  assert.equal(archiveSearchResponse?.status(), 200, 'archive search route must load');
  const archiveSearchResult = await page.evaluate(() => ({
    title: document.querySelector('#workspace-archive-results-title')?.innerText || '',
    summary: document.querySelector('.workspace-archive-search-summary')?.innerText || '',
    summaryHref: document.querySelector('.workspace-archive-search-summary a')?.getAttribute('href') || '',
    cards: [...document.querySelectorAll('.workspace-archive-result-card')].map((card) => ({
      status: card.querySelector('.workspace-score-neutral')?.innerText || '',
      text: card.innerText,
    })),
    caveat: document.querySelector('.workspace-archive-results .workspace-search-caveat')?.innerText || '',
  }));
  assert.match(archiveSearchResult.title, /[1-9]\d* documentos? candidatos/);
  assert.match(archiveSearchResult.summary, /[1-9]\d* PDFs? candidatos? no acervo local/i);
  assert.equal(archiveSearchResult.summaryHref, '#workspace-archive-results-title');
  assert.ok(archiveSearchResult.cards.length > 0, 'accented query must find PDFs in the QA archive');
  assert.ok(
    archiveSearchResult.cards.every((card) => /Pendente|Em revisão/.test(card.status)),
    'archive results must retain their unreviewed status',
  );
  assert.match(archiveSearchResult.caveat, /n[aã]o comprova vig[eê]ncia/i);
  const searchViewportChecks = [];
  for (const width of [320, 360, 640, 768, 1280, 1920]) {
    await page.setViewport({ width, height: 900 });
    const response = await page.goto(archiveSearchUrl.href, {
      waitUntil: 'domcontentloaded',
      timeout: 20000,
    });
    const layout = await page.evaluate(() => ({
      width: document.documentElement.clientWidth,
      scrollWidth: document.documentElement.scrollWidth,
      summaryVisible: Boolean(document.querySelector('.workspace-archive-search-summary')?.getClientRects().length),
      summaryRight: Math.ceil(document.querySelector('.workspace-archive-search-summary')?.getBoundingClientRect().right || 0),
      outOfViewportFocusableControls: [...document.querySelectorAll('a,button,input,select,textarea,[tabindex]')]
        .filter((element) => element.getClientRects().length && element.tabIndex >= 0)
        .filter((element) => {
          const rect = element.getBoundingClientRect();
          return (rect.left < -2 || rect.right > document.documentElement.clientWidth + 2)
            && !element.closest('[inert]')
            && element.closest('[aria-hidden="true"]') === null;
        }).length,
    }));
    assert.equal(response?.status(), 200, `archive search route failed at ${width}px`);
    assert.equal(layout.width, width);
    assert.ok(layout.scrollWidth <= width, `archive search horizontal overflow at ${width}px`);
    assert.ok(layout.summaryVisible, `archive result summary hidden at ${width}px`);
    assert.ok(layout.summaryRight <= width, `archive result summary overflows at ${width}px`);
    assert.equal(layout.outOfViewportFocusableControls, 0, `offscreen focusable control at ${width}px`);
    searchViewportChecks.push(layout);
    if (width === 320) {
      const screenshot = path.join(resolvedEvidenceDir, 'pgm-search-320px.png');
      await page.screenshot({ path: screenshot, fullPage: false });
      report.evidence.push(screenshot);
    }
  }
  report.checks.push({
    id: 'archive-search-summary-responsive',
    status: 'passed',
    viewports: searchViewportChecks,
  });
  await page.setViewport({ width: 1280, height: 900 });
  await page.goto(archiveSearchUrl.href, { waitUntil: 'domcontentloaded', timeout: 20000 });
  const archiveSearchScreenshot = path.join(resolvedEvidenceDir, 'pgm-archive-accent-search.png');
  await page.screenshot({ path: archiveSearchScreenshot, fullPage: false });
  report.evidence.push(archiveSearchScreenshot);
  report.checks.push({
    id: 'real-archive-accent-insensitive-search',
    status: 'passed',
    candidateCount: archiveSearchResult.cards.length,
    statuses: archiveSearchResult.cards.map((card) => card.status),
    caveat: 'candidates are unreviewed PDF extractions, not legal conclusions',
  });

  const duplicateSearchUrl = new URL('/pesquisa/', baseUrl);
  duplicateSearchUrl.searchParams.set('q', '5791');
  duplicateSearchUrl.searchParams.set('corpus', 'archive-qa');
  const duplicateSearchResponse = await page.goto(duplicateSearchUrl.href, {
    waitUntil: 'domcontentloaded',
    timeout: 20000,
  });
  assert.equal(duplicateSearchResponse?.status(), 200, 'duplicate archive search must load');
  await page.$$eval('.workspace-archive-identical-copies', (groups) => {
    for (const group of groups) group.open = true;
  });
  const duplicateGroupResult = await page.evaluate(() => {
    const groups = [...document.querySelectorAll('.workspace-archive-identical-copies')];
    return {
      title: document.querySelector('#workspace-archive-results-title')?.innerText || '',
      groupCount: document.querySelector('.workspace-archive-group-count')?.innerText || '',
      summary: document.querySelector('.workspace-archive-search-summary')?.innerText || '',
      groups: groups.map((group) => ({
        summary: group.querySelector('summary')?.textContent?.trim() || '',
        caveat: group.querySelector('p')?.textContent?.trim() || '',
        copies: [...group.querySelectorAll('a')].map((link) => ({
          label: link.textContent?.trim() || '',
          href: link.getAttribute('href'),
        })),
      })),
    };
  });
  const conflictingIdentityGroup = duplicateGroupResult.groups.find((group) => {
    const labels = group.copies.map((copy) => copy.label).join(' ').toLowerCase();
    return labels.includes('leiordinaria_5791.pdf') && labels.includes('leipromulgada_5791.pdf');
  });
  assert.ok(
    conflictingIdentityGroup,
    `byte-identical 5791 files with conflicting type hints must be grouped: ${JSON.stringify(duplicateGroupResult)}`,
  );
  assert.equal(conflictingIdentityGroup.copies.length, 2, 'both original PDF evidence links must remain visible');
  assert.ok(conflictingIdentityGroup.copies.every((copy) => copy.href.startsWith('/normas/documentos/')));
  assert.match(conflictingIdentityGroup.caveat, /n[aã]o que tenham a mesma identidade jur[ií]dica/i);
  assert.match(duplicateGroupResult.summary, /agrupadas em 1 resultado\./);
  assert.match(duplicateGroupResult.groupCount, /^1 grupo de conteúdo/);
  const duplicateScreenshot = path.join(resolvedEvidenceDir, 'pgm-archive-identical-pdfs-grouped.png');
  await page.screenshot({ path: duplicateScreenshot, fullPage: true });
  report.evidence.push(duplicateScreenshot);
  report.checks.push({
    id: 'archive-groups-byte-identical-conflicting-identities-without-merging-records',
    status: 'passed',
    title: duplicateGroupResult.title,
    summary: duplicateGroupResult.summary,
    group: conflictingIdentityGroup,
    caveat: 'identical bytes do not establish legal identity or force',
  });

  const cosipArchiveUrl = new URL('/pesquisa/', baseUrl);
  cosipArchiveUrl.searchParams.set(
    'q',
    'Qual o valor de R$ 39,75 associado à COSIP na LC 171/2017?',
  );
  cosipArchiveUrl.searchParams.set('corpus', 'archive-qa');
  const cosipArchiveResponse = await page.goto(cosipArchiveUrl.href, {
    waitUntil: 'domcontentloaded',
    timeout: 20000,
  });
  assert.equal(cosipArchiveResponse?.status(), 200, 'natural COSIP archive search must load');
  const cosipArchiveResult = await page.evaluate(() => ({
    title: document.querySelector('#workspace-archive-results-title')?.innerText || '',
    cards: [...document.querySelectorAll('.workspace-archive-result-card')].slice(0, 5).map((card) => ({
      filename: card.querySelector('h3')?.innerText || '',
      excerpt: card.querySelector('.workspace-result-snippet')?.innerText || '',
      status: card.querySelector('.workspace-score-neutral')?.innerText || '',
    })),
  }));
  assert.match(cosipArchiveResult.title, /1 documento candidato/);
  assert.ok(
    cosipArchiveResult.cards.some((card) => /COSIP/i.test(card.excerpt)
      && /39,75/.test(card.excerpt)),
    'the explicit LC 171/2017 query must surface the candidate PDF excerpt containing COSIP and its recorded amount',
  );
  assert.ok(
    cosipArchiveResult.cards.every((card) => /Pendente|Em revisão/.test(card.status)),
    'topical COSIP results must remain visibly unreviewed candidates',
  );
  const cosipScreenshot = path.join(resolvedEvidenceDir, 'pgm-cosip-natural-archive-search.png');
  await page.screenshot({ path: cosipScreenshot, fullPage: true });
  report.evidence.push(cosipScreenshot);
  report.checks.push({
    id: 'lc171-cosip-amount-search-finds-pending-real-pdf-without-legal-promotion',
    status: 'passed',
    title: cosipArchiveResult.title,
    topCandidates: cosipArchiveResult.cards,
    caveat: 'the extracted quote is a pending candidate, not a confirmed rule, minimum or legal conclusion',
  });

  const environmentalArchiveUrl = new URL('/pesquisa/', baseUrl);
  environmentalArchiveUrl.searchParams.set('q', 'ambiental lixo');
  environmentalArchiveUrl.searchParams.set('corpus', 'archive-qa');
  const environmentalArchiveResponse = await page.goto(environmentalArchiveUrl.href, {
    waitUntil: 'domcontentloaded',
    timeout: 20000,
  });
  assert.equal(environmentalArchiveResponse?.status(), 200, 'environmental/waste archive search must load');
  const environmentalArchiveResult = await page.evaluate(() => ({
    query: document.querySelector('input[name="q"]')?.value || '',
    title: document.querySelector('#workspace-archive-results-title')?.innerText || '',
    caveats: [...document.querySelectorAll('.workspace-search-caveat, .workspace-archive-expansion')]
      .map((item) => item.innerText),
    cards: [...document.querySelectorAll('.workspace-archive-result-card')].slice(0, 10).map((card) => ({
      filename: card.querySelector('h3')?.innerText || '',
      matchLabel: card.querySelector('.workspace-archive-snippet-label')?.innerText || '',
      excerpt: card.querySelector('.workspace-result-snippet')?.innerText || '',
      status: card.querySelector('.workspace-score-neutral')?.innerText || '',
    })),
  }));
  assert.equal(environmentalArchiveResult.query, 'ambiental lixo');
  assert.match(environmentalArchiveResult.title, /[1-9]\d* documentos? candidatos/);
  assert.ok(
    environmentalArchiveResult.cards.some((card) => /LeiOrdinaria_20190408_6881/i.test(card.filename)
      && /educa[cç][aã]o ambiental/i.test(card.excerpt)
      && /destina[cç][aã]o adequada do lixo/i.test(card.excerpt)),
    'the real archive must surface a passage that addresses both environmental education and waste disposal',
  );
  assert.ok(
    environmentalArchiveResult.cards.every((card) => /Pendente|Em revisão/.test(card.status)),
    'environmental/waste results must remain visibly unreviewed candidates',
  );
  assert.ok(
    environmentalArchiveResult.cards.some((card) => /corresponde a \d+ de \d+ grupos da busca/i.test(card.matchLabel)),
    'each excerpt should disclose how much of the natural-language query it matches',
  );
  assert.ok(
    environmentalArchiveResult.caveats.some((text) => /relev[aâ]ncia.*estimativa autom[aá]tica/i.test(text))
      && environmentalArchiveResult.caveats.some((text) => /descoberta textual, n[aã]o equival[eê]ncia jur[ií]dica/i.test(text)),
    'the UI must distinguish lexical affinity from a legal conclusion',
  );
  assert.match(
    environmentalArchiveResult.cards[0]?.matchLabel || '',
    /ap[oó]s o primeiro artigo detectado/i,
    'a real-corpus result matching inside a legal article should rank ahead of a preamble-only entity-name match',
  );
  const environmentalScreenshot = path.join(resolvedEvidenceDir, 'pgm-environmental-waste-natural-search.png');
  await page.screenshot({ path: environmentalScreenshot, fullPage: true });
  report.evidence.push(environmentalScreenshot);
  report.checks.push({
    id: 'natural-environmental-waste-search-shows-real-relevant-pdf-without-legal-promotion',
    status: 'passed',
    title: environmentalArchiveResult.title,
    topCandidates: environmentalArchiveResult.cards,
    caveats: environmentalArchiveResult.caveats,
    caveat: 'the archive also contains lexical false positives; each PDF is an unreviewed candidate',
  });

  const normsViewportChecks = [];
  let normsOverview = null;
  for (const width of [320, 360, 640, 768, 1280, 1920]) {
    await page.setViewport({ width, height: 900 });
    const response = await page.goto(new URL('/normas/', baseUrl).href, {
      waitUntil: 'domcontentloaded',
      timeout: 20000,
    });
    assert.equal(response?.status(), 200, `norms route failed at ${width}px`);
    const layout = await page.evaluate(() => {
      const stats = [...document.querySelectorAll('.jurix-norma-stat')].map((item) => item.innerText);
      const candidates = [...document.querySelectorAll('.jurix-archive-candidate')];
      const search = document.querySelector('#norma-search-input');
      const searchStyle = search ? getComputedStyle(search) : null;
      const canvas = document.createElement('canvas');
      const context = canvas.getContext('2d');
      if (context && searchStyle) context.font = searchStyle.font;
      const placeholderWidth = search && context
        ? context.measureText(search.placeholder).width
        : Number.POSITIVE_INFINITY;
      const placeholderAvailableWidth = search && searchStyle
        ? search.clientWidth - Number.parseFloat(searchStyle.paddingLeft) - Number.parseFloat(searchStyle.paddingRight)
        : 0;
      return {
        width: document.documentElement.clientWidth,
        scrollWidth: document.documentElement.scrollWidth,
        title: document.querySelector('#normas-title')?.innerText || '',
        placeholderWidth,
        placeholderAvailableWidth,
        stats,
        candidateTotal: Number(document.querySelector('#archive-candidates-list')?.dataset.totalCandidates || 0),
        displayedCandidates: candidates.length,
        firstCandidateLabel: candidates[0]?.querySelector('h3')?.innerText || '',
        firstCandidateStatus: candidates[0]?.querySelector('.jurix-archive-candidate-status')?.innerText || '',
        allMarkedAsCandidates: candidates.length > 0 && candidates.every((candidate) =>
          candidate.querySelector('.jurix-archive-candidate-meta')?.innerText.includes('PDF candidato')),
        outOfViewportFocusableControls: [...document.querySelectorAll('a,button,input,select,textarea,[tabindex]')]
          .filter((element) => element.getClientRects().length && element.tabIndex >= 0)
          .filter((element) => {
            const rect = element.getBoundingClientRect();
            return (rect.left < -2 || rect.right > document.documentElement.clientWidth + 2)
              && !element.closest('[inert]')
              && element.closest('[aria-hidden="true"]') === null;
          }).length,
      };
    });
    assert.equal(layout.width, width);
    assert.ok(layout.scrollWidth <= width, `norms route horizontal overflow at ${width}px`);
    assert.ok(
      layout.placeholderWidth <= layout.placeholderAvailableWidth,
      `norma search placeholder is clipped at ${width}px (${layout.placeholderWidth.toFixed(1)}px > ${layout.placeholderAvailableWidth.toFixed(1)}px)`,
    );
    assert.equal(layout.title, 'Normas e acervo');
    assert.ok(layout.stats.some((stat) => /^0\s+normas consolidadas$/i.test(stat.replace(/\s+/g, ' '))));
    assert.ok(layout.candidateTotal > 0 && layout.displayedCandidates > 0);
    assert.ok(layout.allMarkedAsCandidates, 'unreviewed PDFs must not be presented as consolidated norms');
    assert.equal(layout.outOfViewportFocusableControls, 0);
    normsViewportChecks.push({
      width,
      scrollWidth: layout.scrollWidth,
      searchPlaceholderWidth: Number(layout.placeholderWidth.toFixed(1)),
      searchPlaceholderAvailableWidth: Number(layout.placeholderAvailableWidth.toFixed(1)),
      candidateTotal: layout.candidateTotal,
      displayedCandidates: layout.displayedCandidates,
      outOfViewportFocusableControls: layout.outOfViewportFocusableControls,
    });
    normsOverview = layout;
    if (width === 320) {
      const screenshot = path.join(resolvedEvidenceDir, 'pgm-normas-320px.png');
      await page.screenshot({ path: screenshot, fullPage: false });
      report.evidence.push(screenshot);
    }
  }
  await page.setViewport({ width: 1280, height: 900 });
  await page.goto(new URL('/normas/?q=LC+258%2F2024&tipo=Lei+Complementar&ano=2024', baseUrl).href, {
    waitUntil: 'domcontentloaded',
    timeout: 20000,
  });
  const archiveBridge = await page.$eval('#archive-global-search-top', (link) => {
    const rect = link.getBoundingClientRect();
    return {
      href: link.href,
      label: link.innerText,
      top: rect.top,
      bottom: rect.bottom,
      viewportHeight: window.innerHeight,
    };
  });
  assert.equal(new URL(archiveBridge.href).searchParams.get('q'), 'Lei Complementar nº 258/2024');
  assert.equal(new URL(archiveBridge.href).searchParams.get('arquivo_tipo'), 'Lei Complementar');
  assert.equal(new URL(archiveBridge.href).searchParams.get('arquivo_ano'), '2024');
  assert.ok(archiveBridge.top >= 0 && archiveBridge.bottom <= archiveBridge.viewportHeight,
    'the full-corpus search CTA should be visible beside the main filters without scrolling');
  const archiveBridgeScreenshot = path.join(resolvedEvidenceDir, 'pgm-normas-global-search-bridge-1280px.png');
  await page.screenshot({ path: archiveBridgeScreenshot, fullPage: false });
  report.evidence.push(archiveBridgeScreenshot);
  const [archiveBridgeResponse] = await Promise.all([
    page.waitForNavigation({ waitUntil: 'domcontentloaded', timeout: 20000 }),
    page.click('#archive-global-search-top'),
  ]);
  assert.equal(archiveBridgeResponse?.status(), 200);
  assert.equal(new URL(page.url()).pathname, '/pesquisa/');
  assert.equal(new URL(page.url()).searchParams.get('q'), 'Lei Complementar nº 258/2024');
  assert.equal(new URL(page.url()).searchParams.get('arquivo_tipo'), 'Lei Complementar');
  assert.equal(new URL(page.url()).searchParams.get('arquivo_ano'), '2024');
  const filteredArchiveResult = await page.$eval('.workspace-archive-result-card', (card) => card.innerText);
  assert.match(filteredArchiveResult, /Lei Complementar nº 258\/2024/i);
  assert.match(filteredArchiveResult, /Pendente/i);
  const appliedArchiveFilters = await page.$eval('.workspace-archive-active-filters', (summary) => summary.innerText);
  assert.match(appliedArchiveFilters, /Espécie: Lei Complementar/i);
  assert.match(appliedArchiveFilters, /Ano: 2024/i);
  report.checks.push({
    id: 'normas-main-search-offers-visible-full-corpus-search',
    status: 'passed',
    query: new URL(page.url()).searchParams.get('q'),
    responseStatus: archiveBridgeResponse.status(),
    visibleWithoutScrolling: true,
    archiveType: new URL(page.url()).searchParams.get('arquivo_tipo'),
    archiveYear: new URL(page.url()).searchParams.get('arquivo_ano'),
    result: 'Lei Complementar nº 258/2024 · pendente de revisão',
    label: archiveBridge.label,
  });
  await page.goto(new URL('/normas/', baseUrl).href, { waitUntil: 'domcontentloaded', timeout: 20000 });
  const normsGlobalSearchScreenshot = path.join(resolvedEvidenceDir, 'pgm-normas-global-search-1280px.png');
  await page.screenshot({ path: normsGlobalSearchScreenshot, fullPage: true });
  report.evidence.push(normsGlobalSearchScreenshot);
  const candidateFilter = await page.$('#archive-candidate-search');
  assert.ok(candidateFilter, 'the local candidate list must expose its page-scoped filter');
  await candidateFilter.evaluate((input) => {
    input.value = 'Lei Complementar nº 120/2010';
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
  const globalArchiveSearch = await page.$eval('#archive-global-search', (link) => ({
    href: link.href,
    label: link.innerText,
    ariaLabel: link.getAttribute('aria-label'),
  }));
  assert.match(globalArchiveSearch.label, /Pesquisar em todo o acervo histórico/);
  assert.equal(new URL(globalArchiveSearch.href).searchParams.get('q'), 'Lei Complementar nº 120/2010');
  const [globalSearchResponse] = await Promise.all([
    page.waitForNavigation({ waitUntil: 'domcontentloaded', timeout: 20000 }),
    page.click('#archive-global-search'),
  ]);
  assert.equal(globalSearchResponse?.status(), 200);
  assert.equal(new URL(page.url()).pathname, '/pesquisa/');
  assert.equal(new URL(page.url()).searchParams.get('q'), 'Lei Complementar nº 120/2010');
  report.checks.push({
    id: 'normas-page-filter-forwards-query-to-global-archive-search',
    status: 'passed',
    query: new URL(page.url()).searchParams.get('q'),
    responseStatus: globalSearchResponse.status(),
  });
  await page.goto(new URL('/normas/', baseUrl).href, { waitUntil: 'domcontentloaded', timeout: 20000 });
  const refreshedCandidateFilter = await page.$('#archive-candidate-search');
  await refreshedCandidateFilter.evaluate((input) => {
    input.value = 'Lei Complementar nº 120/2010';
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
  const filteredCandidates = await page.$$eval('.jurix-archive-candidate:not([hidden])', (cards) => cards.map((card) => ({
    label: card.querySelector('h3')?.innerText || '',
    status: card.querySelector('.jurix-archive-candidate-status')?.innerText || '',
    href: card.querySelector('a[href*="/normas/documentos/"]')?.href || '',
  })));
  assert.ok(filteredCandidates.length > 0, 'the page filter should find the LC 120/2010 local PDF');
  assert.ok(filteredCandidates.every((candidate) => /120\/2010/.test(candidate.label)));
  assert.ok(filteredCandidates.every((candidate) => /Pendente|revis[aã]o/i.test(candidate.status)));
  assert.ok(filteredCandidates[0].href);
  const candidateLink = await page.$('.jurix-archive-candidate:not([hidden]) a[href*="/normas/documentos/"]');
  const [candidateEvidenceResponse] = await Promise.all([
    page.waitForNavigation({ waitUntil: 'domcontentloaded', timeout: 20000 }),
    candidateLink.click(),
  ]);
  assert.equal(candidateEvidenceResponse?.status(), 200);
  const candidateEvidence = await page.evaluate(() => ({
    title: document.querySelector('#evidence-title')?.innerText || '',
    body: document.querySelector('.document-evidence-page')?.innerText || '',
    mainCount: document.querySelectorAll('main').length,
    pdfHref: document.querySelector('a[href*="/pdf/"]')?.href || '',
    reviewFormCount: document.querySelectorAll('[data-document-review-form]').length,
  }));
  assert.match(candidateEvidence.title, /Lei Complementar nº 120\/2010/i);
  assert.match(candidateEvidence.body, /Candidato do acervo histórico/i);
  assert.match(candidateEvidence.body, /identifica[cç][aã]o normativa.*revis[aã]o/i);
  assert.ok(
    /Texto extra[ií]do automaticamente.*rascunho n[aã]o revisado|N[aã]o h[aá] extra[cç][aã]o dispon[ií]vel para esta revis[aã]o/i.test(candidateEvidence.body),
    'the evidence detail must disclose either an unreviewed extraction draft or the absence of an extraction',
  );
  assert.equal(candidateEvidence.mainCount, 1, 'evidence detail must reuse the shell main landmark, not nest another one');
  assert.ok(candidateEvidence.pdfHref);
  assert.equal(candidateEvidence.reviewFormCount, 0, 'anonymous archive browsing must not expose curation forms');
  report.checks.push({
    id: 'normas-archive-candidates-search-and-evidence-detail',
    status: 'passed',
    consolidatedCount: 0,
    candidateTotal: normsOverview.candidateTotal,
    displayedCandidates: normsOverview.displayedCandidates,
    filteredCount: filteredCandidates.length,
    evidenceStatus: candidateEvidenceResponse.status(),
    mainLandmarks: candidateEvidence.mainCount,
    pdfAvailable: Boolean(candidateEvidence.pdfHref),
    extractionState: /N[aã]o h[aá] extra[cç][aã]o dispon[ií]vel para esta revis[aã]o/i.test(candidateEvidence.body)
      ? 'not-extracted'
      : 'unreviewed-draft',
    anonymousReviewForms: candidateEvidence.reviewFormCount,
    caveat: 'PDF candidates are visible for consultation but not approved as consolidated norms',
  });
  report.checks.push({ id: 'normas-responsive', status: 'passed', viewports: normsViewportChecks });
  const normsScreenshot = path.join(resolvedEvidenceDir, 'pgm-normas-candidates-1280px.png');
  await page.screenshot({ path: normsScreenshot, fullPage: false });
  report.evidence.push(normsScreenshot);

  const graphViewportChecks = [];
  let graphEmptyState = null;
  for (const width of [320, 360, 640, 768, 1280, 1920]) {
    await page.setViewport({ width, height: 900 });
    const response = await page.goto(new URL('/explorar/', baseUrl).href, {
      waitUntil: 'domcontentloaded',
      timeout: 20000,
    });
    assert.equal(response?.status(), 200, `normative graph route failed at ${width}px`);
    const layout = await page.evaluate(() => {
      const empty = document.querySelector('.workspace-explore-empty');
      return {
        width: document.documentElement.clientWidth,
        scrollWidth: document.documentElement.scrollWidth,
        heading: document.querySelector('#explore-results-title')?.innerText || '',
        emptyVisible: Boolean(empty?.getClientRects().length),
        emptyText: empty?.innerText || '',
        searchLink: empty?.querySelector('a[href*="/pesquisa/"]')?.getAttribute('href') || '',
        demoLink: document.querySelector('a[href*="/explorar/demo-consolidacao/"]')?.getAttribute('href') || '',
        demoLinkText: document.querySelector('a[href*="/explorar/demo-consolidacao/"]')?.innerText || '',
        filterFormVisible: Boolean(document.querySelector('.explore-filter-panel')),
        relationCards: document.querySelectorAll('.norma-relations, .explore-selected, .explore-graph-action').length,
      };
    });
    assert.equal(layout.width, width);
    assert.ok(layout.scrollWidth <= width, `graph route horizontal overflow at ${width}px`);
    assert.match(layout.heading, /^0 normas?$/i, `expected no consolidated norms in QA: ${layout.heading}`);
    assert.equal(layout.emptyVisible, true, 'empty graph must explain why candidates are not shown');
    assert.match(layout.emptyText, /PDFs em revisão/i);
    assert.ok(layout.searchLink, 'empty graph should direct assessors to the local archive search');
    assert.equal(layout.demoLink, '/explorar/demo-consolidacao/', 'QA should expose the separately labeled LC 258/2024 graph demo');
    assert.match(layout.demoLinkText, /LC 258\/2024/);
    assert.equal(layout.filterFormVisible, false, 'filters should not be shown when there are no consolidated norms');
    assert.equal(layout.relationCards, 0, 'pending PDF candidates must not fabricate normative graph relations');
    graphViewportChecks.push({ width, scrollWidth: layout.scrollWidth, searchLink: layout.searchLink });
    graphEmptyState = layout;
    if (width === 1280) {
      const screenshot = path.join(resolvedEvidenceDir, 'pgm-graph-honest-empty-state.png');
      await page.screenshot({ path: screenshot, fullPage: false });
      report.evidence.push(screenshot);
    }
  }
  report.checks.push({
    id: 'normative-graph-honest-empty-state-responsive',
    status: 'passed',
    viewports: graphViewportChecks,
    emptyState: graphEmptyState,
    caveat: 'zero consolidated/reviewed norms; this verifies honesty and navigation, not graph usefulness',
  });

  const repealGraphViewports = [];
  const ctmTimelineViewports = [];
  for (const width of [320, 360, 768, 1280, 1920]) {
    await page.setViewport({ width, height: 900 });
    const response = await page.goto(new URL('/explorar/demo-consolidacao/', baseUrl).href, {
      waitUntil: 'domcontentloaded',
      timeout: 20000,
    });
    assert.equal(response?.status(), 200, `LC 258/2024 graph demo failed at ${width}px`);
    if (width === 1280) {
      const demoNavigation = await page.evaluate(() => ({
        mainCount: document.querySelectorAll('main').length,
        caseNavigationPosition: getComputedStyle(document.querySelector('.pgm-demo__case-nav')).position,
        graphActionVisible: Boolean(document.querySelector('.pgm-demo__case-nav a[href="#pgm-network-title"]')?.getClientRects().length),
        beforeAfterActionVisible: Boolean(document.querySelector('.pgm-demo__case-nav a[href="#pgm-ctm-change-set-title"]')?.getClientRects().length),
        secondaryCaseCount: document.querySelectorAll('.pgm-demo > details[data-case-disclosure]').length,
        secondaryCaseCollapsed: [...document.querySelectorAll('.pgm-demo > details[data-case-disclosure]')]
          .every((element) => !element.open),
        defaultContentHeight: Math.round(document.querySelector('.pgm-demo')?.getBoundingClientRect().height || 0),
        fakeSimilarityVisible: /\b(?:score|similarity|similaridade)\s*[:=]\s*\d/i.test(
          document.querySelector('.pgm-demo')?.innerText || '',
        ),
      }));
      assert.equal(demoNavigation.mainCount, 1, 'the demo must have one main landmark');
      assert.equal(demoNavigation.caseNavigationPosition, 'sticky', 'sticky case navigation is reserved for the wide desktop layout');
      assert.equal(demoNavigation.graphActionVisible, true, 'the graph must be one direct action from the case introduction');
      assert.equal(demoNavigation.beforeAfterActionVisible, true, 'before/after must be reachable without scanning other cases');
      assert.equal(demoNavigation.secondaryCaseCount, 2, 'the page should group the secondary CTM cotejo and additional case histories');
      assert.equal(demoNavigation.secondaryCaseCollapsed, true, 'secondary evidence-heavy case groups should start collapsed');
      assert.equal(demoNavigation.fakeSimilarityVisible, false, 'the demo must not present relation evidence as a similarity score');
      report.checks.push({ id: 'pgm-demo-task-navigation-and-single-main-landmark', status: 'passed', ...demoNavigation });
      const initialDemoScreenshot = path.join(resolvedEvidenceDir, 'pgm-demo-progressive-cases-default-1280px.png');
      await page.screenshot({ path: initialDemoScreenshot, fullPage: true });
      report.evidence.push(initialDemoScreenshot);
      assert.equal(await page.$eval('[data-case-disclosure]', (element) => element.open), false,
        'secondary CTM comparisons should be collapsed on initial demo load');
      await page.locator('.pgm-demo__case-nav a[href="#pgm-ctm-change-set-title"]').click();
      assert.equal(await page.$eval('[data-case-disclosure]', (element) => element.open), true,
        'the before/after navigation link should open its containing disclosure');
      await page.waitForFunction(() => {
        const target = document.getElementById('pgm-ctm-change-set-title');
        const navigation = document.querySelector('.pgm-demo__case-nav');
        return target && navigation
          && target.getBoundingClientRect().top >= navigation.getBoundingClientRect().bottom + 8
          && target.getBoundingClientRect().top < window.innerHeight;
      }, { timeout: 3000 });
      await page.waitForFunction(() => !document.querySelector('.pgm-demo__case-nav-more')?.open,
        { timeout: 3000 });
      await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'instant' }));
      await page.waitForFunction(() => window.scrollY < 5, { timeout: 3000 });
      await page.locator('.pgm-demo__case-nav-more > summary').click();
      await page.waitForFunction(() => document.querySelector('.pgm-demo__case-nav-more')?.open,
        { timeout: 3000 });
      await page.locator('.pgm-demo__case-nav-menu a[href="#pgm-history-title"]').click();
      assert.equal(await page.$eval('#pgm-history-title', (element) => element.closest('[data-case-disclosure]').open), true,
        'an anchor to a secondary history must reveal its collapsed case group');
      await page.waitForFunction(() => {
        const target = document.getElementById('pgm-history-title');
        const navigation = document.querySelector('.pgm-demo__case-nav');
        return target && navigation
          && target.getBoundingClientRect().top >= navigation.getBoundingClientRect().bottom + 8
          && target.getBoundingClientRect().top < window.innerHeight;
      }, { timeout: 3000 });
      report.checks.push({
        id: 'pgm-demo-progressive-case-disclosures-and-anchor-navigation',
        status: 'passed',
        initialState: 'all secondary case groups collapsed',
        navigation: 'before/after and historical anchors open the correct disclosure and bring the target into view',
      });
    } else {
      await page.$$eval('[data-case-disclosure] > summary', (summaries) => {
        summaries.forEach((summary) => summary.click());
      });
      assert.equal(await page.$$eval('[data-case-disclosure]', (items) => items.every((element) => element.open)), true,
        'case groups should be expanded for the detailed responsive-content checks');
    }
    await page.waitForFunction(() => document.querySelectorAll('.pgm-demo__edges .pgm-demo__edge').length === 12, {
      timeout: 5000,
    });
    const ctmTimeline = await page.evaluate(() => {
      const section = document.querySelector('#pgm-ctm-art20-title')?.closest('.pgm-demo__case');
      const list = section?.querySelector('.pgm-demo__timeline');
      const summary = section?.querySelector('.pgm-demo__notice p')?.innerText || '';
      const diff = section?.querySelector('#pgm-ctm-diff-title')?.closest('.pgm-demo__text-diff');
      const amendment = list?.querySelector(':scope > li:last-child');
      const addedArticleList = document.querySelector(
        '.pgm-demo__change-list[aria-label="Dispositivos novos acrescentados ao Código Tributário"]',
      );
      const consolidatedArt150 = document.querySelector('#pgm-consolidated-150')
        ?.closest('.pgm-demo__consolidated-device')?.querySelector('pre')?.innerText || '';
      const consolidatedArt23 = document.querySelector('#pgm-consolidated-23')
        ?.closest('.pgm-demo__consolidated-device')?.querySelector('pre')?.innerText || '';
      const consolidatedCount = document.querySelector('#pgm-consolidated-texts-title')
        ?.closest('section')?.querySelector('.pgm-demo__diff-heading span')?.innerText || '';
      return {
        labels: [...(list?.querySelectorAll(':scope > li h3') || [])].map((node) => node.innerText.trim()),
        summary,
        hasRemovedText: Boolean(diff?.querySelector('del')),
        hasAddedText: Boolean(diff?.querySelector('ins')),
        sourceAction: amendment?.innerText || '',
        officialNormaRecord: amendment?.querySelector('a[href="https://sapl.natal.rn.leg.br/norma/8975"]')?.innerText || '',
        addedArticles: [...(addedArticleList?.querySelectorAll('summary') || [])].map((node) => node.innerText.trim()),
        addedArticleSourceLinks: addedArticleList?.querySelectorAll('a[href*="/2025/8975/"]').length || 0,
        consolidatedArt23,
        consolidatedArt150,
        consolidatedCount,
        width: document.documentElement.clientWidth,
        scrollWidth: document.documentElement.scrollWidth,
      };
    });
    assert.deepEqual(ctmTimeline.labels, [
      'Consolidação municipal · exercício 2021',
      'Consolidação municipal · exercício 2022',
      'Consolidação municipal · exercício 2024',
      'LC nº 271/2025 · Art. 1º (redação substitutiva do Art. 20)',
      'Redação integrada candidata · Art. 20 em 16/12/2025',
    ], 'CTM Art. 20 should show three dated official snapshots and its later promulgated amendment');
    assert.match(ctmTimeline.summary, /texto extraído do Art\. 20 nas edições de 2021, 2022 e 2024 coincide/i);
    assert.match(ctmTimeline.summary, /As quatro fontes continuam pendentes de revisão no QA/i);
    assert.equal(ctmTimeline.hasRemovedText, true, 'the 2024-to-2025 textual diff should retain removed wording');
    assert.equal(ctmTimeline.hasAddedText, true, 'the 2024-to-2025 textual diff should retain added wording');
    assert.match(ctmTimeline.sourceAction, /Menção de alteração no ato-fonte.*passam a vigorar.*arts\. 20, 23, 25/i,
      'the timeline must expose the exact pending target/action evidence from LC 271/2025');
    assert.match(ctmTimeline.sourceAction, /marco temporal inicial confirmado em fonte oficial.*16\/12\/2025/i,
      'the DOM issue and LC 271 Art. 6 should support the initial effective-date marker');
    assert.match(ctmTimeline.sourceAction, /colofão da cópia PDF hospedada no SAPL informa 2025-12-17/i,
      'the conflicting SAPL PDF colophon date must remain visible as source metadata');
    assert.deepEqual(ctmTimeline.addedArticles, [
      'Art. 133-A · inclusão candidata',
      'Art. 133-B · inclusão candidata',
      'Art. 133-C · inclusão candidata',
      'Art. 133-D · inclusão candidata',
      'Art. 133-E · inclusão candidata',
    ], 'the five complete new CTM devices must appear as separate expandable candidates');
    assert.equal(ctmTimeline.addedArticleSourceLinks, 5, 'each added device must retain an official source link');
    assert.match(ctmTimeline.consolidatedArt150, /Art\. 150\..*Parágrafo único\./s,
      'the candidate Art. 150 text must preserve the caput and replace its sole paragraph');
    assert.match(ctmTimeline.consolidatedArt23, /Art\. 23\b.*§ 5º.*§ 6º A base de cálculo/s,
      'the candidate Art. 23 text must preserve the complete 2024 paragraphs and append the explicit § 6º');
    assert.match(ctmTimeline.consolidatedCount, /3 recomposições determinísticas/);
    assert.match(ctmTimeline.officialNormaRecord, /ficha da norma no SAPL/i);
    assert.equal(ctmTimeline.scrollWidth, ctmTimeline.width, `CTM timeline should reflow at ${width}px`);
    ctmTimelineViewports.push({ width, scrollWidth: ctmTimeline.scrollWidth, labels: ctmTimeline.labels.length });
    if (width === 1280) {
      const section = await page.$('.pgm-demo__case[aria-labelledby="pgm-ctm-art20-title"]');
      const screenshot = path.join(resolvedEvidenceDir, 'pgm-ctm-art20-dated-timeline-1280px.png');
      await section.screenshot({ path: screenshot });
      report.evidence.push(screenshot);
    }
    const graphLayout = await page.evaluate((width) => ({
      width: document.documentElement.clientWidth,
      scrollWidth: document.documentElement.scrollWidth,
      sourceNodes: document.querySelectorAll('.pgm-demo__source-node').length,
      lc55HistoryTitle: document.querySelector('#pgm-lc55-history-title')?.textContent?.trim() || '',
      lc55TimelineColumns: (() => {
        const timeline = document.querySelector('.pgm-demo__timeline--lc55');
        return timeline ? getComputedStyle(timeline).gridTemplateColumns.trim().split(/\s+/).length : 0;
      })(),
      lc55OriginalQuote: document.querySelector('.pgm-demo__timeline--lc55 > li:first-child blockquote')?.innerText || '',
      lc55OriginalLink: document.querySelector('.pgm-demo__timeline--lc55 > li:first-child a')?.href || '',
      lc55OriginalReviewState: document.querySelector('.pgm-demo__timeline--lc55 > li:first-child small')?.innerText || '',
      lc55HistoryGridColumns: (() => {
        const grid = document.querySelector('.pgm-demo__timeline--lc55');
        return grid ? getComputedStyle(grid).gridTemplateColumns.split(/\s+/).length : 0;
      })(),
      lc55HistoryActs: [...document.querySelectorAll('[data-chain-state="candidate"] > strong')]
        .map((node) => node.textContent.trim()),
      lc55HistorySnapshots: [...document.querySelectorAll('[data-chain-state="snapshot"] > strong')]
        .map((node) => node.textContent.trim()),
      lc55HistoryLinks: [...document.querySelectorAll('[data-chain-state] > a')]
        .map((link) => ({ href: link.href, text: link.textContent.trim() })),
      lc55HistoryNotice: document.querySelector('#pgm-lc55-history-title')?.closest('section')?.querySelector('[aria-label="Lacuna da consolidação do Art. 34"]')?.innerText || '',
      lc55TimelineNotice: [...(document.querySelector('#pgm-lc55-history-title')?.closest('section')?.querySelectorAll('.pgm-demo__notice') || [])].at(-1)?.innerText || '',
      lc258DomPublicationLink: [...document.querySelectorAll('a')]
        .find((link) => /edição extra nº 5615 do DOM/i.test(link.innerText))?.href || '',
      lc55ParagraphComparison: document.querySelector('[data-lc55-paragraph-comparison]')?.innerText || '',
      lc55ComparisonStatus: document.querySelector('#pgm-lc55-history-title')
        ?.closest('section')?.querySelector('.pgm-demo__comparison-status')?.innerText || '',
      lc55ParagraphSourceLinks: document.querySelectorAll('[data-lc55-paragraph-comparison] a').length,
      lc208OriginalParagraphLink: [...(document.querySelector('#pgm-working-art18-title')
        ?.closest('article')?.querySelectorAll('a') || [])]
        .find((link) => /redação original da LC 208\/2022, Art\. 18/i.test(link.innerText))?.href || '',
      lc261ReplacementLink: [...(document.querySelector('#pgm-working-art18-title')
        ?.closest('article')?.querySelectorAll('a') || [])]
        .find((link) => /Fonte oficial · LC 261\/2025, Art\. 118/i.test(link.innerText))?.href || '',
      lc261ReplacementQuote: document.querySelector('#pgm-working-art18-title')
        ?.closest('article')?.querySelector('blockquote')?.innerText || '',
      lc208OriginalParagraphQuote: [...document.querySelectorAll('.pgm-demo__case-grid h3')]
        .find((heading) => /LC 208\/2022 · Art\. 18, § 2º/i.test(heading.innerText))
        ?.closest('article')?.querySelector('blockquote')?.innerText || '',
      relationNodes: document.querySelectorAll('[data-graph-relation]').length,
      graphTargets: document.querySelectorAll('[data-graph-target]').length,
      targetCardGridColumns: (() => {
        const grid = document.querySelector('.pgm-demo__target-grid');
        return grid ? getComputedStyle(grid).gridTemplateColumns.split(/\s+/).length : 0;
      })(),
      targetCardWidth: document.querySelector('.pgm-demo__target-node[data-graph-target]')?.getBoundingClientRect().width || 0,
      diagramHeight: document.querySelector('.pgm-demo__diagram')?.getBoundingClientRect().height || 0,
      namedTargets: document.querySelectorAll('.pgm-demo__target-node[data-graph-relation-target="express"]').length,
      repealEdges: document.querySelectorAll('.pgm-demo__edge-label:not(.pgm-demo__edge-label--amendment):not(.pgm-demo__edge-label--generic)').length,
      targetScopeCounts: [...document.querySelectorAll('.pgm-demo__target-node[data-graph-relation-target="express"]')].reduce((counts, card) => {
        const scope = card.dataset.targetScope;
        counts[scope] = (counts[scope] || 0) + 1;
        return counts;
      }, {}),
      targetScopeNotice: document.querySelector('.pgm-demo__targets-heading + .pgm-demo__notice')?.innerText || '',
      renderedGraphEdges: document.querySelectorAll('.pgm-demo__edges .pgm-demo__edge[marker-end="url(#pgm-demo-arrow)"]').length,
      graphEdgesDashPattern: [...document.querySelectorAll('.pgm-demo__edges .pgm-demo__edge')]
        .every((edge) => edge.getAttribute('d')?.startsWith('M ') && edge.getAttribute('d')?.includes(' C ')),
      graphEdgesConnectNodes: (() => {
        const edges = [...document.querySelectorAll('.pgm-demo__edges .pgm-demo__edge')];
        const frame = document.querySelector('.pgm-demo__network')?.getBoundingClientRect();
        if (!frame || edges.length !== 12) return false;
        return edges.every((edge) => {
          const [sourceType, sourceKey] = edge.dataset.graphFrom.split(':');
          const [targetType, targetKey] = edge.dataset.graphTo.split(':');
          const from = sourceType === 'source'
            ? document.querySelector('.pgm-demo__source-node')
            : document.querySelector(`[data-graph-relation="${sourceKey}"]`);
          const to = targetType === 'target'
            ? document.querySelector(`[data-graph-target="${targetKey}"]`)
            : document.querySelector(`[data-graph-relation="${targetKey}"]`);
          if (!from || !to || !targetKey) return false;
          const coordinates = (edge.getAttribute('d') || '').match(/-?\d+(?:\.\d+)?/g)?.map(Number) || [];
          const fromRect = from.getBoundingClientRect();
          const toRect = to.getBoundingClientRect();
          const verticalBranch = sourceType === 'relation' && targetType === 'target'
            && toRect.left + toRect.width / 2 >= fromRect.left
            && toRect.left + toRect.width / 2 <= fromRect.right;
          const verticalOverlap = fromRect.top < toRect.bottom && fromRect.bottom > toRect.top;
          const horizontal = !verticalBranch && verticalOverlap
            && Math.abs((toRect.left + toRect.width / 2) - (fromRect.left + fromRect.width / 2))
            > Math.abs((toRect.top + toRect.height / 2) - (fromRect.top + fromRect.height / 2));
          const direction = horizontal
            ? Math.sign((toRect.left + toRect.width / 2) - (fromRect.left + fromRect.width / 2)) || 1
            : Math.sign((toRect.top + toRect.height / 2) - (fromRect.top + fromRect.height / 2)) || 1;
          const edgeIndex = Number(edge.dataset.edgeIndex) - 1;
          const relatedTargetCount = sourceType === 'relation'
            ? document.querySelectorAll(`[data-graph-relation-target="${sourceKey}"]`).length
            : targetType === 'relation' ? document.querySelectorAll('[data-graph-relation]').length : 1;
          const fanOffset = relatedTargetCount > 1 ? (edgeIndex + 1) / (relatedTargetCount + 1) : 0.5;
          const expectedStartX = (horizontal
            ? (direction > 0 ? fromRect.right : fromRect.left)
            : verticalBranch ? toRect.left + toRect.width / 2 : fromRect.left + fromRect.width * fanOffset) - frame.left;
          const expectedStartY = (horizontal ? fromRect.top + fromRect.height / 2 : (direction > 0 ? fromRect.bottom : fromRect.top)) - frame.top;
          const expectedEndX = (horizontal
            ? (direction > 0 ? toRect.left : toRect.right)
            : verticalBranch ? toRect.left + toRect.width / 2 : toRect.left + toRect.width * fanOffset) - frame.left;
          const expectedEndY = (horizontal ? toRect.top + toRect.height / 2 : (direction > 0 ? toRect.top : toRect.bottom)) - frame.top;
          return coordinates.length === 8
            && Math.abs(coordinates[0] - expectedStartX) < 1.5
            && Math.abs(coordinates[1] - expectedStartY) < 1.5
            && Math.abs(coordinates[6] - expectedEndX) < 1.5
            && Math.abs(coordinates[7] - expectedEndY) < 1.5;
        });
      })(),
      desktopTargetsFollowTheirEventHub: width < 1120 || (() => {
        const relationsByKind = Object.fromEntries([...document.querySelectorAll('[data-graph-relation]')]
          .map((node) => [node.dataset.graphRelation, node.getBoundingClientRect()]));
        return [...document.querySelectorAll('[data-graph-target]')].every((node) => {
          const relation = relationsByKind[node.dataset.graphRelationTarget];
          const target = node.getBoundingClientRect();
          return target.top >= relation.bottom - 2;
        });
      })(),
      desktopExpressFanoutStaysUnderItsHub: width < 921 || (() => {
        const hub = document.querySelector('[data-graph-relation="express"]')?.getBoundingClientRect();
        return Boolean(hub) && [...document.querySelectorAll('[data-graph-relation-target="express"]')]
          .every((node) => {
            const target = node.getBoundingClientRect();
            const center = target.left + target.width / 2;
            return center >= hub.left - 1 && center <= hub.right + 1;
          });
      })(),
      graphSvgIsDecorative: document.querySelector('.pgm-demo__edges')?.getAttribute('aria-hidden') === 'true',
      saplRegistry: (() => {
        const cards = [...document.querySelectorAll('.pgm-demo__target-node')];
        const statuses = Object.fromEntries(cards.map((card) => [
          card.querySelector('h3')?.innerText || '',
          {
            status: card.dataset.saplStatus,
            links: [...card.querySelectorAll('.pgm-demo__sapl-evidence a')].map((link) => ({
              href: link.href,
              rel: link.rel,
              text: link.textContent.trim(),
            })),
            note: card.querySelector('.pgm-demo__sapl-evidence')?.textContent || '',
          },
        ]));
        return {
          statuses,
          candidateLinks: cards.flatMap((card) => [...card.querySelectorAll('.pgm-demo__sapl-evidence a')])
            .map((link) => ({ href: link.href, rel: link.rel })),
          disclosureCount: cards.filter((card) => {
            const disclosure = card.querySelector('.pgm-demo__sapl-evidence');
            return disclosure?.tagName === 'DETAILS' && !disclosure.open;
          }).length,
          disclosureIsNative: [...document.querySelectorAll('.pgm-demo__sapl-evidence')]
            .every((disclosure) => disclosure.tagName === 'DETAILS'),
          disclosureSummariesNamed: [...document.querySelectorAll('.pgm-demo__sapl-evidence > summary')]
            .every((summary) => summary.getAttribute('aria-label')?.includes('SAPL')),
          checkedDateVisible: cards.some((card) => card.querySelector('.pgm-demo__sapl-date')?.innerText.includes('2026-10-15')),
        };
      })(),
      parallelRelations: document.querySelectorAll('.pgm-demo__other-event').length,
      demoTitle: document.querySelector('#pgm-demo-title')?.innerText || '',
      heading: document.querySelector('#pgm-network-title')?.innerText || '',
      genericRepeal: [...document.querySelectorAll('.pgm-demo__relation-kicker')]
        .some((item) => /Art\. 266.*REVOGAÇÃO GENÉRICA/i.test(item.innerText)),
      amendment: [...document.querySelectorAll('.pgm-demo__relation-kicker')]
        .some((item) => /Art\. 261.*ALTERAÇÃO/i.test(item.innerText)),
      focusableOverflowDetails: [...document.querySelectorAll('a,button,input,select,textarea,[tabindex]')]
        .filter((element) => element.getClientRects().length && element.tabIndex >= 0)
        .filter((element) => {
          const rect = element.getBoundingClientRect();
          return (rect.left < -2 || rect.right > document.documentElement.clientWidth + 2)
            && !element.closest('[inert]')
            && element.closest('[aria-hidden="true"]') === null;
        }).map((element) => {
          const rect = element.getBoundingClientRect();
          return {
            tag: element.tagName,
            label: (element.innerText || element.getAttribute('aria-label') || '').trim().slice(0, 100),
            href: element.getAttribute('href'),
            left: Math.round(rect.left),
            right: Math.round(rect.right),
            sidebarState: element.closest('[data-workspace-sidebar]')?.getAttribute('aria-hidden') || null,
          };
        }),
      closedCaseNavLinkCount: (() => {
        const disclosure = document.querySelector('.pgm-demo__case-nav-more');
        return disclosure && !disclosure.open
          ? [...disclosure.querySelectorAll('.pgm-demo__case-nav-menu a')]
            .filter((link) => link.getClientRects().length && link.tabIndex >= 0).length
          : -1;
      })(),
    }), width);
    graphLayout.focusableOverflow = graphLayout.focusableOverflowDetails.length;
    assert.equal(graphLayout.width, width);
    assert.ok(graphLayout.scrollWidth <= width, `LC 258/2024 graph overflows at ${width}px`);
    const expectedLc55Columns = width <= 700 ? 1 : width >= 1600 ? 4 : 2;
    assert.equal(graphLayout.lc55TimelineColumns, expectedLc55Columns,
      `LC 55 historical chain should use ${expectedLc55Columns} columns at ${width}px`);
    assert.equal(graphLayout.sourceNodes, 1);
    assert.match(graphLayout.lc55HistoryTitle, /LC nº 55\/2004/i);
    assert.match(graphLayout.lc55OriginalQuote, /Art\. 34.*§ 1º.*§ 2º/i);
    assert.match(graphLayout.lc55OriginalQuote, /Licença Prévia.*Licença de Operação/i);
    assert.equal(
      new URL(graphLayout.lc55OriginalLink).pathname,
      '/normas/documentos/80752f21-67b5-4190-8109-e7cfa30f1551/pdf/',
      'the verified original candidate must open from the local source archive, not the 2019 compilation',
    );
    const originalPdfUrl = new URL(graphLayout.lc55OriginalLink);
    assert.equal(originalPdfUrl.hash, '#page=9');
    assert.equal((graphLayout.lc55OriginalLink.match(/#page=/g) || []).length, 1);
    assert.match(graphLayout.lc55OriginalReviewState, /revisão pendente e extração complete/i);
    assert.ok(graphLayout.lc55HistoryActs.includes('LC nº 173/2017 · Art. 2º'));
    assert.ok(graphLayout.lc55HistoryActs.includes('LC nº 258/2024 · Art. 260, IV'));
    assert.ok(graphLayout.lc55HistorySnapshots.includes('Compilação oficial municipal · julho/2019 (snapshot, não ato)'));
    assert.equal(
      graphLayout.lc55HistoryLinks.length,
      6,
      'archive candidates expose their source PDFs and, when available, the exact official copies; snapshots and later acts remain separately linked',
    );
    assert.match(graphLayout.lc55HistoryNotice, /§ 4º na compilação oficial de 2019/i);
    assert.match(graphLayout.lc55HistoryNotice, /A compilação atribui o § 5º à LC 185\/2019/i);
    assert.match(graphLayout.lc55HistoryNotice, /Decreto municipal nº 11\.681\/2018/i);
    assert.match(graphLayout.lc55HistoryNotice, /LC 173\/2018.*28\/12\/2017/i);
    assert.match(graphLayout.lc55HistoryNotice, /identidade do PDF da lei foi conferida pelo hash da cópia oficial/i);
    assert.match(graphLayout.lc55TimelineNotice, /a data geral calculada é 27\/03\/2025/i);
    assert.match(graphLayout.lc55TimelineNotice, /publicada na edição extra nº 5615 do Diário Oficial do Município, em 27\/12\/2024/i);
    assert.match(graphLayout.lc55TimelineNotice, /Art. 262 prevê análise integral segundo a legislação da data do protocolo/i);
    assert.match(graphLayout.lc55TimelineNotice, /edição extra nº 5615 do DOM, p\. 17 \(publicação da LC 258\)/i);
    assert.match(graphLayout.lc258DomPublicationLink, /dom_20241227_extra_0aaf5ad445c342a04c28c91e2275c838\.pdf#page=17$/i);
    assert.doesNotMatch(graphLayout.lc55TimelineNotice, /edição do Diário Oficial correspondente não foi confirmada/i);
    assert.match(graphLayout.lc55TimelineNotice, /A lista do Art\. 260, IV, inclui expressamente a LC 55\/2004/i);
    assert.doesNotMatch(graphLayout.lc55TimelineNotice, /a partir daí, o Art\. 260, IV, revoga/i);
    assert.match(graphLayout.lc55TimelineNotice, /protocolados até a entrada em vigor e ainda sem despacho decisório/i);
    assert.match(graphLayout.lc55TimelineNotice, /compilação municipal de julho\/2019 não reproduz o mesmo § 3º/i);
    assert.match(graphLayout.lc55ParagraphComparison, /§ 3º · LC 173\/2017, Art\. 2º/);
    assert.match(graphLayout.lc55ParagraphComparison, /§ 3º · LC 185\/2019, Art\. 87/);
    assert.match(graphLayout.lc55ComparisonStatus, /nenhuma redação é escolhida automaticamente/i);
    assert.equal(graphLayout.lc55ParagraphSourceLinks, 3);
    assert.match(graphLayout.lc208OriginalParagraphLink, /#page=11$/,
      'the original LC 208 Art. 18 § 2º citation must open the page where the paragraph begins');
    assert.match(graphLayout.lc261ReplacementLink, /#page=35$/,
      'the LC 261 Art. 118 replacement wording must open its continuation page');
    assert.match(graphLayout.lc208OriginalParagraphQuote, /SZ-2.*Avenida da Integração/i,
      'the original Art. 18 § 2º wording must be visible for before/after review');
    assert.match(graphLayout.lc261ReplacementQuote, /Acrescer à Subzona de Uso Restrito da ZPA-1/i);
    assert.equal(
      graphLayout.lc55HistoryGridColumns,
      width <= 700 ? 1 : width < 1600 ? 2 : 4,
      `LC 55 timeline must adapt at ${width}px`,
    );
    assert.equal(graphLayout.namedTargets, 7, 'the diagram must show all six acts and the cited device');
    assert.equal(graphLayout.repealEdges, 7, 'every named target must show its citation-scope label');
    assert.deepEqual(graphLayout.targetScopeCounts, { act: 6, device: 1 }, 'the graph must distinguish act citations from device citations');
    assert.match(graphLayout.targetScopeNotice, /não prova revogação integral/i);
    assert.match(graphLayout.targetScopeNotice, /não confirma sozinho o alcance ou os efeitos no tempo/i);
    assert.equal(graphLayout.relationNodes, 3, 'the diagram must show the repeal list, amendment and generic clause as separate events');
    assert.equal(graphLayout.graphTargets, 9, 'the graph must include seven named repeal targets and two additional event targets');
    assert.ok(width <= 1120 || graphLayout.targetCardGridColumns === 3, 'wide desktop must use three readable destination columns');
    assert.ok(width <= 1120 || graphLayout.targetCardWidth >= 250, 'wide desktop target cards must not remain compressed into narrow side panels');
    assert.equal(graphLayout.renderedGraphEdges, 12, 'the three source links and nine event-to-target links must be visible');
    assert.equal(graphLayout.graphEdgesDashPattern, true, 'textual, unvalidated relations must use dashed graph edges');
    assert.equal(graphLayout.graphEdgesConnectNodes, true, 'each SVG edge must join the relation hub to its matching card');
    assert.equal(graphLayout.desktopTargetsFollowTheirEventHub, true, 'desktop target cards should follow their event hub in the vertical flow');
    assert.equal(graphLayout.desktopExpressFanoutStaysUnderItsHub, true, 'desktop repeal destinations must stay beneath the two-column repeal hub to avoid crossing fan-out lines');
    assert.equal(graphLayout.graphSvgIsDecorative, true, 'the visual SVG must not duplicate the accessible HTML list');
    assert.equal(Object.values(graphLayout.saplRegistry.statuses).filter((item) => item.status === 'exact_identity_candidate').length, 1);
    assert.equal(Object.values(graphLayout.saplRegistry.statuses).filter((item) => item.status === 'species_conflict').length, 2);
    assert.equal(Object.values(graphLayout.saplRegistry.statuses).filter((item) => item.status === 'ambiguous').length, 0);
    assert.equal(Object.values(graphLayout.saplRegistry.statuses).filter((item) => item.status === 'year_conflict').length, 1);
    assert.equal(Object.values(graphLayout.saplRegistry.statuses).filter((item) => item.status === 'identity_conflict').length, 1);
    assert.equal(Object.values(graphLayout.saplRegistry.statuses).filter((item) => item.status === 'date_matched_candidate').length, 1);
    assert.equal(Object.values(graphLayout.saplRegistry.statuses).filter((item) => item.status === 'not_checked').length, 1);
    assert.equal(Object.values(graphLayout.saplRegistry.statuses).filter((item) => !item.status).length, 2,
      'the two non-SAPL targets must not be counted as catalog lookups');
    assert.equal(graphLayout.saplRegistry.candidateLinks.length, 19,
      'candidate details must include the public SAPL, DOM and municipal library sources currently mapped');
    assert.equal(graphLayout.saplRegistry.disclosureCount, 6, 'available official-source detail panels must start collapsed to keep the graph scannable');
    assert.equal(graphLayout.saplRegistry.disclosureIsNative, true, 'SAPL evidence must use native keyboard-operable disclosures');
    assert.equal(graphLayout.saplRegistry.disclosureSummariesNamed, true, 'the native details controls must have accessible names');
    const officialSourceHosts = new Set(['sapl.natal.rn.leg.br', 'www2.natal.rn.gov.br', 'natal.rn.gov.br']);
    assert.ok(graphLayout.saplRegistry.candidateLinks.every((link) =>
      officialSourceHosts.has(new URL(link.href).hostname) && /noopener/.test(link.rel)));
    assert.equal(graphLayout.saplRegistry.checkedDateVisible, true);
    const promulgated562 = Object.entries(graphLayout.saplRegistry.statuses)
      .find(([citation]) => /562.*2018/.test(citation))?.[1];
    assert.equal(promulgated562?.status, 'date_matched_candidate');
    const promulgated562Paths = promulgated562?.links.map((link) => new URL(link.href).pathname) || [];
    assert.ok(promulgated562Paths.includes('/norma/254'));
    assert.ok(promulgated562Paths.includes('/norma/9202'));
    assert.ok(promulgated562Paths.includes('/media/sapl/public/normajuridica/2018/254/lp_562.18.pdf'));
    assert.match(promulgated562?.links[0]?.text || '', /14\/09\/2018.*data citada/);
    assert.match(promulgated562?.links[1]?.text || '', /18\/09\/2018/);
    assert.match(promulgated562?.note || '', /não confirma identidade jurídica nem efeito da revogação/i);
    const ordinary1894 = Object.entries(graphLayout.saplRegistry.statuses)
      .find(([citation]) => /1\.894.*1969/.test(citation))?.[1];
    assert.equal(ordinary1894?.status, 'species_conflict');
    assert.match(ordinary1894?.note || '', /referência menciona 31\/12\/1969; a ficha SAPL está datada de 25\/12\/1969/i);
    const lei4566 = Object.entries(graphLayout.saplRegistry.statuses)
      .find(([citation]) => /4\.566.*1992/.test(citation))?.[1];
    assert.equal(lei4566?.status, 'year_conflict');
    assert.ok(lei4566?.links.some((link) => new URL(link.href).hostname === 'www2.natal.rn.gov.br'));
    const leiPromulgada275 = Object.entries(graphLayout.saplRegistry.statuses)
      .find(([citation]) => /275.*2009/.test(citation))?.[1];
    assert.equal(leiPromulgada275?.status, 'identity_conflict');
    assert.equal(leiPromulgada275?.links.filter((link) => /\/storage\/app\/media\/DOM\/anexos\/dom_20090317\.pdf$/.test(new URL(link.href).pathname)).length, 2,
      'the original official gazette PDF and its page-specific link must both be available');
    const lc55 = Object.entries(graphLayout.saplRegistry.statuses)
      .find(([citation]) => /55.*2004/.test(citation))?.[1];
    assert.equal(lc55?.status, 'not_checked');
    assert.equal(lc55?.links.length, 0, 'do not imply that the locally extracted LC 55 identity has been matched in SAPL');
    assert.equal(graphLayout.parallelRelations, 2);
    assert.match(graphLayout.demoTitle, /Art\. 260/i, 'the heading must identify the article that contains the seven repeal references');
    assert.doesNotMatch(graphLayout.demoTitle, /sete atos/i);
    assert.match(graphLayout.heading, /relações normativas/i);
    assert.equal(graphLayout.genericRepeal, true, 'Art. 266 generic repeal must remain visible without invented targets');
    assert.equal(graphLayout.amendment, true, 'Art. 261 amendment must remain distinct from repeal');
    assert.equal(graphLayout.focusableOverflow, 0,
      `focusable controls must remain within ${width}px: ${JSON.stringify(graphLayout.focusableOverflowDetails)}`);
    assert.equal(graphLayout.closedCaseNavLinkCount, 0,
      `links inside a closed case-navigation disclosure must not be rendered or tabbable at ${width}px`);
    if (width === 768) {
      await page.click('.pgm-demo__case-nav-more > summary');
      const openMenu = await page.$eval('.pgm-demo__case-nav-menu', (menu) => {
        const rect = menu.getBoundingClientRect();
        return {
          left: Math.round(rect.left),
          right: Math.round(rect.right),
          viewport: document.documentElement.clientWidth,
          visibleLinks: [...menu.querySelectorAll('a')].filter((link) => link.getClientRects().length).length,
        };
      });
      assert.ok(openMenu.left >= 0 && openMenu.right <= openMenu.viewport,
        `opened case-navigation menu must remain horizontally inside the viewport: ${JSON.stringify(openMenu)}`);
      assert.equal(openMenu.visibleLinks, 6);
      await page.click('.pgm-demo__case-nav-more > summary');
    }
    repealGraphViewports.push(graphLayout);
    if (width === 320 || width === 1280) {
      const screenshot = path.join(resolvedEvidenceDir, `pgm-lc258-repeal-graph-${width}px.png`);
      await page.screenshot({ path: screenshot, fullPage: width === 1280 });
      report.evidence.push(screenshot);
    }
  }
  report.checks.push({
    id: 'lc258-explicit-repeals-and-parallel-relations-responsive',
    status: 'passed',
    viewports: repealGraphViewports,
    legalScope: 'seven named Art. 260 references plus Art. 261 amendment and Art. 266 generic repeal; no legal adjudication',
  });
  report.checks.push({
    id: 'ctm-art20-historical-snapshots-and-amendment-diff-responsive',
    status: 'passed',
    viewports: ctmTimelineViewports,
    legalScope: 'three official historical consolidations plus one later promulgated partial amendment; all sources pending human review',
  });
  await page.setViewport({ width: 1280, height: 900 });
  await page.goto(new URL('/explorar/demo-consolidacao/', baseUrl).href, {
    waitUntil: 'domcontentloaded',
    timeout: 20000,
  });
  await page.waitForSelector('[data-graph-filter="express"]', { timeout: 5000 });
  await page.click('[data-graph-filter="express"]');
  const repealFocus = await page.evaluate(() => ({
    selected: document.querySelector('[data-graph-filter="express"]')?.getAttribute('aria-pressed'),
    liveText: document.querySelector('[data-graph-live]')?.textContent,
    emphasizedTargets: document.querySelectorAll('[data-graph-target][data-graph-emphasis="active"]').length,
    mutedTargets: document.querySelectorAll('[data-graph-target][data-graph-emphasis="muted"]').length,
    mutedLegibility: [...document.querySelectorAll('[data-graph-target][data-graph-emphasis="muted"]')]
      .map((target) => {
        const parseColor = (value) => {
          const channels = value.match(/[\d.]+/g)?.map(Number);
          if (channels?.length >= 3) return channels.slice(0, 3);
          const hex = value.match(/^#([\da-f]{6})$/i)?.[1];
          return hex ? [0, 2, 4].map((index) => Number.parseInt(hex.slice(index, index + 2), 16)) : null;
        };
        const composite = (foreground, background, opacity) => foreground.map(
          (channel, index) => channel * opacity + background[index] * (1 - opacity),
        );
        const luminance = (channels) => channels.map((channel) => {
          const normalized = channel / 255;
          return normalized <= 0.04045 ? normalized / 12.92 : ((normalized + 0.055) / 1.055) ** 2.4;
        }).reduce((total, channel, index) => total + channel * [0.2126, 0.7152, 0.0722][index], 0);
        const opacity = Number.parseFloat(getComputedStyle(target).opacity);
        const canvas = parseColor(getComputedStyle(document.documentElement).getPropertyValue('--jurix-canvas').trim());
        const background = composite(parseColor(getComputedStyle(target).backgroundColor), canvas, opacity);
        const ratio = (element) => {
          const foreground = composite(parseColor(getComputedStyle(element).color), canvas, opacity);
          const [lighter, darker] = [luminance(foreground), luminance(background)].sort((a, b) => b - a);
          return Number(((lighter + 0.05) / (darker + 0.05)).toFixed(2));
        };
        return {
          opacity,
          headingContrast: ratio(target.querySelector('h3')),
          explanationContrast: ratio(target.querySelector('p')),
        };
      }),
    allTargetsRemainAvailable: [...document.querySelectorAll('[data-graph-target]')]
      .every((target) => target.getAttribute('aria-hidden') !== 'true'),
    edgeKinds: [...new Set([...document.querySelectorAll('.pgm-demo__edge[data-graph-emphasis="active"]')]
      .map((edge) => edge.dataset.edgeKind?.replace(/-source$/, '')))],
  }));
  assert.equal(repealFocus.selected, 'true');
  assert.match(repealFocus.liveText, /seis leis e um artigo/i);
  assert.equal(repealFocus.emphasizedTargets, 7);
  assert.equal(repealFocus.mutedTargets, 2);
  assert.ok(repealFocus.mutedLegibility.every((item) => item.opacity >= 0.82), 'filtered graph relations must remain visually secondary but legible');
  assert.ok(repealFocus.mutedLegibility.every((item) => item.headingContrast >= 4.5 && item.explanationContrast >= 4.5), 'muted graph labels must retain 4.5:1 text contrast');
  assert.equal(repealFocus.allTargetsRemainAvailable, true);
  assert.deepEqual(repealFocus.edgeKinds, ['express']);
  const highlightedGraph = path.join(resolvedEvidenceDir, 'pgm-lc258-repeals-focused.png');
  await page.$eval('.pgm-demo__network', (node) => node.scrollIntoView({ block: 'start' }));
  await page.$('.pgm-demo__network').then((node) => node.screenshot({ path: highlightedGraph }));
  report.evidence.push(highlightedGraph);
  await page.click('[data-graph-filter="amendment"]');
  assert.equal(await page.$eval('[data-graph-filter="amendment"]', (node) => node.getAttribute('aria-pressed')), 'true');
  assert.equal(await page.$$eval('[data-graph-target][data-graph-emphasis="active"]', (nodes) => nodes.length), 1);
  assert.match(await page.$eval('[data-graph-live]', (node) => node.textContent), /não é uma revogação/i);
  await page.click('[data-graph-filter="all"]');
  assert.equal(await page.$$eval('[data-graph-target][data-graph-emphasis="active"]', (nodes) => nodes.length), 9);
  await page.focus('[data-graph-filter="generic"]');
  await page.keyboard.press('Enter');
  assert.equal(await page.$eval('[data-graph-filter="generic"]', (node) => node.getAttribute('aria-pressed')), 'true');
  assert.equal(await page.$$eval('[data-graph-target][data-graph-emphasis="active"]', (nodes) => nodes.length), 1);
  assert.equal(await page.evaluate(() => document.activeElement?.dataset.graphFilter), 'generic');
  await page.click('[data-graph-filter="all"]');
  report.checks.push({ id: 'lc258-graph-interactive-relation-highlighting', status: 'passed', details: repealFocus, keyboard: 'Enter activates the focused native filter button; focus remains visible on the control', screenshot: highlightedGraph });
  await page.click('.pgm-demo__sapl-evidence summary');
  const disclosureInteraction = await page.$eval('.pgm-demo__sapl-evidence', (element) => ({
    open: element.open,
    linkVisible: Boolean(element.querySelector('a')?.getClientRects().length),
  }));
  assert.equal(disclosureInteraction.open, true);
  assert.equal(disclosureInteraction.linkVisible, true);
  report.checks.push({ id: 'sapl-registry-disclosure-opens-official-record', status: 'passed' });

  await page.goto(new URL('/assistente/?corpus=archive-qa', baseUrl).href, {
    waitUntil: 'domcontentloaded',
    timeout: 20000,
  });
  assert.equal(await page.$eval('body', (body) => body.dataset.qaArchiveCorpus), 'true');
  assert.equal(await page.$eval('meta[name="jurix-authenticated"]', (meta) => meta.content), 'false');
  const corpusNotice = await page.$('details.jurix-corpus-notice');
  assert.ok(corpusNotice, 'archive limitations must use an expandable native disclosure');
  assert.match(await corpusNotice.$eval('summary', (summary) => summary.innerText), /extrações pendentes de revisão/i);
  assert.match(await corpusNotice.$eval('summary', (summary) => summary.innerText), /atualização do acervo não confirmada/i);
  await page.click('.jurix-corpus-notice__summary');
  assert.equal(await corpusNotice.evaluate((details) => details.open), true);
  const corpusNoticeDetails = await corpusNotice.$eval('.jurix-corpus-notice__details', (panel) => panel.innerText);
  assert.match(corpusNoticeDetails, /Metadados e segmentação estão sob revisão/i);
  assert.match(corpusNoticeDetails, /atualização de uma ou mais fontes oficiais não está confirmada/i);
  assert.match(corpusNoticeDetails, /não confirma a publicação de cada documento citado/i);
  await page.click('.jurix-corpus-notice__summary');
  assert.equal(await corpusNotice.evaluate((details) => details.open), false);
  await page.focus('.jurix-corpus-notice__summary');
  await page.keyboard.press('Enter');
  assert.equal(await corpusNotice.evaluate((details) => details.open), true);
  await page.keyboard.press('Space');
  assert.equal(await corpusNotice.evaluate((details) => details.open), false);
  report.checks.push({ id: 'archive-caveat-disclosure-is-accessible-and-complete', status: 'passed' });

  // Start from the ordinary assistant entry (no archive URL or prior scope),
  // then exercise the user's explicit fallback into the unreviewed PDF corpus.
  await page.goto(new URL('/assistente/?new=1', baseUrl).href, {
    waitUntil: 'domcontentloaded',
    timeout: 20000,
  });
  assert.equal(await page.$eval('body', (body) => body.dataset.qaArchiveCorpus), 'false');
  const archiveFallbackQuestion = 'O que prevê o Art. 262 da Lei Complementar nº 258/2024?';
  const consolidatedMiss = await submitQuestion(archiveFallbackQuestion);
  assert.match(consolidatedMiss, /n[aã]o localizei|n[aã]o encontrei/i);
  const archiveFallbackLink = await page.$('[data-archive-search="1"]');
  assert.ok(archiveFallbackLink, 'a consolidated-corpus miss must offer an explicit archive search');
  const archiveFallbackReachability = await archiveFallbackLink.evaluate((link) => {
    const rect = link.getBoundingClientRect();
    const composerTop = document.getElementById('conversation-input-bar')?.getBoundingClientRect().top
      ?? document.documentElement.clientHeight;
    const hit = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2);
    return {
      visible: rect.width > 0 && rect.height > 0 && rect.top >= 0 && rect.bottom <= composerTop,
      receivesPointer: hit === link || link.contains(hit),
      href: link.href,
    };
  });
  assert.ok(archiveFallbackReachability.visible, 'the fixed composer must not cover the archive fallback');
  assert.ok(archiveFallbackReachability.receivesPointer, 'the archive fallback must be clickable');
  const archiveFallbackScreenshot = path.join(resolvedEvidenceDir, 'pgm-default-to-review-archive-fallback.png');
  await page.screenshot({ path: archiveFallbackScreenshot, fullPage: false });
  report.evidence.push(archiveFallbackScreenshot);

  const archiveSearchPost = new Promise((resolve, reject) => {
    const timeout = setTimeout(() => reject(new Error('archive fallback did not submit a new search')), 90000);
    const onRequest = (request) => {
      if (request.method() !== 'POST' || !request.url().includes('/api/v1/search/answer/stream/')) return;
      let payload;
      try { payload = JSON.parse(request.postData() || '{}'); } catch { return; }
      clearTimeout(timeout);
      page.off('request', onRequest);
      resolve(payload);
    };
    page.on('request', onRequest);
  });
  await page.click('[data-archive-search="1"]');
  const archivePayload = await archiveSearchPost;
  assert.equal(archivePayload.question, archiveFallbackQuestion);
  assert.equal(archivePayload.qa_archive_corpus, true, 'fallback must preserve archive corpus scope in the API request');
  await page.waitForFunction(() =>
    location.pathname.startsWith('/assistente/local-')
      && new URLSearchParams(location.search).get('corpus') === 'archive-qa'
      && document.body.dataset.qaArchiveCorpus === 'true',
  { timeout: 30000 },
  );
  await page.waitForFunction(() => {
    const answer = [...document.querySelectorAll('.message-assistant .message-body')].at(-1);
    const button = document.getElementById('send-button');
    return answer?.innerText?.includes('Art. 262')
      && button && !button.disabled
      && !answer.hasAttribute('data-streaming');
  }, { timeout: 180000 });
  const archiveFallbackAnswer = await page.$$eval(
    '.message-assistant .message-body',
    (answers) => answers.at(-1)?.innerText || '',
  );
  assert.match(archiveFallbackAnswer, /Art\. 262/i);
  const archiveFallbackSources = await page.$$('.message-assistant .jurix-sources-pill-btn');
  assert.ok(archiveFallbackSources.length, 'the archive answer must expose its PDF evidence without F5');
  await archiveFallbackSources.at(-1).click();
  await page.waitForFunction(() =>
    document.getElementById('jurix-sources-drawer-panel')?.getAttribute('aria-hidden') === 'false');
  const expandArchiveEvidence = await page.$(
    '#jurix-sources-drawer-panel .jurix-source-group-toggle-all',
  );
  assert.ok(expandArchiveEvidence, 'the source drawer must expose the grouped archive evidence control');
  await expandArchiveEvidence.evaluate((button) => button.click());
  await page.waitForFunction(() =>
    [...document.querySelectorAll('#jurix-sources-drawer-panel details.jurix-source-group')]
      .some((group) => group.open));
  const archiveEvidenceCards = await page.$$eval(
    '#jurix-sources-drawer-panel .jurix-rag-source',
    (cards) => cards.map((card) => ({
      label: card.getAttribute('aria-label') || '',
      text: card.textContent || '',
      href: card.querySelector('.jurix-rag-source__open:not(.jurix-rag-source__open--secondary)')?.href
        || card.dataset.url || '',
    })),
  );
  assert.ok(archiveEvidenceCards.some((card) =>
    /258\/2024/.test(card.label) && /Art\. 262/i.test(card.text)
      && /\/normas\/documentos\/[^/]+\/pdf\//.test(card.href)),
  'the archive fallback must expose an openable local PDF from the consulted-sources drawer');
  const archivePdfLinkSelector = '#jurix-sources-drawer-panel .jurix-rag-source--archive .jurix-rag-source__open:not(.jurix-rag-source__open--secondary)';
  const archivePdfLinkState = await page.$eval(archivePdfLinkSelector, (link) => ({
    href: link.href,
    target: link.target,
    rel: link.rel,
    visible: Boolean(link.getClientRects().length) && getComputedStyle(link).visibility === 'visible',
  }));
  assert.equal(archivePdfLinkState.target, '_blank');
  assert.match(archivePdfLinkState.rel, /noopener/);
  assert.ok(archivePdfLinkState.visible, 'the PDF link must be visible and keyboard-focusable');
  const archivePdfUrl = new URL(archivePdfLinkState.href);
  assert.equal(archivePdfUrl.hostname, base.hostname);
  assert.match(archivePdfUrl.pathname, /\/normas\/documentos\/[^/]+\/pdf\//);
  assert.match(archivePdfUrl.hash, /^#page=\d+$/);
  await page.keyboard.press('Escape');
  await page.waitForFunction(() =>
    document.getElementById('jurix-sources-drawer-panel')?.getAttribute('aria-hidden') === 'true');
  report.checks.push({
    id: 'default-assistant-fallback-to-review-archive',
    status: 'passed',
    evidence: archiveFallbackScreenshot,
    archiveAnswerContainsArticle262: true,
    archiveSourcesOpenable: archiveEvidenceCards.length,
    archivePdfPath: archivePdfUrl.pathname + archivePdfUrl.hash,
    caveat: 'archive PDF extraction remains pending human review and is not a legal determination',
  });

  const buildSummary = await page.$('.workspace-build-details > summary');
  assert.ok(buildSummary, 'shared shell must expose the technical instance disclosure');
  await buildSummary.click();
  await page.waitForSelector('.workspace-build-details[open] .workspace-build-details__panel');
  const buildDetails = await page.$eval('.workspace-build-details__panel', (panel) => panel.innerText);
  const buildVersion = buildDetails.match(/Build\s*\n([^\n]+)/i)?.[1]?.trim();
  const buildRevision = buildDetails.match(/Revis[aã]o\s*\n([^\n]+)/i)?.[1]?.trim();
  if (allowUnversionedLocalQa) {
    assert.equal(buildVersion, 'build local não identificado');
    assert.equal(buildRevision, 'não informada');
  } else {
    assert.ok(buildVersion && !/build local não identificado/i.test(buildVersion), 'QA smoke must target a build with explicit version metadata');
    assert.match(buildRevision || '', /^[a-f0-9]{7,40}$/i, 'QA smoke must target an explicitly identified source revision');
  }
  assert.match(buildDetails, /QA isolado/);
  assert.match(buildDetails, /Acervo histórico local \(QA\)/);
  const buildScreenshot = path.join(resolvedEvidenceDir, 'pgm-build-identity.png');
  await page.screenshot({ path: buildScreenshot, fullPage: false });
  report.evidence.push(buildScreenshot);
  report.checks.push({
    id: 'build-and-corpus-disclosure',
    status: allowUnversionedLocalQa ? 'unversioned-local-checkout' : 'passed',
    note: allowUnversionedLocalQa
      ? 'the QA server intentionally exposes no release version or source revision for this dirty checkout'
      : 'release version and source revision are explicit',
  });
  await buildSummary.click();

  const referenceQuestion = 'A Lei Complementar nº 198/2021 cita ou faz remissão à Lei Complementar nº 55/2004? Liste todos os artigos do PDF arquivado que mencionam a LC 55/2004 e esclareça se isso comprova alteração normativa.';
  const referenceAnswer = await submitQuestion(referenceQuestion);
  assert.match(referenceAnswer, /refer[eê]ncia|remiss[aã]o/i);
  assert.match(referenceAnswer, /n[aã]o comprova|n[aã]o demonstra|n[aã]o permite concluir/i);

  const sourcePills = await page.$$('.message-assistant .jurix-sources-pill-btn');
  const sourcePill = sourcePills.at(-1);
  assert.ok(sourcePill, 'a completed answer with evidence must show the sources control without F5');
  const sourceData = await page.$$eval('.message-assistant [id^="sources-"]', (containers) => {
    const node = containers.at(-1);
    return {
    count: Array.isArray(node._sourcesData) ? node._sourcesData.length : 0,
    deviceRefs: (node._sourcesData || []).map((item) => item.dispositivo_ref || ''),
    };
  });
  assert.ok(sourceData.count >= 2, `expected multiple recovered articles, got ${sourceData.count}`);
  for (const article of ['1', '2', '4', '6']) {
    assert.ok(
      sourceData.deviceRefs.some((reference) => new RegExp(`art\\.?\\s*${article}\\b`, 'i').test(reference)),
      `the archived LC 198/2021 reference scan should include Art. ${article}`,
    );
  }

  const downloadSession = await page.createCDPSession();
  await downloadSession.send('Page.setDownloadBehavior', {
    behavior: 'allow',
    downloadPath: resolvedEvidenceDir,
  });
  const visibleEvidenceExportButtons = await page.$$('.message-assistant .export-evidence-button:not(.is-hidden)');
  const evidenceExportButton = visibleEvidenceExportButtons.at(-1);
  assert.ok(evidenceExportButton, 'a completed answer with citations must expose the evidence export');
  await evidenceExportButton.click();
  const downloadDeadline = Date.now() + 15000;
  let exportedEvidencePath = '';
  while (Date.now() < downloadDeadline) {
    const downloadedFiles = await fs.readdir(resolvedEvidenceDir);
    const downloadedEvidence = downloadedFiles.find((name) => /^jurix-evidencias-\d{4}-\d{2}-\d{2}\.json$/.test(name));
    if (downloadedEvidence) {
      exportedEvidencePath = path.join(resolvedEvidenceDir, downloadedEvidence);
      break;
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  assert.ok(exportedEvidencePath, 'clicking evidence export must download a JSON file');
  const exportedEvidence = JSON.parse(await fs.readFile(exportedEvidencePath, 'utf8'));
  assert.equal(exportedEvidence.schema_version, 'jurix-evidence-v1');
  assert.ok(Array.isArray(exportedEvidence.sources) && exportedEvidence.sources.length >= sourceData.count);
  assert.ok(exportedEvidence.sources.every((source) =>
    typeof source.citation_id === 'string' && /^(?:jurix|qa):/.test(source.citation_id)
    && typeof source.norma === 'string' && source.norma.trim().length > 0
    && typeof source.dispositivo === 'string' && source.dispositivo.trim().length > 0
    && typeof source.excerpt === 'string' && source.excerpt.trim().length > 0
  ), 'export must preserve stable citation, norm, device and evidence excerpt fields');
  assert.ok(exportedEvidence.sources.every((source) => {
    if (source.official_url) {
      const parsed = new URL(source.official_url);
      return !['localhost', '127.0.0.1', '::1'].includes(parsed.hostname);
    }
    return source.local_pdf_url === null
      || /^\/normas\/documentos\/[0-9a-f-]{36}\/pdf\/(?:#page=\d+)?$/i.test(source.local_pdf_url);
  }), 'local QA PDF routes must not be mislabeled as official or exported as absolute localhost URLs');
  const pageAnchoredLocalEvidence = exportedEvidence.sources.filter((source) => (
    source.local_pdf_url && Number.isInteger(source.page) && source.page > 0
  ));
  assert.ok(pageAnchoredLocalEvidence.length > 0, 'real local-PDF export should include page-addressable evidence');
  assert.ok(pageAnchoredLocalEvidence.every((source) => (
    new URL(source.local_pdf_url, baseUrl).hash === `#page=${source.page}`
  )), 'local PDF export links must open at the exported evidence page');
  const exportedPdfRoutes = [...new Set(pageAnchoredLocalEvidence.map((source) => (
    new URL(source.local_pdf_url, baseUrl).pathname
  )))];
  const exportedPdfResponses = await page.evaluate(async (paths) => Promise.all(paths.map(async (path) => {
    const response = await fetch(path);
    const bytes = new Uint8Array(await response.arrayBuffer());
    const signature = new TextDecoder().decode(bytes.subarray(0, 5));
    const tail = new TextDecoder().decode(bytes.subarray(Math.max(0, bytes.length - 2048)));
    return {
      path,
      status: response.status,
      contentType: response.headers.get('content-type') || '',
      validPdf: signature.startsWith('%PDF') && tail.includes('%%EOF'),
    };
  })), exportedPdfRoutes);
  assert.ok(exportedPdfResponses.every((response) => (
    response.status === 200 && /application\/pdf/i.test(response.contentType) && response.validPdf
  )), 'all unique exported local-PDF routes must resolve to valid PDF bytes');
  report.checks.push({
    id: 'evidence-export-downloads-structured-provenance',
    status: 'passed',
    schemaVersion: exportedEvidence.schema_version,
    sourceCount: exportedEvidence.sources.length,
    pageAnchoredLocalEvidenceCount: pageAnchoredLocalEvidence.length,
    validatedLocalPdfRouteCount: exportedPdfResponses.length,
    fields: ['citation_id', 'norma', 'dispositivo', 'excerpt'],
  });
  await downloadSession.detach();

  // Verify the focus trap in the narrow-screen modal mode. The wide side sheet
  // at 1200px+ intentionally remains non-modal so users can continue reading.
  await page.setViewport({ width: 1024, height: 900 });
  await page.waitForFunction(() => (
    document.documentElement.clientWidth === 1024
    && window.matchMedia('(max-width: 1199px)').matches
  ));
  const composerFilterLayout = await page.$eval('#conversation-input-bar .jurix-composer-filters', (filters) => {
    const controls = [...filters.querySelectorAll(':scope > .figma-search-dropdown')];
    const temporal = filters.querySelector('.jurix-temporal-filter');
    const labels = controls.map((control) => {
      const label = control.querySelector('[data-control-label]');
      return {
        text: label?.textContent?.trim() || '',
        width: Math.round(control.getBoundingClientRect().width),
        whiteSpace: label ? getComputedStyle(label).whiteSpace : '',
      };
    });
    return {
      display: getComputedStyle(filters).display,
      columnCount: getComputedStyle(filters).gridTemplateColumns.split(' ').length,
      width: Math.round(filters.getBoundingClientRect().width),
      labels,
      temporal: temporal ? {
        width: Math.round(temporal.getBoundingClientRect().width),
        gridColumn: getComputedStyle(temporal).gridColumn,
      } : null,
    };
  });
  assert.equal(composerFilterLayout.display, 'grid', `composer filters should reflow at 1024px: ${JSON.stringify(composerFilterLayout)}`);
  assert.equal(composerFilterLayout.columnCount, 3, `composer should preserve three readable control columns: ${JSON.stringify(composerFilterLayout)}`);
  assert.ok(composerFilterLayout.labels.length >= 3 && composerFilterLayout.labels.every((item) => item.width >= 140 && item.whiteSpace === 'nowrap'), `filter labels must not collapse into one-word-per-line controls: ${JSON.stringify(composerFilterLayout)}`);
  assert.ok(composerFilterLayout.temporal?.width >= composerFilterLayout.width - 2, `temporal control should occupy its own full row: ${JSON.stringify(composerFilterLayout)}`);
  report.checks.push({ id: 'composer-controls-remain-readable-at-1024px', status: 'passed', ...composerFilterLayout });
  await page.waitForFunction(() => {
    const trigger = [...document.querySelectorAll('.message-assistant .jurix-sources-pill-btn')].at(-1);
    if (!trigger?.getClientRects().length) return false;
    const rect = trigger.getBoundingClientRect();
    const current = [rect.left, rect.top, rect.width, rect.height].map((value) => Math.round(value * 10) / 10);
    const previous = window.__pgmStableSourceTriggerRect;
    const stablePolls = previous && current.every((value, index) => value === previous[index])
      ? (window.__pgmStableSourceTriggerPolls || 0) + 1
      : 0;
    window.__pgmStableSourceTriggerRect = current;
    window.__pgmStableSourceTriggerPolls = stablePolls;
    return stablePolls >= 3;
  }, { polling: 100, timeout: 5000 });
  const modalSourcePill = (await page.$$('.message-assistant .jurix-sources-pill-btn')).at(-1);
  assert.ok(modalSourcePill, 'the source trigger must remain present after viewport changes');
  await modalSourcePill.click();
  try {
    await page.waitForFunction(() => {
      const drawer = document.getElementById('jurix-sources-drawer-panel');
      return drawer && drawer.getAttribute('aria-hidden') === 'false'
        && drawer.querySelectorAll('.jurix-rag-source').length > 0;
    });
  } catch (error) {
    const diagnostic = await page.evaluate(() => {
      const drawer = document.getElementById('jurix-sources-drawer-panel');
      const trigger = [...document.querySelectorAll('.message-assistant .jurix-sources-pill-btn')].at(-1);
      const rect = trigger?.getBoundingClientRect();
      const center = rect && document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2);
      return {
        url: location.pathname,
        width: document.documentElement.clientWidth,
        trigger: trigger ? { disabled: trigger.disabled, text: trigger.innerText, visible: Boolean(trigger.getClientRects().length), centerTarget: center?.outerHTML?.slice(0, 180) } : null,
        drawer: drawer ? { hidden: drawer.getAttribute('aria-hidden'), modal: drawer.getAttribute('aria-modal'), cards: drawer.querySelectorAll('.jurix-rag-source').length } : null,
      };
    });
    diagnostic.pageErrorNames = pageErrors;
    throw new Error(`${error.message}; source drawer diagnostic: ${JSON.stringify(diagnostic)}`);
  }
  await page.waitForFunction(() => {
    const drawer = document.getElementById('jurix-sources-drawer-panel');
    const rect = drawer?.getBoundingClientRect();
    return rect && rect.left >= 0 && rect.right <= document.documentElement.clientWidth;
  }, { timeout: 5000 });
  const modalDrawerState = await page.$eval('#jurix-sources-drawer-panel', (drawer) => {
    const rect = drawer.getBoundingClientRect();
    return {
      ariaModal: drawer.getAttribute('aria-modal'),
      className: drawer.className,
      left: rect.left,
      right: rect.right,
      viewportWidth: document.documentElement.clientWidth,
      evidenceCards: drawer.querySelectorAll('.jurix-rag-source').length,
      computed: {
        position: getComputedStyle(drawer).position,
        right: getComputedStyle(drawer).right,
        transform: getComputedStyle(drawer).transform,
        bodyTransform: getComputedStyle(document.body).transform,
      },
    };
  });
  assert.equal(modalDrawerState.ariaModal, 'true', `drawer should be modal at 1024px: ${JSON.stringify(modalDrawerState)}`);
  assert.ok(
    modalDrawerState.left >= 0 && modalDrawerState.right <= modalDrawerState.viewportWidth,
    `source drawer must remain inside the viewport: ${JSON.stringify(modalDrawerState)}`,
  );
  await page.waitForFunction(() => document.activeElement?.id === 'jurix-sources-drawer-close');
  await page.keyboard.down('Shift');
  await page.keyboard.press('Tab');
  await page.keyboard.up('Shift');
  const reverseTabFocus = await page.evaluate(() => {
    const panel = document.getElementById('jurix-sources-drawer-panel');
    return {
      remainsInModal: Boolean(panel?.contains(document.activeElement)),
      focusedLabel: document.activeElement?.getAttribute('aria-label') || document.activeElement?.textContent?.trim().slice(0, 80) || '',
    };
  });
  assert.ok(reverseTabFocus.remainsInModal, `Shift+Tab must not move focus behind the modal drawer: ${JSON.stringify(reverseTabFocus)}`);
  report.checks.push({ id: 'source-drawer-reverse-tab-stays-modal', status: 'passed', ...reverseTabFocus });
  const evidenceView = await page.$eval('#jurix-sources-drawer-panel', (drawer) => {
    const cards = [...drawer.querySelectorAll('.jurix-rag-source')];
    const pdfLink = drawer.querySelector('.jurix-rag-source__open[href*="/normas/documentos/"][href*="/pdf/"]');
    const firstCard = cards[0];
    const sourceAction = firstCard?.querySelector('.jurix-rag-source__open, .jurix-rag-source__copy');
    const expandSource = firstCard?.querySelector('.jurix-rag-source__details summary');
    return {
      visible: Boolean(drawer.getClientRects().length),
      title: drawer.querySelector('#sources-drawer-title')?.innerText || '',
      cards: cards.length,
      groups: [...new Set(cards.map((card) => card.querySelector('.source-title')?.innerText || ''))].length,
      hasContribution: cards.some((card) => Boolean(card.querySelector('.jurix-rag-source__contribution'))),
      hasPendingReviewNotice: /revis[aã]o/i.test(drawer.innerText),
      readability: {
        excerptFontSize: firstCard ? getComputedStyle(firstCard.querySelector('.source-snippet')).fontSize : '',
        fullTextFontSize: firstCard ? getComputedStyle(firstCard.querySelector('.jurix-rag-source__details p')).fontSize : '',
        contributionFontSize: firstCard ? getComputedStyle(firstCard.querySelector('.jurix-rag-source__contribution')).fontSize : '',
        sourceActionHeight: sourceAction ? Math.round(sourceAction.getBoundingClientRect().height) : 0,
        expandTargetHeight: expandSource ? Math.round(expandSource.getBoundingClientRect().height) : 0,
      },
      pdfHref: pdfLink?.href || '',
      geometry: {
        viewportWidth: document.documentElement.clientWidth,
        left: Math.round(drawer.getBoundingClientRect().left),
        right: Math.round(drawer.getBoundingClientRect().right),
        width: Math.round(drawer.getBoundingClientRect().width),
        scrollWidth: drawer.scrollWidth,
        clientWidth: drawer.clientWidth,
      },
    };
  });
  assert.equal(evidenceView.visible, true);
  assert.match(evidenceView.title, /Fontes Consultadas/i);
  assert.ok(evidenceView.cards >= 2);
  assert.ok(evidenceView.groups >= 1);
  assert.ok(evidenceView.hasContribution);
  assert.ok(evidenceView.hasPendingReviewNotice, `unreviewed PDF sources must retain their review caveat: ${JSON.stringify(evidenceView)}`);
  assert.equal(evidenceView.readability.excerptFontSize, '14px');
  assert.equal(evidenceView.readability.fullTextFontSize, '14px');
  assert.equal(evidenceView.readability.contributionFontSize, '13px');
  assert.ok(evidenceView.readability.sourceActionHeight >= 44, 'source action must meet the 44px touch target');
  assert.ok(evidenceView.readability.expandTargetHeight >= 44, 'source expansion must meet the 44px touch target');
  assert.ok(
    evidenceView.geometry.left >= 0 && evidenceView.geometry.right <= evidenceView.geometry.viewportWidth,
    `source drawer must remain inside the viewport: ${JSON.stringify(evidenceView.geometry)}`,
  );
  assert.ok(evidenceView.pdfHref, 'at least one source must offer the local PDF');
  const expandAllButton = await page.$('.jurix-source-group-toggle-all');
  assert.ok(expandAllButton);
  await expandAllButton.click();
  await page.waitForFunction(() => {
    const button = document.querySelector('.jurix-source-group-toggle-all');
    const groups = [...document.querySelectorAll('.jurix-source-group')];
    return button?.getAttribute('aria-expanded') === 'true'
      && button.textContent.includes('Recolher todas')
      && groups.length > 0 && groups.every((group) => group.open);
  });
  report.checks.push({
    id: 'source-group-expand-all-state',
    status: 'passed',
    labelAfterExpansion: await expandAllButton.evaluate((button) => button.innerText),
    expandedGroups: await page.$$eval('.jurix-source-group[open]', (groups) => groups.length),
  });

  const pdfCheck = await page.evaluate(async (href) => {
    const response = await fetch(href);
    const buffer = await response.arrayBuffer();
    const bytes = new Uint8Array(buffer);
    const signature = new TextDecoder().decode(bytes.subarray(0, 5));
    const tail = new TextDecoder().decode(bytes.subarray(Math.max(0, bytes.length - 2048)));
    return {
      status: response.status,
      contentType: response.headers.get('content-type') || '',
      bytes: bytes.length,
      validPdf: signature.startsWith('%PDF') && tail.includes('%%EOF'),
    };
  }, evidenceView.pdfHref);
  assert.equal(pdfCheck.status, 200, `source PDF route failed: ${evidenceView.pdfHref}`);
  assert.match(pdfCheck.contentType, /application\/pdf/i);
  assert.ok(pdfCheck.bytes > 1000 && pdfCheck.validPdf);
  const sourcePdfLink = await page.$('.jurix-rag-source__open[href*="/normas/documentos/"][href*="/pdf/"]');
  assert.ok(sourcePdfLink, 'the consulted-source card must expose its PDF action');
  const sourcePdfLinkDetails = await sourcePdfLink.evaluate((link) => ({
    href: link.href,
    target: link.target,
    label: link.innerText.trim(),
  }));
  assert.equal(sourcePdfLinkDetails.target, '_blank', 'opening source PDF must preserve the assistant session');
  const popupPromise = new Promise((resolve) => page.once('popup', resolve));
  await sourcePdfLink.click();
  const pdfPopup = await popupPromise;
  await pdfPopup.waitForFunction(
    (expectedUrl) => location.href.split('#')[0] === expectedUrl,
    { timeout: 10000 },
    sourcePdfLinkDetails.href.split('#')[0],
  );
  // Chromium's built-in PDF viewer does not reliably emit networkidle0. The
  // direct fetch above verifies the response; here we verify the actual tab and
  // allow the native viewer a moment to paint before capturing it.
  await new Promise((resolve) => setTimeout(resolve, 1500));
  assert.equal(pdfPopup.url().split('#')[0], sourcePdfLinkDetails.href.split('#')[0]);
  const openedPdfScreenshot = path.join(resolvedEvidenceDir, 'pgm-source-pdf-opened.png');
  const openedPdfPng = await pdfPopup.screenshot({ path: openedPdfScreenshot, fullPage: false });
  assert.ok(openedPdfPng.length > 10000, 'Chrome PDF viewer should render a non-empty page screenshot');
  report.evidence.push(openedPdfScreenshot);
  report.checks.push({
    id: 'source-card-opens-rendered-pdf-in-new-tab',
    status: 'passed',
    target: sourcePdfLinkDetails.target,
    responseStatus: pdfCheck.status,
    contentType: pdfCheck.contentType,
    title: await pdfPopup.title(),
    screenshot: openedPdfScreenshot,
  });
  await pdfPopup.close();
  report.checks.push({
    id: 'real-archive-cross-reference-and-source-drawer',
    status: 'passed',
    evidenceCount: sourceData.count,
    deviceRefs: sourceData.deviceRefs,
    drawer: { ...evidenceView, pdfHref: undefined },
    pdf: pdfCheck,
    caveat: 'local extraction is pending review; this smoke verifies retrieval/UI, not legal correctness',
  });
  const evidenceScreenshot = path.join(resolvedEvidenceDir, 'pgm-cross-reference-with-sources.png');
  await page.screenshot({ path: evidenceScreenshot, fullPage: false });
  report.evidence.push(evidenceScreenshot);

  await page.keyboard.press('Escape');
  await page.waitForFunction(() => document.getElementById('jurix-sources-drawer-panel')?.getAttribute('aria-hidden') === 'true');
  const focusRestoredToSources = await page.evaluate(() =>
    document.activeElement?.classList.contains('jurix-sources-pill-btn') || false,
  );
  assert.equal(focusRestoredToSources, true, 'closing the source drawer must return focus to its invoking button');
  report.checks.push({ id: 'source-drawer-escape-restores-trigger-focus', status: 'passed' });

  const chainQuestion = 'A Lei Complementar nº 198/2021 alterou o art. 21 da Lei Complementar nº 55/2004? Compare a redação anterior e posterior ou informe a lacuna.';
  const chainAnswer = await submitQuestion(chainQuestion);
  assert.match(chainAnswer, /redação de origem/i);
  assert.match(chainAnswer, /não foi possível confirmar se o dispositivo consultado foi alterado ou revogado/i);
  assert.match(chainAnswer, /nem afirmar sua vigência atual/i);
  assert.doesNotMatch(chainAnswer, /quem alterou|em que data|tente outra formula[cç][aã]o/i);
  const sourcePillsAfterChainQuestion = await page.$$('.message-assistant .jurix-sources-pill-btn');
  assert.equal(
    sourcePillsAfterChainQuestion.length,
    sourcePills.length + 1,
    'the original article may be cited, but the missing change chain must not be invented',
  );
  const chainSourceData = await page.$$eval('.message-assistant [id^="sources-"]', (containers) => {
    const node = containers.at(-1);
    return (node?._sourcesData || []).map((item) => ({
      norma: item.norma_ref || '',
      dispositivo: item.dispositivo_ref || '',
      sourceKind: item.source_kind || '',
      page: item.page || null,
    }));
  });
  assert.equal(chainSourceData.length, 2);
  const originalArticleSource = chainSourceData.find((item) => /Lei Complementar nº 55\/2004/.test(item.norma));
  const candidateRepealSource = chainSourceData.find((item) => /Lei Complementar nº 258\/2024/.test(item.norma));
  assert.ok(originalArticleSource, 'the source drawer must preserve the original Art. 21 text');
  assert.match(originalArticleSource.dispositivo, /Art\.\s*21/i);
  assert.ok(candidateRepealSource, 'the source drawer must expose the later repeal clause as a separate candidate');
  assert.match(candidateRepealSource.dispositivo, /Art\.\s*260/i);
  assert.match(chainAnswer, /v[ií]nculo [eé] apenas candidato documental/i);
  assert.match(chainAnswer, /n[aã]o confirma, por si s[oó], a revoga[cç][aã]o/i);
  report.checks.push({
    id: 'missing-amendment-chain-with-grounded-origin-text',
    status: 'passed',
    sourceCount: chainSourceData.length,
    sources: chainSourceData,
    answer: chainAnswer,
  });

  const historicalDate = '2020-01-01';
  await page.$eval('#jurix-as-of-chat', (input, value) => {
    input.value = value;
    input.dispatchEvent(new Event('change', { bubbles: true }));
  }, historicalDate);
  await page.waitForFunction((value) => {
    const saved = JSON.parse(localStorage.getItem('jurix:search-options:v1') || '{}');
    return saved.as_of === value;
  }, {}, historicalDate);
  let temporalRequest = null;
  const captureTemporalRequest = (request) => {
    if (request.method() !== 'POST' || !request.url().endsWith('/api/v1/search/answer/stream/')) return;
    try {
      const payload = JSON.parse(request.postData() || '{}');
      if (payload.as_of === historicalDate) temporalRequest = { as_of: payload.as_of, qa_archive_corpus: payload.qa_archive_corpus };
    } catch (_) { /* non-JSON request is ignored */ }
  };
  page.on('request', captureTemporalRequest);
  const sourcePillsBeforeHistoricalQuery = await page.$$('.message-assistant .jurix-sources-pill-btn');
  await page.evaluate(() => {
    const container = document.getElementById('messages-container');
    window.__pgmScrollTrace = [];
    const record = (type, values = {}) => {
      window.__pgmScrollTrace.push({ type, ...values, top: container?.scrollTop ?? null });
      if (window.__pgmScrollTrace.length > 40) window.__pgmScrollTrace.shift();
    };
    container?.addEventListener('wheel', (event) => record('wheel', { deltaY: event.deltaY }), { passive: true });
    container?.addEventListener('scroll', () => record('scroll', {
      height: container.scrollHeight,
      client: container.clientHeight,
    }), { passive: true });
    document.addEventListener('keydown', (event) => {
      if (['PageUp', 'PageDown', 'Home', 'End', 'ArrowUp', 'ArrowDown'].includes(event.key)) {
        record('keydown', { key: event.key });
      }
    });
  });
  const historicalAnswer = await submitQuestion(
    'Qual era a redação do Art. 21 da Lei Complementar nº 55/2004 em 1º de janeiro de 2020? Responda apenas se houver versão histórica comprovável no acervo.',
  );
  page.off('request', captureTemporalRequest);
  assert.deepEqual(temporalRequest, { as_of: historicalDate, qa_archive_corpus: true });
  assert.match(historicalAnswer, /n[aã]o encontrei evid[eê]ncias hist[oó]ricas suficientes/i);
  assert.match(historicalAnswer, /redação atual n[aã]o será apresentada como se fosse a redação hist[oó]rica/i);
  const sourcePillsAfterHistoricalQuery = await page.$$('.message-assistant .jurix-sources-pill-btn');
  assert.equal(sourcePillsAfterHistoricalQuery.length, sourcePillsBeforeHistoricalQuery.length);
  await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  const historicalAnswerVisibility = await page.evaluate(() => {
    const container = document.getElementById('messages-container');
    const composer = document.getElementById('conversation-input-bar');
    const latestAnswer = [...document.querySelectorAll('.message-assistant')].at(-1);
    if (!container || !composer || !latestAnswer) return null;
    const containerRect = container.getBoundingClientRect();
    const composerRect = composer.getBoundingClientRect();
    const answerRect = latestAnswer.getBoundingClientRect();
    const visibleBottom = Math.min(containerRect.bottom, composerRect.top) - 8;
    return {
      answerBottom: Math.round(answerRect.bottom),
      answerTop: Math.round(answerRect.top),
      answerHeight: Math.round(answerRect.height),
      visibleTop: Math.round(containerRect.top),
      visibleBottom: Math.round(visibleBottom),
      answerVisible: answerRect.bottom > containerRect.top
        && answerRect.top < visibleBottom
        && answerRect.bottom <= visibleBottom,
      scrollTop: Math.round(container.scrollTop),
      scrollHeight: Math.round(container.scrollHeight),
      clientHeight: Math.round(container.clientHeight),
      scrollRemaining: Math.max(0, container.scrollHeight - container.scrollTop - container.clientHeight),
      scrollTrace: window.__pgmScrollTrace || [],
    };
  });
  assert.ok(
    historicalAnswerVisibility?.answerVisible,
    `a source-free historical abstention must remain visible above the composer: ${JSON.stringify(historicalAnswerVisibility)}`,
  );
  const historicalScreenshot = path.join(resolvedEvidenceDir, 'pgm-temporal-abstention-2020.png');
  await page.screenshot({ path: historicalScreenshot, fullPage: false });
  report.evidence.push(historicalScreenshot);
  report.checks.push({
    id: 'historical-date-is-transmitted-and-unavailable-version-abstains',
    status: 'passed',
    asOf: temporalRequest.as_of,
    sourceCount: 0,
    limitation: 'archive QA cannot reconstruct a historical version and did not substitute current text',
    screenshot: historicalScreenshot,
  });

  await page.$eval('#jurix-as-of-chat', (input) => {
    input.value = '';
    input.dispatchEvent(new Event('change', { bubbles: true }));
  });
  await page.waitForFunction(() => JSON.parse(localStorage.getItem('jurix:search-options:v1') || '{}').as_of === null);

  const transitionChainQuestion = 'Em um processo de licenciamento protocolado antes da entrada em vigor da LC 258/2024 e ainda sem despacho decisório, como devo conferir a aplicação da regra do Art. 21 da Lei Complementar nº 55/2004? Considere o Art. 260, inciso IV, e o Art. 262 da LC 258/2024. Informe a data de publicação e a data calculada de entrada em vigor apenas se houver evidência oficial recuperável, e explique o que ainda exige revisão antes de usar no processo concreto.';
  const transitionChainAnswer = await submitQuestion(transitionChainQuestion);
  assert.match(transitionChainAnswer, /Art\.?\s*260/i);
  assert.match(transitionChainAnswer, /Art\.?\s*262/i);
  assert.match(transitionChainAnswer, /Art\.?\s*21/i);
  assert.doesNotMatch(transitionChainAnswer, /(?:Art\.?\s*21[^.]{0,80})(?:permanece|continua) vigente/i);
  const transitionSources = await page.$$eval('.message-assistant [id^="sources-"]', (containers) => {
    const node = containers.at(-1);
    return (node?._sourcesData || []).map((item) => ({
      norma: item.norma_ref || '',
      dispositivo: item.dispositivo_ref || '',
      sourceKind: item.source_kind || '',
      page: item.page || null,
      sourceUrl: item.source_url || '',
    }));
  });
  assert.ok(transitionSources.some((item) => /Lei Complementar nº 258\/2024/i.test(item.norma) && /Art\.\s*260/i.test(item.dispositivo)));
  assert.ok(transitionSources.some((item) => /Lei Complementar nº 258\/2024/i.test(item.norma) && /Art\.\s*262/i.test(item.dispositivo)));
  assert.ok(transitionSources.some((item) => /Lei Complementar nº 55\/2004/i.test(item.norma) && /Art\.\s*21/i.test(item.dispositivo)));
  assert.ok(transitionSources.some((item) => /Lei Complementar nº 258\/2024/i.test(item.norma) && /Art\.\s*266/i.test(item.dispositivo)));
  const officialCommencement = transitionSources.find((item) =>
    /Lei Complementar nº 258\/2024/i.test(item.norma)
      && /Art\.\s*266\b/i.test(item.dispositivo)
      && item.sourceKind === 'official_gazette_extraction');
  const countingRule = transitionSources.find((item) =>
    /Lei Complementar nº 95\/1998/i.test(item.norma)
      && /§\s*1/i.test(item.dispositivo)
      && item.sourceKind === 'official_vacatio_counting_rule');
  const effectiveDateEvidenceComplete = Boolean(officialCommencement && countingRule);
  if (effectiveDateEvidenceComplete) {
    assert.match(transitionChainAnswer, /27\/03\/2025/,
      'complete official DOM and LC95 evidence should expose the calculated general effective date');
    assert.ok(Number.isInteger(officialCommencement.page) && officialCommencement.page > 0,
      'official DOM commencement evidence must carry its exact PDF page');
  } else {
    assert.match(transitionChainAnswer, /data concreta depende da publicação oficial/i,
      'without both official publication/commencement and counting-rule evidence, the answer must leave the date unresolved');
    assert.doesNotMatch(transitionChainAnswer, /27\/03\/2025/,
      'do not calculate a commencement date when the required evidence was not recovered');
  }
  const transitionSourcesPill = (await page.$$('.message-assistant .jurix-sources-pill-btn')).at(-1);
  assert.ok(transitionSourcesPill, 'the transition answer must expose its consulted sources');
  await transitionSourcesPill.click();
  await page.waitForFunction(() =>
    document.getElementById('jurix-sources-drawer-panel')?.getAttribute('aria-hidden') === 'false');
  const transitionDrawerCards = await page.$$eval(
    '#jurix-sources-drawer-panel .jurix-rag-source',
    (cards) => cards.map((card) => ({
      label: card.getAttribute('aria-label') || '',
      text: card.innerText || '',
      href: card.querySelector('.jurix-rag-source__open')?.href || '',
    })),
  );
  if (officialCommencement) {
    const domCommencementCard = transitionDrawerCards.find((card) =>
      /Lei Complementar nº 258\/2024/i.test(card.label)
        && /dom_20241227_extra_/i.test(card.href));
    assert.ok(domCommencementCard, `drawer must expose recovered official DOM evidence: ${JSON.stringify(transitionDrawerCards)}`);
    const domCommencementUrl = new URL(domCommencementCard.href);
    assert.equal(domCommencementUrl.hostname, 'www2.natal.rn.gov.br');
    assert.match(domCommencementUrl.pathname, /dom_20241227_extra_.*\.pdf$/i);
    assert.match(domCommencementUrl.hash, /^#page=\d+$/, 'official DOM source should open at the extracted page');
  }
  if (countingRule) {
    const lc95Card = transitionDrawerCards.find((card) =>
      /Lei Complementar nº 95\/1998/i.test(card.label)
        && /www\.planalto\.gov\.br/i.test(card.href));
    assert.ok(lc95Card, 'drawer must expose the recovered LC 95/1998 counting rule');
    assert.equal(new URL(lc95Card.href).hostname, 'www.planalto.gov.br');
  }
  await page.keyboard.press('Escape');
  await page.waitForFunction(() =>
    document.getElementById('jurix-sources-drawer-panel')?.getAttribute('aria-hidden') === 'true');
  const transitionChainScreenshot = path.join(resolvedEvidenceDir, 'pgm-lc258-transition-and-revocation.png');
  await page.screenshot({ path: transitionChainScreenshot, fullPage: false });
  report.evidence.push(transitionChainScreenshot);
  report.checks.push({
    id: 'pgm-transition-chain-covers-revocation-transition-and-origin-article',
    status: 'passed',
    sourceCount: transitionSources.length,
    sources: transitionSources,
    effectiveDateEvidenceComplete,
    answer: transitionChainAnswer,
    caveat: 'candidate PDF extractions are pending review; no conclusion of applicability or current validity',
    screenshot: transitionChainScreenshot,
  });

  await page.goto(new URL('/assistente/?new=1&corpus=archive-qa', baseUrl).href, {
    waitUntil: 'domcontentloaded',
    timeout: 20000,
  });
  const lp275Question = 'A Lei Complementar nº 258/2024, Art. 260, inciso V, revoga expressamente o Art. 21 da Lei Promulgada nº 275/2009? O que os documentos disponíveis permitem afirmar e o que permanece pendente de confirmação jurídica?';
  const lp275Answer = await submitQuestion(lp275Question);
  assert.match(lp275Answer, /Lei Promulgada nº 275\/2009/i);
  assert.match(lp275Answer, /O rebaixamento de guias/i);
  assert.match(lp275Answer, /Art\.\s*260/i);
  assert.match(lp275Answer, /pendentes de revis[aã]o/i);
  assert.doesNotMatch(lp275Answer, /n[aã]o localizei no acervo pesquis[aá]vel o texto de Art\. 21/i);
  assert.doesNotMatch(lp275Answer, /Art\.\s*21[^.]{0,100}(?:permanece|continua) vigente/i);
  const lp275Sources = await page.$$eval('.message-assistant [id^="sources-"]', (containers) => {
    const node = containers.at(-1);
    return (node?._sourcesData || []).map((item) => ({
      norma: item.norma_ref || '',
      dispositivo: item.dispositivo_ref || '',
      sourceType: item.source_type || '',
      localPdfUrl: item.local_pdf_url || '',
      page: item.page || null,
    }));
  });
  const lp275ArticleSource = lp275Sources.find((item) =>
    /Lei Promulgada nº 275\/2009/i.test(item.norma) && /Art\.\s*21/i.test(item.dispositivo));
  const lc258RepealSource = lp275Sources.find((item) =>
    /Lei Complementar nº 258\/2024/i.test(item.norma) && /Art\.\s*260/i.test(item.dispositivo));
  assert.ok(lp275ArticleSource, 'the cited LP 275/2009 Article 21 must remain a structured source');
  assert.ok(lc258RepealSource, 'the LC 258/2024 repeal clause must remain a structured source');
  assert.match(lp275ArticleSource.sourceType, /pendente de revis[aã]o/i);
  assert.equal(lp275ArticleSource.page, 6);
  assert.equal(new URL(lp275ArticleSource.localPdfUrl, baseUrl).pathname,
    '/normas/documentos/c452bfe5-1138-4962-a3f2-c4cc9b662007/pdf/');

  const lp275SourcesPill = (await page.$$('.message-assistant .jurix-sources-pill-btn')).at(-1);
  assert.ok(lp275SourcesPill, 'the live answer must expose its source drawer without reload');
  await lp275SourcesPill.click();
  await page.waitForFunction(() =>
    document.getElementById('jurix-sources-drawer-panel')?.getAttribute('aria-hidden') === 'false');
  const lp275DrawerCards = await page.$$eval(
    '#jurix-sources-drawer-panel .jurix-rag-source',
    (cards) => cards.map((card) => ({
      ariaLabel: card.getAttribute('aria-label') || '',
      href: card.querySelector('.jurix-rag-source__open')?.href || '',
      target: card.querySelector('.jurix-rag-source__open')?.target || '',
    })),
  );
  const lp275DrawerCard = lp275DrawerCards.find((card) => /Lei Promulgada nº 275\/2009/i.test(card.ariaLabel));
  assert.ok(lp275DrawerCard, `the consulted-sources drawer must expose an accessible target-law label: ${JSON.stringify(lp275DrawerCards)}`);
  const lp275PdfLink = new URL(lp275DrawerCard.href);
  assert.equal(lp275PdfLink.pathname, '/normas/documentos/c452bfe5-1138-4962-a3f2-c4cc9b662007/pdf/');
  assert.equal(lp275PdfLink.hash, '#page=6');
  assert.equal(lp275DrawerCard.target, '_blank');
  const localPdfResponse = await page.evaluate(async (href) => {
    const response = await fetch(href);
    const bytes = new Uint8Array(await response.arrayBuffer());
    return {
      status: response.status,
      contentType: response.headers.get('content-type') || '',
      signature: new TextDecoder().decode(bytes.slice(0, 4)),
    };
  }, lp275PdfLink.href);
  assert.equal(localPdfResponse.status, 200);
  assert.match(localPdfResponse.contentType, /application\/pdf/i);
  assert.equal(localPdfResponse.signature, '%PDF');
  const lp275Screenshot = path.join(resolvedEvidenceDir, 'pgm-lp275-revocation-and-source-drawer.png');
  await page.screenshot({ path: lp275Screenshot, fullPage: false });
  report.evidence.push(lp275Screenshot);
  report.checks.push({
    id: 'real-lp275-article21-repeal-source-and-pdf-open',
    status: 'passed',
    sources: [
      { norma: lp275ArticleSource.norma, dispositivo: lp275ArticleSource.dispositivo, page: lp275ArticleSource.page },
      { norma: lc258RepealSource.norma, dispositivo: lc258RepealSource.dispositivo },
    ],
    answerStatesBothExtractionsArePending: /pendentes de revis[aã]o/i.test(lp275Answer),
    sourceDrawerOpensLocalPdf: true,
    localPdfResponse,
    screenshot: lp275Screenshot,
    caveat: 'public authentic PDF texts are retrieved; both extractions remain pending and no vigency conclusion is made',
  });
  await page.keyboard.press('Escape');
  await page.waitForFunction(() =>
    document.getElementById('jurix-sources-drawer-panel')?.getAttribute('aria-hidden') === 'true');

  if (includeProposalRagSmoke) {
  await page.goto(new URL('/assistente/?new=1&corpus=archive-qa', baseUrl).href, {
    waitUntil: 'domcontentloaded',
    timeout: 20000,
  });
  const proposalQuestion = 'Qual é a redação proposta no Art. 59 do PLC 12/2025? Se o texto integral do anexo oficial não estiver disponível, informe essa lacuna; não trate a proposta como lei vigente.';
  const proposalAnswer = await submitQuestion(proposalQuestion);
  await page.waitForFunction(() => [...document.querySelectorAll('#chat-sessions-list .chat-session-main')]
    .some((link) => /Art\.\s*59º\s*[—-]\s*PLC\s*nº\s*12\/2025/i.test(link.innerText.trim())));
  const proposalConversationTitles = await page.$$eval(
    '#chat-sessions-list .chat-session-main',
    (links) => links.map((link) => link.innerText.trim()),
  );
  assert.ok(
    proposalConversationTitles.some((title) => /Art\.\s*59º\s*[—-]\s*PLC\s*nº\s*12\/2025/i.test(title)),
    `the recent conversation title must distinguish the bill from a promulgated law; got: ${proposalConversationTitles.join(' | ')}`,
  );
  const proposalSources = await page.$$eval('.message-assistant [id^="sources-"]', (containers) => {
    const node = containers.at(-1);
    return (node?._sourcesData || []).map((item) => ({
      citationId: item.citation_id || '',
      sourceKind: item.source_kind || '',
      norma: item.norma_ref || '',
      dispositivo: item.dispositivo_ref || '',
      contribution: item.contribution || '',
      hasPdfUrl: Boolean(item.pdf_url || item.local_pdf_url),
      page: item.page || null,
    }));
  });
  const matterSource = proposalSources.find((item) => item.sourceKind === 'sapl_legislative_matter');
  const originalProposalSource = proposalSources.find((item) => item.sourceKind === 'sapl_matter_original_pdf');
  assert.ok(matterSource, 'explicit PLC lookup must preserve the official matter as a structured source');
  assert.match(proposalAnswer, /n[aã]o demonstram, por si, aprova[cç][aã]o, promulga[cç][aã]o, vig[eê]ncia/i);
  if (originalProposalSource) {
    assert.ok(originalProposalSource.hasPdfUrl, 'the original proposal source must link to its official PDF');
    assert.match(originalProposalSource.dispositivo, /Texto Original/i);
    assert.match(proposalAnswer, /documento Texto Original anexado à proposição apresenta a redação proposta/i);
    assert.match(proposalAnswer, /proposta legislativa, n[aã]o uma norma promulgada/i);
  } else {
    assert.match(proposalAnswer, /n[aã]o [eé] poss[ií]vel confirmar a reda[cç][aã]o proposta/i,
      'when SAPL metadata is available but its original PDF is not, the answer must state the missing-text limitation');
  }
  let proposalDrawerScreenshot = null;
  if (originalProposalSource) {
    const proposalPill = (await page.$$('.message-assistant .jurix-sources-pill-btn')).at(-1);
    assert.ok(proposalPill, 'the proposal answer must expose its sources control');
    await proposalPill.click();
    await page.waitForFunction(() => {
      const drawer = document.getElementById('jurix-sources-drawer-panel');
      return drawer?.getAttribute('aria-hidden') === 'false'
        && drawer.querySelectorAll('.jurix-rag-source').length >= 2;
    });
    await page.waitForFunction(() => {
      const panel = document.getElementById('jurix-sources-drawer-panel');
      if (!panel?.classList.contains('is-open')) return false;
      const rect = panel.getBoundingClientRect();
      return rect.left >= 0 && rect.right <= window.innerWidth;
    });
    assert.ok(
      await page.$('#jurix-sources-drawer-panel .jurix-source-group-toggle-all'),
      'the source drawer must expose its expand-all evidence control',
    );
    await page.click('#jurix-sources-drawer-panel .jurix-source-group-toggle-all');
    await page.waitForFunction(() => {
      const groups = [...document.querySelectorAll('#jurix-sources-drawer-panel details.jurix-source-group')];
      return groups.length > 0 && groups.every((group) => group.open);
    });
    const proposalDrawerCards = await page.$$eval(
      '#jurix-sources-drawer-panel .jurix-rag-source',
      (cards) => cards.map((card) => ({
        text: card.innerText,
        openHref: card.querySelector('.jurix-rag-source__open')?.href || '',
        target: card.querySelector('.jurix-rag-source__open')?.target || '',
      })),
    );
    const originalPdfCard = proposalDrawerCards.find((card) => /Texto Original/i.test(card.text));
    assert.ok(originalPdfCard, 'the source drawer must show the original proposal PDF separately from the matter record');
    assert.equal(new URL(originalPdfCard.openHref).hostname, 'sapl.natal.rn.leg.br');
    assert.equal(originalPdfCard.target, '_blank');
    proposalDrawerScreenshot = path.join(resolvedEvidenceDir, 'pgm-official-proposal-source-drawer.png');
    await page.screenshot({ path: proposalDrawerScreenshot, fullPage: false });
    report.evidence.push(proposalDrawerScreenshot);
    await page.keyboard.press('Escape');
    await page.waitForFunction(() => document.getElementById('jurix-sources-drawer-panel')?.getAttribute('aria-hidden') === 'true');
  }
  report.checks.push({
    id: 'official-pending-proposal-text-or-explicit-gap',
    status: 'passed',
    sourceCount: proposalSources.length,
    matterFound: Boolean(matterSource),
    originalProposalPdfFound: Boolean(originalProposalSource),
    originalProposalPage: originalProposalSource?.page || null,
    answerStatesProposalIsNotCurrentLaw: /proposta legislativa, n[aã]o uma norma promulgada/i.test(proposalAnswer),
    sourceKinds: proposalSources.map((item) => item.sourceKind),
    originalPdfDrawerOpensOfficialSource: Boolean(proposalDrawerScreenshot),
    caveat: 'SAPL matter/PDF are public source material; proposal is not promulgated law or a validity finding',
  });
  report.checks.push({
    id: 'recent-conversation-title-distinguishes-pending-bill',
    status: 'passed',
    title: proposalConversationTitles.find((title) => /PLC\s*nº\s*12\/2025/i.test(title)),
  });

  await page.goto(new URL('/assistente/?new=1&corpus=archive-qa', baseUrl).href, {
    waitUntil: 'domcontentloaded',
    timeout: 20000,
  });
  const relatedMatterQuestion = 'Houve proposta legislativa no SAPL para alterar o Art. 59 da Lei Complementar nº 258/2024? Localize registros oficiais que citem expressamente esse dispositivo e diga se as evidências confirmam que a alteração foi promulgada ou está vigente.';
  const relatedMatterAnswer = await submitQuestion(relatedMatterQuestion);
  const relatedMatterSources = await page.$$eval('.message-assistant [id^="sources-"]', (containers) => {
    const node = containers.at(-1);
    return (node?._sourcesData || []).map((item) => ({
      citationId: item.citation_id || '',
      sourceKind: item.source_kind || '',
      label: item.citation_label || '',
      relation: item.relation_label || '',
      sourceUrl: item.source_url || item.sapl_url || '',
    }));
  });
  const relatedOfficialMatter = relatedMatterSources.find(
    (item) => item.sourceKind === 'sapl_legislative_matter' && item.citationId === 'sapl:materia:48759',
  );
  assert.ok(
    relatedOfficialMatter,
    `an article-currentness question must surface the exact SAPL proposal found by ementa; got: ${JSON.stringify(relatedMatterSources)}`,
  );
  assert.match(relatedMatterAnswer, /o cadastro de uma proposição não comprova, por si, que o texto foi aprovado, promulgado ou entrou em vigor/i);
  assert.match(relatedMatterAnswer, /Transcrição automática; metadados e segmentação ainda estão sob revisão/i);
  assert.match(relatedMatterAnswer, /Art\. 59 da Lei Complementar nº 258\/2024/i);
  const inlineProposalReference = await page.$$eval(
    '.message-assistant .message-body',
    (bodies) => {
      const body = bodies.at(-1);
      const phrase = 'Projeto de Lei Complementar nº 12/2025';
      const mentioned = body?.innerText.includes(phrase) || false;
      const link = [...(body?.querySelectorAll('a.jurix-legal-reference-link') || [])]
        .find((anchor) => anchor.textContent.trim() === phrase);
      return {
        mentioned,
        linked: Boolean(link),
        text: link?.textContent.trim() || '',
        href: link?.href || '',
        ariaLabel: link?.getAttribute('aria-label') || '',
      };
    },
  );
  if (inlineProposalReference.mentioned) {
    assert.equal(inlineProposalReference.linked, true,
      'a proposal named in a completed answer must link to its official SAPL matter without F5');
    assert.equal(new URL(inlineProposalReference.href).pathname, '/materia/48759');
    assert.match(inlineProposalReference.ariaLabel, /Projeto de Lei Complementar nº 12\/2025/);
  }
  report.checks.push({
    id: 'inline-proposal-reference-links-before-refresh',
    status: 'passed',
    applicable: inlineProposalReference.mentioned,
    linked: inlineProposalReference.linked,
    href: inlineProposalReference.href,
    ariaLabel: inlineProposalReference.ariaLabel,
  });
  assert.equal(new URL(relatedOfficialMatter.sourceUrl).hostname, 'sapl.natal.rn.leg.br');
  const relatedMatterPill = (await page.$$('.message-assistant .jurix-sources-pill-btn')).at(-1);
  assert.ok(relatedMatterPill, 'the related official proposal must be accessible from the source drawer');
  await relatedMatterPill.click();
  await page.waitForFunction(() => {
    return document.getElementById('jurix-sources-drawer-panel')?.getAttribute('aria-hidden') === 'false';
  });
  await page.waitForFunction(() => {
    const panel = document.getElementById('jurix-sources-drawer-panel');
    if (!panel || panel.getAttribute('aria-hidden') !== 'false') return false;
    const transform = new DOMMatrixReadOnly(getComputedStyle(panel).transform);
    const rect = panel.getBoundingClientRect();
    return Math.abs(transform.m41) < 0.5
      && rect.left >= 0
      && rect.right <= document.documentElement.clientWidth;
  }, { timeout: 5000 });
  const expandRelatedEvidence = await page.$('#jurix-sources-drawer-panel .jurix-source-group-toggle-all');
  assert.ok(expandRelatedEvidence, 'the source drawer must expose its expand-all control');
  await expandRelatedEvidence.click();
  await page.waitForFunction(() =>
    document.querySelector('#jurix-sources-drawer-panel .jurix-source-group-toggle-all')
      ?.getAttribute('aria-expanded') === 'true');
  const relatedMatterCard = await page.$$eval(
    '#jurix-sources-drawer-panel .jurix-rag-source',
    (cards) => {
      const card = cards.find((item) => /Altera o art\. 59 da Lei Complementar nº 258/i.test(item.innerText));
      return card ? {
        text: card.innerText,
        href: card.querySelector('.jurix-rag-source__open')?.href || '',
        openLabel: card.querySelector('.jurix-rag-source__open')?.innerText || '',
        target: card.querySelector('.jurix-rag-source__open')?.target || '',
      } : null;
    },
  );
  assert.ok(relatedMatterCard, 'the source drawer must show the exact related SAPL matter');
  assert.match(relatedMatterCard.text, /Registro de matéria legislativa/i);
  assert.match(relatedMatterCard.openLabel, /Abrir matéria no SAPL/i);
  assert.equal(new URL(relatedMatterCard.href).hostname, 'sapl.natal.rn.leg.br');
  assert.equal(relatedMatterCard.target, '_blank');
  const relatedMatterScreenshot = path.join(resolvedEvidenceDir, 'pgm-related-proposal-for-currentness.png');
  await page.screenshot({ path: relatedMatterScreenshot, fullPage: false });
  report.evidence.push(relatedMatterScreenshot);
  report.checks.push({
    id: 'article-currentness-query-discovers-explicit-sapl-proposal',
    status: 'passed',
    matter: relatedOfficialMatter.label,
    relation: relatedOfficialMatter.relation,
    sourceCount: relatedMatterSources.length,
    answerSeparatesProposalFromPromulgatedLaw: /o cadastro de uma proposição não comprova, por si, que o texto foi aprovado, promulgado ou entrou em vigor/i.test(relatedMatterAnswer),
    drawerOpensOfficialSapLRecord: true,
    caveat: 'official SAPL proposal record is related evidence, not proof of amendment, promulgation, or current validity',
    screenshot: relatedMatterScreenshot,
  });
  await page.keyboard.press('Escape');
  await page.waitForFunction(() => document.getElementById('jurix-sources-drawer-panel')?.getAttribute('aria-hidden') === 'true');
  } else {
    report.checks.push({
      id: 'proposal-rag-smoke',
      status: 'deferred',
      note: 'projeto de lei fora do RAG promulgado nesta etapa; habilite JURIX_INCLUDE_PROPOSAL_RAG_SMOKE=1 somente para o teste isolado dessa funcionalidade',
    });
  }

  await page.goto(new URL('/assistente/?new=1&corpus=archive-qa', baseUrl).href, {
    waitUntil: 'domcontentloaded',
    timeout: 20000,
  });
  const ctmComparisonQuestion = 'Compare o texto do Art. 20 da Lei nº 3.882/1989 na consolidação municipal de 2024 com a redação substitutiva transcrita no Art. 1º da LC nº 271/2025. Mostre apenas as fontes e diferenças textuais, sem concluir vigência atual.';
  const ctmComparisonAnswer = await submitQuestion(ctmComparisonQuestion);
  assert.match(ctmComparisonAnswer, /difere textualmente/i);
  assert.match(ctmComparisonAnswer, /termina com reticências/i);
  assert.match(ctmComparisonAnswer, /não confirma vigência/i);
  const ctmComparisonSources = await page.$$eval('.message-assistant [id^="sources-"]', (containers) => {
    const node = containers.at(-1);
    return (node?._sourcesData || []).map((item) => ({
      citationId: item.citation_id || '',
      norm: item.norma_ref || '',
      device: item.dispositivo_ref || '',
      edition: item.edition_label || '',
    }));
  });
  assert.equal(ctmComparisonSources.length, 2,
    `explicit article comparison should expose only the requested old edition and amendment; got ${JSON.stringify(ctmComparisonSources)}`);
  assert.ok(ctmComparisonSources.some((source) => /3\.882\/1989/.test(source.norm)
    && /Art\.? 20\b/i.test(source.device) && /exercício 2024/i.test(source.edition)));
  assert.ok(ctmComparisonSources.some((source) => /271\/2025/.test(source.norm)
    && /Art\.? 1º?/i.test(source.device)));
  assert.ok(!ctmComparisonSources.some((source) => /219\/2023/.test(source.norm)));
  const ctmSourcesPill = (await page.$$('.message-assistant .jurix-sources-pill-btn')).at(-1);
  assert.ok(ctmSourcesPill, 'the comparison evidence drawer must appear without a reload');
  await ctmSourcesPill.click();
  await page.waitForFunction(() =>
    document.getElementById('jurix-sources-drawer-panel')?.getAttribute('aria-hidden') === 'false');
  await page.waitForFunction(() => {
    const panel = document.getElementById('jurix-sources-drawer-panel');
    if (!panel || panel.getAttribute('aria-hidden') !== 'false') return false;
    const transform = new DOMMatrixReadOnly(getComputedStyle(panel).transform);
    const rect = panel.getBoundingClientRect();
    return Math.abs(transform.m41) < 0.5
      && rect.left >= 0
      && rect.right <= document.documentElement.clientWidth;
  }, { timeout: 5000 });
  const ctmExpandAll = await page.$('#jurix-sources-drawer-panel .jurix-source-group-toggle-all');
  assert.ok(ctmExpandAll, 'the comparison sources drawer must expose expand-all');
  await ctmExpandAll.click();
  await page.waitForFunction(() =>
    document.querySelector('#jurix-sources-drawer-panel .jurix-source-group-toggle-all')
      ?.getAttribute('aria-expanded') === 'true');
  const ctmDrawerCards = await page.$$eval(
    '#jurix-sources-drawer-panel .jurix-rag-source',
    (cards) => cards.map((card) => card.innerText),
  );
  const ctmDrawerText = await page.$eval(
    '#jurix-sources-drawer-panel',
    (panel) => panel.innerText,
  );
  assert.equal(ctmDrawerCards.length, 2);
  assert.match(ctmDrawerText, /3\.882\/1989/);
  assert.match(ctmDrawerText, /exerc[ií]cio 2024/i);
  assert.match(ctmDrawerText, /271\/2025/);
  assert.ok(ctmDrawerCards.every((text) => /pendente de revis[aã]o/i.test(text)));
  const ctmComparisonScreenshot = path.join(resolvedEvidenceDir, 'pgm-ctm-article20-comparison.png');
  await page.screenshot({ path: ctmComparisonScreenshot, fullPage: false });
  report.evidence.push(ctmComparisonScreenshot);
  report.checks.push({
    id: 'real-ctm-article20-amendment-comparison-scoped-sources',
    status: 'passed',
    sourceCount: ctmComparisonSources.length,
    sources: ctmComparisonSources,
    answerWarnsAboutOmittedContinuation: /termina com reticências/i.test(ctmComparisonAnswer),
    answerAvoidsCurrentnessClaim: /não confirma vigência/i.test(ctmComparisonAnswer),
    drawerMatchesAnswerEvidence: true,
    screenshot: ctmComparisonScreenshot,
    caveat: 'authentic municipal PDF extractions remain pending human review; text comparison does not establish legal effect or current validity',
  });
  await page.keyboard.press('Escape');
  await page.waitForFunction(() =>
    document.getElementById('jurix-sources-drawer-panel')?.getAttribute('aria-hidden') === 'true');

  const reviewResponse = await page.goto(new URL('/conferir/', baseUrl).href, {
    waitUntil: 'domcontentloaded',
    timeout: 20000,
  });
  const reviewGate = {
    status: reviewResponse?.status() ?? null,
    finalPath: new URL(page.url()).pathname,
    heading: await page.$eval('.workspace-page-header h1', (node) => node.innerText.trim()),
    explainsAuthorization: /exige uma conta autorizada/i.test(
      await page.$eval('.workspace-page-header p', (node) => node.innerText),
    ),
  };
  assert.ok(reviewGate.finalPath.includes('/conta/entrar/'), 'review desk must not be accessible to an anonymous user');
  assert.equal(reviewGate.heading, 'Acesse Conferir fundamentação');
  assert.equal(reviewGate.explainsAuthorization, true, 'the login page must explain why this protected workflow requires sign-in');
  const loginContextScreenshot = path.join(resolvedEvidenceDir, 'pgm-foundation-check-login-context.png');
  await page.screenshot({ path: loginContextScreenshot, fullPage: true });
  report.evidence.push(loginContextScreenshot);
  report.checks.push({
    id: 'anonymous-reviewer-access-gate',
    ...reviewGate,
    screenshot: loginContextScreenshot,
    status: 'passed',
  });

  assert.deepEqual(pageErrors, [], `uncaught browser errors: ${pageErrors.join(', ')}`);
  report.status = 'passed';
  report.pageErrors = pageErrors;
  report.completedAt = new Date().toISOString();
  const reportPath = path.join(resolvedEvidenceDir, 'pgm-workflow-smoke.json');
  await fs.writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`, 'utf8');
  console.log(JSON.stringify({ status: report.status, checks: report.checks, evidence: report.evidence, report: reportPath }, null, 2));
} finally {
  await browser.close();
}
