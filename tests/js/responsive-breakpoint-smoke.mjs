import fs from 'node:fs/promises';
import puppeteer from 'puppeteer-core';

const baseUrl = process.env.JURIX_UI_AUDIT_URL || 'http://127.0.0.1:8004';
const browserCandidates = [
  process.env.PUPPETEER_EXECUTABLE_PATH,
  process.env.CHROME_BIN,
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
  '/usr/bin/google-chrome',
  '/usr/bin/chromium',
].filter(Boolean);

const available = await Promise.all(browserCandidates.map(async (candidate) => {
  try {
    await fs.access(candidate);
    return candidate;
  } catch {
    return null;
  }
}));
const executablePath = available.find(Boolean);
if (!executablePath) throw new Error('Chrome/Edge executable not found.');

const routes = [
  '/assistente/',
  '/pesquisa/',
  '/pesquisa/?q=servidor+educa%C3%A7%C3%A3o&tipo=&ano=&similaridade=0',
  '/normas/',
  '/normas/?q=8205&tipo=&ano=2026&ordenar=recentes',
  '/normas/3/',
  '/normas/3/compare/',
  '/normas/3/tree/',
  '/colecoes/',
  '/historico/',
  '/configuracoes/',
];
const viewports = [
  { width: 768, height: 1024 },
  { width: 1024, height: 768 },
];
const browser = await puppeteer.launch({
  executablePath,
  headless: true,
  args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'],
});
const failures = [];

try {
  for (const viewport of viewports) {
    for (const route of routes) {
      const page = await browser.newPage();
      const errors = [];
      page.on('pageerror', (error) => errors.push(error.message));
      page.on('console', (message) => {
        if (message.type() === 'error') errors.push(message.text());
      });
      page.on('requestfailed', (request) => errors.push(`${request.url()}: ${request.failure()?.errorText}`));
      await page.setViewport(viewport);

      try {
        const response = await page.goto(`${baseUrl}${route}`, { waitUntil: 'domcontentloaded', timeout: 20000 });
        const metrics = await page.evaluate(() => ({
          title: document.title,
          viewport: document.documentElement.clientWidth,
          document: document.documentElement.scrollWidth,
          mainVisible: Boolean(document.querySelector('main')?.getClientRects().length),
        }));
        const result = { route, ...viewport, status: response?.status() ?? null, ...metrics, errors };
        if (result.status !== 200 || !result.mainVisible || result.document > result.viewport || errors.length) {
          failures.push(result);
        }
      } catch (error) {
        failures.push({ route, ...viewport, error: error.message, errors });
      } finally {
        await page.close();
      }
    }
  }
} finally {
  await browser.close();
}

console.log(JSON.stringify({
  baseUrl,
  viewports,
  routeCount: routes.length,
  checked: viewports.length * routes.length,
  failures,
}, null, 2));

if (failures.length) process.exitCode = 1;
