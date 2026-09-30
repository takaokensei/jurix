(function () {
  'use strict';

  let trigger = null;
  let dialog = null;

  function closeDialog(restoreFocus = true) {
    if (!dialog) return;
    dialog.classList.remove('is-open');
    dialog.setAttribute('aria-hidden', 'true');
    dialog.inert = true;
    if (restoreFocus && trigger?.isConnected) trigger.focus();
  }

  function ensureDialog() {
    if (dialog) return dialog;
    dialog = document.createElement('div');
    dialog.className = 'workspace-confirm-backdrop';
    dialog.setAttribute('role', 'dialog');
    dialog.setAttribute('aria-modal', 'true');
    dialog.setAttribute('aria-labelledby', 'history-delete-title');
    dialog.setAttribute('aria-describedby', 'history-delete-description');
    dialog.setAttribute('aria-hidden', 'true');
    dialog.inert = true;
    dialog.innerHTML = `<section class="workspace-confirm-dialog" tabindex="-1">
      <span class="workspace-confirm-icon" aria-hidden="true">!</span>
      <h2 id="history-delete-title">Excluir esta conversa?</h2>
      <p id="history-delete-description">A conversa e seu histórico serão removidos permanentemente.</p>
      <p class="workspace-confirm-error" role="alert" hidden></p>
      <div class="workspace-confirm-actions"><button type="button" class="workspace-button workspace-button-secondary" data-history-cancel>Manter conversa</button><button type="button" class="workspace-button workspace-button-danger" data-history-confirm>Excluir conversa</button></div>
    </section>`;
    document.body.appendChild(dialog);
    dialog.addEventListener('click', (event) => { if (event.target === dialog) closeDialog(); });
    dialog.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') { event.preventDefault(); closeDialog(); return; }
      if (event.key !== 'Tab') return;
      const controls = [...dialog.querySelectorAll('button:not([disabled])')];
      if (!controls.length) return;
      if (event.shiftKey && document.activeElement === controls[0]) { event.preventDefault(); controls.at(-1).focus(); }
      else if (!event.shiftKey && document.activeElement === controls.at(-1)) { event.preventDefault(); controls[0].focus(); }
    });
    dialog.querySelector('[data-history-cancel]').addEventListener('click', () => closeDialog());
    dialog.querySelector('[data-history-confirm]').addEventListener('click', confirmDelete);
    return dialog;
  }

  async function confirmDelete() {
    const card = trigger?.closest('[data-history-card]');
    const confirm = dialog?.querySelector('[data-history-confirm]');
    const error = dialog?.querySelector('.workspace-confirm-error');
    const sessionId = card?.dataset.sessionId;
    if (!sessionId || !window.JurixChatAPI?.deleteSession) return;
    confirm.disabled = true;
    confirm.textContent = 'Excluindo…';
    error.hidden = true;
    try {
      const cards = [...document.querySelectorAll('[data-history-card]')];
      const cardIndex = cards.indexOf(card);
      const adjacentCard = cards[cardIndex + 1] || cards[cardIndex - 1];
      const nextFocusTarget = adjacentCard?.querySelector(
        '.workspace-history-card__link, [data-history-delete], a[href], button:not([disabled])',
      );
      await window.JurixChatAPI.deleteSession(sessionId);
      closeDialog(false);
      card.remove();
      const remaining = document.querySelectorAll('[data-history-card]').length;
      if (!remaining) window.location.reload();
      else nextFocusTarget?.focus({ preventScroll: true });
    } catch (_) {
      // A failed delete can be caused by permissions, server errors or a lost
      // connection. Do not claim the browser is offline unless that is known.
      error.textContent = 'A exclusão não foi concluída. Tente novamente; se continuar, atualize a página.';
      error.hidden = false;
      confirm.disabled = false;
      confirm.textContent = 'Tentar novamente';
    }
  }

  document.addEventListener('click', (event) => {
    const button = event.target.closest?.('[data-history-delete]');
    if (!button) return;
    event.preventDefault();
    trigger = button;
    const modal = ensureDialog();
    modal.inert = false;
    modal.setAttribute('aria-hidden', 'false');
    requestAnimationFrame(() => {
      modal.classList.add('is-open');
      modal.querySelector('[data-history-cancel]').focus();
    });
  });

  document.querySelectorAll('[data-history-card]').forEach((card) => {
    let startX = 0;
    let startY = 0;
    let tracking = false;
    let swipedAt = 0;
    card.addEventListener('pointerdown', (event) => {
      if (event.target.closest('button')) return;
      startX = event.clientX;
      startY = event.clientY;
      tracking = true;
    });
    card.addEventListener('pointermove', (event) => {
      if (!tracking) return;
      const dx = event.clientX - startX;
      const dy = event.clientY - startY;
      if (Math.abs(dy) > Math.abs(dx) + 8) { tracking = false; return; }
      if (dx < -42) {
        document.querySelectorAll('[data-history-card].is-delete-revealed').forEach((item) => item.classList.remove('is-delete-revealed'));
        card.classList.add('is-delete-revealed');
        swipedAt = Date.now();
        tracking = false;
      } else if (dx > 42) {
        card.classList.remove('is-delete-revealed');
        tracking = false;
      }
    });
    card.addEventListener('click', (event) => {
      if (event.target.closest('[data-history-delete]')) return;
      if (Date.now() - swipedAt < 450) {
        event.preventDefault();
        event.stopImmediatePropagation();
      }
    }, true);
    card.addEventListener('pointerup', () => { tracking = false; });
    card.addEventListener('pointercancel', () => { tracking = false; });
  });
})();
