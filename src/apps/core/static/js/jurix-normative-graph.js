const SVG_NS = 'http://www.w3.org/2000/svg';
const ACTION_LABELS = {
  ALTERA: 'Altera', SUBSTITUI: 'Substitui', ADICIONA: 'Adiciona',
  REVOGA: 'Revoga', REGULAMENTA: 'Regulamenta', REFERENCIA: 'Referência',
};

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined && text !== null) node.textContent = String(text);
  if (className) node.className = className;
  return node;
}

function validUrl(value, { sameOrigin = false } = {}) {
  if (!value) return null;
  try {
    const url = new URL(value, window.location.origin);
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) return null;
    if (sameOrigin && url.origin !== window.location.origin) return null;
    return url;
  } catch {
    return null;
  }
}

function groupRelations(edges) {
  const groups = new Map();
  for (const edge of edges) {
    const key = `${edge.source}\u001f${edge.target}`;
    if (!groups.has(key)) groups.set(key, { key, source: edge.source, target: edge.target, events: [] });
    groups.get(key).events.push(edge);
  }
  return [...groups.values()];
}

function relationLabel(group, nodes) {
  const source = nodes.get(group.source)?.label || 'Norma de origem';
  const target = nodes.get(group.target)?.label || 'Norma relacionada';
  return `${source} → ${target}`;
}

function svgNode(tag, attrs = {}, text = '') {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [name, value] of Object.entries(attrs)) node.setAttribute(name, String(value));
  if (text) node.textContent = text;
  return node;
}

function renderGraph(svg, groups, nodes, rootId, onSelect) {
  svg.replaceChildren();
  if (!groups.length) return;
  const connected = new Set();
  groups.forEach((group) => { connected.add(group.source); connected.add(group.target); });
  const ids = [...connected].sort((a, b) => (nodes.get(a)?.label || a).localeCompare(nodes.get(b)?.label || b, 'pt-BR'));
  const root = ids.includes(rootId) ? rootId : ids[0];
  const others = ids.filter((id) => id !== root);
  const height = Math.max(256, others.length * 76 + 32);
  svg.setAttribute('viewBox', `0 0 720 ${height}`);
  svg.setAttribute('height', String(height));
  const positions = new Map([[root, { x: 165, y: height / 2 }]]);
  others.forEach((id, index) => positions.set(id, { x: 555, y: 38 + index * (height - 76) / Math.max(1, others.length - 1) }));
  for (const group of groups) {
    const from = positions.get(group.source);
    const to = positions.get(group.target);
    if (!from || !to) continue;
    const direction = to.x > from.x ? 1 : -1;
    const line = svgNode('line', { x1: from.x + direction * 125, y1: from.y, x2: to.x - direction * 125, y2: to.y, class: 'normative-relations__edge' });
    const caption = group.events.map((event) => `${ACTION_LABELS[event.action] || event.action}${event.resolution === 'conflict' ? ' · conflito' : event.resolution === 'unresolved' ? ' · pendente' : ''}`).filter((label, index, all) => all.indexOf(label) === index).join(' / ');
    const label = svgNode('text', { x: (from.x + to.x) / 2, y: (from.y + to.y) / 2 - 6, 'text-anchor': 'middle', class: 'normative-relations__edge-label' }, caption);
    if (onSelect) {
      line.style.cursor = 'pointer';
      line.addEventListener('click', () => onSelect(group));
      const hit = svgNode('line', { x1: from.x + direction * 125, y1: from.y, x2: to.x - direction * 125, y2: to.y, stroke: 'transparent', 'stroke-width': 24 });
      hit.style.cursor = label.style.cursor = 'pointer';
      hit.addEventListener('click', () => onSelect(group));
      label.addEventListener('click', () => onSelect(group));
      svg.append(hit);
    }
    svg.append(line, label);
  }
  for (const id of ids) {
    const pos = positions.get(id);
    const node = nodes.get(id) || { label: 'Norma relacionada' };
    svg.append(svgNode('rect', { x: pos.x - 125, y: pos.y - 30, width: 250, height: 60, rx: 10, class: `normative-relations__node${id === root ? ' normative-relations__node--root' : ''}` }));
    const words = String(node.label || 'Norma relacionada').split(/\s+/);
    const lines = [''];
    for (const word of words) {
      const current = lines[lines.length - 1];
      if (current && `${current} ${word}`.length > 29 && lines.length < 2) lines.push(word);
      else lines[lines.length - 1] = current ? `${current} ${word}` : word;
    }
    if (lines[1] && lines[1].length > 29) lines[1] = `${lines[1].slice(0, 28)}…`;
    const label = svgNode('text', { x: pos.x, y: pos.y + (lines.length === 1 ? 5 : -2), 'text-anchor': 'middle', class: 'normative-relations__node-label' });
    lines.forEach((line, index) => label.append(svgNode('tspan', { x: pos.x, dy: index === 0 ? 0 : 17 }, line)));
    svg.append(label);
  }
}

function safeNormaLink(node) {
  const url = validUrl(node?.url, { sameOrigin: true });
  return url;
}

function createEventDetails(edge, nodes) {
  const item = element('li', null, 'normative-relations__event');
  const action = ACTION_LABELS[edge.action] || 'Relação normativa';
  item.append(element('h4', action));
  const fromNorm = nodes.get(edge.source)?.label || 'Norma de origem';
  const toNode = nodes.get(edge.target) || { label: 'Referência externa não resolvida' };
  const route = element('p');
  route.append(document.createTextNode(`${fromNorm} — `));
  const targetUrl = safeNormaLink(toNode);
  if (targetUrl) {
    const link = element('a', toNode.label);
    link.href = targetUrl.href;
    route.append(link);
  } else {
    route.append(document.createTextNode(toNode.label));
  }
  item.append(route);

  if (edge.source_device?.label) item.append(element('p', `Dispositivo de origem: ${edge.source_device.label}`));
  if (edge.target_device?.label) item.append(element('p', `Dispositivo de destino: ${edge.target_device.label}`));
  const reviewLabel = edge.review_status === 'confirmed'
    ? 'Confirmado após revisão humana'
    : edge.review_status === 'candidate_confirmed'
      ? 'Trecho e identidade da referência conferidos; efeito jurídico ainda não avaliado'
      : edge.review_status === 'candidate_text_confirmed_unresolved'
        ? 'Trecho citado conferido; identidade do alvo ainda não confirmada'
      : edge.review_status === 'candidate_rejected'
        ? 'Extração rejeitada pelo revisor; preservada para auditoria'
    : edge.review_status === 'rejected'
      ? 'Rejeitado; preservado para auditoria'
      : edge.review_status === 'ai_pilot'
        ? `Análise IA adotada no piloto · ${edge.resolution === 'conflict' ? 'conflito documental' : edge.resolution === 'unresolved' ? 'alvo não resolvido' : edge.resolution === 'partial' ? 'extração parcial' : 'alvo identificado no escopo'}`
        : 'Candidato pendente de revisão';
  item.append(element('p', `Revisão do vínculo: ${reviewLabel}. ${['confirmed', 'candidate_confirmed', 'ai_pilot'].includes(edge.review_status) ? '' : 'Este candidato não comprova efeito jurídico.'}`));
  if (edge.action === 'REFERENCIA' || edge.action === 'REGULAMENTA') {
    item.append(element('p', `Data considerada: publicação da norma de origem${edge.publication_on ? ` (${edge.publication_on})` : ' (não informada)'}. Esta relação não afirma alteração ou revogação.`));
  } else {
    const dateLabel = edge.review_status === 'ai_pilot' && edge.effective_on
      ? `Início calculado no piloto: ${edge.effective_on}; publicação: ${edge.publication_on || 'não comprovada'}. Efeitos especiais/fiscais não presumidos.`
      : edge.effective_status === 'not_assessed'
      ? 'Efeito jurídico: não avaliado; este vínculo representa somente uma relação extraída do documento.'
      : edge.effective_status === 'confirmed' && edge.effective_on
      ? `Efeito registrado em ${edge.effective_on}`
      : `Efeito não confirmado (${edge.effective_status || 'sem dados'})`;
    item.append(element('p', dateLabel));
  }
  if (edge.evidence?.quote) item.append(element('blockquote', edge.evidence.quote));
  const localPdf = validUrl(edge.local_pdf_url, { sameOrigin: true });
  if (localPdf) {
    const link = element('a', 'Conferir cláusula no PDF (nova aba)');
    link.href = localPdf.href;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    item.append(link);
  }
  const targetDocuments = Array.isArray(edge.evidence?.target_document_candidates)
    ? edge.evidence.target_document_candidates
    : [];
  if (targetDocuments.length) {
    item.append(element('p', 'PDFs candidatos ao alvo (coincidência de metadados; vínculo não confirmado):'));
    const documentList = element('ul', null, 'normative-relations__candidate-documents');
    for (const candidate of targetDocuments) {
      const row = element('li');
      const candidateUrl = safeNormaLink(candidate);
      if (candidateUrl) {
        const link = element('a', candidate.filename || 'Abrir PDF candidato');
        link.href = candidateUrl.href;
        row.append(link);
      } else {
        row.append(element('span', candidate.filename || 'PDF sem nome'));
      }
      const identityLabel = candidate.type_matches
        ? candidate.identity_type
        : `conflito de espécie: ${candidate.identity_type}`;
      row.append(element('span', ` · ${candidate.source} · ${candidate.review_status} · ${identityLabel}`));
      documentList.append(row);
    }
    item.append(documentList);
    if (edge.evidence.target_document_candidates_truncated) {
      item.append(element('p', 'Há outros PDFs com metadados coincidentes; a lista foi limitada para revisão.'));
    }
  }
  const official = validUrl(edge.official_url);
  if (official) {
    const link = element('a', 'Abrir fonte oficial (nova aba)');
    link.href = official.href;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    item.append(link);
  } else if (edge.evidence?.document_id) {
    const link = element('a', 'Abrir evidência documental');
    link.href = `/normas/documentos/${encodeURIComponent(edge.evidence.document_id)}/`;
    item.append(link);
  }
  return item;
}

function setupRelations(root) {
  const disclosure = root.querySelector('[data-relations-disclosure]');
  const filter = root.querySelector('[data-relations-action]');
  const status = root.querySelector('[data-relations-status]');
  const retry = root.querySelector('[data-relations-retry]');
  const list = root.querySelector('[data-relations-list]');
  const svg = root.querySelector('[data-relations-svg]');
  const graphWrap = root.querySelector('[data-relations-graph-wrap]');
  const truncated = root.querySelector('[data-relations-truncated]');
  const panel = root.querySelector('[data-relations-panel]');
  const panelContent = root.querySelector('[data-relations-panel-content]');
  const closeButton = root.querySelector('[data-relations-close]');
  const initialPayloadNode = root.dataset.initialPayloadId
    ? document.getElementById(root.dataset.initialPayloadId)
    : null;
  let payload = null;
  if (initialPayloadNode) {
    try {
      const initialPayload = JSON.parse(initialPayloadNode.textContent || 'null');
      if (Array.isArray(initialPayload?.nodes) && Array.isArray(initialPayload?.edges)) payload = initialPayload;
    } catch {
      payload = null;
    }
  }
  let loading = false;
  let trigger = null;

  const setStatus = (message, state = '') => {
    status.textContent = message;
    status.dataset.state = state;
    status.setAttribute('aria-busy', String(state === 'loading'));
  };

  const closePanel = (returnFocus = true) => {
    panel.hidden = true;
    panelContent.replaceChildren();
    if (returnFocus && trigger?.isConnected) trigger.focus();
  };

  const openPanel = (group, button, nodes) => {
    trigger = button;
    const heading = element('p', relationLabel(group, nodes));
    const events = element('ol', null, 'normative-relations__event-list');
    for (const edge of group.events) events.append(createEventDetails(edge, nodes));
    panelContent.replaceChildren(heading, events);
    panel.hidden = false;
    closeButton.focus();
    panel.scrollIntoView?.({ block: 'nearest', behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
  };

  const draw = () => {
    if (!payload) return;
    const nodes = new Map((payload.nodes || []).map((node) => [node.id, node]));
    const chosen = filter.value;
    const edges = (payload.edges || []).filter((edge) => !chosen || edge.action === chosen);
    const groups = groupRelations(edges);
    list.replaceChildren();
    closePanel(false);
    const buttons = new Map();
    for (const group of groups) {
      const item = element('li');
      const button = element('button', null, 'normative-relations__group-button');
      button.type = 'button';
      const label = element('span', relationLabel(group, nodes));
      const count = element('span', `${group.events.length} vínculo${group.events.length === 1 ? '' : 's'}`, 'normative-relations__group-count');
      button.append(label, count);
      button.addEventListener('click', () => openPanel(group, button, nodes));
      buttons.set(group.key, button);
      item.append(button);
      list.append(item);
    }
    graphWrap.hidden = groups.length === 0;
    renderGraph(svg, groups, nodes, payload.root_id || `norma:${payload.norma?.id}`, (group) => openPanel(group, buttons.get(group.key), nodes));
    truncated.hidden = !payload.truncated;
    const availability = edges.length === 1 ? 'disponível' : 'disponíveis';
    setStatus(groups.length ? `${groups.length} grupo${groups.length === 1 ? '' : 's'} de relações; ${edges.length} vínculo${edges.length === 1 ? '' : 's'} ${availability}.` : (chosen ? 'Nenhuma relação corresponde a este filtro.' : 'Esta norma não possui relações públicas disponíveis no corpus.'));
  };

  const load = async () => {
    if (payload) {
      draw();
      return;
    }
    if (loading) return;
    loading = true;
    retry.hidden = true;
    setStatus('Carregando relações normativas…', 'loading');
    try {
      const url = new URL(root.dataset.apiUrl, window.location.origin);
      const response = await fetch(url.href, { headers: { Accept: 'application/json' }, credentials: 'same-origin' });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const result = await response.json();
      if (!result?.success || !Array.isArray(result.edges) || !Array.isArray(result.nodes)) throw new Error('Resposta inválida');
      payload = result;
      draw();
    } catch {
      setStatus('Não foi possível carregar as relações agora. Tente novamente.', 'error');
      retry.hidden = false;
    } finally {
      loading = false;
    }
  };

  disclosure.addEventListener('toggle', () => {
    if (disclosure.open) load();
    else closePanel(false);
  });
  filter.addEventListener('change', () => {
    if (payload) draw();
    else if (disclosure.open) load();
  });
  retry.addEventListener('click', load);
  closeButton.addEventListener('click', () => closePanel(true));
  root.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && !panel.hidden) {
      event.preventDefault();
      closePanel(true);
    }
  });
}

if (typeof document !== 'undefined') {
  document.querySelectorAll('[data-normative-relations]').forEach(setupRelations);
  window.JurixNormativeGraph = Object.freeze({ groupRelations, renderGraph, setupRelations, validUrl });
}
