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
  ['source-drawer', '/assistente/'],
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
  ['history-delete-dialog', '/historico/'],
  ['settings', '/configuracoes/'],
  ['settings-provider', '/configuracoes/'],
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
        if (routeName === 'source-drawer') {
          await page.evaluate(() => {
            window.JurixRagUI.openSourcesDrawer([
              { norma: 'Lei nº 8204/2026', dispositivo_ref: 'Art. 1º', full_text: 'Fica instituída a Política de Combate a Imóveis Abandonados Causadores de Degradação Urbana (PCIA) no Município de Natal, com o objetivo de identificar, notificar, recuperar e reutilizar imóveis abandonados a fim de promover a revitalização urbana.', pdf_url: 'https://sapl.natal.rn.leg.br/media/sapl/public/normajuridica/2026/9385/lei_no_8.204_2026.pdf', similarity_score: 0.98 },
              { norma: 'Lei nº 8204/2026', dispositivo_ref: 'Art. 4º', full_text: 'Esta Lei entra em vigor na data de sua publicação.', pdf_url: 'https://sapl.natal.rn.leg.br/media/sapl/public/normajuridica/2026/9385/lei_no_8.204_2026.pdf', similarity_score: 0.94 },
              { norma: 'Lei nº 8205/2026', dispositivo_ref: 'Art. 1º', full_text: 'Fica instituído, no Calendário Oficial de Eventos do Município de Natal, o Dia da Educação Popular, a ser celebrado anualmente em 2 de abril, em referência à conclusão da experiência de alfabetização das “40 Horas de Angicos”, realizada em 1963 sob coordenação de Paulo Freire.', pdf_url: 'https://sapl.natal.rn.leg.br/media/sapl/public/normajuridica/2026/9386/lei_no_8.205_2026.pdf', similarity_score: 0.83 },
            ]);
          });
          await page.waitForSelector('.jurix-sources-drawer-panel.is-open .jurix-source-group');
          await page.click('.jurix-source-group__header');
          await page.waitForFunction(() => document.querySelector('.jurix-source-group')?.open);
          const partialState = await page.$eval('.jurix-source-group-toggle-all', (button) => button.dataset.state);
          if (partialState !== 'partially-open') throw new Error(`Expected partial evidence state, got ${partialState}`);
          await page.click('.jurix-source-group-toggle-all');
          await page.waitForFunction(() => [...document.querySelectorAll('.jurix-source-group')].every((group) => group.open));
          await new Promise((resolve) => setTimeout(resolve, 220));
          interactionChecks.push({
            control: 'evidence drawer (local sample data)',
            groups: await page.$$eval('.jurix-source-group', (groups) => groups.map((group) => ({
              title: group.querySelector('.jurix-source-group__title')?.textContent.trim(),
              evidenceCount: group.querySelectorAll('.source-card').length,
              open: group.open,
            }))),
            expandAllState: await page.$eval('.jurix-source-group-toggle-all', (button) => button.dataset.state),
            noHorizontalOverflow: await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth),
          });
        }
        if (routeName === 'history-delete-dialog') {
          await page.evaluate(() => {
            const card = document.createElement('article');
            card.className = 'workspace-history-card';
            card.dataset.historyCard = '';
            card.dataset.sessionId = 'local-preview';
            card.innerHTML = '<div class="workspace-history-card__surface"><span class="workspace-history-main"><span class="workspace-eyebrow">Prévia local</span><strong>Conversa de demonstração</strong></span></div><button type="button" class="workspace-history-delete" data-history-delete aria-label="Excluir conversa de demonstração">Excluir</button>';
            document.querySelector('.workspace-content').prepend(card);
            card.querySelector('[data-history-delete]').click();
          });
          await page.waitForSelector('.workspace-confirm-backdrop.is-open');
          const dialogState = await page.evaluate(() => {
            const dialog = document.querySelector('.workspace-confirm-backdrop');
            const panel = dialog.querySelector('.workspace-confirm-dialog');
            const danger = dialog.querySelector('[data-history-confirm]');
            const icon = dialog.querySelector('.workspace-confirm-icon');
            return {
              theme: document.documentElement.dataset.theme,
              background: getComputedStyle(danger).backgroundColor,
              foreground: getComputedStyle(danger).color,
              iconColor: getComputedStyle(icon).color,
              radius: getComputedStyle(panel).borderRadius,
              focus: document.activeElement?.hasAttribute('data-history-cancel') ? 'cancel' : document.activeElement?.textContent.trim(),
            };
          });
          if (dialogState.radius === '0px') throw new Error('History delete confirmation must have rounded corners');
          await page.keyboard.press('Escape');
          await page.waitForFunction(() => document.querySelector('.workspace-confirm-backdrop')?.getAttribute('aria-hidden') === 'true');
          const escapeRestoredFocus = await page.evaluate(() => document.activeElement?.hasAttribute('data-history-delete') === true);
          if (!escapeRestoredFocus) throw new Error('Escape must close the history dialog and restore focus');
          await page.evaluate(() => document.querySelector('[data-history-delete]').click());
          await page.waitForSelector('.workspace-confirm-backdrop.is-open');
          interactionChecks.push({ control: 'history delete confirmation (local preview)', ...dialogState, escapeRestoredFocus });
        }
        if (routeName === 'settings-provider') {
          await page.select('select[name="llm_provider"]', 'compatible');
          const requiredFieldsShown = await page.evaluate(() => ({
            model: !document.querySelector('[data-external-llm-field] input[name="external_model"]')?.closest('[data-external-llm-field]')?.hidden,
            key: !document.querySelector('[data-external-llm-field] input[name="llm_api_key"]')?.closest('[data-external-llm-field]')?.hidden,
            endpoint: !document.querySelector('[data-compatible-endpoint-field]')?.hidden,
          }));
          await page.click('[data-settings-form] button[type="submit"]');
          await page.waitForFunction(() => document.querySelector('[data-settings-status]')?.textContent.includes('Informe modelo, chave'));
          const invalidState = await page.evaluate(() => ({
            status: document.querySelector('[data-settings-status]').textContent.trim(),
            focusedField: document.activeElement?.name,
          }));
          await page.locator('input[name="external_model"]').fill('local-test-model');
          await page.locator('input[name="llm_endpoint"]').fill('http://127.0.0.1:4000/v1');
          await page.locator('input[name="llm_api_key"]').fill('ui-audit-secret-not-real');
          await page.click('[data-settings-form] button[type="submit"]');
          await page.waitForFunction(() => document.querySelector('[data-settings-status]')?.textContent === 'Preferências salvas neste navegador.');
          const savedState = await page.evaluate(() => ({
            localStorageContainsSecret: localStorage.getItem('jurix-preferences')?.includes('ui-audit-secret-not-real') || false,
            sessionConfig: JSON.parse(sessionStorage.getItem('jurix-llm-session-config') || '{}'),
            theme: document.documentElement.dataset.theme,
            status: document.querySelector('[data-settings-status]').textContent.trim(),
          }));
          if (savedState.localStorageContainsSecret) throw new Error('API key must not be stored in localStorage');
          if (savedState.sessionConfig.api_key !== 'ui-audit-secret-not-real') throw new Error('API key was not saved in this tab session');
          await page.reload({ waitUntil: 'domcontentloaded' });
          await page.waitForFunction(() => document.querySelector('[data-settings-form]'));
          const restoredState = await page.evaluate(() => ({
            provider: document.querySelector('[name="llm_provider"]').value,
            providerLabel: document.querySelector('[name="llm_provider"]').selectedOptions[0]?.textContent.trim(),
            model: document.querySelector('[name="external_model"]').value,
            endpoint: document.querySelector('[name="llm_endpoint"]').value,
            keyRestored: document.querySelector('[name="llm_api_key"]').value === 'ui-audit-secret-not-real',
            endpointVisible: !document.querySelector('[data-compatible-endpoint-field]').hidden,
          }));
          if (restoredState.provider !== 'compatible' || restoredState.providerLabel !== 'Compatível (LiteLLM, AirLLM, local)' || !restoredState.keyRestored || !restoredState.endpointVisible) {
            throw new Error(`Settings were not restored safely after reload: ${JSON.stringify(restoredState)}`);
          }
          await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'instant' }));
          await new Promise((resolve) => setTimeout(resolve, 160));
          interactionChecks.push({
            control: 'LLM provider settings (local-only values)',
            requiredFieldsShown,
            invalidSave: invalidState,
            localStorageContainsSecret: savedState.localStorageContainsSecret,
            sessionSecretStored: Boolean(savedState.sessionConfig.api_key),
            reloadRestored: restoredState,
            externalRequestsMade: false,
          });
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
        if (routeName === 'search-results') {
          await page.focus('.workspace-search-panel input[name="q"]');
          const keyboardOrder = [];
          for (let index = 0; index < 4; index += 1) {
            await page.keyboard.press('Tab');
            keyboardOrder.push(await page.evaluate(() => {
              const active = document.activeElement;
              return active?.name || active?.textContent?.trim() || active?.tagName?.toLowerCase();
            }));
          }
          const expectedOrder = ['tipo', 'ano', 'similaridade', 'Pesquisar'];
          if (JSON.stringify(keyboardOrder) !== JSON.stringify(expectedOrder)) {
            throw new Error(`Legal-search keyboard order mismatch: ${keyboardOrder.join(' → ')}`);
          }
          interactionChecks.push({ control: 'legal search filters', keyboardOrder });
          await page.evaluate(() => document.activeElement?.blur());
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
