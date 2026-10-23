import {geometry, route} from './topology.js';

export class Stage {
  constructor(host) {
    this.host = host;
    this.abort = new AbortController();
    this.nodes = new Map();
    this.edges = new Map();
    this.eventsSeen = new Set();
    this.scope = null;
    this.initialized = false;
    this.autoFitPending = false;
    this.viewChangedByUser = false;
    this.showAllRelations = true;
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
    this.controls.style.cssText = 'position:absolute;left:20px;bottom:24px;z-index:2;display:flex;gap:4px;';
    this.controls.append(
      this.makeControl('放大', '+', () => this.zoomBy(1.2)),
      this.makeControl('缩小', '−', () => this.zoomBy(1 / 1.2)),
      this.makeControl('适合视图', '适合', () => this.fit()),
      this.makeControl('按可读大小聚焦节点', '聚焦', () => {const id=this.selected??this.centerId??this.members?.[0],p=this.positions?.get(id);if(!p)return;this.viewChangedByUser=true;this.scale=1;this.tx=this.host.clientWidth/2-p[0];this.ty=this.host.clientHeight/2-p[1];this.applyTransform();this.focus(id);}),
    );
    this.relationControl = this.makeControl('聚焦选中节点关系', '关系聚焦', () => {
      this.showAllRelations = !this.showAllRelations;
      this.updateRelationControl();
      this.drawEdges();
    });
    this.relationControl.hidden = true;
    this.controls.append(this.relationControl);
    this.host.tabIndex = this.host.hasAttribute('tabindex') ? this.host.tabIndex : 0;
    this.host.setAttribute('role', 'group');
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
    this.host.addEventListener('click', e => {
      const node = e.target.closest?.('.stage-node');
      if (!node || !this.suppressedClicks?.has(node)) return;
      e.preventDefault(); e.stopImmediatePropagation(); this.suppressedClicks.delete(node);
    }, {capture:true, signal:this.abort.signal});
    this.host.addEventListener('focusin', e => {
      const node = e.target.closest?.('.stage-node');
      if (node) this.revealNode(Number(node.dataset.node));
    }, {signal:this.abort.signal});
    this.host.addEventListener('keydown', e => {
      if (e.target !== this.host) return;
      const step = e.shiftKey ? 80 : 40;
      if (e.key === 'ArrowLeft' || e.key === 'ArrowRight' || e.key === 'ArrowUp' || e.key === 'ArrowDown') {
        e.preventDefault(); this.viewChangedByUser = true;
        if (e.key === 'ArrowLeft') this.tx += step;
        if (e.key === 'ArrowRight') this.tx -= step;
        if (e.key === 'ArrowUp') this.ty += step;
        if (e.key === 'ArrowDown') this.ty -= step;
        this.applyTransform();
      }
    }, {signal:this.abort.signal});
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
    button.style.minHeight = '44px';
    button.style.minWidth = '44px';
    button.setAttribute('aria-label', label);
    button.addEventListener('click', action, {signal:this.abort.signal});
    return button;
  }

  update({nodes = [], members = [], selected, fresh = false, events = [], scope = '', snapshotSeq} = {}) {
    if (this.destroyed) return;
    const scopeChanged = this.scope !== scope;
    if (!this.initialized || scopeChanged) {
      this.eventsSeen.clear();
      this.centerId=null;this.slotOrder=[];this.pendingLeader=null;this.lastSnapshotSeq=null;this.layoutKey=null;this.pathKey=null;
      for (const event of events) if (Number.isFinite(event.seq)) this.eventsSeen.add(`${scope}:${event.seq}`);
      this.scale=1; this.tx=0; this.ty=0; this.autoFitPending = true; this.viewChangedByUser = false;
      this.showAllRelations = true;
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
      button.querySelector('.stage-role').textContent = ({leader:'Leader',candidate:'竞选中',unknown:!fresh?'过期':'未知'})[role] || 'Follower';
      button.classList.toggle('unreachable',sample?.reachable===false);
      button.classList.toggle('identity-error',sample?.identity_ok===false);
      button.setAttribute('aria-pressed',String(id===selected));
    }

    this.samples = sampleById;
    this.members = memberIds;
    this.fresh = fresh;
    this.selected = selected;
    this.observeLeader(snapshotSeq);
    this.relationControl.hidden = memberIds.length <= 15;
    this.updateRelationControl();
    this.layout();
  }

  observeLeader(seq) {
    if(this.slotOrder.length!==this.members.length||this.members.some(id=>!this.slotOrder.includes(id))){
      this.slotOrder=[...this.members];this.centerId=null;this.pendingLeader=null;
    }
    const leaders=this.fresh?this.members.map(id=>this.samples.get(id)).filter(n=>n?.reachable&&n.identity_ok&&!n.error&&n.status?.state==='Leader'):[];
    if(leaders.length!==1){this.pendingLeader=null;return;}
    const leader=leaders[0],key=JSON.stringify([leader.id,leader.status.instance_id,leader.status.term]);
    if(!Number.isFinite(seq)||!leader.status.instance_id){this.pendingLeader=null;return;}
    if(this.pendingLeader?.key!==key){this.pendingLeader={key,seq};return;}
    if(seq<=this.pendingLeader.seq||leader.id===this.centerId)return;
    const old=this.centerId;
    if(old!=null){const index=this.slotOrder.indexOf(leader.id);this.slotOrder[this.slotOrder.indexOf(old)]=leader.id;this.slotOrder[index]=old;}
    this.centerId=leader.id;this.layoutKey=null;
    this.animateLayout=old!=null&&!matchMedia('(prefers-reduced-motion: reduce)').matches;
  }

  updateRelationControl() {
    this.relationControl.textContent=this.showAllRelations?'关系聚焦':'全部关系';
    this.relationControl.setAttribute('aria-label',this.showAllRelations?'聚焦选中节点关系':'显示全部已观测关系');
    this.relationControl.setAttribute('aria-pressed',String(!this.showAllRelations));
    this.relationControl.disabled=this.selected==null&&this.showAllRelations;
  }

  layout() {
    if(this.destroyed)return;
    const width=Math.max(1,this.host.clientWidth),height=Math.max(1,this.host.clientHeight);
    const resized=this.layoutSize&&(this.layoutSize[0]!==width||this.layoutSize[1]!==height);
    this.layoutSize=[width,height];
    const key=[width,height,this.centerId,...(this.slotOrder||[])].join('/');
    if(this.layoutKey!==key){
      this.layoutKey=key;this.pathKey=null;
      this.geom=geometry(this.members||[],this.slotOrder||[],this.centerId,width,height);
      const before=this.positions;this.positions=this.geom.positions;
      this.host.classList.toggle('stage-dense',this.geom.dense);
      for(const[id,button]of this.nodes){
        const p=this.positions.get(id);if(!p)continue;const size=this.geom.radii.get(id)*2;
        button.style.width=`${size}px`;button.style.height=`${size}px`;
        button.style.left=`${p[0]-size/2}px`;button.style.top=`${p[1]-size/2}px`;
        button.classList.toggle('center-slot',id===this.centerId);
        if(this.animateLayout&&before?.has(id)&&distanceMoved(before.get(id),p)>1){
          const prev=before.get(id),animation=button.animate([{translate:`${prev[0]-p[0]}px ${prev[1]-p[1]}px`},{translate:'0px 0px'}],{duration:280,easing:'cubic-bezier(.2,.8,.2,1)'});
          this.activeAnimations.add(animation);animation.finished.catch(()=>{}).finally(()=>this.activeAnimations.delete(animation));
        }
      }
      this.world.style.width=`${this.geom.width}px`;this.world.style.height=`${this.geom.height}px`;
      this.svg.setAttribute('viewBox',`0 0 ${this.geom.width} ${this.geom.height}`);
      if(this.animateLayout){const animation=this.svg.animate([{opacity:0},{opacity:0,offset:.8},{opacity:1}],{duration:320});this.activeAnimations.add(animation);animation.finished.catch(()=>{}).finally(()=>this.activeAnimations.delete(animation));}
      this.animateLayout=false;
    }
    this.drawEdges();this.applyTransform();
    if(this.autoFitPending||(resized&&!this.viewChangedByUser)){this.fit();this.autoFitPending=false;}
    else if(resized&&this.selected!=null)this.revealNode(this.selected);
  }

  drawEdges() {
    const wanted=new Map();
    if(this.fresh&&this.members){
      const leaders=new Map(this.members.map(id=>this.samples.get(id)).filter(n=>n?.reachable&&n.identity_ok&&!n.error&&n.status?.state==='Leader').map(n=>[n.id,n]));
      for(const id of this.members){const n=this.samples.get(id);if(!n?.reachable||!n.identity_ok||n.error||n.status?.state!=='Follower')continue;
        const leader=leaders.get(n.status.leader_id);if(leader&&leader.status.term===n.status.term)wanted.set(id,leader.id);
      }
    }
    const key=this.layoutKey+'|'+[...wanted].map(([a,b])=>`${a}:${b}`).join(',');
    const changed=key!==this.pathKey;this.pathKey=key;
    for(const[id,line]of this.edges)if(!wanted.has(id)){line.remove();this.edges.delete(id);}
    for(const[from,to]of wanted){
      let line=this.edges.get(from);
      if(!line){line=document.createElementNS('http://www.w3.org/2000/svg','path');line.setAttribute('class','stage-reported-edge');line.setAttribute('fill','none');line.setAttribute('vector-effect','non-scaling-stroke');const title=document.createElementNS('http://www.w3.org/2000/svg','title');line.append(title);this.svg.append(line);this.edges.set(from,line);}
      line.dataset.from=String(from);line.dataset.to=String(to);
      line.firstElementChild.textContent=`节点 #${from} 报告 Leader #${to} · 任期 ${this.samples.get(from).status.term}；非实测链路`;
      if(changed)line.setAttribute('d',route(this.geom,from,to));
      const selected=from===this.selected||to===this.selected;
      line.classList.toggle('selected',selected);line.classList.toggle('subdued',this.selected!=null&&!selected);
      line.style.display=(!this.showAllRelations&&!selected)?'none':'';
    }
    this.host.dataset.relations=String(wanted.size);
    this.host.dataset.visibleRelations=String([...wanted].filter(([a,b])=>this.showAllRelations||a===this.selected||b===this.selected).length);
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
    const p=this.positions?.get(id),radius=this.geom?.radii.get(id)||22;
    const readable=Math.min(1,44/(radius*2));
    if(p&&this.scale<readable){this.viewChangedByUser=true;this.scale=readable;this.tx=this.host.clientWidth/2-p[0]*this.scale;this.ty=this.host.clientHeight/2-p[1]*this.scale;this.applyTransform();}
    this.revealNode(id); button.focus({preventScroll:true});
  }

  revealNode(id) {
    const button = this.nodes.get(id);
    if (!button) return;
    const node = button.getBoundingClientRect(), host = this.host.getBoundingClientRect(), margin = 8;
    if (node.left < host.left + margin) this.tx += host.left + margin - node.left;
    else if (node.right > host.right - margin) this.tx -= node.right - host.right + margin;
    if (node.top < host.top + margin) this.ty += host.top + margin - node.top;
    else if (node.bottom > host.bottom - margin) this.ty -= node.bottom - host.bottom + margin;
    this.applyTransform();
  }

  fit() {
    if (!this.world) return;
    const width = Math.max(1, this.host.clientWidth), height = Math.max(1, this.host.clientHeight);
    const dense=this.members?.length>15;
    const scale = Math.min(1, Math.max(1,width-(dense?24:0)) / this.world.offsetWidth, Math.max(1,height-(dense?144:0)) / this.world.offsetHeight);
    this.viewChangedByUser=false;
    this.scale = scale;
    this.tx = (width - this.world.offsetWidth * scale) / 2;
    this.ty = (height - this.world.offsetHeight * scale) / 2;
    this.applyTransform();
  }

  zoomBy(factor) { this.zoomAt(this.host.getBoundingClientRect().left + this.host.clientWidth / 2, this.host.getBoundingClientRect().top + this.host.clientHeight / 2, factor); }
  minimumScale() { const dense=this.members?.length>15;return Math.min(.5, Math.max(1,this.host.clientWidth-(dense?24:0)) / this.world.offsetWidth, Math.max(1,this.host.clientHeight-(dense?144:0)) / this.world.offsetHeight); }
  zoomAt(clientX, clientY, factor) {
    this.viewChangedByUser=true;
    const rect = this.host.getBoundingClientRect(), x = clientX - rect.left, y = clientY - rect.top;
    const minimum=this.minimumScale();
    const next = Math.max(minimum, Math.min(3, this.scale * factor));
    this.tx = x - (x - this.tx) * next / this.scale; this.ty = y - (y - this.ty) * next / this.scale;
    this.scale = next; this.applyTransform();
  }
  applyTransform() { this.world.style.transform = `translate(${this.tx}px,${this.ty}px) scale(${this.scale})`; }

  pointerDown(event) {
    if (event.target.closest('.stage-control')) return;
    const targetNode = event.target.closest('.stage-node');
    const pointer = {x:event.clientX,y:event.clientY,startX:event.clientX,startY:event.clientY,targetNode,moved:false};
    this.pointers.set(event.pointerId, pointer);
    (targetNode || this.world).setPointerCapture(event.pointerId);
    if (this.pointers.size === 1) this.drag = {x:event.clientX,y:event.clientY,tx:this.tx,ty:this.ty};
    else if (this.pointers.size === 2) {
      const points = [...this.pointers.values()].map(p=>[p.x,p.y]);
      this.pinch = {distance:Math.hypot(points[0][0]-points[1][0],points[0][1]-points[1][1]),scale:this.scale,tx:this.tx,ty:this.ty,x:(points[0][0]+points[1][0])/2,y:(points[0][1]+points[1][1])/2}; this.drag = null;
      for (const p of this.pointers.values()) if (p.targetNode) p.moved = true;
    }
  }
  pointerMove(event) {
    if (!this.pointers.has(event.pointerId)) return;
    const pointer=this.pointers.get(event.pointerId);
    pointer.x=event.clientX; pointer.y=event.clientY;
    if (Math.hypot(event.clientX-pointer.startX,event.clientY-pointer.startY)>6) {pointer.moved=true;this.viewChangedByUser=true;}
    if (this.pointers.size === 1 && this.drag && pointer.moved) { this.tx=this.drag.tx+event.clientX-this.drag.x; this.ty=this.drag.ty+event.clientY-this.drag.y; this.applyTransform(); }
    else if (this.pointers.size === 2 && this.pinch) {
      this.viewChangedByUser=true;
      const points=[...this.pointers.values()].map(p=>[p.x,p.y]), distance=Math.hypot(points[0][0]-points[1][0],points[0][1]-points[1][1]);
      const centerX=(points[0][0]+points[1][0])/2, centerY=(points[0][1]+points[1][1])/2;
      this.scale=Math.max(this.minimumScale(),Math.min(3,this.pinch.scale*distance/Math.max(1,this.pinch.distance)));
      const rect=this.host.getBoundingClientRect();
      const anchorX=this.pinch.x-rect.left, anchorY=this.pinch.y-rect.top;
      this.tx=centerX-rect.left-(anchorX-this.pinch.tx)*this.scale/this.pinch.scale;
      this.ty=centerY-rect.top-(anchorY-this.pinch.ty)*this.scale/this.pinch.scale;
      this.applyTransform();
    }
  }
  pointerUp(event) {
    const pointer=this.pointers.get(event.pointerId);
    if (pointer?.moved && pointer.targetNode) {
      (this.suppressedClicks ||= new Set()).add(pointer.targetNode);
      setTimeout(() => this.suppressedClicks?.delete(pointer.targetNode), 0);
    }
    this.pointers.delete(event.pointerId);
    if (this.pointers.size < 2) this.pinch = null;
    if (!this.pointers.size) this.drag = null;
    else if (this.pointers.size === 1) { const remaining=this.pointers.values().next().value; this.drag={x:remaining.x,y:remaining.y,tx:this.tx,ty:this.ty}; }
  }

  destroy() {
    if (this.destroyed) return;
    this.destroyed = true;
    this.abort.abort(); this.resizeObserver.disconnect();
    for (const animation of this.activeAnimations) animation.cancel();
    this.activeAnimations.clear(); this.nodes.clear(); this.edges.clear(); this.eventsSeen.clear();
    this.host.replaceChildren(); this.host.classList.remove('raft-stage');this.geom=null;this.positions=null;
  }
}

function distanceMoved(a,b){return Math.hypot(a[0]-b[0],a[1]-b[1]);}
