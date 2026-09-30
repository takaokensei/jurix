(function () {
    'use strict';

    const SETTINGS_KEY = 'jurix-preferences';
    const SIDEBAR_COLLAPSED_KEY = 'jurix-sidebar-collapsed';
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
        const shell = sidebar.closest('.workspace-shell');
        const isMobile = () => window.innerWidth <= 900;
        const readCollapsed = () => {
            try { return localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === 'true'; } catch (_) { return false; }
        };
        const setCollapsed = (collapsed) => {
            shell?.classList.toggle('is-sidebar-collapsed', collapsed);
            document.documentElement.setAttribute('data-sidebar-collapsed', String(collapsed));
            toggle.setAttribute('aria-expanded', String(!collapsed));
            toggle.setAttribute('aria-label', collapsed ? 'Expandir navegação' : 'Recolher navegação');
            toggle.title = collapsed ? 'Expandir navegação' : 'Recolher navegação';
            sidebar.inert = false;
            sidebar.setAttribute('aria-hidden', 'false');
            try { localStorage.setItem(SIDEBAR_COLLAPSED_KEY, String(collapsed)); } catch (_) {}
        };
        const setOpen = (open, focusFirst = false) => {
            sidebar.classList.toggle('is-open', open);
            toggle.setAttribute('aria-expanded', String(open));
            toggle.setAttribute('aria-label', open ? 'Fechar menu' : 'Abrir menu');
            toggle.title = open ? 'Fechar menu' : 'Abrir menu';
            const hidden = isMobile() && !open;
            sidebar.inert = hidden;
            sidebar.setAttribute('aria-hidden', String(hidden));
            if (open && focusFirst) sidebar.querySelector('a, button, [tabindex]:not([tabindex="-1"])')?.focus();
        };
        if (isMobile()) {
            document.documentElement.setAttribute('data-sidebar-collapsed', 'false');
            setOpen(false);
        }
        else setCollapsed(readCollapsed());
        toggle.addEventListener('click', () => {
            if (isMobile()) {
                const opening = !sidebar.classList.contains('is-open');
                setOpen(opening, opening);
                return;
            }
            setCollapsed(!shell?.classList.contains('is-sidebar-collapsed'));
        });
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
            setOpen(false);
            if (!isMobile()) setCollapsed(readCollapsed());
            else document.documentElement.setAttribute('data-sidebar-collapsed', 'false');
        });
    }

    function initSettings() {
        const form = document.querySelector('[data-settings-form]');
        if (!form) return;

        const defaults = { ...DEFAULTS, ...readSettings() };
        const modelField = form.querySelector('[name="model"]');
        const temperatureField = form.querySelector('[name="temperature"]');
        const sourcesField = form.querySelector('[name="sources"]');
        const providerField = form.querySelector('[name="llm_provider"]');
        const providerStorageKey = 'jurix-llm-session-config';
        const externalModelField = form.querySelector('[name="external_model"]');
        const endpointField = form.querySelector('[name="llm_endpoint"]');
        const apiKeyField = form.querySelector('[name="llm_api_key"]');
        let providerSettings = {};
        try { providerSettings = JSON.parse(sessionStorage.getItem(providerStorageKey) || '{}'); } catch (_) {}
        if (providerField && providerSettings.provider) providerField.value = providerSettings.provider;
        if (externalModelField) externalModelField.value = providerSettings.model || '';
        if (endpointField) endpointField.value = providerSettings.endpoint || '';
        if (apiKeyField) apiKeyField.value = providerSettings.api_key || '';
        const updateProviderFields = () => {
            const external = providerField?.value && providerField.value !== 'ollama';
            form.querySelectorAll('[data-external-llm-field]').forEach(field => { field.hidden = !external; });
            form.querySelectorAll('[data-compatible-endpoint-field]').forEach(field => { field.hidden = providerField?.value !== 'compatible'; });
            const ollamaField = form.querySelector('[data-ollama-model]')?.closest('.workspace-field');
            if (ollamaField) ollamaField.hidden = Boolean(external);
        };
        providerField?.addEventListener('change', updateProviderFields);
        updateProviderFields();
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
            const selectedProvider = String(formData.get('llm_provider') || 'ollama');
            const providerConfig = selectedProvider === 'ollama' ? { provider: 'ollama' } : {
                provider: selectedProvider,
                model: String(formData.get('external_model') || '').trim(),
                endpoint: String(formData.get('llm_endpoint') || '').trim(),
                api_key: String(formData.get('llm_api_key') || '').trim(),
            };
            const status = form.querySelector('[data-settings-status]');
            if (selectedProvider !== 'ollama' && (!providerConfig.model || !providerConfig.api_key || (selectedProvider === 'compatible' && !providerConfig.endpoint))) {
                if (status) {
                    status.classList.add('is-warning');
                    status.textContent = 'Informe modelo, chave de API e, para endpoint compatível, a URL local.';
                }
                (externalModelField?.value ? apiKeyField : externalModelField)?.focus();
                return;
            }
            let saved = true;
            try {
                localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
            } catch (_) {
                saved = false;
            }
            applyAppearance(settings);
            try { sessionStorage.setItem(providerStorageKey, JSON.stringify(providerConfig)); } catch (_) { saved = false; }
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
                sessionStorage.removeItem(providerStorageKey);
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

    document.addEventListener('click', (event) => {
        const link = event.target.closest?.('a[href]');
        if (!link || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
        const target = new URL(link.href, window.location.href);
        if (target.origin === window.location.origin && target.pathname.replace(/\/$/, '') === window.location.pathname.replace(/\/$/, '') && target.search === window.location.search && !target.hash) event.preventDefault();
    });

    applyAppearance(readSettings());
    initSidebar();
    initSettings();
})();
