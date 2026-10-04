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
assert.equal(localBase.port, '8007', 'smoke is restricted to the isolated QA server on port 8007');
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
await fs.mkdir(evidenceRoot, { recursive: true });
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
  for (const width of [320, 360, 768, 1280, 1920]) {
    for (const route of ['/assistente/', '/pesquisa/', '/normas/', '/colecoes/', '/historico/', '/configuracoes/']) {
      await open(page, route, { width, height: 900 });
    }
  }

  const detailPath = `/normas/${detailNormaId}/`;
  await open(page, detailPath, { width: 1280, height: 900 });
  const detailText = await page.$eval('body', (body) => body.innerText);
  assert.match(detailText, /Lei Complementar nº 55\/2004/);
  assert.match(detailText, /Pendente/);
  assert.match(detailText, /Norma municipal/i);
  assert.match(detailText, /Referência revisada · sem efeito de alteração/);
  assert.match(detailText, /Relações normativas/);
  await page.$$eval('summary', (summaries) => {
    summaries.find((summary) => summary.innerText.includes('Relações normativas'))?.click();
  });
  await page.waitForFunction(() => document.body.innerText.includes('Esta norma não possui relações públicas disponíveis no corpus.'), { timeout: 5000 });
  const detailScreenshot = path.join(evidenceRoot, 'norma-pendente-grafo-expandido-desktop.png');
  await page.screenshot({ path: detailScreenshot, fullPage: true });
  report.evidence.push(detailScreenshot);

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
  assert.ok(mobileDetail.documentWidth <= mobileDetail.viewportWidth, 'detail page must reflow at 360px');
  const mobileScreenshot = path.join(evidenceRoot, 'norma-mobile-320.png');
  await page.screenshot({ path: mobileScreenshot, fullPage: true });
  report.evidence.push(mobileScreenshot);
  report.summary = { viewportRouteChecks: report.checks.filter((item) => item.status !== undefined).length, failures: report.failures.length };
} finally {
  await browserInstance.close();
}

console.log(JSON.stringify(report, null, 2));
if (report.failures.length) process.exitCode = 1;
