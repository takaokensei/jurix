import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import puppeteer from 'puppeteer-core';

const baseUrl = process.env.JURIX_QA_BASE_URL;
const reviewerPassword = process.env.JURIX_QA_REVIEWER_PASSWORD;
const reviewerUsername = process.env.JURIX_QA_REVIEWER_USERNAME;
const qaRoot = process.env.JURIX_QA_ROOT;
const candidates = {
  'lc208-2022': {
    documentId: 'be73504c-64c1-4ced-b430-319679f5af8a',
    extractionId: 7133,
    expectedArticles: ['14'],
  },
  'lc258-2024': {
    documentId: '00c841d2-4b08-42a3-80b1-f018b1e86d43',
    extractionId: 7141,
    expectedArticles: ['260', '261', '262', '266'],
    expectedCounts: { articles: 266, devices: 860 },
    verifyAnnexOcrBoundary: true,
  },
  'lc261-2025': {
    documentId: '396947b8-5153-43cc-83c9-59a7849bf761',
    extractionId: 7135,
    expectedArticles: ['117', '118'],
  },
  'lei4885-1997': {
    documentId: '4f246b2d-6c49-4c70-9014-5c255f969242',
    extractionId: 7146,
    expectedArticles: ['1'],
  },
  'lp562-2018': {
    documentId: 'a2334a00-772f-4b38-9153-c88ba13ebe5b',
    extractionId: 7138,
    expectedArticles: ['1', '13'],
    expectedCounts: { articles: 13 },
  },
  'ctm-3882-lc217': {
    documentId: '6838abb1-51e7-4d1f-b0d1-03d164fdb51a',
    extractionId: 7115,
    expectedArticles: ['1'],
  },
};
const candidateKey = process.env.JURIX_QA_CANDIDATE || 'lc258-2024';
const candidate = candidates[candidateKey];
if (!candidate) throw new Error('Candidate is not in the explicit promulgated-law QA allowlist.');
const { documentId } = candidate;
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
    throw new Error('The isolated QA URL, temporary reviewer, TEMP root and browser are required.');
  }
  if (!/^jurix-pgm-preview-[0-9a-f]{8}$/.test(reviewerUsername)) {
    throw new Error('Reviewer username is outside the isolated preview-account pattern.');
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
  const evidenceDir = path.join(resolvedRoot, `candidate-preview-${Date.now()}`);
  fs.mkdirSync(evidenceDir, { recursive: false });

  const browser = await puppeteer.launch({
    executablePath,
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'],
  });
  const page = await browser.newPage();
  const pageErrors = [];
  const report = {
    status: 'failed',
    scenario: `real_sapl_${candidateKey}_candidate_segmentation_preview`,
    document_public_id: documentId,
    reviewer_permissions: ['legislation.view_documentonormativo'],
    candidate_extraction_id: candidate.extractionId,
    expected_articles: candidate.expectedArticles,
    preview_target_article: candidate.expectedArticles[0],
    persisted_preview: false,
    article_count: 0,
    device_count: 0,
    key_articles_visible: [],
    page_errors: pageErrors,
  };

  try {
    await page.setViewport({ width: 1440, height: 1000, deviceScaleFactor: 1 });
    page.on('pageerror', (error) => pageErrors.push(error.name || 'PageError'));

    const evidencePath = `/normas/documentos/${documentId}/`;
    const loginUrl = new URL('/conta/entrar/', parsed);
    loginUrl.searchParams.set('next', evidencePath);
    await page.goto(loginUrl.href, { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('#id_username', { timeout: 10000 });
    await page.type('#id_username', reviewerUsername);
    await page.type('#id_password', reviewerPassword);
    await Promise.all([
      page.waitForNavigation({ waitUntil: 'domcontentloaded' }),
      page.click('.workspace-login-form button[type="submit"]'),
    ]);
    if (new URL(page.url()).pathname !== evidencePath) {
      throw new Error('The read-only reviewer did not return to the candidate evidence page.');
    }
    const initialText = await page.$eval('body', (node) => node.innerText);
    if (!initialText.includes('Segmentação dos dispositivos')
      || !initialText.includes('Prévia ainda não gerada')
      || !initialText.includes('Calcular prévia temporária dos dispositivos')) {
      throw new Error('The candidate preview controls were not available to the read-only reviewer.');
    }
    if (candidateKey === 'lc258-2024') {
      const pendingRelationCount = initialText.split('aguardando revisão humana').length - 1;
      if (!initialText.includes('Relações candidatas persistidas nesta extração')
        || !initialText.includes('Lei Promulgada nº 275/2009 · Art. 21 · pendente de conferência')
        || !initialText.includes('Lei Promulgada nº 562/2018 · pendente de conferência')
        || !initialText.includes('Lei Complementar nº 208/2022 · Art. 14 · pendente de conferência')
        || pendingRelationCount !== 8
        || !initialText.includes('não cria aresta operativa')) {
        throw new Error(`The persisted relation review state is incomplete or overclaimed: ${JSON.stringify({
          pending_relation_count: pendingRelationCount,
          has_nested_law_article: initialText.includes('Lei Promulgada nº 275/2009 · Art. 21'),
          has_repealed_law: initialText.includes('Lei Promulgada nº 562/2018'),
          has_amended_law_article: initialText.includes('Lei Complementar nº 208/2022 · Art. 14'),
        })}`);
      }
      report.persisted_relation_review_checks = [
        '8 candidates visible and awaiting human review',
        'nested target identity remains separate from device number',
        'candidate state does not claim an operative graph edge',
      ];
      const targetDocumentCandidates = await page.$$eval(
        '.document-review-target-documents',
        (sections) => sections.map((section) => ({
          text: section.textContent || '',
          links: [...section.querySelectorAll('a[href*="/normas/documentos/"]')].map((link) => ({
            text: link.innerText.trim(),
            href: link.getAttribute('href'),
          })),
        })),
      );
      const mismatched1894 = targetDocumentCandidates.find((section) =>
        /lei01894-69\.pdf/i.test(section.text));
      const exactLc55 = targetDocumentCandidates.find((section) =>
        /lc55-original-2004\.pdf/i.test(section.text));
      const exactLc208 = targetDocumentCandidates.find((section) =>
        /pdn_-_lc_208_2022\.pdf/i.test(section.text));
      const exactLp275 = targetDocumentCandidates.find((section) =>
        /5-lei-promulgada-275-2009-regulamenta-as-calcadas-no-municipio\.pdf/i.test(section.text));
      if (!mismatched1894
        || !/espécie cadastral divergente/i.test(mismatched1894.text)
        || !mismatched1894.links.some((link) => /documentos\//.test(link.href))
        || !exactLc55
        || !/espécie cadastral compatível/i.test(exactLc55.text)
        || !exactLc55.links.some((link) => /documentos\//.test(link.href))
        || !exactLc208
        || !/Prévia automática do Art\. 14/.test(exactLc208.text)
        || !/coeficiente de aproveitamento/.test(exactLc208.text)
        || !/extração não revisada/.test(exactLc208.text)
        || !exactLc208.links.some((link) => /\/pdf\/#page=/.test(link.href))
        || !exactLp275
        || !/espécie cadastral compatível com a citação/i.test(exactLp275.text)
        || !/estado Pendente/i.test(exactLp275.text)
        || !/Prévia automática do Art\. 21/.test(exactLp275.text)
        || !/O rebaixamento de guias/i.test(exactLp275.text)
        || !/extração não revisada/i.test(exactLp275.text)
        || !exactLp275.links.some((link) => /\/pdf\/#page=/.test(link.href))) {
        throw new Error(`Target-document leads are absent or over-resolved: ${JSON.stringify(
          targetDocumentCandidates.map(({ text, links }) => ({
            summary: text.slice(0, 300),
            linkCount: links.length,
          })),
        )}`);
      }
      await page.$$eval(
        '.document-review-target-documents',
        (sections) => sections.forEach((section) => {
          if ((section.textContent || '').includes('pdn_-_lc_208_2022.pdf')
            || (section.textContent || '').includes('5-lei-promulgada-275-2009')) section.open = true;
        }),
      );
      const targetPreviewIndex = await page.$$eval(
        '.document-review-target-preview',
        (previews) => previews.findIndex((node) => node.innerText.includes('coeficiente de aproveitamento')),
      );
      if (targetPreviewIndex < 0) {
        throw new Error('The target-article preview could not be brought into the visual evidence frame.');
      }
      const targetPreviews = await page.$$('.document-review-target-preview');
      await targetPreviews[targetPreviewIndex].screenshot({
        path: path.join(evidenceDir, 'candidate-target-article-preview.png'),
      });
      const lp275PreviewIndex = await page.$$eval(
        '.document-review-target-preview',
        (previews) => previews.findIndex((node) => node.innerText.includes('O rebaixamento de guias')),
      );
      if (lp275PreviewIndex < 0) {
        throw new Error('The official LP 275/2009 Art. 21 excerpt was not displayed as a pending preview.');
      }
      const lp275Previews = await page.$$('.document-review-target-preview');
      await lp275Previews[lp275PreviewIndex].screenshot({
        path: path.join(evidenceDir, 'lp275-2009-art21-pending-preview.png'),
      });
      const linkedEvidence = await page.evaluate(async (href) => {
        const response = await fetch(href, { credentials: 'same-origin' });
        const html = await response.text();
        return {
          status: response.status,
          isEvidencePage: html.includes('document-evidence-page'),
        };
      }, exactLc55.links[0].href);
      if (linkedEvidence.status !== 200 || !linkedEvidence.isEvidencePage) {
        throw new Error(`The candidate PDF lead did not open its evidence page: ${JSON.stringify(linkedEvidence)}`);
      }
      report.target_document_candidate_checks = [
        'matching SAPL PDF linked as an unreviewed LC 55/2004 candidate',
        'ordinary-law PDF shown as a species conflict for the LC 1,894/1969 citation',
        'the matching LC 208/2022 PDF exposes Art. 14 as a bounded, unreviewed preview with a page link',
        'the official LP 275/2009 PDF exposes the exact Art. 21 excerpt as a bounded, unreviewed preview with a page link',
        'opening the LC 55 PDF lead returns the local evidence page (HTTP 200)',
        'document leads stay separate from confirmed relation targets',
      ];
    }
    if (candidateKey === 'ctm-3882-lc217') {
      await page.$$eval(
        '.document-review-target-documents',
        (sections) => sections.forEach((section) => { section.open = true; }),
      );
      const targetDocumentCandidates = await page.$$eval(
        '.document-review-target-documents',
        (sections) => sections.map((section) => ({
          text: section.innerText,
          links: [...section.querySelectorAll('a[href*="/normas/documentos/"]')].map((link) => ({
            text: link.innerText.trim(),
            href: link.getAttribute('href'),
          })),
        })),
      );
      const ctmSource = targetDocumentCandidates.find(({ text }) =>
        text.includes('lei3882-1989-consolidado-exercicio-2022.pdf'));
      if (!ctmSource
        || !ctmSource.text.includes('espécie cadastral compatível com a citação')
        || !ctmSource.text.includes('estado Pendente')
        || !ctmSource.links.some(({ href }) => href.includes('9070d6c2-cfe8-489b-b35f-f1c7f58e8e6e'))) {
        throw new Error(`The municipal 2022 consolidation was not exposed as a pending target-document lead: ${JSON.stringify(
          targetDocumentCandidates.map(({ text, links }) => ({
            summary: text.slice(0, 300),
            linkCount: links.length,
          })),
        )}`);
      }
      report.target_document_candidate_checks = [
        'official municipal 2022 consolidation linked to the LC 217 target identity',
        'source remains pending and is presented as a review lead, not an accepted norm',
      ];
    }
    const selectedExtractionId = Number(await page.$eval(
      '[name="extraction_id"]',
      (node) => node.value,
    ));
    if (selectedExtractionId !== candidate.extractionId) {
      throw new Error('The selected candidate extraction differs from the verified QA allowlist.');
    }
    if (await page.$('input[name="action"][value="accept_extraction"]')) {
      throw new Error('The read-only reviewer was incorrectly offered an extraction-acceptance action.');
    }
    await page.screenshot({ path: path.join(evidenceDir, 'candidate-before-preview.png') });

    await page.$eval('input[name="confirm_generation"]', (node) => { node.checked = true; });
    await Promise.all([
      page.waitForNavigation({ waitUntil: 'domcontentloaded' }),
      page.click('button[type="submit"][data-document-review-submit]'),
    ]);
    const previewNotice = await page.$eval(
      'section[aria-labelledby="segmentation-review-title"]',
      (node) => node.innerText,
    );
    if (!previewNotice.includes('Prévia exploratória, não persistida')) {
      throw new Error('The rendered result did not identify itself as an ephemeral preview.');
    }
    if (previewNotice.includes('chave estrutural')
      || !previewNotice.includes('Dispositivo subordinado a ')) {
      throw new Error('The preview did not render human-readable parent labels.');
    }
    if (candidate.verifyAnnexOcrBoundary
      && (!previewNotice.includes('anexos detectados a partir da página 61 do PDF')
        || !previewNotice.includes('16 páginas anexas dependem de OCR')
        || !previewNotice.includes('excluídos da segmentação'))) {
      throw new Error('The preview did not separate annex/OCR scope from legal-device segmentation.');
    }
    if (candidateKey === 'lc258-2024') {
      const relationPreview = await page.$eval(
        '#candidate-relations-title',
        (node) => node.closest('section')?.innerText || '',
      );
      if (!relationPreview.includes('Lei Promulgada nº 275/2009')
        || !/artigo\s+21/i.test(relationPreview)
        || !relationPreview.includes('Lei Promulgada nº 562/2018')
        || !relationPreview.includes('não confirmada')) {
        throw new Error('The real LC 258 preview lost a nested target identity or its unreviewed status.');
      }
      report.relation_preview_checks = [
        'Lei Promulgada 275/2009 · artigo 21',
        'Lei Promulgada 562/2018',
        'relation status remains unreviewed',
      ];
    }
    const headings = await page.$$eval(
      '.document-segmentation-preview__item h3',
      (nodes) => nodes.map((node) => node.innerText.trim()),
    );
    report.device_count = headings.length;
    report.article_count = headings.filter((text) => /^artigo\s/i.test(text)).length;
    report.key_articles_visible = candidate.expectedArticles.filter((number) => (
      headings.some((text) => new RegExp(`^artigo\\s+${number}(?:\\b|\\s)`, 'i').test(text))
    ));
    const expectedCountsMatch = !candidate.expectedCounts
      || (report.article_count === candidate.expectedCounts.articles
        && (candidate.expectedCounts.devices === undefined
          || report.device_count === candidate.expectedCounts.devices));
    if (report.article_count < 1 || report.device_count < 1
      || !expectedCountsMatch
      || report.key_articles_visible.length !== candidate.expectedArticles.length) {
      throw new Error(`Real-PDF device counts or article boundaries differ from the read-only parser diagnostic: ${JSON.stringify({
        article_count: report.article_count,
        device_count: report.device_count,
        key_articles_visible: report.key_articles_visible,
        expected_articles: candidate.expectedArticles,
        expected_counts: candidate.expectedCounts || null,
      })}`);
    }
    if (await page.$('input[name="action"][value="review_segmentation"]')) {
      throw new Error('The ephemeral preview unexpectedly offered a persistent review action.');
    }
    const targetCardFound = await page.$$eval(
      '.document-segmentation-preview__item',
      (cards, articleNumber) => {
        const headingPattern = new RegExp(`^artigo\\s+${articleNumber}(?:\\b|\\s)`, 'i');
        const target = cards.find((card) => headingPattern.test(
          card.querySelector('h3')?.innerText.trim() || '',
        ));
        if (!target) return false;
        target.scrollIntoView({ block: 'center' });
        return true;
      },
      candidate.expectedArticles[0],
    );
    if (!targetCardFound) throw new Error('The target article card could not be brought into view.');
    await page.screenshot({ path: path.join(evidenceDir, 'candidate-preview-devices.png') });
    if (pageErrors.length) throw new Error('A browser page error occurred during the review preview.');

    report.status = 'passed';
    report.evidence_dir = evidenceDir;
    fs.writeFileSync(
      path.join(evidenceDir, 'report.json'),
      `${JSON.stringify(report, null, 2)}\n`,
      { encoding: 'utf8', flag: 'wx' },
    );
    console.log(JSON.stringify(report, null, 2));
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(`Candidate review browser smoke failed: ${error.name || 'Error'}: ${error.message}`);
  process.exitCode = 1;
});
