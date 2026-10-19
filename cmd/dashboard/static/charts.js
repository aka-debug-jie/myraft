const escapeHTML = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
})[char]);

const nodeState = (node) => {
  if (!node.reachable) return '未知';
  const state = String(node.status?.state ?? '未知');
  return state.toLowerCase() === 'leader' ? 'Leader · local' : state;
};

const nodeTile = (node, selected, target) => {
  const id = String(node.id);
  const isSelected = selected != null && id === String(selected);
  const status = node.reachable ? node.status : null;
  const currentState = nodeState(node);
  const progress = status
    ? `<span class="small muted">term ${escapeHTML(status.term ?? '—')} · applied ${escapeHTML(status.last_applied ?? '—')}</span>`
    : `<span class="small muted">${node.reachable ? '状态未知' : '不可达 · 未知'}</span>`;
  const targetHint = target != null && Number.isFinite(Number(target)) && target !== '' && status
    ? `<span class="small muted">目标 ${escapeHTML(target)}：${Number(status.last_applied) >= Number(target) ? '已应用' : '待应用'}</span>`
    : '';
  return `<div class="node-tile" role="listitem"><button type="button" data-node="${escapeHTML(id)}" aria-pressed="${isSelected}"${isSelected ? ' class="selected"' : ''} style="display:grid;gap:4px;width:100%;padding:0;border:0;background:transparent;text-align:left;color:inherit"><strong>${escapeHTML(id)}</strong><span>${escapeHTML(currentState)}</span>${progress}${targetHint}</button></div>`;
};

const nodeGrid = (nodes, selected, target) => `<div class="node-grid" role="list">${nodes.map((node) => nodeTile(node, selected, target)).join('')}</div>`;

const topologyMap = (nodes, selected, target) => {
  const points = nodes.map((node, index) => {
    const angle = (2 * Math.PI * index / nodes.length) - Math.PI / 2;
    return { node, x: 50 + 38 * Math.cos(angle), y: 50 + 40 * Math.sin(angle) };
  });
  const lines = points.map(({ x, y }) => `<line x1="50" y1="50" x2="${x.toFixed(2)}" y2="${y.toFixed(2)}" stroke="var(--line)" stroke-width="1.5" stroke-dasharray="4 5"/>`).join('');
  const buttons = points.map(({ node, x, y }) => {
    const id = String(node.id);
    const isSelected = selected != null && id === String(selected);
    const status = node.reachable ? node.status : null;
    const progress = status ? `term ${escapeHTML(status.term ?? '—')} · applied ${escapeHTML(status.last_applied ?? '—')}` : '不可达 · 未知';
    const targetHint = target != null && Number.isFinite(Number(target)) && target !== '' && status
      ? ` · 目标 ${escapeHTML(target)} ${Number(status.last_applied) >= Number(target) ? '已应用' : '待应用'}` : '';
    return `<button type="button" data-node="${escapeHTML(id)}" aria-pressed="${isSelected}"${isSelected ? ' class="selected"' : ''} style="position:absolute;left:${x.toFixed(2)}%;top:${y.toFixed(2)}%;transform:translate(-50%,-50%);display:grid;gap:3px;width:112px;min-height:68px;padding:9px;border:1px solid var(--line);border-radius:9px;background:var(--surface);color:var(--ink);text-align:left;box-shadow:var(--shadow)"><strong>${escapeHTML(id)}</strong><span>${escapeHTML(nodeState(node))}</span><span class="small muted">${progress}${targetHint}</span></button>`;
  }).join('');
  return `<div style="position:relative;min-height:360px;overflow:hidden"><svg aria-hidden="true" viewBox="0 0 100 100" preserveAspectRatio="none" style="position:absolute;inset:0;width:100%;height:100%">${lines}</svg>${buttons}</div>`;
};

export function topology(nodes, selected, target) {
  const items = Array.isArray(nodes) ? nodes : [];
  const view = items.length >= 3 && items.length <= 15
    ? topologyMap(items, selected, target)
    : nodeGrid(items, selected, target);
  return `<div class="topology-view"><p class="muted small">逻辑关系，非实测链路</p>${items.length ? view : '<p class="empty" role="status">暂无节点数据</p>'}</div>`;
}

const groupKey = (row) => JSON.stringify([
  row.platform ?? '', row.source_sha256 ?? '', row.nodes ?? '', row.scenario ?? '', row.batch_size ?? '',
]);

const groupLabel = (row) => `${escapeHTML(row.platform ?? '未知平台')} · ${escapeHTML(row.nodes ?? '—')} 节点 · ${escapeHTML(row.scenario ?? '未知场景')} · batch ${escapeHTML(row.batch_size ?? '—')}`;

const renderGroup = (group) => {
  const { row, passes, failed, interrupted } = group;
  const values = passes.filter((item) => item.elapsed_seconds != null && item.elapsed_seconds !== '')
    .map((item) => Number(item.elapsed_seconds)).filter(Number.isFinite);
  const n = values.length;
  const mean = n ? values.reduce((sum, value) => sum + value, 0) / n : null;
  const max = Math.max(1, values.reduce((largest, value) => Math.max(largest, value), 0));
  const x = (value) => 28 + (value / max) * 450;
  const dots = values.map((value, index) => `<circle cx="${x(value).toFixed(2)}" cy="${22 + (index % 5) * 8}" r="3.5" fill="var(--accent)"><title>PASS ${escapeHTML(value)} 秒</title></circle>`).join('');
  const meanMark = mean == null ? '' : `<line x1="${x(mean).toFixed(2)}" y1="12" x2="${x(mean).toFixed(2)}" y2="58" stroke="var(--amber)" stroke-width="2" stroke-dasharray="3 3"/><text x="${Math.min(395, x(mean) + 5).toFixed(2)}" y="11" fill="var(--muted)" font-size="8">mean ${mean.toFixed(3)} s</text>`;
  const plot = n ? `<svg viewBox="0 0 500 64" role="img" aria-label="PASS 原始耗时点与均值" style="width:100%;height:auto;min-height:64px"><line x1="28" y1="60" x2="478" y2="60" stroke="var(--line)"/>${dots}${meanMark}<text x="28" y="63" fill="var(--muted)" font-size="8">0 s</text><text x="430" y="63" fill="var(--muted)" font-size="8">${max.toFixed(3)} s</text></svg>` : '<p class="muted small">该组没有可绘制的 PASS 耗时。</p>';
  const source = escapeHTML(row.source_sha256 ?? '未知');
  return `<article class="panel" style="margin:12px 0;padding:14px 16px"><h3 style="margin:0 0 4px;font-size:12px">${groupLabel(row)}</h3><p class="evidence-hash" style="margin:0 0 8px">平台 ${escapeHTML(row.platform ?? '未知')} · 源码 SHA-256 ${source}</p><p class="small muted" style="margin:4px 0">PASS n=${n}${mean == null ? '' : ` · mean ${mean.toFixed(3)} s`} · FAIL ${failed} · INTERRUPTED ${interrupted}</p>${plot}</article>`;
};

export function experimentChart(rows) {
  const groups = new Map();
  for (const row of Array.isArray(rows) ? rows : []) {
    const key = groupKey(row);
    if (!groups.has(key)) groups.set(key, { row, passes: [], failed: 0, interrupted: 0 });
    const group = groups.get(key);
    if (row.result === 'PASS') group.passes.push(row);
    else if (row.result === 'FAIL') group.failed += 1;
    else if (row.result === 'INTERRUPTED') group.interrupted += 1;
  }
  if (!groups.size) return '<p class="empty" role="status">实验尚未执行。</p>';
  return `<div class="experiment-chart">${[...groups.values()].map(renderGroup).join('')}</div>`;
}
