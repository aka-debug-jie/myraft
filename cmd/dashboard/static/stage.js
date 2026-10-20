export class Stage {
  constructor(host) {
    this.host = host;
    this.abort = new AbortController();
    this.nodes = new Map();
    this.edges = new Map();
    this.eventsSeen = new Set();
    this.scope = null;
    this.initialized = false;
    this.scale = 1;
    this.tx = 0;
    this.ty = 0;
    this.activeAnimations = new Set();
    this.suppressAnimation = false;
    this.destroyed = false;
    this.host.classList.add('raft-stage');
    this.host.replaceChildren();

    this.world = document.createElement('div');
    this.world.className = 'stage-world';
    this.world.style.cssText = 'position:absolute;inset:0;transform-origin:0 0;touch-action:none;';
    this.svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    this.svg.classList.add('stage-edges');
    this.svg.setAttribute('aria-hidden', 'true');
    this.svg.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;overflow:visible;pointer-events:none;';
    this.nodeLayer = document.createElement('div');
    this.nodeLayer.style.cssText = 'position:absolute;inset:0;';
    this.world.append(this.svg, this.nodeLayer);

    this.controls = document.createElement('div');
    this.controls.className = 'stage-controls';
    this.controls.setAttribute('role', 'group');
    this.controls.setAttribute('aria-label', '拓扑缩放和平移');
    this.controls.style.cssText = 'position:absolute;right:10px;top:10px;z-index:2;display:flex;gap:4px;';
    this.controls.append(
      this.makeControl('放大', '+', () => this.zoomBy(1.2)),
      this.makeControl('缩小', '−', () => this.zoomBy(1 / 1.2)),
      this.makeControl('适合视图', '适合', () => this.fit()),
    );
    this.host.style.position ||= 'relative';
    this.host.style.overflow = 'hidden';
    this.host.append(this.world, this.controls);

    this.world.addEventListener('wheel', e => {
      e.preventDefault();
      this.zoomAt(e.clientX, e.clientY, e.deltaY < 0 ? 1.12 : 1 / 1.12);
    }, {passive:false, signal:this.abort.signal});
    this.world.addEventListener('pointerdown', e => this.pointerDown(e), {signal:this.abort.signal});
    this.world.addEventListener('pointermove', e => this.pointerMove(e), {signal:this.abort.signal});
    this.world.addEventListener('pointerup', e => this.pointerUp(e), {signal:this.abort.signal});
    this.world.addEventListener('pointercancel', e => this.pointerUp(e), {signal:this.abort.signal});
    this.drag = null;
    this.pointers = new Map();
    this.pinch = null;
    this.resizeObserver = new ResizeObserver(() => this.layout());
    this.resizeObserver.observe(host);
    document.addEventListener('visibilitychange', () => {
      this.suppressAnimation = true;
      for (const animation of this.activeAnimations) animation.cancel();
    }, {capture:true, signal:this.abort.signal});
  }

  makeControl(label, text, action) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'btn stage-control';
    button.textContent = text;
    button.setAttribute('aria-label', label);
    button.addEventListener('click', action, {signal:this.abort.signal});
    return button;
  }

  update({nodes = [], members = [], selected, fresh = false, events = [], scope = ''} = {}) {
    if (this.destroyed) return;
    const scopeChanged = this.scope !== scope;
    if (!this.initialized || scopeChanged) {
      this.eventsSeen.clear();
      for (const event of events) if (Number.isFinite(event.seq)) this.eventsSeen.add(`${scope}:${event.seq}`);
      this.scale=1; this.tx=0; this.ty=0;
      for(const animation of this.activeAnimations) animation.cancel();
      this.scope = scope;
      this.initialized = true;
    } else {
      for (const event of events) {
        if (!Number.isFinite(event.seq)) continue;
        const key = `${scope}:${event.seq}`;
        if (this.eventsSeen.has(key)) continue;
        this.eventsSeen.add(key);
        if (!this.suppressAnimation && fresh && event.source === 'node' && event.node_id != null && event.node_event && ['election_started','leader_elected','log_replicated','log_committed','log_caught_up','node_recovered'].includes(event.name)) this.pulse(event.node_id);
      }
      while (this.eventsSeen.size > 2048) this.eventsSeen.delete(this.eventsSeen.values().next().value);
    }
    this.suppressAnimation = false;

    const memberIds = members.map(member => member?.id ?? member).filter(id => id != null).sort((a,b)=>a-b);
    const sampleById = new Map(nodes.map(node => [node.id, node]));
    const wanted = new Set(memberIds);
    for (const [id, button] of this.nodes) if (!wanted.has(id)) { button.remove(); this.nodes.delete(id); }
    for (const id of memberIds) {
      let button = this.nodes.get(id);
      if (!button) {
        button = document.createElement('button');
        button.type = 'button';
        button.className = 'stage-node';
        button.dataset.node = String(id);
        button.style.cssText = 'position:absolute;box-sizing:border-box;display:flex;flex-direction:column;align-items:center;justify-content:center;';
        const idLabel = document.createElement('span'); idLabel.className = 'stage-id'; idLabel.textContent = `#${id}`;
        const roleLabel = document.createElement('span'); roleLabel.className = 'stage-role';
        button.append(idLabel, roleLabel);
        this.nodeLayer.append(button);
        this.nodes.set(id, button);
      }
      const sample = sampleById.get(id);
      const state = fresh && sample?.reachable && sample?.identity_ok && !sample?.error ? sample?.status?.state || '未知' : '未知';
      const role = state.toLowerCase() === 'leader' ? 'leader' : state.toLowerCase() === 'follower' ? 'follower' : state.toLowerCase() === 'candidate' ? 'candidate' : 'unknown';
      button.classList.remove('leader','follower','candidate','unknown','selected');
      button.classList.add(role);
      if (id === selected) button.classList.add('selected');
      const reachable = sample?.reachable === true;
      const identityOK = sample?.identity_ok === true;
      button.setAttribute('aria-label', `节点 ${id}；角色 ${state}；${reachable ? '可达' : '不可达或未知'}；${identityOK ? '身份匹配' : '身份不匹配或未知'}；任期 ${sample?.status?.term ?? '未知'}；报告 Leader ${sample?.status?.leader_id ?? '未知'}`);
      button.querySelector('.stage-role').textContent = role === 'leader' ? 'Leader' : '';
    }

    this.samples = sampleById;
    this.members = memberIds;
    this.fresh = fresh;
    this.layout();
  }

  layout() {
    if (this.destroyed) return;
    const width = Math.max(1, this.host.clientWidth), height = Math.max(1, this.host.clientHeight), count = this.members?.length || 0;
    const key=[width,height,...(this.members||[])].join('/');
    if(this.layoutKey===key){this.drawEdges();return;}
    this.layoutKey=key;
    let worldWidth = width, worldHeight = height;
    const positions = new Map();
    this.host.classList.toggle('stage-dense',count>15);
    if (count >= 1 && count <= 15) {
      const rx = Math.max(0, (width - 100) * 0.39), ry = Math.max(0, (height - 100) * 0.39);
      this.members.forEach((id, index) => {
        const angle = -Math.PI / 2 + 2 * Math.PI * index / count;
        positions.set(id, [width / 2 + rx * Math.cos(angle), height / 2 + ry * Math.sin(angle)]);
      });
    } else if (count > 15) {
      const cols = Math.max(1, Math.ceil(Math.sqrt(count * width / height)));
      const rows = Math.ceil(count / cols);
      const cell = Math.max(64, Math.min((width-80)/cols, (height-80)/rows));
      worldWidth = Math.max(width, cols * cell + 80);
      worldHeight = Math.max(height, rows * cell + 80);
      const left=(worldWidth-cols*cell)/2, top=(worldHeight-rows*cell)/2;
      this.members.forEach((id, index) => positions.set(id, [left+(index % cols + 0.5) * cell, top+(Math.floor(index / cols) + 0.5) * cell]));
    }
    this.positions = positions;
    let separation=Infinity;
    if(count<=15){const points=[...positions.values()];for(let i=0;i<points.length;i++)for(let j=0;j<i;j++)separation=Math.min(separation,Math.hypot(points[i][0]-points[j][0],points[i][1]-points[j][1]));}
    for (const [id, button] of this.nodes) {
      const point = positions.get(id);
      if (!point) continue;
      const size = count >= 3 && count <= 15 ? Math.max(36, Math.min(100, separation * .76, Math.min(width,height)*.12)) : 48;
      button.style.width = `${size}px`; button.style.height = `${size}px`;
      button.style.left = `${point[0] - size / 2}px`; button.style.top = `${point[1] - size / 2}px`;
    }
    this.world.style.width = `${worldWidth}px`; this.world.style.height = `${worldHeight}px`;
    this.svg.setAttribute('viewBox', `0 0 ${worldWidth} ${worldHeight}`);
    this.drawEdges();
    this.applyTransform();
  }

  drawEdges() {
    const wanted = new Map();
    if (this.fresh && this.members) {
      const leaders = this.members.map(id => this.samples?.get(id)).filter(n => n && !n.error && n.reachable === true && n.identity_ok === true && String(n.status?.state).toLowerCase() === 'leader');
      for (const sample of this.members.map(id => this.samples?.get(id)).filter(Boolean)) {
        if (sample.error || !sample.reachable || !sample.identity_ok || String(sample.status?.state).toLowerCase() !== 'follower') continue;
        const leader = leaders.find(n => n.id === sample.status?.leader_id && n.status?.term === sample.status?.term);
        if (leader) wanted.set(sample.id, leader.id);
      }
    }
    for (const [id, line] of this.edges) if (!wanted.has(id)) { line.remove(); this.edges.delete(id); }
    for (const [from, to] of wanted) {
      let line = this.edges.get(from);
      if (!line) {
        line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
        line.setAttribute('class', 'stage-reported-edge');
        line.setAttribute('stroke', 'currentColor'); line.setAttribute('stroke-width', '2');
        line.setAttribute('stroke-dasharray', '5 5');
        this.svg.append(line); this.edges.set(from, line);
      }
      const a = this.positions?.get(from), b = this.positions?.get(to);
      if (!a || !b) { line.style.display = 'none'; continue; }
      line.style.display = '';
      line.setAttribute('x1', a[0]); line.setAttribute('y1', a[1]); line.setAttribute('x2', b[0]); line.setAttribute('y2', b[1]);
    }
  }

  pulse(id) {
    if (this.destroyed || document.hidden || matchMedia('(prefers-reduced-motion: reduce)').matches || this.activeAnimations.size >= 16) return;
    const button = this.nodes.get(id);
    if (!button || typeof button.animate !== 'function') return;
    const animation = button.animate([{transform:'scale(1)'},{transform:'scale(1.12)'},{transform:'scale(1)'}], {duration:420, easing:'ease-out'});
    this.activeAnimations.add(animation);
    animation.finished.catch(() => {}).finally(() => this.activeAnimations.delete(animation));
  }

  focus(id) {
    const button = this.nodes.get(id);
    if (!button) return;
    const rect = button.getBoundingClientRect(), host = this.host.getBoundingClientRect();
    this.tx += host.left + host.width / 2 - (rect.left + rect.width / 2);
    this.ty += host.top + host.height / 2 - (rect.top + rect.height / 2);
    this.applyTransform(); button.focus({preventScroll:true});
  }

  fit() {
    if (!this.world) return;
    const width = Math.max(1, this.host.clientWidth), height = Math.max(1, this.host.clientHeight);
    const scale = Math.min(1, width / this.world.offsetWidth, height / this.world.offsetHeight);
    this.scale = scale;
    this.tx = (width - this.world.offsetWidth * scale) / 2;
    this.ty = (height - this.world.offsetHeight * scale) / 2;
    this.applyTransform();
  }

  zoomBy(factor) { this.zoomAt(this.host.getBoundingClientRect().left + this.host.clientWidth / 2, this.host.getBoundingClientRect().top + this.host.clientHeight / 2, factor); }
  zoomAt(clientX, clientY, factor) {
    const rect = this.host.getBoundingClientRect(), x = clientX - rect.left, y = clientY - rect.top;
    const minimum=Math.min(.5,this.host.clientWidth / this.world.offsetWidth,this.host.clientHeight / this.world.offsetHeight);
    const next = Math.max(minimum, Math.min(3, this.scale * factor));
    this.tx = x - (x - this.tx) * next / this.scale; this.ty = y - (y - this.ty) * next / this.scale;
    this.scale = next; this.applyTransform();
  }
  applyTransform() { this.world.style.transform = `translate(${this.tx}px,${this.ty}px) scale(${this.scale})`; }

  pointerDown(event) {
    if (event.target.closest('button')) return;
    this.pointers.set(event.pointerId, [event.clientX, event.clientY]);
    this.world.setPointerCapture(event.pointerId);
    if (this.pointers.size === 1) this.drag = {x:event.clientX,y:event.clientY,tx:this.tx,ty:this.ty};
    else if (this.pointers.size === 2) {
      const points = [...this.pointers.values()];
      this.pinch = {distance:Math.hypot(points[0][0]-points[1][0],points[0][1]-points[1][1]),scale:this.scale,tx:this.tx,ty:this.ty,x:(points[0][0]+points[1][0])/2,y:(points[0][1]+points[1][1])/2}; this.drag = null;
    }
  }
  pointerMove(event) {
    if (!this.pointers.has(event.pointerId)) return;
    this.pointers.set(event.pointerId,[event.clientX,event.clientY]);
    if (this.pointers.size === 1 && this.drag) { this.tx=this.drag.tx+event.clientX-this.drag.x; this.ty=this.drag.ty+event.clientY-this.drag.y; this.applyTransform(); }
    else if (this.pointers.size === 2 && this.pinch) {
      const points=[...this.pointers.values()], distance=Math.hypot(points[0][0]-points[1][0],points[0][1]-points[1][1]);
      const centerX=(points[0][0]+points[1][0])/2, centerY=(points[0][1]+points[1][1])/2;
      this.scale=Math.max(0.5,Math.min(3,this.pinch.scale*distance/Math.max(1,this.pinch.distance)));
      const rect=this.host.getBoundingClientRect();
      const anchorX=this.pinch.x-rect.left, anchorY=this.pinch.y-rect.top;
      this.tx=centerX-rect.left-(anchorX-this.pinch.tx)*this.scale/this.pinch.scale;
      this.ty=centerY-rect.top-(anchorY-this.pinch.ty)*this.scale/this.pinch.scale;
      this.applyTransform();
    }
  }
  pointerUp(event) {
    this.pointers.delete(event.pointerId);
    if (this.pointers.size < 2) this.pinch = null;
    if (!this.pointers.size) this.drag = null;
    else if (this.pointers.size === 1) { const [x,y]=this.pointers.values().next().value; this.drag={x,y,tx:this.tx,ty:this.ty}; }
  }

  destroy() {
    if (this.destroyed) return;
    this.destroyed = true;
    this.abort.abort(); this.resizeObserver.disconnect();
    for (const animation of this.activeAnimations) animation.cancel();
    this.activeAnimations.clear(); this.nodes.clear(); this.edges.clear(); this.eventsSeen.clear();
    this.host.replaceChildren(); this.host.classList.remove('raft-stage');
  }
}
