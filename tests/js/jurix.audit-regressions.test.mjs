import assert from 'node:assert/strict';
import fs from 'node:fs';
import { test } from 'node:test';
import puppeteer from 'puppeteer-core';

const browserCandidates = [
  process.env.PUPPETEER_EXECUTABLE_PATH,
  process.env.CHROME_BIN,
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
  'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
  '/usr/bin/google-chrome',
  '/usr/bin/chromium',
  '/usr/bin/chromium-browser',
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
].filter(Boolean);
const executablePath = browserCandidates.find((candidate) => fs.existsSync(candidate));
const baseUrl = process.env.JURIX_QA_BASE_URL?.replace(/\/$/, '');
const normaId = process.env.JURIX_QA_NORMA_ID;
const skipReason = !baseUrl
  ? 'Defina JURIX_QA_BASE_URL para executar contra um servidor Django QA isolado.'
  : !executablePath
    ? 'Chrome/Edge não encontrado; configure PUPPETEER_EXECUTABLE_PATH.'
    : null;

test('Jurix Django QA reflows the core surfaces at five widths without browser errors', {
  skip: skipReason || false,
}, async () => {
  const browser = await puppeteer.launch({
    executablePath,
    headless: true,
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
  });
  const page = await browser.newPage();
  const pageErrors = [];
  const externalFontRequests = [];
  page.on('pageerror', (error) => pageErrors.push(error.message));
  page.on('request', (request) => {
    if (/fonts\.(googleapis|gstatic)\.com/i.test(request.url())) {
      externalFontRequests.push(request.url());
    }
  });

  try {
    const routes = [
      '/assistente/',
      '/normas/',
      '/pesquisa/',
      '/configuracoes/',
      '/historico/',
      '/colecoes/',
    ];
    if (normaId) {
      routes.push(
        `/normas/${encodeURIComponent(normaId)}/`,
        `/normas/${encodeURIComponent(normaId)}/compare/`,
        `/normas/${encodeURIComponent(normaId)}/tree/`,
      );
    }

    for (const width of [320, 360, 768, 1280, 1920]) {
      await page.setViewport({ width, height: 900, deviceScaleFactor: 1 });
      await page.emulateMediaFeatures([
        { name: 'prefers-reduced-motion', value: 'reduce' },
        { name: 'prefers-color-scheme', value: 'dark' },
      ]);
      for (const route of routes) {
        const response = await page.goto(`${baseUrl}${route}`, {
          waitUntil: 'domcontentloaded',
          timeout: 15000,
        });
        assert.ok(response, `Sem resposta HTTP para ${route} em ${width}px`);
        assert.ok(response.status() < 400, `${route} retornou ${response.status()} em ${width}px`);
        const layout = await page.evaluate(() => ({
          viewport: window.innerWidth,
          document: document.documentElement.scrollWidth,
          body: document.body?.scrollWidth || 0,
          hasTraceback: /Traceback|Server Error/i.test(document.body?.innerText || ''),
        }));
        assert.equal(layout.hasTraceback, false, `${route} expôs erro em ${width}px`);
        assert.ok(
          layout.document <= layout.viewport + 1,
          `${route} tem overflow horizontal global em ${width}px (${layout.document}px)`,
        );
        assert.ok(
          layout.body <= layout.viewport + 1,
          `${route} tem body mais largo que viewport em ${width}px (${layout.body}px)`,
        );
      }
    }

    await page.emulateMediaFeatures([{ name: 'prefers-reduced-motion', value: 'reduce' }]);
    assert.equal(await page.evaluate(() => matchMedia('(prefers-reduced-motion: reduce)').matches), true);

    await page.setViewport({ width: 1280, height: 900, deviceScaleFactor: 1 });
    await page.goto(`${baseUrl}/assistente/`, { waitUntil: 'domcontentloaded' });
    const paletteTrigger = await page.$('#command-palette-trigger');
    assert.ok(paletteTrigger, 'Busca rápida deve estar disponível no assistente');
    await paletteTrigger.focus();
    await page.keyboard.press('Enter');
    await page.waitForFunction(() => document.querySelector('#command-palette-overlay')?.classList.contains('active'));
    assert.equal(await page.evaluate(() => document.activeElement?.id), 'command-palette-input');
    await page.keyboard.press('Escape');
    await page.waitForFunction(() => !document.querySelector('#command-palette-overlay')?.classList.contains('active'));
    await new Promise((resolve) => setTimeout(resolve, 300));
    assert.equal(await page.evaluate(() => document.activeElement?.id), 'command-palette-trigger');

    for (const theme of ['light', 'dark']) {
      assert.equal(
        await page.evaluate((nextTheme) => {
          window.jurixTheme.setTheme(nextTheme);
          return document.documentElement.dataset.theme;
        }, theme),
        theme,
        `Tema ${theme} precisa ser aplicável sem recarregar a página`,
      );
    }
    assert.deepEqual(pageErrors, [], 'Erros JavaScript no navegador QA');
    assert.deepEqual(externalFontRequests, [], 'A interface não deve carregar Google Fonts');
  } finally {
    await browser.close();
  }
});
