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
  return `${escapeHTML(row.platform ?? '未知平台')} · ${escapeHTML(row.nodes ?? '—')} 节点 · ${escapeHTML(({election:'首次选举',failover:'故障重选',catchup:'空节点追赶',divergence:'分歧修复',replication:'日志复制'})[row.scenario]??row.scenario??'未知场景')} · 工作量 ${workload} 条命令 · batch ${escapeHTML(row.batch_size ?? '—')}`;
};

const elapsedSeconds = (item) => {
  if (item.elapsed_seconds == null || String(item.elapsed_seconds).trim() === '') return null;
  const value = Number(item.elapsed_seconds);
  return Number.isFinite(value) && value >= 0 ? value : null;
};

const secondsText = (value) => `${value.toFixed(3)} s`;

const renderGroup = (group) => {
  const { row, rows, passes, failed, interrupted } = group;
  const values = passes.map(elapsedSeconds).filter((seconds) => seconds != null);
  const n = values.length;
  const sorted = [...values].sort((a, b) => a - b);
  const mean = n ? values.reduce((sum, value) => sum + value / n, 0) : null;
  const median = n ? (sorted.length % 2 ? sorted[(n - 1) / 2] : sorted[n / 2 - 1] / 2 + sorted[n / 2] / 2) : null;
  const range = n ? `${sorted[0].toFixed(3)}–${secondsText(sorted[n - 1])}` : null;
  let plot = '<p class="small muted perf-empty">没有可用的 通过耗时。</p>';

  if (n === 1) {
    plot = `<p class="perf-single" aria-label="单次 通过耗时 ${secondsText(values[0])}"><strong>${secondsText(values[0])}</strong><span>单次 通过耗时</span></p>`;
  } else if (n > 1) {
    const timeline = rows.map((item, index) => ({ item, index, round: Number(item.round), seconds: item.result === 'PASS' ? elapsedSeconds(item) : null }))
      .filter((entry) => Number.isFinite(entry.round) && entry.round > 0)
      .sort((a, b) => a.round - b.round || a.index - b.index);
    const elapsed = timeline.filter((entry) => entry.seconds != null);
    const timelineMax = Math.max(1, ...elapsed.map((entry) => entry.seconds));
    const firstRound = timeline.length ? timeline[0].round : 1;
    const lastRound = timeline.length ? timeline[timeline.length - 1].round : firstRound;
    const tx = (round) => 42 + (lastRound === firstRound ? 516 : (round - firstRound) / (lastRound - firstRound) * 516);
    const ty = (seconds) => 94 - (seconds / timelineMax) * 66;
    let previous = null;
    const lines = [];
    for (const entry of timeline) {
      const current = entry.seconds == null ? null : { round: entry.round, seconds: entry.seconds, x: tx(entry.round), y: ty(entry.seconds) };
      if (current && previous && entry.round === previous.round + 1) {
        lines.push(`<line class="perf-line-segment" x1="${previous.x.toFixed(2)}" y1="${previous.y.toFixed(2)}" x2="${current.x.toFixed(2)}" y2="${current.y.toFixed(2)}"/>`);
      }
      previous = current;
    }
    const dots = elapsed.map((entry) => {
      const cx = tx(entry.round);
      const cy = ty(entry.seconds);
      return `<circle class="perf-point" cx="${cx.toFixed(2)}" cy="${cy.toFixed(2)}" r="4"><title>第 ${escapeHTML(entry.round)} 轮 · ${secondsText(entry.seconds)}</title></circle><text x="${cx.toFixed(2)}" y="${Math.max(12, cy - 8).toFixed(2)}" text-anchor="middle" class="perf-round-label">r${escapeHTML(entry.round)}</text>`;
    }).join('');
    const maxLabel = secondsText(timelineMax);
    plot = `<div class="perf-chart-scroll"><svg class="perf-timeline" viewBox="0 0 600 132" role="img" aria-label="通过轮次耗时，单位秒" preserveAspectRatio="xMidYMid meet"><line class="perf-axis" x1="42" y1="96" x2="558" y2="96"/><line class="perf-guide" x1="42" y1="28" x2="558" y2="28"/><text class="perf-axis-label" x="42" y="118">${escapeHTML(firstRound)} 轮</text><text class="perf-axis-label" x="558" y="118" text-anchor="end">${escapeHTML(lastRound)} 轮</text><text class="perf-axis-label" x="42" y="22">${escapeHTML(maxLabel)}</text>${lines.join('')}${dots}</svg></div>`;
  }

  const stats = n
    ? `均值 ${secondsText(mean)} · 中位数 ${secondsText(median)} · 范围 ${range} · n=${n}`
    : '有效耗时 n=0';
  const source = escapeHTML(row.source_sha256 ?? '未知');
  return `<article class="panel perf-group"><h3 class="perf-title">${groupLabel(row)}</h3><p class="evidence-hash perf-source">平台 ${escapeHTML(row.platform ?? '未知')} · 源码 SHA-256 ${source}</p><p class="small muted perf-summary">通过 ${passes.length} · ${stats} · 失败 ${failed} · 中断 ${interrupted}</p>${plot}</article>`;
};

export function experimentChart(rows) {
  const groups = new Map();
  for (const row of Array.isArray(rows) ? rows : []) {
    const key = groupKey(row);
    if (!groups.has(key)) groups.set(key, { row, rows: [], passes: [], failed: 0, interrupted: 0 });
    const group = groups.get(key);
    group.rows.push(row);
    if (row.result === 'PASS') group.passes.push(row);
    else if (row.result === 'FAIL') group.failed += 1;
    else if (row.result === 'INTERRUPTED') group.interrupted += 1;
  }
  if (!groups.size) return '<p class="empty" role="status">实验尚未执行。</p>';
  return `<div class="experiment-chart">${[...groups.values()].map(renderGroup).join('')}</div>`;
}
