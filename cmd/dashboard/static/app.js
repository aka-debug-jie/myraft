import * as api from './api.js';
import {pages, esc, icon, age, fresh, overview, logView, faults, experiments, evidence, settings} from './views.js';

const state = {page:'overview', selected:1, filter:'', bootstrap:null, frame:null, connected:false,
  pending:false, logNodes:[], logFrom:1, logLimit:32, logData:{}, logLoading:false, logError:'', events:[], gap:false, streamLoss:0, lastStreamDrop:0};
const views = {overview,logs:logView,faults,experiments,evidence,settings};
let stream, logRequest=0, toastTimer;
const $ = id => document.getElementById(id);
function syncSidebar(){const mobile=matchMedia('(max-width:680px)').matches;const open=$('sidebar').classList.contains('open');$('sidebar').inert=mobile&&!open;document.querySelector('[data-act=menu]')?.setAttribute('aria-expanded',String(open));}
addEventListener('resize',syncSidebar);
const storedTheme=localStorage.getItem('myraft-theme');if(storedTheme)document.documentElement.dataset.theme=storedTheme;

function chrome() {
  syncSidebar();
  const session=state.frame?.session||state.bootstrap?.session;
  $('session-name').textContent=session?.name||'尚无活跃会话';
  $('session-meta').textContent=session?`固定成员 · ${session.config.nodes.length} nodes`:'在会话设置开始';
  const seconds=age(state);
  $('connection').textContent=!state.connected?'连接中断':!session?'无活跃会话':!Number.isFinite(seconds)?'等待采集':`${fresh(state)?'已连接':'样本过期'} · ${seconds.toFixed(1)}s`;
  $('connection').className=`tag ${fresh(state)?'teal':'amber'}`;
  $('mode').textContent=state.frame?.control_enabled?'本机控制':'只读';
}
function render() {
  const focused=document.activeElement;
  const key=focused?.id?`#${CSS.escape(focused.id)}`:['data-page','data-node','data-act','data-session','data-stop','data-entry'].filter(a=>focused?.hasAttribute(a)).map(a=>`[${a}="${CSS.escape(focused.getAttribute(a))}"]`).join('');
  chrome();
  $('nav').innerHTML=pages.map(([id,label,ic])=>`<button data-page="${id}" class="${state.page===id?'active':''}" ${state.page===id?'aria-current="page"':''}>${icon(ic)}${label}</button>`).join('');
  $('crumb').textContent=pages.find(p=>p[0]===state.page)[1];
  const alert=!state.connected?'<div class="notice warn" role="alert">后端连接中断。当前状态未知；不会切换为演示数据或自动重发写入。</div>':
    state.frame?.session&&!fresh(state)?'<div class="notice warn">等待新样本；过期观测不作为在线证明。</div>':'';
  $('main').innerHTML=alert+views[state.page](state);
  if(key)document.querySelector(key)?.focus({preventScroll:true});
}
function toast(message){$('toast').textContent=message;$('toast').classList.remove('hidden');clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').classList.add('hidden'),6000);}
function closeDialog(){const d=$('action-dialog');d?.close();$('overlay').replaceChildren();}
function dialog(title,body,submit,label='确认',danger=false){
  $('overlay').innerHTML=`<dialog id="action-dialog" class="dialog" aria-labelledby="dialog-title"><form method="dialog" id="dialog-form"><h2 id="dialog-title">${esc(title)}</h2>${body}<div class="actions"><button class="btn" value="cancel">取消</button><button id="confirm" class="btn ${danger?'danger':'primary'}" value="confirm">${label}</button></div></form></dialog>`;
  const d=$('action-dialog');d.showModal();let sent=false;const scope={frame:state.frame,bootstrap:state.bootstrap};
  $('dialog-form').addEventListener('submit',async e=>{if(e.submitter?.value!=='confirm'){closeDialog();return;}e.preventDefault();if(sent)return;if(!e.target.reportValidity())return;sent=true;$('confirm').disabled=true;try{await submit(new FormData(e.target),scope);closeDialog();}catch(err){sent=false;if($('confirm'))$('confirm').disabled=false;toast(err.message);}});
}
async function action(kind,params={},scope=state) {
  if(state.pending)throw new Error('请求已经发送，请等待回执。');
  state.pending=true;
  try {const data=await api.operate(kind,scope,params);const latest=state.frame?.operations?.find(o=>o.id===data.id)||data;toast(`操作 ${latest.id||kind}：${latest.state||'已登记'}`);return data;}
  finally {state.pending=false;}
}
async function refreshBootstrap(){state.bootstrap=await api.bootstrap();}
function receive(frame){
  if(frame.mode!=='REAL')return;
  if(state.frame && frame.controller_id===state.frame.controller_id && frame.generation<state.frame.generation)return;
  const changed=frame.controller_id!==state.frame?.controller_id||frame.session?.id!==state.frame?.session?.id||frame.generation!==state.frame?.generation;
  if(changed){logRequest++;state.logData={};state.logNodes=[];state.events=[];state.gap=false;state.streamLoss=0;state.lastStreamDrop=0;state.selected=frame.session?.config.nodes[0]?.id||1;refreshBootstrap().catch(()=>{});}
  state.connected=true;
  state.gap ||= Boolean(frame.gap);const dropped=frame.stream_dropped||0;state.streamLoss+=dropped>=state.lastStreamDrop?dropped-state.lastStreamDrop:dropped;state.lastStreamDrop=dropped;frame.gap=state.gap;frame.stream_dropped=state.streamLoss;
  for(const e of frame.events||[])if(!state.events.some(old=>old.seq===e.seq))state.events.push(e);
  state.events=state.events.slice(-512);frame.eventsHistory=state.events;state.frame=frame;
  if(!document.hidden&&!$('action-dialog')&&!document.activeElement?.matches('input,select'))render();else chrome();
}
async function loadLogs(){
  const session=state.frame?.session, generation=state.frame?.generation;
  if(!session)throw new Error('没有活跃会话');
  const ids=state.logNodes.length?state.logNodes:session.config.nodes.slice(0,2).map(n=>n.id);
  if(ids.length>8||!ids.length)throw new Error('请选择 1–8 个节点');
  const request=++logRequest;state.logLoading=true;state.logError='';render();
  const outcomes=await Promise.all(ids.map(async id=>{try{return [id,await api.logs(id,state.logFrom,state.logLimit,session.id,generation)];}catch(error){return [id,{error:error.message}];}}));
  if(request!==logRequest||state.frame?.session?.id!==session.id||state.frame?.generation!==generation)return;
  state.logLoading=false;state.logData={};const errors=[];
  for(const [id,data] of outcomes){if(data.error)errors.push(`#${id} ${data.error}`);else if(data.session_id===session.id&&data.generation===generation)state.logData[id]=data;}
  state.logError=errors.join('；');render();
}

document.addEventListener('click',async e=>{
  const nav=e.target.closest('[data-page]');if(nav){state.page=nav.dataset.page;$('sidebar').classList.remove('open');render();window.scrollTo(0,0);return;}
  const node=e.target.closest('[data-node]');if(node){state.selected=Number(node.dataset.node);render();return;}
  const entry=e.target.closest('[data-entry]');if(entry){const index=Number(entry.dataset.entry);const rows=Object.entries(state.logData).map(([id,data])=>({node:id,instance:data.range?.instance_id,revision:data.range?.revision,entry:data.range?.entries?.find(x=>x.index===index)||null}));dialog(`同索引比较 #${index}`,`<pre class="json-view">${esc(JSON.stringify(rows,null,2))}</pre>`,async()=>{},'关闭');return;}
  const session=e.target.closest('[data-session]');if(session){try{await action('select_session',{select_session:session.dataset.session});}catch(err){toast(err.message);}return;}
  const stop=e.target.closest('[data-stop]');if(stop)state.selected=Number(stop.dataset.stop);
  const element=stop||e.target.closest('[data-act]');if(!element||element.disabled)return;
  const act=stop?'stop':element.dataset.act;
  try {
    if(act==='menu'){$('sidebar').classList.toggle('open');syncSidebar();return;}
    if(act==='theme'){const theme=document.documentElement.dataset.theme==='dark'?'light':'dark';document.documentElement.dataset.theme=theme;localStorage.setItem('myraft-theme',theme);return;}
    if(act==='present'){document.body.classList.toggle('present');return;}
    if(act==='open-logs'){state.page='logs';render();return;}
    if(act==='generate'){dialog('提交确定性命令',`<p>实际发送给 Raft。受理不等于提交；未知结果不会自动重发。</p><label class="field">命令数<input name="count" type="number" min="1" max="100000" value="2101" required></label><label class="field">种子<input name="seed" type="number" min="-2147483648" max="2147483647" value="42" required></label>`,(v,scope)=>action('generate',{count:Number(v.get('count')),seed:Number(v.get('seed'))},scope),'发送一次');return;}
    if(act==='stop'||act==='stop-all'){
      const members=state.frame?.session?.config.nodes.length||0,reachable=state.frame?.snapshot.nodes.filter(n=>n.reachable).length||0;
      dialog(act==='stop'?`停止节点 #${state.selected}`:'停止本会话全部自有节点',`<p>将终止本控制器拥有的进程，保留数据。</p><div class="notice warn">当前可达 ${reachable}/${members}；多数派门槛 ${Math.floor(members/2)+1}。预计减少 ${act==='stop'?1:reachable} 个进程，可达数不等于实际连通性。</div>`,(_,scope)=>action(act==='stop'?'stop':'stop_all',{node_id:state.selected,confirm:true},scope),'确认停止',true);return;}
    if(act==='enable-control'){dialog('启用本机会话控制','<p>允许创建实验、发起真实写入、停止或恢复本会话节点。每次停止仍需单独确认。</p>',(_,scope)=>action('enable_control',{confirm:true},scope),'明确启用');return;}
    if(act==='restart'){await action('restart',{node_id:state.selected});return;}
    if(act==='resume'){await action('resume');return;}
    if(act==='verify'){await action('verify');return;}
    if(act==='verify-history'){await action('verify_history');return;}
    if(act==='checkpoint'){await action('checkpoint');return;}
    if(act==='export'){await action('export');return;}
    if(act==='divergence'){dialog('独立分歧实验','<p>新建独立构建与数据目录，保留当前会话日志；不在运行节点上改写日志。</p>',(_,scope)=>action('experiment',{nodes:[3],scenarios:['divergence'],count:2101,rounds:1,seed:42,batch:128},scope),'开始独立实验');return;}
    if(act==='cancel-experiment'){const op=state.frame?.operations.find(o=>o.kind==='experiment'&&!o.ended_at);if(op)await action('cancel_experiment',{operation_id:op.id});return;}
  }catch(err){toast(err.message);}
});
document.addEventListener('submit',async e=>{
  if(!['logs-form','create-form','experiment-form'].includes(e.target.id))return;e.preventDefault();const data=new FormData(e.target);
  try{
    if(e.target.id==='logs-form'){state.logFrom=Number($('log-from').value);state.logLimit=Number($('log-limit').value);await loadLogs();}
    if(e.target.id==='create-form')await action('create_session',{name:data.get('name'),nodes:[Number(data.get('nodes'))],batch:Number(data.get('batch'))});
    if(e.target.id==='experiment-form')await action('experiment',{nodes:data.getAll('nodes').map(Number),scenarios:data.getAll('scenarios'),count:Number(data.get('entries')),rounds:Number(data.get('rounds')),seed:Number(data.get('seed')),batch:Number(data.get('batch'))});
  }catch(err){toast(err.message);}
});
document.addEventListener('change',e=>{if(e.target.matches('[data-log-node]')){state.logNodes=[...document.querySelectorAll('[data-log-node]:checked')].map(x=>Number(x.dataset.logNode));if(state.logNodes.length>8){e.target.checked=false;state.logNodes=state.logNodes.filter(id=>id!==Number(e.target.dataset.logNode));toast('最多选择 8 个节点。');}}});
$('search').addEventListener('input',e=>{state.filter=e.target.value.trim();state.page='overview';render();$('search').focus();});
document.addEventListener('keydown',e=>{if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='k'){e.preventDefault();$('search').focus();}if(e.key==='Escape'){$('sidebar').classList.remove('open');syncSidebar();}});
document.addEventListener('visibilitychange',()=>{if(!document.hidden)render();});
setInterval(()=>{chrome();if(!fresh(state)&&state.frame&&!document.hidden&&!$('action-dialog')&&!document.activeElement?.matches('input,select'))render();},1000);

async function connect(){
  try{
    await refreshBootstrap();stream?.close();stream=new EventSource('/api/events');
    stream.addEventListener('frame',e=>{try{receive(JSON.parse(e.data));}catch(error){state.connected=false;toast('快照解析失败：'+error.message);render();}});
    stream.onerror=()=>{state.connected=false;render();};
  }catch(error){state.connected=false;render();toast(error.message);setTimeout(connect,3000);}
}
connect();
