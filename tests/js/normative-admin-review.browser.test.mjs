import fs from 'node:fs';
import path from 'node:path';
import puppeteer from 'puppeteer-core';
import { test } from 'node:test';
import assert from 'node:assert/strict';

const browserPaths = [
  process.env.PUPPETEER_EXECUTABLE_PATH,
  process.env.CHROME_BIN,
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
].filter(Boolean);
const executablePath = browserPaths.find((candidate) => fs.existsSync(candidate));
const baseUrl = process.env.JURIX_QA_BASE_URL;
const reviewerPassword = process.env.JURIX_QA_REVIEWER_PASSWORD;
const fixtureMapPath = process.env.JURIX_QA_FIXTURE_MAP;
const qaRoot = process.env.JURIX_QA_ROOT;
const shouldRun = Boolean(baseUrl && reviewerPassword && fixtureMapPath && qaRoot);

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

test('QA browser: authenticated reviewer can confirm then reject a synthetic event', {
  skip: shouldRun ? false : 'Requires explicit isolated QA URL, fixture map, root and temporary reviewer credential.',
}, async () => {
  assert.ok(executablePath, 'A local Chrome or Edge executable is required.');
  const parsedBase = new URL(baseUrl);
  assert.equal(parsedBase.protocol, 'http:');
  assert.equal(parsedBase.hostname, '127.0.0.1');
  assert.ok(['8007', '8009', '8010', '8011', '8015', '8022', '8023', '8024'].includes(parsedBase.port));
  assert.ok(isPathInsideDirectory(fixtureMapPath, qaRoot), 'Fixture map must stay inside QA root.');
  const resolvedMap = fs.realpathSync(fixtureMapPath);
  const fixtureMap = JSON.parse(fs.readFileSync(resolvedMap, 'utf8'));
  assert.equal(fixtureMap.dataset, 'synthetic_not_gold');
  const eventId = fixtureMap.edge_case_fixtures?.events?.admin_review_smoke;
  assert.ok(Number.isInteger(eventId), 'Seed map must provide the dedicated synthetic review event.');
  const reviewUrl = new URL(`/admin/legislation/eventoalteracao/${eventId}/review/`, parsedBase).href;

  const browser = await puppeteer.launch({
    executablePath,
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'],
  });
  try {
    const page = await browser.newPage();
    await page.goto(reviewUrl, { waitUntil: 'domcontentloaded' });
    assert.match(new URL(page.url()).pathname, /^\/admin\/login\/?$/);

    const loginUrl = new URL('/admin/login/?next=/admin/', parsedBase).href;
    await page.goto(loginUrl, { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('#id_username');
    await page.type('#id_username', 'jurix-qa-reviewer');
    await page.type('#id_password', reviewerPassword);
    await Promise.all([
      page.waitForNavigation({ waitUntil: 'domcontentloaded' }),
      page.click('input[type="submit"]'),
    ]);
    assert.match(new URL(page.url()).pathname, /^\/admin\/?$/);

    await page.goto(reviewUrl, { waitUntil: 'domcontentloaded' });
    const pendingText = await page.$eval('#content-main', (node) => node.innerText);
    assert.match(pendingText, /Estado atual:\s*(?:pending|rejected)/);
    assert.match(pendingText, /Art\. 2º da Lei 9911\/2090/);
    assert.ok(await page.$eval('#id_target_norma_id', (field) => Boolean(field.value)));
    assert.equal(await page.$eval('#id_decision', (field) => field.value), 'approve');

    await page.select('#id_decision', 'approve');
    await page.type('#id_reason', '[QA SINTÉTICO] Revisão e2e de aprovação em ambiente isolado.');
    await Promise.all([
      page.waitForNavigation({ waitUntil: 'domcontentloaded' }),
      page.click('input[type="submit"]'),
    ]);
    const approvalPath = new URL(page.url()).pathname;
    const approvalPageText = await page.$eval('#content-main', (node) => node.innerText);
    assert.match(
      approvalPath,
      new RegExp(`/admin/legislation/eventoalteracao/${eventId}/change/`),
      `Approval was not recorded. Review page: ${approvalPageText}`,
    );
    assert.match(await page.$eval('#content', (node) => node.innerText), /Confirmada por revisor/);

    await page.goto(reviewUrl, { waitUntil: 'domcontentloaded' });
    await page.select('#id_decision', 'reject');
    await page.type('#id_reason', '[QA SINTÉTICO] Revisão e2e de rejeição após aprovação.');
    await Promise.all([
      page.waitForNavigation({ waitUntil: 'domcontentloaded' }),
      page.click('input[type="submit"]'),
    ]);
    const rejectedPageText = await page.$eval('#content', (node) => node.innerText);
    assert.match(rejectedPageText, /Rejeitada por revisor/);
    assert.match(rejectedPageText, /Art\. 2º da Lei 9911\/2090/);
  } finally {
    await browser.close();
  }
});

test('QA browser: normative work-item review resumes only the isolated queue', {
  skip: shouldRun && process.env.JURIX_QA_WORK_ITEM_ID
    ? false
    : 'Requires the isolated QA reviewer, browser inputs and an explicitly selected QA work-item ID.',
}, async () => {
  assert.ok(executablePath, 'A local Chrome or Edge executable is required.');
  const parsedBase = new URL(baseUrl);
  assert.equal(parsedBase.protocol, 'http:');
  assert.equal(parsedBase.hostname, '127.0.0.1');
  assert.ok(['8022', '8024'].includes(parsedBase.port));
  const itemId = Number(process.env.JURIX_QA_WORK_ITEM_ID);
  assert.ok(Number.isSafeInteger(itemId) && itemId > 0);
  const reviewUrl = new URL(`/admin/operations/normativeworkitem/${itemId}/review/`, parsedBase).href;
  const queueUrl = new URL('/admin/operations/normativeworkitem/', parsedBase).href;
  const browser = await puppeteer.launch({
    executablePath,
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'],
  });
  try {
    const page = await browser.newPage();
    await page.goto(queueUrl, { waitUntil: 'domcontentloaded' });
    if (/^\/admin\/login\/?$/.test(new URL(page.url()).pathname)) {
      await page.waitForSelector('#id_username');
      await page.type('#id_username', 'jurix-qa-reviewer');
      await page.type('#id_password', reviewerPassword);
      await Promise.all([
        page.waitForNavigation({ waitUntil: 'domcontentloaded' }),
        page.click('input[type="submit"]'),
      ]);
    }
    await page.goto(queueUrl, { waitUntil: 'domcontentloaded' });
    const queueText = await page.$eval('#content', (node) => node.innerText);
    assert.match(queueText, new RegExp(`\\b${itemId}\\b`));
    const reviewLink = await page.$(`a[href="/admin/operations/normativeworkitem/${itemId}/review/"]`);
    assert.ok(reviewLink, 'Awaiting-review work item must have a visible review action.');
    await reviewLink.click();
    await page.waitForSelector('#id_decision');
    const reviewText = await page.$eval('#content-main', (node) => node.innerText);
    assert.match(reviewText, /não substitui a revisão jurídica/i);
    assert.equal(await page.$eval('#id_decision', (field) => field.value), 'approve');
    await page.type('#id_reason', '[QA SINTÉTICO] Aprovação operacional para exercitar a fila isolada.');
    await Promise.all([
      page.waitForNavigation({ waitUntil: 'domcontentloaded' }),
      page.click('input[type="submit"]'),
    ]);
    assert.match(
      new URL(page.url()).pathname,
      new RegExp(`/admin/operations/normativeworkitem/${itemId}/change/`),
    );
    const updatedItemText = await page.$eval('#content', (node) => node.innerText);
    assert.match(updatedItemText, /human_review.*approved/i);
    assert.match(updatedItemText, /(?:Pendente|Em execução|Concluída|Falha)/);
  } finally {
    await browser.close();
  }
});
