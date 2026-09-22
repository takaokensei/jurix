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
            'href', 'title', 'target', 'rel', 'class', 'data-source-index', 'aria-label',
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

    function normalizeLists(markdown) {
        return String(markdown || '')
            .replace(/([•\-])\s+([^•\n]+?);\s+([•\-])/g, '$1 $2\n$3')
            .replace(/([•\-])\s+([^•\n]+?)\s+([•\-])\s+/g, '$1 $2\n$3 ')
            .replace(/;\s+([•\-])/g, '\n$1')
            .replace(/([^\n])([•\-])\s+/g, '$1\n$2 ')
            .replace(/\n{3,}/g, '\n\n');
    }

    function transformLegalBlocks(markdown) {
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
                return `<a class="jurix-citation" href="#jurix-evidence-${index}" data-source-index="${index}" aria-label="Ver fonte ${index}">[${index}]</a>`;
            });
        }).join('\n');
    }

    function normalize(markdown) {
        return transformLegalBlocks(normalizeLists(markdown));
    }

    function render(markdown) {
        const source = normalize(markdown);
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
