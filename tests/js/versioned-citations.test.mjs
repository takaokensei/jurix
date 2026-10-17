import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { JSDOM } from 'jsdom';

const JS_DIR = path.resolve(import.meta.dirname, '../../src/apps/core/static/js');
const exportFixturePath = path.resolve(import.meta.dirname, '../../src/tests/fixtures/evidence_export_parity.json');
const read = (file) => fs.readFileSync(path.join(JS_DIR, file), 'utf8');

function boot() {
  const dom = new JSDOM(
    '<!doctype html><html><body><div class="message"><div class="message-body"></div><button class="copy-response-button"></button></div></body></html>',
    { url: 'https://jurix.local/assistente/', runScripts: 'dangerously', pretendToBeVisual: true },
  );
  const { window } = dom;
  window.eval(read('jurix-markdown.js'));
  window.eval(read('jurix-rag.js'));
  window.eval(read('jurix-chat-renderer.js'));
  return window;
}

const historicalSource = {
  citation_index: 1,
  citation_id: `jurix:norma:31:version:${'b'.repeat(64)}:device:${'a'.repeat(64)}`,
  citation_label: 'Lei nº 8.205/2026, Art. 1º (redação projetada pelo Jurix em 2026-05-01)',
  pdf_url: 'https://sapl.natal.rn.leg.br/media/lei.pdf#:~:text=truncated-old-marker',
  full_text: 'Redação histórica completa.',
  temporal_version: { as_of: '2026-05-01', version_hash: 'b'.repeat(64) },
};

test('an invalid citation marker never falls through to a different source', () => {
  const window = boot();
  const html = window.JurixMarkdown.normalize('[[2]]', [historicalSource]);

  assert.equal(html, '[[2]]');
  assert.doesNotMatch(html, /jurix-citation/);
  window.close();
});

test('legacy sources without citation indexes retain their array-order contract', () => {
  const window = boot();
  const html = window.JurixMarkdown.normalize('[[1]]', [
    { citation_label: 'Lei nº 8.205/2026, Art. 1º' },
  ]);

  assert.match(html, /data-source-index="1"/);
  assert.match(html, /Lei nº 8\.205\/2026/);
  window.close();
});

test('inline citation displays its resolved legal device while retaining the source index', () => {
  const window = boot();
  const html = window.JurixMarkdown.normalize('A regra está em [[1]].', [{
    ...historicalSource,
    dispositivo_ref: 'Art. 2º > Inciso IV',
  }]);
  const rendered = new JSDOM(`<body>${html}</body>`).window.document.querySelector('.jurix-citation');

  assert.equal(rendered?.textContent, 'Art. 2º, inciso IV');
  assert.equal(rendered?.getAttribute('data-source-index'), '1');
  assert.match(rendered?.getAttribute('aria-label') || '', /Art\. 1º/);
  window.close();
});

test('inline bullet normalization does not turn a legal hyphen into a new list item', () => {
  const window = boot();
  const clause = 'Parágrafo Único - As demais gratificações permanecem regidas por lei específica.';
  const inlineBullets = '• primeira hipótese • segunda hipótese';

  assert.equal(window.JurixMarkdown.normalize(clause), clause);
  assert.equal(
    window.JurixMarkdown.normalize(inlineBullets),
    '• primeira hipótese\n• segunda hipótese',
  );
  window.close();
});

test('historical source navigation opens the official base without a text fragment', () => {
  const window = boot();
  const href = window.JurixRagUI.buildSourceUrl(historicalSource);

  assert.equal(href, 'https://sapl.natal.rn.leg.br/media/lei.pdf');
  window.close();
});

test('copied response retains a Markdown citation to the unmarked official source', async () => {
  const window = boot();
  const copied = [];
  Object.defineProperty(window.navigator, 'clipboard', {
    configurable: true,
    value: { writeText: async (value) => copied.push(value) },
  });
  const button = window.document.querySelector('.copy-response-button');
  button._citationSources = [historicalSource];

  await window.JurixChatRenderer.copyResponseToClipboard(
    'Conforme [[1]], aplica-se a redação histórica.',
    button,
  );

  assert.equal(copied.length, 1);
  assert.match(copied[0], /\[Lei nº 8\.205\/2026, Art\. 1º \(redação projetada pelo Jurix em 2026-05-01\)\]/);
  assert.match(copied[0], /<https:\/\/sapl\.natal\.rn\.leg\.br\/media\/lei\.pdf>/);
  assert.doesNotMatch(copied[0], /#:~:text=/);
  window.close();
});

test('evidence JSON export is versioned, source-linked, and excludes arbitrary fields', () => {
  const window = boot();
  const packageDto = window.JurixChatRenderer.buildEvidencePackage([{
    ...historicalSource,
    norma_ref: 'Lei nº 8.205/2026',
    dispositivo_ref: 'Art. 1º',
    source_url: 'https://sapl.natal.rn.leg.br/media/lei.pdf#:~:text=old',
    contribution: 'Institui a política',
    evidence_text: 'Redação consolidada.',
    document_sha256: 'a'.repeat(64),
    page: 2,
    span: { start: 8, end: 32, raw_text: 'must-not-export' },
    span_basis: 'normalized_legal_text',
    private_token: 'must-not-export',
  }], { revision: 'r7', digest: 'c'.repeat(64), completeness: 'partial', source: 'municipal-natal', secret: 'must-not-export' }, {
    coverage_status: 'partial',
    corpus_revision: { revision: 7, digest: 'c'.repeat(64) },
    scope_limited: true,
    checked_until: '2024-12-31',
    sources_checked: [{
      source: 'sapl',
      jurisdiction: 'BR-RN-NATAL',
      series: 'municipal_lc',
      period_start: '2010-01-01',
      period_end: '2024-12-31',
      checked_until: '2024-12-31',
      source_checksum: 'd'.repeat(64),
      coverage_status: 'partial',
      missing_intervals: [{ start: '2015-01-01', end: '2015-12-31', internal_path: 'must-not-export' }],
      pending_review: 4,
      internal_path: 'C:/private/archive',
    }],
    missing_intervals: [{
      source: 'sapl',
      jurisdiction: 'BR-RN-NATAL',
      series: 'municipal_lc',
      start: '2015-01-01',
      end: '2015-12-31',
      internal_path: 'must-not-export',
    }],
    pending_review: 4,
    reason: 'registered_scopes_only_not_a_universal_completeness_claim',
    private_key: 'must-not-export',
  });

  assert.equal(packageDto.schema_version, 'jurix-evidence-v1');
  assert.equal(packageDto.sources[0].citation_id, historicalSource.citation_id);
  assert.equal(packageDto.sources[0].official_url, 'https://sapl.natal.rn.leg.br/media/lei.pdf');
  assert.equal(packageDto.sources[0].temporal_version.version_hash, 'b'.repeat(64));
  assert.equal(packageDto.sources[0].document_sha256, 'a'.repeat(64));
  assert.equal(packageDto.sources[0].page, 2);
  assert.deepEqual({ ...packageDto.sources[0].span }, { start: 8, end: 32 });
  assert.equal(packageDto.sources[0].span_basis, 'normalized_legal_text');
  assert.deepEqual({ ...packageDto.corpus_revision }, { revision: 'r7', digest: 'c'.repeat(64), source: 'municipal-natal', completeness: 'partial' });
  assert.deepEqual(JSON.parse(JSON.stringify(packageDto.corpus_coverage)), {
    coverage_status: 'partial',
    corpus_revision: { revision: 7, digest: 'c'.repeat(64) },
    scope_limited: true,
    checked_until: '2024-12-31',
    sources_checked: [{
      source: 'sapl',
      jurisdiction: 'BR-RN-NATAL',
      series: 'municipal_lc',
      period_start: '2010-01-01',
      period_end: '2024-12-31',
      checked_until: '2024-12-31',
      source_checksum: 'd'.repeat(64),
      coverage_status: 'partial',
      missing_intervals: [{ start: '2015-01-01', end: '2015-12-31' }],
      pending_review: 4,
      last_success_at: null,
    }],
    missing_intervals: [{
      source: 'sapl',
      jurisdiction: 'BR-RN-NATAL',
      series: 'municipal_lc',
      start: '2015-01-01',
      end: '2015-12-31',
    }],
    pending_review: 4,
    reason: 'registered_scopes_only_not_a_universal_completeness_claim',
  });
  assert.doesNotMatch(JSON.stringify(packageDto), /must-not-export/);
  assert.doesNotMatch(JSON.stringify(packageDto), /C:\\/);
  assert.equal(window.JurixChatRenderer.buildEvidencePackage([{ private_token: 'secret' }]).sources.length, 0);
  window.close();
});

test('evidence JSON export rejects impossible publication, effective, and snapshot dates', () => {
  const window = boot();
  const packageDto = window.JurixChatRenderer.buildEvidencePackage([{
    ...historicalSource,
    data_publicacao: '2026-02-30',
    data_vigencia: '2026-13-01',
    temporal_version: {
      as_of: '2026-02-30',
      effective_on: '2026-02-30',
      version_hash: 'e'.repeat(64),
    },
  }]);

  assert.equal(packageDto.sources[0].publication_date, null);
  assert.equal(packageDto.sources[0].effective_date, null);
  assert.equal(packageDto.sources[0].temporal_version, null);
  window.close();
});

test('browser evidence DTO matches the shared Python export contract fixture', () => {
  const window = boot();
  const fixture = JSON.parse(fs.readFileSync(exportFixturePath, 'utf8'));
  const NativeDate = window.Date;
  window.Date = class extends NativeDate {
    constructor(...args) {
      super(...(args.length ? args : [fixture.generated_at]));
    }

    static now() {
      return NativeDate.parse(fixture.generated_at);
    }
  };
  const packageDto = window.JurixChatRenderer.buildEvidencePackage(
    [fixture.source],
    fixture.corpus_revision,
    fixture.corpus_coverage,
  );
  const expected = fixture.expected;

  assert.equal(packageDto.schema_version, expected.schema_version);
  assert.equal(packageDto.generated_at, expected.generated_at);
  assert.deepEqual(JSON.parse(JSON.stringify(packageDto.corpus_revision)), expected.corpus_revision);
  assert.deepEqual(JSON.parse(JSON.stringify(packageDto.corpus_coverage)), expected.corpus_coverage);
  assert.equal(packageDto.sources.length, 1);
  const source = packageDto.sources[0];
  const selectedFields = Object.fromEntries(
    Object.keys(expected.source_fields).map((key) => [key, source[key]]),
  );
  assert.deepEqual(JSON.parse(JSON.stringify(selectedFields)), expected.source_fields);
  assert.equal(source.span.raw_text, undefined);
  window.close();
});

test('browser evidence package sorts citations like Python, including missing indexes and ties', () => {
  const window = boot();
  const packageDto = window.JurixChatRenderer.buildEvidencePackage([
    { citation_id: 'z-unindexed', citation_label: 'Sem índice Z' },
    { citation_id: 'b-invalid-index', citation_index: -1, citation_label: 'Índice inválido' },
    { citation_id: 'c-indexed', citation_index: 2, citation_label: 'Índice 2' },
    { citation_id: 'z-tied', citation_index: 1, citation_label: 'Índice 1 Z' },
    { citation_id: 'a-tied', citation_index: 1, citation_label: 'Índice 1 A' },
    { citation_id: 'a-unindexed', citation_label: 'Sem índice A' },
  ]);

  assert.deepEqual(
    packageDto.sources.map(({ citation_id }) => citation_id),
    ['a-tied', 'z-tied', 'c-indexed', 'a-unindexed', 'b-invalid-index', 'z-unindexed'],
  );
  window.close();
});

test('evidence export keeps allowlisted graph events, snapshot identity, and verification limits', () => {
  const window = boot();
  const packageDto = window.JurixChatRenderer.buildEvidencePackage([{
    ...historicalSource,
    evidence_scope: 'reviewed_norma',
    graph_relation: {
      event_id: 'event-17',
      action: 'REVOGA',
      review_status: 'approved',
      effective_status: 'effective',
      effective_on: '2025-01-01',
      publication_on: '2024-12-20',
      quote: 'Revoga o dispositivo anterior.',
      api_key: 'must-not-export',
    },
    temporal_version: {
      ...historicalSource.temporal_version,
      input_hash: 'c'.repeat(64),
      snapshot_id: 42,
      status_note: 'Texto projetado para a data consultada.',
    },
    coverage: {
      as_of: '2026-05-01',
      status: 'complete',
      complete: true,
      snapshot_id: 42,
      version_hash: 'b'.repeat(64),
      input_hash: 'c'.repeat(64),
      policy: 'normative-projection-v1',
      projected_devices: 12,
      selected_devices: 12,
      internal_path: 'C:/private',
    },
    private_token: 'must-not-export',
  }]);
  const source = packageDto.sources[0];
  const markdown = window.JurixChatRenderer.renderEvidenceMarkdown(packageDto);

  assert.equal(source.graph_relation.event_id, 'event-17');
  assert.equal(source.graph_relation.action, 'REVOGA');
  assert.equal(source.graph_relation.api_key, undefined);
  assert.equal(source.temporal_version.snapshot_id, 42);
  assert.equal(source.temporal_version.input_hash, 'c'.repeat(64));
  assert.equal(source.projection_coverage.selected_devices, 12);
  assert.match(source.verification_limit, /não determina aplicabilidade/);
  assert.match(markdown, /Snapshot: `42`/);
  assert.match(markdown, /Relação: REVOGA/);
  assert.match(markdown, /Limite da verificação/);
  assert.doesNotMatch(JSON.stringify(packageDto), /must-not-export|C:\\/);
  window.close();
});

test('evidence export labels local archive and incomplete historical verification limits', () => {
  const window = boot();
  const packageDto = window.JurixChatRenderer.buildEvidencePackage([
    { citation_id: 'archive-1', evidence_scope: 'isolated_qa_archive' },
    {
      ...historicalSource,
      citation_id: 'historical-2',
      citation_index: 2,
      coverage: { complete: false },
    },
  ]);

  const archiveSource = packageDto.sources.find((source) => source.citation_id === 'archive-1');
  const historical = packageDto.sources.find((source) => source.citation_id === 'historical-2');
  assert.match(archiveSource.verification_limit, /revisão jurídica/);
  assert.match(historical.verification_limit, /parcial ou incompleta/);
  window.close();
});

test('evidence Markdown export keeps citations, coverage limits, and omits private fields', () => {
  const window = boot();
  const packageDto = window.JurixChatRenderer.buildEvidencePackage([{
    ...historicalSource,
    citation_label: 'Lei Complementar nº 258/2024, Art. 262',
    norma_ref: 'Lei Complementar nº 258/2024',
    dispositivo_ref: 'Art. 262',
    source_url: 'https://sapl.natal.rn.leg.br/norma/258',
    contribution: 'Regra transitória',
    evidence_text: 'Trecho da norma revisado.',
    document_sha256: 'a'.repeat(64),
    page: 61,
    private_token: 'do-not-export',
  }], { revision: 'r9', completeness: 'partial' }, {
    coverage_status: 'partial',
    scope_limited: true,
    checked_until: '2026-09-30',
    pending_review: 12,
    sources_checked: [{
      source: 'sapl',
      jurisdiction: 'BR-RN-NATAL',
      series: 'municipal_lc',
      period_start: '2000-01-01',
      period_end: '2026-09-30',
      coverage_status: 'partial',
      pending_review: 12,
      internal_path: 'C:/private/archive',
    }],
    missing_intervals: [{
      source: 'sapl',
      jurisdiction: 'BR-RN-NATAL',
      series: 'municipal_lc',
      start: '2018-01-01',
      end: '2018-12-31',
      internal_path: 'C:/private/archive',
    }],
    reason: 'registered_scopes_only_not_a_universal_completeness_claim',
    private_key: 'do-not-export',
  });

  const markdown = window.JurixChatRenderer.renderEvidenceMarkdown(packageDto);
  assert.match(markdown, /\[Lei Complementar nº 258\/2024, Art\. 262\]\(<https:\/\/sapl\.natal\.rn\.leg\.br\/norma\/258>\)/);
  assert.match(markdown, /Cobertura do acervo: \*\*parcial\*\*/);
  assert.match(markdown, /Corte verificado: \*\*2026-09-30\*\*/);
  assert.match(markdown, /não comprova completude universal/);
  assert.match(markdown, /Intervalo sem cobertura registrada.*2018-01-01 a 2018-12-31/);
  assert.match(markdown, /SHA-256 do documento:/);
  assert.match(markdown, /Página: 61/);
  assert.doesNotMatch(markdown, /do-not-export|C:\\private|internal_path|private_key/);
  window.close();
});

test('evidence Markdown download creates a Markdown file only when citations are exportable', () => {
  const window = boot();
  let createdBlob = null;
  let downloadedName = null;
  window.URL.createObjectURL = (blob) => { createdBlob = blob; return 'blob:jurix-test'; };
  window.URL.revokeObjectURL = () => {};
  window.HTMLAnchorElement.prototype.click = function click() { downloadedName = this.download; };

  assert.equal(window.JurixChatRenderer.downloadEvidenceMarkdown([historicalSource]), true);
  assert.equal(createdBlob.type, 'text/markdown;charset=utf-8');
  assert.match(downloadedName, /^jurix-evidencias-\d{4}-\d{2}-\d{2}\.md$/);
  assert.equal(window.JurixChatRenderer.downloadEvidenceMarkdown([]), false);
  window.close();
});

test('evidence export keeps a local Jurix PDF route separate from official URLs', () => {
  const window = boot();
  const localPath = '/normas/documentos/12345678-1234-5678-1234-567812345678/pdf/#page=61';
  const packageDto = window.JurixChatRenderer.buildEvidencePackage([{
    ...historicalSource,
    source_url: null,
    pdf_url: null,
    sapl_url: null,
    local_pdf_url: localPath,
  }]);

  assert.equal(packageDto.sources[0].official_url, null);
  assert.equal(packageDto.sources[0].local_pdf_url, localPath);

  const unsafe = window.JurixChatRenderer.buildEvidencePackage([{
    ...historicalSource,
    source_url: null,
    pdf_url: null,
    sapl_url: null,
    local_pdf_url: '/normas/documentos/not-a-uuid/pdf/',
  }]);
  assert.equal(unsafe.sources[0].official_url, null);
  assert.equal(unsafe.sources[0].local_pdf_url, null);

  const sameOriginAbsolute = window.JurixChatRenderer.buildEvidencePackage([{
    ...historicalSource,
    source_url: `${window.location.origin}${localPath}`,
    pdf_url: null,
    sapl_url: null,
    local_pdf_url: null,
  }]);
  assert.equal(sameOriginAbsolute.sources[0].official_url, null);
  assert.equal(sameOriginAbsolute.sources[0].local_pdf_url, localPath);
  window.close();
});

test('local PDF evidence export opens at its cited page', () => {
  const window = boot();
  const localPath = '/normas/documentos/12345678-1234-5678-1234-567812345678/pdf/';
  const packageDto = window.JurixChatRenderer.buildEvidencePackage([{
    ...historicalSource,
    page: 61,
    source_url: null,
    pdf_url: null,
    sapl_url: null,
    local_pdf_url: localPath,
  }]);

  assert.equal(packageDto.sources[0].local_pdf_url, `${localPath}#page=61`);
  assert.match(
    window.JurixChatRenderer.renderEvidenceMarkdown(packageDto),
    /\]\(<\/normas\/documentos\/12345678-1234-5678-1234-567812345678\/pdf\/#page=61>\)/,
  );
  window.close();
});

test('corpus revision export rejects invalid dates and unsupported completeness values', () => {
  const window = boot();
  const packageDto = window.JurixChatRenderer.buildEvidencePackage([], {
    revision: ' r8 ',
    digest: 'invalid',
    completeness: 'pretend-complete',
    updated_at: '2026-99-99',
  });

  assert.deepEqual({ ...packageDto.corpus_revision }, { revision: 'r8' });
  assert.equal(packageDto.corpus_coverage, null);
  window.close();
});

test('unknown review counts and corpus revisions stay unknown instead of becoming zero', () => {
  const window = boot();
  const packageDto = window.JurixChatRenderer.buildEvidencePackage([], {
    revision: null,
  }, {
    coverage_status: 'unknown',
    corpus_revision: { revision: null, digest: null },
    pending_review: null,
    sources_checked: [{
      coverage_status: 'unknown',
      pending_review: null,
    }],
    reason: 'no_reviewed_coverage_scope',
  });

  assert.equal(packageDto.corpus_coverage.pending_review, null);
  assert.equal(packageDto.corpus_coverage.sources_checked[0].pending_review, null);
  assert.equal(packageDto.corpus_coverage.corpus_revision.revision, null);
  const markdown = window.JurixChatRenderer.renderEvidenceMarkdown(packageDto);
  assert.doesNotMatch(markdown, /Documentos pendentes de revisão: \*\*0\*\*/);
  assert.doesNotMatch(markdown, /pendências?:? 0\b/);

  const knownZero = window.JurixChatRenderer.buildEvidencePackage([], null, {
    coverage_status: 'partial',
    pending_review: 0,
    sources_checked: [{ coverage_status: 'partial', pending_review: 0 }],
  });
  assert.equal(knownZero.corpus_coverage.pending_review, 0);
  assert.equal(knownZero.corpus_coverage.sources_checked[0].pending_review, 0);
  assert.match(
    window.JurixChatRenderer.renderEvidenceMarkdown(knownZero),
    /Documentos pendentes de revisão: \*\*0\*\*/,
  );
  window.close();
});

test('anonymous local history preserves safe versioned citation DTOs and strips unknown secrets', () => {
  const dom = new JSDOM(
    '<!doctype html><html><body data-authenticated="false"></body></html>',
    { url: 'https://jurix.local/assistente/', runScripts: 'dangerously', pretendToBeVisual: true },
  );
  const { window } = dom;
  window.eval(read('jurix-anonymous-history.js'));
  const history = window.JurixAnonymousHistory;
  const sessionId = history.ensureSession('local-citation-test');
  history.addMessage(sessionId, 'user', 'O que prevê a versão histórica?');
  history.updateLastAssistant(sessionId, 'Resposta [[1]].', [{
    ...historicalSource,
    dispositivo_structural_key: 'a'.repeat(64),
    graph_relation: { action: 'ALTERA', quote: 'Trecho validado.', api_key: 'do-not-export' },
    private_token: 'do-not-export',
  }], true);

  const restored = history.get(sessionId).messages.at(-1).sources[0];
  const exported = history.exportData().sessions[0].messages.at(-1).sources[0];
  assert.equal(restored.temporal_version.version_hash, 'b'.repeat(64));
  assert.equal(exported.dispositivo_structural_key, 'a'.repeat(64));
  assert.equal(exported.graph_relation.action, 'ALTERA');
  assert.equal(exported.graph_relation.api_key, undefined);
  assert.equal(exported.private_token, undefined);
  assert.equal(exported.pdf_url.includes('#:~:text='), true);
  window.close();
});
