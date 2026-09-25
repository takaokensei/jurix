/*
 * Backward-compatible runtime overlay for the existing chat API module.
 * It fixes anonymous-session 401 noise, persists guest history locally,
 * exposes temporary attachments and injects the selected retrieval mode into
 * the existing SSE request without rewriting the mature streaming parser.
 */
(function () {
  'use strict';

  const installedApis = new WeakSet();

  function apiObject() {
    return window.JurixChatAPI || window.jurixChatAPI || window.chatAPI || null;
  }

  function anonymous() {
    return window.JurixAnonymousHistory?.isAnonymous?.() === true;
  }

  function authToken() {
    const value = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
    return value ? decodeURIComponent(value[1]) : '';
  }

  function options() {
    return window.JurixSearchControls?.getPayload?.() || {};
  }

  let attachmentMemoryBackup = [];

  function attachmentStore() {
    const key = 'jurix:anonymous-attachments:v1';
    return {
      read() {
        try {
          const raw = localStorage.getItem(key);
          if (raw) {
            const parsed = JSON.parse(raw);
            if (Array.isArray(parsed)) return parsed;
          }
        } catch (_) {}
        return Array.isArray(attachmentMemoryBackup) ? attachmentMemoryBackup.slice() : [];
      },
      write(value) {
        const sliced = Array.isArray(value) ? value.slice(-5) : [];
        attachmentMemoryBackup = sliced.slice();
        try {
          localStorage.setItem(key, JSON.stringify(sliced));
        } catch (error) {
          console.warn('[Jurix] Local attachment metadata store unavailable:', error);
        }
      },
    };
  }

  function installFetchEnvelope() {
    if (window.__jurixFetchOverlayInstalled) return;
    const originalFetch = window.fetch.bind(window);
    window.fetch = async function (input, init) {
      const url = typeof input === 'string' ? input : input?.url || '';
      if (!url.includes('/api/v1/search/answer/stream/')) {
        return originalFetch(input, init);
      }
      const envelope = init ? { ...init } : {};
      if (typeof envelope.body === 'string') {
        try {
          const body = JSON.parse(envelope.body);
          const selected = options();
          const merged = {
            ...body,
            k: Math.min(20, Math.max(12, Number(body.k) || 12)),
            search_mode: selected.mode || body.search_mode || 'hybrid',
            norma_status: selected.norma_status || body.norma_status || 'consolidated',
            source_scope: selected.source_scope || body.source_scope || 'municipal',
            attachment_ids: Array.isArray(selected.attachment_ids) ? selected.attachment_ids : [],
          };
          envelope.body = JSON.stringify(merged);
        } catch (_) {}
      }
      return originalFetch(input, envelope);
    };
    window.__jurixFetchOverlayInstalled = true;
  }

  function install() {
    let api = apiObject();
    if (!api || installedApis.has(api)) return;
    if (Object.isFrozen(api) || !Object.isExtensible(api)) {
      api = { ...api };
      window.JurixChatAPI = api;
    }
    installedApis.add(api);
    installFetchEnvelope();

    const originalList = api.listSessions?.bind(api);
    if (originalList) {
      api.listSessions = async function () {
        if (anonymous()) {
          return { success: true, sessions: window.JurixAnonymousHistory.list() };
        }
        try {
          return await originalList();
        } catch (error) {
          if (error?.status === 401) return { success: true, sessions: [] };
          throw error;
        }
      };
    }

    const originalGet = api.getSession?.bind(api);
    if (originalGet) {
      api.getSession = async function (sessionId, cursor = null) {
        if (anonymous()) {
          const session = window.JurixAnonymousHistory.get(sessionId);
          if (!session) throw Object.assign(new Error('Session not found'), { status: 404 });
          return { success: true, session, messages: session.messages, has_more: false, next_cursor: null };
        }
        return originalGet(sessionId, cursor);
      };
    }

    const originalDelete = api.deleteSession?.bind(api);
    const originalGetBySlug = api.getSessionBySlug?.bind(api);
    api.getSessionBySlug = function (slug, cursor = null) {
      return anonymous() ? api.getSession(slug, cursor) : (originalGetBySlug ? originalGetBySlug(slug, cursor) : undefined);
    };
    if (originalDelete) {
      api.deleteSession = async function (sessionId) {
        if (anonymous()) {
          window.JurixAnonymousHistory.remove(sessionId);
          return { success: true };
        }
        return originalDelete(sessionId);
      };
    }

    const originalStream = api.streamAnswer?.bind(api);
    if (originalStream) {
      api.streamAnswer = async function (question, sessionId, callbacks = {}) {
        const { onChunk, onSources, onDone, onError, onSession } = callbacks || {};
        if (!anonymous()) {
          return originalStream(question, sessionId, callbacks);
        }
        const localId = window.JurixAnonymousHistory.ensureSession(sessionId, question);
        window.JurixAnonymousHistory.addMessage(localId, 'user', question, []);
        await onSession?.({ session_id: localId, session_slug: localId });
        let answer = '';
        let sources = [];
        const wrappedChunk = (chunk) => {
          answer += String(chunk || '');
          window.JurixAnonymousHistory.updateLastAssistant(localId, answer, sources);
          return onChunk?.(chunk);
        };
        const wrappedSources = (items, ...rest) => {
          sources = Array.isArray(items) ? items : [];
          return onSources?.(items, ...rest);
        };
        const wrappedDone = (doneEvent, ...rest) => {
          const answerFromEvent = doneEvent && typeof doneEvent === 'object'
            ? doneEvent.answer
            : doneEvent;
          if (answerFromEvent != null) answer = String(answerFromEvent);
          window.JurixAnonymousHistory.updateLastAssistant(localId, answer, sources);
          return onDone?.({ ...doneEvent, answer, session_id: localId, session_slug: localId }, ...rest);
        };
        const wrappedError = (error) => {
          if (answer.trim()) window.JurixAnonymousHistory.updateLastAssistant(localId, answer, sources);
          return onError?.(error);
        };
        // The anonymous DB API intentionally receives no session_id because
        // ChatSession.user is non-null. The local ID remains the UI identity.
        return originalStream(question, null, {
          onChunk: wrappedChunk,
          onSources: wrappedSources,
          onDone: wrappedDone,
          onError: wrappedError,
        });
      };
    }

    api.uploadAttachment = async function (file) {
      if (anonymous()) {
        const max = 10 * 1024 * 1024;
        if (file.size > max) throw new Error('Arquivo maior que 10 MB.');
        const id = `local-attachment-${Date.now()}-${Math.random().toString(36).slice(2)}`;
        const values = attachmentStore().read();
        const item = { id, name: file.name, size: file.size, content_type: file.type || 'application/octet-stream' };
        // Anonymous attachment contents are uploaded to the server only when
        // the chat endpoint is used; localStorage intentionally stores metadata
        // while the server session retains the actual extracted text.
        const form = new FormData();
        form.append('file', file);
        const response = await fetch('/api/v1/chat/attachments/', {
          method: 'POST',
          credentials: 'same-origin',
          headers: authToken() ? { 'X-CSRFToken': authToken() } : {},
          body: form,
        });
        const payload = await response.json();
        if (!response.ok || !payload.success) throw new Error(payload.error || 'Não foi possível anexar o documento.');
        values.push(payload.attachment);
        try {
          attachmentStore().write(values);
        } catch (_) {}
        return payload.attachment;
      }
      const form = new FormData();
      form.append('file', file);
      const response = await fetch('/api/v1/chat/attachments/', {
        method: 'POST', credentials: 'same-origin',
        headers: authToken() ? { 'X-CSRFToken': authToken() } : {},
        body: form,
      });
      const payload = await response.json();
      if (!response.ok || !payload.success) throw new Error(payload.error || 'Não foi possível anexar o documento.');
      return payload.attachment;
    };

    api.deleteAttachment = async function (attachmentId) {
      const response = await fetch(`/api/v1/chat/attachments/${encodeURIComponent(attachmentId)}/`, {
        method: 'DELETE',
        credentials: 'same-origin',
        headers: authToken() ? { 'X-CSRFToken': authToken() } : {},
      });
      const payload = await response.json();
      if (!response.ok || !payload.success) {
        throw new Error(payload.error || 'Não foi possível desanexar o documento.');
      }
      try {
        const values = attachmentStore().read().filter(item => item.id !== attachmentId);
        attachmentStore().write(values);
      } catch (_) {}
      return payload;
    };

    api.listLocalAttachments = function () {
      return attachmentStore().read();
    };
  }

  // Install synchronously: chat.js captures the API object during evaluation.
  // A deferred replacement would leave it holding the unwrapped frozen object.
  install();
})();
