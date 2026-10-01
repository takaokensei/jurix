(function () {
    'use strict';
    async function sessions() {
        const store = window.JurixAnonymousHistory;
        if (store?.isAnonymous()) return store.list();
        const response = await fetch('/api/v1/chat/sessions/');
        if (!response.ok) throw new Error('Histórico indisponível');
        const data = await response.json();
        return Array.isArray(data.sessions) ? data.sessions : [];
    }
    function sessionUrl(session) {
        return `${document.body.dataset.chatbotUrl || '/assistente/'}${encodeURIComponent(session.slug || session.id)}/`;
    }
    function render(entries, { activeSessionId = null, preserveTemporary = false } = {}) {
        const list = document.getElementById('chat-sessions-list');
        if (!list) return false;
        const temporary = preserveTemporary
            ? [...list.querySelectorAll('.chat-session-item[data-session-id^="temp-"]')]
            : [];
        const sorted = [...(Array.isArray(entries) ? entries : [])].sort((a, b) => {
            const dateA = Date.parse(a.updated_at || a.created_at || '') || 0;
            const dateB = Date.parse(b.updated_at || b.created_at || '') || 0;
            return dateB - dateA || String(b.id).localeCompare(String(a.id), undefined, { numeric: true });
        });
        list.replaceChildren();
        temporary.forEach(item => list.append(item));
        sorted.slice(0, 24).forEach(session => {
            const item = document.createElement('div');
            const isActive = activeSessionId != null && String(session.id) === String(activeSessionId);
            item.className = `chat-session-item${isActive ? ' active' : ''}`;
            item.dataset.sessionId = String(session.id);
            const link = document.createElement('a');
            link.className = 'jurix-recent-chat chat-session-main';
            link.href = sessionUrl(session);
            link.textContent = session.title || 'Conversa sem título';
            link.title = link.textContent;
            if (isActive) link.setAttribute('aria-current', 'page');
            item.append(link);
            list.append(item);
        });
        if (!sorted.length && !temporary.length) list.textContent = 'Nenhuma conversa ainda';
        return true;
    }
    async function refresh() {
        const list = document.getElementById('chat-sessions-list');
        if (!list) return;
        try {
            const entries = await sessions();
            const active = document.querySelector('.chat-session-item.active')?.dataset.sessionId || null;
            render(entries, { activeSessionId: active });
        } catch (_) {
            list.textContent = 'Histórico indisponível. Tente novamente ao abrir a busca.';
        }
    }
    window.JurixSidebar = Object.freeze({ sessions, sessionUrl, render, refresh });
    document.querySelectorAll('[data-search-conversations]').forEach(button => {
        button.addEventListener('click', () => window.jurixCommandPalette?.open({ conversationsOnly: true }));
    });
    document.getElementById('new-chat-button')?.addEventListener('click', event => event.preventDefault());
    window.addEventListener('storage', refresh);
    window.addEventListener('jurix:sessions-changed', refresh);
    if (!document.querySelector('.figma-workspace')) refresh();
})();
