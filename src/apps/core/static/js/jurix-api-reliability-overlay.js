/*
 * Backward-compatible runtime overlay for the existing chat API module.
 * It fixes anonymous-session 401 noise, persists guest history locally,
 * exposes temporary attachments and injects the selected retrieval mode into
 * the existing SSE request without rewriting the mature streaming parser.
 */
(function () {
  'use strict';

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

  function attachmentStore() {
    const key = 'jurix:anonymous-attachments:v1';
    return {
      read() {
        try { return JSON.parse(localStorage.getItem(key) || '[]'); } catch (_) { return []; }
      },
      write(value) { localStorage.setItem(key, JSON.stringify(value.slice(-5))); },
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
    const api = apiObject();
    if (!api || api.__jurixReliabilityOverlay) return;
    api.__jurixReliabilityOverlay = true;
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
      api.getSession = async function (sessionId) {
        if (anonymous()) {
          const session = window.JurixAnonymousHistory.get(sessionId);
          if (!session) throw Object.assign(new Error('Session not found'), { status: 404 });
          return { success: true, session };
        }
        return originalGet(sessionId);
      };
    }

    const originalDelete = api.deleteSession?.bind(api);
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
      api.streamAnswer = async function (question, sessionId, onChunk, onSources, onDone, onError) {
        if (!anonymous()) {
          return originalStream(question, sessionId, onChunk, onSources, onDone, onError);
        }
        const localId = window.JurixAnonymousHistory.ensureSession(sessionId, question);
        window.JurixAnonymousHistory.addMessage(localId, 'user', question, []);
        let answer = '';
        let sources = [];
        const wrappedChunk = (chunk) => {
          answer += String(chunk || '');
          return onChunk?.(chunk);
        };
        const wrappedSources = (items, ...rest) => {
          sources = Array.isArray(items) ? items : [];
          return onSources?.(items, ...rest);
        };
        const wrappedDone = (doneAnswer, ...rest) => {
          if (doneAnswer != null) answer = String(doneAnswer);
          window.JurixAnonymousHistory.updateLastAssistant(localId, answer, sources);
          return onDone?.(doneAnswer, ...rest);
        };
        const wrappedError = (error) => {
          if (answer.trim()) window.JurixAnonymousHistory.updateLastAssistant(localId, answer, sources);
          return onError?.(error);
        };
        // The anonymous DB API intentionally receives no session_id because
        // ChatSession.user is non-null. The local ID remains the UI identity.
        return originalStream(question, null, wrappedChunk, wrappedSources, wrappedDone, wrappedError);
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
        attachmentStore().write(values);
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

    api.listLocalAttachments = function () {
      return attachmentStore().read();
    };
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', install, { once: true });
  else install();
  setTimeout(install, 0);
})();
