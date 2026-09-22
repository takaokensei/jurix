/**
 * Jurix Chat State
 *
 * Small finite-state store for the assistant UI. It deliberately owns
 * interaction state, not DOM rendering or transport.
 */
(function () {
    'use strict';

    const STATES = Object.freeze({
        IDLE: 'idle',
        SUBMITTING: 'submitting',
        STREAMING: 'streaming',
        REGENERATING: 'regenerating',
        ERROR: 'error',
    });

    const BUSY_STATES = new Set([
        STATES.SUBMITTING,
        STATES.STREAMING,
        STATES.REGENERATING,
    ]);

    let status = STATES.IDLE;
    let sessionId = null;
    let lastQuestion = '';
    let lastError = null;
    let greetingStreaming = false;

    const subscribers = new Set();

    function snapshot() {
        return Object.freeze({
            status,
            sessionId,
            lastQuestion,
            lastError,
            greetingStreaming,
            busy: BUSY_STATES.has(status),
        });
    }

    function syncDom() {
        const root = document.documentElement;
        if (root) {
            root.dataset.jurixChatState = status;
        }

        const form = document.getElementById('chat-form');
        if (form) {
            form.setAttribute('aria-busy', BUSY_STATES.has(status) ? 'true' : 'false');
        }
    }

    function emit() {
        const state = snapshot();
        syncDom();

        subscribers.forEach((listener) => {
            try {
                listener(state);
            } catch (error) {
                console.error('JurixChatState subscriber error:', error);
            }
        });

        document.dispatchEvent(
            new CustomEvent('jurix:chat-state', {
                detail: state,
            })
        );
    }

    function transition(nextStatus, meta = {}) {
        if (!Object.values(STATES).includes(nextStatus)) {
            throw new Error(`Invalid Jurix chat state: ${nextStatus}`);
        }

        status = nextStatus;

        if (Object.prototype.hasOwnProperty.call(meta, 'sessionId')) {
            sessionId = meta.sessionId;
        }
        if (Object.prototype.hasOwnProperty.call(meta, 'question')) {
            lastQuestion = String(meta.question || '');
        }
        if (Object.prototype.hasOwnProperty.call(meta, 'error')) {
            lastError = meta.error || null;
        } else if (nextStatus !== STATES.ERROR) {
            lastError = null;
        }

        emit();
        return snapshot();
    }

    function setSessionId(value) {
        sessionId = value === null || value === undefined ? null : Number(value);
        if (Number.isNaN(sessionId)) sessionId = null;
        emit();
    }

    function setLastQuestion(question) {
        lastQuestion = String(question || '');
        emit();
    }

    function beginGreeting() {
        if (greetingStreaming) return;
        greetingStreaming = true;
        emit();
    }

    function endGreeting() {
        if (!greetingStreaming) return;
        greetingStreaming = false;
        emit();
    }

    function isBusy() {
        return BUSY_STATES.has(status);
    }

    function subscribe(listener) {
        if (typeof listener !== 'function') {
            throw new TypeError('listener must be a function');
        }
        subscribers.add(listener);
        listener(snapshot());
        return () => subscribers.delete(listener);
    }

    function reset() {
        return transition(STATES.IDLE);
    }

    const api = Object.freeze({
        STATES,
        snapshot,
        transition,
        setSessionId,
        setLastQuestion,
        beginGreeting,
        endGreeting,
        isGreetingStreaming: () => greetingStreaming,
        isBusy,
        subscribe,
        reset,
    });

    window.JurixChatState = api;

    if (document.readyState !== 'loading') {
        syncDom();
    } else {
        document.addEventListener('DOMContentLoaded', syncDom, { once: true });
    }
})();
