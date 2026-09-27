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
    let evidenceId = 0;
    let lastSourceTrigger = null;
    let drawerListenersBound = false;

    function commitMarkdown(element, markdown) {
        const container = document.getElementById('messages-container');
        const follow = container && container.scrollHeight - container.scrollTop - container.clientHeight < 100;
        element.innerHTML = renderMarkdown(markdown);
        if (follow) container.scrollTop = container.scrollHeight;
    }

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
            commitMarkdown(element, current.markdown);
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
        commitMarkdown(element, markdown);
        if (typeof window.scrollToBottomIfAtBottom === 'function') {
            window.requestAnimationFrame(() => window.scrollToBottomIfAtBottom());
        }
    }

    function setStreamingState(element, isStreaming) {
        if (!element) return;
        const current = state.get(element) || {};
        current.streaming = isStreaming;
        state.set(element, current);
        element.classList.toggle('is-streaming', isStreaming);
        element.toggleAttribute('data-streaming', isStreaming);
    }

    function getStatus(error) {
        return Number(error?.status || error?.response?.status || 0);
    }

    function errorCopy(error) {
        if (error?.code === 'RAG_STREAM_ERROR' || error?.code === 'INCOMPLETE_STREAM') {
            return { title: 'Resposta interrompida', detail: String(error.message), tone: 'warning' };
        }
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

    function getRelevanceLabel(normalized) {
        if (normalized >= 0.8) return 'Alta correspondência';
        if (normalized >= 0.6) return 'Boa correspondência';
        if (normalized >= 0.4) return 'Correspondência parcial';
        return 'Baixa correspondência';
    }

    function getContributionLabel(source, normalized) {
        const explicit = source?.contribution || source?.evidence_role || source?.source_role;
        if (explicit) return String(explicit);
        if (normalized < 0.4) return 'Contexto relacionado';
        if (source?.dispositivo_ref || source?.hierarchy) return 'Trecho de dispositivo';
        return 'Fonte normativa relacionada';
    }

    function renderEvidenceCard(source, index = 0) {
        const safeSource = source || {};
        const { normalized, percent } = getSourceScore(safeSource);
        const band = normalized >= 0.8 ? 'high' : normalized >= 0.6 ? 'medium' : 'low';
        const relevanceLabel = getRelevanceLabel(normalized);
        const contributionLabel = getContributionLabel(safeSource, normalized);

        const normaRef = safeSource.norma || safeSource.norma_ref || 'Norma jurídica';
        const dispositivoRef = safeSource.dispositivo_ref || '';
        const sourceType = safeSource.source_type || safeSource.tipo || safeSource.type || '';
        const status = safeSource.status_label || safeSource.vigencia || safeSource.situacao || '';
        const snippet = String(safeSource.text || safeSource.full_text || '').trim();
        const linkUrl = safeHttpUrl(safeSource.pdf_url) || safeHttpUrl(safeSource.sapl_url);
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
                    ${linkUrl.includes('sapl') ? 'Abrir no SAPL' : 'Abrir fonte oficial'}
                    <span aria-hidden="true">↗</span>
                </a>
            `
            : '';

        return `
            <article
                class="source-card jurix-rag-source jurix-rag-source--${band}${linkUrl ? ' source-card-clickable' : ''}"
                id="jurix-evidence-${++evidenceId}"
                aria-label="${escapeHtml(cardLabel)}"
                data-evidence-rank="${index + 1}"
                data-evidence-band="${band}"
                ${linkUrl ? `data-url="${escapeHtml(linkUrl)}"` : ''}
            >
                <div class="source-card-header">
                    <div class="source-title">${escapeHtml(normaRef)}</div>
                    <div class="source-score" aria-label="${escapeHtml(relevanceLabel)}. Pontuação técnica: ${percent}%">
                        <span class="jurix-rag-score-label">Relevância</span>
                        <div class="score-bar" aria-hidden="true">
                            <div class="score-fill score-fill-${band}"></div>
                        </div>
                        <span class="jurix-rag-score-text">${escapeHtml(relevanceLabel)}</span>
                    </div>
                </div>

                ${meta ? `<div class="jurix-rag-source__meta-row">${meta}</div>` : ''}

                <div class="jurix-rag-source__contribution">
                    <span class="jurix-rag-source__contribution-label">Contribuição</span>
                    <span>${escapeHtml(contributionLabel)}</span>
                </div>

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

                <span class="jurix-rag-sr-only">${escapeHtml(relevanceLabel)}. Pontuação técnica de recuperação: ${percent}%.</span>
            </article>
        `;
    }

    function focusEvidence(index, scope = document) {
        const target = scope.querySelector(`[data-evidence-rank="${Number(index)}"]`);
        if (!target) {
            announce(`Fonte ${Number(index)} não encontrada.`);
            return;
        }
        if (typeof target.scrollIntoView === 'function') {
            target.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
        target.classList.add('is-citation-target');
        window.setTimeout(() => target.classList.remove('is-citation-target'), 1400);
        announce(`Fonte ${Number(index)} destacada.`);
    }

    function ensureDrawerDOM() {
        let backdrop = document.getElementById('jurix-sources-drawer-backdrop');
        let panel = document.getElementById('jurix-sources-drawer-panel');
        if (!backdrop) {
            backdrop = document.createElement('div');
            backdrop.id = 'jurix-sources-drawer-backdrop';
            backdrop.className = 'jurix-sources-drawer-backdrop';
            backdrop.setAttribute('aria-hidden', 'true');
            document.body.appendChild(backdrop);
        }
        if (!panel) {
            panel = document.createElement('aside');
            panel.id = 'jurix-sources-drawer-panel';
            panel.className = 'jurix-sources-drawer-panel';
            panel.setAttribute('aria-hidden', 'true');
            panel.setAttribute('role', 'dialog');
            panel.setAttribute('aria-modal', 'true');
            panel.setAttribute('tabindex', '-1');
            panel.setAttribute('aria-labelledby', 'sources-drawer-title');
            panel.setAttribute('aria-describedby', 'sources-drawer-subtitle');
            panel.innerHTML = `
                <div class="jurix-sources-drawer-header">
                    <div class="jurix-sources-drawer-title-group">
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#60A5FA" stroke-width="2">
                            <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/>
                        </svg>
                        <h3 id="sources-drawer-title">Fontes Consultadas</h3>
                    </div>
                    <button type="button" class="jurix-sources-drawer-close" id="jurix-sources-drawer-close" aria-label="Fechar painel de fontes">
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <line x1="18" y1="6" x2="6" y2="18"></line>
                            <line x1="6" y1="6" x2="18" y2="18"></line>
                        </svg>
                    </button>
                </div>
                <div class="jurix-sources-drawer-subtitle" id="sources-drawer-subtitle">
                    Evidências legislativas recuperadas para fundamentar a resposta com exatidão jurídica.
                </div>
                <div class="jurix-sources-drawer-body" id="jurix-sources-drawer-body"></div>
            `;
            document.body.appendChild(panel);
        }
        if (!drawerListenersBound) {
            const closeButton = panel.querySelector('#jurix-sources-drawer-close');
            const closeHandler = (event) => {
                event.preventDefault();
                event.stopPropagation();
                closeSourcesDrawer();
            };
            if (closeButton) closeButton.dataset.bound = 'true';
            closeButton?.addEventListener('click', closeHandler);
            backdrop?.addEventListener('click', closeHandler);
            drawerListenersBound = true;
        }
        return {
            backdrop,
            panel,
            body: panel.querySelector('#jurix-sources-drawer-body') || document.getElementById('jurix-sources-drawer-body'),
            titleEl: panel.querySelector('#sources-drawer-title') || document.getElementById('sources-drawer-title'),
            subtitleEl: panel.querySelector('#sources-drawer-subtitle') || document.getElementById('sources-drawer-subtitle'),
        };
    }

    function openSourcesDrawer(sources = [], title = 'Fontes Consultadas') {
        const dom = ensureDrawerDOM();
        const { backdrop, panel, body, titleEl, subtitleEl } = dom;
        if (!panel || !body) return;
        lastSourceTrigger = document.activeElement instanceof HTMLElement ? document.activeElement : null;

        const count = Array.isArray(sources) ? sources.length : 0;
        if (titleEl) titleEl.textContent = `${title} (${count})`;
        if (subtitleEl) {
            subtitleEl.textContent = `${count} ${count === 1 ? 'dispositivo recuperado' : 'dispositivos recuperados'} do corpus municipal de Natal.`;
        }

        body.innerHTML = '';
        if (Array.isArray(sources)) {
            sources.forEach((source, index) => {
                const cardHtml = renderEvidenceCard(source, index);
                body.insertAdjacentHTML('beforeend', cardHtml);
            });
        }
        if (!body.children.length) {
            body.innerHTML = `
                <div class="jurix-sources-empty" role="status">
                    <strong>As evidências não estão disponíveis nesta restauração.</strong>
                    <p>Recarregue a conversa para tentar recuperar os trechos usados na resposta. Até lá, confirme a informação na fonte oficial antes de utilizá-la.</p>
                    <button type="button" class="jurix-sources-empty-retry">Recarregar conversa</button>
                </div>
            `;
            body.querySelector('.jurix-sources-empty-retry')?.addEventListener('click', () => {
                window.location.reload();
            }, { once: true });
        }

        panel.classList.add('is-open');
        panel.setAttribute('aria-hidden', 'false');
        if (backdrop) {
            backdrop.classList.add('is-open');
            backdrop.setAttribute('aria-hidden', 'false');
        }
        document.body.classList.add('jurix-sources-drawer-open');
        window.requestAnimationFrame(() => {
            document.getElementById('jurix-sources-drawer-close')?.focus();
        });
    }

    function closeSourcesDrawer() {
        const backdrop = document.getElementById('jurix-sources-drawer-backdrop');
        const panel = document.getElementById('jurix-sources-drawer-panel');
        if (panel) {
            panel.classList.remove('is-open');
            panel.setAttribute('aria-hidden', 'true');
        }
        if (backdrop) {
            backdrop.classList.remove('is-open');
            backdrop.setAttribute('aria-hidden', 'true');
        }
        document.body.classList.remove('jurix-sources-drawer-open');
        if (lastSourceTrigger && document.contains(lastSourceTrigger)) {
            lastSourceTrigger.focus();
        }
        lastSourceTrigger = null;
    }

    document.addEventListener('click', (event) => {
        if (!event.target || !event.target.closest) return;
        const pill = event.target.closest('.jurix-sources-pill-btn');
        if (pill) {
            event.preventDefault();
            const sources = pill._sourcesData || [];
            openSourcesDrawer(sources, 'Fontes Consultadas');
            return;
        }
        if (event.target.closest('#jurix-sources-drawer-close') || event.target.closest('#jurix-sources-drawer-backdrop')) {
            if (event.target.closest('#jurix-sources-drawer-close')?.dataset.bound === 'true') return;
            event.preventDefault();
            closeSourcesDrawer();
            return;
        }
        const citation = event.target.closest('.jurix-citation[data-source-index]');
        if (citation) {
            event.preventDefault();
            const message = citation.closest('.message');
            const sourcesContainer = message?.querySelector('[id^="sources-"]');
            const sources = sourcesContainer?._sourcesData || [];
            const sourceIndex = citation.dataset.sourceIndex;

            // Evidence cards live in the global drawer, not inside the message
            // that contains the citation. Open that drawer before resolving the
            // target; otherwise citation clicks silently announce "not found".
            if (sources.length > 0) {
                openSourcesDrawer(sources, 'Fontes Consultadas');
                window.requestAnimationFrame(() => focusEvidence(sourceIndex, document));
            } else {
                focusEvidence(sourceIndex, document);
            }
        }
    });

    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape') {
            closeSourcesDrawer();
            return;
        }
        if (event.key !== 'Tab') return;

        const panel = document.getElementById('jurix-sources-drawer-panel');
        if (!panel || panel.getAttribute('aria-hidden') === 'true') return;

        const focusable = [...panel.querySelectorAll(
            'button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
        )].filter((element) => element.getClientRects().length > 0);
        if (!focusable.length) {
            event.preventDefault();
            panel.focus();
            return;
        }

        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) {
            event.preventDefault();
            last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault();
            first.focus();
        }
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
        openSourcesDrawer,
        closeSourcesDrawer,
    };
})();
