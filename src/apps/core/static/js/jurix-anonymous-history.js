/*
 * Local, bounded history for anonymous Jurix sessions.
 *
 * The server deliberately does not create ChatSession rows for anonymous
 * visitors because ChatSession.user is mandatory. The old frontend treated a
 * 401 from /chat/sessions/ as a fatal initialization error, so a refresh lost
 * the visible conversation. This module provides a small local-first history
 * store and is intentionally independent from the Django session.
 */
(function () {
  'use strict';

  const STORAGE_KEY = 'jurix:anonymous-history:v2';
  const SCHEMA_VERSION = 2;
  const MAX_SESSIONS = 24;
  const MAX_MESSAGES = 80;
  const MAX_BYTES = 3 * 1024 * 1024;
  let memoryState = null;
  let storageUnavailable = false;

  function storageFailed(error) {
    storageUnavailable = true;
    console.warn('[Jurix] history is temporarily in memory', error);
    let notice = document.getElementById('jurix-storage-warning');
    if (!notice && document.body) {
      notice = document.createElement('p');
      notice.id = 'jurix-storage-warning';
      notice.setAttribute('role', 'alert');
      notice.textContent = 'O histórico não pôde ser salvo neste navegador. Copie as respostas antes de sair.';
      document.body.prepend(notice);
    }
  }

  function isAnonymous() {
    const bodyValue = document.body?.dataset?.authenticated;
    if (bodyValue) return bodyValue !== 'true';
    const meta = document.querySelector('meta[name="jurix-authenticated"]');
    return meta?.content !== 'true';
  }

  function now() {
    return new Date().toISOString();
  }

  function newId() {
    if (window.crypto?.randomUUID) return `local-${window.crypto.randomUUID()}`;
    return `local-${Date.now()}-${Math.random().toString(36).slice(2)}`;
  }

  function emptyState() {
    return { schema: SCHEMA_VERSION, sessions: [] };
  }

  function read() {
    if (storageUnavailable && memoryState) return JSON.parse(JSON.stringify(memoryState));
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return emptyState();
      const value = JSON.parse(raw);
      if (!value || value.schema !== SCHEMA_VERSION || !Array.isArray(value.sessions)) {
        return emptyState();
      }
      return value;
    } catch (error) {
      storageFailed(error);
      return memoryState || emptyState();
    }
  }

  function prune(state) {
    state.sessions = state.sessions
      .filter(session => session && session.id && Array.isArray(session.messages))
      .sort((a, b) => String(b.updated_at).localeCompare(String(a.updated_at)))
      .slice(0, MAX_SESSIONS);

    state.sessions.forEach(session => {
      session.messages = session.messages.slice(-MAX_MESSAGES).map(message => ({
        role: message.role === 'assistant' ? 'assistant' : 'user',
        content: String(message.content || '').slice(0, 30_000),
        created_at: message.created_at || now(),
        grounded: message.grounded === true,
        sources: message.grounded === true && Array.isArray(message.sources)
          ? message.sources.slice(0, 20)
          : [],
      }));
    });
    return state;
  }

  function write(state) {
    state = prune(state);
    let serialized = JSON.stringify(state);

    // Reduce history gradually instead of deleting everything at once.
    while (serialized.length > MAX_BYTES && state.sessions.length) {
      const oldest = state.sessions[state.sessions.length - 1];
      if (oldest.messages.length > 8) {
        oldest.messages.splice(0, Math.ceil(oldest.messages.length / 4));
      } else {
        state.sessions.pop();
      }
      serialized = JSON.stringify(state);
    }
    try {
      memoryState = JSON.parse(serialized);
      localStorage.setItem(STORAGE_KEY, serialized);
      storageUnavailable = false;
    } catch (error) {
      storageFailed(error);
    }
    return state;
  }

  function ensureSession(id, title) {
    const state = read();
    const sessionId = id || newId();
    let session = state.sessions.find(item => String(item.id) === String(sessionId));
    if (!session) {
      session = {
        id: sessionId,
        title: String(title || 'Nova pesquisa').slice(0, 120),
        created_at: now(),
        updated_at: now(),
        messages: [],
      };
      state.sessions.unshift(session);
    } else if (title && session.title === 'Nova pesquisa') {
      session.title = String(title).slice(0, 120);
    }
    session.updated_at = now();
    write(state);
    return session.id;
  }

  function addMessage(sessionId, role, content, sources) {
    const state = read();
    let session = state.sessions.find(item => String(item.id) === String(sessionId));
    if (!session) {
      ensureSession(sessionId);
      return addMessage(sessionId, role, content, sources);
    }
    session.messages.push({
      role: role === 'assistant' ? 'assistant' : 'user',
      content: String(content || ''),
      created_at: now(),
      grounded: false,
      sources: Array.isArray(sources) ? sources.slice(0, 20) : [],
    });
    if (role === 'user' && session.title === 'Nova pesquisa') {
      session.title = String(content || 'Nova pesquisa').slice(0, 120);
    }
    session.updated_at = now();
    write(state);
  }

  function updateLastAssistant(sessionId, content, sources, grounded = false) {
    const state = read();
    const session = state.sessions.find(item => String(item.id) === String(sessionId));
    if (!session) return;
    const messages = session.messages;
    const last = messages[messages.length - 1];
    if (last && last.role === 'assistant') {
      last.content = String(content || '');
      last.grounded = grounded === true;
      last.sources = last.grounded && Array.isArray(sources) ? sources.slice(0, 20) : [];
    } else {
      messages.push({
        role: 'assistant',
        content: String(content || ''),
        created_at: now(),
        grounded: grounded === true,
        sources: grounded === true && Array.isArray(sources) ? sources.slice(0, 20) : [],
      });
    }
    session.updated_at = now();
    write(state);
  }

  function prepareRetry(sessionId, question) {
    const state = read();
    const session = state.sessions.find(item => String(item.id) === String(sessionId));
    if (!session) return false;
    const messages = session.messages;
    if (messages[messages.length - 1]?.role === 'assistant') messages.pop();
    const last = messages[messages.length - 1];
    if (!last || last.role !== 'user' || last.content !== String(question || '')) return false;
    session.updated_at = now();
    write(state);
    return true;
  }

  function list() {
    return prune(read()).sessions.map(session => ({
      id: session.id,
      slug: session.id,
      title: session.title,
      is_pinned: session.is_pinned === true,
      created_at: session.created_at,
      updated_at: session.updated_at,
      messages_count: session.messages.length,
    }));
  }

  function get(id) {
    const session = prune(read()).sessions.find(item => String(item.id) === String(id));
    return session ? JSON.parse(JSON.stringify(session)) : null;
  }

  function setTitle(id, title) {
    const clean = String(title || '').replace(/[\u0000-\u001f]/g, ' ').trim().slice(0, 70);
    if (!clean) return false;
    const state = read();
    const session = state.sessions.find(item => String(item.id) === String(id));
    if (!session) return false;
    session.title = clean;
    session.updated_at = now();
    write(state);
    return true;
  }

  function setPinned(id, isPinned) {
    if (typeof isPinned !== 'boolean') return false;
    const state = read();
    const session = state.sessions.find(item => String(item.id) === String(id));
    if (!session) return false;
    session.is_pinned = isPinned;
    session.updated_at = now();
    write(state);
    return true;
  }

  function remove(id) {
    const state = read();
    const session = state.sessions.find(item => String(item.id) === String(id));
    if (!session) return false;
    state.sessions = state.sessions.filter(item => String(item.id) !== String(id));
    write(state);
    return true;
  }

  function clear() {
    try {
      localStorage.removeItem(STORAGE_KEY);
      memoryState = emptyState();
      return true;
    } catch (error) {
      memoryState = emptyState();
      storageFailed(error);
      return false;
    }
  }

  function exportData() {
    const allowedSourceFields = [
      'id', 'norma_ref', 'dispositivo_ref', 'text', 'full_text', 'sapl_url', 'pdf_url',
      'source_url', 'similarity_score', 'contribution', 'source_type', 'data_publicacao',
      'data_vigencia', 'citation_id', 'citation_index', 'citation_label',
      'retrieval_strategy', 'evidence_scope', 'coverage',
    ];
    const state = prune(read());
    return {
      schema: 'jurix-anonymous-history-export/v1',
      exported_at: now(),
      sessions: state.sessions.map(session => ({
        id: String(session.id),
        title: String(session.title || 'Nova pesquisa').slice(0, 120),
        created_at: session.created_at,
        updated_at: session.updated_at,
        messages: session.messages.map(message => ({
          role: message.role === 'assistant' ? 'assistant' : 'user',
          content: String(message.content || ''),
          created_at: message.created_at,
          grounded: message.role === 'assistant' && message.grounded === true,
          sources: message.role === 'assistant' && message.grounded === true
            ? (Array.isArray(message.sources) ? message.sources : []).slice(0, 20).map(source =>
              Object.fromEntries(allowedSourceFields
                .filter(key => Object.prototype.hasOwnProperty.call(source || {}, key))
                .map(key => [key, source[key]])))
            : [],
        })),
      })),
    };
  }

  window.JurixAnonymousHistory = {
    isAnonymous,
    newId,
    ensureSession,
    addMessage,
    updateLastAssistant,
    prepareRetry,
    list,
    get,
    setTitle,
    setPinned,
    remove,
    clear,
    exportData,
  };
})();
