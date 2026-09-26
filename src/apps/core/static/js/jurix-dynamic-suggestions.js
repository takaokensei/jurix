/**
 * Jurix Dynamic Corpus Suggestions
 * --------------------------------
 * The welcome screen contains no legal-question placeholders. Every suggestion
 * visible to the user is returned by the corpus API and is rendered safely here.
 */
(function () {
    'use strict';

    const ENDPOINT = '/api/v1/suggestions/';
    const LIMIT = 4;
    const CACHE_KEY = 'jurix:ui:suggestions:v3';
    const CACHE_TTL = 2 * 60 * 1000;
    let request = null;
    let lastItems = [];

    function escapeHtml(value) {
        const div = document.createElement('div');
        div.textContent = String(value ?? '');
        return div.innerHTML;
    }

    function escapeAttr(value) {
        return String(value ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function getRoot() {
        return document.getElementById('figma-suggestions-cards');
    }

    function setBusy(busy) {
        const root = getRoot();
        if (!root) return;
        root.setAttribute('aria-busy', busy ? 'true' : 'false');
        root.dataset.suggestionState = busy ? 'loading' : 'ready';
    }

    function renderLoading() {
        const root = getRoot();
        if (!root) return;
        setBusy(true);
        root.innerHTML = `
            <div class="jurix-suggestions-loading" role="status" aria-live="polite">
                <span class="jurix-suggestion-skeleton"></span>
                <span class="jurix-suggestion-skeleton"></span>
                <span class="jurix-suggestion-skeleton"></span>
            </div>`;
    }

    function renderEmpty() {
        const root = getRoot();
        if (!root) return;
        setBusy(false);
        root.innerHTML = `
            <div class="jurix-suggestions-empty" role="status">
                <span class="jurix-suggestions-empty-mark" aria-hidden="true">—</span>
                <div>
                    <strong>Sem sugestões disponíveis</strong>
                    <p>O corpus jurídico ainda não possui conteúdo suficiente para gerar perguntas contextuais.</p>
                </div>
            </div>`;
        const chips = document.getElementById('suggestion-chips');
        if (chips) chips.replaceChildren();
    }

    function render(items) {
        const root = getRoot();
        const chips = document.getElementById('suggestion-chips');
        if (!root) return;

        if (!Array.isArray(items) || items.length === 0) {
            renderEmpty();
            return;
        }

        const normalized = items
            .filter((item) => item && typeof item.question === 'string' && item.question.trim())
            .slice(0, LIMIT);
        if (!normalized.length) {
            renderEmpty();
            return;
        }

        setBusy(false);
        root.innerHTML = normalized.map((item) => {
            const question = item.question.trim();
            const title = (item.title || question).trim();
            const description = (item.description || item.topic || '').trim();
            const identifier = (item.identifier || '').trim();
            return `
                <button
                    type="button"
                    class="figma-suggestion-card jurix-dynamic-suggestion-card"
                    data-question="${escapeAttr(question)}"
                    data-source="corpus"
                    aria-label="Usar sugestão: ${escapeAttr(question)}"
                >
                    <span class="figma-suggestion-top">
                        <span class="figma-suggestion-title">${escapeHtml(title)}</span>
                        <span class="figma-suggestion-arrow" aria-hidden="true">→</span>
                    </span>
                    <span class="figma-suggestion-desc">${escapeHtml(description)}</span>
                    ${identifier ? `<span class="jurix-suggestion-source">${escapeHtml(identifier)}</span>` : ''}
                </button>`;
        }).join('');

        if (chips) {
            chips.innerHTML = normalized.slice(0, 3).map((item) => {
                const question = item.question.trim();
                return `<button type="button" class="chip" data-question="${escapeAttr(question)}">${escapeHtml(question)}</button>`;
            }).join('');
        }
        lastItems = normalized;
    }

    function readCache() {
        try {
            const raw = sessionStorage.getItem(CACHE_KEY);
            if (!raw) return null;
            const payload = JSON.parse(raw);
            if (!payload || Date.now() - Number(payload.time || 0) > CACHE_TTL) return null;
            return Array.isArray(payload.items) ? payload.items : null;
        } catch (_) {
            return null;
        }
    }

    function writeCache(items) {
        try {
            sessionStorage.setItem(CACHE_KEY, JSON.stringify({ time: Date.now(), items }));
        } catch (_) {}
    }

    async function fetchItems(signal) {
        const response = await fetch(`${ENDPOINT}?limit=${LIMIT}`, {
            method: 'GET',
            headers: { Accept: 'application/json' },
            credentials: 'same-origin',
            cache: 'no-store',
            signal,
        });
        if (!response.ok) throw new Error(`Suggestion API ${response.status}`);
        const payload = await response.json();
        if (!payload || payload.success !== true || payload.source !== 'municipal_natal_corpus' || !Array.isArray(payload.suggestions)) return [];
        return payload.suggestions;
    }

    async function refresh({ force = false } = {}) {
        const cached = force ? null : readCache();
        if (cached) {
            render(cached);
            return cached;
        }
        if (request) return request;

        renderLoading();
        const controller = new AbortController();
        const timeout = window.setTimeout(() => controller.abort(), 6500);
        request = fetchItems(controller.signal)
            .then((items) => {
                writeCache(items);
                render(items);
                return items;
            })
            .catch((error) => {
                console.warn('[Jurix] dynamic corpus suggestions unavailable', error);
                if (lastItems.length) render(lastItems);
                else renderEmpty();
                return [];
            })
            .finally(() => {
                window.clearTimeout(timeout);
                request = null;
            });
        return request;
    }

    function clearForNewSession() {
        lastItems = [];
        try { sessionStorage.removeItem(CACHE_KEY); } catch (_) {}
        refresh({ force: true });
    }

    window.JurixDynamicSuggestions = { refresh, clearForNewSession, getItems: () => [...lastItems] };

    document.addEventListener('DOMContentLoaded', () => {
        const root = getRoot();
        if (!root) return;
        refresh();
    });
})();
