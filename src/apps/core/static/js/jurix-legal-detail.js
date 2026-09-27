(() => {
    'use strict';
    document.addEventListener('click', (event) => {
        const trigger = event.target.closest('[data-expand-device]');
        if (!trigger) return;
        const text = trigger.previousElementSibling;
        if (text) text.classList.add('is-expanded');
        trigger.hidden = true;
    });
})();
