import assert from 'node:assert/strict';
import fs from 'node:fs';
import puppeteer from 'puppeteer-core';

const baseUrl = process.env.JURIX_BASE_URL || 'http://127.0.0.1:8005';
const executablePath = process.env.PUPPETEER_EXECUTABLE_PATH || [
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
  '/usr/bin/google-chrome',
  '/usr/bin/chromium',
].find((candidate) => fs.existsSync(candidate));

if (!executablePath) throw new Error('Defina PUPPETEER_EXECUTABLE_PATH para Chrome/Edge.');

const routes = [
  '/assistente/',
  '/normas/',
  '/normas/3/',
  '/pesquisa/',
  '/colecoes/',
  '/historico/',
  '/configuracoes/',
];
const browser = await puppeteer.launch({
  executablePath,
  headless: true,
  args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'],
});
const page = await browser.newPage();
const errors = [];
page.on('pageerror', (error) => errors.push(error.message));
const observations = [];

try {
  for (const width of [320, 360, 768, 1280, 1920]) {
    await page.setViewport({ width, height: 900 });
    for (const route of routes) {
      const response = await page.goto(new URL(route, baseUrl), {
        waitUntil: 'domcontentloaded',
        timeout: 20000,
      });
      await new Promise((resolve) => setTimeout(resolve, 180));
      const view = await page.evaluate(() => ({
        title: document.title,
        route: location.pathname,
        width: document.documentElement.clientWidth,
        scrollWidth: document.documentElement.scrollWidth,
        main: Boolean(document.querySelector('main')),
        sidebar: Boolean(document.querySelector('#sidebar')),
        heading: document.querySelector('main h1, main h2')?.textContent.trim() || null,
      }));
      assert.ok(response?.status() < 500, `${route} retornou HTTP ${response?.status()}`);
      assert.equal(view.width, width, `${route} alterou a largura do viewport em ${width}px`);
      assert.ok(view.main, `${route} não possui landmark main`);
      assert.ok(view.scrollWidth <= width, `${route} tem overflow horizontal em ${width}px`);
      observations.push({ viewport: width, status: response.status(), ...view });
    }
  }

  await page.setViewport({ width: 1280, height: 900 });
  await page.goto(new URL('/normas/', baseUrl), { waitUntil: 'domcontentloaded' });
  const collapseButton = await page.$('#toggle-sidebar');
  assert.ok(collapseButton, 'toggle da sidebar não encontrado em /normas/');
  await collapseButton.click();
  await page.waitForFunction(() => document.documentElement.dataset.sidebarCollapsed === 'true');
  await page.goto(new URL('/configuracoes/', baseUrl), { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => document.documentElement.dataset.sidebarCollapsed === 'true');
  const collapsedIcons = await page.$$eval(
    '#sidebar .workspace-nav-item svg, #sidebar .workspace-nav-item [aria-hidden="true"]',
    (nodes) => nodes.length,
  );
  assert.ok(collapsedIcons >= 4, 'sidebar recolhida perdeu os ícones de navegação');

  assert.deepEqual(errors, [], `erros JavaScript em runtime: ${errors.join('; ')}`);
  console.log(JSON.stringify({
    baseUrl,
    status: 'passed',
    route_observations: observations,
    collapsed_sidebar_icons: collapsedIcons,
    page_errors: errors,
    note: 'Smoke visual/estrutural, não certifica WCAG nem substitui testes de interação jurídica.',
  }, null, 2));
} finally {
  await browser.close();
}
