import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import puppeteer from 'puppeteer-core';
import { test } from 'node:test';
import assert from 'node:assert/strict';

const executablePath = [
  process.env.PUPPETEER_EXECUTABLE_PATH,
  process.env.CHROME_BIN,
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
].filter(Boolean).find((candidate) => fs.existsSync(candidate));
const baseUrl = process.env.JURIX_QA_BASE_URL;
const reviewerPassword = process.env.JURIX_QA_REVIEWER_PASSWORD;
const qaRoot = process.env.JURIX_QA_ROOT;
const fixtureMapPath = process.env.JURIX_QA_FIXTURE_MAP;
const shouldRun = Boolean(baseUrl && reviewerPassword && qaRoot && fixtureMapPath);

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

async function deleteR20QaCollections(page, parsedBase) {
  await page.goto(new URL('/admin/legislation/collection/', parsedBase).href, {
    waitUntil: 'domcontentloaded',
  });
  const collectionIds = await page.$$eval('#result_list tbody tr', (rows) => rows
    .filter((row) => row.innerText.includes('R20 QA isolation '))
    .map((row) => row.querySelector('th a')?.getAttribute('href') ?? '')
    .map((href) => href.match(/\/admin\/legislation\/collection\/(\d+)\/change\//)?.[1])
    .filter(Boolean));
  for (const collectionId of collectionIds) {
    await page.goto(
      new URL(`/admin/legislation/collection/${collectionId}/delete/`, parsedBase).href,
      { waitUntil: 'domcontentloaded' },
    );
    await Promise.all([
      page.waitForNavigation({ waitUntil: 'domcontentloaded' }),
      page.click('input[type="submit"]'),
    ]);
  }
}

test('QA browser: workspace sign-in, collection persistence and owner isolation', {
  skip: shouldRun ? false : 'Requires an explicit isolated QA URL/root and temporary reviewer credential.',
}, async () => {
  assert.ok(executablePath, 'A local Chrome or Edge executable is required.');
  const parsedBase = new URL(baseUrl);
  assert.equal(parsedBase.protocol, 'http:');
  assert.equal(parsedBase.hostname, '127.0.0.1');
  assert.ok(['8007', '8009', '8010', '8011', '8015', '8023', '8024'].includes(parsedBase.port));
  assert.ok(isPathInsideDirectory(fixtureMapPath, qaRoot));
  const fixtureMap = JSON.parse(fs.readFileSync(fs.realpathSync(fixtureMapPath), 'utf8'));
  assert.equal(fixtureMap.dataset, 'synthetic_not_gold');
  assert.equal(fixtureMap.collection_fixture?.synthetic_only, true);
  assert.equal(fixtureMap.collection_fixture?.not_legal_gold, true);
  const collectionNormaId = fixtureMap.collection_fixture?.norma_id;
  assert.ok(Number.isInteger(collectionNormaId));

  const browser = await puppeteer.launch({
    executablePath,
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'],
  });
  const observerUsername = `jurix-qa-observer-${crypto.randomBytes(5).toString('hex')}`;
  const observerPassword = crypto.randomBytes(32).toString('base64url');
  const collectionName = `R20 QA isolation ${crypto.randomBytes(4).toString('hex')}`;
  const evidenceDir = fs.mkdtempSync(path.join(path.resolve(qaRoot), 'r20-collections-'));
  let observerId;
  let page;
  try {
    page = await browser.newPage();
    await page.setViewport({ width: 1280, height: 900 });
    const loginUrl = new URL('/conta/entrar/?next=%2Fcolecoes%2F', parsedBase).href;
    await page.goto(loginUrl, { waitUntil: 'domcontentloaded' });
    await page.type('#id_username', 'jurix-qa-reviewer');
    await page.type('#id_password', reviewerPassword);
    await Promise.all([
      page.waitForNavigation({ waitUntil: 'domcontentloaded' }),
      page.click('.workspace-login-form button[type="submit"]'),
    ]);
    assert.equal(new URL(page.url()).pathname, '/colecoes/');
    assert.ok(await page.$('[data-open-collection-form]'));

    await deleteR20QaCollections(page, parsedBase);
    await page.goto(new URL('/admin/auth/user/', parsedBase).href, { waitUntil: 'domcontentloaded' });
    const priorObserverIds = await page.$$eval('#result_list tbody tr', (rows) => rows
      .filter((row) => row.innerText.includes('jurix-qa-observer-'))
      .map((row) => row.querySelector('th a')?.getAttribute('href') ?? '')
      .map((href) => href.match(/\/admin\/auth\/user\/(\d+)\/change\//)?.[1])
      .filter(Boolean));
    for (const priorObserverId of priorObserverIds) {
      await page.goto(
        new URL(`/admin/auth/user/${priorObserverId}/change/`, parsedBase).href,
        { waitUntil: 'domcontentloaded' },
      );
      const priorActive = await page.$eval('#id_is_active', (field) => field.checked);
      if (priorActive) await page.click('#id_is_active');
      await Promise.all([
        page.waitForNavigation({ waitUntil: 'domcontentloaded' }),
        page.click('input[name="_save"]'),
      ]);
    }

    await page.goto(new URL('/admin/auth/user/add/', parsedBase).href, { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('#id_password1');
    await page.type('#id_username', observerUsername);
    await page.type('#id_password1', observerPassword);
    await page.type('#id_password2', observerPassword);
    await Promise.all([
      page.waitForNavigation({ waitUntil: 'domcontentloaded' }),
      page.click('input[name="_save"]'),
    ]);
    observerId = new URL(page.url()).pathname.match(/\/admin\/auth\/user\/(\d+)\/change\//)?.[1];
    assert.ok(observerId, 'Temporary observer should be visible in the QA user list.');

    await page.goto(new URL('/colecoes/', parsedBase).href, { waitUntil: 'domcontentloaded' });
    await page.click('[data-open-collection-form]');
    await page.type('#collection-name', collectionName);
    await page.type('#collection-description', 'Coleção sintética para verificar isolamento entre contas.');
    await Promise.all([
      page.waitForNavigation({ waitUntil: 'domcontentloaded' }),
      page.click('[data-collection-dialog] button[type="submit"]'),
    ]);
    assert.match(await page.$eval('#main-content', (node) => node.innerText), new RegExp(collectionName));
    const collectionHref = await page.$eval(
      `[aria-label="Suas coleções"] a[href^="/colecoes/"]`,
      (node) => node.getAttribute('href'),
    );
    const collectionId = collectionHref.match(/^\/colecoes\/(\d+)\/$/)?.[1];
    assert.ok(collectionId, 'Owner should receive a persisted collection URL.');
    await page.goto(new URL(`/normas/${collectionNormaId}/`, parsedBase).href, {
      waitUntil: 'domcontentloaded',
    });
    assert.ok(await page.$('[data-collection-form]'), 'Consolidated synthetic norma should offer saving to a collection.');
    await Promise.all([
      page.waitForNavigation({ waitUntil: 'domcontentloaded' }),
      page.click('[data-collection-form] button[type="submit"]'),
    ]);
    assert.equal(new URL(page.url()).pathname, collectionHref);
    assert.match(await page.$eval('#main-content', (node) => node.innerText), /Lei nº 9917\/2090/);
    assert.match(await page.$eval('#main-content', (node) => node.innerText), /1 norma/);
    await page.screenshot({ path: path.join(evidenceDir, 'r20-owner-collection.png'), fullPage: true });

    await page.click('button[aria-label="Sair da conta"]');
    await page.waitForNavigation({ waitUntil: 'domcontentloaded' });
    await page.goto(new URL('/conta/entrar/?next=%2Fcolecoes%2F', parsedBase).href, { waitUntil: 'domcontentloaded' });
    await page.type('#id_username', observerUsername);
    await page.type('#id_password', observerPassword);
    await Promise.all([
      page.waitForNavigation({ waitUntil: 'domcontentloaded' }),
      page.click('.workspace-login-form button[type="submit"]'),
    ]);
    const otherUserText = await page.$eval('#main-content', (node) => node.innerText);
    assert.match(otherUserText, /Crie seu primeiro dossiê jurídico/);
    assert.doesNotMatch(otherUserText, new RegExp(collectionName));
    const forbiddenCollection = await page.goto(
      new URL(`/colecoes/${collectionId}/`, parsedBase).href,
      { waitUntil: 'domcontentloaded' },
    );
    assert.equal(forbiddenCollection.status(), 404);
    await page.screenshot({ path: path.join(evidenceDir, 'r20-other-user-empty.png'), fullPage: true });
  } finally {
    if (observerId) {
      try {
        const cleanupContext = await browser.createBrowserContext();
        const cleanupPage = await cleanupContext.newPage();
        await cleanupPage.setViewport({ width: 1280, height: 900 });
        await cleanupPage.goto(
          new URL('/conta/entrar/?next=%2Fadmin%2F', parsedBase).href,
          { waitUntil: 'domcontentloaded' },
        );
        await cleanupPage.type('#id_username', 'jurix-qa-reviewer');
        await cleanupPage.type('#id_password', reviewerPassword);
        await Promise.all([
          cleanupPage.waitForNavigation({ waitUntil: 'domcontentloaded' }),
          cleanupPage.click('.workspace-login-form button[type="submit"]'),
        ]);
        await cleanupPage.goto(
          new URL(`/admin/auth/user/${observerId}/change/`, parsedBase).href,
          { waitUntil: 'domcontentloaded' },
        );
        const active = await cleanupPage.$eval('#id_is_active', (field) => field.checked);
        if (active) await cleanupPage.click('#id_is_active');
        await Promise.all([
          cleanupPage.waitForNavigation({ waitUntil: 'domcontentloaded' }),
          cleanupPage.click('input[name="_save"]'),
        ]);
        await deleteR20QaCollections(cleanupPage, parsedBase);
        await cleanupContext.close();
      } catch (error) {
        console.error(`QA observer deactivation failed: ${error.message}`);
      }
    }
    await browser.close();
  }
});
