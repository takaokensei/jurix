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
        try { localStorage.setItem('jurix-theme', settings.theme || DEFAULTS.theme); } catch (_) {}
    }

    function initSidebar() {
        const sidebar = document.querySelector('[data-workspace-sidebar]');
        const toggle = document.querySelector('[data-workspace-toggle]');
        if (!sidebar || !toggle) return;
        const setOpen = (open, focusFirst = false) => {
            sidebar.classList.toggle('is-open', open);
            toggle.setAttribute('aria-expanded', String(open));
            toggle.setAttribute('aria-label', open ? 'Fechar menu' : 'Abrir menu');
            const hidden = window.innerWidth <= 900 && !open;
            sidebar.inert = hidden;
            sidebar.setAttribute('aria-hidden', String(hidden));
            if (open && focusFirst) sidebar.querySelector('a, button, [tabindex]:not([tabindex="-1"])')?.focus();
        };
        setOpen(false);
        toggle.addEventListener('click', () => setOpen(!sidebar.classList.contains('is-open'), !sidebar.classList.contains('is-open')));
        document.addEventListener('click', (event) => {
            if (window.innerWidth > 900 || !sidebar.classList.contains('is-open')) return;
            if (!sidebar.contains(event.target) && !toggle.contains(event.target)) setOpen(false);
        });
        document.addEventListener('keydown', (event) => {
            if (event.key === 'Escape' && sidebar.classList.contains('is-open')) {
                setOpen(false);
                toggle.focus();
            }
        });
        window.addEventListener('resize', () => {
            if (window.innerWidth > 900) setOpen(false);
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
            let saved = true;
            try {
                localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
            } catch (_) {
                saved = false;
            }
            applyAppearance(settings);
            const status = form.querySelector('[data-settings-status]');
            if (status) {
                status.classList.toggle('is-warning', !saved);
                status.textContent = saved
                    ? 'Preferências salvas neste navegador.'
                    : 'Preferências aplicadas, mas não foi possível salvá-las neste navegador.';
            }
            window.dispatchEvent(new CustomEvent('jurix:preferences-changed', { detail: settings }));
        });

        const reset = form.querySelector('[data-settings-reset]');
        reset?.addEventListener('click', () => {
            let removed = true;
            try {
                localStorage.removeItem(SETTINGS_KEY);
            } catch (_) {
                removed = false;
            }
            const configuredDefaultModel = modelField?.querySelector('option[selected]')?.value
                || modelField?.options[0]?.value
                || 'llama3';
            const resetSettings = { ...DEFAULTS, model: configuredDefaultModel };
            if (modelField) modelField.value = resetSettings.model;
            if (temperatureField) temperatureField.value = resetSettings.temperature;
            if (sourcesField) sourcesField.value = resetSettings.sources;
            const resetTheme = form.querySelector(`[name="theme"][value="${resetSettings.theme}"]`);
            const resetDensity = form.querySelector(`[name="density"][value="${resetSettings.density}"]`);
            if (resetTheme) resetTheme.checked = true;
            if (resetDensity) resetDensity.checked = true;
            applyAppearance(resetSettings);

            const status = form.querySelector('[data-settings-status]');
            if (status) {
                status.classList.toggle('is-warning', !removed);
                status.textContent = removed
                    ? 'Preferências padrão restauradas.'
                    : 'Padrões aplicados nesta página, mas não foi possível remover as preferências salvas. Elas podem voltar após recarregar.';
            }
            if (removed) window.location.reload();
        });
    }

    applyAppearance(readSettings());
    initSidebar();
    initSettings();
})();
