// Read-only browser audit. Usage: node docs/audit/capture_runtime.mjs http://127.0.0.1:8005
// Uses a fresh browser profile; never submits a server-side form.
// Assistant GET creates a Django session, so it is opt-in and changes ephemeral QA data.
import fs from 'node:fs/promises';
import path from 'node:path';
import { createRequire } from 'node:module';

const requireFromTests = createRequire(new URL('../../tests/js/package.json', import.meta.url));
const puppeteer = requireFromTests('puppeteer-core');
const root = path.dirname(new URL(import.meta.url).pathname.replace(/^\/(?:[A-Za-z]:)/, value => value.slice(1)));
const base = process.argv[2];
if (!base || !/^http:\/\/(127\.0\.0\.1|localhost):\d+$/.test(base)) {
  throw new Error('Pass an explicit localhost HTTP origin.');
}
const candidates = [
  process.env.CHROME_BIN,
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
  'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
].filter(Boolean);
let executablePath;
for (const candidate of candidates) {
  try { await fs.access(candidate); executablePath = candidate; break; } catch { /* next */ }
}
if (!executablePath) throw new Error('Chrome/Edge executable unavailable.');

const allowSessionSideEffects = process.argv.includes('--allow-audit-session');
const routes = [
  ...(allowSessionSideEffects ? [['assistant', '/assistente/']] : []),
  ['norms', '/normas/'],
  ['norm-detail', '/normas/3/'],
  ['norm-compare', '/normas/3/compare/'],
  ['norm-tree', '/normas/3/tree/'],
  ['search-empty', '/pesquisa/'],
  ['search-results', '/pesquisa/?q=IPTU'],
  ['collections', '/colecoes/'],
  ['history', '/historico/'],
  ['settings', '/configuracoes/'],
];
const viewports = [[360, 800], [768, 1024], [1280, 800], [1920, 1080]];
const screenshotDir = path.join(root, 'screenshots');
await fs.mkdir(screenshotDir, { recursive: true });
const browser = await puppeteer.launch({ executablePath, headless: true, args: ['--no-sandbox'] });
const records = [];

try {
  for (const theme of ['dark', 'light']) {
    for (const [name, route] of routes) {
      for (const [width, height] of viewports) {
        const page = await browser.newPage();
        const errors = [];
        await page.setViewport({ width, height, deviceScaleFactor: 1 });
        await page.evaluateOnNewDocument(selectedTheme => {
          localStorage.setItem('jurix-preferences', JSON.stringify({ theme: selectedTheme, density: 'comfortable' }));
        }, theme);
        page.on('pageerror', error => errors.push(error.name));
        let status = 0;
        try {
          const response = await page.goto(base + route, { waitUntil: 'networkidle2', timeout: 30000 });
          status = response?.status() || 0;
          const metrics = await page.evaluate(() => {
            const clickable = [...document.querySelectorAll('a, button, input, select, summary')]
              .filter(el => { const box = el.getBoundingClientRect(); return box.width > 0 && box.height > 0; });
            const small = clickable.filter(el => {
              const box = el.getBoundingClientRect();
              return box.width < 24 || box.height < 24;
            });
            const nav = performance.getEntriesByType('navigation')[0];
            return {
              title: document.title,
              h1Count: document.querySelectorAll('h1').length,
              horizontalOverflowPx: Math.max(0, document.documentElement.scrollWidth - innerWidth),
              scrollHeight: document.documentElement.scrollHeight,
              viewportHeight: innerHeight,
              visibleTargets: clickable.length,
              under24Targets: small.length,
              under24Selectors: small.slice(0, 8).map(el => `${el.tagName.toLowerCase()}${el.className && typeof el.className === 'string' ? '.' + el.className.trim().split(/\s+/).slice(0, 2).join('.') : ''}`),
              domContentLoadedMs: nav ? Math.round(nav.domContentLoadedEventEnd - nav.startTime) : null,
              transferBytes: performance.getEntriesByType('resource').reduce((sum, entry) => sum + (entry.transferSize || 0), 0),
            };
          });
          // Public pages only; the fresh profile has no account or personal history.
          // Blur public legal text that may contain people's names in the visual artifact.
          await page.addStyleTag({ content: '.dispositivo-text, .legal-detail-ementa, .workspace-result-snippet, .jurix-norma-card p { filter: blur(7px) !important; }' });
          const file = `${name}-${theme}-${width}x${height}.png`;
          await page.screenshot({ path: path.join(screenshotDir, file), fullPage: false });
          const interaction = {};
          if (theme === 'dark' && width === 360 && name === 'assistant') {
            await page.keyboard.down('Control');
            await page.keyboard.press('k');
            await page.keyboard.up('Control');
            interaction.paletteOpened = await page.$eval('#command-palette-overlay', el => el.getAttribute('aria-hidden') === 'false');
            await page.keyboard.press('Escape');
          }
          if (theme === 'dark' && width === 360 && name === 'settings') {
            await page.select('[name="llm_provider"]', 'openai');
            interaction.providerFieldsVisible = await page.$eval('[name="llm_api_key"]', el => !el.closest('[hidden]'));
          }
          if (theme === 'dark' && width === 360 && name === 'norm-detail') {
            const summary = await page.$('.legal-consolidated-details > summary');
            if (summary) {
              await summary.click();
              interaction.fullTextOpened = await page.$eval('.legal-consolidated-details', el => el.open);
            }
          }
          records.push({ route, name, theme, width, height, status, ...metrics, interaction, pageErrors: errors, screenshot: file });
        } catch (error) {
          records.push({ route, name, theme, width, height, status, failure: error.name, pageErrors: errors });
        } finally {
          await page.close();
        }
      }
    }
  }
} finally {
  await browser.close();
}
await fs.writeFile(path.join(root, 'runtime-manifest.json'), JSON.stringify(records, null, 2) + '\n');
const failed = records.filter(record => record.status !== 200 || record.failure || record.pageErrors.length);
console.log(JSON.stringify({ views: records.length, failed: failed.length, failures: failed.map(({ name, theme, width, status, failure }) => ({ name, theme, width, status, failure })) }));
