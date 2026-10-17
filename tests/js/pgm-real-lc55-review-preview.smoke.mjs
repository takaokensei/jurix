import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import puppeteer from 'puppeteer-core';

const baseUrl = process.env.JURIX_QA_BASE_URL;
const username = process.env.JURIX_QA_REVIEWER_USERNAME;
const password = process.env.JURIX_QA_REVIEWER_PASSWORD;
const qaRoot = process.env.JURIX_QA_ROOT;
const documentId = '80752f21-67b5-4190-8109-e7cfa30f1551';
const extractionId = 7142;
const executablePath = [
  process.env.PUPPETEER_EXECUTABLE_PATH,
  process.env.CHROME_BIN,
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
].find((candidate) => candidate && fs.existsSync(candidate));

function validateEnvironment() {
  if (!baseUrl || !username || !password || !qaRoot || !executablePath) {
    throw new Error('QA URL, temporary read-only reviewer, temp evidence path and browser are required.');
  }
  if (!/^jurix-pgm-preview-[0-9a-f]{8}$/.test(username)) {
    throw new Error('Reviewer username is outside the temporary QA pattern.');
  }
  const parsed = new URL(baseUrl);
  if (parsed.protocol !== 'http:' || parsed.hostname !== '127.0.0.1' || parsed.port !== '8287') {
    throw new Error('This smoke is restricted to the isolated local QA server on port 8287.');
  }
  const root = fs.realpathSync(path.resolve(qaRoot));
  const temp = fs.realpathSync(os.tmpdir());
  if (!root.toLowerCase().startsWith(`${temp.toLowerCase()}${path.sep.toLowerCase()}`)) {
    throw new Error('Evidence must be written under the system temporary directory.');
  }
  return { parsed, root };
}

async function main() {
  const { parsed, root } = validateEnvironment();
  const evidenceDir = path.join(root, `lc55-review-preview-${Date.now()}`);
  fs.mkdirSync(evidenceDir, { recursive: false });
  const browser = await puppeteer.launch({
    executablePath,
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'],
  });
  const page = await browser.newPage();
  const pageErrors = [];
  const report = {
    scenario: 'real_promulgated_lc55_original_candidate_preview',
    document_public_id: documentId,
    extraction_id: extractionId,
    status: 'failed',
    article_count: 0,
    device_count: 0,
    target_articles_visible: [],
    persisted_preview: false,
    page_errors: pageErrors,
    screenshot: path.join(evidenceDir, 'lc55-original-preview.png'),
  };

  try {
    await page.setViewport({ width: 1440, height: 1000, deviceScaleFactor: 1 });
    page.on('pageerror', (error) => pageErrors.push(error.name || 'PageError'));
    const evidencePath = `/normas/documentos/${documentId}/`;
    const loginUrl = new URL('/conta/entrar/', parsed);
    loginUrl.searchParams.set('next', evidencePath);
    await page.goto(loginUrl.href, { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('#id_username', { timeout: 10000 });
    await page.type('#id_username', username);
    await page.type('#id_password', password);
    await Promise.all([
      page.waitForNavigation({ waitUntil: 'domcontentloaded' }),
      page.click('.workspace-login-form button[type="submit"]'),
    ]);
    if (new URL(page.url()).pathname !== evidencePath) {
      throw new Error('Temporary read-only reviewer did not return to the candidate document.');
    }
    const before = await page.$eval('body', (node) => node.innerText);
    await page.screenshot({ path: path.join(evidenceDir, 'lc55-before-preview.png') });
    report.document_heading_visible = before.includes('55/2004');
    report.preview_controls_visible = before.includes('Calcular prévia temporária dos dispositivos');
    if (!before.includes('Segmentação dos dispositivos')
      || !before.includes('Calcular prévia temporária dos dispositivos')
      || !report.document_heading_visible) {
      throw new Error(`Candidate review controls missing at ${page.url()}: ${JSON.stringify(report)}`);
    }
    if (await page.$('input[name="action"][value="accept_extraction"]')) {
      throw new Error('Read-only reviewer was offered an extraction-acceptance action.');
    }
    await page.$eval('input[name="confirm_generation"]', (node) => { node.checked = true; });
    await Promise.all([
      page.waitForNavigation({ waitUntil: 'domcontentloaded' }),
      page.click('button[type="submit"][data-document-review-submit]'),
    ]);
    const previewText = await page.$eval(
      'section[aria-labelledby="segmentation-review-title"]',
      (node) => node.innerText,
    );
    if (!previewText.includes('Prévia exploratória, não persistida')) {
      throw new Error('The result did not explicitly identify itself as an ephemeral preview.');
    }
    const headings = await page.$$eval(
      '.document-segmentation-preview__item h3',
      (nodes) => nodes.map((node) => node.innerText.trim()),
    );
    report.device_count = headings.length;
    report.article_count = headings.filter((text) => /^artigo\s/i.test(text)).length;
    report.target_articles_visible = ['21', '34'].filter((number) => (
      headings.some((text) => new RegExp(`^artigo\\s+${number}(?:\\b|\\s)`, 'i').test(text))
    ));
    if (report.device_count !== 482 || report.article_count !== 179
      || report.target_articles_visible.length !== 2) {
      throw new Error('Preview device/article counts or targeted LC 55 articles diverged from expected extraction.');
    }
    await page.$$eval('.document-segmentation-preview__item h3', (nodes) => {
      const target = nodes.find((node) => /^artigo\s+21(?:\b|\s)/i.test(node.innerText.trim()));
      target?.scrollIntoView({ block: 'center' });
    });
    await page.screenshot({ path: report.screenshot });
    if (pageErrors.length) throw new Error('Browser reported a page error.');
    report.status = 'passed';
    console.log(JSON.stringify(report, null, 2));
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(`${error.name}: ${error.message}`);
  process.exitCode = 1;
});
