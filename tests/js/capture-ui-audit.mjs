import fs from 'node:fs/promises';
import path from 'node:path';
import puppeteer from 'puppeteer-core';

const ROOT = path.resolve(import.meta.dirname, '../..');
const BASE_URL = process.env.JURIX_UI_AUDIT_URL || 'http://127.0.0.1:8004';
const phase = process.argv[2];

if (!['before', 'after'].includes(phase)) {
  throw new Error('Usage: node tests/js/capture-ui-audit.mjs <before|after>');
}

const browserPaths = [
  process.env.PUPPETEER_EXECUTABLE_PATH,
  process.env.CHROME_BIN,
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
  'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
  '/usr/bin/google-chrome',
  '/usr/bin/chromium',
  '/usr/bin/chromium-browser',
].filter(Boolean);
// Resolve executable candidates with async fs.access without depending on the
// user's PATH or on a browser-specific Puppeteer download.
const availableBrowsers = await Promise.all(browserPaths.map(async (candidate) => {
  try {
    await fs.access(candidate);
    return candidate;
  } catch {
    return null;
  }
}));
const browserPath = availableBrowsers.find(Boolean);
if (!browserPath) throw new Error('Chrome/Edge executable not found.');

const routes = [
  ['assistant', '/assistente/'],
  ['command-palette', '/normas/'],
  ['search-empty', '/pesquisa/'],
  ['search-results', '/pesquisa/?q=servidor+educa%C3%A7%C3%A3o&tipo=&ano=&similaridade=0'],
  ['norms', '/normas/'],
  ['norm-number-year', '/normas/?q=8205&tipo=&ano=2026&ordenar=recentes'],
  ['norm-detail', '/normas/3/'],
  ['norm-compare', '/normas/3/compare/'],
  ['norm-tree', '/normas/3/tree/'],
  ['collections', '/colecoes/'],
  ['history', '/historico/'],
  ['settings', '/configuracoes/'],
];
const viewports = [
  ['1440x900', 1440, 900],
  ['1280x800', 1280, 800],
  ['390x844', 390, 844],
];
const outputDir = path.join(ROOT, 'docs', 'ui-audit', phase);
await fs.mkdir(outputDir, { recursive: true });

const browser = await puppeteer.launch({
  executablePath: browserPath,
  headless: true,
  args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'],
});
const results = [];

try {
  for (const [routeName, routePath] of routes) {
    for (const [viewportName, width, height] of viewports) {
      const page = await browser.newPage();
      const consoleErrors = [];
      const failedRequests = [];
      const badResponses = [];
      await page.setViewport({ width, height, deviceScaleFactor: 1 });
      page.on('pageerror', (error) => consoleErrors.push(error.message));
      page.on('console', (message) => {
        if (message.type() === 'error') consoleErrors.push(message.text());
      });
      page.on('requestfailed', (request) => {
        failedRequests.push({ url: request.url(), error: request.failure()?.errorText });
      });
      page.on('response', (response) => {
        if (response.status() >= 400) {
          badResponses.push({ status: response.status(), url: response.url() });
        }
      });

      let status = null;
      let navigationError = null;
      try {
        const response = await page.goto(`${BASE_URL}${routePath}`, {
          waitUntil: 'domcontentloaded',
          timeout: 20000,
        });
        status = response?.status() ?? null;
        await page.evaluate(() => document.fonts?.ready);
        await new Promise((resolve) => setTimeout(resolve, 180));
        if (routeName === 'command-palette') {
          await page.click('#command-palette-trigger');
          await page.type('#command-palette-input', 'normas');
          await page.waitForSelector('.command-palette-item[data-command-id="norms"][aria-selected="true"]');
        }
      } catch (error) {
        navigationError = error.message;
      }

      const metrics = await page.evaluate(() => ({
        title: document.title,
        url: location.href,
        viewportWidth: document.documentElement.clientWidth,
        documentWidth: document.documentElement.scrollWidth,
        documentHeight: document.documentElement.scrollHeight,
        mainVisible: Boolean(document.querySelector('main')?.getClientRects().length),
      })).catch((error) => ({ inspectionError: error.message }));
      const filename = `${routeName}-${viewportName}.png`;
      await page.screenshot({ path: path.join(outputDir, filename), fullPage: false });
      results.push({
        route: routeName,
        requestedPath: routePath,
        viewport: viewportName,
        screenshot: filename,
        status,
        navigationError,
        ...metrics,
        horizontalOverflow: metrics.documentWidth > width,
        consoleErrors,
        failedRequests,
        badResponses,
      });
      await page.close();
    }
  }
} finally {
  await browser.close();
}

const manifest = {
  phase,
  baseUrl: BASE_URL,
  capturedAt: new Date().toISOString(),
  browser: browserPath,
  results,
};
await fs.writeFile(
  path.join(outputDir, 'manifest.json'),
  `${JSON.stringify(manifest, null, 2)}\n`,
  'utf8',
);
const failed = results.filter((result) => (
  result.status !== 200
  || result.navigationError
  || result.horizontalOverflow
  || result.consoleErrors.length
  || result.badResponses.length
));
console.log(`${phase}: captured ${results.length} views; ${failed.length} need review`);
if (failed.length) console.log(JSON.stringify(failed, null, 2));
