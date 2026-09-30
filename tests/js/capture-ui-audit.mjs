import fs from 'node:fs/promises';
import path from 'node:path';
import puppeteer from 'puppeteer-core';

const ROOT = path.resolve(import.meta.dirname, '../..');
const BASE_URL = process.env.JURIX_UI_AUDIT_URL || 'http://127.0.0.1:8004';
const phase = process.argv[2];
const theme = process.argv[3] || 'dark';
const routeFilter = new Set((process.argv[4] || '').split(',').filter(Boolean));

if (!['before', 'after'].includes(phase) || !['dark', 'light'].includes(theme)) {
  throw new Error('Usage: node tests/js/capture-ui-audit.mjs <before|after> [dark|light]');
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
const selectedRoutes = routeFilter.size ? routes.filter(([name]) => routeFilter.has(name)) : routes;
if (routeFilter.size && selectedRoutes.length !== routeFilter.size) {
  throw new Error(`Unknown audit route: ${[...routeFilter].filter((name) => !routes.some(([route]) => route === name)).join(', ')}`);
}
const viewports = [
  ['1440x900', 1440, 900],
  ['1024x768', 1024, 768],
  ['768x1024', 768, 1024],
  ['1280x800', 1280, 800],
  ['390x844', 390, 844],
];
const outputDir = path.join(ROOT, 'docs', 'ui-audit', phase, ...(theme === 'light' ? ['light'] : []));
await fs.mkdir(outputDir, { recursive: true });

const browser = await puppeteer.launch({
  executablePath: browserPath,
  headless: true,
  args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'],
});
const results = [];

try {
  for (const [routeName, routePath] of selectedRoutes) {
    for (const [viewportName, width, height] of viewports) {
      const page = await browser.newPage();
      const consoleErrors = [];
      const failedRequests = [];
      const badResponses = [];
      const interactionChecks = [];
      await page.setViewport({ width, height, deviceScaleFactor: 1 });
      await page.evaluateOnNewDocument((selectedTheme) => {
        try {
          localStorage.setItem('jurix-preferences', JSON.stringify({ theme: selectedTheme, density: 'comfortable' }));
        } catch {
          // The audit still runs if browser storage is unavailable; the page reports that state separately.
        }
      }, theme);
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
        if (routeName === 'norm-detail') {
          const disclosure = await page.$('.legal-detail-ementa--expandable');
          if (disclosure) {
            const collapsedPreviewVisible = await disclosure.evaluate((details) => (
              !details.open && Boolean(details.querySelector('.legal-detail-ementa-preview')?.getClientRects().length)
            ));
            await disclosure.$eval('summary', (summary) => summary.click());
            await page.waitForFunction(() => {
              const details = document.querySelector('.legal-detail-ementa--expandable');
              return details?.open && Boolean(details.querySelector('.legal-detail-ementa-full')?.getClientRects().length);
            });
            const expandedBounds = await disclosure.evaluate((details) => ({
              height: details.getBoundingClientRect().height,
              width: details.scrollWidth,
              clientWidth: details.clientWidth,
              collapseLabel: details.querySelector('.legal-detail-ementa-collapse-label')?.textContent.trim(),
            }));
            const expandedScreenshot = `norm-detail-ementa-expanded-${viewportName}.png`;
            await page.screenshot({ path: path.join(outputDir, expandedScreenshot), fullPage: false });
            await disclosure.$eval('summary', (summary) => summary.click());
            await page.waitForFunction(() => !document.querySelector('.legal-detail-ementa--expandable')?.open);
            await disclosure.$eval('summary', (summary) => summary.focus());
            await page.keyboard.press('Enter');
            await page.waitForFunction(() => document.querySelector('.legal-detail-ementa--expandable')?.open);
            const keyboardExpanded = await disclosure.evaluate((details) => details.open);
            await page.keyboard.press('Enter');
            await page.waitForFunction(() => !document.querySelector('.legal-detail-ementa--expandable')?.open);
            interactionChecks.push({
              control: 'norma ementa disclosure',
              collapsedPreviewVisible,
              expandedHeight: expandedBounds.height,
              noHorizontalOverflow: expandedBounds.width <= expandedBounds.clientWidth,
              collapseLabel: expandedBounds.collapseLabel,
              collapsedAgain: true,
              keyboardExpanded,
              keyboardCollapsed: true,
              expandedScreenshot,
            });
          }
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
        interactionChecks,
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
  theme,
  routeFilter: [...routeFilter],
  baseUrl: BASE_URL,
  capturedAt: new Date().toISOString(),
  browser: browserPath,
  results,
};
await fs.writeFile(
  path.join(outputDir, routeFilter.size ? `manifest-${[...routeFilter].join('-')}.json` : 'manifest.json'),
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
