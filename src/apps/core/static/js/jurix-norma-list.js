/*
 * Jurix Norma Library interactions
 * - remembers grid/list preference per browser
 * - clear/search shortcut
 * - mobile-friendly filter state
 * - preserves native server-side pagination and accessibility
 */
(function () {
    'use strict';

    const STORAGE_KEY = 'jurix:norma-view:v2';
    const list = document.getElementById('jurix-norma-list');
    const search = document.getElementById('norma-search-input');
    const clear = document.getElementById('norma-search-clear');
    const filterForm = document.getElementById('norma-filter-form');
    const viewButtons = document.querySelectorAll('[data-norma-view]');
    const mobileFilterToggle = document.getElementById('norma-filter-toggle');
    const filterGrid = document.getElementById('norma-filter-grid');

    function setView(view, persist = true) {
        if (!list || !['grid', 'list'].includes(view)) return;
        list.classList.toggle('is-list', view === 'list');
        viewButtons.forEach((button) => {
            button.setAttribute('aria-pressed', button.dataset.normaView === view ? 'true' : 'false');
        });
        if (persist) {
            try { localStorage.setItem(STORAGE_KEY, view); } catch (_) {}
        }
    }

    function initialView() {
        try {
            const stored = localStorage.getItem(STORAGE_KEY);
            if (stored === 'list' || stored === 'grid') return stored;
        } catch (_) {}
        return window.matchMedia('(max-width: 860px)').matches ? 'list' : 'grid';
    }

    viewButtons.forEach((button) => {
        button.addEventListener('click', () => setView(button.dataset.normaView));
    });
    setView(initialView(), false);

    // Respect user motion preferences if smooth animations or transitions are triggered
    const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    if (search) {
        const syncClear = () => {
            if (!clear) return;
            clear.hidden = !search.value.trim();
        };
        search.addEventListener('input', syncClear);
        search.addEventListener('keydown', (event) => {
            if (event.key === 'Escape' && search.value) {
                event.preventDefault();
                search.value = '';
                syncClear();
                search.focus();
            }
            if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
                event.preventDefault();
                search.focus();
                search.select();
            }
        });
        syncClear();
    }

    clear?.addEventListener('click', () => {
        if (!search) return;
        search.value = '';
        search.focus();
        clear.hidden = true;
    });

    mobileFilterToggle?.addEventListener('click', () => {
        if (!filterGrid) return;
        const open = filterGrid.classList.toggle('is-open');
        mobileFilterToggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    });

    filterForm?.addEventListener('submit', () => {
        const button = filterForm.querySelector('button[type="submit"]');
        if (button) {
            button.setAttribute('aria-busy', 'true');
            button.dataset.originalText = button.textContent;
            button.textContent = 'Buscando…';
        }
    });

    // Keep focus on the first result after server-rendered searches when requested
    // by a query parameter. This is useful for keyboard users and does not disturb
    // ordinary navigation.
    try {
        const params = new URLSearchParams(window.location.search);
        if (params.has('q') && list) {
            window.requestAnimationFrame(() => {
                const firstLink = list.querySelector('.jurix-norma-card-link');
                if (firstLink && window.location.hash === '#resultados') firstLink.focus();
            });
        }
    } catch (_) {}
})();
