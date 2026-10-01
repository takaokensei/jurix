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
  const normalize = value => String(value || '').normalize('NFKD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase('pt-BR');
  const tokens = value => normalize(value).match(/[\p{L}\p{N}]{2,}/gu)?.filter(word => !stopwords.has(word)) || [];
  const plainText = value => String(value || '')
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/!\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
    .replace(/^\s{0,3}#{1,6}\s+/gm, '')
    .replace(/^\s{0,3}(?:[-*+]\s+|\d+[.)]\s+)/gm, '')
    .replace(/[>*_`~]/g, '')
    .replace(/<[^>]*>/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
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
      const rawPreview = firstAssistant?.content || firstUser?.content || '';
      let cleanedPreview = plainText(rawPreview);
      const foldedTitle = normalize(title);
      if (foldedTitle && normalize(cleanedPreview).startsWith(foldedTitle)) {
        cleanedPreview = cleanedPreview.slice(String(title).length).replace(/^[\s:—–.,;!?-]+/, '').trim();
      }
      const preview = !cleanedPreview
        ? `${count} ${count === 1 ? 'mensagem registrada' : 'mensagens registradas'}`
        : cleanedPreview;
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
      return `<article class="workspace-history-card" data-history-card data-session-id="${escapeHtml(session.id)}">
        <div class="workspace-history-card__surface"><a class="workspace-history-card__link" href="${href}">
          <div class="workspace-history-main"><span class="workspace-eyebrow">Conversa local</span><h2>${escapeHtml(title)}</h2><p>${escapeHtml(preview.slice(0, 220))}</p></div>
          <div class="workspace-history-meta"><span>${count} ${count === 1 ? 'mensagem' : 'mensagens'}</span><time datetime="${escapeHtml(session.updated_at)}">${escapeHtml(formatDate(session.updated_at))}</time></div>
        </a></div>
        <button type="button" class="workspace-history-delete" data-history-delete aria-label="Excluir conversa: ${escapeHtml(title)}" title="Excluir conversa">Excluir</button>
      </article>`;
    }).join('')}
  `;
  };
  searchForm?.addEventListener('submit', event => { event.preventDefault(); render(); });
  searchInput?.addEventListener('input', render);
  searchInput?.addEventListener('search', render);
  render();
})();
