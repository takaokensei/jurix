/**
 * Jurix Chat Controller
 *
 * Presentation/orchestration layer between the chat state store and the DOM.
 * It does not own transport or message rendering.
 */
(function () {
    'use strict';

    const state = window.JurixChatState;
    if (!state) {
        console.warn('JurixChatController: JurixChatState is unavailable.');
        return;
    }

    const STATUS_COPY = Object.freeze({
        idle: '',
        submitting: 'Preparando pesquisa…',
        streaming: 'Gerando resposta…',
        regenerating: 'Regenerando resposta…',
        error: 'A última pesquisa encontrou um erro.',
    });

    function getElement(id) {
        return document.getElementById(id);
    }

    function focusComposer() {
        const textarea = getElement('question-textarea');
        if (!textarea) return false;
        textarea.focus();
        textarea.selectionStart = textarea.value.length;
        textarea.selectionEnd = textarea.value.length;
        return true;
    }

    function focusHeroSearch() {
        const input = getElement('hero-search-input');
        if (!input) return false;
        input.focus();
        return true;
    }

    function syncStateUI(snapshot) {
        const form = getElement('chat-form');
        const textarea = getElement('question-textarea');
        const sendButton = getElement('send-button');
        const indicator = getElement('chat-state-indicator');
        const composer = getElement('conversation-input-bar');

        const hasQuestion = Boolean(textarea && textarea.value.trim());
        const disabled = snapshot.busy || !hasQuestion;

        if (form) {
            form.dataset.chatState = snapshot.status;
            form.setAttribute('aria-busy', snapshot.busy ? 'true' : 'false');
        }

        if (textarea) {
            textarea.setAttribute('aria-busy', snapshot.busy ? 'true' : 'false');
        }

        if (sendButton) {
            sendButton.disabled = disabled;
            sendButton.classList.toggle('is-busy', snapshot.busy);
            sendButton.setAttribute(
                'aria-label',
                snapshot.busy ? 'Gerando resposta' : 'Enviar pergunta'
            );
        }

        if (composer) {
            composer.dataset.chatState = snapshot.status;
            composer.classList.toggle('is-chat-busy', snapshot.busy);
        }

        if (indicator) {
            indicator.dataset.state = snapshot.status;
            indicator.textContent = STATUS_COPY[snapshot.status] || '';
            indicator.toggleAttribute('hidden', !STATUS_COPY[snapshot.status]);
        }
    }

    function dispatchFocusEvent(target) {
        document.dispatchEvent(new CustomEvent(`jurix:focus-${target}`));
    }

    function submitQuestion(question) {
        const value = String(question || '').trim();
        if (!value || state.isBusy()) return false;
        if (window.jurixChat && typeof window.jurixChat.askQuestion === 'function') {
            window.jurixChat.askQuestion(value);
            return true;
        }
        return false;
    }

    function newConversation() {
        if (window.jurixChat && typeof window.jurixChat.createNewSession === 'function') {
            window.jurixChat.createNewSession();
            return true;
        }
        return false;
    }

    function openSession(sessionId) {
        if (!sessionId) return false;
        if (window.jurixChat && typeof window.jurixChat.loadSession === 'function') {
            window.jurixChat.loadSession(sessionId);
            return true;
        }
        return false;
    }

    function bindDomEvents() {
        document.addEventListener('jurix:focus-composer', focusComposer);
        document.addEventListener('jurix:focus-hero', focusHeroSearch);

        const textarea = getElement('question-textarea');
        if (textarea) {
            textarea.addEventListener('input', () => syncStateUI(state.snapshot()));
        }

        const commandTrigger = getElement('command-palette-trigger');
        if (commandTrigger) {
            commandTrigger.addEventListener('click', () => {
                window.requestAnimationFrame(() => {
                    const input = getElement('command-palette-input');
                    if (input) input.focus();
                });
            });
        }
    }

    function init() {
        state.subscribe(syncStateUI);
        bindDomEvents();
        syncStateUI(state.snapshot());
    }

    const controller = Object.freeze({
        focusComposer,
        focusHeroSearch,
        submitQuestion,
        newConversation,
        openSession,
        dispatchFocusEvent,
    });

    window.JurixChatController = controller;


    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init, { once: true });
    } else {
        init();
    }
})();
