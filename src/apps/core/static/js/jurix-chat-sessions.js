(function () {
    'use strict';

    const SESSION_SELECTOR = '.chat-session-item[data-session-id]';
    const ENHANCED_ATTR = 'data-jurix-session-enhanced';

    function getSessionId(item) {
        const rawId = item && item.dataset ? item.dataset.sessionId : null;
        const id = Number(rawId);
        return Number.isFinite(id) ? id : null;
    }

    function syncActiveState(item) {
        if (!item) return;
        if (item.classList.contains('active')) {
            item.setAttribute('aria-current', 'page');
        } else {
            item.removeAttribute('aria-current');
        }
    }

    function normalizeContentWrapper(item) {
        const wrapper = item.querySelector('.chat-session-main') || Array.from(item.children).find(
            (child) => child instanceof HTMLElement && !child.classList.contains('delete-session-button')
        );
        if (!wrapper) return;
        wrapper.classList.add('chat-session-main');
        wrapper.style.removeProperty('flex');
        wrapper.style.removeProperty('min-width');
    }

    function runEntryAnimation(item) {
        item.classList.add('jurix-session-entering');
        item.style.removeProperty('opacity');
        item.style.removeProperty('transform');
        item.style.removeProperty('transition');

        window.requestAnimationFrame(() => {
            item.classList.remove('jurix-session-entering');
        });
    }

    function enhanceItem(item) {
        const sessionId = getSessionId(item);
        if (sessionId === null) return;

        item.dataset.loadSessionId = String(sessionId);
        item.setAttribute('role', 'button');
        item.setAttribute('tabindex', '0');
        syncActiveState(item);
        normalizeContentWrapper(item);

        if (item.getAttribute(ENHANCED_ATTR) === '1') return;
        item.setAttribute(ENHANCED_ATTR, '1');
        item.onclick = null;
        item.onkeydown = null;
        runEntryAnimation(item);

        item.addEventListener('click', (event) => {
            if (event.target.closest && event.target.closest('[data-delete-session-id]')) return;
            const id = getSessionId(item);
            if (id === null) return;
            if (window.jurixChat && typeof window.jurixChat.loadSession === 'function') {
                window.jurixChat.loadSession(id);
            }
        });

        item.addEventListener('keydown', (event) => {
            if (event.target.closest && event.target.closest('[data-delete-session-id]')) return;
            if (event.key !== 'Enter' && event.key !== ' ') return;
            event.preventDefault();
            const id = getSessionId(item);
            if (id === null) return;
            if (window.jurixChat && typeof window.jurixChat.loadSession === 'function') {
                window.jurixChat.loadSession(id);
            }
        });
    }

    function enhanceNewChatButton() {
        const button = document.getElementById('new-chat-button');
        if (!button) return;
        button.style.removeProperty('opacity');
        button.style.removeProperty('cursor');
    }

    function enhanceSessions() {
        document.querySelectorAll(SESSION_SELECTOR).forEach(enhanceItem);
        enhanceNewChatButton();
    }

    function observeSessionState() {
        const list = document.getElementById('chat-sessions-list');
        if (!list) return;

        const observer = new MutationObserver((mutations) => {
            let shouldRefresh = false;
            for (const mutation of mutations) {
                if (mutation.type === 'childList' || mutation.type === 'attributes') {
                    shouldRefresh = true;
                    break;
                }
            }
            if (shouldRefresh) enhanceSessions();
        });

        observer.observe(list, {
            childList: true,
            subtree: true,
            attributes: true,
            attributeFilter: ['class', 'style', 'data-session-id'],
        });
    }

    function init() {
        enhanceSessions();
        observeSessionState();
    }

    window.JurixChatSessions = Object.freeze({ refresh: enhanceSessions });

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init, { once: true });
    } else {
        init();
    }
})();
