(function () {
    'use strict';

    const list = document.getElementById('archive-candidates-list');
    const search = document.getElementById('archive-candidate-search');
    const identity = document.getElementById('archive-candidate-identity');
    const status = document.getElementById('archive-candidate-status');
    const extraction = document.getElementById('archive-candidate-extraction');
    const summary = document.getElementById('archive-candidate-filter-summary');
    const empty = document.getElementById('archive-candidates-no-results');
    if (!list || !search || !identity || !status || !extraction || !summary || !empty) return;

    const cards = Array.from(list.querySelectorAll('.jurix-archive-candidate'));
    const fold = (value) => String(value || '')
        .normalize('NFD')
        .replace(/[\u0300-\u036f]/g, '')
        .toLocaleLowerCase('pt-BR')
        // Legal identifiers are commonly entered with thousands separators
        // (e.g. 7.795/2005), while archive filenames and labels may use 7795.
        .replace(/(?<=\d)\.(?=\d)/g, '')
        .trim();

    function applyFilters() {
        const terms = fold(search.value).split(/\s+/).filter(Boolean);
        const identityValue = identity.value;
        const statusValue = status.value;
        const extractionValue = extraction.value;
        let visible = 0;

        cards.forEach((card) => {
            const searchableText = fold(card.dataset.search);
            const matches = (!terms.length || terms.every((term) => searchableText.includes(term)))
                && (identityValue === 'all' || card.dataset.identity === identityValue)
                && (statusValue === 'all' || card.dataset.reviewStatus === statusValue)
                && (extractionValue === 'all' || card.dataset.extractionStatus === extractionValue);
            card.hidden = !matches;
            if (matches) visible += 1;
        });

        summary.textContent = `Exibindo ${visible} de ${cards.length} documentos.`;
        empty.hidden = visible !== 0;
    }

    search.addEventListener('input', applyFilters);
    identity.addEventListener('change', applyFilters);
    status.addEventListener('change', applyFilters);
    extraction.addEventListener('change', applyFilters);
    applyFilters();
})();
