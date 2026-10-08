import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import puppeteer from 'puppeteer-core';

const baseUrl = process.env.JURIX_BASE_URL || '';
const qaRoot = process.env.JURIX_QA_ROOT || '';
const evidenceDir = process.env.JURIX_EVIDENCE_DIR || '';
const parsedBase = new URL(baseUrl);
assert.equal(parsedBase.protocol, 'http:');
assert.ok(['127.0.0.1', 'localhost'].includes(parsedBase.hostname));
assert.ok(['8007', '8009', '8010', '8011', '8012', '8013', '8014', '8015', '8016', '8017', '8018', '8019', '8020', '8021', '8022', '8023', '8024', '8025', '8026'].includes(parsedBase.port));
assert.ok(qaRoot && evidenceDir, 'QA root and evidence directory are required');
const resolvedTemp = await fs.realpath(os.tmpdir());
const resolvedRoot = await fs.realpath(qaRoot);
const absoluteEvidenceDir = path.resolve(evidenceDir);
const evidenceParent = await fs.realpath(path.dirname(absoluteEvidenceDir));
const resolvedEvidenceDir = path.join(evidenceParent, path.basename(absoluteEvidenceDir));
assert.ok(resolvedRoot.toLowerCase().startsWith(resolvedTemp.toLowerCase() + path.sep));
const evidenceRelativeToRoot = path.relative(resolvedRoot, resolvedEvidenceDir);
assert.ok(evidenceRelativeToRoot && !evidenceRelativeToRoot.startsWith('..') && !path.isAbsolute(evidenceRelativeToRoot));
await fs.mkdir(resolvedEvidenceDir, { recursive: true });

const browserCandidates = [
  process.env.PUPPETEER_EXECUTABLE_PATH,
  process.env.CHROME_BIN,
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
  'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
].filter(Boolean);
let executablePath;
for (const candidate of browserCandidates) {
  try {
    await fs.access(candidate);
    executablePath = candidate;
    break;
  } catch {
    // Continue only through known local browser locations.
  }
}
assert.ok(executablePath, 'an already-installed Chrome or Edge executable is required');

async function auditArchivePdfRoutes(browser, baseUrl) {
  const page = await browser.newPage();
  try {
    const response = await page.goto(new URL('/normas/', baseUrl).href, {
      waitUntil: 'domcontentloaded',
      timeout: 20000,
    });
    assert.equal(response?.status(), 200, 'the local archive library must load');
    const result = await page.evaluate(async () => {
      const listResponse = await fetch('/normas/');
      const listHtml = await listResponse.text();
      const listDocument = new DOMParser().parseFromString(listHtml, 'text/html');
      const documentIds = [...new Set(
        [...listDocument.querySelectorAll('a[href*="/normas/documentos/"]')]
          .map((anchor) => anchor.getAttribute('href') || '')
          .map((href) => href.match(/\/normas\/documentos\/([0-9a-f-]{36})\//i)?.[1])
          .filter(Boolean),
      )];
      let detailPagesOk = 0;
      let pdfFilesOk = 0;
      let totalBytes = 0;
      let minimumBytes = Number.POSITIVE_INFINITY;
      let maximumBytes = 0;
      const failures = [];

      for (const id of documentIds) {
        const detailResponse = await fetch(`/normas/documentos/${id}/`);
        if (!detailResponse.ok) {
          failures.push('document_detail_http');
          continue;
        }
        detailPagesOk += 1;
        const detailHtml = await detailResponse.text();
        const detailDocument = new DOMParser().parseFromString(detailHtml, 'text/html');
        const pdfAnchor = [...detailDocument.querySelectorAll('a[href*="/pdf/"]')]
          .find((anchor) => new URL(anchor.href, location.href).pathname
            .startsWith(`/normas/documentos/${id}/pdf/`));
        if (!pdfAnchor) {
          failures.push('document_pdf_link_missing');
          continue;
        }
        const pdfResponse = await fetch(pdfAnchor.href);
        const contentType = pdfResponse.headers.get('content-type') || '';
        const bytes = new Uint8Array(await pdfResponse.arrayBuffer());
        const signature = new TextDecoder().decode(bytes.subarray(0, 5));
        const tail = new TextDecoder().decode(bytes.subarray(Math.max(0, bytes.length - 2048)));
        if (!pdfResponse.ok || !/application\/pdf/i.test(contentType)
          || !signature.startsWith('%PDF') || !tail.includes('%%EOF')) {
          failures.push('document_pdf_invalid');
          continue;
        }
        pdfFilesOk += 1;
        totalBytes += bytes.length;
        minimumBytes = Math.min(minimumBytes, bytes.length);
        maximumBytes = Math.max(maximumBytes, bytes.length);
      }

      return {
        listStatus: listResponse.status,
        documentsVisible: documentIds.length,
        detailPagesOk,
        pdfFilesOk,
        totalBytes,
        minimumBytes: Number.isFinite(minimumBytes) ? minimumBytes : 0,
        maximumBytes,
        failures,
      };
    });
    assert.equal(result.listStatus, 200);
    assert.equal(result.documentsVisible, 40, `the QA archive should expose 40 documents: ${JSON.stringify(result)}`);
    assert.equal(result.detailPagesOk, 40, `all 40 document fiches should load: ${JSON.stringify(result)}`);
    assert.equal(result.pdfFilesOk, 40, `all 40 complete local PDFs should be served: ${JSON.stringify(result)}`);
    assert.deepEqual(result.failures, []);
    return result;
  } finally {
    await page.close();
  }
}

const browser = await puppeteer.launch({
  executablePath,
  headless: true,
  args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'],
});

try {
  await browser.defaultBrowserContext().overridePermissions(baseUrl, ['clipboard-read', 'clipboard-write']);
  const page = await browser.newPage();
  const failures = [];
  page.on('pageerror', (error) => failures.push(error.name));
  const startedAt = Date.now();
  const route = '/assistente/?corpus=archive-qa';
  const pageResponse = await page.goto(new URL(route, baseUrl).href, {
    waitUntil: 'domcontentloaded',
    timeout: 20000,
  });
  assert.equal(pageResponse?.status(), 200, 'assistant page must load in the QA browser');
  assert.equal(await page.$eval('body', (body) => body.dataset.qaArchiveCorpus), 'true');
  assert.equal(await page.$eval('meta[name="jurix-authenticated"]', (meta) => meta.content), 'false');

  await page.evaluate(() => {
    window.__jurixLiveRagTrace = {
      submittedAt: null,
      sourcesAtMs: null,
      firstTextAtMs: null,
      completionUiAtMs: null,
      sendDisabledObserved: false,
    };
    const observer = new MutationObserver(() => {
      const trace = window.__jurixLiveRagTrace;
      if (trace.submittedAt === null) return;
      const elapsed = Math.round(performance.now() - trace.submittedAt);
      if (trace.sourcesAtMs === null && document.querySelector('.jurix-sources-pill-btn')) {
        trace.sourcesAtMs = elapsed;
      }
      const body = document.querySelector('.message-assistant .message-body');
      const hasFinalContent = Boolean(body?.textContent?.trim())
        && !body?.querySelector('.jurix-answer-pending');
      if (trace.firstTextAtMs === null && hasFinalContent && body?.hasAttribute('data-streaming')) {
        trace.firstTextAtMs = elapsed;
      }
      const sendButton = document.getElementById('send-button');
      if (sendButton?.disabled) trace.sendDisabledObserved = true;
      if (trace.firstTextAtMs !== null && trace.completionUiAtMs === null
        && hasFinalContent && body && !body.hasAttribute('data-streaming')) {
        trace.completionUiAtMs = elapsed;
      }
    });
    observer.observe(document.body, {
      subtree: true,
      childList: true,
      characterData: true,
      attributes: true,
    });
  });

  let streamResponse = null;
  page.on('response', (response) => {
    if (new URL(response.url()).pathname === '/api/v1/search/answer/stream/') {
      streamResponse = response;
    }
  });
  const question = 'Na Lei Complementar nº 120/2010, compare o que disciplinam os arts. 17 e 18 sobre vencimento básico; explique a diferença em duas frases, mencione a identificação completa da norma e cite cada dispositivo.';
  await page.$eval('#question-textarea', (input, value) => {
    input.value = value;
    input.dispatchEvent(new Event('input', { bubbles: true }));
  }, question);
  await page.evaluate(() => {
    window.__jurixLiveRagTrace.submittedAt = performance.now();
    document.getElementById('chat-form').requestSubmit();
  });

  await page.waitForFunction(() => {
    const button = document.getElementById('send-button');
    const answer = document.querySelector('.message-assistant .message-body');
    return button && !button.disabled && answer?.textContent?.trim().length > 0
      && !answer.querySelector('.jurix-answer-pending') && !answer.hasAttribute('data-streaming');
  }, { timeout: 180000 });
  await new Promise((resolve) => setTimeout(resolve, 150));

  const result = await page.evaluate(() => {
    const answer = document.querySelector('.message-assistant .message-body');
    const sourceContainer = answer?.closest('.message-content')?.querySelector('[id^="sources-"]');
    const sourceButton = sourceContainer?.querySelector('.jurix-sources-pill-btn');
    const anchors = [...(answer?.querySelectorAll('a') || [])];
    const legalLinks = anchors.filter((anchor) => anchor.classList.contains('jurix-legal-reference-link'));
    const article17Link = legalLinks.find((anchor) => /\bart(?:igo)?\.?\s*17\b/i.test(anchor.textContent || ''));
    const article18Link = legalLinks.find((anchor) => /\bart(?:igo)?\.?\s*18\b/i.test(anchor.textContent || ''));
    const normLink = legalLinks.find((anchor) => /\b120\s*\/\s*2010\b/i.test(anchor.textContent || '')
      && !/\bart(?:igo)?\.?\s*(?:17|18)\b/i.test(anchor.textContent || ''));
    const hasTextFragment = (anchor) => {
      try { return new URL(anchor.href).hash.startsWith('#:~:text='); } catch { return false; }
    };
    const text = answer?.textContent || '';
    return {
      trace: window.__jurixLiveRagTrace,
      answerCharCount: text.length,
      headingCount: answer?.querySelectorAll('h1, h2, h3, h4, h5, h6').length || 0,
      paragraphCount: answer?.querySelectorAll('p').length || 0,
      listItemCount: answer?.querySelectorAll('li').length || 0,
      answerHasAbstention: /não (?:foi possível|encontrei|localizei)|evidências? suficientes/i.test(text),
      answerNodeDiagnostics: [...document.querySelectorAll('.message-assistant .message-body')].map((body) => ({
        id: body.id,
        textLength: body.textContent?.length || 0,
        pendingStatusPresent: Boolean(body.querySelector('.jurix-answer-pending')),
        pendingStatusLength: body.querySelector('.jurix-answer-pending')?.textContent?.length || 0,
        childTags: [...body.children].map((child) => `${child.tagName.toLowerCase()}.${String(child.className || '').toString()}`),
        streaming: body.hasAttribute('data-streaming'),
      })),
      ragUiAvailable: Boolean(window.JurixRagUI),
      renderTrace: window.__jurixLiveRagTrace,
      answerMentionsArticle17: /art(?:igo)?\.?\s*17\s*[º°o]?/i.test(text),
      answerMentionsArticle18: /art(?:igo)?\.?\s*18\s*[º°o]?/i.test(text),
      sourceCount: Array.isArray(sourceContainer?._sourcesData) ? sourceContainer._sourcesData.length : 0,
      sourceControlVisible: Boolean(sourceButton && sourceButton.getClientRects().length),
      citationLinkCount: anchors.length,
      citationLinksIncludeArticle17: anchors.some((anchor) => /art(?:igo)?\.?\s*17\b/i.test(anchor.innerText)),
      citationLinksIncludeArticle18: anchors.some((anchor) => /art(?:igo)?\.?\s*18\b/i.test(anchor.innerText)),
      article17LegalLinkHasTextFragment: Boolean(article17Link && hasTextFragment(article17Link)),
      article18LegalLinkHasTextFragment: Boolean(article18Link && hasTextFragment(article18Link)),
      normLegalLinkPresent: Boolean(normLink),
      normLegalLinkHasNoTextFragment: Boolean(normLink && !hasTextFragment(normLink)),
      sourceDeviceRefs: (Array.isArray(sourceContainer?._sourcesData) ? sourceContainer._sourcesData : [])
        .map((source) => String(source?.dispositivo_ref || ''))
        .filter(Boolean),
      citationLinksAreLocalOrOfficial: anchors.every((anchor) => {
        try {
          const url = new URL(anchor.href);
          return url.hostname === location.hostname || url.hostname === 'sapl.natal.rn.leg.br';
        } catch { return false; }
      }),
      sourceButtonLabel: sourceButton?.getAttribute('aria-label') || '',
      conversationUrlHasCorpus: new URL(location.href).searchParams.get('corpus') === 'archive-qa',
    };
  });
  const streamBody = await streamResponse.text();
  const events = streamBody.split(/\r?\n/)
    .filter((line) => line.startsWith('data:'))
    .map((line) => JSON.parse(line.slice(5).trim()));
  const eventTypes = events.map((event) => event.type);
  const sourcesIndex = eventTypes.indexOf('sources');
  const firstChunkIndex = eventTypes.indexOf('chunk');
  const doneEvent = events.find((event) => event.type === 'done');
  const streamDiagnostics = {
    reasonCode: doneEvent?.reason_code || null,
    grounded: doneEvent?.grounded === true,
    answerCharCount: String(doneEvent?.answer || '').length,
    answerCitationMarkerCount: (String(doneEvent?.answer || '').match(/\[\[\d+\]\]/g) || []).length,
    claimCount: Array.isArray(doneEvent?.contract?.claim_report)
      ? doneEvent.contract.claim_report.length
      : 0,
    supportedClaimCount: Array.isArray(doneEvent?.contract?.claim_report)
      ? doneEvent.contract.claim_report.filter((claim) => claim?.supported === true).length
      : 0,
  };
  assert.equal(streamResponse?.status(), 200, 'one successful streaming request must reach the QA backend');
  assert.ok(result.answerCharCount > 0, 'assistant must render a final answer or safe abstention');
  assert.equal(result.answerMentionsArticle17, true, `the answer must address the first requested device: ${JSON.stringify({
    answerCharCount: result.answerCharCount,
    answerHasAbstention: result.answerHasAbstention,
    sourceCount: result.sourceCount,
    sourceDeviceRefs: result.sourceDeviceRefs,
    citationLinkCount: result.citationLinkCount,
    answerNodeDiagnostics: result.answerNodeDiagnostics,
    ragUiAvailable: result.ragUiAvailable,
    renderTrace: result.renderTrace,
    streamDiagnostics,
  })}`);
  assert.equal(result.answerMentionsArticle18, true, `the answer must address the second requested device: ${JSON.stringify({
    answerCharCount: result.answerCharCount,
    answerHasAbstention: result.answerHasAbstention,
    sourceCount: result.sourceCount,
    sourceDeviceRefs: result.sourceDeviceRefs,
    citationLinkCount: result.citationLinkCount,
  })}`);
  assert.ok(result.sourceCount > 0, 'the selected historical corpus should return at least one source');
  assert.ok(result.citationLinkCount >= 2, 'the answer must render citations for the multi-device request');
  assert.ok(result.sourceDeviceRefs.some((ref) => /art\.?\s*17\b/i.test(ref)));
  assert.ok(result.sourceDeviceRefs.some((ref) => /art\.?\s*18\b/i.test(ref)));
  assert.equal(result.citationLinksIncludeArticle17, true, 'the article 17 reference must be linked');
  assert.equal(result.citationLinksIncludeArticle18, true, 'the article 18 reference must be linked');
  assert.equal(result.article17LegalLinkHasTextFragment, true, 'the article 17 inline link must target its cited PDF passage');
  assert.equal(result.article18LegalLinkHasTextFragment, true, 'the article 18 inline link must target its cited PDF passage');
  if (result.normLegalLinkPresent) {
    assert.equal(result.normLegalLinkHasNoTextFragment, true, 'a whole-norm inline link must open the document without an article highlight');
  }
  assert.equal(result.sourceControlVisible, true, 'sources must be available without refreshing');
  assert.ok(
    result.trace.firstTextAtMs !== null && result.trace.completionUiAtMs !== null &&
      result.trace.firstTextAtMs < result.trace.completionUiAtMs,
    `validated answer text must become visible before the UI indicates completion: ${JSON.stringify({
      firstTextAtMs: result.trace.firstTextAtMs,
      completionUiAtMs: result.trace.completionUiAtMs,
    })}`,
  );
  assert.equal(result.citationLinksAreLocalOrOfficial, true, 'citations must not point to untrusted hosts');
  assert.equal(result.conversationUrlHasCorpus, true, 'QA corpus scope must survive session URL update');
  assert.equal(failures.length, 0, 'the browser must not emit uncaught page errors');

  const copyButton = await page.$('.message-assistant .copy-response-button.show');
  assert.ok(copyButton, 'a completed answer must expose its copy action');
  await copyButton.click();
  const copiedCitationChecks = await page.evaluate(async () => {
    const copied = await navigator.clipboard.readText();
    const links = [...copied.matchAll(/\[[^\]]+\]\(<([^>]+)>\)/g)].map((match) => match[1]);
    return {
      hasArticle17MarkdownLink: /\[[^\]]*\bart(?:igo)?\.?\s*17\b[^\]]*\]\(<[^>]+>\)/i.test(copied),
      hasArticle18MarkdownLink: /\[[^\]]*\bart(?:igo)?\.?\s*18\b[^\]]*\]\(<[^>]+>\)/i.test(copied),
      hasNoUnresolvedCitationMarkers: !/\[\[\d{1,3}\]\]/.test(copied),
      allMarkdownLinksTrusted: links.every((href) => {
        try {
          const url = new URL(href, location.href);
          return url.hostname === location.hostname || url.hostname === 'sapl.natal.rn.leg.br';
        } catch { return false; }
      }),
      markdownLinkCount: links.length,
    };
  });
  assert.equal(copiedCitationChecks.hasArticle17MarkdownLink, true, 'copied Markdown must preserve the article 17 citation link');
  assert.equal(copiedCitationChecks.hasArticle18MarkdownLink, true, 'copied Markdown must preserve the article 18 citation link');
  assert.equal(copiedCitationChecks.hasNoUnresolvedCitationMarkers, true, 'copied response must resolve structured citation markers');
  assert.equal(copiedCitationChecks.allMarkdownLinksTrusted, true, 'copied links must remain on the app or official SAPL host');
  assert.ok(copiedCitationChecks.markdownLinkCount >= 2, 'copied answer must include Markdown links for its citations');

  const generationAttempts = doneEvent?.contract?.generation_attempts || [];
  const generationMs = doneEvent?.contract?.timings_ms?.generation ?? null;
  assert.ok(sourcesIndex >= 0 && firstChunkIndex > sourcesIndex, 'SSE must deliver sources before answer text');
  assert.ok(doneEvent && eventTypes.lastIndexOf('done') > firstChunkIndex, 'SSE must deliver answer chunks before done');
  assert.ok(generationAttempts.length > 0, 'the two-device synthesis must exercise an actual model-generation attempt');
  assert.ok(Number(generationMs) > 0, 'backend generation timing must confirm the Ollama path ran');

  const drawer = await page.$('#jurix-sources-drawer-panel');
  assert.ok(drawer, 'sources drawer must exist');
  const sourceActionLayout = await page.$eval('.jurix-sources-pill-btn', (button) => {
    const rect = button.getBoundingClientRect();
    const composer = document.querySelector('#conversation-input-bar')?.getBoundingClientRect();
    const container = document.querySelector('#messages-container');
    const hit = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2);
    return {
      pill: { top: rect.top, bottom: rect.bottom, left: rect.left, right: rect.right },
      composerTop: composer?.top,
      hit: hit ? `${hit.tagName.toLowerCase()}.${String(hit.className || '').toString().trim().replace(/\s+/g, '.')}` : null,
      messageScroll: container && {
        top: container.scrollTop,
        max: container.scrollHeight - container.clientHeight,
        clearance: container.style.getPropertyValue('--jurix-composer-clearance'),
      },
    };
  });
  await page.focus('.jurix-sources-pill-btn');
  await page.keyboard.press('Enter');
  try {
    await page.waitForFunction(() => document.querySelector('#jurix-sources-drawer-panel')?.getAttribute('aria-hidden') === 'false', { timeout: 2500 });
  } catch {
    throw new Error(`The consulted-sources drawer did not open: ${JSON.stringify(sourceActionLayout)}`);
  }
  const drawerHasEvidence = await page.$eval('#jurix-sources-drawer-body', (body) => body.innerText.trim().length > 0);
  assert.equal(drawerHasEvidence, true, 'opening the source drawer must show evidence');
  const pdfSource = await page.$eval(
    '#jurix-sources-drawer-body .jurix-rag-source__open[href*="/normas/documentos/"][href*="/pdf/"]',
    (anchor) => {
      const rect = anchor.getBoundingClientRect();
      const hit = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2);
      return {
        href: anchor.href,
        pathname: new URL(anchor.href).pathname,
        target: anchor.target,
        rel: anchor.rel,
        visible: rect.width > 0 && rect.height > 0,
        pointerEvents: getComputedStyle(anchor).pointerEvents,
        hitTag: hit?.tagName?.toLowerCase() || null,
        hitClass: String(hit?.className || '').toString().slice(0, 100),
      };
    },
  );
  assert.equal(pdfSource.target, '_blank', 'a cited archive PDF must open in a separate tab');
  assert.match(pdfSource.rel, /noopener/);
  const pdfResponse = await page.evaluate(async (href) => {
    const response = await fetch(href);
    return {
      status: response.status,
      contentType: response.headers.get('content-type') || '',
      contentLength: Number(response.headers.get('content-length') || 0),
    };
  }, pdfSource.href);
  assert.equal(
    pdfResponse.status,
    200,
    `the cited local PDF route must be available (${pdfSource.pathname}; HTTP ${pdfResponse.status}; ${pdfResponse.contentType || 'no content type'})`,
  );
  assert.match(pdfResponse.contentType, /application\/pdf/i);
  const targetsBeforePdfClick = new Set(browser.targets());
  const openedPdfTargets = [];
  const onTargetCreated = (target) => {
    if (!targetsBeforePdfClick.has(target)) openedPdfTargets.push(target.url());
  };
  browser.on('targetcreated', onTargetCreated);
  let popupObserved = false;
  const onPopup = () => { popupObserved = true; };
  page.on('popup', onPopup);
  await page.evaluate(() => {
    window.__jurixPdfClickDiagnostic = null;
    document.addEventListener('click', (event) => {
      const anchor = event.target?.closest?.('.jurix-rag-source__open[href*="/normas/documentos/"][href*="/pdf/"]');
      if (!anchor) return;
      const snapshot = {
        href: anchor.href,
        trusted: event.isTrusted,
        defaultPreventedAtCapture: event.defaultPrevented,
      };
      setTimeout(() => {
        window.__jurixPdfClickDiagnostic = {
          ...snapshot,
          defaultPreventedAfterDispatch: event.defaultPrevented,
        };
      }, 0);
    }, true);
  });
  const assistantRouteBeforePdfClick = page.url();
  await page.click('#jurix-sources-drawer-body .jurix-rag-source__open[href*="/normas/documentos/"][href*="/pdf/"]');
  const pageUrlAfterPdfClick = page.url();
  await new Promise((resolve) => setTimeout(resolve, 1200));
  const pdfClickDiagnostic = await page.evaluate(() => window.__jurixPdfClickDiagnostic);
  const directPdfPage = await browser.newPage();
  const directPdfResponse = await directPdfPage.goto(pdfSource.href, { waitUntil: 'domcontentloaded', timeout: 15000 });
  const directPdfViewer = await directPdfPage.evaluate(() => ({
    url: location.pathname,
    title: document.title,
    bodyTextLength: document.body?.innerText?.trim()?.length || 0,
    pdfViewerPresent: Boolean(document.querySelector('embed[type="application/pdf"], pdf-viewer, #plugin, #viewer')),
  }));
  await directPdfPage.close();
  browser.off('targetcreated', onTargetCreated);
  page.off('popup', onPopup);
  for (const target of browser.targets()) {
    if (!targetsBeforePdfClick.has(target)) {
      const pdfTab = await target.page();
      if (pdfTab) await pdfTab.close();
    }
  }
  await page.keyboard.press('Escape');
  await page.waitForFunction(() => document.querySelector('#jurix-sources-drawer-panel')?.getAttribute('aria-hidden') === 'true');
  const sourceDrawerFocusRestored = await page.evaluate(() =>
    document.activeElement === document.querySelector('.message-assistant .jurix-sources-pill-btn'));
  assert.equal(sourceDrawerFocusRestored, true, 'Escape must close the source drawer and return focus to its opening control');

  const urlBeforeReload = page.url();
  const stateBeforeReload = {
    answerCharCount: result.answerCharCount,
    sourceCount: result.sourceCount,
    sourceDeviceRefs: [...result.sourceDeviceRefs].sort(),
  };
  await page.reload({ waitUntil: 'domcontentloaded', timeout: 20000 });
  await page.waitForFunction(() => {
    const answer = document.querySelector('.message-assistant .message-body');
    const sourceButton = document.querySelector('.message-assistant .jurix-sources-pill-btn');
    return answer?.textContent?.trim() && sourceButton;
  }, { timeout: 15000 });
  const restoredState = await page.evaluate(() => {
    const answer = document.querySelector('.message-assistant .message-body');
    const sourceContainer = answer?.closest('.message-content')?.querySelector('[id^="sources-"]');
    return {
      answerCharCount: answer?.textContent?.length || 0,
      sourceCount: Array.isArray(sourceContainer?._sourcesData) ? sourceContainer._sourcesData.length : 0,
      sourceDeviceRefs: (Array.isArray(sourceContainer?._sourcesData) ? sourceContainer._sourcesData : [])
        .map((source) => String(source?.dispositivo_ref || ''))
        .filter(Boolean)
        .sort(),
      citationLinkCount: answer?.querySelectorAll('a').length || 0,
      urlHasCorpus: new URL(location.href).searchParams.get('corpus') === 'archive-qa',
    };
  });
  assert.equal(restoredState.answerCharCount, stateBeforeReload.answerCharCount);
  assert.equal(restoredState.sourceCount, stateBeforeReload.sourceCount);
  assert.deepEqual(restoredState.sourceDeviceRefs, stateBeforeReload.sourceDeviceRefs);
  assert.ok(restoredState.citationLinkCount >= 2);
  assert.equal(restoredState.urlHasCorpus, true);
  assert.equal(page.url(), urlBeforeReload, 'the conversation URL must remain stable after reload');

  let followUpStreamResponse = null;
  page.on('response', (response) => {
    if (new URL(response.url()).pathname === '/api/v1/search/answer/stream/') {
      followUpStreamResponse = response;
    }
  });
  await page.$eval('#question-textarea', (input, value) => {
    input.value = value;
    input.dispatchEvent(new Event('input', { bubbles: true }));
  }, 'E o Art. 19?');
  await page.evaluate(() => document.getElementById('chat-form').requestSubmit());
  await page.waitForFunction(() => {
    const answers = [...document.querySelectorAll('.message-assistant .message-body')];
    const latest = answers.at(-1);
    const sendButton = document.getElementById('send-button');
    return answers.length >= 2 && sendButton && !sendButton.disabled
      && latest?.textContent?.trim() && !latest.querySelector('.jurix-answer-pending')
      && !latest.hasAttribute('data-streaming');
  }, { timeout: 180000 });
  assert.equal(followUpStreamResponse?.status(), 200,
    'an elliptical article follow-up must reach the stream endpoint in the same session');
  const followUp = await page.evaluate(() => {
    const answers = [...document.querySelectorAll('.message-assistant .message-body')];
    const answer = answers.at(-1);
    const sourceContainer = answer?.closest('.message-content')?.querySelector('[id^="sources-"]');
    const sources = Array.isArray(sourceContainer?._sourcesData) ? sourceContainer._sourcesData : [];
    const links = [...(answer?.querySelectorAll('a') || [])];
    const article19Link = links.find((link) => /art(?:igo)?\.?\s*19\b/i.test(link.innerText || link.textContent || ''));
    return {
      answerCharCount: answer?.textContent?.trim()?.length || 0,
      mentionsArticle19: /art(?:igo)?\.?\s*19\b/i.test(answer?.textContent || ''),
      sourceCount: sources.length,
      sourceDeviceRefs: sources.map((source) => String(source?.dispositivo_ref || '')).filter(Boolean),
      sourceNormRefs: sources.map((source) => String(source?.norma_ref || '')).filter(Boolean),
      linkedArticle19: links.some((link) => /art(?:igo)?\.?\s*19\b/i.test(link.innerText || link.textContent || '')),
      article19Href: article19Link?.href || '',
      userTurnCount: document.querySelectorAll('.message-user').length,
      assistantTurnCount: answers.length,
      url: location.href,
    };
  });
  assert.ok(followUp.answerCharCount > 0);
  assert.equal(followUp.mentionsArticle19, true,
    `the short follow-up must resolve the requested article: ${JSON.stringify(followUp)}`);
  assert.ok(followUp.sourceCount > 0, 'the follow-up must return its own evidence');
  assert.ok(followUp.sourceDeviceRefs.some((ref) => /art\.?\s*19\b/i.test(ref)),
    `the sources must support Art. 19: ${JSON.stringify(followUp.sourceDeviceRefs)}`);
  assert.ok(followUp.sourceNormRefs.some((ref) => /120\s*\/\s*2010/i.test(ref)),
    `the follow-up must retain LC nº 120/2010 context: ${JSON.stringify(followUp.sourceNormRefs)}`);
  assert.equal(followUp.linkedArticle19, true, 'the follow-up device must have a resolvable citation link');
  const article19Pdf = await page.evaluate(async (href) => {
    const url = new URL(href, location.href);
    const response = await fetch(url.href);
    return {
      localPdfPath: url.pathname.startsWith('/normas/documentos/') && url.pathname.endsWith('/pdf/'),
      status: response.status,
      contentType: response.headers.get('content-type') || '',
    };
  }, followUp.article19Href);
  assert.equal(article19Pdf.localPdfPath, true,
    `the Art. 19 citation must target the local source PDF in the QA corpus: ${JSON.stringify(article19Pdf)}`);
  assert.equal(article19Pdf.status, 200, 'the cited article PDF must be openable');
  assert.match(article19Pdf.contentType, /application\/pdf/i);
  followUp.article19PdfOpens = true;
  delete followUp.article19Href;
  assert.equal(followUp.userTurnCount, 2, 'the follow-up must append exactly one user turn');
  assert.equal(followUp.assistantTurnCount, 2, 'the follow-up must append exactly one assistant turn');
  assert.equal(followUp.url, urlBeforeReload, 'the follow-up must preserve the stable conversation URL');

  const archivePdfRouteAudit = await auditArchivePdfRoutes(browser, baseUrl);

  const overviewContext = await browser.createBrowserContext();
  let wholeNormOverview;
  try {
    const overviewPage = await overviewContext.newPage();
    const overviewErrors = [];
    overviewPage.on('pageerror', (error) => overviewErrors.push(error.name));
    const overviewResponse = await overviewPage.goto(new URL(route, baseUrl).href, {
      waitUntil: 'domcontentloaded',
      timeout: 20000,
    });
    assert.equal(overviewResponse?.status(), 200);
    assert.equal(await overviewPage.$eval('body', (body) => body.dataset.qaArchiveCorpus), 'true');
    let answerStreamResponse = null;
    overviewPage.on('response', (response) => {
      if (new URL(response.url()).pathname === '/api/v1/search/answer/stream/') {
        answerStreamResponse = response;
      }
    });
    const overviewQuestion = 'O que prevê a Lei Complementar nº 120/2010? Faça uma visão geral dos temas identificáveis e informe claramente o que ficou fora da amostra.';
    await overviewPage.$eval('#question-textarea', (input, value) => {
      input.value = value;
      input.dispatchEvent(new Event('input', { bubbles: true }));
    }, overviewQuestion);
    await overviewPage.evaluate(() => document.getElementById('chat-form').requestSubmit());
    await overviewPage.waitForFunction(() => {
      const button = document.getElementById('send-button');
      const answer = document.querySelector('.message-assistant .message-body');
      return button && !button.disabled && answer?.textContent?.trim().length > 0
        && !answer.querySelector('.jurix-answer-pending') && !answer.hasAttribute('data-streaming');
    }, { timeout: 180000 });
    assert.ok(answerStreamResponse, 'whole-norm question must reach the streaming endpoint');
    const overviewStreamBody = await answerStreamResponse.text();
    const overviewEvents = overviewStreamBody.split(/\r?\n/)
      .filter((line) => line.startsWith('data:'))
      .map((line) => JSON.parse(line.slice(5).trim()));
    const overviewSourceEvent = overviewEvents.find((event) => event.type === 'sources');
    const overviewDoneEvent = overviewEvents.find((event) => event.type === 'done');
    const corpusCoverage = overviewDoneEvent?.contract?.corpus_coverage || {};
    const coverageScopeCount = Array.isArray(corpusCoverage.sources_checked)
      ? corpusCoverage.sources_checked.length
      : 0;
    assert.ok(
      ['unknown', 'partial', 'reviewed'].includes(corpusCoverage.coverage_status),
      'the final SSE contract must expose an explicit corpus coverage status',
    );
    if (coverageScopeCount === 0) {
      assert.equal(
        corpusCoverage.coverage_status,
        'unknown',
        'an uncertified QA corpus must not be presented as complete or reviewed',
      );
    }
    const coverage = overviewSourceEvent?.coverage || {};
    const retrievedSourceCount = Array.isArray(overviewSourceEvent?.sources) ? overviewSourceEvent.sources.length : 0;
    const coverageComplete = coverage.complete;
    const selectedArticles = coverage.selected_articles;
    const totalArticles = coverage.total_articles;
    const plannedSampleCount = selectedArticles <= 8
      ? selectedArticles
      : Math.min(10, Math.max(5, Math.ceil(Math.sqrt(selectedArticles))));
    const overviewGenerationAttempts = overviewDoneEvent?.contract?.generation_attempts || [];
    const overviewGenerationMs = overviewDoneEvent?.contract?.timings_ms?.generation ?? null;
    const streamCitationMarkers = overviewEvents
      .filter((event) => event.type === 'chunk')
      .reduce((count, event) => count + (String(event.chunk || '').match(/\[\[\d+\]\]/g) || []).length, 0);
    const doneCitationMarkers = (String(overviewDoneEvent?.answer || '').match(/\[\[\d+\]\]/g) || []).length;
    const citationRendererProbe = await overviewPage.evaluate(({ answer, sources }) => {
      const probe = document.createElement('div');
      probe.innerHTML = window.JurixMarkdown.render(answer, sources);
      return {
        linkCount: probe.querySelectorAll('.jurix-citation[data-source-index]').length,
        unresolvedMarkerCount: (probe.textContent.match(/\[\[\d+\]\]/g) || []).length,
      };
    }, { answer: overviewDoneEvent?.answer || '', sources: overviewSourceEvent?.sources || [] });
    const overviewUi = await overviewPage.evaluate(() => {
      const answer = document.querySelector('.message-assistant .message-body');
      const sourceContainer = answer?.closest('.message-content')?.querySelector('[id^="sources-"]');
      const sourceButton = sourceContainer?.querySelector('.jurix-sources-pill-btn');
      const answerText = answer?.textContent || '';
      const sourceData = Array.isArray(sourceContainer?._sourcesData) ? sourceContainer._sourcesData : [];
      const citationBindings = [...(answer?.querySelectorAll('.jurix-citation[data-source-index]') || [])]
        .map((anchor) => {
          const sourceIndex = Number(anchor.dataset.sourceIndex);
          const source = sourceData.find((item) => Number(item?.citation_index) === sourceIndex);
          const citationLabel = anchor.getAttribute('aria-label') || anchor.textContent;
          const citationArticle = citationLabel.match(/\bArt\.?\s*(\d+)/i)?.[1] || null;
          const sourceArticle = String(source?.dispositivo_ref || source?.hierarchy || '')
            .match(/\bart\.?\s*(\d+)/i)?.[1] || null;
          return {
            sourceIndex,
            citationArticle,
            sourceArticle,
            resolved: Boolean(source && citationArticle && sourceArticle === citationArticle),
          };
        });
      return {
        answerCharCount: answerText.length,
        answerMentionsArticleLabels: /art\.?\s*\d+/i.test(answerText),
        answerContainsQuotedExcerpts: /[“”]/.test(answerText),
        headingCount: answer?.querySelectorAll('h1, h2, h3, h4, h5, h6').length || 0,
        citationLinkCount: answer?.querySelectorAll('a').length || 0,
        jurixCitationNodeCount: answer?.querySelectorAll('.jurix-citation, [data-source-index]').length || 0,
        hasRawCitationMarker: /\[\[\d+\]\]/.test(answerText),
        sourceCitationIndexes: sourceData.map((source) => Number(source?.citation_index)).filter(Number.isInteger),
        citationBindings,
        sourceCount: sourceData.length,
        sourceControlVisible: Boolean(sourceButton && sourceButton.getClientRects().length),
        statesCoverage: /amostra consultada (?:cobre|re[uú]ne trechos de)\s+\d+\s+(?:de|dos?)\s+\d+\s+artigos/i.test(answerText),
        statesNotIntegral: /n[aã]o (?:uma s[ií]ntese integral|permite resumir os demais assuntos|representa a totalidade|representa uma an[aá]lise integral)/i.test(answerText),
        statesAnnexOmission: /anexos?.{0,100}(?:n[aã]o entraram|fora da sele[cç][aã]o|consultados [aà] parte)/i.test(answerText),
      };
    });
    assert.equal(answerStreamResponse?.status(), 200);
    assert.ok(overviewUi.answerCharCount > 0);
    assert.ok(overviewUi.sourceCount > 0, JSON.stringify({
      uiSourceCount: overviewUi.sourceCount,
      retrievedSourceCount,
      coverage: {
        complete: coverage.complete,
        selected_articles: coverage.selected_articles,
        total_articles: coverage.total_articles,
        annexes_present: coverage.annexes_present,
      },
      reasonCode: overviewDoneEvent?.reason_code,
      grounded: overviewDoneEvent?.grounded,
    }));
    assert.ok(
      overviewUi.citationBindings.length >= 3 && overviewUi.citationBindings.every((binding) => binding.resolved),
      `every article citation label must resolve to the same article in its structured evidence: ${JSON.stringify({
        citationBindings: overviewUi.citationBindings,
        sourceCitationIndexes: overviewUi.sourceCitationIndexes,
      })}`,
    );
    assert.ok(
      overviewUi.sourceCount <= plannedSampleCount,
      `a whole-norm answer must not cite more excerpts than its adaptive sample: ${JSON.stringify({
        sourceCount: overviewUi.sourceCount,
        plannedSampleCount,
        selectedArticles,
      })}`,
    );
    assert.equal(coverageComplete, false, 'a partial archive extraction must not be reported as complete');
    assert.ok(Number.isInteger(selectedArticles) && Number.isInteger(totalArticles));
    assert.ok(selectedArticles < totalArticles, 'whole-norm retrieval must disclose its actual article coverage');
    assert.equal(overviewUi.statesCoverage, true, 'the answer must explain the sample coverage');
    assert.equal(
      overviewUi.statesNotIntegral,
      true,
      `the answer must explicitly describe partial scope: ${JSON.stringify({
        statesCoverage: overviewUi.statesCoverage,
        statesNotIntegral: overviewUi.statesNotIntegral,
        statesAnnexOmission: overviewUi.statesAnnexOmission,
        headingCount: overviewUi.headingCount,
        citationLinkCount: overviewUi.citationLinkCount,
        jurixCitationNodeCount: overviewUi.jurixCitationNodeCount,
        hasRawCitationMarker: overviewUi.hasRawCitationMarker,
        sourceCitationIndexes: overviewUi.sourceCitationIndexes,
        streamCitationMarkers,
        doneCitationMarkers,
        doneGrounded: overviewDoneEvent?.grounded === true,
        doneReasonCode: overviewDoneEvent?.reason_code || null,
        citationRendererProbe,
        assistantMessageCount: await overviewPage.$$eval('.message-assistant .message-body', (nodes) => nodes.length),
      })}`
    );
    assert.ok(
      overviewUi.citationLinkCount >= 3,
      `a partial overview must render links for the evidence it cites: ${JSON.stringify({
        citationLinkCount: overviewUi.citationLinkCount,
        jurixCitationNodeCount: overviewUi.jurixCitationNodeCount,
        hasRawCitationMarker: overviewUi.hasRawCitationMarker,
        sourceCitationIndexes: overviewUi.sourceCitationIndexes,
        streamCitationMarkers,
        doneCitationMarkers,
        doneGrounded: overviewDoneEvent?.grounded === true,
        doneReasonCode: overviewDoneEvent?.reason_code || null,
        citationRendererProbe,
      })}`
    );
    assert.ok(overviewGenerationAttempts.length > 0, 'the overview must exercise the configured local model');
    assert.ok(Number(overviewGenerationMs) > 0);
    assert.equal(overviewUi.sourceControlVisible, true, 'sources must be present without refresh');
    const overviewSourceControlLayout = await overviewPage.evaluate(() => {
      const button = [...document.querySelectorAll('.message-assistant .jurix-sources-pill-btn')].at(-1);
      if (!button) throw new Error('the completed overview has no sources control');
        const rect = button.getBoundingClientRect();
        const composer = document.querySelector('#conversation-input-bar')?.getBoundingClientRect();
        const scroller = document.querySelector('#messages-container')?.getBoundingClientRect();
        const unobscuredBottom = Math.min(composer?.top ?? window.innerHeight, scroller?.bottom ?? window.innerHeight);
        return {
          bottom: rect.bottom,
          unobscuredBottom,
          hitTargetIsSourceControl: document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2)
            ?.closest('.jurix-sources-pill-btn') === button,
        };
    });
    assert.ok(
      overviewSourceControlLayout.bottom <= overviewSourceControlLayout.unobscuredBottom,
      `latest consulted-sources control must not be hidden behind the fixed composer: ${JSON.stringify({
        bottom: overviewSourceControlLayout.bottom,
        unobscuredBottom: overviewSourceControlLayout.unobscuredBottom,
      })}`,
    );
    assert.ok(
      overviewSourceControlLayout.hitTargetIsSourceControl,
      'the latest consulted-sources control must remain the hit target before the user scrolls or focuses it',
    );
    const overviewScreenshot = path.join(resolvedEvidenceDir, 'whole-norm-overview.png');
    await overviewPage.setViewport({ width: 1280, height: 900 });
    await overviewPage.evaluate(() => {
      document.querySelector('.message-assistant .message-body')?.scrollIntoView({ block: 'start' });
    });
    await overviewPage.screenshot({ path: overviewScreenshot });
    await overviewPage.$eval('.message-assistant .jurix-sources-pill-btn', (button) => {
      button.scrollIntoView({ block: 'center' });
    });
    await overviewPage.click('.message-assistant .jurix-sources-pill-btn');
    await overviewPage.waitForFunction(() =>
      document.querySelector('#jurix-sources-drawer-panel')?.getAttribute('aria-hidden') === 'false');
    await overviewPage.waitForFunction(() => {
      const panel = document.querySelector('#jurix-sources-drawer-panel');
      return panel?.contains(document.activeElement);
    }, { timeout: 3000 });
    const overviewDrawerInitial = await overviewPage.evaluate(() => ({
      groupCount: document.querySelectorAll('#jurix-sources-drawer-body details.jurix-source-group').length,
      evidenceCardCount: document.querySelectorAll('#jurix-sources-drawer-body .source-card').length,
      openGroupCount: [...document.querySelectorAll('#jurix-sources-drawer-body details.jurix-source-group')]
        .filter((group) => group.open).length,
      toggleText: document.querySelector('.jurix-source-group-toggle-all')?.textContent?.trim() || '',
      allGroupTitlesPresent: [...document.querySelectorAll('#jurix-sources-drawer-body .jurix-source-group__title')]
        .every((title) => title.textContent.trim().length > 0),
    }));
    assert.equal(overviewDrawerInitial.groupCount, 1,
      'evidence citations from the same law must be grouped under one normative source');
    assert.equal(overviewDrawerInitial.evidenceCardCount, overviewUi.sourceCount,
      'the grouped law must retain every cited evidence card');
    assert.ok(overviewDrawerInitial.evidenceCardCount >= overviewDrawerInitial.groupCount,
      'each source group must expose its evidence cards');
    assert.equal(overviewDrawerInitial.openGroupCount, 0, 'source groups start collapsed');
    assert.equal(overviewDrawerInitial.toggleText, 'Expandir todas as evidências');
    assert.equal(overviewDrawerInitial.allGroupTitlesPresent, true);
    await overviewPage.focus('#jurix-sources-drawer-body .jurix-source-group-toggle-all');
    assert.equal(
      await overviewPage.evaluate(() => document.activeElement?.matches('.jurix-source-group-toggle-all')),
      true,
      'the expand-all button must receive keyboard focus before Enter is tested',
    );
    await overviewPage.keyboard.press('Enter');
    await overviewPage.waitForFunction(() =>
      document.querySelector('.jurix-source-group-toggle-all')?.dataset.state === 'all-open');
    const overviewDrawerExpanded = await overviewPage.evaluate(() => ({
      groupCount: document.querySelectorAll('#jurix-sources-drawer-body details.jurix-source-group').length,
      openGroupCount: [...document.querySelectorAll('#jurix-sources-drawer-body details.jurix-source-group')]
        .filter((group) => group.open).length,
      toggleText: document.querySelector('.jurix-source-group-toggle-all')?.textContent?.trim() || '',
      ariaExpanded: document.querySelector('.jurix-source-group-toggle-all')?.getAttribute('aria-expanded'),
    }));
    assert.equal(overviewDrawerExpanded.openGroupCount, overviewDrawerExpanded.groupCount);
    assert.equal(overviewDrawerExpanded.toggleText, 'Recolher todas as evidências');
    assert.equal(overviewDrawerExpanded.ariaExpanded, 'true');
    await overviewPage.focus('#jurix-sources-drawer-body .jurix-source-group-toggle-all');
    await overviewPage.keyboard.press('Enter');
    await overviewPage.waitForFunction(() =>
      document.querySelector('.jurix-source-group-toggle-all')?.dataset.state === 'all-closed');
    assert.equal(overviewErrors.length, 0);
    wholeNormOverview = {
      route,
      streamHttpStatus: answerStreamResponse.status(),
      selectedArticles,
      totalArticles,
      plannedSampleCount,
      coverageComplete,
      sourceCount: overviewUi.sourceCount,
      retrievedSourceCount,
      answerCharCount: overviewUi.answerCharCount,
      answerMentionsArticleLabels: overviewUi.answerMentionsArticleLabels,
      answerContainsQuotedExcerpts: overviewUi.answerContainsQuotedExcerpts,
      headingCount: overviewUi.headingCount,
      citationLinkCount: overviewUi.citationLinkCount,
      jurixCitationNodeCount: overviewUi.jurixCitationNodeCount,
      hasRawCitationMarker: overviewUi.hasRawCitationMarker,
      sourceCitationIndexes: overviewUi.sourceCitationIndexes,
      citationBindings: overviewUi.citationBindings,
      streamCitationMarkers,
      doneCitationMarkers,
      doneGrounded: overviewDoneEvent?.grounded === true,
      doneReasonCode: overviewDoneEvent?.reason_code || null,
      corpusCoverageStatus: corpusCoverage.coverage_status,
      corpusCoverageScopeCount: coverageScopeCount,
      citationRendererProbe,
      jurixCitationNodeCount: overviewUi.jurixCitationNodeCount,
      hasRawCitationMarker: overviewUi.hasRawCitationMarker,
      sourceCitationIndexes: overviewUi.sourceCitationIndexes,
      citationBindings: overviewUi.citationBindings,
      sourceControlVisibleWithoutRefresh: overviewUi.sourceControlVisible,
      sourceDrawerGroups: overviewDrawerInitial.groupCount,
      sourceDrawerEvidenceCards: overviewDrawerInitial.evidenceCardCount,
      sourceDrawerGroupsStartCollapsed: overviewDrawerInitial.openGroupCount === 0,
      expandAllButtonStateUpdates: overviewDrawerExpanded.toggleText === 'Recolher todas as evidências'
        && overviewDrawerExpanded.ariaExpanded === 'true',
      collapseAllReturnsToCollapsedState: true,
      statesCoverage: overviewUi.statesCoverage,
      statesNotIntegral: overviewUi.statesNotIntegral,
      statesAnnexOmission: overviewUi.statesAnnexOmission,
      ollamaGenerationAttempts: overviewGenerationAttempts.length,
      backendGenerationMs: overviewGenerationMs,
      grounded: overviewDoneEvent?.grounded === true,
      reasonCode: overviewDoneEvent?.reason_code || null,
      validationScope: overviewDoneEvent?.contract?.grounding?.validation_scope || null,
      uncaughtBrowserErrors: overviewErrors.length,
      screenshot: overviewScreenshot,
      answerAndSourceTextStoredInEvidence: false,
    };
  } finally {
    await overviewContext.close();
  }

  const cancelContext = await browser.createBrowserContext();
  let cancellation;
  try {
    const cancelPage = await cancelContext.newPage();
    const cancelErrors = [];
    cancelPage.on('pageerror', (error) => cancelErrors.push(error.name));
    const cancellationStreams = [];
    cancelPage.on('response', (response) => {
      if (new URL(response.url()).pathname === '/api/v1/search/answer/stream/') {
        cancellationStreams.push(response);
      }
    });
    const cancelPageResponse = await cancelPage.goto(new URL(route, baseUrl).href, {
      waitUntil: 'domcontentloaded',
      timeout: 20000,
    });
    assert.equal(cancelPageResponse?.status(), 200);
    await cancelPage.$eval('#question-textarea', (input, value) => {
      input.value = value;
      input.dispatchEvent(new Event('input', { bubbles: true }));
    }, 'Explique a diferença entre os arts. 17 e 18 da Lei Complementar nº 120/2010 e cite os dois dispositivos.');
    await cancelPage.evaluate(() => document.getElementById('chat-form').requestSubmit());
    await cancelPage.waitForFunction(() => {
      const button = document.getElementById('send-button');
      const answer = document.querySelector('.message-assistant .message-body');
      return button?.dataset.action === 'stop' && answer?.textContent?.trim().length > 0
        && !answer.querySelector('.jurix-answer-pending') && answer.hasAttribute('data-streaming');
    }, { timeout: 180000 });
    const partialTextLength = await cancelPage.$eval(
      '.message-assistant .message-body',
      (answer) => answer.textContent.trim().length,
    );
    assert.ok(partialTextLength > 0, 'the real model must produce visible text before cancellation');
    await cancelPage.click('#send-button');
    await cancelPage.waitForFunction(() => Boolean(
      document.querySelector('.message-assistant .jurix-stream-interrupted-note')
      && document.querySelector('.message-assistant .jurix-interrupted-retry:not(:disabled)')
      && document.getElementById('send-button')?.dataset.action === 'send'
    ), { timeout: 15000 });
    const cancelledUi = await cancelPage.evaluate(() => {
      const message = document.querySelector('.message-assistant');
      const answer = message?.querySelector('.message-body');
      const sources = answer?.closest('.message-content')?.querySelector('[id^="sources-"]');
      const badge = sources?.querySelector('.jurix-sources-pill-badge');
      return {
        userTurnCount: document.querySelectorAll('.message-user').length,
        assistantTurnCount: document.querySelectorAll('.message-assistant .message-body').length,
        answerTextLength: answer?.textContent?.trim().length || 0,
        interruptedNoticeVisible: Boolean(message?.querySelector('.jurix-stream-interrupted-note')),
        retryVisible: Boolean(message?.querySelector('.jurix-interrupted-retry')),
        sourcesMarkedCancelled: sources?._sourcesMeta?.cancelled === true,
        sourcesPending: sources?._sourcesMeta?.pending === true,
        badgeText: badge?.textContent?.trim() || '',
        copyActionVisible: Boolean(message?.querySelector('.copy-response-button.show')),
      };
    });
    assert.equal(cancelledUi.userTurnCount, 1, 'cancelling must not duplicate the user question');
    assert.equal(cancelledUi.assistantTurnCount, 1);
    assert.equal(cancelledUi.interruptedNoticeVisible, true);
    assert.equal(cancelledUi.retryVisible, true);
    assert.equal(cancelledUi.sourcesMarkedCancelled, true, 'in-flight evidence must not look validated after cancellation');
    assert.equal(cancelledUi.sourcesPending, false);
    assert.match(cancelledUi.badgeText, /n[aã]o validadas/i);
    assert.equal(cancelledUi.copyActionVisible, false, 'cancelled partial text must not expose the completed-answer copy action');
    assert.equal(cancelErrors.length, 0);

    await cancelPage.click('.message-assistant .jurix-interrupted-retry');
    await cancelPage.waitForFunction(() => {
      const button = document.getElementById('send-button');
      const answer = document.querySelector('.message-assistant .message-body');
      return button?.dataset.action === 'stop' && answer?.textContent?.trim().length > 0
        && !answer.querySelector('.jurix-answer-pending') && answer.hasAttribute('data-streaming');
    }, { timeout: 180000 });
    await cancelPage.waitForFunction(() => {
      const button = document.getElementById('send-button');
      const answer = document.querySelector('.message-assistant .message-body');
      return button?.dataset.action === 'send' && answer?.textContent?.trim().length > 0
        && !answer.querySelector('.jurix-answer-pending') && !answer.hasAttribute('data-streaming');
    }, { timeout: 180000 });
    assert.equal(cancellationStreams.length, 2, 'retry must issue exactly one new streaming request');
    const retryEvents = (await cancellationStreams[1].text()).split(/\r?\n/)
      .filter((line) => line.startsWith('data:'))
      .map((line) => JSON.parse(line.slice(5).trim()));
    const retryDone = retryEvents.find((event) => event.type === 'done');
    assert.ok(retryDone, 'the retry must complete normally');
    assert.ok((retryDone.contract?.generation_attempts || []).length > 0, 'the retry must reach the local model');
    const retriedUi = await cancelPage.evaluate(() => {
      const answer = document.querySelector('.message-assistant .message-body');
      const message = answer?.closest('.message-assistant');
      const sources = answer?.closest('.message-content')?.querySelector('[id^="sources-"]');
      return {
        userTurnCount: document.querySelectorAll('.message-user').length,
        assistantTurnCount: document.querySelectorAll('.message-assistant .message-body').length,
        answerTextLength: answer?.textContent?.trim().length || 0,
        sourceCount: Array.isArray(sources?._sourcesData) ? sources._sourcesData.length : 0,
        sourcesStillMarkedCancelled: sources?._sourcesMeta?.cancelled === true,
        copyActionVisible: Boolean(message?.querySelector('.copy-response-button.show')),
        retryActionVisible: Boolean(message?.querySelector('.jurix-interrupted-retry')),
      };
    });
    assert.equal(retriedUi.userTurnCount, 1, 'retry must reuse, not duplicate, the user turn');
    assert.equal(retriedUi.assistantTurnCount, 1, 'retry must replace, not duplicate, the assistant turn');
    assert.ok(retriedUi.answerTextLength > 0);
    assert.ok(retriedUi.sourceCount > 0, 'completed retry must restore its grounded sources');
    assert.equal(retriedUi.sourcesStillMarkedCancelled, false, 'completed retry must not retain cancelled source state');
    assert.equal(retriedUi.copyActionVisible, true, 'copy becomes available only after retry completes');
    assert.equal(retriedUi.retryActionVisible, false);

    await cancelPage.$eval('#question-textarea', (input, value) => {
      input.value = value;
      input.dispatchEvent(new Event('input', { bubbles: true }));
    }, 'O que prevê o art. 1º da Lei Complementar nº 99.999/2099?');
    await cancelPage.evaluate(() => document.getElementById('chat-form').requestSubmit());
    await cancelPage.waitForFunction(() => {
      const button = document.getElementById('send-button');
      const answers = document.querySelectorAll('.message-assistant .message-body');
      const answer = answers[answers.length - 1];
      return answers.length === 2 && button?.dataset.action === 'send'
        && answer?.textContent?.trim().length > 0 && !answer.querySelector('.jurix-answer-pending')
        && !answer.hasAttribute('data-streaming');
    }, { timeout: 30000 });
    assert.equal(cancellationStreams.length, 3, 'the insufficient-evidence follow-up must make one new request');
    const insufficientEvents = (await cancellationStreams[2].text()).split(/\r?\n/)
      .filter((line) => line.startsWith('data:'))
      .map((line) => JSON.parse(line.slice(5).trim()));
    const insufficientSources = insufficientEvents.find((event) => event.type === 'sources');
    const insufficientDone = insufficientEvents.find((event) => event.type === 'done');
    const insufficientStatus = insufficientEvents
      .filter((event) => event.type === 'status')
      .map((event) => event.status);
    assert.deepEqual(insufficientSources?.sources, []);
    assert.equal(insufficientDone?.grounded, false);
    assert.equal(insufficientDone?.reason_code, 'qa_archive_no_match');
    const insufficientUi = await cancelPage.evaluate(() => {
      const answers = [...document.querySelectorAll('.message-assistant .message-body')];
      const answer = answers[answers.length - 1];
      const sources = answer?.closest('.message-content')?.querySelector('[id^="sources-"]');
      const text = answer?.textContent || '';
      return {
        userTurnCount: document.querySelectorAll('.message-user').length,
        assistantTurnCount: answers.length,
        answerCharCount: text.trim().length,
        hasSourcesControl: Boolean(sources?.querySelector('.jurix-sources-pill-btn')),
        hasSourceData: Array.isArray(sources?._sourcesData) && sources._sourcesData.length > 0,
        hasCitationLinks: Boolean(answer?.querySelector('a')),
        explainsLocalCorpusGap: /n[aã]o encontrei|n[aã]o localizei|trecho leg[ií]vel|acervo hist[oó]rico/i.test(text),
        falselyClaimsNormDoesNotExist: /a norma n[aã]o existe|n[aã]o existe no mundo/i.test(text),
        showsGenericConnectionError: /conex[aã]o indispon[ií]vel|verifique sua conex[aã]o/i.test(text),
        priorGroundedSourcePillCount: document.querySelectorAll('.message-assistant .jurix-sources-pill-btn').length,
      };
    });
    assert.equal(insufficientUi.userTurnCount, 2);
    assert.equal(insufficientUi.assistantTurnCount, 2);
    assert.ok(insufficientUi.answerCharCount > 0);
    assert.equal(insufficientUi.hasSourcesControl, false, 'the no-match answer must not reuse the retry sources');
    assert.equal(insufficientUi.hasSourceData, false);
    assert.equal(insufficientUi.hasCitationLinks, false);
    assert.equal(insufficientUi.explainsLocalCorpusGap, true);
    assert.equal(insufficientUi.falselyClaimsNormDoesNotExist, false);
    assert.equal(insufficientUi.showsGenericConnectionError, false);
    assert.equal(insufficientUi.priorGroundedSourcePillCount, 1, 'only the grounded retry retains its own source control');
    assert.ok(insufficientStatus.includes('insufficient_evidence'));
    cancellation = {
      pageStatus: cancelPageResponse.status(),
      partialTextLength,
      ...cancelledUi,
      retry: {
        streamHttpStatus: cancellationStreams[1].status(),
        generationAttempts: retryDone.contract.generation_attempts.length,
        ...retriedUi,
      },
      insufficientEvidenceAfterRetry: {
        streamHttpStatus: cancellationStreams[2].status(),
        reasonCode: insufficientDone.reason_code,
        statusEvents: insufficientStatus,
        ...insufficientUi,
      },
      uncaughtBrowserErrors: cancelErrors.length,
      answerAndSourceTextStoredInEvidence: false,
    };
  } finally {
    await cancelContext.close();
  }

  const relationContext = await browser.createBrowserContext();
  let relationSmoke;
  try {
    const relationPage = await relationContext.newPage();
    const relationErrors = [];
    relationPage.on('pageerror', (error) => relationErrors.push(error.name));
    let relationStream = null;
    relationPage.on('response', (response) => {
      if (new URL(response.url()).pathname === '/api/v1/search/answer/stream/') {
        relationStream = response;
      }
    });
    const relationPageResponse = await relationPage.goto(new URL('/assistente/', baseUrl).href, {
      waitUntil: 'domcontentloaded',
      timeout: 20000,
    });
    assert.equal(relationPageResponse?.status(), 200);
    await relationPage.click('.figma-search-dropdown[data-control="norma_status"]');
    await relationPage.evaluate(() => {
      const option = [...document.querySelectorAll('.jurix-control-option')]
        .find((button) => button.textContent.trim() === 'Todas as normas indexadas');
      if (!option) throw new Error('the norma-scope menu did not expose its all-indexed option');
      option.click();
    });
    assert.equal(await relationPage.evaluate(() => {
      return JSON.parse(localStorage.getItem('jurix:search-options:v1') || '{}').norma_status;
    }), 'all', 'the relation smoke must use the visible all-indexed-norms control');
    await relationPage.$eval('#question-textarea', (input, value) => {
      input.value = value;
      input.dispatchEvent(new Event('input', { bubbles: true }));
    }, 'A Lei nº 9002/2021 modifica algum dispositivo da Lei nº 9001/2020? Diferencie essa alteração de uma simples referência, identifique o artigo de origem e o artigo alterado, e indique o que ainda é incerto.');
    await relationPage.evaluate(() => document.getElementById('chat-form').requestSubmit());
    await relationPage.waitForFunction(() => {
      const button = document.getElementById('send-button');
      const answer = document.querySelector('.message-assistant .message-body');
      return button?.dataset.action === 'send' && answer?.textContent?.trim().length > 0
        && !answer.querySelector('.jurix-answer-pending') && !answer.hasAttribute('data-streaming');
    }, { timeout: 180000 });
    assert.equal(relationStream?.status(), 200);
    const relationEvents = (await relationStream.text()).split(/\r?\n/)
      .filter((line) => line.startsWith('data:'))
      .map((line) => JSON.parse(line.slice(5).trim()));
    const relationSourceEvent = relationEvents.find((event) => event.type === 'sources');
    const relationDoneEvent = relationEvents.find((event) => event.type === 'done');
    const graphSources = (relationSourceEvent?.sources || [])
      .filter((source) => source?.graph_relation)
      .map((source) => ({
        action: source.graph_relation.action,
        role: source.graph_relation.role,
        resolution: source.graph_relation.resolution,
        reviewStatus: source.graph_relation.review_status,
      }));
    const relationUi = await relationPage.evaluate(() => {
      const answer = document.querySelector('.message-assistant .message-body');
      const sources = answer?.closest('.message-content')?.querySelector('[id^="sources-"]');
      return {
        answerLength: answer?.textContent?.trim().length || 0,
        partialNoticeVisible: answer?.textContent?.includes('A resposta foi limitada ao que as fontes consultadas permitem confirmar.') || false,
        draftNoticeVisible: answer?.textContent?.includes('Rascunho em geração') || false,
        sourceControlVisible: Boolean(sources?.querySelector('.jurix-sources-pill-btn')),
        sourceCount: Array.isArray(sources?._sourcesData) ? sources._sourcesData.length : 0,
        graphSourceCount: (Array.isArray(sources?._sourcesData) ? sources._sourcesData : [])
          .filter((source) => source?.graph_relation).length,
      };
    });
    assert.ok(graphSources.some((source) => source.action === 'ALTERA'),
      `the graph arm must expose the reviewed alteration as a source for the relation question: ${JSON.stringify({
        sourceCount: relationSourceEvent?.sources?.length || 0,
        sourceTrace: (relationSourceEvent?.sources || []).map((source) => ({
          citation_id: source?.citation_id,
          dispositivo_ref: source?.dispositivo_ref,
          graph_relation: source?.graph_relation || null,
        })),
        statusEvents: relationEvents.filter((event) => event.type === 'status').map((event) => event.status),
        doneReason: relationDoneEvent?.reason_code || null,
      })}`);
    assert.equal(relationUi.sourceControlVisible, true, 'relation sources must be available in the assistant UI');
    assert.ok(relationUi.sourceCount > 0, 'the completed answer must retain its cited source data');
    if (relationDoneEvent?.reason_code === 'generation_partial_after_grounded_prefix') {
      assert.equal(relationUi.partialNoticeVisible, true, 'a partial grounded answer must explain its limitation');
    }
    assert.equal(relationUi.draftNoticeVisible, false, 'the completed answer must not be presented as a generation draft');
    await relationPage.click('.message-assistant .jurix-sources-pill-btn');
    await relationPage.waitForSelector('.jurix-rag-source', { timeout: 5000 });
    const relationDrawer = await relationPage.$$eval('.jurix-rag-source', (cards) => cards.map((card) => ({
      text: card.textContent.replace(/\s+/g, ' ').trim().slice(0, 220),
      relationLabel: card.querySelector('.jurix-rag-source__contribution span:last-child')?.textContent?.trim() || '',
    })));
    assert.equal(relationErrors.length, 0);
    relationSmoke = {
      pageStatus: relationPageResponse.status(),
      streamHttpStatus: relationStream.status(),
      status: relationDoneEvent?.reason_code || (relationDoneEvent?.grounded ? 'grounded' : 'not_grounded'),
      answerLength: relationUi.answerLength,
      sourceCount: relationUi.sourceCount,
      graphSources,
      graphSourceCountInUi: relationUi.graphSourceCount,
      drawerSourceCards: relationDrawer,
      uncaughtBrowserErrors: relationErrors.length,
      responseTextStoredInEvidence: false,
    };
  } finally {
    await relationContext.close();
  }

  const historyContext = await browser.createBrowserContext();
  let temporalRag;
  try {
    const historyPage = await historyContext.newPage();
    const historyErrors = [];
    const historyStreams = [];
    historyPage.on('pageerror', (error) => historyErrors.push(error.name));
    historyPage.on('response', (response) => {
      if (new URL(response.url()).pathname === '/api/v1/search/answer/stream/') {
        historyStreams.push(response);
      }
    });
    const historyPageResponse = await historyPage.goto(new URL('/assistente/', baseUrl).href, {
      waitUntil: 'domcontentloaded',
      timeout: 20000,
    });
    assert.equal(historyPageResponse?.status(), 200);
    await historyPage.click('.figma-search-dropdown[data-control="norma_status"]');
    await historyPage.evaluate(() => {
      const option = [...document.querySelectorAll('.jurix-control-option')]
        .find((button) => button.textContent.trim() === 'Todas as normas indexadas');
      if (!option) throw new Error('the historical RAG smoke could not select all indexed norms');
      option.click();
    });
    const historicalQuestion = 'Qual era o prazo do Art. 5º da Lei nº 9001/2020?';
    const askAt = async (asOf) => {
      await historyPage.$eval('[data-jurix-as-of]', (input, value) => {
        input.value = value;
        input.dispatchEvent(new Event('change', { bubbles: true }));
      }, asOf);
      assert.equal(await historyPage.evaluate(() =>
        window.JurixSearchControls.getPayload().as_of), asOf,
      'the visible historical-date control must update the RAG request scope');
      await historyPage.$eval('#question-textarea', (input, value) => {
        input.value = value;
        input.dispatchEvent(new Event('input', { bubbles: true }));
      }, historicalQuestion);
      const expectedTurnCount = await historyPage.$$eval(
        '.message-assistant .message-body',
        (answers) => answers.length + 1,
      );
      await historyPage.evaluate(() => document.getElementById('chat-form').requestSubmit());
      await historyPage.waitForFunction((turnCount) => {
        const answers = [...document.querySelectorAll('.message-assistant .message-body')];
        const answer = answers.at(-1);
        const sendButton = document.getElementById('send-button');
        return answers.length === turnCount && sendButton && !sendButton.disabled
          && answer?.textContent?.trim() && !answer.querySelector('.jurix-answer-pending')
          && !answer.hasAttribute('data-streaming');
      }, { timeout: 180000 }, expectedTurnCount);
      const response = historyStreams.at(-1);
      assert.equal(response?.status(), 200);
      const events = (await response.text()).split(/\r?\n/)
        .filter((line) => line.startsWith('data:'))
        .map((line) => JSON.parse(line.slice(5).trim()));
      const sourceEvent = events.find((event) => event.type === 'sources');
      const doneEvent = events.find((event) => event.type === 'done');
      const streamCitationMarkerCount = events
        .filter((event) => event.type === 'chunk')
        .reduce((count, event) => count + (String(event.chunk || '').match(/\[\[\d+\]\]/g) || []).length, 0);
      const doneCitationMarkerCount = (String(doneEvent?.answer || '').match(/\[\[\d+\]\]/g) || []).length;
      const ui = await historyPage.evaluate(() => {
        const answers = [...document.querySelectorAll('.message-assistant .message-body')];
        const answer = answers.at(-1);
        const sources = answer?.closest('.message-content')?.querySelector('[id^="sources-"]');
        return {
          text: answer?.textContent || '',
          answerMentionsArticle: /art(?:igo)?\.?\s*5\b/i.test(answer?.textContent || ''),
          answerMentionsNorm: /lei\s+(?:complementar\s+)?n[º°o.]?\s*9?\.?001\s*\/\s*2020/i.test(answer?.textContent || ''),
          sources: Array.isArray(sources?._sourcesData) ? sources._sourcesData : [],
          citationLinkCount: answer?.querySelectorAll('a').length || 0,
          turns: answers.length,
        };
      });
      return {
        asOf,
        sourceCount: Array.isArray(sourceEvent?.sources) ? sourceEvent.sources.length : 0,
        sourceDeviceRefs: ui.sources.map((source) => String(source?.dispositivo_ref || '')).filter(Boolean),
        sourceNormRefs: ui.sources.map((source) => String(source?.norma_ref || '')).filter(Boolean),
        sourceVersionCount: ui.sources.filter((source) => Boolean(source?.temporal_version?.version_hash)).length,
        answerContainsTenDays: /dez\s+dias/i.test(ui.text),
        answerContainsTwentyDays: /vinte\s+dias/i.test(ui.text),
        answerMentionsArticle: ui.answerMentionsArticle,
        answerMentionsNorm: ui.answerMentionsNorm,
        citationLinkCount: ui.citationLinkCount,
        streamCitationMarkerCount,
        doneCitationMarkerCount,
        grounded: doneEvent?.grounded === true,
        reasonCode: doneEvent?.reason_code || null,
        groundingClaimCount: Array.isArray(doneEvent?.contract?.claim_report)
          ? doneEvent.contract.claim_report.length
          : 0,
        supportedGroundingClaimCount: Array.isArray(doneEvent?.contract?.claim_report)
          ? doneEvent.contract.claim_report.filter((claim) => claim?.supported === true).length
          : 0,
        supportedClaimsWithCitationIds: Array.isArray(doneEvent?.contract?.claim_report)
          ? doneEvent.contract.claim_report.filter((claim) => claim?.supported === true
            && Array.isArray(claim?.matches)
            && claim.matches.some((match) => Array.isArray(match?.citation_ids) && match.citation_ids.length > 0)).length
          : 0,
        turns: ui.turns,
      };
    };
    const beforeEffect = await askAt('2021-02-28');
    assert.ok(beforeEffect.sourceCount > 0, `the pre-effect snapshot must return evidence: ${JSON.stringify(beforeEffect)}`);
    assert.ok(beforeEffect.sourceDeviceRefs.some((ref) => /art\.?\s*5\b/i.test(ref)));
    assert.ok(beforeEffect.sourceNormRefs.some((ref) => ref.replace(/\D/g, '').includes('90012020')),
      `the historical source must retain Lei 9001/2020 identity: ${JSON.stringify(beforeEffect.sourceNormRefs)}`);
    assert.equal(beforeEffect.answerContainsTenDays, true,
      `the pre-effect response must use the ten-day version: ${JSON.stringify(beforeEffect)}`);
    assert.equal(beforeEffect.answerContainsTwentyDays, false);
    assert.ok(beforeEffect.sourceVersionCount > 0, 'historical evidence must carry an immutable version hash');

    const afterEffect = await askAt('2021-03-02');
    assert.ok(afterEffect.sourceCount > 0, `the post-effect snapshot must return evidence: ${JSON.stringify(afterEffect)}`);
    assert.ok(afterEffect.sourceDeviceRefs.some((ref) => /art\.?\s*5\b/i.test(ref)),
      `the post-effect source must remain the requested Art. 5: ${JSON.stringify(afterEffect)}`);
    assert.ok(afterEffect.sourceNormRefs.some((ref) => ref.replace(/\D/g, '').includes('90012020')),
      `the later historical source must retain Lei 9001/2020 identity: ${JSON.stringify(afterEffect.sourceNormRefs)}`);
    assert.equal(afterEffect.answerContainsTwentyDays, true,
      `the post-effect response must use the twenty-day version: ${JSON.stringify(afterEffect)}`);
    assert.equal(afterEffect.answerContainsTenDays, false);
    assert.ok(afterEffect.sourceVersionCount > 0);
    assert.equal(afterEffect.turns, 2, 'changing the date must append one turn, not duplicate earlier content');
    assert.equal(historyErrors.length, 0);
    temporalRag = {
      pageStatus: historyPageResponse.status(),
      beforeEffect,
      afterEffect,
      answerTextStoredInEvidence: false,
      uncaughtBrowserErrors: historyErrors.length,
    };
  } finally {
    await historyContext.close();
  }

  const trace = result.trace;
  const report = {
    dataset: 'authentic_historical_archive_qa_unreviewed',
    sourceDocumentState: 'human_review_pending',
    route,
    pageStatus: pageResponse.status(),
    streamHttpStatus: streamResponse.status(),
    eventOrder: eventTypes.filter((type, index) => ['sources', 'chunk', 'done'].includes(type) && (type !== 'chunk' || index === firstChunkIndex)),
    sourcesBeforeFirstChunk: sourcesIndex < firstChunkIndex,
    ollamaGenerationAttempts: generationAttempts.length,
    backendGenerationMs: generationMs,
    elapsedMs: Date.now() - startedAt,
    sourcesAvailableAfterMs: trace.sourcesAtMs,
    firstAnswerTextAfterMs: trace.firstTextAtMs,
    completionUiAtMs: trace.completionUiAtMs,
    answerVisibleBeforeCompletion: trace.firstTextAtMs < trace.completionUiAtMs,
    visibleStreamingLeadMs: trace.completionUiAtMs - trace.firstTextAtMs,
    answerCharCount: result.answerCharCount,
    headingCount: result.headingCount,
    paragraphCount: result.paragraphCount,
    listItemCount: result.listItemCount,
    headingPerArticlePatternObserved: result.headingCount >= 3,
    answerWasSafeAbstention: result.answerHasAbstention,
    answerMentionsArticle17: result.answerMentionsArticle17,
    answerMentionsArticle18: result.answerMentionsArticle18,
    sourceCount: result.sourceCount,
    sourceDeviceRefs: result.sourceDeviceRefs,
    citationLinksIncludeArticle17: result.citationLinksIncludeArticle17,
    citationLinksIncludeArticle18: result.citationLinksIncludeArticle18,
    article17LegalLinkHasTextFragment: result.article17LegalLinkHasTextFragment,
    article18LegalLinkHasTextFragment: result.article18LegalLinkHasTextFragment,
    normLegalLinkPresent: result.normLegalLinkPresent,
    normLegalLinkCheckApplicable: result.normLegalLinkPresent,
    normLegalLinkHasNoTextFragment: result.normLegalLinkHasNoTextFragment,
    sourceControlVisibleBeforeRefresh: result.sourceControlVisible,
    citationLinkCount: result.citationLinkCount,
    copiedMarkdownCitationChecks: copiedCitationChecks,
    citationLinksAreLocalOrOfficial: result.citationLinksAreLocalOrOfficial,
    sourceDrawerOpenedWithEvidence: drawerHasEvidence,
    clickedSourcePopupObserved: popupObserved,
    clickedSourceOpenedBrowserTarget: openedPdfTargets.length > 0,
    clickedSourceTargetOrigins: openedPdfTargets.map((href) => {
      try { return new URL(href).origin; } catch { return 'internal-viewer'; }
    }),
    pdfSourceInteraction: {
      pathname: pdfSource.pathname,
      target: pdfSource.target,
      visible: pdfSource.visible,
      pointerEvents: pdfSource.pointerEvents,
      hitTag: pdfSource.hitTag,
      hitClass: pdfSource.hitClass,
      pageUrlUnchanged: pageUrlAfterPdfClick === assistantRouteBeforePdfClick,
      click: pdfClickDiagnostic,
    },
    directPdfViewer: {
      status: directPdfResponse?.status() || null,
      contentType: directPdfResponse?.headers()?.['content-type'] || '',
      ...directPdfViewer,
    },
    citedPdfRoute: { status: pdfResponse.status, contentType: pdfResponse.contentType, bytes: pdfResponse.contentLength },
    escapeClosedDrawer: true,
    sourceDrawerFocusRestored,
    reloadRestoredAnswerAndSources: true,
    reloadPreservedConversationUrl: true,
    reloadRestoredCitationLinkCount: restoredState.citationLinkCount,
    followUp,
    archivePdfRouteAudit,
    uncaughtBrowserErrors: failures.length,
    responseContentStoredInEvidence: false,
    wholeNormOverview,
    cancellation,
    relationSmoke,
    temporalRag,
  };
  const outputPath = path.join(resolvedEvidenceDir, 'live-rag-browser-smoke.json');
  try {
    await fs.access(outputPath);
    throw new Error('Refusing to overwrite existing live RAG evidence.');
  } catch (error) {
    if (error?.code !== 'ENOENT') throw error;
  }
  await fs.writeFile(outputPath, `${JSON.stringify(report, null, 2)}\n`, { flag: 'wx' });
  console.log(JSON.stringify({ ...report, evidence: outputPath }, null, 2));
} finally {
  await browser.close();
}
