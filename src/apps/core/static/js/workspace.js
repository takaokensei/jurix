(function () {
    'use strict';

    const SETTINGS_KEY = 'jurix-preferences';
    const DEFAULTS = {
        model: document.querySelector('[name="model"]')?.value || 'llama3',
        temperature: 0.3,
        sources: 5,
        theme: 'dark',
        density: 'comfortable',
    };

    function readSettings() {
        try {
            return { ...DEFAULTS, ...JSON.parse(localStorage.getItem(SETTINGS_KEY) || '{}') };
        } catch (_) {
            return { ...DEFAULTS };
        }
    }

    function applyAppearance(settings) {
        const theme = settings.theme === 'system'
            ? (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
            : settings.theme;
        document.documentElement.setAttribute('data-theme', theme);
        document.documentElement.setAttribute('data-density', settings.density || DEFAULTS.density);
    }

    function initSidebar() {
        const sidebar = document.querySelector('[data-workspace-sidebar]');
        const toggle = document.querySelector('[data-workspace-toggle]');
        if (!sidebar || !toggle) return;
        toggle.addEventListener('click', () => sidebar.classList.toggle('is-open'));
        document.addEventListener('click', (event) => {
            if (window.innerWidth > 900 || !sidebar.classList.contains('is-open')) return;
            if (!sidebar.contains(event.target) && !toggle.contains(event.target)) sidebar.classList.remove('is-open');
        });
    }

    function initSettings() {
        const form = document.querySelector('[data-settings-form]');
        if (!form) return;

        const defaults = { ...DEFAULTS, ...readSettings() };
        const modelField = form.querySelector('[name="model"]');
        const temperatureField = form.querySelector('[name="temperature"]');
        const sourcesField = form.querySelector('[name="sources"]');
        if (modelField) modelField.value = defaults.model;
        if (temperatureField) temperatureField.value = defaults.temperature;
        if (sourcesField) sourcesField.value = defaults.sources;
        const themeField = form.querySelector(`[name="theme"][value="${defaults.theme}"]`);
        const densityField = form.querySelector(`[name="density"][value="${defaults.density}"]`);
        if (themeField) themeField.checked = true;
        if (densityField) densityField.checked = true;
        applyAppearance(defaults);

        form.addEventListener('submit', (event) => {
            event.preventDefault();
            const formData = new FormData(form);
            const settings = {
                model: String(formData.get('model') || DEFAULTS.model),
                temperature: Math.max(0, Math.min(1, Number(formData.get('temperature') || DEFAULTS.temperature))),
                sources: Math.max(1, Math.min(10, Number(formData.get('sources') || DEFAULTS.sources))),
                theme: String(formData.get('theme') || DEFAULTS.theme),
                density: String(formData.get('density') || DEFAULTS.density),
            };
            try {
                localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
            } catch (_) {}
            applyAppearance(settings);
            const status = form.querySelector('[data-settings-status]');
            if (status) status.textContent = 'Preferências salvas neste navegador.';
            window.dispatchEvent(new CustomEvent('jurix:preferences-changed', { detail: settings }));
        });

        const reset = form.querySelector('[data-settings-reset]');
        reset?.addEventListener('click', () => {
            try {
                localStorage.removeItem(SETTINGS_KEY);
            } catch (_) {}
            Object.assign(DEFAULTS, { model: modelField?.options[0]?.value || 'llama3' });
            window.location.reload();
        });
    }

    applyAppearance(readSettings());
    initSidebar();
    initSettings();
})();
