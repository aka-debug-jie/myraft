import {geometry, route, pathSegments} from './topology.js';

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
    this.groupIndex=0;this.thumbnail=false;
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
    this.hitLayer=document.createElementNS(this.svg.namespaceURI,'g');this.svg.append(this.hitLayer);
    this.svg.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;overflow:visible;pointer-events:none;';
    this.nodeLayer = document.createElement('div');
    this.nodeLayer.style.cssText = 'position:absolute;inset:0;pointer-events:none;';
    this.world.append(this.svg, this.nodeLayer);
    this.svg.addEventListener('pointermove',e=>this.inspectEdge(e),{signal:this.abort.signal});
    this.svg.addEventListener('pointerleave',()=>{this.hovered=null;this.paintRelations();},{signal:this.abort.signal});

    this.controls = document.createElement('div');
    this.controls.className = 'stage-controls';
    this.controls.setAttribute('role', 'group');
    this.controls.setAttribute('aria-label', '拓扑缩放和平移');
    
    this.controls.append(
      this.makeControl('放大', '+', () => this.zoomBy(1.2)),
      this.makeControl('缩小', '−', () => this.zoomBy(1 / 1.2)),
      this.makeControl('适合视图', '适合', () => this.fit()),
      this.makeControl('按可读大小聚焦节点', '聚焦', () => {const id=this.selected??this.displayCenter??this.members?.[0];this.focus(id);const p=this.positions?.get(id);if(!p)return;this.viewChangedByUser=true;this.scale=1;this.tx=this.host.clientWidth/2-p[0];this.ty=this.host.clientHeight/2-p[1];this.applyTransform();this.focus(id);}),
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
    this.relationNote=document.createElement('div');
    this.relationNote.className='stage-relation-note';this.relationNote.hidden=true;
    this.relationNote.setAttribute('role','status');
    this.orientation=document.createElement('button');this.orientation.type='button';
    this.orientation.className='stage-orientation';this.orientation.hidden=true;
    this.orientation.setAttribute('aria-label','返回全景');
    this.orientation.addEventListener('click',()=>this.fit(),{signal:this.abort.signal});
    this.controls.append(this.orientation);
    this.groupControls=document.createElement('div');this.groupControls.className='stage-groups';
    this.groupPrev=this.makeControl('上一组','上一组',()=>this.changeGroup(-1));
    this.groupNext=this.makeControl('下一组','下一组',()=>this.changeGroup(1));
    this.groupLabel=document.createElement('span');this.groupLabel.className='group-label';this.groupLabel.setAttribute('aria-live','polite');
    this.overviewControl=this.makeControl('全部节点缩略视图','全部缩略',()=>{this.thumbnail=!this.thumbnail;this.autoFitPending=true;this.layoutKey=null;this.layout();});
    this.groupControls.append(this.groupPrev,this.groupLabel,this.groupNext,this.overviewControl);
    this.centerNotice=document.createElement('div');this.centerNotice.className='center-notice';this.centerNotice.setAttribute('role','status');
    this.host.append(this.world,this.controls,this.relationNote,this.groupControls,this.centerNotice);

    this.world.addEventListener('wheel', e => {
      if(e.ctrlKey||e.metaKey){e.preventDefault();if(e.deltaY)this.zoomAt(e.clientX,e.clientY,Math.exp(-e.deltaY*.002));}
      else if(this.viewChangedByUser){e.preventDefault();this.tx-=e.deltaX;this.ty-=e.deltaY;this.applyTransform();}
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
      if(node){this.tabNode=Number(node.dataset.node);this.updateTabStops();this.revealNode(this.tabNode);}
    }, {signal:this.abort.signal});
    this.host.addEventListener('keydown', e => {
      const node=e.target.closest('.stage-node');
      if(node&&['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','Home','End'].includes(e.key)){
        e.preventDefault();const i=this.members.indexOf(Number(node.dataset.node));
        const next=e.key==='Home'?0:e.key==='End'?this.members.length-1:(i+(['ArrowLeft','ArrowUp'].includes(e.key)?-1:1)+this.members.length)%this.members.length;
        this.focus(this.members[next]);return;
      }
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
      this.groupIndex=0;this.thumbnail=false;this.previousSelected=null;this.centerId=null;this.displayCenter=null;this.hovered=null;this.focusedNode=null;this.slotOrder=[];this.pendingLeader=null;this.lastSnapshotSeq=null;this.layoutKey=null;this.pathKey=null;
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
        button.style.cssText = 'position:absolute;box-sizing:border-box;display:flex;flex-direction:column;align-items:center;justify-content:center;pointer-events:auto;';
        const idLabel = document.createElement('span'); idLabel.className = 'stage-id'; idLabel.textContent = `#${id}`;
        const roleLabel = document.createElement('span'); roleLabel.className = 'stage-role';
        button.append(idLabel, roleLabel);
        button.addEventListener('pointerenter',()=>{if(!this.pointers.size){this.hovered=id;this.paintRelations();}},{signal:this.abort.signal});
        button.addEventListener('pointerleave',()=>{this.hovered=null;this.paintRelations();},{signal:this.abort.signal});
        button.addEventListener('focus',()=>{this.focusedNode=id;this.paintRelations();},{signal:this.abort.signal});
        button.addEventListener('blur',()=>{this.focusedNode=null;this.paintRelations();},{signal:this.abort.signal});
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
      button.setAttribute('aria-label', `节点 ${id}；角色 ${state}；${reachable ? '可达' : '不可达或未知'}；${!fresh||!reachable?'身份未核验':identityOK?'身份匹配':'身份不匹配'}；任期 ${sample?.status?.term ?? '未知'}；报告 Leader ${sample?.status?.leader_id ?? '未知'}`);
      button.querySelector('.stage-role').textContent = ({leader:'Leader',candidate:'竞选中',unknown:!fresh?'过期':!reachable?'不可达':'未知'})[role] || 'Follower';
      button.classList.toggle('unreachable',sample?.reachable===false);
      button.classList.toggle('identity-error',fresh&&sample?.reachable===true&&sample?.identity_ok===false);
      button.setAttribute('aria-pressed',String(id===selected));
    }

    this.samples = sampleById;
    this.members = memberIds;
    this.fresh = fresh;
    this.selectionChanged=selected!==this.selected;this.selected = selected;
    this.observeLeader(snapshotSeq);
    this.relationControl.hidden = memberIds.length <= 15;
    this.updateRelationControl();
    this.layout();
  }

  observeLeader(seq) {
    if(this.slotOrder.length!==this.members.length||this.members.some(id=>!this.slotOrder.includes(id))){
      this.slotOrder=[...this.members];this.centerId=null;this.displayCenter=null;this.pendingLeader=null;this.autoFitPending=true;this.viewChangedByUser=false;
    }
    const leaders=this.fresh?this.members.map(id=>this.samples.get(id)).filter(n=>n?.reachable&&n.identity_ok&&!n.error&&n.status?.state==='Leader'):[];
    if(leaders.length!==1){this.pendingLeader=null;return;}
    const leader=leaders[0],key=JSON.stringify([leader.id,leader.status.instance_id,leader.status.term]);
    if(!Number.isFinite(seq)||!leader.status.instance_id){this.pendingLeader=null;return;}
    // First placement is presentation only. Two distinct observations still confirm changes.
    if(this.displayCenter==null)this.displayCenter=leader.id;
    if(this.pendingLeader?.key!==key){this.pendingLeader={key,seq};return;}
    if(seq<=this.pendingLeader.seq||leader.id===this.centerId)return;
    const old=this.displayCenter;
    this.centerId=leader.id;this.displayCenter=leader.id;this.layoutKey=null;
    this.animateLayout=old!=null&&old!==leader.id&&!matchMedia('(prefers-reduced-motion: reduce)').matches;
  }

  updateRelationControl() {
    this.relationControl.textContent=this.showAllRelations?'关系聚焦':'全部关系';
    this.relationControl.setAttribute('aria-label',this.showAllRelations?'聚焦选中节点关系':'显示全部已观测关系');
    this.relationControl.setAttribute('aria-pressed',String(!this.showAllRelations));
    const follower=this.edges.has(this.selected);
    this.relationControl.disabled=!follower&&this.showAllRelations;
    this.relationControl.title=follower?'单独查看此 Follower 报告的关系':'选择 Follower 或悬停一条关系线';
  }

  layout() {
    if(this.destroyed)return;
    const width=Math.max(1,this.host.clientWidth),height=Math.max(1,this.host.clientHeight);
    const resized=this.layoutSize&&(this.layoutSize[0]!==width||this.layoutSize[1]!==height);
    this.layoutSize=[width,height];
    const active=this.samples?.get(this.displayCenter),center=this.fresh&&active?.reachable&&active.identity_ok&&!active.error&&active.status?.state==='Leader'?this.displayCenter:null;
    const all=this.members||[];
    const capacityKey=[width,height,...all].join('/');
    if(this.capacityKey!==capacityKey){
      let count=all.length;
      while(count>2){const ids=all.slice(0,count);if(geometry(ids,ids,-1,width,height).fits)break;count--;}
      this.readableCapacity=Math.max(1,count);this.capacityKey=capacityKey;
    }
    const capacity=this.thumbnail?all.length:this.readableCapacity;
    this.capacity=Math.max(1,capacity);this.groupCount=Math.max(1,Math.ceil(all.length/this.capacity));
    if((this.selectionChanged||resized)&&this.selected!=null)this.groupIndex=Math.floor(all.indexOf(this.selected)/this.capacity);
    this.selectionChanged=false;this.groupIndex=Math.max(0,Math.min(this.groupCount-1,this.groupIndex));
    const group=this.thumbnail?all:all.slice(this.groupIndex*this.capacity,(this.groupIndex+1)*this.capacity);
    const visible=new Set(group);if(center!=null)visible.add(center);this.visibleIds=visible;
    const key=[width,height,center,this.thumbnail,this.groupIndex,...group].join('/');
    if(this.layoutKey!==key){
      this.layoutKey=key;this.pathKey=null;
      const worldWidth=this.thumbnail?Math.max(width,all.length*28):width,worldHeight=this.thumbnail?Math.max(height,all.length*18):height;
      this.geom=geometry([...visible],group,center,worldWidth,worldHeight);
      const before=this.positions;this.positions=this.geom.positions;
      this.host.classList.toggle('stage-dense',this.geom.dense);this.host.classList.toggle('stage-compact',this.geom.compact);
      for(const[id,button]of this.nodes){
        button.hidden=!visible.has(id);const p=this.positions.get(id);if(!p)continue;const size=this.geom.radii.get(id)*2;
        button.style.width=`${size}px`;button.style.height=`${size}px`;
        button.style.left=`${p[0]-size/2}px`;button.style.top=`${p[1]-size/2}px`;
        button.classList.toggle('center-slot',id===center);
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
    this.groupControls.hidden=this.groupCount===1&&!this.thumbnail;
    this.groupLabel.textContent=this.thumbnail?`全部 ${all.length} 节点 · 缩略视图`:`第 ${this.groupIndex+1}/${this.groupCount} 组 · 成员 #${group[0]??'—'}–#${group.at(-1)??'—'} / 共 ${all.length}`;
    this.groupPrev.hidden=this.groupNext.hidden=this.thumbnail;
    this.groupPrev.disabled=this.groupIndex===0;this.groupNext.disabled=this.groupIndex===this.groupCount-1;
    this.overviewControl.textContent=this.thumbnail?'可读分组':'全部缩略';
    this.updateTabStops();this.updateCenterNotice(center);this.drawEdges();this.applyTransform();
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
    for(const[id,line]of this.edges)if(!wanted.has(id)){line.hit.remove();line.remove();this.edges.delete(id);}
    for(const[from,to]of wanted){
      let line=this.edges.get(from);
      if(!line){
        line=document.createElementNS('http://www.w3.org/2000/svg','path');
        line.setAttribute('class','stage-reported-edge');line.setAttribute('fill','none');line.setAttribute('vector-effect','non-scaling-stroke');
        const title=document.createElementNS('http://www.w3.org/2000/svg','title');line.append(title);line.hit=document.createElementNS(this.svg.namespaceURI,'path');
        line.hit.setAttribute('class','stage-edge-hit');line.hit.setAttribute('fill','none');line.hit.setAttribute('vector-effect','non-scaling-stroke');
        line.hit.dataset.from=String(from);this.hitLayer.append(line.hit);this.svg.append(line);this.edges.set(from,line);
      }
      line.dataset.from=String(from);line.dataset.to=String(to);
      line.firstElementChild.textContent=`节点 #${from} 报告 Leader #${to} · 任期 ${this.samples.get(from).status.term}；非实测链路`;
      if(changed){const d=route(this.geom,from,to);line.setAttribute('d',d);line.hit.setAttribute('d',d);line.segments=pathSegments(d);}
    }
    this.host.dataset.relations=String(wanted.size);
    if(!wanted.has(this.selected))this.showAllRelations=true;
    this.updateRelationControl();this.paintRelations();
  }

  inspectEdge(event) {
    if(this.pointers.size)return;
    const p=new DOMPoint(event.clientX,event.clientY).matrixTransform(this.svg.getScreenCTM().inverse());
    let closest,limit=(6/this.scale)**2;
    for(const[id,line]of this.edges){if(line.style.display==='none')continue;
      for(const[a,b]of line.segments){
        const dx=b[0]-a[0],dy=b[1]-a[1],length=dx*dx+dy*dy;
        const t=length?Math.max(0,Math.min(1,((p.x-a[0])*dx+(p.y-a[1])*dy)/length)):0;
        const squared=(p.x-a[0]-t*dx)**2+(p.y-a[1]-t*dy)**2;
        if(squared<limit){limit=squared;closest=id;}
      }
    }
    if(this.hovered!==closest){this.hovered=closest;this.paintRelations();}
  }

  paintRelations() {
    // Selecting a Leader is not a request to emphasize every incident edge.
    const from=[this.hovered,this.focusedNode,this.selected].find(id=>this.visibleIds?.has(id)&&this.edges.has(id)&&this.visibleIds.has(Number(this.edges.get(id).dataset.to)));
    const active=this.edges.get(from),to=active?Number(active.dataset.to):null;
    let visible=0;
    for(const[id,line]of this.edges){
      line.classList.toggle('selected',id===from);
      line.classList.toggle('subdued',from!=null&&id!==from);
      line.style.display=(!this.visibleIds?.has(id)||!this.visibleIds?.has(Number(line.dataset.to))||this.thumbnail&&id!==from||!this.showAllRelations&&from!=null&&id!==from)?'none':'';
      line.hit.style.display=line.style.display;if(line.style.display!=='none')visible++;
    }
    for(const[id,node]of this.nodes){
      node.classList.toggle('related',id===from||id===to);
      node.classList.toggle('unrelated',from!=null&&id!==from&&id!==to&&id!==this.selected);
    }
    this.host.dataset.visibleRelations=String(visible);
    const leader=this.samples?.get(this.selected);
    const leaderSelected=this.fresh&&leader?.reachable&&leader.identity_ok&&!leader.error&&leader.status?.state==='Leader';
    this.relationNote.hidden=!active&&!leaderSelected;
    if(!active&&leaderSelected)this.relationNote.textContent=`Leader #${this.selected} · ${[...this.edges.values()].filter(e=>Number(e.dataset.to)===this.selected).length} 条有效报告关系 · 非复制确认`;
    if(active)this.relationNote.textContent=`#${from} 报告 Leader #${to} · Term ${this.samples.get(from)?.status?.term} · 非实测链路`;
  }

  changeGroup(delta){this.groupIndex+=delta;this.hovered=null;this.focusedNode=null;this.showAllRelations=true;this.autoFitPending=true;this.viewChangedByUser=false;this.layoutKey=null;this.host.dispatchEvent(new CustomEvent('stage-clear-selection',{bubbles:true}));this.layout();}
  updateTabStops(){
    const visible=[...this.nodes].filter(([,n])=>!n.hidden).map(([id])=>id);
    if(!visible.includes(this.tabNode))this.tabNode=visible.includes(this.selected)?this.selected:visible[0];
    for(const[id,node]of this.nodes)node.tabIndex=id===this.tabNode?0:-1;
  }
  clearSelection(){this.selected=undefined;this.hovered=null;this.focusedNode=null;this.showAllRelations=true;for(const node of this.nodes.values()){node.classList.remove('selected');node.setAttribute('aria-pressed','false');}this.paintRelations();this.updateRelationControl();}
  updateCenterNotice(center){
    const valid=this.fresh?[...this.samples.values()].filter(n=>n.reachable&&n.identity_ok&&!n.error):[];
    const leaders=valid.filter(n=>n.status?.state==='Leader'),candidates=valid.filter(n=>n.status?.state==='Candidate');
    this.centerNotice.hidden=center!=null;
    this.centerNotice.textContent=!this.fresh?'等待新鲜观测':leaders.length>1?'多个本地 Leader · 等待观测稳定':leaders.length===1?`观测到 Leader #${leaders[0].id} · 等待稳定`:candidates.length?`正在选举 · ${candidates.length} 个候选节点 · 观测任期 ${[...new Set(candidates.map(n=>n.status.term))].join('/')}`:'尚未观察到 Leader';
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
    if(this.thumbnail){this.thumbnail=false;this.groupIndex=Math.floor(this.members.indexOf(id)/this.readableCapacity);this.autoFitPending=true;this.layoutKey=null;this.layout();}
    const button = this.nodes.get(id);
    if (!button) return;
    if(!this.visibleIds?.has(id)&&this.capacity){this.groupIndex=Math.floor(this.members.indexOf(id)/this.capacity);this.autoFitPending=true;this.layoutKey=null;this.layout();}
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
    const scale = Math.min(1,width/this.world.offsetWidth,height/this.world.offsetHeight);
    this.viewChangedByUser=false;
    this.scale = scale;
    this.tx = (width - this.world.offsetWidth * scale) / 2;
    this.ty = (height - this.world.offsetHeight * scale) / 2;
    this.applyTransform();
  }

  zoomBy(factor) { this.zoomAt(this.host.getBoundingClientRect().left + this.host.clientWidth / 2, this.host.getBoundingClientRect().top + this.host.clientHeight / 2, factor); }
  minimumScale() {return Math.min(1,this.host.clientWidth/this.world.offsetWidth,this.host.clientHeight/this.world.offsetHeight);}
  zoomAt(clientX, clientY, factor) {
    this.viewChangedByUser=true;
    const rect = this.host.getBoundingClientRect(), x = clientX - rect.left, y = clientY - rect.top;
    const minimum=this.minimumScale();
    const next = Math.max(minimum, Math.min(3, this.scale * factor));
    this.tx = x - (x - this.tx) * next / this.scale; this.ty = y - (y - this.ty) * next / this.scale;
    this.scale = next; this.applyTransform();
  }
  applyTransform() {
    this.world.style.transform=`translate(${this.tx}px,${this.ty}px) scale(${this.scale})`;this.host.classList.toggle('stage-thumbnail',this.thumbnail);
    if(this.orientation){
      this.orientation.hidden=!this.viewChangedByUser;
      this.orientation.textContent=`${Math.round(this.scale*100)}% · 返回全景`;
    }
  }

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
      for (const p of this.pointers.values()) p.moved = true;
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
    if(pointer&&!pointer.moved&&!pointer.targetNode&&event.type==='pointerup')this.host.dispatchEvent(new CustomEvent('stage-clear-selection',{bubbles:true}));
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
