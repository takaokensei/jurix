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

    function copyWithDocumentCommand(markdownText) {
        if (typeof document.execCommand !== 'function') return false;
        const previousFocus = document.activeElement;
        const field = document.createElement('textarea');
        field.className = 'jurix-clipboard-fallback';
        field.value = markdownText;
        field.setAttribute('readonly', '');
        field.setAttribute('aria-hidden', 'true');
        field.tabIndex = -1;
        document.body.appendChild(field);
        field.focus();
        field.select();
        let copied = false;
        try {
            copied = document.execCommand('copy') === true;
        } catch (_) {
            copied = false;
        }
        field.remove();
        if (previousFocus instanceof HTMLElement && document.contains(previousFocus)) {
            previousFocus.focus({ preventScroll: true });
        }
        return copied;
    }

    async function copyResponseToClipboard(markdownText, button) {
        if (!markdownText || !button) return false;
        let copied = false;
        try {
            if (navigator.clipboard?.writeText) {
                await navigator.clipboard.writeText(markdownText);
                copied = true;
            }
        } catch (_) {
            copied = false;
        }
        if (!copied) copied = copyWithDocumentCommand(markdownText);
        if (!copied) {
            button.setAttribute('aria-label', 'Não foi possível copiar a resposta');
            button.setAttribute('title', 'Não foi possível copiar a resposta');
            window.setTimeout(() => {
                button.setAttribute('aria-label', 'Copiar resposta em Markdown');
                button.setAttribute('title', 'Copiar resposta');
            }, 2200);
            return false;
        }

        {
            const copyIcon = button.querySelector('.copy-icon');
            const checkIcon = button.querySelector('.check-icon');
            if (copyIcon && checkIcon) {
                button.classList.add('copied');
                copyIcon.classList.add('is-hidden');
                checkIcon.classList.remove('is-hidden');
                copyIcon.hidden = true;
                checkIcon.hidden = false;
                window.setTimeout(() => {
                    copyIcon.hidden = false;
                    checkIcon.hidden = true;
                    copyIcon.classList.remove('is-hidden');
                    checkIcon.classList.add('is-hidden');
                    button.classList.remove('copied');
                }, 2000);
            }
            button.setAttribute('aria-label', 'Resposta copiada');
            button.setAttribute('title', 'Resposta copiada');
            window.setTimeout(() => {
                button.setAttribute('aria-label', 'Copiar resposta em Markdown');
                button.setAttribute('title', 'Copiar resposta');
            }, 2000);
            return true;
        }
    }

    // Export public API
    root.escapeHtml = escapeHtml;
    root.addUserMessage = addUserMessage;
    root.addLoadingMessage = addLoadingMessage;
    root.removeLoadingMessage = removeLoadingMessage;
    root.copyResponseToClipboard = copyResponseToClipboard;
})();
