(function () {
  'use strict';

  const root = document.querySelector('[data-anonymous-history]');
  const store = window.JurixAnonymousHistory;
  if (!root || !store || typeof store.list !== 'function') return;

  const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[char]));

  const formatDate = (value) => {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return 'agora';
    return new Intl.DateTimeFormat('pt-BR', { dateStyle: 'short', timeStyle: 'short' }).format(date);
  };

  const sessions = store.list();
  if (!sessions.length) return;

  root.className = 'workspace-history-list';
  root.setAttribute('aria-live', 'polite');
  root.innerHTML = `
    <div class="workspace-section-heading">
      <div><span class="workspace-eyebrow">Sessão pública</span><h2>Conversas deste navegador</h2></div>
      <span class="workspace-badge">${sessions.length} ${sessions.length === 1 ? 'conversa' : 'conversas'}</span>
    </div>
    ${sessions.map((session) => {
      const detail = store.get(session.id);
      const firstUser = detail?.messages?.find((message) => message.role === 'user');
      const title = session.title || firstUser?.content || 'Nova pesquisa';
      const preview = firstUser?.content || 'Conversa sem pergunta registrada';
      const count = Number(session.messages_count || detail?.messages?.length || 0);
      const href = `/assistente/${encodeURIComponent(session.slug || session.id)}/`;
      return `<a class="workspace-history-card" href="${href}">
        <div class="workspace-history-main"><span class="workspace-eyebrow">Conversa local</span><h2>${escapeHtml(title)}</h2><p>${escapeHtml(preview.slice(0, 220))}</p></div>
        <div class="workspace-history-meta"><span>${count} ${count === 1 ? 'mensagem' : 'mensagens'}</span><time datetime="${escapeHtml(session.updated_at)}">${escapeHtml(formatDate(session.updated_at))}</time></div>
      </a>`;
    }).join('')}
  `;
})();
