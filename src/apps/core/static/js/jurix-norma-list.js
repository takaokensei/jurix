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
    const yearFilter = document.getElementById('norma-ano');
    const viewButtons = document.querySelectorAll('[data-norma-view]');
    const mobileFilterToggle = document.getElementById('norma-filter-toggle');
    const filterGrid = document.getElementById('norma-filter-grid');

    function submitSearchReset() {
        if (!filterForm || !search) return;
        // Exclude the cleared field so the URL returns to a genuinely clean query
        // while retaining type/year/order filters selected by the user.
        search.disabled = true;
        filterForm.requestSubmit();
    }

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

    function splitNormaIdentifier() {
        if (!search || !yearFilter) return;
        const match = search.value.trim().match(
            /^(?:(lei(?:\s+(?:complementar|ordin[áa]ria|org[âa]nica))?|decreto(?:-lei|\s+legislativo)?|resolu[cç][aã]o|portaria)\s*(?:n(?:[úu]mero|[º°.]?)\s*)?)?((?:\d{1,6}|\d{1,3}(?:\.\d{3})+))\s*\/\s*((?:19|20)\d{2})$/i,
        );
        if (!match) return;

        const number = match[2].replace(/\D/g, '');
        const yearOption = Array.from(yearFilter.options).find((option) => option.value === match[3]);
        if (!yearOption) return;

        const typeFilter = document.getElementById('norma-tipo');
        if (match[1] && typeFilter) {
            const canonical = (value) => value.normalize('NFD').replace(/[\u0300-\u036f]/g, '')
                .toLowerCase().replace(/\s+/g, ' ').trim()
                .replace(/^lei ordinaria$/, 'lei');
            const requestedType = canonical(match[1]);
            const matchingOption = Array.from(typeFilter.options).find((option) =>
                canonical(option.value) === requestedType || canonical(option.textContent) === requestedType,
            );
            if (!matchingOption || (typeFilter.value && typeFilter.value !== matchingOption.value)) return;
            typeFilter.value = matchingOption.value;
        }

        let exactReference = filterForm.querySelector('input[name="referencia_exata"]');
        if (!exactReference) {
            exactReference = document.createElement('input');
            exactReference.type = 'hidden';
            exactReference.name = 'referencia_exata';
            filterForm.appendChild(exactReference);
        }
        exactReference.value = '1';

        // The server searches the number field and year facet independently;
        // normalize dotted thousands and retain explicit type/year filters.
        search.value = number;
        yearFilter.value = match[3];
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
        search.addEventListener('input', () => {
            filterForm?.querySelector('input[name="referencia_exata"]')?.remove();
            syncClear();
        });
        search.addEventListener('keydown', (event) => {
            if (event.key === 'Escape' && search.value) {
                event.preventDefault();
                search.value = '';
                syncClear();
                submitSearchReset();
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
        clear.hidden = true;
        submitSearchReset();
    });

    mobileFilterToggle?.addEventListener('click', () => {
        if (!filterGrid) return;
        const open = filterGrid.classList.toggle('is-open');
        mobileFilterToggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    });

    filterForm?.addEventListener('submit', () => {
        splitNormaIdentifier();
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
