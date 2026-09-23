// Jurix Chat Renderer
// Provides UI primitives for chat messages, loading indicators, and error handling.
// This file is framework‑free and used by chat.js via window.JurixChatRenderer.

(function () {
    'use strict';

    const root = window.JurixChatRenderer = window.JurixChatRenderer || {};

    function escapeHtml(value) {
        const div = document.createElement('div');
        div.textContent = String(value ?? '');
        return div.innerHTML;
    }

    function renderMarkdown(text, fallback) {
        try {
            if (typeof fallback === 'function') return fallback(text);
            if (window.JurixMarkdown && typeof window.JurixMarkdown.render === 'function') {
                return window.JurixMarkdown.render(text);
            }
            if (typeof marked !== 'undefined' && typeof DOMPurify !== 'undefined') {
                return DOMPurify.sanitize(marked.parse(String(text || '')));
            }
        } catch (_) {
            // fall through
        }
        return escapeHtml(text).replace(/\n/g, '<br>');
    }

    function timestamp() {
        return new Date().toLocaleTimeString('pt-BR', {
            hour: '2-digit',
            minute: '2-digit',
        });
    }

    function nextId(prefix) {
        return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
    }

    function getMessagesWrapper() {
        return document.getElementById('messages-wrapper');
    }

    function addUserMessage(text, deps = {}) {
        const wrapper = getMessagesWrapper();
        if (!wrapper) return null;
        const body = renderMarkdown(text, deps.renderMarkdown);
        const message = document.createElement('div');
        message.className = 'message message-user jurix-message-enter';
        message.innerHTML = `
            <div class="message-content">
                <div class="message-header">
                    <span class="message-role">Você</span>
                    <span class="message-time">${escapeHtml(timestamp())}</span>
                </div>
                <div class="message-body">${body}</div>
            </div>
        `;
        wrapper.appendChild(message);
        requestAnimationFrame(() => message.classList.remove('jurix-message-enter'));
        if (typeof deps.scrollToBottom === 'function') deps.scrollToBottom();
        return message;
    }

    function addLoadingMessage(opts = {}) {
        const wrapper = getMessagesWrapper();
        if (!wrapper) return null;
        const loadingId = nextId('loading');
        const logo = opts.config && opts.config.logoIconUrl ? opts.config.logoIconUrl : '/static/img/logo-icon.png';
        const message = document.createElement('div');
        message.className = 'message message-assistant jurix-message-enter';
        message.id = loadingId;
        message.innerHTML = `
            <div class="message-avatar">
                <img src="${escapeHtml(logo)}" alt="Jurix">
            </div>
            <div class="message-content">
                <div class="loading-message" role="status" aria-live="polite">
                    <div class="loading-dots" aria-hidden="true">
                        <div class="loading-dot"></div>
                        <div class="loading-dot"></div>
                        <div class="loading-dot"></div>
                    </div>
                    <span>Pensando...</span>
                </div>
            </div>
        `;
        wrapper.appendChild(message);
        requestAnimationFrame(() => message.classList.remove('jurix-message-enter'));
        if (typeof opts.scrollToBottom === 'function') opts.scrollToBottom();
        return loadingId;
    }

    function removeLoadingMessage(loadingId) {
        const node = document.getElementById(loadingId);
        if (!node) return;
        node.classList.add('jurix-message-exit');
        window.setTimeout(() => node.remove(), 140);
    }

    function copyResponseToClipboard(markdownText, button) {
        if (!markdownText || !button || !navigator.clipboard) return Promise.resolve(false);
        return navigator.clipboard.writeText(markdownText).then(() => {
            const copyIcon = button.querySelector('.copy-icon');
            const checkIcon = button.querySelector('.check-icon');
            if (copyIcon && checkIcon) {
                button.classList.add('copied');
                copyIcon.hidden = true;
                checkIcon.hidden = false;
                window.setTimeout(() => {
                    copyIcon.hidden = false;
                    checkIcon.hidden = true;
                    button.classList.remove('copied');
                }, 2000);
            }
            button.setAttribute('aria-label', 'Resposta copiada');
            window.setTimeout(() => button.setAttribute('aria-label', 'Copiar resposta em Markdown'), 2000);
            return true;
        }).catch((e) => {
            console.error('Jurix: clipboard failed', e);
            return false;
        });
    }

    // Export public API
    root.escapeHtml = escapeHtml;
    root.addUserMessage = addUserMessage;
    root.addLoadingMessage = addLoadingMessage;
    root.removeLoadingMessage = removeLoadingMessage;
    root.copyResponseToClipboard = copyResponseToClipboard;
})();
