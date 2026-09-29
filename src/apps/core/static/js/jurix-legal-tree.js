(() => {
    'use strict';

    const tree = document.querySelector('[role="tree"]');
    if (!tree) return;

    const items = () => Array.from(tree.querySelectorAll('[role="treeitem"]'));
    const visibleItems = () => items().filter((item) => !item.closest('[role="group"][hidden]'));
    const childGroup = (item) => Array.from(item.children)
        .find((child) => child.classList.contains('tree-node-children')) || null;
    const toggleButton = (item) => item.querySelector(':scope > .node-header [data-tree-toggle]');
    const itemLabel = (item) => item.querySelector(':scope > .node-header .node-title')?.textContent.trim() || 'dispositivo';

    const updateExpanded = (item, expanded) => {
        const group = childGroup(item);
        const button = toggleButton(item);
        if (!group || !button) return false;

        group.hidden = !expanded;
        item.setAttribute('aria-expanded', String(expanded));
        button.setAttribute('aria-expanded', String(expanded));
        button.setAttribute('aria-label', `${expanded ? 'Recolher' : 'Expandir'} ${itemLabel(item)}`);
        return true;
    };

    const focusItem = (item) => {
        if (!item) return;
        items().forEach((candidate) => candidate.setAttribute('tabindex', candidate === item ? '0' : '-1'));
        item.focus();
    };

    const firstChild = (item) => childGroup(item)?.querySelector(':scope > [role="treeitem"]') || null;
    const parentItem = (item) => item.parentElement.closest('[role="treeitem"]');

    items().forEach((item) => {
        const group = childGroup(item);
        if (group) updateExpanded(item, !group.hidden);
    });
    const initialItem = visibleItems()[0];
    if (initialItem) initialItem.setAttribute('tabindex', '0');

    tree.addEventListener('click', (event) => {
        const button = event.target.closest('[data-tree-toggle]');
        if (!button || !tree.contains(button)) return;
        const item = button.closest('[role="treeitem"]');
        const expanded = item?.getAttribute('aria-expanded') === 'true';
        if (item && updateExpanded(item, !expanded)) focusItem(item);
    });

    tree.addEventListener('keydown', (event) => {
        const current = event.target.closest('[role="treeitem"]');
        if (!current || !tree.contains(current)) return;

        const visible = visibleItems();
        const index = visible.indexOf(current);
        const group = childGroup(current);
        const isExpanded = current.getAttribute('aria-expanded') === 'true';

        switch (event.key) {
        case 'ArrowDown':
            event.preventDefault();
            focusItem(visible[Math.min(index + 1, visible.length - 1)]);
            break;
        case 'ArrowUp':
            event.preventDefault();
            focusItem(visible[Math.max(index - 1, 0)]);
            break;
        case 'Home':
            event.preventDefault();
            focusItem(visible[0]);
            break;
        case 'End':
            event.preventDefault();
            focusItem(visible[visible.length - 1]);
            break;
        case 'ArrowRight':
            if (!group) break;
            event.preventDefault();
            if (!isExpanded) updateExpanded(current, true);
            else focusItem(firstChild(current));
            break;
        case 'ArrowLeft':
            if (group && isExpanded) {
                event.preventDefault();
                updateExpanded(current, false);
            } else {
                const parent = parentItem(current);
                if (parent) {
                    event.preventDefault();
                    focusItem(parent);
                }
            }
            break;
        case 'Enter':
        case ' ':
            if (group && !event.target.closest('[data-tree-toggle]')) {
                event.preventDefault();
                updateExpanded(current, !isExpanded);
            }
            break;
        default:
            break;
        }
    });
})();
