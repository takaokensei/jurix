// Jurix Chat Renderer
// Provides UI primitives for chat messages, loading indicators, and error handling.
// This file is framework‑free and used by chat.js via window.JurixChatRenderer.

(function () {
    'use strict';

    const root = window.JurixChatRenderer = window.JurixChatRenderer || {};

    function escapeHtml(value) {
        const div = document.createElement('div');
        div.textContent = String(value ?? '');
        return div.innerHTML;
    }

    function renderMarkdown(text, fallback) {
        try {
            if (typeof fallback === 'function') return fallback(text);
            if (window.JurixMarkdown && typeof window.JurixMarkdown.render === 'function') {
                return window.JurixMarkdown.render(text);
            }
            if (typeof marked !== 'undefined' && typeof DOMPurify !== 'undefined') {
                return DOMPurify.sanitize(marked.parse(String(text || '')));
            }
        } catch (_) {
            // fall through
        }
        return escapeHtml(text).replace(/\n/g, '<br>');
    }

    function formatTimestamp(value) {
        const parsed = value ? new Date(value) : null;
        const date = parsed && !Number.isNaN(parsed.getTime()) ? parsed : new Date();
        return date.toLocaleTimeString('pt-BR', {
            hour: '2-digit',
            minute: '2-digit',
        });
    }

    function nextId(prefix) {
        return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
    }

    function getMessagesWrapper() {
        return document.getElementById('messages-wrapper');
    }

    function addUserMessage(text, deps = {}) {
        const wrapper = getMessagesWrapper();
        if (!wrapper) return null;
        const body = renderMarkdown(text, deps.renderMarkdown);
        const message = document.createElement('div');
        message.className = 'message message-user jurix-message-enter';
        message.innerHTML = `
            <div class="message-content">
                <div class="message-header">
                    <span class="message-role">Você</span>
                    <span class="message-time">${escapeHtml(formatTimestamp(deps.createdAt))}</span>
                </div>
                <div class="message-body">${body}</div>
            </div>
        `;
        const retryContext = deps.retryContext;
        if (retryContext && typeof deps.onRetry === 'function' &&
            ['failed', 'cancelled', 'interrupted'].includes(retryContext.state) &&
            /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(String(retryContext.clientTurnId || ''))) {
            const actions = document.createElement('div');
            actions.className = 'message-actions';
            const retry = document.createElement('button');
            retry.type = 'button';
            retry.className = 'jurix-interrupted-retry';
            retry.textContent = 'Tentar novamente';
            retry.setAttribute('aria-label', 'Tentar novamente a pergunta interrompida');
            retry.addEventListener('click', () => deps.onRetry(String(text || ''), retryContext.clientTurnId));
            actions.append(retry);
            message.querySelector('.message-content')?.append(actions);
        }
        wrapper.appendChild(message);
        requestAnimationFrame(() => message.classList.remove('jurix-message-enter'));
        if (typeof deps.scrollToBottom === 'function') deps.scrollToBottom();
        return message;
    }

    function addLoadingMessage(opts = {}) {
        const wrapper = getMessagesWrapper();
        if (!wrapper) return null;
        const loadingId = nextId('loading');
        const logo = opts.config && opts.config.logoIconUrl ? opts.config.logoIconUrl : '/static/img/logo-icon.svg';
        const message = document.createElement('div');
        message.className = 'message message-assistant jurix-message-enter';
        message.id = loadingId;
        message.innerHTML = `
            <div class="message-avatar">
                <img src="${escapeHtml(logo)}" alt="Jurix">
            </div>
            <div class="message-content">
                <div class="loading-message" role="status" aria-live="polite">
                    <div class="loading-dots" aria-hidden="true">
                        <div class="loading-dot"></div>
                        <div class="loading-dot"></div>
                        <div class="loading-dot"></div>
                    </div>
                    <span>Pensando...</span>
                </div>
            </div>
        `;
        wrapper.appendChild(message);
        requestAnimationFrame(() => message.classList.remove('jurix-message-enter'));
        if (typeof opts.scrollToBottom === 'function') opts.scrollToBottom();
        return loadingId;
    }

    function removeLoadingMessage(loadingId) {
        const node = document.getElementById(loadingId);
        if (!node) return;
        node.classList.add('jurix-message-exit');
        window.setTimeout(() => node.remove(), 140);
    }

    function showPendingAnswer(messageBody) {
        if (!(messageBody instanceof HTMLElement)) return null;
        const status = document.createElement('div');
        status.className = 'jurix-answer-pending';
        status.setAttribute('role', 'status');
        status.setAttribute('aria-live', 'polite');

        const marker = document.createElement('span');
        marker.className = 'jurix-answer-pending-marker';
        marker.setAttribute('aria-hidden', 'true');
        const label = document.createElement('span');
        label.textContent = 'Organizando as evidências antes de apresentar a resposta…';
        status.append(marker, label);
        messageBody.replaceChildren(status);
        return status;
    }

    function clearPendingAnswer(status) {
        if (status instanceof HTMLElement && status.classList.contains('jurix-answer-pending')) {
            status.remove();
        }
    }

    function copyWithDocumentCommand(markdownText) {
        if (typeof document.execCommand !== 'function') return false;
        const previousFocus = document.activeElement;
        const field = document.createElement('textarea');
        field.className = 'jurix-clipboard-fallback';
        field.value = markdownText;
        field.setAttribute('readonly', '');
        field.setAttribute('aria-hidden', 'true');
        field.tabIndex = -1;
        document.body.appendChild(field);
        field.focus();
        field.select();
        let copied = false;
        try {
            copied = document.execCommand('copy') === true;
        } catch (_) {
            copied = false;
        }
        field.remove();
        if (previousFocus instanceof HTMLElement && document.contains(previousFocus)) {
            previousFocus.focus({ preventScroll: true });
        }
        return copied;
    }

    function markdownWithRenderedCitations(markdownText, button) {
        const message = button?.closest('.message');
        const body = message?.querySelector('.message-body');
        const sources = button?._citationSources || body?._citationSources || [];
        const sourceForCitation = (index) => {
            const exact = sources.find((item) => Number(item?.citation_index) === index);
            if (exact) return exact;
            if (!sources.some((item) => Number.isInteger(Number(item?.citation_index)))) {
                return sources[index - 1] || null;
            }
            return null;
        };
        const links = [];
        body?.querySelectorAll('a.jurix-legal-reference-link').forEach((anchor) => {
            const label = String(anchor.textContent || '').trim();
            const href = anchor.href;
            if (label && /^https?:$/.test(new URL(href, window.location.href).protocol)) {
                links.push({ label, href });
            }
        });

        const escapeLabel = (value) => String(value).replace(/\\/g, '\\\\').replace(/([\[\]])/g, '\\$1');
        const renderPlainText = (text) => {
            let rendered = text;
            links.sort((left, right) => right.label.length - left.label.length).forEach(({ label, href }) => {
                const escaped = label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
                rendered = rendered.replace(new RegExp(escaped, 'g'), (match, offset, fullText) => {
                    // Do not wrap an existing Markdown link label a second time.
                    if (fullText[offset - 1] === '[' && fullText.slice(offset + match.length).startsWith('](')) {
                        return match;
                    }
                    return `[${escapeLabel(label)}](<${href}>)`;
                });
            });
            return rendered.replace(/\[\[(\d{1,3})\]\]/g, (marker, rawIndex) => {
                const index = Number(rawIndex);
                const source = sourceForCitation(index);
                const href = window.JurixRagUI?.buildSourceUrl?.(source);
                if (!source || !href) return marker;
                const label = source.citation_label || `Fonte ${index}`;
                return `[${escapeLabel(label)}](<${href}>)`;
            });
        };

        const codeSegments = [];
        const protectedText = String(markdownText || '').replace(/(```[\s\S]*?```|`[^`\n]*`)/g, (code) => {
            const token = `\u0000JURIX_CODE_${codeSegments.length}\u0000`;
            codeSegments.push(code);
            return token;
        });
        return renderPlainText(protectedText).replace(/\u0000JURIX_CODE_(\d+)\u0000/g, (_token, index) => codeSegments[Number(index)]);
    }

    function exportableEvidence(sources) {
        const rows = Array.isArray(sources) ? sources : [];
        return rows.map((source) => {
            const version = source?.temporal_version || {};
            const versionHash = /^[a-f0-9]{64}$/i.test(String(version.version_hash || ''))
                ? String(version.version_hash).toLowerCase() : null;
            const relation = source?.graph_relation && typeof source.graph_relation === 'object'
                ? source.graph_relation : null;
            const coverage = source?.coverage && typeof source.coverage === 'object'
                ? source.coverage : null;
            const safeDate = (value) => {
                const candidate = String(value || '');
                if (!/^\d{4}-\d{2}-\d{2}$/.test(candidate)) return null;
                const parsed = new Date(`${candidate}T00:00:00Z`);
                return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === candidate
                    ? candidate : null;
            };
            const safeCount = (value) => Number.isInteger(value) && value >= 0 ? value : null;
            const allowedActions = new Set(['ALTERA', 'SUBSTITUI', 'ADICIONA', 'REVOGA', 'REFERENCIA']);
            const action = String(relation?.action || '').toUpperCase();
            let graphRelation = null;
            if (relation && allowedActions.has(action)) {
                graphRelation = { action };
                for (const [key, maxLength] of [
                    ['event_id', 160], ['intent', 160], ['role', 160], ['label', 160],
                    ['review_status', 160], ['effective_status', 160], ['resolution', 160], ['quote', 1200],
                ]) {
                    const value = String(relation[key] || '').slice(0, maxLength);
                    if (value) graphRelation[key] = value;
                }
                for (const key of ['effective_on', 'publication_on']) {
                    const value = safeDate(relation[key]);
                    if (value) graphRelation[key] = value;
                }
                for (const key of ['source_norma_id', 'target_norma_id']) {
                    const value = relation[key];
                    if (Number.isInteger(value) && value > 0) graphRelation[key] = value;
                }
                for (const key of ['source_device_key', 'target_device_key']) {
                    const value = relation[key];
                    if (typeof value === 'string' && /^[a-f0-9]{64}$/i.test(value)) {
                        graphRelation[key] = value.toLowerCase();
                    }
                }
            }
            const projectionCoverage = coverage ? {
                as_of: safeDate(coverage.as_of),
                version_hash: /^[a-f0-9]{64}$/i.test(String(coverage.version_hash || ''))
                    ? String(coverage.version_hash).toLowerCase() : null,
                input_hash: /^[a-f0-9]{64}$/i.test(String(coverage.input_hash || ''))
                    ? String(coverage.input_hash).toLowerCase() : null,
                snapshot_id: safeCount(coverage.snapshot_id),
                status: String(coverage.status || '').slice(0, 80) || null,
                policy: String(coverage.policy || '').slice(0, 80) || null,
                complete: typeof coverage.complete === 'boolean' ? coverage.complete : null,
                projected_devices: safeCount(coverage.projected_devices),
                selected_devices: safeCount(coverage.selected_devices),
                citation_anchor_unavailable: typeof coverage.citation_anchor_unavailable === 'boolean'
                    ? coverage.citation_anchor_unavailable : null,
            } : null;
            const temporalAsOf = safeDate(version.as_of);
            const temporalVersion = versionHash && temporalAsOf ? {
                as_of: temporalAsOf,
                legal_status: String(version.legal_status || '').slice(0, 32),
                version_hash: versionHash,
                policy: String(version.policy || '').slice(0, 100) || null,
                effective_on: safeDate(version.effective_on),
                source_document_id: String(version.source_document_id || '').slice(0, 64) || null,
                input_hash: /^[a-f0-9]{64}$/i.test(String(version.input_hash || ''))
                    ? String(version.input_hash).toLowerCase() : null,
                snapshot_id: safeCount(version.snapshot_id),
                status_note: String(version.status_note || '').slice(0, 240) || null,
            } : null;
            let verificationLimit = 'As evidências recuperadas não certificam exaustividade do corpus nem aplicabilidade ao caso concreto.';
            if (source?.evidence_scope === 'isolated_qa_archive') {
                verificationLimit = 'Extração de acervo histórico local; revisão jurídica e consolidação não são atestadas por este pacote.';
            } else if (source?.source_kind === 'official_gazette_extraction') {
                verificationLimit = 'Trecho extraído automaticamente de edição oficial do Diário Oficial; confira o PDF e não presuma vigência atual ou ausência de alterações posteriores.';
            } else if (temporalVersion) {
                verificationLimit = projectionCoverage?.complete === true
                    ? 'Projeção registrada para a data indicada; não determina aplicabilidade ao caso concreto.'
                    : 'Projeção histórica parcial ou incompleta; a redação integral não foi confirmada.';
            }
            const rawUrl = source?.source_url || source?.pdf_url || source?.sapl_url;
            let officialUrl = null;
            let sameOriginPath = '';
            if (rawUrl) {
                try {
                    const url = new URL(String(rawUrl), window.location.href);
                    if (url.origin === window.location.origin) {
                        sameOriginPath = `${url.pathname}${url.hash}`;
                    } else if (['http:', 'https:'].includes(url.protocol) && !url.username) {
                        if (url.hash.startsWith('#:~:text=')) url.hash = '';
                        officialUrl = url.href;
                    }
                } catch (_) { /* invalid source URL is omitted */ }
            }
            const rawLocalPdfUrl = String(source?.local_pdf_url || sameOriginPath);
            const localPdfUrl = /^\/normas\/documentos\/[0-9a-f-]{36}\/pdf\/(?:#page=\d+)?$/i.test(rawLocalPdfUrl)
                ? rawLocalPdfUrl : null;
            const citationIndex = Number(source?.citation_index);
            const page = Number(source?.page);
            const anchoredLocalPdfUrl = localPdfUrl && Number.isInteger(page) && page > 0
                && !/#page=\d+$/i.test(localPdfUrl)
                ? `${localPdfUrl}#page=${page}` : localPdfUrl;
            const rawSpan = source?.span;
            const span = Number.isInteger(rawSpan?.start) && Number.isInteger(rawSpan?.end)
                && rawSpan.start >= 0 && rawSpan.end >= rawSpan.start
                ? { start: rawSpan.start, end: rawSpan.end } : null;
            const row = {
                citation_id: typeof source?.citation_id === 'string' ? source.citation_id.slice(0, 240) : null,
                citation_index: Number.isInteger(citationIndex) && citationIndex > 0 ? citationIndex : null,
                label: String(source?.citation_label || '').slice(0, 500) || null,
                norma: String(source?.norma_ref || '').slice(0, 240) || null,
                norma_id: source?.norma_id == null ? null : String(source.norma_id).slice(0, 64),
                dispositivo: String(source?.dispositivo_ref || '').slice(0, 240) || null,
                evidence_type: String(source?.source_type || '').slice(0, 120) || null,
                edition_label: String(source?.edition_label || '').slice(0, 180) || null,
                source_kind: String(source?.source_kind || '').slice(0, 80) || null,
                contribution: String(source?.contribution || '').slice(0, 240) || null,
                matter_status: typeof source?.matter_status === 'boolean' ? source.matter_status : null,
                matter_result: String(source?.matter_result || '').slice(0, 240) || null,
                status_label: String(source?.status_label || '').slice(0, 160) || null,
                evidence_scope: String(source?.evidence_scope || '').slice(0, 80) || null,
                publication_date: safeDate(source?.data_publicacao),
                consulted_at: /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(String(source?.consulted_at || '')) ? source.consulted_at : null,
                effective_date: safeDate(source?.data_vigencia),
                temporal_status: String(source?.temporal_status || '').slice(0, 48) || null,
                temporal_version: temporalVersion,
                graph_relation: graphRelation,
                projection_coverage: projectionCoverage,
                verification_limit: verificationLimit,
                document_id: String(source?.source_id || source?.document_id || '').slice(0, 64) || null,
                document_sha256: /^[a-f0-9]{64}$/i.test(String(source?.document_sha256 || source?.content_sha256 || ''))
                    ? String(source.document_sha256 || source.content_sha256).toLowerCase() : null,
                page: Number.isInteger(page) && page > 0 ? page : null,
                span,
                span_basis: String(source?.span_basis || '').slice(0, 80) || null,
                official_url: officialUrl,
                local_pdf_url: anchoredLocalPdfUrl,
                excerpt: String(source?.evidence_text || source?.full_text || source?.text || '').slice(0, 4000) || null,
            };
            return row;
        }).filter((source) => source.citation_id || source.citation_index !== null)
            .sort((left, right) => {
                const leftMissing = left.citation_index === null;
                const rightMissing = right.citation_index === null;
                if (leftMissing !== rightMissing) return leftMissing ? 1 : -1;
                if (!leftMissing && left.citation_index !== right.citation_index) {
                    return left.citation_index - right.citation_index;
                }
                return String(left.citation_id || '').localeCompare(String(right.citation_id || ''));
            });
    }

    function sanitizeCorpusCoverage(coverage) {
        if (!coverage || typeof coverage !== 'object' || Array.isArray(coverage)) return null;
        const allowedStatuses = new Set(['unknown', 'partial', 'reviewed']);
        const safeCount = (value) => {
            if (typeof value === 'number') {
                return Number.isSafeInteger(value) && value >= 0 ? value : null;
            }
            if (typeof value === 'string' && /^\d+$/.test(value)) {
                const parsed = Number(value);
                return Number.isSafeInteger(parsed) ? parsed : null;
            }
            return null;
        };
        const safeDate = (value) => {
            const candidate = String(value || '');
            if (!/^\d{4}-\d{2}-\d{2}$/.test(candidate)) return null;
            const parsed = new Date(`${candidate}T00:00:00Z`);
            return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === candidate
                ? candidate : null;
        };
        const safeScope = (scope) => {
            if (!scope || typeof scope !== 'object' || Array.isArray(scope)) return null;
            const status = allowedStatuses.has(scope.coverage_status) ? scope.coverage_status : 'unknown';
            const intervals = Array.isArray(scope.missing_intervals)
                ? scope.missing_intervals.slice(0, 100).map((interval) => ({
                    start: safeDate(interval?.start),
                    end: safeDate(interval?.end),
                })).filter((interval) => interval.start || interval.end)
                : null;
            const pendingReview = safeCount(scope.pending_review);
            return {
                source: String(scope.source || '').slice(0, 80) || null,
                jurisdiction: String(scope.jurisdiction || '').slice(0, 100) || null,
                series: String(scope.series || '').slice(0, 80) || null,
                period_start: safeDate(scope.period_start),
                period_end: safeDate(scope.period_end),
                checked_until: safeDate(scope.checked_until),
                source_checksum: /^[a-f0-9]{64}$/i.test(String(scope.source_checksum || ''))
                    ? String(scope.source_checksum).toLowerCase() : null,
                coverage_status: status,
                missing_intervals: intervals,
                pending_review: pendingReview,
                last_success_at: /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(String(scope.last_success_at || ''))
                    ? String(scope.last_success_at) : null,
            };
        };
        const status = allowedStatuses.has(coverage.coverage_status)
            ? coverage.coverage_status : 'unknown';
        const revision = coverage.corpus_revision && typeof coverage.corpus_revision === 'object'
            ? coverage.corpus_revision : {};
        const scopes = Array.isArray(coverage.sources_checked)
            ? coverage.sources_checked.slice(0, 100).map(safeScope).filter(Boolean) : [];
        const rawMissing = coverage.missing_intervals;
        const missingIntervals = Array.isArray(rawMissing)
            ? rawMissing.slice(0, 100).map((interval) => ({
                source: String(interval?.source || '').slice(0, 80) || null,
                jurisdiction: String(interval?.jurisdiction || '').slice(0, 100) || null,
                series: String(interval?.series || '').slice(0, 80) || null,
                start: safeDate(interval?.start),
                end: safeDate(interval?.end),
            })).filter((interval) => interval.start || interval.end)
            : null;
        const pendingReview = safeCount(coverage.pending_review);
        const revisionNumber = safeCount(revision.revision);
        return {
            coverage_status: status,
            corpus_revision: {
                revision: revisionNumber,
                digest: /^[a-f0-9]{64}$/i.test(String(revision.digest || ''))
                    ? String(revision.digest).toLowerCase() : null,
            },
            scope_limited: coverage.scope_limited === true,
            checked_until: safeDate(coverage.checked_until),
            sources_checked: scopes,
            missing_intervals: missingIntervals,
            pending_review: pendingReview,
            reason: ['no_reviewed_coverage_scope', 'registered_scopes_only_not_a_universal_completeness_claim']
                .includes(coverage.reason) ? coverage.reason : null,
        };
    }

    function buildEvidencePackage(sources, corpusRevision = null, corpusCoverage = null) {
        const revision = {};
        if (corpusRevision && typeof corpusRevision === 'object') {
            if (typeof corpusRevision.revision === 'string' && corpusRevision.revision.trim()) revision.revision = corpusRevision.revision.trim().slice(0, 120);
            if (/^[a-f0-9]{64}$/i.test(String(corpusRevision.digest || ''))) revision.digest = String(corpusRevision.digest).toLowerCase();
            if (typeof corpusRevision.source === 'string' && corpusRevision.source.trim()) revision.source = corpusRevision.source.trim().slice(0, 120);
            if (['complete', 'partial', 'unknown', 'incomplete'].includes(corpusRevision.completeness)) {
                revision.completeness = corpusRevision.completeness;
            }
            const updatedAt = String(corpusRevision.updated_at || '');
            const parsedUpdatedAt = /^\d{4}-\d{2}-\d{2}$/.test(updatedAt)
                ? new Date(`${updatedAt}T00:00:00Z`) : null;
            if (parsedUpdatedAt && !Number.isNaN(parsedUpdatedAt.getTime())
                && parsedUpdatedAt.toISOString().slice(0, 10) === updatedAt) {
                revision.updated_at = updatedAt;
            }
        }
        return {
            schema_version: 'jurix-evidence-v1',
            generated_at: new Date().toISOString().replace(/\.\d{3}Z$/, 'Z'),
            corpus_revision: Object.keys(revision).length ? revision : null,
            corpus_coverage: sanitizeCorpusCoverage(corpusCoverage),
            sources: exportableEvidence(sources),
        };
    }

    function downloadEvidencePackage(sources, corpusRevision = null, corpusCoverage = null) {
        const packageDto = buildEvidencePackage(sources, corpusRevision, corpusCoverage);
        if (!packageDto.sources.length || typeof URL.createObjectURL !== 'function') return false;
        const blob = new Blob([JSON.stringify(packageDto, null, 2)], { type: 'application/json;charset=utf-8' });
        const url = URL.createObjectURL(blob);
        const anchor = document.createElement('a');
        anchor.href = url;
        anchor.download = `jurix-evidencias-${new Date().toISOString().slice(0, 10)}.json`;
        anchor.hidden = true;
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
        window.setTimeout(() => URL.revokeObjectURL(url), 0);
        return true;
    }

    function markdownText(value) {
        return String(value || '')
            .replace(/\\/g, '\\\\')
            .replace(/([`*_{}\[\]<>|])/g, '\\$1')
            .replace(/[\r\n]+/g, ' ')
            .trim();
    }

    function renderEvidenceMarkdown(packageDto) {
        const lines = ['## Referências e evidências', ''];
        const revision = packageDto?.corpus_revision;
        if (revision && typeof revision === 'object') {
            const label = markdownText(revision.revision || 'não informada');
            const completeness = markdownText(revision.completeness || 'não verificada');
            lines.push(`Corpus: \`${label}\` — completude: **${completeness}**.`, '');
        }

        const coverage = packageDto?.corpus_coverage;
        const coverageLabels = {
            unknown: 'não verificada',
            partial: 'parcial',
            reviewed: 'revisada somente nos escopos listados',
        };
        if (!coverage || typeof coverage !== 'object') {
            lines.push('Cobertura do acervo: **não informada**.', '');
        } else {
            lines.push(`Cobertura do acervo: **${coverageLabels[coverage.coverage_status] || coverageLabels.unknown}**.`);
            if (coverage.checked_until) lines.push(`Corte verificado: **${markdownText(coverage.checked_until)}**.`);
            if (Number.isInteger(coverage.pending_review) && coverage.pending_review >= 0) {
                lines.push(`Documentos pendentes de revisão: **${coverage.pending_review}**.`);
            }
            if (coverage.scope_limited === true) {
                lines.push('A cobertura abaixo é limitada aos escopos declarados; não comprova completude universal.');
            }
            for (const scope of Array.isArray(coverage.sources_checked) ? coverage.sources_checked : []) {
                const identity = [scope.source, scope.jurisdiction, scope.series]
                    .filter(Boolean).map(markdownText).join(' · ') || 'Escopo sem identificação completa';
                const start = markdownText(scope.period_start || 'início não informado');
                const end = markdownText(scope.period_end || 'fim não informado');
                const status = coverageLabels[scope.coverage_status] || coverageLabels.unknown;
                let line = `- ${identity}: ${start} a ${end}; cobertura ${status}`;
                if (scope.checked_until) line += `, conferida até ${markdownText(scope.checked_until)}`;
                if (Number.isInteger(scope.pending_review) && scope.pending_review >= 0) {
                    line += `, ${scope.pending_review} pendência(s)`;
                }
                lines.push(`${line}.`);
            }
            for (const interval of Array.isArray(coverage.missing_intervals) ? coverage.missing_intervals : []) {
                const identity = [interval.source, interval.jurisdiction, interval.series]
                    .filter(Boolean).map(markdownText).join(' · ');
                const start = markdownText(interval.start || 'início não informado');
                const end = markdownText(interval.end || 'fim não informado');
                lines.push(`- Intervalo sem cobertura registrada — ${identity ? `${identity}: ` : ''}${start} a ${end}.`);
            }
            if (coverage.reason === 'no_reviewed_coverage_scope') {
                lines.push('Nenhum escopo de cobertura revisada foi registrado.');
            } else if (coverage.reason === 'registered_scopes_only_not_a_universal_completeness_claim') {
                lines.push('Os escopos registrados não constituem declaração de completude de todo o acervo.');
            }
            lines.push('');
        }

        const sources = Array.isArray(packageDto?.sources) ? packageDto.sources : [];
        for (const source of sources) {
            const label = markdownText(source.label || source.norma || 'Fonte jurídica');
            const url = source.official_url || source.local_pdf_url;
            lines.push(url ? `- [${label}](<${url}>)` : `- ${label}`);
            const details = [source.contribution, source.evidence_type].filter(Boolean).map(markdownText);
            if (details.length) lines.push(`  - ${details.join('; ')}`);
            if (source.excerpt) lines.push(`  - Evidência: “${markdownText(source.excerpt)}”`);
            if (source.document_sha256) lines.push(`  - SHA-256 do documento: \`${source.document_sha256}\``);
            if (source.page) lines.push(`  - Página: ${source.page}`);
            if (source.temporal_version) {
                const temporal = source.temporal_version;
                lines.push(`  - Projeção em ${markdownText(temporal.as_of)} · versão \`${temporal.version_hash}\` · situação: ${markdownText(temporal.legal_status || 'não determinada')}`);
                if (temporal.snapshot_id !== null && temporal.snapshot_id !== undefined) lines.push(`  - Snapshot: \`${temporal.snapshot_id}\`.`);
                if (temporal.input_hash) lines.push(`  - Hash de entrada da projeção: \`${temporal.input_hash}\`.`);
            }
            if (source.graph_relation) {
                const relation = source.graph_relation;
                const event = relation.event_id ? `evento \`${markdownText(relation.event_id)}\`` : 'evento normativo';
                lines.push(`  - Relação: ${markdownText(relation.action)} · ${event} · revisão: ${markdownText(relation.review_status || 'não informada')} · efeito: ${markdownText(relation.effective_status || 'não confirmado')}`);
                if (relation.quote) lines.push(`  - Trecho do evento: “${markdownText(relation.quote)}”`);
            }
            if (source.projection_coverage) {
                const coverage = source.projection_coverage;
                if (coverage.selected_devices !== null || coverage.projected_devices !== null) {
                    lines.push(`  - Cobertura da projeção: ${coverage.selected_devices ?? 'não informada'} selecionado(s) de ${coverage.projected_devices ?? 'total não informado'} dispositivo(s).`);
                }
            }
            if (source.verification_limit) lines.push(`  - Limite da verificação: ${markdownText(source.verification_limit)}`);
        }
        if (!sources.length) lines.push('Nenhuma fonte estruturada foi fornecida para exportação.');
        lines.push('', `Exportado em: ${markdownText(packageDto?.generated_at || 'não informado')}.`);
        return lines.join('\n');
    }

    function downloadEvidenceMarkdown(sources, corpusRevision = null, corpusCoverage = null) {
        const packageDto = buildEvidencePackage(sources, corpusRevision, corpusCoverage);
        if (!packageDto.sources.length || typeof URL.createObjectURL !== 'function') return false;
        const blob = new Blob([renderEvidenceMarkdown(packageDto)], { type: 'text/markdown;charset=utf-8' });
        const url = URL.createObjectURL(blob);
        const anchor = document.createElement('a');
        anchor.href = url;
        anchor.download = `jurix-evidencias-${new Date().toISOString().slice(0, 10)}.md`;
        anchor.hidden = true;
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
        window.setTimeout(() => URL.revokeObjectURL(url), 0);
        return true;
    }

    async function copyResponseToClipboard(markdownText, button) {
        if (!markdownText || !button) return false;
        markdownText = markdownWithRenderedCitations(markdownText, button);
        let copied = false;
        try {
            if (navigator.clipboard?.writeText) {
                await navigator.clipboard.writeText(markdownText);
                copied = true;
            }
        } catch (_) {
            copied = false;
        }
        if (!copied) copied = copyWithDocumentCommand(markdownText);
        if (!copied) {
            button.setAttribute('aria-label', 'Não foi possível copiar a resposta');
            button.setAttribute('title', 'Não foi possível copiar a resposta');
            window.setTimeout(() => {
                button.setAttribute('aria-label', 'Copiar resposta em Markdown');
                button.setAttribute('title', 'Copiar resposta');
            }, 2200);
            return false;
        }

        {
            const copyIcon = button.querySelector('.copy-icon');
            const checkIcon = button.querySelector('.check-icon');
            if (copyIcon && checkIcon) {
                button.classList.add('copied');
                copyIcon.classList.add('is-hidden');
                checkIcon.classList.remove('is-hidden');
                copyIcon.hidden = true;
                checkIcon.hidden = false;
                window.setTimeout(() => {
                    copyIcon.hidden = false;
                    checkIcon.hidden = true;
                    copyIcon.classList.remove('is-hidden');
                    checkIcon.classList.add('is-hidden');
                    button.classList.remove('copied');
                }, 2000);
            }
            button.setAttribute('aria-label', 'Resposta copiada');
            button.setAttribute('title', 'Resposta copiada');
            window.setTimeout(() => {
                button.setAttribute('aria-label', 'Copiar resposta em Markdown');
                button.setAttribute('title', 'Copiar resposta');
            }, 2000);
            return true;
        }
    }

    // Export public API
    root.escapeHtml = escapeHtml;
    root.formatTimestamp = formatTimestamp;
    root.addUserMessage = addUserMessage;
    root.addLoadingMessage = addLoadingMessage;
    root.removeLoadingMessage = removeLoadingMessage;
    root.showPendingAnswer = showPendingAnswer;
    root.clearPendingAnswer = clearPendingAnswer;
    root.copyResponseToClipboard = copyResponseToClipboard;
    root.buildEvidencePackage = buildEvidencePackage;
    root.downloadEvidencePackage = downloadEvidencePackage;
    root.renderEvidenceMarkdown = renderEvidenceMarkdown;
    root.downloadEvidenceMarkdown = downloadEvidenceMarkdown;
})();
