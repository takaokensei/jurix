/**
 * Jurix Theme Management (Light / Dark Mode)
 * Handles system preferences, localStorage persistence, and DOM attribute toggling.
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
            return localStorage.getItem('jurix-theme');
        } catch (e) {
            return null;
        }
    }

    function setTheme(theme) {
        document.documentElement.setAttribute('data-theme', theme);
        try {
            localStorage.setItem('jurix-theme', theme);
        } catch (e) {
            // Storage unavailable
        }

        const toggle = document.getElementById('theme-toggle');
        if (toggle) {
            toggle.setAttribute('aria-pressed', theme === 'dark' ? 'true' : 'false');
        }
    }

    function toggleTheme() {
        const current = document.documentElement.getAttribute('data-theme') || 'light';
        const newTheme = current === 'dark' ? 'light' : 'dark';
        setTheme(newTheme);
    }

    function initTheme() {
        const stored = getStoredTheme();
        const theme = stored || getSystemThemePreference();
        setTheme(theme);

        if (!stored && window.matchMedia) {
            window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e) => {
                if (!getStoredTheme()) {
                    setTheme(e.matches ? 'dark' : 'light');
                }
            });
        }
    }

    // Attach listeners on load
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => {
            initTheme();
            const toggle = document.getElementById('theme-toggle');
            if (toggle) {
                toggle.addEventListener('click', toggleTheme);
            }
        });
    } else {
        initTheme();
        const toggle = document.getElementById('theme-toggle');
        if (toggle) {
            toggle.addEventListener('click', toggleTheme);
        }
    }

    window.jurixTheme = {
        setTheme,
        toggleTheme,
        initTheme,
    };
})();
