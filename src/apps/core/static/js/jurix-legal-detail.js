(() => {
    'use strict';
    const enhanceDeviceIndex = () => {
        const index = document.querySelector('[data-device-index]');
        if (!index) return;
        const links = [...index.querySelectorAll('[data-device-index-link]')];
        const nodes = new Map([...document.querySelectorAll('.dispositivo-node[id]')].map((node) => [node.id, node]));
        const linkByNode = new Map(links.map((link) => [link.hash.slice(1), link]));
        const articleIds = new Set([...nodes.values()]
            .filter((node) => node.dataset.deviceType === 'artigo' && !node.dataset.deviceParentId)
            .map((node) => node.id));
        const childrenByArticle = new Map([...articleIds].map((id) => [id, []]));
        const standalone = [];

        links.forEach((link) => {
            const targetId = link.hash.slice(1);
            const target = nodes.get(targetId);
            if (!target) {
                standalone.push(link);
                return;
            }
            if (articleIds.has(targetId)) return;
            let parentId = target.dataset.deviceParentId;
            const visited = new Set();
            let articleId = '';
            while (parentId && !visited.has(parentId)) {
                visited.add(parentId);
                const parent = nodes.get(`dispositivo-${parentId}`);
                if (!parent) break;
                if (articleIds.has(parent.id)) {
                    articleId = parent.id;
                    break;
                }
                parentId = parent.dataset.deviceParentId;
            }
            if (articleId && articleId !== targetId) childrenByArticle.get(articleId).push(link);
            else standalone.push(link);
        });

        const fragment = document.createDocumentFragment();
        articleIds.forEach((articleId) => {
            const rootLink = linkByNode.get(articleId);
            if (!rootLink) return;
            const group = document.createElement('div');
            group.className = 'dispositivos-index-group';
            group.append(rootLink);
            const children = childrenByArticle.get(articleId) || [];
            if (children.length) {
                const disclosure = document.createElement('details');
                disclosure.className = 'dispositivos-index-disclosure';
                disclosure.dataset.deviceIndexGroup = articleId;
                const summary = document.createElement('summary');
                summary.textContent = `Dispositivos de ${rootLink.textContent.trim()} (${children.length})`;
                const childLinks = document.createElement('div');
                childLinks.className = 'dispositivos-index-children';
                children.forEach((link) => {
                    const normalizedIdentifier = link.textContent.replace(/\s*>\s*/g, ', ');
                    link.textContent = normalizedIdentifier;
                    link.setAttribute('aria-label', normalizedIdentifier);
                    childLinks.append(link);
                });
                disclosure.append(summary, childLinks);
                group.append(disclosure);
            }
            fragment.append(group);
        });
        standalone.forEach((link) => fragment.append(link));
        index.replaceChildren(fragment);
    };

    const focusHashTarget = () => {
        const hash = window.location.hash;
        if (!hash) return;
        const indexLink = [...document.querySelectorAll('[data-device-index-link]')]
            .find((link) => link.hash === hash);
        indexLink?.closest('[data-device-index-group]')?.setAttribute('open', '');
        const target = document.getElementById(hash.slice(1));
        if (!target) return;
        target.classList.add('is-deep-linked');
        target.focus({ preventScroll: true });
        target.scrollIntoView({ block: 'center', behavior: 'smooth' });
        window.setTimeout(() => target.classList.remove('is-deep-linked'), 1800);
    };
    window.addEventListener('hashchange', focusHashTarget);
    window.addEventListener('DOMContentLoaded', focusHashTarget, { once: true });
    enhanceDeviceIndex();
    focusHashTarget();
    document.querySelectorAll('[data-device-text-preview], [data-device-text-full]').forEach((element) => {
        element.textContent = element.textContent.trim();
    });
    const writeClipboard = (value) => {
        if (navigator.clipboard?.writeText) return navigator.clipboard.writeText(value);
        const textarea = document.createElement('textarea');
        textarea.value = value;
        textarea.setAttribute('readonly', '');
        textarea.className = 'jurix-copy-fallback';
        document.body.appendChild(textarea);
        textarea.select();
        const copied = document.execCommand('copy');
        textarea.remove();
        return copied ? Promise.resolve() : Promise.reject(new Error('copy failed'));
    };
    document.addEventListener('click', (event) => {
        const citationButton = event.target.closest('[data-copy-citation]');
        if (citationButton) {
            const citation = citationButton.dataset.copyCitation || '';
            writeClipboard(citation).then(() => {
                citationButton.dataset.originalLabel ||= citationButton.textContent;
                citationButton.textContent = 'Citação copiada';
                citationButton.classList.add('is-copied');
                window.setTimeout(() => {
                    citationButton.textContent = citationButton.dataset.originalLabel || 'Copiar citação';
                    citationButton.classList.remove('is-copied');
                }, 1800);
            }).catch(() => {
                citationButton.textContent = 'Selecione e copie manualmente';
                window.setTimeout(() => { citationButton.textContent = 'Copiar citação'; }, 2200);
            });
            return;
        }
        const trigger = event.target.closest('[data-expand-device]');
        if (!trigger) return;
        const text = trigger.previousElementSibling;
        const preview = text?.querySelector('[data-device-text-preview]');
        const full = text?.querySelector('[data-device-text-full]');
        if (!preview || !full) return;
        const expanded = trigger.getAttribute('aria-expanded') !== 'true';
        preview.hidden = expanded;
        full.hidden = !expanded;
        trigger.setAttribute('aria-expanded', String(expanded));
        trigger.textContent = expanded ? 'Recolher texto' : 'Ver texto completo';
    });
})();
