(() => {
    'use strict';
    const focusHashTarget = () => {
        const target = window.location.hash ? document.querySelector(window.location.hash) : null;
        if (!target) return;
        target.classList.add('is-deep-linked');
        target.focus({ preventScroll: true });
        target.scrollIntoView({ block: 'center', behavior: 'smooth' });
        window.setTimeout(() => target.classList.remove('is-deep-linked'), 1800);
    };
    window.addEventListener('hashchange', focusHashTarget);
    window.addEventListener('DOMContentLoaded', focusHashTarget, { once: true });
    focusHashTarget();
    const writeClipboard = (value) => {
        if (navigator.clipboard?.writeText) return navigator.clipboard.writeText(value);
        const textarea = document.createElement('textarea');
        textarea.value = value;
        textarea.setAttribute('readonly', '');
        textarea.className = 'jurix-copy-fallback';
        document.body.appendChild(textarea);
        textarea.select();
        const copied = document.execCommand('copy');
        textarea.remove();
        return copied ? Promise.resolve() : Promise.reject(new Error('copy failed'));
    };
    document.addEventListener('click', (event) => {
        const citationButton = event.target.closest('[data-copy-citation]');
        if (citationButton) {
            const citation = citationButton.dataset.copyCitation || '';
            writeClipboard(citation).then(() => {
                citationButton.dataset.originalLabel ||= citationButton.textContent;
                citationButton.textContent = 'Citação copiada';
                citationButton.classList.add('is-copied');
                window.setTimeout(() => {
                    citationButton.textContent = citationButton.dataset.originalLabel || 'Copiar citação';
                    citationButton.classList.remove('is-copied');
                }, 1800);
            }).catch(() => {
                citationButton.textContent = 'Selecione e copie manualmente';
                window.setTimeout(() => { citationButton.textContent = 'Copiar citação'; }, 2200);
            });
            return;
        }
        const trigger = event.target.closest('[data-expand-device]');
        if (!trigger) return;
        const text = trigger.previousElementSibling;
        const preview = text?.querySelector('[data-device-text-preview]');
        const full = text?.querySelector('[data-device-text-full]');
        if (!preview || !full) return;
        const expanded = trigger.getAttribute('aria-expanded') !== 'true';
        preview.hidden = expanded;
        full.hidden = !expanded;
        trigger.setAttribute('aria-expanded', String(expanded));
        trigger.textContent = expanded ? 'Recolher texto' : 'Ver texto completo';
    });
})();
