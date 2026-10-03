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

    function updateSession(sessionId, updates) {
        if (!sessionId) return Promise.reject(new Error('sessionId is required'));
        return requestJson(`/api/v1/chat/sessions/${encodeURIComponent(sessionId)}/`, {
            method: 'PATCH',
            body: JSON.stringify(updates || {}),
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

    let activeStream = null;
    const retryTurnIds = new Map();
    let fallbackClientSessionId = '';

    function createUuid() {
        if (window.crypto?.randomUUID) return window.crypto.randomUUID();
        if (window.crypto?.getRandomValues) {
            const bytes = new Uint8Array(16);
            window.crypto.getRandomValues(bytes);
            bytes[6] = (bytes[6] & 0x0f) | 0x40;
            bytes[8] = (bytes[8] & 0x3f) | 0x80;
            const hex = [...bytes].map(value => value.toString(16).padStart(2, '0')).join('');
            return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
        }
        return `${Date.now().toString(16)}-${Math.random().toString(16).slice(2)}-${Math.random().toString(16).slice(2)}`;
    }

    function getClientSessionId() {
        const key = 'jurix:client-session-id:v1';
        try {
            let value = sessionStorage.getItem(key);
            if (!value) {
                value = createUuid();
                sessionStorage.setItem(key, value);
            }
            return value;
        } catch (_) {
            if (!fallbackClientSessionId) fallbackClientSessionId = createUuid();
            return fallbackClientSessionId;
        }
    }

    async function streamAnswer(
        question,
        sessionId,
        {
            onChunk, onSources, onDone, onError, onSession, onStatus, onTitle,
            retryExistingQuestion = false, searchOptions = {},
        } = {}
    ) {
        if (!question || !String(question).trim()) {
            throw new Error('question is required');
        }

        if (activeStream) cancelStream();

        const controller = new AbortController();
        const streamState = {
            controller,
            cancelToken: null,
            cancelRequested: false,
            cancelConfirmed: false,
        };
        activeStream = streamState;
        let reader;
        let completed = false;
        const clientSessionId = searchOptions.client_session_id || getClientSessionId();
        const retryKey = `${sessionId || clientSessionId}\\u0000${String(question).trim()}`;
        const previousTurnId = retryTurnIds.get(retryKey) || null;
        const retryOfTurnId = searchOptions.retry_of_client_turn_id ||
            (retryExistingQuestion ? previousTurnId : null);
        const clientTurnId = searchOptions.client_turn_id || createUuid();
        retryTurnIds.set(retryKey, clientTurnId);

        try {
            let response;
            try {
                let preferences = {};
                try {
                    const stored = JSON.parse(localStorage.getItem('jurix-preferences') || '{}');
                    if (stored && typeof stored === 'object' && !Array.isArray(stored)) preferences = stored;
                } catch (_) {}
                let providerConfig = { provider: 'ollama' };
                try {
                    const configuredProvider = JSON.parse(sessionStorage.getItem('jurix-llm-session-config') || '{}');
                    if (configuredProvider && typeof configuredProvider === 'object' && !Array.isArray(configuredProvider)) providerConfig = configuredProvider;
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
                        ...(searchOptions.previous_question ? { previous_question: searchOptions.previous_question } : {}),
                        ...searchOptions,
                        client_session_id: clientSessionId,
                        client_turn_id: clientTurnId,
                        ...(retryOfTurnId ? { retry_of_client_turn_id: retryOfTurnId } : {}),
                        llm_provider: providerConfig,
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
                if (eventData.type === 'status') {
                    if (eventData.cancel_token && activeStream === streamState) {
                        streamState.cancelToken = eventData.cancel_token;
                    }
                    if (eventData.status === 'cancelled') streamState.cancelConfirmed = true;
                    if (onStatus) await onStatus(eventData.status, eventData);
                } else if (eventData.type === 'session' && onSession) {
                    await onSession(eventData);
                } else if (eventData.type === 'sources' && onSources) {
                    await onSources(eventData.sources, eventData.confidence, eventData);
                } else if (eventData.type === 'chunk' && onChunk) {
                    await onChunk(eventData.chunk, eventData);
                } else if (eventData.type === 'done') {
                    completed = true;
                    retryTurnIds.delete(retryKey);
                    if (onDone) {
                        try { await onDone(eventData); }
                        catch (error) { console.error('[Jurix] Falha em atualização secundária após resposta concluída.', error); }
                    }
                } else if (eventData.type === 'title' && onTitle) {
                    try { await onTitle(eventData); }
                    catch (error) { console.error('[Jurix] Falha ao atualizar título da conversa.', error); }
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

                for (const part of parts) await handleEvent(part.trim());
            }

            // A valid SSE stream may end immediately after the JSON payload,
            // without a final blank line. Do not lose that terminal event.
            if (buffer.trim()) await handleEvent(buffer.trim());
            if (streamState.cancelConfirmed && !completed) return;
            if (!completed) {
                throw Object.assign(new Error('A resposta foi interrompida antes de terminar.'), { code: 'INCOMPLETE_STREAM' });
            }
        } catch (error) {
            if (completed) {
                console.error('[Jurix] A resposta foi concluída; erro ao finalizar a leitura do stream ignorado.', error);
                return;
            }
            if (error.name !== 'AbortError' && onError) await onError(error);
            throw error;
        } finally {
            try { await reader?.cancel?.(); } catch (_) { /* Preserve the original stream error. */ }
            reader?.releaseLock?.();
            if (activeStream === streamState) {
                activeStream = null;
            }
        }
    }

    function cancelStream() {
        const streamState = activeStream;
        if (!streamState) return false;
        streamState.cancelRequested = true;
        activeStream = null;

        if (!streamState.cancelToken) {
            streamState.controller.abort();
            return true;
        }

        // Set the server-side cancellation marker before disconnecting the SSE
        // reader, so generator cleanup can close the provider response safely.
        fetch('/api/v1/search/cancel/', {
            method: 'POST',
            credentials: 'same-origin',
            headers: buildHeaders({}, true),
            body: JSON.stringify({ cancel_token: streamState.cancelToken }),
        }).then(async (response) => {
            let result = {};
            try { result = await response.json(); } catch (_) {}
            if (!response.ok || result.success !== true) {
                streamState.controller.abort();
                return;
            }
            if (result.cancelled === true || result.state === 'finished') {
                streamState.cancelConfirmed = result.cancelled === true;
                streamState.controller.abort();
            }
            // `finalizing`/`completed` means the server won the race; keep
            // reading so the completed answer is not discarded locally.
        }).catch(() => {
            // Preserve the existing local stop behavior if the control request
            // itself cannot be delivered. The UI must not claim server cleanup.
            streamState.controller.abort();
        });
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
        updateSession,
        regenerateSession,
        streamAnswer,
        cancelStream,
        answerBatch,
    });
})();
