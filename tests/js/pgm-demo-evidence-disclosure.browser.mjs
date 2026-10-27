import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import puppeteer from 'puppeteer-core';

const baseUrl = process.env.JURIX_BASE_URL || '';
const requestedEvidenceDir = process.env.JURIX_EVIDENCE_DIR || '';
const executablePath = process.env.PUPPETEER_EXECUTABLE_PATH
  || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const base = new URL(baseUrl);
assert.equal(base.protocol, 'http:');
assert.ok(['127.0.0.1', 'localhost'].includes(base.hostname));
assert.equal(base.port, '8287', 'this smoke is restricted to the isolated QA web service :8287');

const tempRoot = await fs.realpath(os.tmpdir());
await fs.access(executablePath);
await fs.mkdir(requestedEvidenceDir, { recursive: true });
const evidenceDir = await fs.realpath(requestedEvidenceDir);
assert.ok(
  evidenceDir.toLowerCase().startsWith(`${tempRoot.toLowerCase()}${path.sep}`),
  'browser evidence must remain under the temporary QA root',
);

const browser = await puppeteer.launch({ headless: true, executablePath });
try {
  const page = await browser.newPage({ viewport: { width: 360, height: 900 } });
  const pageErrors = [];
  page.on('pageerror', (error) => pageErrors.push(error.message));
  const observations = [];
  const route = new URL('/explorar/demo-consolidacao/', base).href;

  for (const width of [320, 360, 768, 1280, 1920]) {
    await page.setViewport({ width, height: 900 });
    const response = await page.goto(route, { waitUntil: 'domcontentloaded', timeout: 15000 });
    assert.equal(response?.status(), 200);

    const layout = await page.evaluate(() => ({
      viewport: document.documentElement.clientWidth,
      scrollWidth: document.documentElement.scrollWidth,
      namedTargets: document.querySelectorAll(
        '.pgm-demo__target-node[data-graph-relation-target="express"]',
      ).length,
      evidenceDisclosures: [...document.querySelectorAll('.pgm-demo__target-evidence')]
        .map((details) => ({
          open: details.open,
          label: details.querySelector('summary')?.getAttribute('aria-label') || '',
          summary: details.querySelector('summary')?.textContent.trim() || '',
        })),
      cssLoaded: [...document.styleSheets].some((sheet) =>
        sheet.href?.includes('jurix-pgm-demo.css?v=20261018-compact-evidence1')),
    }));
    assert.equal(layout.viewport, width);
    assert.equal(layout.scrollWidth, width, `horizontal overflow at ${width}px`);
    assert.ok(layout.namedTargets > 0);
    assert.equal(layout.evidenceDisclosures.length, layout.namedTargets);
    assert.ok(layout.evidenceDisclosures.every((item) => !item.open));
    assert.ok(layout.evidenceDisclosures.every((item) => item.label && item.summary));
    assert.equal(layout.cssLoaded, true);
    observations.push({ width, namedTargets: layout.namedTargets, evidenceDisclosures: layout.evidenceDisclosures.length });

    if (width !== 360) continue;

    await page.click('.pgm-demo__case-nav a[href="#pgm-ctm-change-set-title"]');
    const beforeAfterNavigation = await page.$eval('#pgm-ctm-change-set-title', (target) => {
      const disclosure = target.closest('details');
      return {
        disclosureOpen: Boolean(disclosure?.open),
        targetVisible: Boolean(target.getClientRects().length),
        targetTop: Math.round(target.getBoundingClientRect().top),
      };
    });
    assert.equal(beforeAfterNavigation.disclosureOpen, true);
    assert.equal(beforeAfterNavigation.targetVisible, true);
    assert.ok(beforeAfterNavigation.targetTop >= 0 && beforeAfterNavigation.targetTop < 900);
    observations.at(-1).beforeAfterNavigation = beforeAfterNavigation;
    await page.goto(route, { waitUntil: 'domcontentloaded', timeout: 15000 });

    const firstSummary = await page.$('.pgm-demo__target-evidence summary');
    await firstSummary.focus();
    await page.keyboard.press('Space');
    const disclosureOpened = await page.$eval('.pgm-demo__target-evidence', (details) => ({
      open: details.open,
      contentVisible: Boolean(details.querySelector('.pgm-demo__target-evidence-content')?.getClientRects().length),
      focusInside: details.contains(document.activeElement),
    }));
    assert.deepEqual(disclosureOpened, { open: true, contentVisible: true, focusInside: true });
    await page.screenshot({
      path: path.join(evidenceDir, 'graph-mobile-evidence-open.png'),
      fullPage: false,
    });
    await page.keyboard.press('Space');
    assert.equal(await page.$eval('.pgm-demo__target-evidence', (details) => details.open), false);

    const saplDetails = await page.$('.pgm-demo__sapl-evidence');
    await saplDetails.$eval('summary', (summary) => summary.click());
    const saplDisclosure = await saplDetails.evaluate((details) => ({
      open: details.open,
      links: [...details.querySelectorAll('a')]
        .filter((link) => link.getClientRects().length > 0)
        .map((link) => ({ href: link.href, text: link.textContent.trim() })),
    }));
    assert.equal(saplDisclosure.open, true);
    assert.ok(saplDisclosure.links.length > 0, 'SAPL details should expose an official record link');

    await page.click('[data-graph-filter="express"]');
    assert.equal(await page.$eval('[data-graph-filter="express"]', (button) => button.getAttribute('aria-pressed')), 'true');
    observations.at(-1).keyboardDisclosure = disclosureOpened;
    observations.at(-1).saplLinks = saplDisclosure.links.length;
  }

  assert.deepEqual(pageErrors, []);
  console.log(JSON.stringify({ route, observations, pageErrors, status: 'passed' }, null, 2));
} finally {
  await browser.close();
}
