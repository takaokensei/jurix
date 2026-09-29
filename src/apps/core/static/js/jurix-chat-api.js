/**
 * Jurix Chat API
 *
 * Transport-only layer for chat/session requests.
 * UI state, DOM rendering and navigation remain outside this module.
 */
(function () {
    'use strict';

    function getCookie(name) {
        let cookieValue = null;
        if (!document.cookie) return null;

        const cookies = document.cookie.split(';');
        for (const rawCookie of cookies) {
            const cookie = rawCookie.trim();
            if (cookie.substring(0, name.length + 1) !== `${name}=`) continue;
            cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
            break;
        }
        return cookieValue;
    }

    function buildHeaders(headers = {}, includeJson = false) {
        const merged = new Headers(headers);
        if (includeJson && !merged.has('Content-Type')) {
            merged.set('Content-Type', 'application/json');
        }

        const csrfToken = getCookie('csrftoken');
        if (csrfToken && !merged.has('X-CSRFToken')) {
            merged.set('X-CSRFToken', csrfToken);
        }
        return merged;
    }

    function createHttpError(response, fallbackMessage) {
        const error = new Error(
            `${fallbackMessage || 'Request failed'} (HTTP ${response.status})`
        );
        error.status = response.status;
        error.response = response;
        return error;
    }

    async function requestJson(url, options = {}) {
        let response;
        try {
            response = await fetch(url, {
                credentials: 'same-origin',
                ...options,
                headers: buildHeaders(options.headers, Boolean(options.body)),
            });
        } catch (error) {
            error.code = 'NETWORK_ERROR';
            throw error;
        }

        if (!response.ok) {
            throw createHttpError(response);
        }

        if (response.status === 204) {
            return null;
        }

        return response.json();
    }

    function listSessions() {
        return requestJson('/api/v1/chat/sessions/');
    }

    function getSession(sessionId, cursor = null) {
        if (!sessionId) return Promise.reject(new Error('sessionId is required'));
        const query = cursor ? `?before=${encodeURIComponent(cursor)}` : '';
        return requestJson(`/api/v1/chat/sessions/${encodeURIComponent(sessionId)}/${query}`);
    }

    function getSessionBySlug(slug) {
        if (!slug) return Promise.reject(new Error('slug is required'));
        return requestJson(
            `/api/v1/chat/sessions/slug/${encodeURIComponent(slug)}/`
        );
    }

    async function deleteSession(sessionId) {
        if (!sessionId) throw new Error('sessionId is required');
        await requestJson(`/api/v1/chat/sessions/${encodeURIComponent(sessionId)}/`, {
            method: 'DELETE',
            headers: buildHeaders({}, false),
        });
    }

    function regenerateSession(sessionId) {
        if (!sessionId) return Promise.reject(new Error('sessionId is required'));
        return requestJson(
            `/api/v1/chat/sessions/${encodeURIComponent(sessionId)}/regenerate/`,
            {
                method: 'POST',
                body: JSON.stringify({}),
            }
        );
    }

    let activeStreamController = null;

    async function streamAnswer(
        question,
        sessionId,
        { onChunk, onSources, onDone, onError, onSession, onStatus, searchOptions = {} } = {}
    ) {
        if (!question || !String(question).trim()) {
            throw new Error('question is required');
        }

        if (activeStreamController) {
            activeStreamController.abort();
        }

        const controller = new AbortController();
        activeStreamController = controller;
        let reader;

        try {
            let response;
            try {
                let preferences = {};
                try {
                    const stored = JSON.parse(localStorage.getItem('jurix-preferences') || '{}');
                    if (stored && typeof stored === 'object' && !Array.isArray(stored)) preferences = stored;
                } catch (_) {}
                const preferredTemperature = Number(preferences.temperature);
                const preferredSources = Number(preferences.sources);
                response = await fetch('/api/v1/search/answer/stream/', {
                    method: 'POST',
                    credentials: 'same-origin',
                    signal: controller.signal,
                    headers: buildHeaders({}, true),
                    body: JSON.stringify({
                        question,
                        session_id: sessionId,
                        ...searchOptions,
                        ...(preferences.model ? { model: preferences.model } : {}),
                        max_sources: Number.isFinite(preferredSources)
                            ? Math.max(1, Math.min(10, preferredSources))
                            : (searchOptions.max_sources || 5),
                        temperature: Number.isFinite(preferredTemperature)
                            ? Math.max(0, Math.min(1, preferredTemperature))
                            : (searchOptions.temperature ?? 0.3),
                    }),
                });
            } catch (error) {
                if (error.name === 'AbortError') throw error;
                error.code = 'NETWORK_ERROR';
                throw error;
            }

            if (!response.ok || !response.body) {
                throw createHttpError(
                    response,
                    response.body ? 'Streaming request failed' : 'Streaming response unavailable'
                );
            }

            reader = response.body.getReader();
            const decoder = new TextDecoder('utf-8');
            let buffer = '';
            let completed = false;

            const handleEvent = async (rawEvent) => {
                const dataLines = String(rawEvent || '')
                    .split(/\r?\n/)
                    .filter((line) => line.startsWith('data:'))
                    .map((line) => line.slice(5).replace(/^ /, ''));
                if (!dataLines.length) return;

                // SSE joins multiple data fields with a newline. The backend
                // currently emits one JSON line, but this keeps the client
                // correct when a proxy folds or fragments an event.
                const payload = dataLines.join('\n');
                const eventData = JSON.parse(payload);
                if (eventData.type === 'status' && onStatus) {
                    await onStatus(eventData.status);
                } else if (eventData.type === 'session' && onSession) {
                    await onSession(eventData);
                } else if (eventData.type === 'sources' && onSources) {
                    await onSources(eventData.sources, eventData.confidence);
                } else if (eventData.type === 'chunk' && onChunk) {
                    await onChunk(eventData.chunk);
                } else if (eventData.type === 'done') {
                    completed = true;
                    if (onDone) await onDone(eventData);
                } else if (eventData.type === 'error') {
                    const error = new Error(eventData.error || 'RAG stream error');
                    error.code = 'RAG_STREAM_ERROR';
                    throw error;
                }
            };

            while (true) {
                const { done, value } = await reader.read();
                if (done) {
                    buffer += decoder.decode();
                    break;
                }

                buffer += decoder.decode(value, { stream: true });
                const parts = buffer.split(/\r?\n\r?\n/);
                buffer = parts.pop() || '';

                for (const part of parts) {
                    await handleEvent(part.trim());
                    if (completed) return;
                }
            }

            // A valid SSE stream may end immediately after the JSON payload,
            // without a final blank line. Do not lose that terminal event.
            if (!completed && buffer.trim()) {
                await handleEvent(buffer.trim());
            }
            if (!completed) {
                throw Object.assign(new Error('A resposta foi interrompida antes de terminar.'), { code: 'INCOMPLETE_STREAM' });
            }
        } catch (error) {
            if (onError) await onError(error);
            throw error;
        } finally {
            try { await reader?.cancel?.(); } catch (_) { /* Preserve the original stream error. */ }
            reader?.releaseLock?.();
            if (activeStreamController === controller) {
                activeStreamController = null;
            }
        }
    }

    function cancelStream() {
        if (!activeStreamController) return false;
        activeStreamController.abort();
        activeStreamController = null;
        return true;
    }

    function answerBatch(question, sessionId, url = '/assistente/') {
        return requestJson(url, {
            method: 'POST',
            body: JSON.stringify({
                question,
                session_id: sessionId,
                regenerate: false,
            }),
        });
    }

    window.JurixChatAPI = Object.freeze({
        listSessions,
        getSession,
        getSessionBySlug,
        deleteSession,
        regenerateSession,
        streamAnswer,
        cancelStream,
        answerBatch,
    });
})();
