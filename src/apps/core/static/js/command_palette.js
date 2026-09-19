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

    const config = window.JURIX_CONFIG || {
        normaListUrl: '/normas/',
        chatbotUrl: '/normas/chatbot/',
    };

    const commands = [
        {
            id: 'norms',
            title: 'Ver Normas Consolidadas',
            description: 'Abrir catálogo de normas municipais',
            icon: `<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M9 12h6M9 16h6M17 21H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h7.586a1 1 0 0 1 .707.293l3.414 3.414A1 1 0 0 1 19 7.414V19a2 2 0 0 1-2 2z" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
            action: () => (window.location.href = config.normaListUrl),
        },
        {
            id: 'admin',
            title: 'Painel Admin',
            description: 'Acessar área administrativa',
            icon: `<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="12" cy="12" r="3" stroke="currentColor" stroke-width="2"/><path d="M12 1v6m0 6v6M5.64 5.64l4.24 4.24m4.24 4.24l4.24 4.24M1 12h6m6 0h6M5.64 18.36l4.24-4.24m4.24-4.24l4.24-4.24" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>`,
            action: () => (window.location.href = '/admin/'),
        },
        {
            id: 'new-chat',
            title: 'Nova Conversa',
            description: 'Limpar conversa atual e começar nova',
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
    ];

    async function loadChatSessionsForSearch() {
        try {
            const response = await fetch('/api/v1/chat/sessions/');
            if (response.ok) {
                const data = await response.json();
                if (data.success && data.sessions) {
                    chatSessionsForSearch = data.sessions.map((session) => ({
                        id: `chat-${session.id}`,
                        title: session.title || 'Conversa sem título',
                        description: session.latest_message_preview || 'Sem mensagens',
                        sessionId: session.id,
                        icon: `<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
                        action: () => {
                            if (window.jurixChat && typeof window.jurixChat.loadSession === 'function') {
                                window.jurixChat.loadSession(session.id);
                            }
                            closeCommandPalette();
                        },
                    }));
                }
            }
        } catch (error) {
            console.error('Error loading chat sessions for search:', error);
        }
    }

    function openCommandPalette() {
        selectedIndex = -1;
        overlay.classList.remove('closing');
        overlay.classList.add('active');
        input.focus();
        loadChatSessionsForSearch().then(() => {
            updateCommandPaletteResults('');
        });
    }

    function closeCommandPalette() {
        overlay.classList.add('closing');
        setTimeout(() => {
            overlay.classList.remove('active', 'closing');
            input.value = '';
            resultsContainer.innerHTML = '';
            selectedIndex = -1;
        }, 250);
    }

    function selectItem(index) {
        const items = resultsContainer.querySelectorAll('.command-palette-item');
        items.forEach((item, i) => {
            if (i === index) {
                item.classList.add('selected');
                item.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
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
                cmd.title.toLowerCase().includes(queryLower) ||
                cmd.description.toLowerCase().includes(queryLower)
        );

        selectedIndex = -1;

        if (filtered.length === 0) {
            resultsContainer.innerHTML =
                '<div class="command-palette-empty">Nenhum comando encontrado</div>';
            return;
        }

        resultsContainer.innerHTML = filtered
            .map(
                (cmd) => `
            <div class="command-palette-item" 
                 data-command-id="${cmd.id}">
                <span class="command-palette-item-icon">${cmd.icon}</span>
                <div class="command-palette-item-content">
                    <div class="command-palette-item-title">${cmd.title}</div>
                    <div class="command-palette-item-description">${cmd.description}</div>
                </div>
            </div>
        `
            )
            .join('');

        resultsContainer.querySelectorAll('.command-palette-item').forEach((item) => {
            item.addEventListener('click', () => {
                executeCommand(item.dataset.commandId);
            });
        });
    }

    function executeCommand(commandId) {
        if (!commandId) return;

        if (commandId.startsWith('chat-')) {
            const sessionId = parseInt(commandId.replace('chat-', ''), 10);
            if (sessionId && window.jurixChat && typeof window.jurixChat.loadSession === 'function') {
                closeCommandPalette();
                window.jurixChat.loadSession(sessionId);
                return;
            }
        }

        const cmd = commands.find((c) => c.id === commandId);
        if (cmd) {
            closeCommandPalette();
            cmd.action();
        }
    }

    // Event listeners
    if (triggerBtn) {
        triggerBtn.addEventListener('click', openCommandPalette);
    }

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
                const query = input.value.toLowerCase().trim();
                if (query.includes('norma')) {
                    executeCommand('norms');
                    return;
                }
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
