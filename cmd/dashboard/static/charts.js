const escapeHTML = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
})[char]);

const nodeState = (node) => {
  if (!node.reachable) return '未知';
  const state = String(node.status?.state ?? '未知');
  return state.toLowerCase() === 'leader' ? 'Leader · local' : state;
};

const targetIndex = (target) => {
  if (target == null || target === '' || !Number.isFinite(Number(target)) || Number(target) <= 0) return null;
  return Number(target);
};

const targetStatus = (target, node) => {
  const index = targetIndex(target);
  if (index == null) return '目标未设置';
  if (!node.reachable || !node.status) return `目标 ${escapeHTML(index)} · 未知`;
  return `目标 ${escapeHTML(index)} · ${Number(node.status.last_applied) >= index ? '已应用' : '待应用'}`;
};

const nodeTile = (node, selected, target) => {
  const id = String(node.id);
  const isSelected = selected != null && id === String(selected);
  const status = node.reachable ? node.status : null;
  const currentState = nodeState(node);
  const progress = status
    ? `<span class="small muted">term ${escapeHTML(status.term ?? '—')} · applied ${escapeHTML(status.last_applied ?? '—')}</span>`
    : `<span class="small muted">${node.reachable ? '状态未知' : '不可达 · 未知'}</span>`;
  const targetHint = `<span class="small muted">${targetStatus(target, node)}</span>`;
  return `<div class="node-tile" role="listitem"><button type="button" data-node="${escapeHTML(id)}" aria-pressed="${isSelected}"${isSelected ? ' class="selected"' : ''} style="display:grid;gap:4px;width:100%;padding:0;border:0;background:transparent;text-align:left;color:inherit"><strong>${escapeHTML(id)}</strong><span>${escapeHTML(currentState)}</span>${progress}${targetHint}</button></div>`;
};

const nodeGrid = (nodes, selected, target) => `<div class="node-grid" role="list">${nodes.map((node) => nodeTile(node, selected, target)).join('')}</div>`;

const topologyMap = (nodes, selected, target) => {
  const leaderIndex = nodes.findIndex((node) => node.reachable &&
    String(node.status?.state ?? '').toLowerCase() === 'leader');
  const center = leaderIndex < 0 ? null : nodes[leaderIndex];
  const ring = nodes.filter((_, index) => index !== leaderIndex);
  const points = ring.map((node, index) => {
    const angle = (2 * Math.PI * index / ring.length) - Math.PI / 2;
    return { node, x: 50 + 36 * Math.cos(angle), y: 50 + 32 * Math.sin(angle) };
  });
  const lines = points.map(({ x, y }) => `<line x1="50" y1="50" x2="${x.toFixed(2)}" y2="${y.toFixed(2)}" stroke="var(--line)" stroke-width="0.7" stroke-dasharray="1.2 1.5" vector-effect="non-scaling-stroke"/>`).join('');
  const button = (node, x, y) => {
    const id = String(node.id);
    const isSelected = selected != null && id === String(selected);
    const status = node.reachable ? node.status : null;
    const role = nodeState(node);
    const term = status ? `term ${escapeHTML(status.term ?? '—')}` : (node.reachable ? 'term —' : '');
    const ariaLabel = `节点 ${id}，${role}${term ? `，${term}` : ''}`;
    return `<button type="button" data-node="${escapeHTML(id)}" aria-label="${escapeHTML(ariaLabel)}" title="${escapeHTML(ariaLabel)}" aria-pressed="${isSelected}"${isSelected ? ' class="selected"' : ''} style="position:absolute;left:${x.toFixed(2)}%;top:${y.toFixed(2)}%;transform:translate(-50%,-50%);display:grid;place-items:center;width:46px;height:46px;padding:0;border:0;background:transparent;color:var(--ink);text-align:center"><span style="display:grid;place-items:center;width:42px;height:42px;border:1px solid ${isSelected ? 'var(--accent)' : 'var(--line)'};border-radius:50%;background:${isSelected ? 'var(--accentbg)' : 'var(--surface)'};font-size:11px;font-weight:600;box-shadow:var(--shadow)">${escapeHTML(id)}</span>${nodes.length <= 7 || node === center ? `<span class="topology-meta"><span>${escapeHTML(role)}</span>${term ? `<span class="small muted node-term">${term}</span>` : ''}</span>` : ''}</button>`;
  };
  const buttons = [
    ...(center ? [button(center, 50, 50)] : []),
    ...points.map(({ node, x, y }) => button(node, x, y)),
  ].join('');
  const leaderCount = nodes.filter((node) => node.reachable && String(node.status?.state ?? '').toLowerCase() === 'leader').length;
  const multipleLeadersNote = leaderCount > 1
    ? '<p class="small muted" style="margin:0;text-align:center">多个 Leader 时仅居中展示一个观察结果，不表示额外授权。</p>' : '';
  const index = targetIndex(target);
  const targetText = index == null ? '目标未设置' : `目标索引 ${escapeHTML(index)}`;
  return `<div style="height:300px;display:grid;place-items:center;overflow:hidden"><div style="position:relative;width:min(100%,560px);height:300px"><svg aria-hidden="true" viewBox="0 0 100 100" preserveAspectRatio="none" style="position:absolute;inset:0;width:100%;height:100%">${lines}</svg>${buttons}</div></div>${multipleLeadersNote}<p class="small muted" style="margin:3px 0 0;text-align:center">${targetText}</p>`;
};

export function topology(nodes, selected, target) {
  const items = Array.isArray(nodes) ? nodes : [];
  const view = items.length >= 3 && items.length <= 15
    ? topologyMap(items, selected, target)
    : nodeGrid(items, selected, target);
  return `<div class="topology-view"><p class="muted small">逻辑关系，非实测链路</p>${items.length ? view : '<p class="empty" role="status">暂无节点数据</p>'}</div>`;
}

const groupKey = (row) => JSON.stringify([
  row.platform ?? '', row.source_sha256 ?? '', row.nodes ?? '', row.scenario ?? '', row.batch_size ?? '', row.requested_commands ?? '',
]);

const groupLabel = (row) => {
  const commands = Number(row.requested_commands);
  const workload = Number.isFinite(commands) ? commands.toLocaleString('zh-CN') : escapeHTML(row.requested_commands ?? '—');
  return `${escapeHTML(row.platform ?? '未知平台')} · ${escapeHTML(row.nodes ?? '—')} 节点 · ${escapeHTML(row.scenario ?? '未知场景')} · 工作量 ${workload} 条命令 · batch ${escapeHTML(row.batch_size ?? '—')}`;
};

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
