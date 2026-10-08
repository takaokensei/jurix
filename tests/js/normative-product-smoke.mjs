import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import puppeteer from 'puppeteer-core';

const baseUrl = process.env.JURIX_BASE_URL || '';
const mapPath = process.env.JURIX_FIXTURE_MAP || '';
const evidenceDir = process.env.JURIX_EVIDENCE_DIR || '';
const localBase = new URL(baseUrl);
assert.equal(localBase.protocol, 'http:');
assert.ok(['127.0.0.1', 'localhost'].includes(localBase.hostname));
assert.ok(
  ['8007', '8011', '8013', '8014', '8015', '8019', '8020', '8021', '8022', '8023', '8024'].includes(localBase.port),
  'smoke is restricted to isolated QA servers on ports 8007, 8011, 8013, 8014, 8015, 8019, 8020, 8021, 8022, 8023, and 8024',
);
assert.ok(mapPath, 'JURIX_FIXTURE_MAP is required');
assert.ok(evidenceDir, 'JURIX_EVIDENCE_DIR is required');

const resolvedMap = await fs.realpath(mapPath);
const resolvedTemp = await fs.realpath(os.tmpdir());
assert.ok(
  resolvedMap.toLowerCase().startsWith(resolvedTemp.toLowerCase() + path.sep),
  'fixture map must remain under the operating-system temporary directory',
);
const fixtureMap = JSON.parse(await fs.readFile(resolvedMap, 'utf8'));
assert.equal(fixtureMap.dataset, 'synthetic_not_gold');
assert.equal(fixtureMap.temporal_scenarios?.synthetic_only, true);
const detailNormaId = Number(fixtureMap.temporal_scenarios?.lc55_2004?.norma_id);
assert.ok(Number.isInteger(detailNormaId) && detailNormaId > 0);

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
    // Continue only through known local browser locations.
  }
}
assert.ok(executablePath, 'an already-installed Chrome or Edge executable is required');

const evidenceRoot = path.resolve(evidenceDir);
await fs.mkdir(evidenceRoot);
const browserInstance = await puppeteer.launch({
  executablePath,
  headless: true,
  args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'],
});
const report = { baseUrl, dataset: fixtureMap.dataset, checks: [], failures: [], evidence: [] };

async function open(page, route, viewport) {
  await page.setViewport(viewport);
  const errors = [];
  page.removeAllListeners('pageerror');
  page.on('pageerror', (error) => errors.push(error.message));
  const response = await page.goto(new URL(route, baseUrl).href, {
    waitUntil: 'domcontentloaded',
    timeout: 20000,
  });
  const metrics = await page.evaluate(() => ({
    viewportWidth: document.documentElement.clientWidth,
    documentWidth: document.documentElement.scrollWidth,
    mainVisible: Boolean(document.querySelector('main')?.getClientRects().length),
  }));
  const result = { route, ...viewport, status: response?.status() ?? null, ...metrics, errors };
  report.checks.push(result);
  if (result.status !== 200 || !result.mainVisible || result.documentWidth > result.viewportWidth || errors.length) {
    report.failures.push(result);
  }
  return result;
}

try {
  const page = await browserInstance.newPage();
  await page.evaluateOnNewDocument(() => {
    localStorage.setItem('jurix-theme', 'dark');
    localStorage.setItem('jurix-preferences', JSON.stringify({ theme: 'dark', density: 'comfortable' }));
  });
  for (const width of [320, 360, 768, 1280, 1920]) {
    for (const route of ['/assistente/', '/pesquisa/', '/normas/', '/colecoes/', '/historico/', '/configuracoes/']) {
      await open(page, route, { width, height: 900 });
    }
  }

  await page.setViewport({ width: 1280, height: 900 });
  await page.goto(new URL('/assistente/', baseUrl).href, { waitUntil: 'networkidle0', timeout: 20000 });
  await page.waitForFunction(() => Boolean(
    document.querySelector('.figma-welcome-state:not(.is-hidden)')
    && typeof window.scrollToBottomIfAtBottom === 'function',
  ));
  const emptyAssistantLayout = await page.evaluate(() => {
    const scroller = document.getElementById('messages-container');
    const hero = document.querySelector('.figma-hero-title');
    const banner = document.querySelector('.jurix-anonymous-banner');
    const heroRect = hero?.getBoundingClientRect();
    const bannerRect = banner?.getBoundingClientRect();
    return {
      scrollTop: scroller?.scrollTop ?? null,
      heroTop: heroRect ? Math.round(heroRect.top) : null,
      bannerBottom: bannerRect ? Math.round(bannerRect.bottom) : null,
      welcomeVisible: Boolean(document.querySelector('.figma-welcome-state:not(.is-hidden)')),
    };
  });
  const emptyAssistantCheck = {
    route: '/assistente/',
    interaction: 'empty-assistant-starts-at-top-with-hero-below-banner',
    width: 1280,
    height: 900,
    ...emptyAssistantLayout,
  };
  report.checks.push(emptyAssistantCheck);
  if (
    !emptyAssistantLayout.welcomeVisible
    || emptyAssistantLayout.scrollTop !== 0
    || emptyAssistantLayout.heroTop === null
    || emptyAssistantLayout.bannerBottom === null
    || emptyAssistantLayout.heroTop < emptyAssistantLayout.bannerBottom
  ) report.failures.push(emptyAssistantCheck);
  const emptyAssistantScreenshot = path.join(evidenceRoot, 'empty-assistant-home-viewport.png');
  await page.screenshot({ path: emptyAssistantScreenshot, fullPage: false });
  report.evidence.push(emptyAssistantScreenshot);

  const ordinaryLawId = Number(fixtureMap.scenarios?.lei?.norma_id);
  const complementaryLawId = Number(fixtureMap.scenarios?.['lei-complementar']?.norma_id);
  assert.ok(Number.isInteger(ordinaryLawId) && Number.isInteger(complementaryLawId));
  assert.notEqual(ordinaryLawId, complementaryLawId, 'homonymous law types must retain separate records');
  const ordinaryRoute = `/normas/${ordinaryLawId}/`;
  await open(page, ordinaryRoute, { width: 1280, height: 900 });
  const ordinaryHeading = await page.$eval('main h1', (heading) => heading.innerText);
  assert.match(ordinaryHeading, /Lei nº 9901\/2090/);
  assert.doesNotMatch(ordinaryHeading, /Lei Complementar/);
  report.checks.push({ route: ordinaryRoute, interaction: 'R02-ordinary-law-identity', heading: ordinaryHeading });
  const complementaryRoute = `/normas/${complementaryLawId}/`;
  await open(page, complementaryRoute, { width: 1280, height: 900 });
  const complementaryHeading = await page.$eval('main h1', (heading) => heading.innerText);
  assert.match(complementaryHeading, /Lei Complementar nº 9901\/2090/);
  report.checks.push({ route: complementaryRoute, interaction: 'R02-complementary-law-identity', heading: complementaryHeading });

  const relationNormaId = Number(fixtureMap.temporal_scenarios?.norma_a?.norma_id);
  assert.ok(Number.isInteger(relationNormaId) && relationNormaId > 0);
  const relationRoute = `/normas/${relationNormaId}/`;
  await open(page, relationRoute, { width: 1280, height: 900 });
  const temporalText = await page.$eval('main', (main) => main.innerText);
  assert.match(temporalText, /Publicação da fonte:\s*10\/01\/2021/);
  assert.match(temporalText, /Efeito jurídico revisado: 01\/03\/2021/);
  const desktopTimelineOpen = await page.$eval('[data-responsive-timeline]', (timeline) => timeline.open);
  assert.equal(desktopTimelineOpen, true, 'desktop keeps the normative timeline expanded');
  const temporalScreenshot = path.join(evidenceRoot, 'norma-timeline-publicacao-efeito-desktop.png');
  await page.screenshot({ path: temporalScreenshot, fullPage: true });
  report.evidence.push(temporalScreenshot);
  report.checks.push({ route: relationRoute, interaction: 'R08-publication-and-effect-separate', publication: '2021-01-10', effectiveDate: '2021-03-01' });

  await page.setViewport({ width: 320, height: 900 });
  await page.goto(new URL(relationRoute, baseUrl).href, { waitUntil: 'domcontentloaded' });
  const compactTimeline = await page.$eval('[data-responsive-timeline]', (timeline) => ({
    open: timeline.open,
    summaryVisible: Boolean(timeline.querySelector('summary')?.getClientRects().length),
    summaryText: timeline.querySelector('summary')?.innerText,
    itemCount: timeline.querySelectorAll('.norma-timeline-item').length,
    cardHeight: Math.round(timeline.getBoundingClientRect().height),
  }));
  assert.equal(compactTimeline.open, false, 'long chronology starts collapsed on a phone');
  assert.equal(compactTimeline.summaryVisible, true, 'collapsed chronology keeps its summary visible');
  assert.match(compactTimeline.summaryText, /Linha do tempo normativa[\s\S]*\d+ registros cronológicos/);
  const compactRelations = await page.$eval('.relation-extraction-disclosure', (disclosure) => ({
    open: disclosure.open,
    summaryVisible: Boolean(disclosure.querySelector('summary')?.getClientRects().length),
    summaryText: disclosure.querySelector('summary')?.innerText,
    cardHeight: Math.round(disclosure.getBoundingClientRect().height),
    recordCount: disclosure.querySelectorAll('.relation-extraction-card').length,
  }));
  assert.equal(compactRelations.open, false, 'secondary extracted records start collapsed on a phone');
  assert.equal(compactRelations.summaryVisible, true);
  assert.match(compactRelations.summaryText, /Registros de relações extraídos \(\d+\)/);
  const compactTimelineScreenshot = path.join(evidenceRoot, 'norma-timeline-recolhida-mobile-320.png');
  await page.screenshot({ path: compactTimelineScreenshot, fullPage: true });
  report.evidence.push(compactTimelineScreenshot);
  await page.focus('.timeline-disclosure-summary');
  await page.keyboard.press('Enter');
  const mobileTimelineExpanded = await page.$eval('[data-responsive-timeline]', (timeline) => timeline.open && timeline.querySelectorAll('.norma-timeline-item').length > 0);
  assert.equal(mobileTimelineExpanded, true, 'keyboard/mouse disclosure reveals every timeline entry');
  await page.focus('.relation-extraction-summary');
  await page.keyboard.press('Space');
  const mobileRelationRecordsExpanded = await page.$eval('.relation-extraction-disclosure', (disclosure) => disclosure.open && disclosure.querySelectorAll('.relation-extraction-card').length > 0);
  assert.equal(mobileRelationRecordsExpanded, true, 'disclosure reveals all extracted relationship records');
  report.checks.push({ route: relationRoute, interaction: 'R24-mobile-secondary-disclosures', timelineInitiallyCollapsed: true, timelineExpandedByKeyboard: mobileTimelineExpanded, timelineCollapsedHeight: compactTimeline.cardHeight, timelineEntries: compactTimeline.itemCount, relationRecordsInitiallyCollapsed: true, relationRecordsExpandedByKeyboard: mobileRelationRecordsExpanded, relationRecordsCollapsedHeight: compactRelations.cardHeight, relationRecordCount: compactRelations.recordCount });
  await page.setViewport({ width: 1280, height: 900 });

  const historyLink = await page.$('a[href*="/compare/"]');
  assert.ok(historyLink, 'the device detail must provide a historical comparison action');
  const historyUrl = await historyLink.evaluate((link) => link.href);
  await page.goto(historyUrl, { waitUntil: 'domcontentloaded' });
  const historicalModeLink = await page.$('a[href*="history=1"]');
  assert.ok(historicalModeLink, 'the comparison page must provide a historical-date comparison action');
  const historicalModeUrl = await historicalModeLink.evaluate((link) => link.href);
  await page.goto(historicalModeUrl, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('#from-as-of');
  const dateFrom = fixtureMap.temporal_scenarios.date_boundaries.d_minus_1;
  const dateTo = fixtureMap.temporal_scenarios.date_boundaries.d;
  await page.$eval('#from-as-of', (input, value) => { input.value = value; }, dateFrom);
  await page.$eval('#to-as-of', (input, value) => { input.value = value; }, dateTo);
  await Promise.all([
    page.waitForNavigation({ waitUntil: 'domcontentloaded' }),
    page.click('.historical-date-form button[type="submit"]'),
  ]);
  const compareUrl = new URL(page.url());
  assert.equal(compareUrl.searchParams.get('from_as_of'), dateFrom);
  assert.equal(compareUrl.searchParams.get('to_as_of'), dateTo);
  let historicalDiff = await page.$eval('main', (main) => main.innerText);
  assert.match(historicalDiff, /O prazo é de dez dias\./);
  assert.match(historicalDiff, /O prazo é de vinte dias\./);
  const diffScreenshot = path.join(evidenceRoot, 'norma-comparacao-D-1-D-desktop.png');
  await page.screenshot({ path: diffScreenshot, fullPage: true });
  report.evidence.push(diffScreenshot);
  await page.reload({ waitUntil: 'domcontentloaded' });
  historicalDiff = await page.$eval('main', (main) => main.innerText);
  assert.match(historicalDiff, /O prazo é de dez dias\./);
  assert.match(historicalDiff, /O prazo é de vinte dias\./);
  await page.goBack({ waitUntil: 'domcontentloaded' });
  assert.match(page.url(), /\/normas\/3\//);
  await page.goForward({ waitUntil: 'domcontentloaded' });
  assert.equal(new URL(page.url()).searchParams.get('to_as_of'), dateTo);
  report.checks.push({ route: page.url(), interaction: 'R07-R09-historical-diff-reload-back-forward', dateFrom, dateTo, beforeTextVisible: true, afterTextVisible: true });

  const missingOriginalNormaId = Number(fixtureMap.edge_case_fixtures?.missing_original?.norma_id);
  assert.ok(Number.isInteger(missingOriginalNormaId) && missingOriginalNormaId > 0);
  const missingOriginalUrl = new URL(`/normas/${missingOriginalNormaId}/compare/?history=1&from_as_of=2020-01-01&to_as_of=2021-01-01`, baseUrl);
  await page.goto(missingOriginalUrl.href, { waitUntil: 'domcontentloaded' });
  const missingOriginalText = await page.$eval('main', (main) => main.innerText);
  assert.match(missingOriginalText, /Não foi possível reconstruir com segurança/);
  assert.match(missingOriginalText, /não será usado como substituto/);
  assert.doesNotMatch(missingOriginalText, /Estado inicial: completa/);
  const insufficientHistoryScreenshot = path.join(evidenceRoot, 'historico-sem-original-abstencao-desktop.png');
  await page.screenshot({ path: insufficientHistoryScreenshot, fullPage: true });
  report.evidence.push(insufficientHistoryScreenshot);
  report.checks.push({ route: missingOriginalUrl.pathname, interaction: 'R10-missing-original-safe-abstention', noticeVisible: true, currentTextNotPresentedAsHistorical: true });

  const partialProjection = fixtureMap.temporal_scenarios?.partial_projection;
  const partialNormaId = Number(partialProjection?.norma_id);
  assert.ok(Number.isInteger(partialNormaId) && partialNormaId > 0, 'fixture map must identify the synthetic norm with a pending event');
  assert.equal(partialProjection?.expected_projection, 'partial');
  const partialProjectionUrl = new URL(
    `/normas/${partialNormaId}/compare/?history=1&from_as_of=2004-01-01&to_as_of=${encodeURIComponent(partialProjection.as_of)}`,
    baseUrl,
  );
  await page.goto(partialProjectionUrl.href, { waitUntil: 'domcontentloaded' });
  const partialProjectionText = await page.$eval('main', (main) => main.innerText);
  assert.match(partialProjectionText, /Estado inicial:\s*parcial/i);
  assert.match(partialProjectionText, /final:\s*parcial/i);
  assert.match(partialProjectionText, /Cobertura parcial/);
  assert.match(partialProjectionText, /evento\(s\) não aplicados/);
  assert.match(partialProjectionText, /Pendência de revisão|evento\(s\) não aplicados/i);
  assert.doesNotMatch(partialProjectionText, /Situação:\s*revogado na projeção/i);
  const partialProjectionScreenshot = path.join(evidenceRoot, 'historico-evento-pendente-cobertura-parcial-desktop.png');
  await page.screenshot({ path: partialProjectionScreenshot, fullPage: true });
  report.evidence.push(partialProjectionScreenshot);
  report.checks.push({
    route: partialProjectionUrl.pathname,
    interaction: 'R10-pending-event-explicit-partial-projection',
    initialStatePartial: true,
    finalStatePartial: true,
    pendingEventExplained: true,
    pendingRevocationNotApplied: true,
  });

  const sameDateConflict = fixtureMap.temporal_scenarios?.same_date_conflict;
  assert.ok(Number.isInteger(Number(sameDateConflict?.norma_id)) && sameDateConflict?.synthetic_only === true);
  assert.equal(sameDateConflict.expected_projection, 'partial');
  const sameDateConflictUrl = new URL(
    `/normas/${sameDateConflict.norma_id}/compare/?history=1&from_as_of=${encodeURIComponent(sameDateConflict.from_as_of)}&to_as_of=${encodeURIComponent(sameDateConflict.as_of)}`,
    baseUrl,
  );
  await page.goto(sameDateConflictUrl.href, { waitUntil: 'domcontentloaded' });
  const sameDateConflictText = await page.$eval('main', (main) => main.innerText);
  assert.match(sameDateConflictText, /Estado inicial:\s*completa/i);
  assert.match(sameDateConflictText, /final:\s*parcial/i);
  assert.match(sameDateConflictText, /eventos aplicados:\s*0/i);
  assert.match(sameDateConflictText, /eventos pendentes ou conflitantes:\s*2/i);
  assert.match(sameDateConflictText, /2 evento\(s\) não aplicados/i);
  assert.match(sameDateConflictText, new RegExp(sameDateConflict.expected_text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  assert.doesNotMatch(sameDateConflictText, /Situação:\s*revogado na projeção/i);
  const sameDateConflictScreenshot = path.join(evidenceRoot, 'historico-conflito-confirmado-mesma-data-desktop.png');
  await page.screenshot({ path: sameDateConflictScreenshot, fullPage: true });
  report.evidence.push(sameDateConflictScreenshot);
  report.checks.push({
    route: sameDateConflictUrl.pathname,
    interaction: 'R10-same-date-confirmed-effects-fail-closed',
    initialStateComplete: true,
    finalStatePartial: true,
    appliedEventCount: 0,
    pendingConflictCount: 2,
    originalTextPreserved: true,
    falselyMarkedRevoked: false,
  });

  await page.goto(new URL(relationRoute, baseUrl).href, { waitUntil: 'domcontentloaded' });
  await page.click('[data-relations-toggle]');
  await page.waitForFunction(() => {
    const status = document.querySelector('[data-relations-status]');
    return status && status.getAttribute('aria-busy') !== 'true' && !status.innerText.includes('Abra esta seção');
  }, { timeout: 5000 });
  const relationGroups = await page.$$eval('.normative-relations__group-button', (buttons) => buttons.map((button) => button.innerText));
  assert.equal(relationGroups.length, 1);
  assert.match(relationGroups[0], /Lei nº 9002\/2021.*Lei nº 9001\/2020/s);
  assert.equal(await page.$$eval('[data-relations-svg] line', (lines) => lines.length), 1);
  await page.$eval('[data-relations-graph-wrap]', (graph) => graph.scrollIntoView({ block: 'center', behavior: 'instant' }));
  const reviewedGraphOverview = path.join(evidenceRoot, 'norma-grafo-relacao-visao-geral-desktop.png');
  await page.screenshot({ path: reviewedGraphOverview });
  report.evidence.push(reviewedGraphOverview);
  await page.click('.normative-relations__group-button');
  const relationPanelText = await page.$eval('[data-relations-panel-content]', (panel) => panel.innerText);
  assert.match(relationPanelText, /Altera/);
  assert.match(relationPanelText, /Dispositivo de origem: Artigo 1º/);
  assert.match(relationPanelText, /Dispositivo de destino: Art(?:igo|\.) 5º/);
  assert.match(relationPanelText, /Revisão do vínculo: confirmado/);
  assert.match(relationPanelText, /Efeito registrado em 2021-03-01/);
  assert.match(relationPanelText, /Art\. 5º da Lei 9001\/2020/);
  assert.match(relationPanelText, /Abrir evidência documental/);
  await page.$eval('[data-relations-panel]', (panel) => panel.scrollIntoView({ block: 'center', behavior: 'instant' }));
  const reviewedGraphScreenshot = path.join(evidenceRoot, 'norma-grafo-relacao-revisada-desktop.png');
  await page.screenshot({ path: reviewedGraphScreenshot });
  report.evidence.push(reviewedGraphScreenshot);
  report.checks.push({ route: relationRoute, interaction: 'R03-reviewed-relation-and-evidence', groupCount: relationGroups.length, svgEdgeCount: 1, relationPanelText });

  const multiRelationNormaId = Number(fixtureMap.temporal_scenarios?.lc198_2021?.norma_id);
  assert.ok(Number.isInteger(multiRelationNormaId) && multiRelationNormaId > 0);
  const multiRelationRoute = `/normas/${multiRelationNormaId}/`;
  await open(page, multiRelationRoute, { width: 1280, height: 900 });
  await page.click('[data-relations-toggle]');
  await page.waitForFunction(() => {
    const status = document.querySelector('[data-relations-status]');
    return status && status.getAttribute('aria-busy') !== 'true' && status.innerText.includes('grupo de relações');
  }, { timeout: 5000 });
  let multiRelationGroups = await page.$$eval('.normative-relations__group-button', (buttons) => buttons.map((button) => button.innerText));
  assert.equal(multiRelationGroups.length, 1, 'two article references between the same norms must share one visual group');
  assert.match(multiRelationGroups[0], /2 vínculos/);
  await page.click('.normative-relations__group-button');
  const multiRelationPanel = await page.$eval('[data-relations-panel-content]', (panel) => panel.innerText);
  assert.match(multiRelationPanel, /Artigo 21/);
  assert.match(multiRelationPanel, /Artigo 44/);
  await page.$eval('[data-relations-panel]', (panel) => panel.scrollIntoView({ block: 'center', behavior: 'instant' }));
  const multiRelationScreenshot = path.join(evidenceRoot, 'norma-duas-remissoes-grupo-desktop.png');
  await page.screenshot({ path: multiRelationScreenshot });
  report.evidence.push(multiRelationScreenshot);
  await page.click('[data-relations-close]');
  await page.click('[data-relations-toggle]');
  assert.equal(await page.$eval('[data-relations-disclosure]', (disclosure) => disclosure.open), false);
  await page.click('[data-relations-toggle]');
  await page.waitForFunction(() => {
    const status = document.querySelector('[data-relations-status]');
    return status && status.getAttribute('aria-busy') !== 'true' && status.innerText.includes('grupo de relações');
  }, { timeout: 5000 });
  multiRelationGroups = await page.$$eval('.normative-relations__group-button', (buttons) => buttons.map((button) => button.innerText));
  assert.equal(multiRelationGroups.length, 1, 'collapsing and reopening must not duplicate relation groups');
  assert.match(multiRelationGroups[0], /2 vínculos/);
  report.checks.push({ route: multiRelationRoute, interaction: 'R04-multiple-device-references-grouped', groupCount: multiRelationGroups.length, eventCount: 2, bothTargetArticlesVisible: true, noDuplicateAfterReopen: true });

  const detailPath = `/normas/${detailNormaId}/`;
  await open(page, detailPath, { width: 1280, height: 900 });
  const detailText = await page.$eval('body', (body) => body.innerText);
  assert.match(detailText, /Lei Complementar nº 55\/2004/);
  assert.match(detailText, /Pendente/);
  assert.match(detailText, /Norma municipal/i);
  assert.match(detailText, /Referência revisada · sem efeito de alteração/);
  const remittanceTimelineEntries = await page.$$eval('.norma-timeline-item', (items) => items
    .map((item) => item.innerText)
    .filter((text) => /menciona/i.test(text) && /Lei Complementar nº 55\/2004/.test(text)));
  assert.equal(
    remittanceTimelineEntries.filter((text) => /Art\. 21º/.test(text)).length,
    1,
    'the same fingerprinted Art. 21 reference must appear once in the target timeline',
  );
  assert.equal(
    remittanceTimelineEntries.filter((text) => /Art\. 44º/.test(text)).length,
    1,
    'the distinct Art. 44 reference must remain visible once in the target timeline',
  );
  const relationRecordSummary = await page.$$eval('.relation-extraction-card', (cards) => cards.map((card) => card.innerText));
  assert.equal(relationRecordSummary.length, 3, 'the evidence list must collapse duplicate rows while preserving two references and one revocation');
  assert.equal(relationRecordSummary.filter((text) => /^Referência/m.test(text)).length, 2);
  assert.equal(relationRecordSummary.filter((text) => /^Revogação/m.test(text)).length, 1);
  const deduplicatedTimelineScreenshot = path.join(evidenceRoot, 'norma-timeline-remissoes-deduplicadas.png');
  await page.screenshot({ path: deduplicatedTimelineScreenshot, fullPage: true });
  report.evidence.push(deduplicatedTimelineScreenshot);
  report.checks.push({ route: detailPath, interaction: 'deduplicate-timeline-and-evidence-records', referenceTimelineEntries: remittanceTimelineEntries.length, relationRecordCount: relationRecordSummary.length });
  assert.match(detailText, /Relações normativas/);
  await page.$$eval('summary', (summaries) => {
    summaries.find((summary) => summary.innerText.includes('Relações normativas'))?.click();
  });
  await page.waitForFunction(() => {
    const status = document.querySelector('[data-relations-status]');
    return status && status.getAttribute('aria-busy') !== 'true' && status.innerText.includes('2 vínculos');
  }, { timeout: 5000 });
  const incomingRelationGroups = await page.$$eval('.normative-relations__group-button', (buttons) => buttons.map((button) => button.innerText));
  assert.equal(incomingRelationGroups.length, 1);
  assert.match(incomingRelationGroups[0], /Lei Complementar nº 198\/2021.*Lei Complementar nº 55\/2004/s);
  const detailScreenshot = path.join(evidenceRoot, 'norma-remissoes-recebidas-expandido-desktop.png');
  await page.screenshot({ path: detailScreenshot, fullPage: true });
  report.evidence.push(detailScreenshot);

  await page.goto(new URL(detailPath, baseUrl).href, { waitUntil: 'domcontentloaded' });
  const actionFilter = await page.$('[data-relations-action]');
  await actionFilter.evaluate((select) => {
    select.value = 'REFERENCIA';
    select.dispatchEvent(new Event('change', { bubbles: true }));
  });
  let delayedFailureCount = 1;
  await page.setRequestInterception(true);
  const failGraphOnce = async (request) => {
    if (delayedFailureCount > 0 && new URL(request.url()).pathname.endsWith('/relations/')) {
      delayedFailureCount -= 1;
      await new Promise((resolve) => setTimeout(resolve, 350));
      await request.respond({ status: 503, contentType: 'application/json', body: '{"success":false}' });
      return;
    }
    await request.continue();
  };
  page.on('request', failGraphOnce);
  await page.click('[data-relations-toggle]');
  const graphStatus = await page.$('[data-relations-status]');
  await page.waitForFunction(() => document.querySelector('[data-relations-status]')?.getAttribute('aria-busy') === 'true');
  const slowStateVisible = await graphStatus.evaluate((element) => element.innerText.includes('Carregando relações'));
  assert.equal(slowStateVisible, true, 'slow graph request must expose a loading status');
  await page.waitForFunction(() => document.querySelector('[data-relations-status]')?.dataset.state === 'error');
  const errorState = await graphStatus.evaluate((element) => element.innerText);
  const retryVisible = await page.$eval('[data-relations-retry]', (button) => !button.hidden);
  const filterPreserved = await actionFilter.evaluate((select) => select.value === 'REFERENCIA');
  assert.match(errorState, /Não foi possível carregar as relações/);
  assert.equal(retryVisible, true);
  assert.equal(filterPreserved, true, 'API failure must preserve the selected relation filter');
  await page.setRequestInterception(false);
  page.off('request', failGraphOnce);
  await page.click('[data-relations-retry]');
  await page.waitForFunction(() => {
    const status = document.querySelector('[data-relations-status]');
    return status && status.dataset.state !== 'error' && status.getAttribute('aria-busy') !== 'true';
  });
  const retryHiddenAfterSuccess = await page.$eval('[data-relations-retry]', (button) => button.hidden);
  assert.equal(retryHiddenAfterSuccess, true, 'successful retry must clear the retry action');
  report.checks.push({ route: detailPath, interaction: 'R06-slow-503-retry', slowStateVisible, errorState, retryVisible, filterPreserved, retryHiddenAfterSuccess });

  await open(page, '/pesquisa/?q=Lei%20n%C2%BA%209001%2F2020', { width: 1280, height: 900 });
  const exactSearchText = await page.$eval('body', (body) => body.innerText);
  assert.match(exactSearchText, /Referência normativa exata não localizada/);
  assert.match(exactSearchText, /Norma não encontrada no acervo/);
  assert.doesNotMatch(exactSearchText, /Nenhuma correspondência semântica encontrada/);
  const searchScreenshot = path.join(evidenceRoot, 'pesquisa-referencia-ausente-desktop.png');
  await page.screenshot({ path: searchScreenshot, fullPage: true });
  report.evidence.push(searchScreenshot);

  await page.goto(new URL('/normas/', baseUrl).href, { waitUntil: 'domcontentloaded' });
  await page.click('button[aria-label="Recolher navegação"], button[aria-label="Expandir navegação"]');
  await page.waitForFunction(() => document.querySelector('button[aria-label="Expandir navegação"]'));
  const sidebarWidth = await page.$eval('.workspace-sidebar', (element) => getComputedStyle(element).width);
  assert.equal(sidebarWidth, '72px');
  await page.goto(new URL('/configuracoes/', baseUrl).href, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('button[aria-label="Expandir navegação"]');
  const sidebarIcons = await page.$$eval('.workspace-nav-icon', (icons) => icons.length);
  assert.ok(sidebarIcons >= 6, `expected navigation icons in collapsed shell, got ${sidebarIcons}`);
  report.checks.push({ route: '/configuracoes/', interaction: 'sidebar-collapse-persists-across-routes', sidebarWidth, sidebarIcons });

  await page.setViewport({ width: 320, height: 800 });
  await page.goto(new URL(detailPath, baseUrl).href, { waitUntil: 'domcontentloaded' });
  const mobileDetail = await page.evaluate(() => ({
    viewportWidth: document.documentElement.clientWidth,
    documentWidth: document.documentElement.scrollWidth,
    mainVisible: Boolean(document.querySelector('main')?.getClientRects().length),
  }));
  assert.ok(mobileDetail.documentWidth <= mobileDetail.viewportWidth, 'detail page must reflow at 320px');
  const temporalFactsLayout = await page.$eval('.legal-temporal-facts', (facts) => ({
    rowCount: facts.querySelectorAll(':scope > div').length,
    rows: [...facts.querySelectorAll(':scope > div')].map((row) => {
      const label = row.querySelector('dt').getBoundingClientRect();
      const value = row.querySelector('dd').getBoundingClientRect();
      return {
        labelWidth: Math.round(label.width),
        valueWidth: Math.round(value.width),
        labelBottom: Math.round(label.bottom),
        valueTop: Math.round(value.top),
      };
    }),
  }));
  assert.equal(temporalFactsLayout.rowCount, 3, 'publication, effective date and status must remain separate labelled facts');
  assert.ok(temporalFactsLayout.rows.every((row) => row.valueWidth >= row.labelWidth), 'temporal values must use the full mobile card width instead of a squeezed second table column');
  assert.ok(temporalFactsLayout.rows.every((row) => row.valueTop >= row.labelBottom), 'temporal values must stack beneath their labels on mobile');
  report.checks.push({ route: detailPath, interaction: 'R24-mobile-temporal-facts-stack', ...temporalFactsLayout });
  const mobileBackLink = await page.$eval('.legal-detail-back-link', (link) => {
    const rect = link.getBoundingClientRect();
    return { width: rect.width, height: rect.height, left: rect.left, right: rect.right };
  });
  assert.ok(mobileBackLink.height >= 44, 'detail back action must meet the 44px touch-target baseline');
  assert.ok(mobileBackLink.left >= 0 && mobileBackLink.right <= mobileDetail.viewportWidth, 'detail back action must remain visible at 320px');
  report.checks.push({ route: detailPath, interaction: 'R24-mobile-detail-back-target', ...mobileBackLink });
  const mobileScreenshot = path.join(evidenceRoot, 'norma-mobile-320.png');
  await page.screenshot({ path: mobileScreenshot, fullPage: true });
  report.evidence.push(mobileScreenshot);

  const lightPage = await browserInstance.newPage();
  await lightPage.setViewport({ width: 1280, height: 900 });
  await lightPage.evaluateOnNewDocument(() => {
    localStorage.setItem('jurix-theme', 'light');
    localStorage.setItem('jurix-preferences', JSON.stringify({ theme: 'light', density: 'comfortable' }));
  });
  for (const route of ['/assistente/', '/pesquisa/', '/normas/', '/colecoes/', '/historico/', '/configuracoes/']) {
    const errors = [];
    lightPage.removeAllListeners('pageerror');
    lightPage.on('pageerror', (error) => errors.push(error.name));
    const response = await lightPage.goto(new URL(route, baseUrl).href, {
      waitUntil: 'domcontentloaded',
      timeout: 20000,
    });
    const metrics = await lightPage.evaluate(() => ({
      theme: document.documentElement.getAttribute('data-theme'),
      viewportWidth: document.documentElement.clientWidth,
      documentWidth: document.documentElement.scrollWidth,
      mainVisible: Boolean(document.querySelector('main')?.getClientRects().length),
      bodyBackground: getComputedStyle(document.body).backgroundColor,
    }));
    const result = {
      route,
      theme: 'light',
      width: 1280,
      height: 900,
      status: response?.status() ?? null,
      ...metrics,
      errors,
    };
    report.checks.push(result);
    if (
      result.status !== 200
      || result.theme !== 'light'
      || !result.mainVisible
      || result.documentWidth > result.viewportWidth
      || errors.length
    ) report.failures.push(result);
    if (route === '/normas/' || route === '/assistente/') {
      const screenshot = path.join(evidenceRoot, `light-${route.replaceAll('/', '') || 'home'}.png`);
      await lightPage.screenshot({ path: screenshot, fullPage: true });
      report.evidence.push(screenshot);
    }
  }
  report.summary = {
    viewportRouteChecks: report.checks.filter((item) => item.status !== undefined).length,
    interactionChecks: report.checks.length - report.checks.filter((item) => item.status !== undefined).length,
    lightThemeRouteChecks: report.checks.filter((item) => item.theme === 'light').length,
    failures: report.failures.length,
  };
} finally {
  await browserInstance.close();
}

await fs.writeFile(
  path.join(evidenceRoot, 'product-smoke-report.json'),
  JSON.stringify(report, null, 2),
  { flag: 'wx' },
);
console.log(JSON.stringify(report, null, 2));
if (report.failures.length) process.exitCode = 1;
