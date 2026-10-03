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
        ALLOWED_ATTR: ['href', 'title', 'target', 'rel', 'class', 'data-source-index', 'data-citation-id', 'aria-label'],
        FORBID_TAGS: ['style', 'script', 'iframe', 'object', 'embed', 'form', 'input', 'button', 'svg', 'math'],
        FORBID_ATTR: ['style', 'onclick', 'onerror', 'onload', 'src', 'srcset', 'poster', 'action', 'formaction'],
        ALLOW_UNKNOWN_PROTOCOLS: false,
    };

    const state = new WeakMap();
    let evidenceId = 0;
    let lastSourceTrigger = null;
    let drawerListenersBound = false;
    let currentSourcesDrawerContext = null;

    function commitMarkdown(element, markdown, sources = []) {
        const container = document.getElementById('messages-container');
        const follow = container && container.scrollHeight - container.scrollTop - container.clientHeight < 100;
        element.innerHTML = renderMarkdown(markdown, sources);
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

    function renderMarkdown(markdown, sources = []) {
        const source = String(markdown || '');
        if (window.JurixMarkdown && typeof window.JurixMarkdown.render === 'function') {
            return window.JurixMarkdown.render(source, sources);
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
            commitMarkdown(element, current.markdown, current.sources || []);
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
        commitMarkdown(element, markdown, current.sources || []);
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

    function setCitationSources(element, sources) {
        if (!element) return;
        const current = state.get(element) || {};
        current.sources = Array.isArray(sources) ? sources : [];
        state.set(element, current);
        if (typeof current.markdown === 'string') scheduleRender(element, current.markdown);
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
        if (error?.code === 'NETWORK_ERROR' || /^(?:failed to fetch|networkerror when attempting to fetch resource\.?|load failed|network request failed|err_network)/i.test(String(error?.message || '').trim())) {
            if (typeof navigator !== 'undefined' && navigator.onLine === false) {
                return {
                    title: 'Sem conexão com a internet',
                    detail: 'Reconecte-se à internet e tente novamente.',
                    tone: 'error'
                };
            }
            return {
                title: 'Falha na comunicação',
                detail: 'Não foi possível concluir a solicitação. O serviço pode estar temporariamente indisponível; tente novamente.',
                tone: 'warning'
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
            if (score.closest('.jurix-rag-source--coverage, .jurix-rag-source--explicit')) return;
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

    function buildSourceUrl(source = {}) {
        const pdfUrl = safeHttpUrl(source.pdf_url);
        const url = pdfUrl || safeHttpUrl(source.sapl_url);
        if (!url) return null;

        const isPdf = Boolean(pdfUrl) || new URL(url).pathname.toLowerCase().endsWith('.pdf');
        // `text` is only a 200-character display preview from the API and ends in
        // "...". Use the exact full device text whenever it is available.
        const excerpt = String(source.full_text || source.text || '')
            .replace(/\s+/g, ' ')
            .trim()
            .replace(/(?:…|\.{3,})\s*$/, '')
            .trim();
        if (!isPdf || !excerpt) return url;

        // Long devices use exact beginning/end anchors. This keeps the URL short while
        // preventing a truncated preview or partial final word from breaking the match.
        const takeStart = (value, limit) => {
            let result = value.slice(0, limit);
            const boundary = result.lastIndexOf(' ');
            if (boundary > limit * 0.55) result = result.slice(0, boundary);
            return result.trim();
        };
        const takeEnd = (value, limit) => {
            let result = value.slice(-limit);
            const boundary = result.indexOf(' ');
            if (boundary >= 0 && boundary < limit * 0.45) result = result.slice(boundary + 1);
            return result.trim();
        };
        const fragment = excerpt.length > 190
            ? `${encodeURIComponent(takeStart(excerpt, 100))},${encodeURIComponent(takeEnd(excerpt, 90))}`
            : encodeURIComponent(excerpt);
        const target = new URL(url);
        target.hash = `:~:text=${fragment}`;
        return target.href;
    }

    function getSourceScore(source) {
        let rawScore = source?.similarity_score;
        if (rawScore === undefined || rawScore === null) {
            rawScore = Math.max(0, 1 - parseFloat(source?.distance || 1));
        }
        const normalized = Math.max(0, Math.min(1, Number.parseFloat(rawScore) || 0));
        return {
            normalized,
            percent: Math.max(0, Math.min(100, Math.round(normalized * 100))),
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

    function renderEvidenceCard(source, index = 0, options = {}) {
        const safeSource = source || {};
        const citationIndex = Number(safeSource.citation_index) || index + 1;
        const scopeBased = safeSource.retrieval_strategy === 'whole_norma';
        const explicitReference = safeSource.match_kind === 'explicit_reference';
        const { normalized, percent } = getSourceScore(safeSource);
        const band = scopeBased ? 'coverage' : explicitReference ? 'explicit' : normalized >= 0.8 ? 'high' : normalized >= 0.6 ? 'medium' : 'low';
        const relevanceLabel = getRelevanceLabel(normalized);
        const contributionLabel = getContributionLabel(safeSource, normalized);

        const normaRef = safeSource.norma || safeSource.norma_ref || 'Norma jurídica';
        const dispositivoRef = safeSource.dispositivo_ref || '';
        const sourceType = safeSource.source_type || safeSource.tipo || safeSource.type || '';
        const status = safeSource.status_label || safeSource.vigencia || safeSource.situacao || '';
        const snippet = String(safeSource.text || safeSource.full_text || '').trim();
        const linkUrl = buildSourceUrl(safeSource);
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
        const citationText = `${normaRef}${dispositivoRef ? `, ${dispositivoRef}` : ''}${snippet ? `: “${snippet}”` : ''}`;

        return `
            <article
                class="source-card jurix-rag-source jurix-rag-source--${band}${linkUrl ? ' source-card-clickable' : ''}"
                id="jurix-evidence-card-${++evidenceId}"
                aria-label="${escapeHtml(cardLabel)}"
                data-evidence-rank="${citationIndex}"
                data-evidence-band="${band}"
                ${linkUrl ? `data-url="${escapeHtml(linkUrl)}"` : ''}
            >
                <div class="source-card-header">
                    ${options.showNormTitle === false ? '' : `<div class="source-title">${escapeHtml(normaRef)}</div>`}
                    ${scopeBased
                        ? `<div class="source-score" aria-label="Dispositivo incluído no escopo da consulta"><span class="jurix-rag-score-text">${safeSource.evidence_scope === 'complete' ? 'Todos os dispositivos indexados' : 'Amostra da norma'}</span></div>`
                        : explicitReference
                        ? `<div class="source-score" aria-label="Dispositivo identificado pela referência normativa">
                            <span class="jurix-rag-score-label">Tipo de identificação</span>
                            <span class="jurix-rag-score-text">Dispositivo identificado</span>
                        </div>`
                        : `<div class="source-score" aria-label="${escapeHtml(relevanceLabel)}. Pontuação técnica: ${percent}%">
                            <span class="jurix-rag-score-label">Relevância</span>
                            <progress class="jurix-rag-score-meter jurix-rag-score-meter--${band}" max="100" value="${percent}" aria-hidden="true"></progress>
                            <span class="jurix-rag-score-text">${escapeHtml(relevanceLabel)}</span>
                        </div>`}
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
                    <button type="button" class="jurix-rag-source__copy" data-copy-legal-citation="${escapeHtml(citationText)}">Copiar citação</button>
                    ${openAction}
                </div>

                ${scopeBased || explicitReference ? '' : `<span class="jurix-rag-sr-only">${escapeHtml(relevanceLabel)}. Pontuação técnica de recuperação: ${percent}%.</span>`}
            </article>
        `;
    }

    function focusEvidence(index, scope = document) {
        const target = scope.querySelector(`[data-evidence-rank="${Number(index)}"]`);
        if (!target) {
            announce(`Fonte ${Number(index)} não encontrada.`);
            return;
        }
        const group = target.closest('details.jurix-source-group');
        if (group) group.open = true;
        if (typeof target.scrollIntoView === 'function') {
            target.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
        target.classList.add('is-citation-target');
        window.setTimeout(() => target.classList.remove('is-citation-target'), 1400);
        announce(`Fonte ${Number(index)} destacada.`);
    }

    function linkLegalReferences(container, sources = []) {
        if (!container || !Array.isArray(sources) || !sources.length) return;
        const normalize = value => String(value || '').normalize('NFKD')
            .replace(/[\u0300-\u036f]/g, '').toLowerCase();
        const normPattern = /\b(Lei(?:\s+Complementar)?|Decreto|Resolução|Portaria)\s+(?:n[º°o.]?\s*)?([\d.]+)\s*\/\s*(\d{4})\b/i;
        const normKey = match => match
            ? normalize(match[1]) + ':' + match[2].replace(/\./g, '').replace(/^0+(?=\d)/, '') + '/' + match[3]
            : null;
        const references = sources.map(source => {
            const norm = String(source?.norma || source?.norma_ref || '');
            const device = String(source?.dispositivo_ref || source?.hierarchy || '');
            const article = device.match(/\bart\.?\s*(\d+)/i)?.[1];
            const inciso = device.match(/\binciso\s+([IVXLCDM]+)\b/i)?.[1]?.toUpperCase();
            const href = buildSourceUrl(source);
            const identity = normKey(norm.match(normPattern));
            return identity && href ? { identity, article, inciso, href, label: norm + ', ' + device, device } : null;
        }).filter(Boolean);
        if (!references.length) return;

        const identities = [...new Set(references.map(item => item.identity))];
        let currentNorm = identities.length === 1 ? identities[0] : null;
        let currentArticle = null;
        const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT, {
            acceptNode(node) {
                return !node.nodeValue?.trim() || node.parentElement?.closest('a, code, pre, button, script, style')
                    ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT;
            },
        });
        const textNodes = [];
        while (walker.nextNode()) textNodes.push(walker.currentNode);
        const normExpression = normPattern.source;
        // Qualified articles override prior context; standalone labels reuse only recovered evidence.
        const pattern = new RegExp(
            normExpression + '|\\bArt\\.?\\s*\\d+[º°o]?(?:\\s+(?:da|do)\\s+' + normExpression
                + ')?|\\bInciss?o\\s+[IVXLCDM]+\\b', 'gi'
        );
        textNodes.forEach(node => {
            const text = node.nodeValue;
            pattern.lastIndex = 0;
            let match;
            let cursor = 0;
            const fragment = document.createDocumentFragment();
            let changed = false;
            while ((match = pattern.exec(text))) {
                const token = match[0];
                const explicitNorm = token.match(normPattern);
                const article = token.match(/\bArt\.?\s*(\d+)/i);
                const inciso = token.match(/^Inciss?o\s+([IVXLCDM]+)/i);
                if (explicitNorm) {
                    currentNorm = normKey(explicitNorm);
                    currentArticle = null;
                }
                if (article) currentArticle = article[1];
                const candidates = references.filter(item => item.identity === currentNorm);
                let reference;
                if (inciso) {
                    // Never guess which article a repeated inciso belongs to.
                    const matches = candidates.filter(item => item.inciso === inciso[1].toUpperCase()
                        && (!currentArticle || item.article === currentArticle));
                    if (new Set(matches.map(item => item.device)).size === 1) reference = matches[0];
                } else if (article) {
                    reference = candidates.find(item => item.article === currentArticle && !item.device.includes('>'))
                        || candidates.find(item => item.article === currentArticle);
                } else {
                    reference = candidates[0];
                }
                if (!reference) continue;
                fragment.append(document.createTextNode(text.slice(cursor, match.index)));
                const anchor = document.createElement('a');
                anchor.className = 'jurix-legal-reference-link';
                let targetHref = reference.href;
                let targetLabel = reference.label;
                if (explicitNorm && !article && !inciso) {
                    const lawUrl = new URL(targetHref);
                    if (lawUrl.hash.startsWith('#:~:text=')) lawUrl.hash = '';
                    targetHref = lawUrl.href;
                    targetLabel = token;
                }
                anchor.href = targetHref;
                anchor.target = '_blank';
                anchor.rel = 'noopener noreferrer';
                anchor.title = 'Abrir ' + targetLabel + ' no SAPL (nova aba)';
                anchor.setAttribute('aria-label', anchor.title);
                anchor.textContent = token;
                fragment.append(anchor);
                cursor = pattern.lastIndex;
                changed = true;
            }
            if (changed) {
                fragment.append(document.createTextNode(text.slice(cursor)));
                node.replaceWith(fragment);
            }
        });
    }

    async function copyLegalCitation(button) {
        const value = button.dataset.copyLegalCitation || '';
        if (!value) return;
        try {
            if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(value);
            else {
                const input = document.createElement('textarea');
                input.value = value;
                input.setAttribute('readonly', '');
                input.style.position = 'fixed';
                input.style.opacity = '0';
                document.body.appendChild(input);
                input.select();
                const copied = document.execCommand('copy');
                input.remove();
                if (!copied) throw new Error('Clipboard unavailable');
            }
            button.dataset.originalLabel ||= button.textContent;
            button.textContent = 'Citação copiada';
            button.classList.add('is-copied');
            announce('Citação copiada para a área de transferência.');
            window.setTimeout(() => {
                if (!button.isConnected) return;
                button.textContent = button.dataset.originalLabel || 'Copiar citação';
                button.classList.remove('is-copied');
            }, 1800);
        } catch (_) {
            announce('Não foi possível copiar. Selecione o texto da citação manualmente.');
        }
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
            panel.setAttribute('inert', '');
            panel.setAttribute('role', 'dialog');
            panel.setAttribute('aria-modal', 'false');
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

    function groupEvidenceByNorm(sources) {
        const groups = [];
        const groupsByKey = new Map();

        sources.forEach((source, index) => {
            const normName = String(source?.norma || source?.norma_ref || '').trim();
            const normalizedName = normName
                .normalize('NFKD')
                .replace(/[\u0300-\u036f]/g, '')
                .toLowerCase()
                .replace(/[^a-z0-9]/g, '');
            // Unknown titles are kept separate: grouping them could imply that
            // unrelated evidence belongs to the same legal instrument.
            const key = normalizedName || `unknown-source-${index}`;
            let group = groupsByKey.get(key);
            if (!group) {
                group = { key, title: normName || 'Norma não identificada', sources: [] };
                groupsByKey.set(key, group);
                groups.push(group);
            }
            group.sources.push({ source, index });
        });

        return groups;
    }

    function openSourcesDrawer(sources = [], title = 'Fontes Consultadas', metadata = {}) {
        const dom = ensureDrawerDOM();
        const { backdrop, panel, body, titleEl, subtitleEl } = dom;
        if (!panel || !body) return;
        lastSourceTrigger = document.activeElement instanceof HTMLElement ? document.activeElement : null;

        const safeSources = Array.isArray(sources) ? sources : [];
        const count = safeSources.length;
        const groups = groupEvidenceByNorm(safeSources);
        currentSourcesDrawerContext = { count, groups, metadata: { ...metadata } };
        if (titleEl) titleEl.textContent = `${title} (${count})`;
        renderSourcesDrawerSubtitle(subtitleEl, currentSourcesDrawerContext);

        body.innerHTML = '';
        let syncToggleAll = () => {};
        if (groups.length) {
            const controls = document.createElement('div');
            controls.className = 'jurix-source-group-controls';
            controls.innerHTML = '<button type="button" class="jurix-source-group-toggle-all" aria-expanded="false">Expandir todas as evidências</button>';
            const toggleAll = controls.querySelector('button');
            const groupsContainer = document.createElement('div');
            groupsContainer.className = 'jurix-source-groups';
            syncToggleAll = () => {
                const groups = [...groupsContainer.querySelectorAll('details.jurix-source-group')];
                const openCount = groups.filter((group) => group.open).length;
                const allOpen = groups.length > 0 && openCount === groups.length;
                toggleAll.setAttribute('aria-expanded', String(allOpen));
                toggleAll.textContent = allOpen
                    ? 'Recolher todas as evidências'
                    : openCount
                        ? `Expandir restantes (${openCount} de ${groups.length} abertas)`
                        : 'Expandir todas as evidências';
                toggleAll.dataset.state = allOpen ? 'all-open' : openCount ? 'partially-open' : 'all-closed';
            };
            toggleAll.addEventListener('click', () => {
                const expand = toggleAll.getAttribute('aria-expanded') !== 'true';
                groupsContainer.querySelectorAll('details.jurix-source-group').forEach((group) => { group.open = expand; });
                syncToggleAll();
            });
            body.appendChild(controls);
            body.appendChild(groupsContainer);
        }
        groups.forEach((group, groupIndex) => {
            const groupSection = document.createElement('details');
            groupSection.className = 'jurix-source-group';
            groupSection.open = false;
            groupSection.setAttribute('aria-labelledby', `jurix-source-group-title-${groupIndex}`);
            const evidenceLabel = group.sources.length === 1 ? '1 evidência' : `${group.sources.length} evidências`;
            groupSection.innerHTML = `
                <summary class="jurix-source-group__header">
                    <span class="jurix-source-group__disclosure" aria-hidden="true"></span>
                    <h4 class="jurix-source-group__title" id="jurix-source-group-title-${groupIndex}">${escapeHtml(group.title)}</h4>
                    <span class="jurix-source-group__count">${evidenceLabel}</span>
                </summary>
                <div class="jurix-source-group__cards"><div class="jurix-source-group__cards-inner"></div></div>
            `;
            const cards = groupSection.querySelector('.jurix-source-group__cards-inner');
            groupSection.addEventListener('toggle', syncToggleAll);
            group.sources.forEach(({ source, index }) => {
                cards.insertAdjacentHTML('beforeend', renderEvidenceCard(source, index, { showNormTitle: false }));
            });
            (body.querySelector('.jurix-source-groups') || body).appendChild(groupSection);
        });
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
        panel.inert = false;
        panel.setAttribute('aria-hidden', 'false');
        panel.setAttribute('aria-modal', 'true');
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
            panel.inert = true;
            panel.setAttribute('aria-hidden', 'true');
            panel.setAttribute('aria-modal', 'false');
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

    function renderSourcesDrawerSubtitle(subtitleEl, context) {
        if (!subtitleEl || !context) return;
        const { count, groups, metadata } = context;
        const evidenceLabel = count === 1 ? 'evidência' : 'evidências';
        const normLabel = groups.length === 1 ? 'norma' : 'normas';
        const validation = metadata.pending ? ' A resposta ainda está sendo validada.' : '';
        const coverage = metadata.coverage;
        const scope = coverage && !coverage.complete
            ? ` Amostra distribuída: ${coverage.selected_articles} de ${coverage.total_articles} artigos.`
            : '';
        subtitleEl.textContent = `${count} ${evidenceLabel} em ${groups.length} ${normLabel} do corpus municipal de Natal.${scope}${validation}`;
    }

    function updateSourcesDrawerMetadata(metadata = {}) {
        if (!currentSourcesDrawerContext) return;
        currentSourcesDrawerContext.metadata = { ...currentSourcesDrawerContext.metadata, ...metadata };
        renderSourcesDrawerSubtitle(
            document.querySelector('#jurix-sources-drawer-panel .jurix-sources-drawer-subtitle'),
            currentSourcesDrawerContext
        );
    }

    function clearSourcesDrawer() {
        const panel = document.getElementById('jurix-sources-drawer-panel');
        if (panel?.classList.contains('is-open')) closeSourcesDrawer();
        const body = panel?.querySelector('.jurix-sources-drawer-body');
        body?.replaceChildren();
        currentSourcesDrawerContext = null;
    }

    document.addEventListener('click', (event) => {
        if (!event.target || !event.target.closest) return;
        const copyButton = event.target.closest('[data-copy-legal-citation]');
        if (copyButton) {
            event.preventDefault();
            event.stopPropagation();
            copyLegalCitation(copyButton);
            return;
        }
        const sourceCard = event.target.closest('.source-card-clickable');
        if (sourceCard && !event.target.closest('a, button, summary')) {
            const sourceUrl = safeHttpUrl(sourceCard.dataset.url);
            if (sourceUrl) window.open(sourceUrl, '_blank', 'noopener,noreferrer');
        }
        const pill = event.target.closest('.jurix-sources-pill-btn');
        if (pill) {
            event.preventDefault();
            const sources = pill._sourcesData || [];
            openSourcesDrawer(sources, 'Fontes Consultadas', pill._sourcesMeta || {});
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
                openSourcesDrawer(sources, 'Fontes Consultadas', sourcesContainer?._sourcesMeta || {});
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
            'button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), summary, [tabindex]:not([tabindex="-1"])'
        )].filter((element) => {
            let ancestor = element.parentElement;
            while (ancestor && ancestor !== panel) {
                if (ancestor.matches('details:not([open])') && ancestor.querySelector(':scope > summary') !== element) {
                    return false;
                }
                ancestor = ancestor.parentElement;
            }
            return element.getClientRects().length > 0;
        });
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
        setCitationSources,
        setStreamingState,
        renderErrorState,
        enhanceSources,
        announce,
        renderEvidenceCard,
        buildSourceUrl,
        focusEvidence,
        linkLegalReferences,
        openSourcesDrawer,
        closeSourcesDrawer,
        updateSourcesDrawerMetadata,
        clearSourcesDrawer,
    };
})();
