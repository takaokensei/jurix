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
})();
