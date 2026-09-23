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
        try { return localStorage.getItem('jurix-theme'); } catch (e) { return null; }
    }

    function setTheme(theme) {
        document.documentElement.setAttribute('data-theme', theme);
        try { localStorage.setItem('jurix-theme', theme); } catch (e) {}

        // Sidebar toggle (workspace pages)
        var sidebarToggle = document.getElementById('theme-toggle');
        if (sidebarToggle) {
            sidebarToggle.setAttribute('aria-pressed', theme === 'dark' ? 'true' : 'false');
        }
        // Navbar toggle (public/legacy pages)
        var navbarToggle = document.getElementById('theme-toggle-navbar');
        if (navbarToggle) {
            navbarToggle.setAttribute('aria-pressed', theme === 'dark' ? 'true' : 'false');
        }
    }

    function toggleTheme() {
        var current = document.documentElement.getAttribute('data-theme') || 'light';
        setTheme(current === 'dark' ? 'light' : 'dark');
    }

    function initTheme() {
        var stored = getStoredTheme();
        var theme = stored || getSystemThemePreference();
        setTheme(theme);

        // Follow system preference when no manual override is stored.
        if (!stored && window.matchMedia) {
            window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', function (e) {
                if (!getStoredTheme()) { setTheme(e.matches ? 'dark' : 'light'); }
            });
        }
    }

    // ── Anti-FOUC: apply theme immediately before DOM paint ──
    var _stored = getStoredTheme();
    var _dark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
    document.documentElement.setAttribute('data-theme', _stored || (_dark ? 'dark' : 'light'));

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

