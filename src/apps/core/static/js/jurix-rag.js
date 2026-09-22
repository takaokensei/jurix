/* Jurix RAG UI — Phase 2, 3 & 4 */
(function () {
    'use strict';

    const SANITIZE_CONFIG = {
        ALLOWED_TAGS: [
            'p', 'br', 'strong', 'em', 'b', 'i', 'u', 's', 'del',
            'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
            'ul', 'ol', 'li', 'blockquote', 'code', 'pre',
            'table', 'thead', 'tbody', 'tr', 'th', 'td',
            'a', 'hr', 'span', 'div'
        ],
        ALLOWED_ATTR: ['href', 'title', 'target', 'rel', 'class', 'data-source-index', 'aria-label'],
        FORBID_TAGS: ['style', 'script', 'iframe', 'object', 'embed', 'form', 'input', 'button', 'svg', 'math'],
        FORBID_ATTR: ['style', 'onclick', 'onerror', 'onload', 'src', 'srcset', 'poster', 'action', 'formaction'],
        ALLOW_UNKNOWN_PROTOCOLS: false,
    };

    const state = new WeakMap();

    function escapeHtml(value) {
        return String(value ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    function renderMarkdown(markdown) {
        const source = String(markdown || '');
        if (window.JurixMarkdown && typeof window.JurixMarkdown.render === 'function') {
            return window.JurixMarkdown.render(source);
        }
        if (typeof marked === 'undefined' || typeof DOMPurify === 'undefined') {
            return `<p>${escapeHtml(source)}</p>`;
        }
        return DOMPurify.sanitize(marked.parse(source), SANITIZE_CONFIG);
    }

    function scheduleRender(element, markdown) {
        if (!element) return;
        const current = state.get(element) || {};
        current.markdown = markdown;
        state.set(element, current);

        if (current.pending) return;
        current.pending = true;
        requestAnimationFrame(() => {
            current.pending = false;
            element.innerHTML = renderMarkdown(current.markdown);
            if (current.streaming) element.classList.add('is-streaming');
            if (typeof window.scrollToBottomIfAtBottom === 'function') {
                window.scrollToBottomIfAtBottom();
            }
        });
    }

    function flushRender(element, markdown) {
        if (!element) return;
        const current = state.get(element) || {};
        current.markdown = markdown;
        current.pending = false;
        state.set(element, current);
        element.innerHTML = renderMarkdown(markdown);
    }

    function setStreamingState(element, isStreaming) {
        if (!element) return;
        const current = state.get(element) || {};
        current.streaming = isStreaming;
        state.set(element, current);
        element.classList.toggle('is-streaming', isStreaming);
    }

    function getStatus(error) {
        return Number(error?.status || error?.response?.status || 0);
    }

    function errorCopy(error) {
        const status = getStatus(error);
        if (status === 429) {
            return {
                title: 'Muitas solicitações',
                detail: 'Aguarde alguns segundos antes de tentar novamente.',
                tone: 'warning'
            };
        }
        if ([502, 503, 504].includes(status)) {
            return {
                title: 'Assistente temporariamente indisponível',
                detail: 'O mecanismo de IA ou a recuperação de fontes não respondeu. Você pode tentar novamente.',
                tone: 'warning'
            };
        }
        if (error instanceof TypeError || /network|offline|failed to fetch/i.test(String(error?.message || error))) {
            return {
                title: 'Conexão indisponível',
                detail: 'Verifique sua conexão e tente novamente.',
                tone: 'error'
            };
        }
        return {
            title: 'Não foi possível concluir a pesquisa',
            detail: 'O Jurix não conseguiu finalizar esta solicitação. Tente novamente.',
            tone: 'error'
        };
    }

    function renderErrorState(container, error, retryHandler) {
        if (!container) return;
        const copy = errorCopy(error);
        container.innerHTML = `
            <div class="jurix-rag-error jurix-rag-error--${copy.tone}" role="alert">
                <div class="jurix-rag-error-icon" aria-hidden="true">!</div>
                <div class="jurix-rag-error-content">
                    <strong>${escapeHtml(copy.title)}</strong>
                    <span>${escapeHtml(copy.detail)}</span>
                    ${typeof retryHandler === 'function' ? '<button type="button" class="jurix-rag-retry">Tentar novamente</button>' : ''}
                </div>
            </div>
        `;
        const retryButton = container.querySelector('.jurix-rag-retry');
        if (retryButton && retryHandler) retryButton.addEventListener('click', retryHandler);
        announce(copy.title);
    }

    function enhanceSources(container) {
        if (!container) return;
        container.querySelectorAll('.source-card').forEach((card) => {
            card.classList.add('jurix-rag-source');
        });
        container.querySelectorAll('.score-fill').forEach((fill) => {
            const score = Number(fill.getAttribute('data-score') || 0);
            fill.classList.remove('score-fill-high', 'score-fill-medium', 'score-fill-low');
            fill.classList.add(score >= 80 ? 'score-fill-high' : score >= 60 ? 'score-fill-medium' : 'score-fill-low');
            fill.setAttribute('aria-hidden', 'true');
        });
        container.querySelectorAll('.source-score').forEach((score) => {
            const label = score.querySelector('.jurix-rag-score-label');
            const value = score.querySelector('span');
            if (!label && value) {
                const span = document.createElement('span');
                span.className = 'jurix-rag-score-label';
                span.textContent = 'Relevância da fonte';
                score.insertBefore(span, score.firstChild);
            }
        });
    }

    function announce(message) {
        const live = document.getElementById('rag-stream-status');
        if (live) live.textContent = message || '';
    }

    function safeHttpUrl(value) {
        if (!value) return null;
        try {
            const url = new URL(String(value), window.location.href);
            return url.protocol === 'http:' || url.protocol === 'https:' ? url.href : null;
        } catch (_) {
            return null;
        }
    }

    function getSourceScore(source) {
        let rawScore = source?.similarity_score;
        if (rawScore === undefined || rawScore === null) {
            rawScore = Math.max(0, 1 - parseFloat(source?.distance || 1));
        }
        const normalized = Math.max(0, Math.min(1, Number.parseFloat(rawScore) || 0));
        return {
            normalized,
            percent: Math.max(1, Math.min(100, Math.round(normalized * 100))),
        };
    }

    function renderEvidenceCard(source, index = 0) {
        const safeSource = source || {};
        const { normalized, percent } = getSourceScore(safeSource);
        const band = normalized >= 0.8 ? 'high' : normalized >= 0.6 ? 'medium' : 'low';
        const relevanceLabel = band === 'high'
            ? 'Alta correspondência'
            : band === 'medium'
            ? 'Boa correspondência'
            : 'Baixa correspondência';

        const normaRef = safeSource.norma || safeSource.norma_ref || 'Norma jurídica';
        const dispositivoRef = safeSource.dispositivo_ref || '';
        const sourceType = safeSource.tipo || safeSource.type || '';
        const status = safeSource.status_label || safeSource.vigencia || safeSource.situacao || '';
        const snippet = String(safeSource.text || safeSource.full_text || '').trim();
        const linkUrl = safeHttpUrl(safeSource.sapl_url) || safeHttpUrl(safeSource.pdf_url);
        const cardLabel = `Fonte jurídica ${index + 1}: ${normaRef}`;

        const meta = [
            dispositivoRef ? `<span class="jurix-rag-source__meta-item">${escapeHtml(dispositivoRef)}</span>` : '',
            sourceType ? `<span class="jurix-rag-source__meta-item">${escapeHtml(sourceType)}</span>` : '',
            status ? `<span class="jurix-rag-source__meta-item jurix-rag-source__meta-item--status">${escapeHtml(status)}</span>` : '',
        ].join('');

        const openAction = linkUrl
            ? `
                <a
                    class="jurix-rag-source__open"
                    href="${escapeHtml(linkUrl)}"
                    target="_blank"
                    rel="noopener noreferrer"
                >
                    Abrir fonte
                    <span aria-hidden="true">↗</span>
                </a>
            `
            : '';

        return `
            <article
                class="source-card jurix-rag-source jurix-rag-source--${band}"
                id="jurix-evidence-${index + 1}"
                aria-label="${escapeHtml(cardLabel)}"
                data-evidence-rank="${index + 1}"
                data-evidence-band="${band}"
            >
                <div class="source-card-header">
                    <div class="source-title">${escapeHtml(normaRef)}</div>
                    <div class="source-score" aria-label="Relevância da fonte: ${percent}%">
                        <span class="jurix-rag-score-label">Relevância</span>
                        <div class="score-bar" aria-hidden="true">
                            <div class="score-fill score-fill-${band}"></div>
                        </div>
                        <span class="jurix-rag-score-text">${percent}%</span>
                    </div>
                </div>

                ${meta ? `<div class="jurix-rag-source__meta-row">${meta}</div>` : ''}

                <div class="source-snippet">${escapeHtml(snippet.substring(0, 280))}${snippet.length > 280 ? '…' : ''}</div>

                ${snippet
                    ? `
                        <details class="jurix-rag-source__details">
                            <summary>Ver trecho completo</summary>
                            <p>${escapeHtml(snippet)}</p>
                        </details>
                    `
                    : ''
                }

                <div class="jurix-rag-source__actions">
                    ${openAction}
                </div>

                <span class="jurix-rag-sr-only">${escapeHtml(relevanceLabel)}. Similaridade da recuperação: ${percent}%.</span>
            </article>
        `;
    }

    function focusEvidence(index) {
        const target = document.getElementById(`jurix-evidence-${Number(index)}`);
        if (!target) {
            announce(`Fonte ${Number(index)} não encontrada.`);
            return;
        }
        target.scrollIntoView({ behavior: 'smooth', block: 'center' });
        target.classList.add('is-citation-target');
        window.setTimeout(() => target.classList.remove('is-citation-target'), 1400);
        announce(`Fonte ${Number(index)} destacada.`);
    }

    document.addEventListener('click', (event) => {
        const citation = event.target.closest ? event.target.closest('.jurix-citation[data-source-index]') : null;
        if (!citation) return;
        event.preventDefault();
        focusEvidence(citation.dataset.sourceIndex);
    });

    window.JurixRagUI = {
        scheduleRender,
        flushRender,
        setStreamingState,
        renderErrorState,
        enhanceSources,
        announce,
        renderEvidenceCard,
        focusEvidence,
    };
})();
