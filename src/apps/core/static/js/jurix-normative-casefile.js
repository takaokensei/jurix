(() => {
  const tablist = document.querySelector('[data-casefile-tabs]');
  if (!tablist) return;

  const tabs = Array.from(tablist.querySelectorAll('a[href^="#"]'));
  const entries = tabs
    .map((tab) => ({ tab, panel: document.getElementById(decodeURIComponent(tab.hash.slice(1))) }))
    .filter(({ panel }) => panel?.hasAttribute('data-casefile-panel'));
  if (!entries.length) return;

  tablist.setAttribute('role', 'tablist');
  tablist.setAttribute('aria-orientation', 'horizontal');

  entries.forEach(({ tab, panel }, index) => {
    tab.id = tab.id || `casefile-tab-${index + 1}`;
    tab.setAttribute('role', 'tab');
    tab.setAttribute('aria-controls', panel.id);
    panel.setAttribute('role', 'tabpanel');
    panel.setAttribute('aria-labelledby', tab.id);
    panel.setAttribute('tabindex', '0');
  });

  function activate(selected, { focus = false, updateHash = true } = {}) {
    entries.forEach(({ tab, panel }) => {
      const active = tab === selected;
      tab.setAttribute('aria-selected', String(active));
      tab.tabIndex = active ? 0 : -1;
      panel.hidden = !active;
    });

    if (updateHash && window.location.hash !== selected.hash) {
      window.history.replaceState(null, '', `${window.location.pathname}${window.location.search}${selected.hash}`);
    }
    if (focus) selected.focus();
  }

  tablist.addEventListener('click', (event) => {
    const tab = event.target.closest('[role="tab"]');
    if (!tab || !tablist.contains(tab)) return;
    event.preventDefault();
    activate(tab);
  });

  tablist.addEventListener('keydown', (event) => {
    const current = entries.findIndex(({ tab }) => tab === event.target.closest('[role="tab"]'));
    if (current < 0) return;

    let next = current;
    if (event.key === 'ArrowRight') next = (current + 1) % entries.length;
    else if (event.key === 'ArrowLeft') next = (current - 1 + entries.length) % entries.length;
    else if (event.key === 'Home') next = 0;
    else if (event.key === 'End') next = entries.length - 1;
    else return;

    event.preventDefault();
    activate(entries[next].tab, { focus: true });
  });

  const initial = entries.find(({ tab }) => tab.hash === window.location.hash) || entries[0];
  activate(initial.tab, { updateHash: Boolean(window.location.hash) });
})();
