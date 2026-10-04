(() => {
    'use strict';

    const form = document.querySelector('.historical-date-form');
    if (!form) return;

    const defaults = {
        from_as_of: form.dataset.defaultFrom || '',
        to_as_of: form.dataset.defaultTo || '',
    };

    const syncDatesFromUrl = () => {
        const params = new URL(window.location.href).searchParams;
        for (const [name, fallback] of Object.entries(defaults)) {
            const input = form.elements.namedItem(name);
            if (!input) continue;
            input.value = params.has(name) ? params.get(name) : fallback;
        }
    };

    window.addEventListener('pageshow', syncDatesFromUrl);
    window.addEventListener('popstate', syncDatesFromUrl);
    syncDatesFromUrl();
})();
