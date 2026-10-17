import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import puppeteer from 'puppeteer-core';

const baseUrl = process.env.JURIX_QA_BASE_URL;
const reviewerPassword = process.env.JURIX_QA_REVIEWER_PASSWORD;
const reviewerUsername = process.env.JURIX_QA_REVIEWER_USERNAME;
const qaRoot = process.env.JURIX_QA_ROOT;
const browserPaths = [
  process.env.PUPPETEER_EXECUTABLE_PATH,
  process.env.CHROME_BIN,
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
].filter(Boolean);
const executablePath = browserPaths.find((candidate) => fs.existsSync(candidate));

function isPathInsideDirectory(candidatePath, rootPath) {
  const rootStat = fs.statSync(rootPath, { bigint: true });
  let currentPath = fs.realpathSync(candidatePath);
  while (true) {
    const currentStat = fs.statSync(currentPath, { bigint: true });
    if (currentStat.dev === rootStat.dev && currentStat.ino === rootStat.ino) return true;
    const parentPath = path.dirname(currentPath);
    if (parentPath === currentPath) return false;
    currentPath = parentPath;
  }
}

function requireEnvironment() {
  if (!baseUrl || !reviewerPassword || !reviewerUsername || !qaRoot || !executablePath) {
    throw new Error('The isolated QA URL, reviewer credential, TEMP root and browser are required.');
  }
  if (!/^jurix-pgm-preview-[0-9a-f]{8}$/.test(reviewerUsername)) {
    throw new Error('The browser smoke accepts only a temporary, scoped QA reviewer account.');
  }
  const parsed = new URL(baseUrl);
  if (parsed.protocol !== 'http:' || parsed.hostname !== '127.0.0.1' || parsed.port !== '8287') {
    throw new Error('This smoke is restricted to the dedicated local QA web on port 8287.');
  }
  const resolvedRoot = fs.realpathSync(path.resolve(qaRoot));
  if (!isPathInsideDirectory(resolvedRoot, os.tmpdir())
    || fs.statSync(resolvedRoot).ino === fs.statSync(os.tmpdir()).ino) {
    throw new Error('QA evidence must remain inside the system temporary directory.');
  }
  return { parsed, resolvedRoot };
}

async function main() {
  const { parsed, resolvedRoot } = requireEnvironment();
  const evidenceDir = path.join(resolvedRoot, `foundation-check-browser-${Date.now()}`);
  if (fs.existsSync(evidenceDir)) throw new Error('Refusing to overwrite prior browser evidence.');
  fs.mkdirSync(evidenceDir, { recursive: true });

  const browser = await puppeteer.launch({
    executablePath,
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'],
  });
  const page = await browser.newPage();
  const pageErrors = [];
  const report = {
    status: 'failed',
    scenario: 'public_hypothetical_lc258_lc55',
    corpus_kind: 'authentic_local_archive_candidates_pending_review',
    synthetic_reviewer: true,
    private_text_persisted: false,
    detected_reference_count: 0,
    detected_reference_labels: [],
    comparison_statuses: [],
    local_pdf_link_count: 0,
    relation_candidate_count: 0,
    act_scope_caveat_visible: false,
    amendment_preview_visible: false,
    amendment_source_link_count: 0,
    amendment_pending_disclosure_visible: false,
    reflow_by_width: [],
    opened_pdf_http_status: null,
    opened_pdf_content_type: null,
    foundation_http_statuses: [],
    foundation_redirects: [],
    final_job_status: null,
    final_progress_message: null,
    final_visible_alert_count: 0,
    privacy_copy_visible: false,
    status_updates: [],
    result_fetches: [],
    page_errors: pageErrors,
  };

  try {
    await page.setViewport({ width: 1440, height: 1200, deviceScaleFactor: 1 });
    await page.evaluateOnNewDocument(() => {
      window.__foundationSmokeDiagnostics = { statuses: [], resultFetches: [] };
      const originalFetch = window.fetch.bind(window);
      window.fetch = async (...args) => {
        const requestUrl = new URL(typeof args[0] === 'string' ? args[0] : args[0].url, location.href);
        try {
          const response = await originalFetch(...args);
          if (requestUrl.pathname.startsWith('/conferir/status/')) {
            const state = await response.clone().json().catch(() => ({}));
            window.__foundationSmokeDiagnostics.statuses.push(state.status || `http_${response.status}`);
          }
          if (requestUrl.pathname.startsWith('/conferir/resultado/')) {
            window.__foundationSmokeDiagnostics.resultFetches.push({
              status: response.status,
              ok: response.ok,
              finalPath: new URL(response.url).pathname.replace(/[0-9a-f-]{36}/gi, '{job}'),
            });
          }
          return response;
        } catch (error) {
          if (requestUrl.pathname.startsWith('/conferir/resultado/')) {
            window.__foundationSmokeDiagnostics.resultFetches.push({
              error: error.name || 'FetchError',
              message: String(error.message || '').replace(/https?:\/\/[^\s"']+/gi, '{url}')
                .replace(/[0-9a-f-]{36}/gi, '{job}').slice(0, 160),
            });
          }
          throw error;
        }
      };
    });
    page.on('pageerror', (error) => pageErrors.push(error.name || 'PageError'));
    page.on('response', (response) => {
      const responseUrl = new URL(response.url());
      if (responseUrl.pathname.startsWith('/conferir/')) {
        report.foundation_http_statuses.push({
          path: responseUrl.pathname.replace(/[0-9a-f-]{36}/gi, '{job}'),
          status: response.status(),
        });
        if (response.status() >= 300 && response.status() < 400) {
          const location = response.headers().location;
          if (location) {
            const target = new URL(location, response.url());
            report.foundation_redirects.push({
              same_origin: target.origin === responseUrl.origin,
              path: target.pathname.replace(/[0-9a-f-]{36}/gi, '{job}'),
              query_keys: [...target.searchParams.keys()].sort(),
            });
          }
        }
      }
    });

    const checkUrl = new URL('/conferir/', parsed).href;
    await page.goto(checkUrl, { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('#id_username', { timeout: 10000 });
    if (!new URL(page.url()).pathname.startsWith('/conta/entrar/')) {
      throw new Error('Anonymous access did not reach the protected-workspace login page.');
    }
    const loginCopy = await page.$eval('body', (node) => node.innerText);
    if (!loginCopy.includes('Acesse Conferir fundamentação') || !loginCopy.includes('conta autorizada')) {
      throw new Error('Protected-route explanation was not visible to the user.');
    }
    await page.screenshot({ path: path.join(evidenceDir, 'foundation-login.png'), fullPage: true });

    await page.type('#id_username', reviewerUsername);
    await page.type('#id_password', reviewerPassword);
    await Promise.all([
      page.waitForNavigation({ waitUntil: 'domcontentloaded' }),
      page.click('.workspace-login-form button[type="submit"]'),
    ]);
    if (new URL(page.url()).pathname !== '/conferir/') {
      throw new Error('QA reviewer login did not return to the requested foundation-check route.');
    }
    await page.waitForSelector('#foundation-text');
    const privacyCopy = await page.$eval('.foundation-caveat', (node) => node.innerText);
    report.privacy_copy_visible = privacyCopy.includes('O conteúdo integral não é salvo em conversa ou banco')
      && privacyCopy.includes('incluindo os trechos curtos das citações')
      && privacyCopy.includes('cache por até 15 minutos')
      && privacyCopy.includes('Não cole conteúdo reservado sem autorização institucional');
    if (!report.privacy_copy_visible) {
      throw new Error('The privacy notice does not describe temporary caching of detected citation snippets.');
    }
    await page.screenshot({ path: path.join(evidenceDir, 'foundation-empty.png'), fullPage: true });

    const hypotheticalText =
      'Em um caso hipotético, a fundamentação cita o Art. 21 da Lei Complementar nº 55/2004. ' +
      'A Lei Complementar nº 258/2024, Art. 260, inciso IV, consta como cláusula de revogação. ' +
      'Confira os dispositivos entre 1º de janeiro de 2004 e 31 de dezembro de 2024 e informe ' +
      'expressamente se a cobertura do acervo não permitir concluir.';
    await page.$eval('#foundation-text', (node, value) => {
      node.value = value;
      node.dispatchEvent(new Event('input', { bubbles: true }));
    }, hypotheticalText);
    await page.click('button[value="review"]');
    await page.waitForSelector('#detected-references-title', { timeout: 15000 });
    const references = await page.$$eval(
      '.foundation-reference__heading strong',
      (nodes) => nodes.map((node) => node.innerText.trim()),
    );
    report.detected_reference_count = references.length;
    report.detected_reference_labels = references;
    if (references.length < 2 || !references.some((item) => item.includes('55/2004'))
      || !references.some((item) => item.includes('258/2024'))) {
      throw new Error('The assessor review step did not identify both public-law references.');
    }
    await page.screenshot({ path: path.join(evidenceDir, 'foundation-references.png'), fullPage: true });

    await page.$eval('#foundation-from', (node) => {
      node.value = '2004-01-01';
      node.dispatchEvent(new Event('input', { bubbles: true }));
      node.dispatchEvent(new Event('change', { bubbles: true }));
    });
    await page.$eval('#foundation-to', (node) => {
      node.value = '2024-12-31';
      node.dispatchEvent(new Event('input', { bubbles: true }));
      node.dispatchEvent(new Event('change', { bubbles: true }));
    });
    await page.click('[data-foundation-compare]');
    try {
      await page.waitForFunction(() => (
        document.querySelector('[data-foundation-summary]')
        || window.__foundationSmokeDiagnostics?.resultFetches?.length
      ), { timeout: 30000 });
      if (!(await page.$('[data-foundation-summary]'))) {
        throw new Error('The result fetch failed before the summary could render.');
      }
    } catch (error) {
      const state = await page.$eval('#foundation-workspace', (root) => ({
        jobStatus: root.querySelector('[data-foundation-form]')?.dataset.jobStatus || null,
        progressMessage: root.querySelector('[data-foundation-progress]')?.innerText || '',
        visibleAlertCount: [...root.querySelectorAll('[role="alert"]')]
          .filter((node) => node.getClientRects().length > 0).length,
      }));
      report.final_job_status = state.jobStatus;
      report.final_progress_message = state.progressMessage.slice(0, 180);
      report.final_visible_alert_count = state.visibleAlertCount;
      const diagnostics = await page.evaluate(() => window.__foundationSmokeDiagnostics || {});
      report.status_updates = diagnostics.statuses || [];
      report.result_fetches = diagnostics.resultFetches || [];
      await page.screenshot({ path: path.join(evidenceDir, 'foundation-comparison-timeout.png'), fullPage: true });
      throw new Error(`Comparison did not render within the wait limit (job=${state.jobStatus || 'unknown'}).`);
    }
    const resultText = await page.$eval('[data-foundation-summary]', (node) => node.innerText);
    if (!resultText.includes('Resultado auxiliar') || !resultText.includes('Corte do corpus')) {
      throw new Error('The comparison result omitted its safety/corpus-scope disclosures.');
    }
    const relationPanel = await page.$(
      '[aria-label="Pistas documentais de alteração ou revogação"]',
    );
    if (relationPanel) {
      report.relation_candidate_count = await relationPanel.$$eval('li', (items) => items.length);
      const relationText = await relationPanel.evaluate((node) => node.innerText);
      report.act_scope_caveat_visible = relationText.includes('cita o ato como um todo')
        && relationText.includes('nem prova que todos os seus dispositivos foram atingidos')
        && relationText.includes('não determina se o dispositivo citado continua vigente');
    }
    if (!report.relation_candidate_count || !report.act_scope_caveat_visible) {
      throw new Error('The exact LC 55/2004 documentary clue or its non-operative scope caution was not rendered.');
    }
    report.comparison_statuses = await page.$$eval(
      '[data-foundation-summary] .foundation-pill',
      (nodes) => nodes.map((node) => node.dataset.status || 'unknown'),
    );
    const pdfLinks = await page.$$eval(
      '[data-foundation-summary] a[href*="/normas/documentos/"][href*="/pdf/"]',
      (nodes) => nodes.map((node) => node.href),
    );
    report.local_pdf_link_count = pdfLinks.length;
    await page.screenshot({ path: path.join(evidenceDir, 'foundation-comparison.png'), fullPage: true });

    if (pdfLinks.length) {
      const pdfPage = await browser.newPage();
      const response = await pdfPage.goto(pdfLinks[0], { waitUntil: 'domcontentloaded', timeout: 30000 });
      report.opened_pdf_http_status = response?.status() ?? null;
      report.opened_pdf_content_type = response?.headers()?.['content-type']?.split(';')[0] ?? null;
      if (report.opened_pdf_http_status !== 200
        || report.opened_pdf_content_type !== 'application/pdf') {
        throw new Error('A local source link did not open a PDF response in QA.');
      }
      await pdfPage.close();
    }

    await page.goto(checkUrl, { waitUntil: 'domcontentloaded' });
    const amendmentScenario =
      'A fundamentação cita o Art. 14 da Lei Complementar nº 208/2022. Compare com a redação indicada pela Lei Complementar nº 258/2024, Art. 261, entre 08/03/2022 e 27/12/2024.';
    await page.$eval('#foundation-text', (node, value) => {
      node.value = value;
      node.dispatchEvent(new Event('input', { bubbles: true }));
    }, amendmentScenario);
    await page.click('button[value="review"]');
    await page.waitForSelector('#detected-references-title', { timeout: 15000 });
    await page.$eval('#foundation-from', (node) => {
      node.value = '2022-03-08';
      node.dispatchEvent(new Event('input', { bubbles: true }));
      node.dispatchEvent(new Event('change', { bubbles: true }));
    });
    await page.$eval('#foundation-to', (node) => {
      node.value = '2024-12-27';
      node.dispatchEvent(new Event('input', { bubbles: true }));
      node.dispatchEvent(new Event('change', { bubbles: true }));
    });
    await page.click('[data-foundation-compare]');
    await page.waitForSelector('[data-foundation-summary]', { timeout: 30000 });
    const amendmentPreview = await page.$('.foundation-amendment-preview');
    if (amendmentPreview) {
      const previewText = await amendmentPreview.evaluate((node) => node.textContent);
      report.amendment_preview_visible = previewText.includes('Texto extraído da fonte anterior')
        && previewText.includes('Trecho extraído do ato modificador');
      report.amendment_source_link_count = await amendmentPreview.$$eval(
        'a[href*=".pdf"], a[href*="/normas/documentos/"][href*="/pdf/"]',
        (items) => items.length,
      );
      report.amendment_pending_disclosure_visible = previewText.includes('extrações pendentes')
        && previewText.includes('não aprova identidade, redação, eficácia ou vigência');
      await amendmentPreview.$eval('summary', (node) => node.click());
      const expandedText = await amendmentPreview.evaluate((node) => node.innerText);
      report.amendment_preview_visible = report.amendment_preview_visible
        && expandedText.includes('Texto extraído da fonte anterior')
        && expandedText.includes('Trecho extraído do ato modificador')
        && expandedText.includes('Art. 14');
    }
    await page.screenshot({
      path: path.join(evidenceDir, 'foundation-amendment-comparison.png'),
      fullPage: true,
    });
    if (!report.amendment_preview_visible || report.amendment_source_link_count !== 2
      || !report.amendment_pending_disclosure_visible) {
      throw new Error('The LC 208/2022 Art. 14 candidate comparison did not render both source PDFs and pending-status caveats.');
    }

    for (const width of [320, 360, 390, 768]) {
      await page.setViewport({ width, height: 900, deviceScaleFactor: 1 });
      const dimensions = await page.evaluate(() => ({
        viewport: window.innerWidth,
        document: document.documentElement.scrollWidth,
        body: document.body.scrollWidth,
      }));
      report.reflow_by_width.push({ width, ...dimensions });
      if (dimensions.document > width || dimensions.body > width) {
        throw new Error(`Foundation comparison overflows at ${width}px.`);
      }
      if (width === 390) {
        await page.screenshot({
          path: path.join(evidenceDir, 'foundation-amendment-mobile.png'),
          fullPage: true,
        });
      }
    }

    if (pageErrors.length) throw new Error('Browser reported an unhandled page error.');
    report.status = 'passed';
  } finally {
    await browser.close();
    fs.writeFileSync(
      path.join(evidenceDir, 'foundation-check-smoke.json'),
      JSON.stringify(report, null, 2),
      { flag: 'wx' },
    );
  }

  process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
}

main().catch((error) => {
  process.stderr.write(`${error.name}: ${error.message}\n`);
  process.exitCode = 1;
});
