/* Functional search controls. The existing shell is intentionally preserved;
 * this module wires its four pre-rendered controls to real application state. */
(function () {
  'use strict';

  const STORAGE_KEY = 'jurix:search-options:v1';
  const defaults = {
    norma_status: 'consolidated',
    source_scope: 'municipal',
    mode: 'hybrid',
    attachment_ids: [],
  };
  let state = { ...defaults };

  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}');
    state = { ...state, ...saved };
  } catch (_) {}
  // Attachments belong to the current conversation and must never survive a new one.
  state.attachment_ids = [];
  state.attachments = [];

  const config = () => {
    const value = document.body?.dataset?.searchOptions;
    if (!value) return;
    try { state = { ...state, ...JSON.parse(value) }; } catch (_) {}
  };
  config();

  function save() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
    } catch (_) {}
  }

  function controls() {
    return Array.from(document.querySelectorAll('.figma-search-dropdown'));
  }

  function descriptor(index, element) {
    const explicit = element.dataset.control;
    if (explicit) return explicit;
    if (index === 0) return 'norma_status';
    if (index === 1) return 'source_scope';
    if (index === 2) return 'attachment';
    return 'mode';
  }

  const options = {
    norma_status: [
      ['consolidated', 'Normas consolidadas'],
      ['all', 'Todas as normas indexadas'],
    ],
    source_scope: [
      ['municipal', 'Legislação municipal'],
      ['all', 'Todas as fontes indexadas'],
    ],
    mode: [
      ['hybrid', 'Pesquisa híbrida'],
      ['semantic', 'Pesquisa semântica'],
      ['lexical', 'Pesquisa textual'],
    ],
  };

  function closeAll(except, restoreFocus = false) {
    document.querySelectorAll('[data-jurix-control-menu]').forEach(menu => {
      if (menu === except) return;
      const control = menu.closest('.figma-search-dropdown');
      menu.remove();
      control?.classList.remove('jurix-control-menu-above', 'jurix-control-menu-align-end');
      control?.setAttribute('aria-expanded', 'false');
      if (restoreFocus) control?.focus();
    });
  }

  function buttonLabel(key) {
    const map = {
      norma_status: state.norma_status === 'all' ? 'Todas as normas' : 'Pesquisa normativa',
      source_scope: state.source_scope === 'all' ? 'Todas as fontes' : 'Legislação municipal',
      mode: state.mode === 'lexical' ? 'Pesquisa textual' : state.mode === 'semantic' ? 'Pesquisa semântica' : 'Pesquisa híbrida',
    };
    if (!map[key]) return;
    controls().forEach(control => {
      if (control.dataset.control !== key) return;
      const label = control.querySelector('[data-control-label]');
      if (label) label.textContent = map[key];
    });
  }

  function renderMenu(control, key, focusFirst = false) {
    const existingMenu = control.querySelector('[data-jurix-control-menu]');
    if (existingMenu) {
      existingMenu.remove();
      control.setAttribute('aria-expanded', 'false');
      control.focus();
      return;
    }
    closeAll();
    if (key === 'attachment') {
      ensureFileInput().click();
      return;
    }
    const menu = document.createElement('div');
    menu.dataset.jurixControlMenu = 'true';
    menu.id = `jurix-control-menu-${key}-${controls().indexOf(control)}`;
    menu.className = 'jurix-control-menu';
    menu.setAttribute('role', 'menu');
    options[key].forEach(([value, text]) => {
      const item = document.createElement('button');
      item.type = 'button';
      item.className = 'jurix-control-option';
      item.textContent = text;
      item.setAttribute('role', 'menuitemradio');
      item.setAttribute('aria-checked', String(state[key] === value));
      item.onclick = event => {
        event.preventDefault();
        event.stopPropagation();
        state[key] = value;
        save();
        buttonLabel(key);
        menu.remove();
        control.setAttribute('aria-expanded', 'false');
        control.focus();
        window.dispatchEvent(new CustomEvent('jurix:search-options-changed', { detail: getPayload() }));
      };
      menu.appendChild(item);
    });
    control.classList.add('jurix-control-positioned');
    control.classList.remove('jurix-control-menu-above', 'jurix-control-menu-align-end');
    control.setAttribute('aria-controls', menu.id);
    control.setAttribute('aria-expanded', 'true');
    control.appendChild(menu);
    const controlBounds = control.getBoundingClientRect();
    const menuBounds = menu.getBoundingClientRect();
    if (controlBounds.bottom + menuBounds.height + 8 > window.innerHeight && controlBounds.top > window.innerHeight - controlBounds.bottom) {
      control.classList.add('jurix-control-menu-above');
    }
    if (controlBounds.right + menuBounds.width > window.innerWidth - 8) {
      control.classList.add('jurix-control-menu-align-end');
    }
    if (focusFirst) menu.querySelector('button')?.focus();
  }

  function ensureFileInput() {
    let input = document.getElementById('jurix-document-input');
    if (input) return input;
    input = document.createElement('input');
    input.type = 'file';
    input.id = 'jurix-document-input';
    input.setAttribute('aria-label', 'Selecionar documentos para anexar');
    input.accept = '.pdf,.txt,.md,.csv,.json,.docx';
    input.multiple = true;
    input.hidden = true;
    document.body.appendChild(input);
    return input;
  }

  function wire() {
    ensureFileInput();
    controls().forEach((control, index) => {
      const key = descriptor(index, control);
      control.dataset.control = key;
      control.setAttribute('role', 'button');
      control.setAttribute('tabindex', '0');
      control.setAttribute('aria-haspopup', 'menu');
      control.setAttribute('aria-expanded', 'false');
      control.addEventListener('click', event => {
        event.preventDefault();
        event.stopPropagation();
        renderMenu(control, key);
      });
      control.addEventListener('keydown', event => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          renderMenu(control, key, true);
        }
      });
      buttonLabel(key);
    });
  }

  function setAttachments(attachments) {
    state.attachments = attachments.slice(0, 5);
    state.attachment_ids = state.attachments.map(item => item.id);
    save();
    renderAttachments();
    document.querySelectorAll('.jurix-attachment-count').forEach(node => {
      node.textContent = state.attachment_ids.length ? `(${state.attachment_ids.length})` : '';
    });
    window.dispatchEvent(new CustomEvent('jurix:search-options-changed', { detail: getPayload() }));
  }

  function getPayload() {
    return JSON.parse(JSON.stringify(state));
  }

  function announceAttachmentError(message) {
    const container = document.getElementById('jurix-attachment-previews');
    if (!container) return;
    let notice = container.querySelector('[data-attachment-error]');
    if (!notice) {
      notice = document.createElement('p');
      notice.dataset.attachmentError = 'true';
      notice.className = 'jurix-attachment-error';
      notice.setAttribute('role', 'alert');
      container.prepend(notice);
    }
    notice.textContent = message;
    window.setTimeout(() => notice.remove(), 5000);
  }

  function renderAttachments() {
    const container = document.getElementById('jurix-attachment-previews');
    if (!container) return;
    container.replaceChildren();
    state.attachments.forEach(item => {
      const preview = document.createElement('div');
      preview.className = 'jurix-attachment-preview';
      preview.title = item.name || 'Documento anexado';
      preview.innerHTML = `<span class="jurix-attachment-icon" aria-hidden="true">PDF</span><span class="jurix-attachment-name"></span>`;
      preview.querySelector('.jurix-attachment-name').textContent = item.name || 'Documento';
      const remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'jurix-attachment-remove';
      remove.setAttribute('aria-label', `Desanexar ${item.name || 'documento'}`);
      remove.textContent = 'x';
      remove.onclick = async () => {
        remove.disabled = true;
        try {
          await (window.JurixChatAPI || window.jurixChatAPI).deleteAttachment(item.id);
          setAttachments(state.attachments.filter(current => current.id !== item.id));
        } catch (error) {
          remove.disabled = false;
          announceAttachmentError(error.message || 'Não foi possível desanexar o documento.');
        }
      };
      preview.appendChild(remove);
      container.appendChild(preview);
    });
    container.hidden = state.attachments.length === 0;
    document.querySelectorAll('.jurix-attachment-count').forEach(node => {
      node.textContent = state.attachments.length ? `(${state.attachments.length})` : '';
    });
  }

  async function upload(files) {
    const chatApi = window.JurixChatAPI || window.jurixChatAPI;
    if (!chatApi?.uploadAttachment) {
      throw new Error('API de anexos indisponível.');
    }
    const merged = [...state.attachments];
    for (const file of Array.from(files || []).slice(0, 5 - state.attachments.length)) {
      const item = await chatApi.uploadAttachment(file);
      merged.push(item);
    }
    setAttachments(merged);
  }

  document.addEventListener('click', event => {
    if (!event.target.closest('.figma-search-dropdown')) closeAll();
  });

  document.addEventListener('keydown', event => {
    if (event.key !== 'Escape' || !document.querySelector('[data-jurix-control-menu]')) return;
    event.preventDefault();
    event.stopPropagation();
    closeAll(null, true);
  }, true);

  document.addEventListener('change', event => {
    if (event.target?.id !== 'jurix-document-input') return;
    upload(event.target.files).catch(error => {
      console.error('[Jurix] attachment upload failed', error);
      announceAttachmentError(error.message || 'Não foi possível anexar o documento.');
    });
    event.target.value = '';
  });

  document.addEventListener('jurix:new-conversation', () => {
    const current = [...state.attachments];
    state.attachments = [];
    state.attachment_ids = [];
    save();
    renderAttachments();
    const api = window.JurixChatAPI || window.jurixChatAPI;
    current.forEach(item => api?.deleteAttachment?.(item.id).catch(() => {}));
    window.dispatchEvent(new CustomEvent('jurix:search-options-changed', { detail: getPayload() }));
  });

  window.JurixSearchControls = { getPayload, setAttachments, upload, state };
  document.addEventListener('DOMContentLoaded', () => {
    wire();
    renderAttachments();
  }, { once: true });
})();
