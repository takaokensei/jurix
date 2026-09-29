/**
 * Jurix Theme Management (Light / Dark Mode)
 *
 * Loaded as the FIRST script in <head> to prevent Flash of Unstyled Content (FOUC).
 * Handles system-preference detection, localStorage persistence and DOM toggling.
 */
(function () {
    'use strict';

    function getSystemThemePreference() {
        return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches
            ? 'dark'
            : 'light';
    }

    function getStoredTheme() {
        try {
            var preferences = JSON.parse(localStorage.getItem('jurix-preferences') || '{}');
            if (preferences && typeof preferences === 'object' && !Array.isArray(preferences)
                && ['dark', 'light', 'system'].includes(preferences.theme)) {
                return preferences.theme;
            }
        } catch (e) {}
        try {
            var legacyTheme = localStorage.getItem('jurix-theme');
            return ['dark', 'light', 'system'].includes(legacyTheme) ? legacyTheme : null;
        } catch (e) { return null; }
    }

    function resolveTheme(theme) {
        if (theme === 'system') return getSystemThemePreference();
        return theme === 'light' ? 'light' : 'dark';
    }

    function getStoredDensity() {
        try {
            var preferences = JSON.parse(localStorage.getItem('jurix-preferences') || '{}');
            if (preferences && typeof preferences === 'object' && !Array.isArray(preferences)
                && ['compact', 'comfortable'].includes(preferences.density)) {
                return preferences.density;
            }
        } catch (e) {}
        return 'comfortable';
    }

    function applyDensity() {
        document.documentElement.setAttribute('data-density', getStoredDensity());
    }

    function setTheme(theme) {
        var preference = ['dark', 'light', 'system'].includes(theme) ? theme : 'dark';
        var resolvedTheme = resolveTheme(preference);
        document.documentElement.setAttribute('data-theme', resolvedTheme);
        applyDensity();
        try {
            localStorage.setItem('jurix-theme', preference);
            var preferences = JSON.parse(localStorage.getItem('jurix-preferences') || '{}');
            if (preferences && typeof preferences === 'object' && !Array.isArray(preferences)) {
                preferences.theme = preference;
                localStorage.setItem('jurix-preferences', JSON.stringify(preferences));
            }
        } catch (e) {}

        // Sidebar toggle (workspace pages)
        var sidebarToggle = document.getElementById('theme-toggle');
        if (sidebarToggle) {
            sidebarToggle.setAttribute('aria-pressed', resolvedTheme === 'dark' ? 'true' : 'false');
        }
        // Navbar toggle (public/legacy pages)
        var navbarToggle = document.getElementById('theme-toggle-navbar');
        if (navbarToggle) {
            navbarToggle.setAttribute('aria-pressed', resolvedTheme === 'dark' ? 'true' : 'false');
        }
    }

    function toggleTheme() {
        var current = document.documentElement.getAttribute('data-theme') || 'light';
        setTheme(current === 'dark' ? 'light' : 'dark');
    }

    function initTheme() {
        var stored = getStoredTheme();
        var theme = stored || 'system';
        setTheme(theme);

        // Follow system preference when no manual override is stored.
        if (!stored && window.matchMedia) {
            window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', function (e) {
                if (!getStoredTheme()) { setTheme('system'); }
            });
        }
    }

    // ── Anti-FOUC: apply theme immediately before DOM paint ──
    var _stored = getStoredTheme();
    document.documentElement.setAttribute('data-theme', resolveTheme(_stored || 'system'));
    applyDensity();

    // ── Wire toggle buttons once DOM is ready ──
    function onReady() {
        initTheme();
        ['theme-toggle', 'theme-toggle-navbar'].forEach(function (id) {
            var btn = document.getElementById(id);
            if (btn) { btn.addEventListener('click', toggleTheme); }
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', onReady);
    } else {
        onReady();
    }

    // Expose globally so legacy onclick="toggleTheme()" still works.
    window.toggleTheme = toggleTheme;

    window.jurixTheme = { setTheme: setTheme, toggleTheme: toggleTheme, initTheme: initTheme };
})();

