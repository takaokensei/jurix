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
  { width: 320, height: 780, isMobile: true, hasTouch: true },
  { width: 360, height: 780, isMobile: true, hasTouch: true },
  { width: 768, height: 1024 },
  { width: 1280, height: 900 },
  { width: 1920, height: 1080 },
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
          internalOverflow: location.pathname === '/normas/'
            ? (() => {
              const main = document.querySelector('main')?.getBoundingClientRect();
              if (!main) return ['main-missing'];
              return [
                ['norma-shell', document.querySelector('.jurix-norma-shell')],
                ['norma-toolbar', document.querySelector('.jurix-norma-toolbar')],
                ['norma-filters', document.querySelector('.jurix-norma-filter-grid')],
                ['archive-filters', document.querySelector('.jurix-archive-candidate-filters')],
                ...[...document.querySelectorAll('.jurix-norma-select')].map((element, index) => [`norma-select-${index + 1}`, element]),
              ].flatMap(([name, element]) => {
                if (!element) return [];
                const rect = element.getBoundingClientRect();
                return rect.left < main.left - 1 || rect.right > main.right + 1
                  || element.scrollWidth > element.clientWidth + 1
                  ? [{ name, left: Math.round(rect.left), right: Math.round(rect.right), width: element.clientWidth, scrollWidth: element.scrollWidth }]
                  : [];
              });
            })()
            : [],
          touchTargetFailures: matchMedia('(pointer: coarse)').matches
            ? [...document.querySelectorAll('button,select,textarea,input,[role=button]')]
              .map((element) => element.matches('input[type=radio]') ? element.closest('label') : element)
              .filter((element) => element?.getClientRects().length)
              .map((element) => {
                const rect = element.getBoundingClientRect();
                return { element, width: Math.round(rect.width), height: Math.round(rect.height) };
              })
              .filter(({ element, width, height }) => {
                const rect = element.getBoundingClientRect();
                return rect.right > 0 && rect.left < innerWidth && (width < 44 || height < 44);
              })
              .map(({ element, width, height }) => ({
                label: (element.innerText || element.getAttribute('aria-label') || element.name || element.tagName)
                  .trim().replace(/\s+/g, ' ').slice(0, 48),
                width,
                height,
              }))
            : [],
          linkTargetFailures: matchMedia('(pointer: coarse)').matches
            ? [...document.querySelectorAll('a[href]')]
              .filter((element) => element.getClientRects().length)
              .map((element) => {
                const rect = element.getBoundingClientRect();
                return {
                  element,
                  width: Math.round(rect.width),
                  height: Math.round(rect.height),
                  left: Math.round(rect.left),
                  right: Math.round(rect.right),
                  top: Math.round(rect.top),
                  bottom: Math.round(rect.bottom),
                };
              })
              .filter(({ width, height, left, right, top, bottom }) =>
                right > 0 && left < innerWidth && bottom > 0 && top < innerHeight
                && (width < 24 || height < 24))
              .map(({ element, width, height }) => ({
                label: (element.innerText || element.getAttribute('aria-label') || element.title || 'link')
                  .trim().replace(/\s+/g, ' ').slice(0, 48),
                width,
                height,
              }))
            : [],
        }));
        const result = { route, ...viewport, status: response?.status() ?? null, ...metrics, errors };
        if (result.status !== 200 || !result.mainVisible || result.document > result.viewport
          || result.internalOverflow.length || result.touchTargetFailures.length
          || result.linkTargetFailures.length || errors.length) {
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
