(() => {
    const dialog = document.querySelector('[data-collection-dialog]');
    const open = document.querySelector('[data-open-collection-form]');
    const close = document.querySelector('[data-close-collection-form]');
    if (dialog && open) {
        open.addEventListener('click', () => dialog.showModal());
        close?.addEventListener('click', () => dialog.close());
        dialog.addEventListener('click', (event) => {
            if (event.target === dialog) dialog.close();
        });
        dialog.addEventListener('close', () => open.focus());
    }

    const collectionForm = document.querySelector('[data-collection-form]');
    const collectionTarget = document.querySelector('[data-collection-target]');
    if (collectionForm && collectionTarget) {
        collectionTarget.addEventListener('change', () => {
            collectionForm.action = `/colecoes/${encodeURIComponent(collectionTarget.value)}/`;
        });
    }

    const removeForms = document.querySelectorAll('[data-collection-remove-form]');
    if (!removeForms.length) return;

    let pendingForm = null;
    let pendingTrigger = null;
    const overlay = document.createElement('div');
    overlay.className = 'workspace-confirm-backdrop';
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-modal', 'true');
    overlay.setAttribute('aria-labelledby', 'collection-remove-title');
    overlay.setAttribute('aria-describedby', 'collection-remove-description');
    overlay.setAttribute('aria-hidden', 'true');
    overlay.inert = true;

    const panel = document.createElement('section');
    panel.className = 'workspace-confirm-dialog';
    panel.tabIndex = -1;
    const icon = document.createElement('span');
    icon.className = 'workspace-confirm-icon';
    icon.setAttribute('aria-hidden', 'true');
    icon.textContent = '!';
    const title = document.createElement('h2');
    title.id = 'collection-remove-title';
    title.textContent = 'Remover norma deste dossiê?';
    const description = document.createElement('p');
    description.id = 'collection-remove-description';
    const normName = document.createElement('strong');
    normName.dataset.collectionRemoveName = '';
    description.append(
        normName,
        document.createTextNode(' deixará de aparecer nesta coleção, mas continuará disponível no acervo.'),
    );
    const actions = document.createElement('div');
    actions.className = 'workspace-confirm-actions';
    const cancel = document.createElement('button');
    cancel.type = 'button';
    cancel.className = 'workspace-button workspace-button-secondary';
    cancel.dataset.collectionRemoveCancel = '';
    cancel.textContent = 'Manter na coleção';
    const confirm = document.createElement('button');
    confirm.type = 'button';
    confirm.className = 'workspace-button workspace-button-danger';
    confirm.dataset.collectionRemoveConfirm = '';
    confirm.textContent = 'Remover norma';
    actions.append(cancel, confirm);
    panel.append(icon, title, description, actions);
    overlay.append(panel);
    document.body.append(overlay);

    function closeRemoveDialog(restoreFocus = true) {
        overlay.classList.remove('is-open');
        overlay.setAttribute('aria-hidden', 'true');
        overlay.inert = true;
        const trigger = pendingTrigger;
        pendingForm = null;
        pendingTrigger = null;
        if (restoreFocus && trigger?.isConnected) trigger.focus();
    }

    function openRemoveDialog(form, trigger) {
        pendingForm = form;
        pendingTrigger = trigger;
        normName.textContent = trigger.dataset.collectionNorm || 'Esta norma';
        overlay.inert = false;
        overlay.setAttribute('aria-hidden', 'false');
        requestAnimationFrame(() => {
            overlay.classList.add('is-open');
            cancel.focus();
        });
    }

    cancel.addEventListener('click', () => closeRemoveDialog());
    overlay.addEventListener('click', (event) => {
        if (event.target === overlay) closeRemoveDialog();
    });
    overlay.addEventListener('keydown', (event) => {
        if (event.key === 'Escape') {
            event.preventDefault();
            closeRemoveDialog();
            return;
        }
        if (event.key !== 'Tab') return;
        const controls = [cancel, confirm].filter((control) => !control.disabled);
        if (!controls.length) return;
        if (event.shiftKey && document.activeElement === controls[0]) {
            event.preventDefault();
            controls.at(-1).focus();
        } else if (!event.shiftKey && document.activeElement === controls.at(-1)) {
            event.preventDefault();
            controls[0].focus();
        }
    });
    confirm.addEventListener('click', () => {
        const form = pendingForm;
        const submitter = pendingTrigger;
        if (!form?.isConnected) return closeRemoveDialog();
        form.dataset.collectionRemoveConfirmed = 'true';
        closeRemoveDialog(false);
        form.requestSubmit(submitter);
    });

    removeForms.forEach((form) => {
        form.addEventListener('submit', (event) => {
            if (form.dataset.collectionRemoveConfirmed === 'true') {
                delete form.dataset.collectionRemoveConfirmed;
                return;
            }
            const submitter = event.submitter || form.querySelector('button[type="submit"]');
            if (!submitter) return;
            event.preventDefault();
            openRemoveDialog(form, submitter);
        });
    });
})();
