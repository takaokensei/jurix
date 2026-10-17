function initFoundationCheck() {
  let root = document.querySelector('#foundation-workspace');
  if (!root) return;
  let form = root.querySelector('[data-foundation-form]');
  if (!form || form.dataset.initialized === 'true') return;
  form.dataset.initialized = 'true';
  // A submit button named "action" masks HTMLFormElement.action with the button.
  const endpoint = form.getAttribute('action') || window.location.href;
  let progress = form.querySelector('[data-foundation-progress]');
  let cancelButton = form.querySelector('[data-foundation-cancel]');
  const csrf = form.querySelector('[name=csrfmiddlewaretoken]')?.value || '';
  let submitting = false;
  let polling = false;
  let timer = null;

  const showProgress = (completed, total) => {
    progress.replaceChildren();
    if (total > 0) {
      const label = document.createElement('span');
      label.textContent = `Conferindo projeções temporais (${completed} de ${total})…`;
      const bar = document.createElement('progress');
      bar.max = 100;
      bar.value = Math.min(100, Math.floor((completed / total) * 100));
      bar.setAttribute('aria-label', 'Progresso da conferência');
      progress.append(label, bar);
      return;
    }
    progress.textContent = 'Conferindo referências e cobertura do corpus…';
  };

  const replaceWorkspace = (html, targetUrl, preservedText = null) => {
    const parsed = new DOMParser().parseFromString(html, 'text/html');
    const updated = parsed.querySelector('#foundation-workspace');
    if (!updated) {
      window.location.assign(targetUrl || endpoint);
      return null;
    }
    root.replaceWith(updated);
    root = updated;
    form = updated.querySelector('[data-foundation-form]');
    progress = form?.querySelector('[data-foundation-progress]');
    cancelButton = form?.querySelector('[data-foundation-cancel]');
    if (preservedText !== null) {
      const textarea = updated.querySelector('#foundation-text');
      if (textarea) textarea.value = preservedText;
    }
    const target = updated.querySelector('[role=alert]')
      || updated.querySelector('[data-foundation-summary]')
      || updated.querySelector('[role=status]')
      || updated.querySelector('h1');
    target?.focus({ preventScroll: false });
    const reducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    window.scrollTo({
      top: updated.getBoundingClientRect().top + window.scrollY - 24,
      behavior: reducedMotion ? 'auto' : 'smooth',
    });
    window.jurixInitFoundationCheck?.();
    return updated;
  };

  const finishFromResult = async (preservedText, status) => {
    if (timer) window.clearInterval(timer);
    timer = null;
    if (status === 'cancelled') progress.textContent = 'Conferência interrompida; preservando o texto para nova tentativa…';
    if (status === 'failed') progress.textContent = 'Conferência não concluída; preservando o texto…';
    try {
      const response = await fetch(form.dataset.resultUrl, {
        credentials: 'same-origin',
        headers: { 'X-Requested-With': 'XMLHttpRequest' },
      });
      if (!response.ok) throw new Error('result_unavailable');
      const updated = replaceWorkspace(await response.text(), response.url, preservedText);
      if (updated) {
        const replacementForm = updated.querySelector('[data-foundation-form]');
        if (replacementForm) {
          replacementForm.removeAttribute('aria-busy');
          replacementForm.dataset.jobStatus = '';
        }
      }
    } catch (_) {
      progress.textContent = 'Não foi possível carregar o resultado. O texto permanece no campo; tente novamente.';
      form.removeAttribute('aria-busy');
      submitting = false;
      if (cancelButton) cancelButton.hidden = true;
    }
  };

  const poll = async (preservedText = form.querySelector('textarea[name=text]')?.value || '') => {
    if (polling) return;
    polling = true;
    try {
      const response = await fetch(form.dataset.statusUrl, {
        credentials: 'same-origin',
        headers: { Accept: 'application/json' },
      });
      if (!response.ok) throw new Error('status_unavailable');
      const state = await response.json();
      if (state.status === 'queued') {
        progress.textContent = 'Conferência na fila; seu texto permanece apenas nesta sessão.';
      } else if (state.status === 'cancelling') {
        progress.textContent = 'Interrupção solicitada; aguardando encerrar a operação atual…';
      } else if (state.status === 'completed' || state.status === 'cancelled' || state.status === 'failed') {
        await finishFromResult(preservedText, state.status);
      } else if (state.total > 0) {
        showProgress(state.completed, state.total);
      } else {
        progress.textContent = 'Conferindo referências e cobertura do corpus…';
      }
    } catch (_) {
      progress.textContent = 'Conferência em andamento; tentando atualizar o estado…';
    } finally {
      polling = false;
    }
  };

  const startPolling = () => {
    if (timer) return;
    form.setAttribute('aria-busy', 'true');
    if (cancelButton) cancelButton.hidden = false;
    poll();
    timer = window.setInterval(poll, 800);
  };

  if (form.dataset.jobStatus === 'queued' || form.dataset.jobStatus === 'running') {
    startPolling();
  }

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
    const preservedText = form.querySelector('textarea[name=text]')?.value || '';
    form.setAttribute('aria-busy', 'true');
    const data = new FormData(form);
    data.set('action', action);
    if (submitter) submitter.disabled = true;
    progress.textContent = action === 'compare' ? 'Enviando conferência para a fila segura…' : 'Identificando referências…';

    try {
      const response = await fetch(endpoint, {
        method: 'POST',
        body: data,
        credentials: 'same-origin',
        headers: { 'X-Requested-With': 'XMLHttpRequest' },
      });
      const updated = replaceWorkspace(await response.text(), response.url, preservedText);
      if (!updated) return;
      if (action === 'compare' && response.ok && updated.querySelector('[data-foundation-form]')?.dataset.jobStatus === 'queued') {
        if (updated.querySelector('[data-foundation-form]')?.dataset.initialized !== 'true') {
          startPolling();
        }
      } else {
        submitting = false;
        const replacementForm = updated.querySelector('[data-foundation-form]');
        replacementForm?.removeAttribute('aria-busy');
      }
    } catch (_) {
      progress.textContent = 'Falha de conexão durante a conferência. O texto permanece no campo; tente novamente.';
      submitting = false;
      form.removeAttribute('aria-busy');
      if (submitter) submitter.disabled = false;
      if (cancelButton) cancelButton.hidden = true;
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
      progress.textContent = 'Não foi possível confirmar a interrupção; a conferência ainda pode estar em andamento.';
    }
  });
}

window.jurixInitFoundationCheck = initFoundationCheck;
initFoundationCheck();
