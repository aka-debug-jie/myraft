import * as api from './api.js';
import {Stage} from './stage.js';
import {pages,esc,icon,age,fresh,labels,actionReason,activeExperiment,overview,logView,faults,experiments,evidence,settings,nodeDetail,stageNodes,stageNotice,faultContent,compareLogs,workflow,lessonDock,stageChrome,stageLegend,taskSummary,taskBody} from './views.js';

const validPage=value=>pages.some(([id])=>id===value)?value:'overview';
const state={page:validPage(location.hash.slice(1)),selected:1,bootstrap:null,frame:null,connected:false,pending:false,pendingKind:'',
  logNodes:[],logFrom:1,logLimit:32,logQuery:null,logData:{},logLoading:false,logError:'',events:[],gap:false,streamLoss:0,lastStreamDrop:0,
  drafts:{},detailOpen:false,demoOpen:false,actionError:null,lastReceipt:null};
const views={overview,logs:logView,faults,experiments,evidence,settings};
const $=id=>document.getElementById(id);
const scopeKey=s=>[s.frame?.controller_id||s.bootstrap?.controller_id,s.frame?.session?.id||'',s.frame?.generation||s.bootstrap?.generation].join('/');
let stream,stage,renderedPage='',renderedScope='',navTimer,toastTimer,bootstrapRequest=0,logRequest=0,logAbort,pinned=false,modalScope='',modalInvoker;
let rendering=false,bootstrapPending=0,bootstrapNeeded=false,bootstrapRetryAt=0;
const workbench=document.createElement('div');workbench.id='workbench';
workbench.innerHTML='<button class="demo-trigger btn" data-act="demo" aria-controls="demo-drawer" aria-expanded="false">演示流程</button><aside id="demo-drawer" class="demo-drawer" aria-label="课堂演示流程" hidden></aside><details id="task-tray" class="task-tray" hidden><summary id="task-summary" aria-live="polite"></summary><div id="task-body"></div></details>';
workbench.insertAdjacentHTML('beforeend','<div id="stage-topbar" class="stage-topbar"></div><div id="lesson-dock" class="lesson-dock" aria-label="课堂演示下一步"></div><details id="stage-legend" class="stage-legend" data-disclosure="stage-legend"></details>');
document.body.append(workbench);
document.documentElement.dataset.theme=localStorage.getItem('myraft-theme')||'dark';

function syncSidebar(){const open=$('sidebar').classList.contains('open')||pinned;$('sidebar').inert=!open;$('nav-trigger').setAttribute('aria-expanded',String(open));$('nav-pin').setAttribute('aria-pressed',String(pinned));}
function openNav(){clearTimeout(navTimer);$('sidebar').classList.add('open');syncSidebar();}
function closeNav(force=false){clearTimeout(navTimer);if(pinned&&!force)return;$('sidebar').classList.remove('open');if(force){pinned=false;$('sidebar').classList.remove('pinned');}syncSidebar();}
function scheduleClose(){clearTimeout(navTimer);navTimer=setTimeout(()=>{if(!$('sidebar').matches(':hover')&&!$('sidebar').contains(document.activeElement))closeNav();},300);}
$('sidebar').addEventListener('pointerenter',openNav);$('sidebar').addEventListener('pointerleave',scheduleClose);
$('sidebar').addEventListener('focusin',openNav);$('sidebar').addEventListener('focusout',scheduleClose);
document.addEventListener('pointermove',e=>{if(e.pointerType==='mouse'&&e.clientX<=28)openNav();else if(e.clientX>220)scheduleClose();});

// Only live regions are replaced: forms and their focus/selection stay in the DOM.
function setContent(element,html) {
  if(!element||element._markup===html)return;
  const selector=node=>node.id?`#${CSS.escape(node.id)}`:
    ['data-disclosure','data-receipt','data-step','data-act','data-node','data-session','data-entry','data-entry-node']
      .filter(a=>node.hasAttribute(a)).map(a=>`[${a}="${CSS.escape(node.getAttribute(a))}"]`).join('');
  const focus=document.activeElement,restore=element.contains(focus);
  const scope=restore?focus.closest('details[data-disclosure],details[data-receipt],[data-step]'):null;
  const scopeKey=scope&&element.contains(scope)?selector(scope):'';
  const focusKey=restore?(selector(focus)||(focus.tagName==='SUMMARY'?'summary':'')):'';
  const focusIndex=focusKey?[...(scopeKey?scope:element).querySelectorAll(focusKey)].indexOf(focus):-1;
  const opened=[...element.querySelectorAll('details[open][data-disclosure],details[open][data-receipt]')].map(selector);
  const scrollSelector='.table-scroll,.json-view,.perf-chart-scroll';
  const scrolls=[...element.querySelectorAll(scrollSelector)].map((node,index)=>{
    const parent=node.closest('details[data-disclosure],details[data-receipt]');
    return {parent:parent?selector(parent):'',index:parent?[...parent.querySelectorAll(scrollSelector)].indexOf(node):index,top:node.scrollTop,left:node.scrollLeft};
  });
  const top=element.scrollTop,left=element.scrollLeft;
  element.innerHTML=html;element._markup=html;
  for(const key of opened){const d=element.querySelector(key);if(d)d.open=true;}
  // Raw receipts are populated after rendering, so defer their scroll restoration.
  queueMicrotask(()=>{if(element._markup!==html)return;for(const saved of scrolls){
    const parent=saved.parent?element.querySelector(saved.parent):element;
    const node=parent?.querySelectorAll(scrollSelector)[saved.index];
    if(node){node.scrollTop=saved.top;node.scrollLeft=saved.left;}
  }});
  element.scrollTop=top;element.scrollLeft=left;
  if(focusIndex>=0){const parent=scopeKey?element.querySelector(scopeKey):element;
    const next=parent?.querySelectorAll(focusKey)[focusIndex];
    if(next&&!next.closest('[hidden],[inert]'))next.focus({preventScroll:true});
  }
}

function chrome() {
  syncSidebar();const session=state.frame?.session||state.bootstrap?.session,seconds=age(state);
  $('session-name').textContent=session?.name||'尚无活跃会话';
  $('session-meta').textContent=session?`固定成员 · ${session.config.nodes.length} 节点`:'创建或恢复实验';
  $('connection').textContent=!state.connected?'连接中断':!session?'无活跃会话':!Number.isFinite(seconds)?'等待采集':`${fresh(state)?'已连接':'样本过期'} · ${seconds.toFixed(1)}s`;
  $('connection').className=`tag ${fresh(state)?'teal':'amber'}`;
  $('mode').textContent=state.frame?.control_enabled&&!state.bootstrap?.read_only_transport?'本机控制':'只读';
}
function draftKey(id){return scopeKey(state)+'/'+id;}
function restoreDrafts() {
  for(const form of $('main').querySelectorAll('form'))for(const field of form.elements){
    const value=state.drafts[draftKey(form.id)]?.[field.name];if(value===undefined)continue;
    if(field.type==='checkbox')field.checked=value.includes(field.value);else field.value=value;
  }
}
function syncActions() {
  for(const b of document.querySelectorAll('button[data-act]')) {
    const kind=b.dataset.act.replaceAll('-','_');if(!Object.hasOwn(labels,kind))continue;
    const reason=actionReason(state,kind);b.disabled=Boolean(reason);b.title=reason||labels[kind];
  }
  for(const [id,kind,label] of [['create-form','create_session','创建并启动'],['experiment-form','experiment','运行实际实验']]) {
    const form=$(id);if(!form)continue;
    const reason=actionReason(state,kind),b=form.querySelector('button[type=submit]');
    b.disabled=Boolean(reason);b.textContent=state.pendingKind===kind&&state.pending?'正在发送…':label;
    b.setAttribute('aria-busy',String(state.pendingKind===kind&&state.pending));
    form.querySelector('[data-form-reason]').textContent=reason;
  }
  if($('logs-form')){const b=$('logs-form').querySelector('button');b.disabled=!fresh(state)||state.logLoading;b.textContent=state.logLoading?'读取中…':'读取实际日志';}
  for(const b of document.querySelectorAll('[data-session]'))b.disabled=b.dataset.session===state.frame?.session?.id||Boolean(actionReason(state,'select_session'));
}
function render() {
  if(rendering)return;rendering=true;
  try {
    chrome();document.body.dataset.page=state.page;
    for(const b of $('nav').querySelectorAll('[data-page]')){b.classList.toggle('active',b.dataset.page===state.page);if(b.dataset.page===state.page)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');}
    $('crumb').textContent=pages.find(p=>p[0]===state.page)[1];
    setContent($('nav-actions'),'<button class="btn primary" data-act="generate">提交命令</button><button class="btn" data-act="verify">校验当前</button>');
    const withStage=state.page==='overview'||state.page==='faults',scope=scopeKey(state);
    if(renderedPage!==state.page||renderedScope!==scope) {
      stage?.destroy();stage=null;
      $('main').innerHTML=(withStage?'':'<div id="page-alert" role="status"></div>')+views[state.page](state);
      renderedPage=state.page;renderedScope=scope;restoreDrafts();
      if(withStage)stage=new Stage($('stage-host'));
    } else if(!withStage) {
      const template=document.createElement('template');template.innerHTML=views[state.page](state);
      for(const next of template.content.querySelectorAll('[data-live]'))setContent($('main').querySelector(`[data-live="${next.dataset.live}"]`),next.innerHTML);
    }
    if($('page-alert'))setContent($('page-alert'),!state.connected?'<div class="notice warn">后端连接中断。当前状态未知；不会自动重发写入。</div>':state.frame?.session&&!fresh(state)?'<div class="notice warn">样本过期；等待新的节点观测。</div>':'');
    if(withStage) {
      setContent($('stage-alert'),stageNotice(state));$('stage-alert').hidden=!$('stage-alert').textContent;
      if(state.page==='faults')setContent($('fault-content'),faultContent(state));
      stage.update({nodes:stageNodes(state),members:state.frame?.session?.config.nodes||[],selected:state.nodeSelected?state.selected:undefined,fresh:fresh(state),events:state.events,scope,snapshotSeq:state.frame?.snapshot?.seq});
      $('node-detail').hidden=!state.detailOpen;if(state.detailOpen)setContent($('node-detail'),nodeDetail(state));
    }
    for(const id of ['stage-topbar','lesson-dock','stage-legend'])$(id).hidden=state.page!=='overview';
    if(state.page==='overview'){setContent($('stage-topbar'),stageChrome(state));setContent($('lesson-dock'),lessonDock(state));setContent($('stage-legend'),stageLegend(state,Number(stage?.host.dataset.visibleRelations||0),Number(stage?.host.dataset.relations||0)));}
    $('demo-drawer').hidden=!state.demoOpen;
    workbench.querySelector('.demo-trigger').setAttribute('aria-expanded',String(state.demoOpen));
    if(state.demoOpen)setContent($('demo-drawer'),workflow(state));
    const summary=taskSummary(state);document.body.classList.toggle('has-tasks',Boolean(summary));$('task-tray').hidden=!summary;$('task-summary').textContent=summary;
    if(summary)setContent($('task-body'),taskBody(state));
    syncActions();
    for(const d of document.querySelectorAll('details[data-receipt][open]'))fillReceipt(d);
  }finally{rendering=false;}
}
function fillReceipt(details) {
  const op=state.frame?.operations?.find(o=>o.id===details.dataset.receipt)||(state.lastReceipt?.id===details.dataset.receipt?state.lastReceipt:null);
  if(op&&details.open)details.querySelector('[data-receipt-json]').textContent=JSON.stringify(op,null,2);
}
document.addEventListener('toggle',e=>{if(e.target.matches('details[data-receipt]'))fillReceipt(e.target);},true);
function navigate(page,history=true) {
  state.page=validPage(page);state.detailOpen=false;state.demoOpen=false;closeNav();
  if(history&&location.hash!=='#'+state.page)window.history.pushState(null,'','#'+state.page);
  render();$('main').focus({preventScroll:true});window.scrollTo(0,0);
}
window.addEventListener('popstate',()=>navigate(location.hash.slice(1),false));
window.addEventListener('hashchange',()=>{if(state.page!==validPage(location.hash.slice(1)))navigate(location.hash.slice(1),false);});
function rememberDraft(e) {
  const form=e.target.form;if(!form?.id||!e.target.name)return;
  const draft=state.drafts[draftKey(form.id)]||={};
  draft[e.target.name]=e.target.type==='checkbox'?[...form.querySelectorAll(`input[name="${e.target.name}"]:checked`)].map(x=>x.value):e.target.value;
}
function toast(message){$('toast').textContent=message;$('toast').classList.remove('hidden');clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').classList.add('hidden'),6000);}
function closeDialog() {
  $('action-dialog')?.close();$('overlay').replaceChildren();$('overlay').setAttribute('aria-hidden','true');modalScope='';render();
  if(modalInvoker?.isConnected&&!modalInvoker.closest('[hidden],[inert]'))modalInvoker.focus({preventScroll:true});
}
function dialog(title,body,submit,label='确认',danger=false) {
  modalInvoker=document.activeElement;modalScope=scopeKey(state);$('overlay').removeAttribute('aria-hidden');
  const scope={frame:state.frame,bootstrap:state.bootstrap};
  $('overlay').innerHTML=`<dialog id="action-dialog" class="dialog" aria-labelledby="dialog-title"><form method="dialog" id="dialog-form"><h2 id="dialog-title">${esc(title)}</h2>${body}<p class="field-error" hidden></p><div class="actions"><button class="btn" type="submit" value="cancel" ${danger?'autofocus':''}>取消</button><button id="confirm" type="submit" class="btn ${danger?'danger':'primary'}" value="confirm">${label}</button></div></form></dialog>`;
  const d=$('action-dialog');d.showModal();d.addEventListener('cancel',e=>{e.preventDefault();closeDialog();});let sent=false;
  $('dialog-form').addEventListener('submit',async e=>{
    e.preventDefault();if(e.submitter?.value!=='confirm'){closeDialog();return;}
    if(sent||!e.target.reportValidity())return;
    if(modalScope!==scopeKey(state)){closeDialog();toast('会话已变化，请重新确认操作。');return;}
    sent=true;$('confirm').disabled=true;
    try{await submit(new FormData(e.target),scope);if(d.isConnected)closeDialog();}
    catch(err){sent=Boolean(state.actionError?.unknown);if(!d.isConnected)return;const error=d.querySelector('.field-error');error.textContent=sent?'结果未知：'+err.message+'。请关闭后核对任务，不要重复发送。':err.message;error.setAttribute('role','alert');error.hidden=false;$('confirm').disabled=sent;}
  });
}
async function refreshBootstrap() {
  const request=++bootstrapRequest,expected=state.frame?.controller_id;
  bootstrapPending++;bootstrapNeeded=true;
  try {
    const data=await api.bootstrap();
    if(request!==bootstrapRequest||expected&&state.frame?.controller_id!==expected)return;
    if(state.frame&&data.controller_id!==state.frame.controller_id)return;
    state.bootstrap=data;bootstrapNeeded=false;render();
  } finally {bootstrapPending--;if(request===bootstrapRequest)bootstrapRetryAt=Date.now()+2000;}
}
async function action(kind,params={},scope={frame:state.frame,bootstrap:state.bootstrap}) {
  const reason=actionReason(state,kind,params.node_id??state.selected);if(reason)throw new Error(reason);
  if(scopeKey(scope)!==scopeKey(state))throw new Error('会话已变化，请重新确认操作。');
  const sentScope=scopeKey(scope);state.pending=true;state.pendingKind=kind;state.actionError=null;render();
  try {
    const data=await api.operate(kind,scope,params);
    // Session creation/selection can legitimately return a new generation.
    if(scope.frame?.controller_id===state.frame?.controller_id&&(sentScope===scopeKey(state)||(['create_session','select_session'].includes(kind)&&data.session_id===state.frame?.session?.id&&data.generation===state.frame?.generation)))state.lastReceipt=data;
    return data;
  } catch(error) {
    if(sentScope===scopeKey(state))state.actionError={kind,message:error.message,unknown:!error.status||error.status>=500};
    throw error;
  } finally {state.pending=false;state.pendingKind='';render();}
}
function receive(frame) {
  if(frame.mode!=='REAL')return;
  if(state.frame&&frame.controller_id===state.frame.controller_id&&frame.generation<state.frame.generation)return;
  const changed=scopeKey({frame})!==scopeKey(state);
  if(changed) {
    logRequest++;logAbort?.abort();state.logQuery=null;state.logLoading=false;state.logError='';state.logData={};state.logNodes=[];
    state.events=[];state.gap=false;state.streamLoss=0;state.lastStreamDrop=0;state.selected=frame.session?.config.nodes[0]?.id||1;state.detailOpen=false;state.nodeSelected=false;state.lastReceipt=null;state.actionError=null;state.drafts={};
  }
  state.connected=true;state.gap ||= Boolean(frame.gap);
  const dropped=frame.stream_dropped||0;state.streamLoss+=dropped>=state.lastStreamDrop?dropped-state.lastStreamDrop:dropped;state.lastStreamDrop=dropped;
  for(const e of frame.events||[])if(!state.events.some(old=>old.seq===e.seq))state.events.push(e);
  state.events=state.events.slice(-512);frame.gap=state.gap;frame.stream_dropped=state.streamLoss;frame.eventsHistory=state.events;state.frame=frame;
  if(changed){if($('action-dialog')&&modalScope!==scopeKey(state)){closeDialog();toast('会话已变化，请重新确认操作。');}refreshBootstrap().catch(()=>{});}
  if(!document.hidden)render();else chrome();
}
async function loadLogs() {
  const session=state.frame?.session,generation=state.frame?.generation,controller=state.frame?.controller_id;
  if(!session)throw new Error('没有活跃会话');
  const ids=(state.logNodes.length?state.logNodes:session.config.nodes.slice(0,2).map(n=>n.id)).slice().sort((a,b)=>a-b);
  if(ids.length>8||!ids.length)throw new Error('请选择1–8个节点');
  const query={controller,session:session.id,generation,nodes:ids,from:state.logFrom,limit:state.logLimit};
  const request=++logRequest;logAbort?.abort();const abort=new AbortController();logAbort=abort;state.logQuery=query;state.logLoading=true;state.logError='';state.logData={};render();
  const current=()=>request===logRequest&&state.logQuery===query&&state.frame?.controller_id===controller&&state.frame?.session?.id===session.id&&state.frame?.generation===generation;
  try {
    const outcomes=await Promise.all(ids.map(async id=>{try{return[id,await api.logs(id,query.from,query.limit,session.id,generation,abort.signal)];}catch(error){return[id,{error:error.message}];}}));
    if(!current())return;
    const errors=[];
    for(const [id,data] of outcomes){if(data.error)errors.push(`#${id} ${data.error}`);else if(data.session_id===session.id&&data.generation===generation)state.logData[id]=data;}
    state.logError=errors.join('；');
  } finally {
    if(current()){state.logLoading=false;if(logAbort===abort)logAbort=null;render();}
  }
}
function invalidateLogQuery(){logRequest++;logAbort?.abort();logAbort=null;state.logQuery=null;state.logLoading=false;state.logError='';state.logData={};}
function openNode(id){state.selected=id;state.nodeSelected=true;state.detailOpen=true;state.demoOpen=false;render();$('node-detail')?.querySelector('.detail-close')?.focus({preventScroll:true});}
function showError(error){toast(error.message);if(state.actionError)$('task-tray').open=true;}

document.addEventListener('click',async e=>{
  const nav=e.target.closest('button[data-page]');if(nav){navigate(nav.dataset.page);return;}
  const node=e.target.closest('[data-node]');if(node){openNode(Number(node.dataset.node));return;}
  const entry=e.target.closest('[data-entry]');if(entry){const index=Number(entry.dataset.entry);dialog(`同索引比较 #${index}`,compareLogs(state,index),async()=>{},'关闭');return;}
  const session=e.target.closest('[data-session]');if(session&&!session.disabled){try{await action('select_session',{select_session:session.dataset.session});}catch(error){showError(error);}return;}
  const preset=e.target.closest('[data-preset]');if(preset){
    const form=$('experiment-form'),scale=preset.dataset.preset==='scale';
    for(const field of form.querySelectorAll('[name=nodes]'))field.checked=(scale?[10,20,50,100]:[11]).includes(Number(field.value));
    for(const field of form.querySelectorAll('[name=scenarios]'))field.checked=field.value===(scale?'election':'replication');
    for(const field of form.elements)if(field.name)rememberDraft({target:field});return;
  }
  const stop=e.target.closest('[data-stop]');if(stop)state.selected=Number(stop.dataset.stop);
  const element=stop||e.target.closest('[data-act]');if(!element||element.disabled)return;
  const act=stop?'stop':element.dataset.act;
  if(element.closest('#nav-actions')){closeNav();$('main').focus({preventScroll:true});}
  try {
    if(act==='show-task'){$('task-tray').open=true;$('task-summary').focus();return;}
    if(act==='menu'){openNav();return;}
    if(act==='close-nav'){closeNav(true);$('nav-trigger').focus();return;}
    if(act==='pin-nav'){pinned=!pinned;$('sidebar').classList.toggle('pinned',pinned);openNav();return;}
    if(act==='demo'){state.demoOpen=!state.demoOpen;state.detailOpen=false;render();if(state.demoOpen)$('demo-drawer').querySelector('button').focus();return;}
    if(act==='close-demo'){state.demoOpen=false;render();workbench.querySelector('.demo-trigger').focus();return;}
    if(act==='close-detail'){state.detailOpen=false;render();document.querySelector(`.stage-node[data-node="${state.selected}"]`)?.focus({preventScroll:true});return;}
    if(act==='theme'){const theme=document.documentElement.dataset.theme==='dark'?'light':'dark';document.documentElement.dataset.theme=theme;localStorage.setItem('myraft-theme',theme);return;}
    if(act==='present'){document.body.classList.toggle('present');return;}
    if(act==='dismiss-error'){state.actionError=null;render();return;}
    if(act==='refresh-dependencies'){await refreshBootstrap();return;}
    if(act==='open-logs'||act==='node-logs'){if(act==='node-logs'){invalidateLogQuery();state.logNodes=[state.selected];}navigate('logs');return;}
    if(act==='generate'){
      dialog('提交确定性命令','<p>通过真实 Raft 提交。结果未知时不会自动重发。</p><label class="field">算术命令数<input name="count" type="number" min="1" max="100000" value="2101" required></label><label class="field">随机种子<input name="seed" type="number" min="-2147483648" max="2147483647" value="42" required></label>',(v,scope)=>action('generate',{count:Number(v.get('count')),seed:Number(v.get('seed'))},scope),'发送一次');return;
    }
    if(act==='stop'||act==='stop-all'){
      const nodes=state.frame?.snapshot?.nodes||[],owned=nodes.filter(n=>n.owned),members=state.frame?.session?.config.nodes.length||0,id=state.selected;
      const affected=act==='stop'?owned.filter(n=>n.id===id):owned;
      dialog(act==='stop'?`停止节点 #${id}`:'停止本会话全部自有节点',`<p>保留配置和数据；仅终止本控制器持有的进程。</p><div class="notice warn">操作对象：${affected.map(n=>'#'+n.id).join('、')||'无'}<br>最近观测自有进程 ${affected.length} 个；${fresh(state)?`可达 ${nodes.filter(n=>n.reachable).length}/${members}`:'节点观测过期，可达数量未知'}。多数派门槛 ${Math.floor(members/2)+1}。可达数不表示实际连通性或多数派授权。</div>`,(_,scope)=>action(act==='stop'?'stop':'stop_all',{node_id:id,confirm:true},scope),'确认停止',true);return;
    }
    if(act==='enable-control'){dialog('启用本机会话控制','<p>允许创建、写入及恢复本机会话。停止节点仍需单独确认。</p>',(_,scope)=>action('enable_control',{confirm:true},scope),'明确启用');return;}
    if(act==='checkpoint'&&state.frame?.checkpoint){dialog('替换历史检查点',`<p>现有检查点 index=${state.frame.checkpoint.index}。替换后未来的历史验证将使用新的前缀；故障恢复实验通常应保留原检查点。</p>`,(_,scope)=>action('checkpoint',{},scope),'确认替换');return;}
    if(act==='experiment'&&element.dataset.divergence){dialog('独立分歧实验','<p>使用独立构建和数据目录，运行中不改写当前会话日志。</p>',(_,scope)=>action('experiment',{nodes:[3],scenarios:['divergence'],count:2101,rounds:1,seed:42,batch:128},scope),'开始独立实验');return;}
    if(act==='cancel-experiment'){const op=activeExperiment(state);if(op)await action('cancel_experiment',{operation_id:op.id});return;}
    const kind=act.replaceAll('-','_');if(Object.hasOwn(labels,kind))await action(kind,kind==='restart'?{node_id:state.selected}:{});
  }catch(error){showError(error);}
});
document.addEventListener('submit',async e=>{
  const form=e.target;if(!['logs-form','create-form','experiment-form'].includes(form.id))return;e.preventDefault();const data=new FormData(form),errorBox=form.querySelector('.field-error');
  if(errorBox){errorBox.hidden=true;errorBox.removeAttribute('role');}
  try{
    if(form.id==='logs-form'){invalidateLogQuery();state.logFrom=Number(data.get('from'));state.logLimit=Number(data.get('limit'));await loadLogs();}
    if(form.id==='create-form')await action('create_session',{name:data.get('name'),nodes:[Number(data.get('nodes'))],batch:Number(data.get('batch'))});
    if(form.id==='experiment-form') {
      const nodes=data.getAll('nodes').map(Number),scenarios=data.getAll('scenarios'),rounds=Number(data.get('rounds'));
      if(!nodes.length||nodes.length>4||!scenarios.length||nodes.length*scenarios.length*rounds>100)throw new Error('请选择1–4种节点规模和至少1个场景，总轮次不超过100。');
      await action('experiment',{nodes,scenarios,count:Number(data.get('entries')),rounds,seed:Number(data.get('seed')),batch:Number(data.get('batch'))});
    }
  }catch(error){if(errorBox){errorBox.textContent=error.message;errorBox.setAttribute('role','alert');errorBox.hidden=false;}showError(error);}
});
document.addEventListener('change',e=>{if(e.target.matches('[data-log-node]')){state.logNodes=[...document.querySelectorAll('[data-log-node]:checked')].map(x=>Number(x.dataset.logNode));if(!state.logNodes.length){e.target.checked=true;state.logNodes=[Number(e.target.dataset.logNode)];toast('至少保留1个节点。');}if(state.logNodes.length>8){e.target.checked=false;state.logNodes=state.logNodes.filter(id=>id!==Number(e.target.dataset.logNode));toast('最多选择8个节点。');}invalidateLogQuery();render();}});
document.addEventListener('input',rememberDraft);document.addEventListener('change',rememberDraft);
$('search').addEventListener('change',e=>{const id=Number(e.target.value.trim());if(state.frame?.session?.config.nodes.some(n=>n.id===id)){navigate('overview');openNode(id);stage.focus(id);}else toast('没有这个节点 ID。');});
document.addEventListener('keydown',e=>{
  if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='k'){e.preventDefault();openNav();$('search').focus();}
  if(e.key==='Escape') {if($('action-dialog'))return;if(state.detailOpen){state.detailOpen=false;render();document.querySelector(`.stage-node[data-node="${state.selected}"]`)?.focus({preventScroll:true});}else if(state.demoOpen){state.demoOpen=false;render();workbench.querySelector('.demo-trigger').focus();}else{closeNav(true);$('nav-trigger').focus();}}
});
document.addEventListener('visibilitychange',()=>{if(!document.hidden)render();});
setInterval(()=>{chrome();if(!document.hidden)render();if(state.frame&&state.connected&&bootstrapNeeded&&!bootstrapPending&&Date.now()>=bootstrapRetryAt)refreshBootstrap().catch(()=>{});},1000);
async function connect() {
  try {
    await refreshBootstrap();stream?.close();stream=new EventSource('/api/events');
    stream.addEventListener('frame',e=>{try{receive(api.parseJSON(e.data));}catch(error){state.connected=false;toast('快照解析失败：'+error.message);render();}});
    stream.onerror=()=>{state.connected=false;render();};
  }catch(error){state.connected=false;render();toast(error.message);setTimeout(connect,3000);}
}
connect();
