(() => {
  'use strict';

  document.addEventListener('click', (event) => {
    const link = event.target.closest('a[href^="#"]');
    if (!link) return;
    const caseNavigationMenu = link.closest('.pgm-demo__case-nav-menu');
    if (caseNavigationMenu) {
      const disclosure = caseNavigationMenu.closest('details');
      if (disclosure) window.setTimeout(() => { disclosure.open = false; }, 0);
    }
    let targetId;
    try {
      targetId = decodeURIComponent(link.hash.slice(1));
    } catch {
      return;
    }
    const target = document.getElementById(targetId);
    const disclosure = target?.closest('[data-case-disclosure]');
    if (disclosure && !disclosure.open) disclosure.open = true;
  });

  const namespace = 'http://www.w3.org/2000/svg';
  const graph = document.querySelector('.pgm-demo__network');
  const svg = graph?.querySelector('.pgm-demo__edges');
  const source = graph?.querySelector('.pgm-demo__source-node');
  const relations = graph ? [...graph.querySelectorAll('[data-graph-relation]')] : [];
  const targets = graph ? [...graph.querySelectorAll('[data-graph-target]')] : [];
  const filters = graph ? [...graph.querySelectorAll('[data-graph-filter]')] : [];
  const liveStatus = graph?.querySelector('[data-graph-live]');
  if (!graph || !svg || !source || !relations.length || !targets.length) return;

  let scheduled = false;
  const drawEdges = () => {
    scheduled = false;
    const graphRect = graph.getBoundingClientRect();
    if (!graphRect.width || !graphRect.height) return;

    svg.setAttribute('viewBox', `0 0 ${graphRect.width} ${graphRect.height}`);
    svg.setAttribute('width', String(graphRect.width));
    svg.setAttribute('height', String(graphRect.height));
    svg.querySelectorAll('.pgm-demo__edge').forEach((edge) => edge.remove());

    const drawConnection = (from, to, kind, index, fanCount = 1) => {
      const fromRect = from.getBoundingClientRect();
      const toRect = to.getBoundingClientRect();
      const fromCenterX = fromRect.left + fromRect.width / 2;
      const fromCenterY = fromRect.top + fromRect.height / 2;
      const toCenterX = toRect.left + toRect.width / 2;
      const toCenterY = toRect.top + toRect.height / 2;
      const fanBranch = Boolean(from.dataset.graphRelation && to.dataset.graphTarget
        && toCenterX >= fromRect.left && toCenterX <= fromRect.right);
      const verticalOverlap = fromRect.top < toRect.bottom && fromRect.bottom > toRect.top;
      const horizontal = !fanBranch && verticalOverlap
        && Math.abs(toCenterX - fromCenterX) > Math.abs(toCenterY - fromCenterY);
      const direction = horizontal ? Math.sign(toCenterX - fromCenterX) || 1 : Math.sign(toCenterY - fromCenterY) || 1;
      const fanOffset = fanCount > 1 ? (index + 1) / (fanCount + 1) : 0.5;
      const startX = (horizontal
        ? (direction > 0 ? fromRect.right : fromRect.left)
        : fanBranch ? toCenterX : fromRect.left + fromRect.width * fanOffset) - graphRect.left;
      const startY = (horizontal ? fromCenterY : (direction > 0 ? fromRect.bottom : fromRect.top)) - graphRect.top;
      const endX = (horizontal
        ? (direction > 0 ? toRect.left : toRect.right)
        : fanBranch ? toCenterX : toRect.left + toRect.width * fanOffset) - graphRect.left;
      const endY = (horizontal ? toCenterY : (direction > 0 ? toRect.top : toRect.bottom)) - graphRect.top;
      const curve = Math.min(90, Math.abs(horizontal ? endX - startX : endY - startY) * 0.42);
      const control1X = horizontal ? startX + direction * curve : startX;
      const control1Y = horizontal ? startY : startY + direction * curve;
      const control2X = horizontal ? endX - direction * curve : endX;
      const control2Y = horizontal ? endY : endY - direction * curve;
      const edge = document.createElementNS(namespace, 'path');
      edge.setAttribute('class', `pgm-demo__edge pgm-demo__edge--${kind}`);
      edge.setAttribute('data-edge-kind', kind);
      if (fanBranch) edge.setAttribute('data-edge-branch', 'true');
      edge.setAttribute('data-edge-index', String(index + 1));
      edge.setAttribute('data-graph-from', from.dataset.graphRelation ? `relation:${from.dataset.graphRelation}` : 'source');
      edge.setAttribute('data-graph-to', to.dataset.graphTarget
        ? `target:${to.dataset.graphTarget}`
        : `relation:${to.dataset.graphRelation || ''}`);
      edge.setAttribute('marker-end', 'url(#pgm-demo-arrow)');
      edge.setAttribute('d', `M ${startX} ${startY} C ${control1X} ${control1Y}, ${control2X} ${control2Y}, ${endX} ${endY}`);
      svg.append(edge);
    };

    relations.forEach((relation, index) => {
      const kind = relation.dataset.graphRelation;
      drawConnection(source, relation, `${kind}-source`, index, relations.length);
      const relatedTargets = targets.filter((target) => target.dataset.graphRelationTarget === kind);
      relatedTargets.forEach((target, targetIndex) =>
        drawConnection(relation, target, kind, targetIndex, relatedTargets.length));
    });
  };

  const scheduleDraw = () => {
    if (scheduled) return;
    scheduled = true;
    window.requestAnimationFrame(drawEdges);
  };

  const summaries = {
    all: 'Visão completa: sete referências expressas, uma alteração e uma cláusula geral.',
    express: 'Destaque: o Art. 260 cita seis leis e um artigo para revogação expressa. A relação ainda depende de revisão jurídica.',
    amendment: 'Destaque: o Art. 261 altera a LC nº 208/2022, Art. 14. Esta relação não é uma revogação.',
    generic: 'Destaque: o Art. 266 contém cláusula geral, sem individualizar outras leis como alvos.',
  };

  filters.forEach((button) => {
    button.addEventListener('click', () => {
      const selected = button.dataset.graphFilter;
      graph.dataset.graphFocus = selected;
      filters.forEach((candidate) => {
        candidate.setAttribute('aria-pressed', String(candidate === button));
      });
      relations.forEach((relation) => {
        relation.dataset.graphEmphasis = selected === 'all' || relation.dataset.graphRelation === selected
          ? 'active'
          : 'muted';
      });
      targets.forEach((target) => {
        target.dataset.graphEmphasis = selected === 'all' || target.dataset.graphRelationTarget === selected
          ? 'active'
          : 'muted';
      });
      svg.querySelectorAll('.pgm-demo__edge').forEach((edge) => {
        const isSourceEdge = edge.dataset.graphFrom === 'source';
        const edgeKind = edge.dataset.edgeKind?.replace(/-source$/, '');
        edge.dataset.graphEmphasis = selected === 'all' || edgeKind === selected
          || (isSourceEdge && edge.dataset.graphTo === `relation:${selected}`)
          ? 'active'
          : 'muted';
      });
      if (liveStatus) liveStatus.textContent = summaries[selected] || summaries.all;
    });
  });

  if ('ResizeObserver' in window) {
    const observer = new ResizeObserver(scheduleDraw);
    [graph, source, ...relations, ...targets].forEach((element) => observer.observe(element));
  } else {
    window.addEventListener('resize', scheduleDraw, { passive: true });
  }
  window.addEventListener('load', scheduleDraw, { once: true });
  scheduleDraw();
})();
