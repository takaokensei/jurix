(function () {
    'use strict';
    let lastMenuTrigger = null;
    let dialogSession = null;
    let dialogAction = null;
    let currentSessions = [];

    async function sessions() {
        const store = window.JurixAnonymousHistory;
        if (store?.isAnonymous()) return store.list();
        const data = await window.JurixChatAPI.listSessions();
        return Array.isArray(data.sessions) ? data.sessions : [];
    }
    function sessionUrl(session) {
        return `${document.body.dataset.chatbotUrl || '/assistente/'}${encodeURIComponent(session.slug || session.id)}/`;
    }

    function announce(message, isError = false) {
        let status = document.getElementById('jurix-sidebar-status');
        if (!status) {
            status = document.createElement('p');
            status.id = 'jurix-sidebar-status';
            status.className = 'jurix-sidebar-status';
            status.setAttribute('role', 'status');
            status.setAttribute('aria-live', 'polite');
            document.body.append(status);
        }
        status.textContent = message;
        status.dataset.error = String(isError);
        status.setAttribute('role', isError ? 'alert' : 'status');
        clearTimeout(status._dismissTimer);
        status._dismissTimer = setTimeout(() => status.remove(), 3500);
    }

    function closeMenu(restoreFocus = false) {
        document.getElementById('jurix-session-menu')?.remove();
        if (restoreFocus && lastMenuTrigger?.isConnected) lastMenuTrigger.focus();
    }

    function buildMenuButton(menu, label, action, extraClass = '') {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = `jurix-session-menu-item${extraClass ? ` ${extraClass}` : ''}`;
        button.setAttribute('role', 'menuitem');
        button.dataset.sessionAction = action;
        button.textContent = label;
        menu.append(button);
        return button;
    }

    function openMenu(trigger, session) {
        closeMenu();
        lastMenuTrigger = trigger;
        const menu = document.createElement('div');
        menu.id = 'jurix-session-menu';
        menu.className = 'jurix-session-menu';
        menu.setAttribute('role', 'menu');
        menu.setAttribute('aria-label', `Opções da conversa ${session.title || ''}`);
        menu.dataset.sessionId = String(session.id);
        menu.dataset.sessionSlug = String(session.slug || '');
        menu.dataset.sessionTitle = String(session.title || '');
        menu.dataset.pinned = String(session.is_pinned === true);
        menu.dataset.pending = String(session.is_pending === true);
        if (session.is_pending === true) {
            buildMenuButton(menu, 'Remover pesquisa pendente', 'delete', 'is-danger');
        } else {
            buildMenuButton(menu, 'Renomear', 'rename');
            buildMenuButton(menu, session.is_pinned ? 'Desafixar' : 'Fixar', 'pin');
            const divider = document.createElement('div');
            divider.className = 'jurix-session-menu-divider';
            divider.setAttribute('role', 'separator');
            menu.append(divider);
            buildMenuButton(menu, 'Excluir conversa', 'delete', 'is-danger');
        }
        document.body.append(menu);

        const bounds = trigger.getBoundingClientRect();
        const menuBounds = menu.getBoundingClientRect();
        const left = Math.max(8, Math.min(bounds.right - menuBounds.width, window.innerWidth - menuBounds.width - 8));
        const top = Math.max(8, Math.min(bounds.bottom + 4, window.innerHeight - menuBounds.height - 8));
        menu.style.left = `${left}px`;
        menu.style.top = `${top}px`;
        menu.querySelector('[role="menuitem"]')?.focus();
    }

    function ensureDialog() {
        let dialog = document.getElementById('jurix-session-dialog');
        if (dialog) return dialog;
        dialog = document.createElement('dialog');
        dialog.id = 'jurix-session-dialog';
        dialog.className = 'jurix-session-dialog';
        dialog.innerHTML = `<form class="jurix-session-dialog__form">
          <h2 class="jurix-session-dialog__title"></h2>
          <p class="jurix-session-dialog__description"></p>
          <label class="jurix-session-dialog__field" hidden>Nome da conversa
            <input name="title" maxlength="70" autocomplete="off">
          </label>
          <p class="jurix-session-dialog__error" role="alert" hidden></p>
          <div class="jurix-session-dialog__actions">
            <button type="button" class="jurix-session-dialog__cancel">Cancelar</button>
            <button type="submit" class="jurix-session-dialog__confirm"></button>
          </div>
        </form>`;
        document.body.append(dialog);
        dialog.querySelector('.jurix-session-dialog__form').addEventListener('submit', submitDialog);
        dialog.querySelector('.jurix-session-dialog__cancel').addEventListener('click', () => dialog.close());
        dialog.addEventListener('close', () => {
            if (lastMenuTrigger?.isConnected) lastMenuTrigger.focus();
        });
        return dialog;
    }

    function showDialog(action, session) {
        const dialog = ensureDialog();
        dialogAction = action;
        dialogSession = session;
        const rename = action === 'rename';
        dialog.querySelector('.jurix-session-dialog__title').textContent = rename
            ? 'Renomear conversa'
            : session.is_pending === true ? 'Remover pesquisa pendente?' : 'Excluir conversa?';
        dialog.querySelector('.jurix-session-dialog__description').textContent = rename
            ? 'Escolha um nome curto para encontrar esta conversa depois.'
            : session.is_pending === true
                ? 'A pergunta não enviada ao histórico será removida desta lista.'
                : 'O histórico desta conversa será removido permanentemente.';
        const field = dialog.querySelector('.jurix-session-dialog__field');
        const input = dialog.querySelector('input[name="title"]');
        field.hidden = !rename;
        input.value = rename ? session.title || '' : '';
        dialog.querySelector('.jurix-session-dialog__confirm').textContent = rename ? 'Salvar nome' : 'Excluir conversa';
        dialog.querySelector('.jurix-session-dialog__confirm').classList.toggle('is-danger', !rename);
        dialog.querySelector('.jurix-session-dialog__error').hidden = true;
        dialog.showModal();
        if (rename) input.focus();
        else dialog.querySelector('.jurix-session-dialog__cancel').focus();
    }

    async function updateSession(session, updates) {
        if (String(session.id).startsWith('local-')) {
            const store = window.JurixAnonymousHistory;
            const result = updates.title !== undefined
                ? store?.setTitle?.(session.id, updates.title)
                : store?.setPinned?.(session.id, updates.is_pinned);
            if (!result) throw new Error('Não foi possível atualizar a conversa local.');
        } else {
            await window.JurixChatAPI.updateSession(session.id, updates);
        }
        window.dispatchEvent(new Event('jurix:sessions-changed'));
    }

    async function submitDialog(event) {
        event.preventDefault();
        if (!dialogSession || !dialogAction) return;
        const dialog = event.currentTarget.closest('dialog');
        const confirm = dialog.querySelector('.jurix-session-dialog__confirm');
        const error = dialog.querySelector('.jurix-session-dialog__error');
        confirm.disabled = true;
        try {
            if (dialogAction === 'rename') {
                const title = dialog.querySelector('input[name="title"]').value.trim();
                if (!title) throw new Error('Digite um nome para a conversa.');
                await updateSession(dialogSession, { title });
                announce('Nome da conversa atualizado.');
            } else if (dialogSession.is_pending === true) {
                [...document.querySelectorAll('.chat-session-item')]
                    .find((item) => item.dataset.sessionId === String(dialogSession.id))?.remove();
                const list = document.getElementById('chat-sessions-list');
                if (list && !list.querySelector('.chat-session-item')) list.textContent = 'Nenhuma conversa ainda';
                announce('Pesquisa pendente removida.');
            } else {
                const id = String(dialogSession.id);
                if (id.startsWith('local-')) {
                    if (!window.JurixAnonymousHistory?.remove?.(id)) throw new Error('Não foi possível excluir a conversa.');
                } else {
                    await window.JurixChatAPI.deleteSession(id);
                }
                const path = window.location.pathname;
                if (path.includes(encodeURIComponent(dialogSession.slug || id))) {
                    window.location.assign(document.body.dataset.chatbotUrl || '/assistente/');
                    return;
                }
                announce('Conversa excluída.');
                window.dispatchEvent(new Event('jurix:sessions-changed'));
            }
            dialog.close();
        } catch (failure) {
            error.textContent = failure.message || 'Não foi possível concluir a ação. Tente novamente.';
            error.hidden = false;
        } finally {
            confirm.disabled = false;
        }
    }
    function updateSessionRow(item, session, isActive, { keepPending = false } = {}) {
        const isPending = session.is_pending === true;
        item.className = `chat-session-item${isActive ? ' active' : ''}${isPending ? ' session-card-new' : ''}`;
        if (session.is_pinned === true) item.classList.add('is-pinned');
        item.dataset.sessionId = String(session.id);
        item.dataset.pinned = String(session.is_pinned === true);
        if (session.client_session_id || session.pending_client_session_id) {
            item.dataset.clientSessionId = String(session.client_session_id || session.pending_client_session_id);
        } else if (!keepPending && !isPending) {
            delete item.dataset.clientSessionId;
        }
        if (keepPending || isPending) item.dataset.sessionPending = 'true';
        else delete item.dataset.sessionPending;
        if (isPending) {
            item.dataset.pendingLocal = String(session.pending_local === true);
            item.dataset.pendingQuestion = String(session.pending_question || '');
            item.dataset.pendingState ||= 'running';
        } else if (!keepPending) {
            delete item.dataset.pendingLocal;
            delete item.dataset.pendingQuestion;
            delete item.dataset.pendingState;
            delete item.dataset.pendingServer;
        }

        let link = item.querySelector('.chat-session-main');
        if (!link) {
            link = document.createElement('a');
            link.className = 'jurix-recent-chat chat-session-main';
        }
        link.href = isPending && session.pending_local === true
            ? (document.body.dataset.chatbotUrl || '/assistente/')
            : sessionUrl(session);
        link.textContent = session.title || 'Conversa sem título';
        link.title = link.textContent;
        link.removeAttribute('aria-current');
        if (isActive) link.setAttribute('aria-current', 'page');
        if (isPending && session.pending_local === true) {
            link.dataset.pendingSessionLink = '';
            link.setAttribute('aria-label', `Retomar pesquisa: ${link.textContent}`);
        } else {
            delete link.dataset.pendingSessionLink;
            link.removeAttribute('aria-label');
        }
        item.append(link);

        let pin = item.querySelector('.jurix-session-pinned-mark');
        if (session.is_pinned === true) {
            if (!pin) {
                pin = document.createElement('span');
                pin.className = 'jurix-session-pinned-mark';
                pin.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m16 3 5 5-4 1-4 4-3-3 4-4 2-3Z"></path><path d="m12 13-1 8"></path></svg>';
            }
            pin.setAttribute('aria-label', 'Conversa fixada');
            pin.title = 'Conversa fixada';
            item.append(pin);
        } else pin?.remove();

        let menuButton = item.querySelector('[data-session-menu-trigger]');
        if (!menuButton) {
            menuButton = document.createElement('button');
            menuButton.type = 'button';
            menuButton.className = 'jurix-session-menu-trigger';
            menuButton.setAttribute('aria-haspopup', 'menu');
            menuButton.dataset.sessionMenuTrigger = '';
        }
        menuButton.setAttribute('aria-label', isPending && session.pending_local === true
            ? `Opções da pesquisa pendente: ${link.textContent}`
            : `Opções da conversa: ${link.textContent}`);
        menuButton.title = isPending && item.dataset.pendingState !== 'failed'
            ? 'A pesquisa está em andamento'
            : 'Opções da conversa';
        menuButton.textContent = '⋯';
        menuButton.disabled = isPending && item.dataset.pendingState !== 'failed';
        item.append(menuButton);
        return item;
    }

    function addPending({ clientSessionId, question, title } = {}) {
        const list = document.getElementById('chat-sessions-list');
        if (!list) return false;
        const clientId = String(clientSessionId || '');
        if (!clientId) return false;
        const existing = [...list.querySelectorAll('.chat-session-item[data-client-session-id]')]
            .find((item) => item.dataset.clientSessionId === clientId);
        if (existing) return existing;
        const row = updateSessionRow(document.createElement('div'), {
            id: `pending-${clientId}`,
            title: title || String(question || '').slice(0, 50) || 'Nova pesquisa',
            is_pending: true,
            pending_local: true,
            pending_question: question,
            client_session_id: clientId,
        }, true);
        if (!list.querySelector('.chat-session-item')) list.replaceChildren();
        else list.querySelector('[data-history-empty], .history-empty, .chat-sessions-empty')?.remove();
        list.prepend(row);
        return row;
    }

    function reconcilePending(clientSessionId, session = {}) {
        const list = document.getElementById('chat-sessions-list');
        const row = [...(list?.querySelectorAll('.chat-session-item[data-session-pending="true"]') || [])]
            .find((item) => item.dataset.clientSessionId === String(clientSessionId));
        const sessionId = session.id || session.session_id;
        if (!row || !sessionId) return false;
        const title = session.title || row.querySelector('.chat-session-main')?.textContent || 'Conversa sem título';
        updateSessionRow(row, {
            ...session,
            id: sessionId,
            slug: session.slug || session.session_slug,
            title,
            is_pending: true,
            pending_local: false,
            client_session_id: clientSessionId,
        }, true, { keepPending: true });
        row.dataset.pendingServer = 'true';
        return row;
    }

    function updatePendingTitle(clientSessionId, title) {
        if (!title) return false;
        const row = [...document.querySelectorAll('.chat-session-item[data-session-pending="true"]')]
            .find((item) => item.dataset.clientSessionId === String(clientSessionId));
        const link = row?.querySelector('.chat-session-main');
        if (!link) return false;
        link.textContent = String(title);
        link.title = link.textContent;
        if (row.dataset.pendingLocal === 'true') link.setAttribute('aria-label', `Retomar pesquisa: ${link.textContent}`);
        return true;
    }

    function markPendingFailed(clientSessionId) {
        const row = [...document.querySelectorAll('.chat-session-item[data-session-pending="true"]')]
            .find((item) => item.dataset.clientSessionId === String(clientSessionId));
        if (!row) return false;
        row.dataset.pendingState = 'failed';
        const trigger = row.querySelector('[data-session-menu-trigger]');
        if (trigger) {
            trigger.disabled = false;
            trigger.title = 'Opções da conversa';
        }
        return true;
    }

    function markPendingRunning(clientSessionId) {
        const row = [...document.querySelectorAll('.chat-session-item[data-session-pending="true"]')]
            .find((item) => item.dataset.clientSessionId === String(clientSessionId));
        if (!row) return false;
        row.dataset.pendingState = 'running';
        const trigger = row.querySelector('[data-session-menu-trigger]');
        if (trigger) {
            trigger.disabled = true;
            trigger.title = 'A pesquisa está em andamento';
        }
        return true;
    }

    function render(entries, { activeSessionId = null, preserveTemporary = false } = {}) {
        const list = document.getElementById('chat-sessions-list');
        if (!list) return false;
        const temporary = preserveTemporary
            ? [...list.querySelectorAll('.chat-session-item[data-session-pending="true"]')]
            : [];
        const sorted = [...(Array.isArray(entries) ? entries : [])].sort((a, b) => {
            const pinned = Number(b.is_pinned === true) - Number(a.is_pinned === true);
            if (pinned) return pinned;
            const dateA = Date.parse(a.updated_at || a.created_at || '') || 0;
            const dateB = Date.parse(b.updated_at || b.created_at || '') || 0;
            return dateB - dateA || String(b.id).localeCompare(String(a.id), undefined, { numeric: true });
        });
        currentSessions = sorted;
        list.replaceChildren();
        const remainingTemporary = new Set(temporary);
        sorted.slice(0, 24).forEach(session => {
            const isActive = activeSessionId != null && String(session.id) === String(activeSessionId);
            const pendingRow = temporary.find((row) =>
                row.dataset.sessionId === String(session.id) ||
                (session.client_session_id && row.dataset.clientSessionId === String(session.client_session_id))
            );
            const item = pendingRow || document.createElement('div');
            if (pendingRow) remainingTemporary.delete(pendingRow);
            updateSessionRow(item, session, isActive);
            list.append(item);
        });
        remainingTemporary.forEach((item) => list.append(item));
        if (!sorted.length && !remainingTemporary.size) list.textContent = 'Nenhuma conversa ainda';
        return true;
    }
    async function refresh() {
        const list = document.getElementById('chat-sessions-list');
        if (!list) return;
        try {
            const entries = await sessions();
            const active = document.querySelector('.chat-session-item.active')?.dataset.sessionId || null;
            render(entries, { activeSessionId: active });
        } catch (_) {
            list.textContent = 'Histórico indisponível. Tente novamente ao abrir a busca.';
        }
    }

    document.addEventListener('click', (event) => {
        const trigger = event.target.closest?.('[data-session-menu-trigger]');
        if (trigger) {
            event.preventDefault();
            const session = currentSessions.find(item => String(item.id) === trigger.closest('[data-session-id]')?.dataset.sessionId);
            const row = trigger.closest('[data-session-id]');
            if (session) openMenu(trigger, session);
            else if (row) openMenu(trigger, {
                id: row.dataset.sessionId,
                title: row.querySelector('.chat-session-main')?.textContent || 'Conversa',
                is_pinned: row.dataset.pinned === 'true',
                is_pending: row.dataset.pendingLocal === 'true',
            });
            return;
        }
        const menuAction = event.target.closest?.('[data-session-action]');
        if (menuAction) {
            const menu = menuAction.closest('.jurix-session-menu');
            const session = {
                id: menu.dataset.sessionId,
                slug: menu.dataset.sessionSlug,
                title: menu.dataset.sessionTitle,
                is_pinned: menu.dataset.pinned === 'true',
                is_pending: menu.dataset.pending === 'true',
            };
            const action = menuAction.dataset.sessionAction;
            closeMenu();
            if (action === 'rename' || action === 'delete') showDialog(action, session);
            if (action === 'pin') updateSession(session, { is_pinned: !session.is_pinned })
                .then(() => announce(session.is_pinned ? 'Conversa desafixada.' : 'Conversa fixada no topo.'))
                .catch(() => announce('Não foi possível alterar a conversa. Tente novamente.', true));
            return;
        }
        if (!event.target.closest?.('#jurix-session-menu')) closeMenu();
    });
    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && document.getElementById('jurix-session-menu')) closeMenu(true);
    });
    document.getElementById('chat-sessions-list')?.addEventListener('scroll', () => closeMenu(), { passive: true });

    window.JurixSidebar = Object.freeze({
        sessions,
        sessionUrl,
        render,
        addPending,
        reconcilePending,
        updatePendingTitle,
        markPendingFailed,
        markPendingRunning,
        refresh,
    });
    document.querySelectorAll('[data-search-conversations]').forEach(button => {
        button.addEventListener('click', () => window.jurixCommandPalette?.open({ conversationsOnly: true }));
    });
    document.getElementById('new-chat-button')?.addEventListener('click', event => event.preventDefault());
    window.addEventListener('storage', refresh);
    window.addEventListener('jurix:sessions-changed', refresh);
    if (!document.querySelector('.figma-workspace')) refresh();
})();
