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
    async function refresh() {
        // The assistant owns its live list, including retry/deletion/session state.
        if (document.querySelector('.figma-workspace')) return;
        const list = document.getElementById('chat-sessions-list');
        if (!list) return;
        try {
            const entries = await sessions();
            list.replaceChildren();
            entries.slice(0, 24).forEach(session => {
                const link = document.createElement('a');
                link.className = 'jurix-recent-chat';
                link.href = sessionUrl(session);
                link.textContent = session.title || 'Conversa sem título';
                link.title = link.textContent;
                list.append(link);
            });
            if (!entries.length) list.textContent = 'Nenhuma conversa ainda';
        } catch (_) {
            list.textContent = 'Histórico indisponível. Tente novamente ao abrir a busca.';
        }
    }
    window.JurixSidebar = Object.freeze({ sessions, sessionUrl, refresh });
    document.querySelectorAll('[data-search-conversations]').forEach(button => {
        button.addEventListener('click', () => window.jurixCommandPalette?.open({ conversationsOnly: true }));
    });
    document.getElementById('new-chat-button')?.addEventListener('click', event => event.preventDefault());
    window.addEventListener('storage', refresh);
    refresh();
})();
