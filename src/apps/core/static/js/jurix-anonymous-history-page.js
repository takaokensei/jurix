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

  const searchForm = document.querySelector('[data-history-search]');
  const searchInput = searchForm?.querySelector('input[name="q"]');
  const stopwords = new Set(['para', 'como', 'sobre', 'entre', 'pela', 'pelo', 'uma', 'que', 'qual', 'com', 'dos', 'das']);
  const tokens = value => String(value || '').toLocaleLowerCase('pt-BR').match(/[\p{L}\p{N}]{2,}/gu)?.filter(word => !stopwords.has(word)) || [];
  const baseSessions = store.list();
  root.className = 'workspace-history-list';
  root.setAttribute('aria-live', 'polite');

  const render = () => {
    const queryTokens = [...new Set(tokens(searchInput?.value))];
    const sessions = baseSessions.map(session => {
      const detail = store.get(session.id);
      const firstUser = detail?.messages?.find(message => message.role === 'user');
      const firstAssistant = detail?.messages?.find(message => message.role === 'assistant');
      const title = session.title || firstUser?.content || 'Nova pesquisa';
      const corpus = tokens([title, ...(detail?.messages || []).map(message => message.content)].join(' '));
      const frequency = corpus.reduce((counts, word) => (counts[word] = (counts[word] || 0) + 1, counts), {});
      const score = queryTokens.reduce((sum, word) => sum + Math.min(frequency[word] || 0, 3), 0);
      const count = Number(session.messages_count || detail?.messages?.length || 0);
      const preview = firstAssistant?.content || (firstUser?.content === title ? `${count} ${count === 1 ? 'mensagem registrada' : 'mensagens registradas'}` : firstUser?.content) || 'Conversa sem mensagem registrada';
      return { session, title, preview, score, count };
    }).filter(item => !queryTokens.length || item.score > 0)
      .sort((a, b) => queryTokens.length ? b.score - a.score || String(b.session.updated_at).localeCompare(String(a.session.updated_at)) : String(b.session.updated_at).localeCompare(String(a.session.updated_at)));
    if (!sessions.length) {
      root.innerHTML = queryTokens.length
        ? `<section class="workspace-empty-state workspace-empty-state-large" role="status"><span class="workspace-eyebrow">Busca no histórico</span><h2>Nenhuma conversa encontrada</h2><p>Tente termos relacionados ao assunto, à norma ou ao conteúdo da resposta.</p></section>`
        : `<section class="workspace-empty-state workspace-empty-state-large" aria-labelledby="history-empty-title"><div class="workspace-empty-icon" aria-hidden="true">◷</div><span class="workspace-eyebrow">Histórico vazio</span><h2 id="history-empty-title">Suas pesquisas aparecerão aqui</h2><p>Comece uma conversa no Assistente ou faça uma pesquisa jurídica para criar o primeiro registro.</p><a href="/assistente/" class="workspace-button workspace-button-primary">Abrir Assistente</a></section>`;
      return;
    }
    root.innerHTML = `
    <div class="workspace-section-heading">
      <div><span class="workspace-eyebrow">Sessão pública</span><h2>Conversas deste navegador</h2></div>
      <span class="workspace-badge">${sessions.length} ${sessions.length === 1 ? 'conversa' : 'conversas'}</span>
    </div>
    ${sessions.map(({ session, title, preview, count }) => {
      const href = `/assistente/${encodeURIComponent(session.slug || session.id)}/`;
      return `<a class="workspace-history-card" href="${href}">
        <div class="workspace-history-card__surface"><div class="workspace-history-card__link">
          <div class="workspace-history-main"><span class="workspace-eyebrow">Conversa local</span><h2>${escapeHtml(title)}</h2><p>${escapeHtml(preview.slice(0, 220))}</p></div>
          <div class="workspace-history-meta"><span>${count} ${count === 1 ? 'mensagem' : 'mensagens'}</span><time datetime="${escapeHtml(session.updated_at)}">${escapeHtml(formatDate(session.updated_at))}</time></div>
        </div></div>
      </a>`;
    }).join('')}
  `;
  };
  searchForm?.addEventListener('submit', event => { event.preventDefault(); render(); });
  searchInput?.addEventListener('input', render);
  searchInput?.addEventListener('search', render);
  render();
})();
