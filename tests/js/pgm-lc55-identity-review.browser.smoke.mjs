import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import puppeteer from 'puppeteer-core';

const baseUrl = process.env.JURIX_QA_BASE_URL;
const username = process.env.JURIX_QA_REVIEWER_USERNAME;
const password = process.env.JURIX_QA_REVIEWER_PASSWORD;
const qaRoot = process.env.JURIX_QA_ROOT;
const documentId = '80752f21-67b5-4190-8109-e7cfa30f1551';
const executablePath = [
  process.env.PUPPETEER_EXECUTABLE_PATH,
  process.env.CHROME_BIN,
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
].find((candidate) => candidate && fs.existsSync(candidate));

function validateEnvironment() {
  if (!baseUrl || !username || !password || !qaRoot || !executablePath) {
    throw new Error('QA URL, temporary reviewer, temporary evidence path and browser are required.');
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
  const evidenceDir = path.join(root, `lc55-identity-review-${Date.now()}`);
  fs.mkdirSync(evidenceDir, { recursive: false });
  const browser = await puppeteer.launch({
    executablePath,
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'],
  });
  const page = await browser.newPage();
  const pageErrors = [];
  const report = {
    scenario: 'real_lc55_pending_identity_review_form',
    document_public_id: documentId,
    status: 'failed',
    form_visible: false,
    submit_clicked: false,
    page_errors: pageErrors,
    screenshot: path.join(evidenceDir, 'lc55-identity-review-form.png'),
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
      throw new Error('Temporary reviewer did not return to the LC 55 candidate.');
    }
    const state = await page.evaluate(() => {
      const section = document.querySelector('section[aria-labelledby="document-review-title"]');
      const panel = section?.querySelector('form[data-document-review-form]');
      const button = panel?.querySelector('[data-document-review-submit]');
      return {
        heading: document.querySelector('#document-review-title')?.innerText || '',
        action: panel?.querySelector('input[name="action"]')?.value || '',
        candidateLabel: panel?.querySelector('.document-review-identity')?.innerText || '',
        hasIdentityConfirmation: Boolean(panel?.querySelector('input[name="confirm_identity"]')),
        hasUseCondition: Boolean(panel?.querySelector('select[name="confirmed_condition_of_use"]')),
        useConditionValue: panel?.querySelector('select[name="confirmed_condition_of_use"]')?.value || '',
        hasReason: Boolean(panel?.querySelector('textarea[name="reason"]')),
        submitLabel: button?.innerText.trim() || '',
        caution: section?.innerText.includes('não aprova a extração') || false,
        acceptedTextActionVisible: Boolean(document.querySelector('input[name="action"][value="accept_extraction"]')),
      };
    });
    report.form_visible = Boolean(state.action === 'review_identity'
      && state.hasIdentityConfirmation && state.hasUseCondition && state.hasReason);
    report.document_use_basis_starts_unselected = state.useConditionValue === '';
    report.submit_label = state.submitLabel;
    report.pending_identity_label = state.candidateLabel;
    report.identity_action_separate_from_text_acceptance = !state.acceptedTextActionVisible;
    report.caution_visible = state.caution;
    await page.$eval(
      'section[aria-labelledby="document-review-title"]',
      (node) => node.scrollIntoView({ block: 'center' }),
    );
    await page.screenshot({ path: report.screenshot });
    if (!report.form_visible || !state.heading.includes('identidade normativa')
      || !state.candidateLabel.includes('55/2004')
      || !state.submitLabel.includes('Registrar identidade pendente')
      || !state.caution || state.useConditionValue !== '' || state.acceptedTextActionVisible) {
      throw new Error(`Identity-review form did not meet expectations: ${JSON.stringify(report)}`);
    }
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
