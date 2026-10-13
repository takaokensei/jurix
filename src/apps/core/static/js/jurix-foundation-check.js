function initFoundationCheck() {
  const root = document.querySelector('#foundation-workspace');
  if (!root) return;
  const form = root.querySelector('[data-foundation-form]');
  if (!form || form.dataset.initialized === 'true') return;
  form.dataset.initialized = 'true';
  // A submit button named "action" masks HTMLFormElement.action with the
  // button element. Read the endpoint attribute directly for fetch/redirect.
  const endpoint = form.getAttribute('action') || window.location.href;

  const progress = form.querySelector('[data-foundation-progress]');
  const cancelButton = form.querySelector('[data-foundation-cancel]');
  const csrf = form.querySelector('[name=csrfmiddlewaretoken]')?.value || '';
  let submitting = false;
  let polling = false;

  const poll = async () => {
    if (polling) return;
    polling = true;
    try {
      const response = await fetch(form.dataset.statusUrl, {
        credentials: 'same-origin',
        headers: { Accept: 'application/json' },
      });
      if (!response.ok) return;
      const state = await response.json();
      if (state.total > 0) {
        const percent = Math.floor((state.completed / state.total) * 100);
        progress.innerHTML = `Conferindo projeções temporais (${state.completed} de ${state.total})…<progress max="100" value="${percent}" aria-label="Progresso da conferência"></progress>`;
      } else {
        progress.textContent = 'Conferindo referências e cobertura do corpus…';
      }
      if (state.status === 'cancelling') progress.textContent = 'Interrupção solicitada; aguardando finalizar a projeção atual…';
    } catch (_) {
      progress.textContent = 'Conferência em andamento…';
    } finally {
      polling = false;
    }
  };

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (submitting) return;
    const submitter = event.submitter;
    const action = submitter?.value || 'review';
    const fromDate = form.elements.namedItem('from_date');
    const toDate = form.elements.namedItem('to_date');
    fromDate?.setCustomValidity('');
    toDate?.setCustomValidity('');
    if (action === 'compare') {
      if (fromDate && !fromDate.value) fromDate.setCustomValidity('Informe a data inicial da comparação.');
      if (toDate && !toDate.value) toDate.setCustomValidity('Informe a data final da comparação.');
      if (fromDate?.value && toDate?.value && fromDate.value >= toDate.value) {
        toDate.setCustomValidity('A data final deve ser posterior à data inicial.');
      }
    }
    if (!form.reportValidity()) return;
    submitting = true;
    form.setAttribute('aria-busy', 'true');
    const data = new FormData(form);
    data.set('action', action);
    if (submitter) submitter.disabled = true;
    if (action === 'compare') {
      cancelButton.hidden = false;
      progress.textContent = 'Iniciando conferência…';
    } else {
      progress.textContent = 'Identificando referências…';
    }

    let timer;
    if (action === 'compare') {
      await poll();
      timer = window.setInterval(poll, 800);
    }
    try {
      const response = await fetch(endpoint, {
        method: 'POST',
        body: data,
        credentials: 'same-origin',
        headers: { 'X-Requested-With': 'XMLHttpRequest' },
      });
      const html = await response.text();
      const parsed = new DOMParser().parseFromString(html, 'text/html');
      const updated = parsed.querySelector('#foundation-workspace');
      if (!updated) {
        window.location.assign(response.url || endpoint);
        return;
      }
      root.replaceWith(updated);
      const target = updated.querySelector('[role=alert]')
        || updated.querySelector('[data-foundation-summary]')
        || updated.querySelector('[role=status]')
        || updated.querySelector('h1');
      target?.focus({ preventScroll: false });
      const reducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
      window.scrollTo({ top: updated.getBoundingClientRect().top + window.scrollY - 24, behavior: reducedMotion ? 'auto' : 'smooth' });
      // The updated fragment contains the new job token and is initialized after replacement.
      window.jurixInitFoundationCheck?.();
    } catch (_) {
      progress.textContent = 'Falha de conexão durante a conferência. O texto permanece no campo; tente novamente.';
      submitting = false;
      form.removeAttribute('aria-busy');
      if (submitter) submitter.disabled = false;
      cancelButton.hidden = true;
    } finally {
      if (timer) window.clearInterval(timer);
    }
  });

  cancelButton?.addEventListener('click', async () => {
    cancelButton.disabled = true;
    progress.textContent = 'Solicitando interrupção segura…';
    try {
      await fetch(form.dataset.cancelUrl, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'X-CSRFToken': csrf, Accept: 'application/json' },
      });
    } catch (_) {
      progress.textContent = 'Não foi possível confirmar a interrupção; a requisição ainda pode estar em andamento.';
    }
  });
}

window.jurixInitFoundationCheck = initFoundationCheck;
initFoundationCheck();
