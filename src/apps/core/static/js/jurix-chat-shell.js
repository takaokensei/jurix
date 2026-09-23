/**
 * Jurix Chat Shell
 *
 * Phase 13–15 progressive-enhancement layer:
 * - composer ergonomics and character feedback
 * - offline/network feedback
 * - accessible live announcements and focus recovery
 *
 * It deliberately does not own message state, transport or streaming.
 */
(function () {
    'use strict';

    const MAX_LENGTH = 10000;
    const NEAR_LIMIT = 9000;
    let networkTimer = null;

    function byId(id) {
        return document.getElementById(id);
    }

    function getComposer() {
        return byId('question-textarea');
    }

    function getForm() {
        return byId('chat-form');
    }

    function ensureLiveRegion() {
        let region = byId('jurix-chat-live-status');
        if (region) return region;
        region = document.createElement('div');
        region.id = 'jurix-chat-live-status';
        region.className = 'jurix-sr-status';
        region.setAttribute('role', 'status');
        region.setAttribute('aria-live', 'polite');
        region.setAttribute('aria-atomic', 'true');
        document.body.appendChild(region);
        return region;
    }

    function announce(message) {
        const region = ensureLiveRegion();
        region.textContent = '';
        window.setTimeout(() => {
            region.textContent = message;
        }, 10);
    }

    function ensureNetworkBanner() {
        let banner = byId('jurix-network-status');
        if (banner) return banner;
        banner = document.createElement('div');
        banner.id = 'jurix-network-status';
        banner.className = 'jurix-network-status';
        banner.setAttribute('role', 'status');
        banner.setAttribute('aria-live', 'polite');
        banner.innerHTML = `
            <span class="jurix-network-status__dot" aria-hidden="true"></span>
            <span class="jurix-network-status__text"></span>
        `;
        document.body.appendChild(banner);
        return banner;
    }

    function showNetworkStatus(message, type = 'error', duration = 4500) {
        const banner = ensureNetworkBanner();
        const text = banner.querySelector('.jurix-network-status__text');
        if (text) text.textContent = message;
        banner.classList.remove('is-error', 'is-offline');
        if (type === 'offline') banner.classList.add('is-offline');
        else banner.classList.add('is-error');
        banner.classList.add('is-visible');
        window.clearTimeout(networkTimer);
        if (duration > 0) {
            networkTimer = window.setTimeout(() => {
                banner.classList.remove('is-visible');
            }, duration);
        }
    }

    function hideNetworkStatus() {
        const banner = byId('jurix-network-status');
        if (banner) banner.classList.remove('is-visible');
    }

    function ensureCounter() {
        const composer = getComposer();
        if (!composer || byId('jurix-composer-counter')) return;
        const meta = document.createElement('div');
        meta.className = 'jurix-composer-meta';
        meta.innerHTML = `
            <span aria-hidden="true">Enter para enviar · Shift+Enter para nova linha</span>
            <span id="jurix-composer-counter" class="jurix-composer-counter">0/${MAX_LENGTH}</span>
        `;
        const parent = composer.closest('form') || composer.parentElement;
        if (parent) parent.appendChild(meta);
    }

    function updateCounter() {
        const composer = getComposer();
        const counter = byId('jurix-composer-counter');
        if (!composer || !counter) return;
        const length = composer.value.length;
        counter.textContent = `${length}/${MAX_LENGTH}`;
        counter.classList.toggle('is-near-limit', length >= NEAR_LIMIT && length < MAX_LENGTH);
        counter.classList.toggle('is-at-limit', length >= MAX_LENGTH);
        const describedBy = new Set(
            String(composer.getAttribute('aria-describedby') || '')
                .split(/\s+/)
                .filter(Boolean)
        );
        describedBy.add('jurix-composer-counter');
        composer.setAttribute('aria-describedby', Array.from(describedBy).join(' '));
    }

    function autosize() {
        const composer = getComposer();
        if (!composer) return;
        composer.style.height = 'auto';
        composer.style.height = `${Math.min(composer.scrollHeight, 200)}px`;
    }

    function persistDraft() {
        const composer = getComposer();
        if (!composer) return;
        const sessionId = window.JurixChatState && typeof window.JurixChatState.snapshot === 'function' ? window.JurixChatState.snapshot().sessionId : null;
if (!sessionId) return;
try {
    const value = composer.value;
    if (value) localStorage.setItem(`chat-input-${sessionId}`, value);
    else localStorage.removeItem(`chat-input-${sessionId}`);
} catch (error) {
    console.warn('Jurix draft persistence unavailable:', error);
}
    }

    function onComposerInput() {
        const composer = getComposer();
        if (!composer) return;
        if (composer.value.length > MAX_LENGTH) {
            composer.value = composer.value.slice(0, MAX_LENGTH);
        }
        updateCounter();
        autosize();
        persistDraft();
    }

    function onComposerKeydown(event) {
    if (event.key !== 'Enter' || event.shiftKey || event.isComposing) return;

    const composer = getComposer();
    const form = getForm();
    const chatState = window.JurixChatState;

    if (!composer || !form || !composer.value.trim()) return;
    if (chatState && typeof chatState.isBusy === 'function' && chatState.isBusy()) return;

    event.preventDefault();
    if (typeof form.requestSubmit === 'function') {
        form.requestSubmit();
    } else {
        form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    }
}

    function focusComposer() {
        const composer = getComposer();
        if (!composer || composer.disabled) return;
        window.requestAnimationFrame(() => {
            composer.focus({ preventScroll: true });
        });
    }

    function handleState(event) {
        const detail = event.detail || {};
        const state = detail.state;
        if (state === 'submitting') {
            announce('Pergunta enviada. Preparando pesquisa jurídica.');
        } else if (state === 'streaming') {
            announce('Gerando resposta jurídica.');
        } else if (state === 'regenerating') {
            announce('Regenerando resposta jurídica.');
        } else if (state === 'error') {
            announce('Ocorreu um erro ao gerar a resposta.');
            focusComposer();
        } else if (state === 'idle') {
            focusComposer();
        }
    }

    function handleOnline() {
        hideNetworkStatus();
        announce('Conexão restaurada.');
    }

    function handleOffline() {
        showNetworkStatus('Sem conexão. A resposta não poderá ser enviada até a conexão voltar.', 'offline', 0);
        announce('Sem conexão com a internet.');
    }

    function handleUnhandledRejection(event) {
        const reason = event.reason;
        if (!reason) return;
        const message = String(reason.message || reason);
        if (/network|fetch|failed to fetch|offline/i.test(message)) {
            showNetworkStatus('Não foi possível conectar ao Jurix. Tente novamente.', 'error');
        }
    }

    // ===== RECENT SEARCHES (home screen) =====

    /**
     * Converts an ISO date string to a human-readable relative time in Portuguese.
     * e.g. "há 2 horas", "ontem", "há 3 dias"
     */
    function relativeTime(isoString) {
        if (!isoString) return '';
        const diff = Date.now() - new Date(isoString).getTime();
        const minutes = Math.floor(diff / 60000);
        if (minutes < 1) return 'agora mesmo';
        if (minutes < 60) return `há ${minutes} min`;
        const hours = Math.floor(minutes / 60);
        if (hours < 24) return `há ${hours} hora${hours > 1 ? 's' : ''}`;
        const days = Math.floor(hours / 24);
        if (days === 1) return 'ontem';
        if (days < 30) return `há ${days} dias`;
        const months = Math.floor(days / 30);
        return `há ${months} ${months > 1 ? 'meses' : 'mês'}`;
    }

    /**
     * Escapes HTML special characters to prevent XSS.
     */
    function escapeHtml(str) {
        return String(str || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    /**
     * Renders a single session as a recent-search row.
     * Clicking navigates to the session via jurixChat.loadSession if available,
     * otherwise falls back to the slug URL.
     */
    function buildRecentSearchRow(session) {
        const row = document.createElement('div');
        row.className = 'figma-recent-search-row';
        row.setAttribute('role', 'button');
        row.setAttribute('tabindex', '0');
        row.setAttribute('aria-label', `Abrir conversa: ${session.title}`);

        const title = escapeHtml(session.latest_message_preview || session.title || 'Conversa sem título');
        const time = relativeTime(session.updated_at);
        const msgCount = typeof session.message_count === 'number' ? session.message_count : null;
        const msgLabel = msgCount !== null
            ? `${msgCount} mensage${msgCount !== 1 ? 'ns' : 'm'}`
            : '';

        row.innerHTML = `
            <div class="figma-col-query">
                <div class="figma-query-title">${title}</div>
            </div>
            <div class="figma-col-time">
                <div class="figma-meta-texts">
                    <span class="figma-meta-value">${escapeHtml(time)}</span>
                </div>
            </div>
            ${msgLabel ? `<div class="figma-col-docs">
                <span class="figma-doc-dot figma-dot-green"></span>
                <span class="figma-doc-text">${escapeHtml(msgLabel)}</span>
            </div>` : ''}
        `;

        function openSession() {
            if (window.jurixChat && typeof window.jurixChat.loadSession === 'function') {
                window.jurixChat.loadSession(session.id);
            } else if (session.slug) {
                window.location.href = `/c/${encodeURIComponent(session.slug)}/`;
            }
        }

        row.addEventListener('click', openSession);
        row.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                openSession();
            }
        });

        return row;
    }

    /**
     * Fetches the user's recent sessions and renders them in the "Pesquisa recente" section.
     * Uses chatAPI (jurix-chat-api.js) which must be loaded before this script.
     */
    async function loadRecentSearches() {
        const list = byId('figma-recent-searches-list');
        const loading = byId('figma-recent-searches-loading');
        const empty = byId('figma-recent-searches-empty');
        const newChatLink = byId('figma-new-chat-link');

        // Section not present on this page — nothing to do.
        if (!list) return;

        // Wire the "Inicie uma pesquisa" link to the new-chat button if available.
        if (newChatLink) {
            newChatLink.addEventListener('click', (e) => {
                e.preventDefault();
                const btn = byId('new-chat-button');
                if (btn) btn.click();
            });
        }

        if (!window.JurixChatAPI || typeof window.JurixChatAPI.listSessions !== 'function') {
            // chatAPI not available; hide loading silently.
            if (loading) loading.hidden = true;
            return;
        }

        try {
            const data = await window.JurixChatAPI.listSessions();
            if (loading) loading.hidden = true;

            if (!data || !data.success || !Array.isArray(data.sessions) || data.sessions.length === 0) {
                if (empty) empty.hidden = false;
                return;
            }

            // Show at most 5 sessions.
            const sessions = data.sessions.slice(0, 5);
            const fragment = document.createDocumentFragment();
            sessions.forEach((s) => fragment.appendChild(buildRecentSearchRow(s)));
            list.appendChild(fragment);
        } catch (_err) {
            // Silently hide loading on error — don't break the page.
            if (loading) loading.hidden = true;
        }
    }

    function init() {
        ensureLiveRegion();
        ensureNetworkBanner();
        ensureCounter();
        const composer = getComposer();
        if (composer) {
            composer.maxLength = MAX_LENGTH;
            composer.addEventListener('input', onComposerInput);
            composer.addEventListener('keydown', onComposerKeydown);
            updateCounter();
            autosize();
        }
        document.addEventListener('jurij:chat-state', handleState);
        window.addEventListener('online', handleOnline);
        window.addEventListener('offline', handleOffline);
        window.addEventListener('unhandledrejection', handleUnhandledRejection);
        if (!navigator.onLine) handleOffline();

        // Load real data into "Pesquisa recente" section (home screen only).
        loadRecentSearches();
    }

    window.JurixChatShell = {
        announce,
        focusComposer,
        showNetworkStatus,
        hideNetworkStatus,
        updateCounter,
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init, { once: true });
    } else {
        init();
    }
})();
