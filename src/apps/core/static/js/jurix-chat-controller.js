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
        finalizing: 'Finalizando resposta…',
        regenerating: 'Regenerando resposta…',
        cancelled: 'Geração interrompida neste navegador; o servidor pode ainda estar encerrando a tarefa.',
        failed: 'A pesquisa não foi concluída. Você pode tentar novamente.',
        completed: '',
        error: 'A última pesquisa encontrou um erro.',
    });
    const PIPELINE_COPY = Object.freeze({
        queued: 'Preparando consulta…',
        retrieving: 'Buscando normas relevantes…',
        reranking: 'Refinando as evidências…',
        grounding: 'Conferindo as referências…',
        generating: 'Gerando resposta…',
        finalizing: 'Concluindo a pesquisa…',
        insufficient_evidence: 'Conferindo o que o acervo permite afirmar…',
        failed: 'A pesquisa não foi concluída. Você pode tentar novamente.',
    });
    let waitStartedAt = 0;
    let waitTimeout = null;
    let waitInterval = null;

    function getElement(id) {
        return document.getElementById(id);
    }

    function renderIndicator(indicator, label) {
        if (!indicator) return;
        let labelElement = indicator.querySelector('.jurix-chat-state-label');
        let elapsedElement = indicator.querySelector('.jurix-chat-state-elapsed');
        if (!labelElement) {
            labelElement = document.createElement('span');
            labelElement.className = 'jurix-chat-state-label';
        }
        if (!elapsedElement) {
            elapsedElement = document.createElement('span');
            elapsedElement.className = 'jurix-chat-state-elapsed';
            elapsedElement.setAttribute('aria-hidden', 'true');
        }
        labelElement.textContent = label || '';
        indicator.replaceChildren(labelElement, elapsedElement);
    }

    function clearWaitClock() {
        if (waitTimeout !== null) window.clearTimeout(waitTimeout);
        if (waitInterval !== null) window.clearInterval(waitInterval);
        waitTimeout = null;
        waitInterval = null;
        waitStartedAt = 0;
        const elapsed = getElement('chat-state-indicator')?.querySelector('.jurix-chat-state-elapsed');
        if (elapsed) elapsed.textContent = '';
    }

    function updateElapsed() {
        const elapsed = getElement('chat-state-indicator')?.querySelector('.jurix-chat-state-elapsed');
        if (!elapsed || !waitStartedAt) return;
        const seconds = Math.floor((Date.now() - waitStartedAt) / 1000);
        if (seconds >= 10) elapsed.textContent = `· ${seconds} s`;
    }

    function startWaitClock() {
        if (waitStartedAt) return;
        waitStartedAt = Date.now();
        waitTimeout = window.setTimeout(() => {
            updateElapsed();
            waitInterval = window.setInterval(updateElapsed, 1000);
        }, 10000);
    }

    function setPipelineStatus(status) {
        const indicator = getElement('chat-state-indicator');
        if (!indicator) return false;
        const key = String(status || '');
        if (['completed', 'failed', 'cancelled'].includes(key)) {
            clearWaitClock();
            if (key !== 'completed') renderIndicator(indicator, PIPELINE_COPY[key] || STATUS_COPY[key]);
            delete indicator.dataset.pipelineStatus;
            return true;
        }
        if (!PIPELINE_COPY[key]) return false;
        indicator.dataset.pipelineStatus = key;
        indicator.dataset.state = key === 'generating' ? 'streaming' : key;
        indicator.removeAttribute('hidden');
        renderIndicator(indicator, PIPELINE_COPY[key]);
        startWaitClock();
        return true;
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
        // A terminal SSE event has already won once the backend enters
        // finalizing; keep the stop control available only while generation can
        // still be cancelled, so the UI cannot label a completed answer as aborted.
        const canCancel = snapshot.status === state.STATES.STREAMING;
        const disabled = canCancel ? false : (snapshot.busy || !hasQuestion);

        if (form) {
            form.dataset.chatState = snapshot.status;
            form.setAttribute('aria-busy', snapshot.busy ? 'true' : 'false');
        }

        if (textarea) {
            textarea.setAttribute('aria-busy', snapshot.busy ? 'true' : 'false');
        }

        if (sendButton) {
            sendButton.disabled = disabled;
            sendButton.classList.toggle('is-busy', canCancel);
            sendButton.classList.toggle('is-stop-action', canCancel);
            sendButton.setAttribute(
                'aria-label',
                canCancel ? 'Parar geração' : snapshot.busy ? 'Pesquisa em andamento' : 'Enviar pergunta'
            );
            sendButton.title = canCancel ? 'Parar geração' : snapshot.busy ? 'Pesquisa em andamento' : 'Enviar pergunta';
            sendButton.dataset.action = canCancel ? 'stop' : 'send';
            if (canCancel) {
                sendButton.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true"><rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor"/></svg>';
            } else {
                sendButton.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="5" y1="12" x2="19" y2="12"></line><polyline points="12 5 19 12 12 19"></polyline></svg>';
            }
        }

        if (composer) {
            composer.dataset.chatState = snapshot.status;
            composer.classList.toggle('is-chat-busy', snapshot.busy);
        }

        if (indicator) {
            indicator.dataset.state = snapshot.status;
            if (snapshot.busy) startWaitClock();
            else clearWaitClock();
            const pipelineCopy = snapshot.busy ? PIPELINE_COPY[indicator.dataset.pipelineStatus] : '';
            renderIndicator(indicator, pipelineCopy || STATUS_COPY[snapshot.status] || '');
            indicator.toggleAttribute('hidden', !STATUS_COPY[snapshot.status]);
            if (snapshot.busy && pipelineCopy) indicator.removeAttribute('hidden');
            if (!snapshot.busy) {
                delete indicator.dataset.pipelineStatus;
            }
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
        setPipelineStatus,
    });

    window.JurixChatController = controller;


    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init, { once: true });
    } else {
        init();
    }
})();
