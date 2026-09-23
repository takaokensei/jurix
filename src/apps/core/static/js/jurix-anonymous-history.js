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
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return emptyState();
      const value = JSON.parse(raw);
      if (!value || value.schema !== SCHEMA_VERSION || !Array.isArray(value.sessions)) {
        return emptyState();
      }
      return value;
    } catch (error) {
      console.warn('[Jurix] anonymous history read failed', error);
      return emptyState();
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
        sources: Array.isArray(message.sources) ? message.sources.slice(0, 20) : [],
      }));
    });
    return state;
  }

  function write(state) {
    state = prune(state);
    let serialized = JSON.stringify(state);
    if (serialized.length <= MAX_BYTES) {
      localStorage.setItem(STORAGE_KEY, serialized);
      return state;
    }

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
      localStorage.setItem(STORAGE_KEY, serialized);
    } catch (error) {
      console.warn('[Jurix] anonymous history write failed', error);
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
      sources: Array.isArray(sources) ? sources.slice(0, 20) : [],
    });
    if (role === 'user' && session.title === 'Nova pesquisa') {
      session.title = String(content || 'Nova pesquisa').slice(0, 120);
    }
    session.updated_at = now();
    write(state);
  }

  function updateLastAssistant(sessionId, content, sources) {
    const state = read();
    const session = state.sessions.find(item => String(item.id) === String(sessionId));
    if (!session) return;
    const messages = session.messages;
    const last = messages[messages.length - 1];
    if (last && last.role === 'assistant') {
      last.content = String(content || '');
      last.sources = Array.isArray(sources) ? sources.slice(0, 20) : (last.sources || []);
    } else {
      messages.push({ role: 'assistant', content: String(content || ''), created_at: now(), sources: sources || [] });
    }
    session.updated_at = now();
    write(state);
  }

  function list() {
    return prune(read()).sessions.map(session => ({
      id: session.id,
      title: session.title,
      created_at: session.created_at,
      updated_at: session.updated_at,
      messages_count: session.messages.length,
    }));
  }

  function get(id) {
    const session = read().sessions.find(item => String(item.id) === String(id));
    return session ? JSON.parse(JSON.stringify(session)) : null;
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
    localStorage.removeItem(STORAGE_KEY);
  }

  window.JurixAnonymousHistory = {
    isAnonymous,
    newId,
    ensureSession,
    addMessage,
    updateLastAssistant,
    list,
    get,
    remove,
    clear,
  };
})();
