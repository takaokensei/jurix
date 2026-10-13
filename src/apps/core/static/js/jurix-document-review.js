(() => {
  const forms = document.querySelectorAll('[data-document-review-form]');
  forms.forEach((form) => {
    const firstError = form.querySelector('[role="alert"]');
    if (firstError) firstError.focus({ preventScroll: false });

    const submit = form.querySelector('[data-document-review-submit]');
    form.addEventListener('submit', (event) => {
      if (form.dataset.submitting === 'true') {
        event.preventDefault();
        return;
      }
      if (!form.reportValidity()) {
        event.preventDefault();
        return;
      }
      form.dataset.submitting = 'true';
      form.setAttribute('aria-busy', 'true');
      if (submit) {
        submit.disabled = true;
        submit.textContent = submit.dataset.submittingLabel || 'Registrando identidade…';
      }
    });
  });
})();
