/* Jurix RAG UI — Phase 2 */
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
        ALLOWED_ATTR: ['href', 'title', 'target', 'rel', 'class'],
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

    window.JurixRagUI = {
        scheduleRender,
        flushRender,
        setStreamingState,
        renderErrorState,
        enhanceSources,
        announce,
    };
})();
