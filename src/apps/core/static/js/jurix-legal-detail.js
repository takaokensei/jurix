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
    document.addEventListener('click', (event) => {
        const trigger = event.target.closest('[data-expand-device]');
        if (!trigger) return;
        const text = trigger.previousElementSibling;
        if (text) text.classList.add('is-expanded');
        trigger.hidden = true;
    });
})();
