import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';

const script = await readFile(
  new URL('../../src/apps/core/static/js/jurix-normative-casefile.js', import.meta.url),
  'utf8',
);

class Element {
  constructor(id = '', hash = '') {
    this.id = id;
    this.hash = hash;
    this.attributes = new Map();
    this.listeners = new Map();
    this.hidden = false;
    this.tabIndex = 0;
    this.focused = false;
  }

  setAttribute(name, value) { this.attributes.set(name, String(value)); }
  getAttribute(name) { return this.attributes.get(name) ?? null; }
  hasAttribute(name) { return this.attributes.has(name); }
  addEventListener(name, callback) { this.listeners.set(name, callback); }
  contains(element) { return this.children.includes(element); }
  closest(selector) { return selector === '[role="tab"]' && this.getAttribute('role') === 'tab' ? this : null; }
  focus() { this.focused = true; }
}

function setup(initialHash = '') {
  const ids = ['texto-na-data', 'alteracoes', 'grafo', 'fontes'];
  const tabs = ids.map((id) => new Element('', `#${id}`));
  const panels = new Map(ids.map((id) => {
    const panel = new Element(id);
    panel.setAttribute('data-casefile-panel', '');
    return [id, panel];
  }));
  const tablist = new Element();
  tablist.children = tabs;
  tablist.querySelectorAll = () => tabs;
  const location = { pathname: '/explorar/norma/1/', search: '', hash: initialHash };
  const context = {
    document: {
      querySelector: () => tablist,
      getElementById: (id) => panels.get(id) ?? null,
    },
    window: {
      location,
      history: {
        replaceState(_state, _title, url) {
          const parsed = new URL(url, 'https://jurix.test');
          location.pathname = parsed.pathname;
          location.search = parsed.search;
          location.hash = parsed.hash;
        },
      },
    },
  };
  vm.runInNewContext(script, context);
  return { tabs, panels, tablist, location };
}

test('shows the first panel by default and exposes accessible tab semantics', () => {
  const { tabs, panels, tablist } = setup();

  assert.equal(tablist.getAttribute('role'), 'tablist');
  assert.equal(tabs[0].getAttribute('aria-selected'), 'true');
  assert.equal(tabs[0].tabIndex, 0);
  assert.equal(panels.get('texto-na-data').hidden, false);
  assert.equal(tabs[1].getAttribute('aria-controls'), 'alteracoes');
  assert.equal(panels.get('alteracoes').getAttribute('aria-labelledby'), tabs[1].id);
  assert.equal(panels.get('alteracoes').hidden, true);
});

test('opens a deep-linked tab and updates the hash on user selection', () => {
  const { tabs, panels, location, tablist } = setup('#grafo');
  assert.equal(tabs[2].getAttribute('aria-selected'), 'true');
  assert.equal(panels.get('grafo').hidden, false);

  let prevented = false;
  tablist.listeners.get('click')({
    target: tabs[3],
    preventDefault() { prevented = true; },
  });

  assert.equal(prevented, true);
  assert.equal(location.hash, '#fontes');
  assert.equal(panels.get('fontes').hidden, false);
  assert.equal(panels.get('grafo').hidden, true);
});

test('supports arrow and Home/End keyboard navigation with focus', () => {
  const { tabs, tablist } = setup();
  const dispatch = (key, target) => {
    let prevented = false;
    tablist.listeners.get('keydown')({
      key,
      target,
      preventDefault() { prevented = true; },
    });
    return prevented;
  };

  assert.equal(dispatch('ArrowRight', tabs[0]), true);
  assert.equal(tabs[1].focused, true);
  assert.equal(tabs[1].getAttribute('aria-selected'), 'true');
  assert.equal(dispatch('End', tabs[1]), true);
  assert.equal(tabs[3].focused, true);
  assert.equal(dispatch('Home', tabs[3]), true);
  assert.equal(tabs[0].getAttribute('aria-selected'), 'true');
});
