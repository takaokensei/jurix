/**
 * Jurix Command Palette (⌘K / Ctrl+K)
 * Spotlight-style command palette for quick navigation and global actions.
 */

(function () {
    'use strict';

    const overlay = document.getElementById('command-palette-overlay');
    const input = document.getElementById('command-palette-input');
    const resultsContainer = document.getElementById('command-palette-results');
    const triggerBtn = document.getElementById('command-palette-trigger');

    if (!overlay || !input || !resultsContainer) {
        return;
    }

    let chatSessionsForSearch = [];
    let selectedIndex = -1;
    let lastFocusedElement = null;

    const config = window.JURIX_CONFIG || {
        normaListUrl: '/normas/',
        chatbotUrl: '/assistente/',
    };
    const groupOrder = ['Navegar', 'Ações', 'Histórico Recente'];
    const commands = [
        {
            id: 'assistant',
            category: 'Navegar',
            title: 'Assistente',
            description: 'Abrir o assistente jurídico',
            icon: '<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
            action: () => (window.location.href = config.chatbotUrl),
        },
        {
            id: 'search',
            category: 'Navegar',
            title: 'Pesquisa Jurídica',
            description: 'Pesquisar normas e dispositivos por relevância',
            icon: '<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="11" cy="11" r="8" stroke="currentColor" stroke-width="2"/><path d="m21 21-4.35-4.35" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>',
            action: () => (window.location.href = '/pesquisa/'),
        },
        {
            id: 'norms',
            category: 'Navegar',
            title: 'Normas Consolidadas',
            description: 'Abrir catálogo de normas municipais',
            icon: `<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M9 12h6M9 16h6M17 21H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h7.586a1 1 0 0 1 .707.293l3.414 3.414A1 1 0 0 1 19 7.414V19a2 2 0 0 1-2 2z" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
            action: () => (window.location.href = config.normaListUrl),
        },
        {
            id: 'collections',
            category: 'Navegar',
            title: 'Coleções',
            description: 'Abrir dossiês legislativos salvos',
            icon: '<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/></svg>',
            action: () => (window.location.href = '/colecoes/'),
        },
        {
            id: 'history',
            category: 'Navegar',
            title: 'Histórico',
            description: 'Pesquisar conversas e consultas anteriores',
            icon: '<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="2"/><path d="M12 7v5l3 2" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>',
            action: () => (window.location.href = '/historico/'),
        },
        {
            id: 'settings',
            category: 'Navegar',
            title: 'Configurações',
            description: 'Preferências do modelo, tema e densidade',
            icon: '<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Z" stroke="currentColor" stroke-width="2"/><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.88l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06A1.7 1.7 0 0 0 15 19.4a1.7 1.7 0 0 0-1 .6 1.7 1.7 0 0 0-.5 1.2V21a2 2 0 1 1-4 0v-.1A1.7 1.7 0 0 0 8.4 19.4a1.7 1.7 0 0 0-1.88.34l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.7 1.7 0 0 0 4.6 15a1.7 1.7 0 0 0-.6-1 1.7 1.7 0 0 0-1.2-.5H3a2 2 0 1 1 0-4h.1A1.7 1.7 0 0 0 4.6 8.4a1.7 1.7 0 0 0-.34-1.88L4.2 6.46A2 2 0 1 1 7.03 3.63l.06.06A1.7 1.7 0 0 0 9 4.6h.1A1.7 1.7 0 0 0 10 3.2V3a2 2 0 1 1 4 0v.1A1.7 1.7 0 0 0 15 4.6a1.7 1.7 0 0 0 1.88-.34l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.7 1.7 0 0 0 19.4 9c.06.38.25.73.52 1 .27.27.62.46 1 .5H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5.5Z" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
            action: () => (window.location.href = '/configuracoes/'),
        },
        {
            id: 'new-chat',
            category: 'Ações',
            title: 'Nova pesquisa',
            description: 'Começar uma nova conversa no assistente',
            icon: `<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
            action: () => {
                if (window.jurixChat && typeof window.jurixChat.createNewSession === 'function') {
                    window.jurixChat.createNewSession();
                } else {
                    window.location.href = config.chatbotUrl;
                }
                closeCommandPalette();
            },
        },
        {
            id: 'admin',
            category: 'Ações',
            title: 'Painel Admin',
            description: 'Acessar área administrativa',
            icon: `<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="12" cy="12" r="3" stroke="currentColor" stroke-width="2"/><path d="M12 1v6m0 6v6M5.64 5.64l4.24 4.24m4.24 4.24l4.24 4.24M1 12h6m6 0h6M5.64 18.36l4.24-4.24m4.24-4.24l4.24-4.24" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>`,
            action: () => (window.location.href = '/admin/'),
        },
    ];

    async function loadChatSessionsForSearch() {
        try {
            const response = await fetch('/api/v1/chat/sessions/');
            if (response.ok) {
                const data = await response.json();
                if (data.sessions && Array.isArray(data.sessions)) {
                    chatSessionsForSearch = data.sessions.map((session) => ({
                        id: `chat-${session.id}`,
                        category: 'Histórico Recente',
                        title: session.title || 'Conversa sem título',
                        description: `Sessão #${session.id}`,
                        icon: `<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="2"/><path d="M12 7v5l3 2" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>`,
                        action: () => {
                            if (window.jurixChat && typeof window.jurixChat.loadSession === 'function') {
                                window.jurixChat.loadSession(session.id);
                            } else {
                                window.location.href = `${config.chatbotUrl}${session.slug || session.id}/`;
                            }
                            closeCommandPalette();
                        },
                    }));
                }
            }
        } catch (error) {
            console.warn('Command Palette: Could not load chat sessions', error);
        }
    }

    function openCommandPalette() {
        lastFocusedElement = document.activeElement;
        overlay.classList.add('active');
        document.body.style.overflow = 'hidden';
        input.value = '';
        selectedIndex = -1;
        loadChatSessionsForSearch().then(() => {
            updateCommandPaletteResults('');
        });
        setTimeout(() => {
            input.focus();
        }, 50);
    }

    function closeCommandPalette() {
        overlay.classList.remove('active');
        document.body.style.overflow = '';
        setTimeout(() => {
            input.value = '';
            resultsContainer.innerHTML = '';
            selectedIndex = -1;
            if (lastFocusedElement && typeof lastFocusedElement.focus === 'function') {
                lastFocusedElement.focus();
            }
            lastFocusedElement = null;
        }, 250);
    }

    function selectItem(index) {
        const items = resultsContainer.querySelectorAll('.command-palette-item');
        items.forEach((item, idx) => {
            if (idx === index) {
                item.classList.add('selected');
                if (typeof item.scrollIntoView === 'function') {
                    item.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
                }
            } else {
                item.classList.remove('selected');
            }
        });
        selectedIndex = index;
    }

    function updateCommandPaletteResults(query) {
        const allCommands = [...commands, ...chatSessionsForSearch];
        const queryLower = query.toLowerCase().trim();

        const filtered = allCommands.filter(
            (cmd) =>
                (cmd.title || '').toLowerCase().includes(queryLower) ||
                (cmd.description || '').toLowerCase().includes(queryLower)
        );

        if (filtered.length === 0) {
            resultsContainer.innerHTML = `
                <div class="command-palette-empty">
                    Nenhum resultado para "<strong>${escapeHtml(query)}</strong>"
                </div>
            `;
            selectedIndex = -1;
            return;
        }

        const grouped = filtered.reduce((groups, cmd) => {
            const category = cmd.category || 'Ações';
            if (!groups[category]) groups[category] = [];
            groups[category].push(cmd);
            return groups;
        }, {});

        const escapeHtml = (value) => String(value || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');

        resultsContainer.innerHTML = groupOrder
            .filter((category) => grouped[category]?.length)
            .map((category) => `
                <div class="command-palette-category" role="presentation">${category}</div>
                ${grouped[category].map((cmd) => `
                    <div class="command-palette-item" data-command-id="${escapeHtml(cmd.id)}" role="option" tabindex="-1">
                        <span class="command-palette-item-icon">${cmd.icon}</span>
                        <div class="command-palette-item-content">
                            <div class="command-palette-item-title">${escapeHtml(cmd.title)}</div>
                            <div class="command-palette-item-description">${escapeHtml(cmd.description)}</div>
                        </div>
                    </div>
                `).join('')}
            `)
            .join('');

        const items = resultsContainer.querySelectorAll('.command-palette-item');
        items.forEach((item, index) => {
            item.addEventListener('click', () => {
                executeCommand(item.dataset.commandId);
            });
            item.addEventListener('mouseenter', () => {
                selectItem(index);
            });
        });

        if (items.length > 0) {
            selectItem(0);
        } else {
            selectedIndex = -1;
        }
    }

    function executeCommand(commandId) {
        const allCommands = [...commands, ...chatSessionsForSearch];
        const cmd = allCommands.find((c) => c.id === commandId);
        if (!cmd) return;

        if (commandId.startsWith('chat-')) {
            const sessionId = parseInt(commandId.replace('chat-', ''), 10);
            if (sessionId && window.jurixChat && typeof window.jurixChat.loadSession === 'function') {
                closeCommandPalette();
                window.jurixChat.loadSession(sessionId);
                return;
            }
        }

        closeCommandPalette();
        cmd.action();
    }

    // Event listeners
    document.querySelectorAll('#command-palette-trigger, [data-open-command-palette]').forEach((trigger) => {
        trigger.addEventListener('click', openCommandPalette);
    });

    input.addEventListener('input', (e) => {
        updateCommandPaletteResults(e.target.value);
    });

    input.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            closeCommandPalette();
        } else if (e.key === 'Enter') {
            e.preventDefault();
            const selected = resultsContainer.querySelector('.command-palette-item.selected');
            if (selected) {
                executeCommand(selected.dataset.commandId);
            } else {
                const first = resultsContainer.querySelector('.command-palette-item');
                if (first) {
                    executeCommand(first.dataset.commandId);
                }
            }
        } else if (e.key === 'ArrowDown') {
            e.preventDefault();
            const items = resultsContainer.querySelectorAll('.command-palette-item');
            if (items.length > 0) {
                selectedIndex = selectedIndex < items.length - 1 ? selectedIndex + 1 : 0;
                selectItem(selectedIndex);
            }
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            const items = resultsContainer.querySelectorAll('.command-palette-item');
            if (items.length > 0) {
                selectedIndex = selectedIndex > 0 ? selectedIndex - 1 : items.length - 1;
                selectItem(selectedIndex);
            }
        }
    });

    overlay.addEventListener('click', (e) => {
        if (e.target === overlay) {
            closeCommandPalette();
        }
    });

    // Keyboard shortcut: ⌘K or Ctrl+K
    document.addEventListener('keydown', (e) => {
        if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
            e.preventDefault();
            if (overlay.classList.contains('active')) {
                closeCommandPalette();
            } else {
                openCommandPalette();
            }
        }
    });

    window.jurixCommandPalette = {
        open: openCommandPalette,
        close: closeCommandPalette,
        loadSessions: loadChatSessionsForSearch,
    };
})();
