/* Jurix Legal Markdown — Phase 4 */
(function () {
    'use strict';

    const SANITIZE_CONFIG = {
        ALLOWED_TAGS: [
            'p', 'br', 'strong', 'em', 'b', 'i', 'u', 's', 'del',
            'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
            'ul', 'ol', 'li', 'blockquote', 'code', 'pre',
            'table', 'thead', 'tbody', 'tr', 'th', 'td',
            'a', 'hr', 'span', 'div',
        ],
        ALLOWED_ATTR: [
            'href', 'title', 'target', 'rel', 'class', 'data-source-index', 'data-citation-id', 'aria-label', 'align',
        ],
        FORBID_TAGS: [
            'img', 'picture', 'source', 'video', 'audio', 'track', 'image', 'use', 'svg', 'math',
            'style', 'link', 'form', 'input', 'button', 'textarea', 'select', 'iframe', 'object', 'embed',
        ],
        FORBID_ATTR: [
            'style', 'srcset', 'poster', 'background', 'ping',
            'onclick', 'onerror', 'onload', 'onmouseover', 'onfocus', 'onblur',
        ],
        ALLOW_UNKNOWN_PROTOCOLS: false,
    };

    const CALLOUTS = {
        'VIGÊNCIA': { className: 'vigencia', label: 'Vigência' },
        'ATENÇÃO': { className: 'atencao', label: 'Atenção' },
        'REVOGAÇÃO': { className: 'revogacao', label: 'Revogação' },
        'JURISPRUDÊNCIA': { className: 'jurisprudencia', label: 'Jurisprudência' },
    };

    function escapeHtml(value) {
        return String(value ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    function sourceForCitation(sources, index) {
        const rows = Array.isArray(sources) ? sources : [];
        const exact = rows.find((item) => Number(item?.citation_index) === index);
        if (exact) return exact;
        // Legacy history without indices relies on the original array-order contract.
        if (!rows.some((item) => Number.isInteger(Number(item?.citation_index)))) {
            return rows[index - 1] || null;
        }
        return null;
    }

    function normalizeLists(markdown) {
        return String(markdown || '')
            .replace(/(•)\s+([^•\n]+?);\s+(•)/g, '$1 $2\n$3')
            .replace(/(•)\s+([^•\n]+?)\s+(•)\s+/g, '$1 $2\n$3 ')
            .replace(/;\s+(•)/g, '\n$1')
            .replace(/([^\n])•\s+/g, '$1\n• ')
            .replace(/\n{3,}/g, '\n\n');
    }

    function transformLegalBlocks(markdown, sources = []) {
        const lines = String(markdown || '').split('\n');
        let inFence = false;

        return lines.map((line) => {
            if (/^\s*```/.test(line)) {
                inFence = !inFence;
                return line;
            }
            if (inFence) return line;

            const calloutMatch = line.match(/^\s*(?:>\s*)?\[\s*(VIGÊNCIA|ATENÇÃO|REVOGAÇÃO|JURISPRUDÊNCIA)\s*\]\s*(.*)$/i);
            if (calloutMatch) {
                const key = calloutMatch[1].toUpperCase();
                const definition = CALLOUTS[key];
                const body = escapeHtml(calloutMatch[2]);
                return `<blockquote class="jurix-callout jurix-callout--${definition.className}"><strong>${definition.label}</strong><span>${body}</span></blockquote>`;
            }

            return line.replace(/\[\[(\d{1,3})\]\]/g, (full, sourceIndex) => {
                const index = Number.parseInt(sourceIndex, 10);
                if (!index || index > 999) return full;
                const source = sourceForCitation(sources, index);
                if (!source) return full;
                const label = source?.citation_label || `Fonte ${index}`;
                const citationId = source?.citation_id ? ` data-citation-id="${escapeHtml(source.citation_id)}"` : '';
                return `<a class="jurix-citation" href="#jurix-evidence-${index}" data-source-index="${index}"${citationId} aria-label="Ver ${escapeHtml(label)}">[${index}]</a>`;
            });
        }).join('\n');
    }

    function normalize(markdown, sources = []) {
        return transformLegalBlocks(normalizeLists(markdown), sources);
    }

    function render(markdown, sources = []) {
        const source = normalize(markdown, sources);
        if (typeof marked === 'undefined' || typeof DOMPurify === 'undefined') {
            return `<p>${escapeHtml(source)}</p>`;
        }
        return DOMPurify.sanitize(marked.parse(source), SANITIZE_CONFIG);
    }

    window.JurixMarkdown = {
        normalize,
        render,
    };
})();
