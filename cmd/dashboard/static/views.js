import {experimentChart} from './charts.js';

export const pages = [['overview','集群总览','grid'],['logs','日志实验室','log'],['faults','故障与时间线','bolt'],['experiments','性能实验','chart'],['evidence','一致性证据','shield'],['settings','会话与设置','sliders']];
export const esc = value => String(value ?? '—').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const icon = name => `<svg class="ico" aria-hidden="true"><use href="#i-${name}"></use></svg>`;
const num = n => n == null ? '—' : Number(n).toLocaleString('zh-CN');
const tag = (label, cls='') => `<span class="tag ${cls}">${esc(label)}</span>`;
export const labels = {generate:'提交命令',create_session:'创建会话',select_session:'切换会话',stop:'停止节点',stop_all:'停止自有节点',restart:'恢复节点',resume:'恢复会话',verify:'校验当前',verify_history:'校验历史',checkpoint:'保存检查点',export:'导出证据',experiment:'性能实验',cancel_experiment:'取消实验',enable_control:'启用控制'};
const phases = {queued:'已登记',running:'进行中',succeeded:'任务完成',failed:'失败',canceled:'已取消',cancel_requested:'正在取消',unknown:'结果未知',interrupted:'已中断'};
const checks = {not_run:'未执行',running:'校验中',passed:'通过',failed:'未通过',partial:'部分不可达',unreachable:'部分不可达',stale:'结果已过期'};
export const scenarioLabels = {election:'首次选举',failover:'故障重选',catchup:'空节点追赶',divergence:'分歧修复',replication:'日志复制'};
export function age(s) {const at=s.frame?.snapshot?.completed_at;return at&&!at.startsWith('0001')?(Date.now()-Date.parse(at))/1000:Infinity;}
export function fresh(s) {return s.connected&&age(s)<Math.max(5,(s.bootstrap?.poll_ms||1000)/1000*3);}
export function activeExperiment(s) {return s.frame?.operations?.find(o=>o.kind==='experiment'&&!o.ended_at);}
export function actionReason(s, kind, id=s.selected) {
  const f=s.frame||{}, session=f.session;
  if(!s.connected)return '连接中断，等待控制器重新连接';
  if(!s.bootstrap||s.bootstrap.controller_id!==f.controller_id)return '正在确认控制器身份';
  if(s.bootstrap.read_only_transport)return '当前预览入口只允许查看，操作请使用本机控制台';
  if(s.pending)return '请求已发出，正在等待回执';
  if(kind==='enable_control')return !s.bootstrap.control_allowed?'当前入口仅供查看，未开放会话控制':f.control_enabled?'已启用控制':'';
  if(kind==='cancel_experiment') {
    const op=activeExperiment(s);
    return !f.control_enabled?'请先明确启用本机控制':!op||op.result?.phase!=='running'?'实验尚未进入可取消阶段':op.state==='cancel_requested'?'已请求取消':'';
  }
  if(f.busy)return '另一项任务正在进行';
  if(!['verify','verify_history','checkpoint','export','select_session'].includes(kind)&&!f.control_enabled)return s.bootstrap.control_allowed?'请先在会话设置明确启用本机控制':'当前入口仅供查看，未开放会话控制';
  if(['create_session','select_session'].includes(kind))return '';
  if(!session)return '请先创建或选择会话';
  if(['generate','verify','verify_history','checkpoint'].includes(kind)&&!fresh(s))return '等待新鲜的节点观测';
  const node=f.snapshot?.nodes?.find(n=>n.id===id);
  if(kind==='stop'&&!node?.owned)return '该节点不是本控制器持有的进程';
  if(kind==='stop_all'&&!f.snapshot?.nodes?.some(n=>n.owned))return '没有本控制器持有的节点进程';
  if(['restart','resume'].includes(kind)&&!session.managed)return '外部会话请使用原启动入口恢复';
  if(kind==='restart'&&node?.reachable)return '节点当前可达';
  if(kind==='verify_history'&&!f.checkpoint)return '请先保存历史检查点';
  if(kind==='experiment'&&!s.bootstrap.experiment_dependencies?.ready)return '实验环境未就绪';
  return '';
}
function button(s,kind,label,cls='',extra='') {
  const reason=actionReason(s,kind);
  return `<button type="button" class="btn ${cls}" data-act="${kind.replaceAll('_','-')}" ${reason?'disabled':''} title="${esc(reason||label)}" ${extra}>${esc(label)}</button>`;
}
const header=(title,subtitle,actions='')=>`<div class="intro"><div><h1>${title}</h1><p>${subtitle}</p></div><div class="actions" data-live="page-actions">${actions}</div></div>`;
const empty=text=>`<div class="empty-state muted">${text}</div>`;
const footer=()=>'<div class="footer"><span>REAL · 本机节点</span><span>连线为逻辑关系，完整一致性需校验</span></div>';
const live=(id,html,cls='')=>`<div data-live="${id}" class="${cls}">${html}</div>`;
export function verificationState(s,v) {return !fresh(s)&&v?.state==='passed'?'stale':v?.state||'not_run';}
export function receipt(op) {
  if(!op)return empty('尚无任务回执。');
  const state=phases[op.state]||op.state;
  return `<div class="job"><div class="task-summary"><strong>${esc(labels[op.kind]||op.kind)}</strong>${tag(op.result?.category==='environment_unavailable'?'环境未就绪':state,op.state==='failed'?'amber':'')}</div>
    ${op.kind==='generate'?`<p>${op.accepted===true?'已受理':op.accepted===false?'未受理':'受理情况未知'} · ${op.committed===true?'已提交':'尚未确认提交'}</p>`:''}
    ${op.kind==='restart'||op.kind==='resume'?'<p class="muted">进程恢复后仍需观察追赶并校验。</p>':''}
    ${op.kind==='experiment'?`<p>已记录 ${op.result?.rows?.length||0} 轮 · ${esc(op.result?.phase||state)}</p>`:''}
    ${op.error?`<p class="error-text">${esc(op.error)}</p>`:''}
    <details data-disclosure="receipt-${esc(op.id)}" data-receipt="${esc(op.id)}"><summary>原始回执</summary><p class="small muted">operation_id 仅跟踪任务，不代表 exactly-once。</p><pre class="json-view" data-receipt-json></pre></details></div>`;
}
const eventLabels={election_started:'开始竞选',leader_elected:'当选 Leader',log_appended:'接收新日志',log_replicated:'日志复制推进',log_committed:'日志已提交',state_applied:'状态机应用',log_caught_up:'节点追赶完成',node_recovered:'从本地日志恢复',reachability_changed:'可达性观测变化',operation_queued:'任务已登记',operation_started:'任务开始',operation_succeeded:'任务完成',operation_failed:'任务失败',control_enabled:'已明确启用控制'};
function eventGap(f){return `${f.gap?'<span>部分历史事件未取得</span>':''}${f.stream_dropped?`<span>订阅快照丢弃 ${num(f.stream_dropped)}</span>`:''}`;}
function events(f,limit=100) {
  const rows=(f?.eventsHistory||f?.events||[]).slice(-limit).reverse(),source={node:'节点事件',control:'控制操作',observation:'采集观测'};
  return rows.length?`<ol class="timeline">${rows.map(e=>`<li class="event-${esc(e.source)}"><div class="small muted"><span>${esc(source[e.source]||e.source)}</span> · <time>${esc(new Date(e.received_at).toLocaleTimeString('zh-CN',{hour12:false}))}</time>${e.node_id?` · 节点 #${esc(e.node_id)}`:''}</div><strong>${esc(eventLabels[e.name]||e.name)}</strong><details data-disclosure="event-${e.seq}"><summary>原始事件</summary><p class="mono small">${esc(e.name)} · 接收序号 ${esc(e.seq)}</p><p>${esc(e.message)}</p></details></li>`).join('')}</ol>`:empty('等待节点事件。选择节点可停止或恢复。');
}
function samples(s) {return(s.frame?.snapshot?.nodes||[]).map(n=>fresh(s)?n:{...n,reachable:false,status:null,error:'样本过期，当前状态未知'});}
export function stageNodes(s) {const found=new Map(samples(s).map(n=>[n.id,n]));return(s.frame?.session?.config.nodes||[]).map(n=>found.get(n.id)||{id:n.id,reachable:false,identity_ok:false,status:null});}
export function overview() {return '<h1 class="sr-only">集群总览</h1><div id="stage-host" class="raft-stage" aria-label="固定成员逻辑拓扑"></div><div id="stage-alert" class="stage-alert"></div><aside id="node-detail" class="node-detail" aria-label="节点详情" hidden></aside>';}
export function nodeDetail(s) {
  const selected=samples(s).find(n=>n.id===s.selected), st=selected?.status;
  return `<button class="iconbtn detail-close" data-act="close-detail" aria-label="关闭节点详情">×</button><p class="eyebrow">节点详情</p><h2>Node ${esc(s.selected)}</h2>${tag(st?st.state+' · local':'未知',st?.state==='Leader'?'teal':'')}
    ${[['Term',st?.term],['报告 Leader',st?.leader_id?`#${st.leader_id}`:'未报告'],['LastLogIndex',st?.last_log_index],['CommitIndex',st?.commit_index],['LastApplied',st?.last_applied],['x',st?.x]].map(([k,v])=>`<div class="kv"><span>${k}</span><b class="mono">${esc(v)}</b></div>`).join('')}
    <div class="kv"><span>可达性</span><b>${selected?.reachable?'可达':'未知 / 不可达'}</b></div><div class="kv"><span>样本年龄</span><b>${Number.isFinite(age(s))?age(s).toFixed(1)+'s':'未知'}</b></div>
    ${selected?.error?`<p class="error-text">${esc(selected.error)}</p>`:''}
    <div class="actions">${button(s,'stop','停止节点','danger')}${button(s,'restart','恢复原节点')}</div>
    <p class="action-reason">${esc((s.bootstrap?.read_only_transport||!s.frame?.control_enabled)?(s.bootstrap?.control_allowed&&!s.bootstrap?.read_only_transport?'只读模式，可在会话设置启用控制。':'当前入口仅供查看；提交、停止和恢复操作未开放。'):!selected?.owned?'该节点当前没有本控制器持有的进程。':'只停止自有进程，原数据保留。')}</p>
    <button class="btn" data-act="node-logs">查看此节点日志</button>
    <details data-disclosure="node-details"><summary>观测说明</summary><p>Leader 是观察到的本地角色。连线不代表实测链路；日志一致性需单独校验。</p><p>展示事件丢弃：${num(st?.dropped_events)}</p></details>`;
}
export function stageNotice(s) {
  if(!s.connected)return '<p role="alert">后端连接中断 · 当前状态未知</p>';
  if(!s.frame?.session)return '<p>无活跃会话</p><button class="btn" data-page="settings">创建或恢复实验</button>';
  if(!fresh(s))return '<p role="status">样本过期 · 等待新的节点观测</p>';
  const errors=(s.frame?.snapshot?.nodes||[]).filter(n=>n.error&&n.reachable);
  if(errors.length)return `<p role="alert">${errors.length} 个节点返回错误；选择节点查看</p>`;
  return ''; // Historical gaps are disclosed separately from current connection failures.
}
export function logView(s) {
  const members=s.frame?.session?.config.nodes||[], selected=s.logNodes.length?s.logNodes:members.slice(0,2).map(n=>n.id), start=s.logFrom, limit=s.logLimit;
  const cells=Array.from({length:limit},(_,i)=>start+i).map(index=>`<tr><th class="mono">${index}</th>${selected.map(id=>{
    const range=s.logQuery?.nodes.includes(id)?s.logData[id]?.range:null,entry=range?.entries?.find(e=>e.index===index);
    const label=entry?(index<=range.last_applied?'已应用':index<=range.commit_index?'已提交':'未提交'):range&&index>range.last_log_index?'缺失':'未知';
    return `<td>${entry?`<button class="log-cell ${index<=range.commit_index?'teal':'amber'}" data-entry="${index}" data-entry-node="${id}"><span class="mono">T${entry.term} · ${esc(entry.command.op)} ${entry.command.op==='noop'?'':esc(entry.command.value)}</span><small>${label}${entry.command.op==='noop'?' · 内部 noop':''}</small></button>`:`<span class="muted small">${label}</span>`}</td>`;
  }).join('')}</tr>`).join('');
  return header('日志实验室','选择节点与索引窗口，比较真实日志。')+
    `<section class="panel pad"><form id="logs-form" class="actions"><label>起始索引<input name="from" id="log-from" type="number" min="1" value="${start}" required></label><label>窗口<select name="limit" id="log-limit">${[32,64,128,256].map(n=>`<option ${limit===n?'selected':''}>${n}</option>`).join('')}</select></label><button class="btn primary" type="submit">读取实际日志</button></form><div class="node-picker">${members.map(n=>`<label><input type="checkbox" data-log-node="${n.id}" ${selected.includes(n.id)?'checked':''}> #${n.id}</label>`).join('')}</div><p class="small muted">最多8个节点。点击单元格查看同索引比较；各节点采样不保证同时。</p></section>`+
    live('log-error',s.logError?`<div class="notice warn" role="alert">${esc(s.logError)}</div>`:'')+
    live('log-results',`<section class="panel"><div class="table-scroll log-matrix"><table><thead><tr><th>索引</th>${selected.map(id=>`<th>#${id}<small class="muted">revision ${esc(s.logData[id]?.range?.revision)}</small></th>`).join('')}</tr></thead><tbody>${Object.keys(s.logData).length?cells:`<tr><td colspan="${selected.length+1}">尚未读取。选择范围后点击“读取实际日志”。</td></tr>`}</tbody></table></div></section>`)+footer();
}
export function compareLogs(s,index) {
  const selected=s.logNodes.length?s.logNodes:(s.frame?.session?.config.nodes||[]).slice(0,2).map(n=>n.id);
  const rows=Object.entries(s.logData).filter(([id])=>selected.includes(Number(id))&&s.logQuery?.nodes.includes(Number(id))).map(([id,data])=>({id,range:data.range,entry:data.range?.entries?.find(e=>e.index===index)}));
  const signature=e=>e?JSON.stringify([e.term,e.command.op,e.command.value]):null;
  const baseline=signature(rows.find(r=>r.entry)?.entry);
  return `<table class="comparison-table"><thead><tr><th>节点</th><th>Term</th><th>命令</th><th>状态</th></tr></thead><tbody>${rows.map(({id,range,entry})=>`<tr class="${entry&&signature(entry)!==baseline?'different':''}"><td>#${esc(id)}</td><td>${esc(entry?.term)}</td><td class="mono">${entry?`${esc(entry.command.op)} ${entry.command.op==='noop'?'（内部）':esc(entry.command.value)}`:'未读取 / 缺失'}</td><td>${entry?(index<=range.last_applied?'已应用':index<=range.commit_index?'已提交':'未提交'):'未知'}</td></tr>`).join('')}</tbody></table><p class="small muted">不同项突出显示；未提交差异不等于已提交历史冲突。</p><details><summary>原始条目与 revision</summary><pre class="json-view">${esc(JSON.stringify(rows,null,2))}</pre></details>`;
}
export function faultContent(s) {
  const f=s.frame||{};
  return `<section class="panel pad"><h2>故障操作</h2><div class="actions">${button(s,'stop_all','停止全部自有节点','danger')}${button(s,'resume','恢复原会话')}${button(s,'generate','提交命令','primary')}${button(s,'experiment','独立分歧实验','','data-divergence="true"')}<button class="btn" disabled title="没有真实网络注入器；停止进程不等于分区">网络分区：不可用</button></div><p class="small muted">点选节点可查看停止与恢复操作。独立分歧实验另建目录。</p></section><section class="panel pad"><h2>实际事件</h2><details data-disclosure="event-semantics"><summary>时间与记录范围</summary><p>按接收序号显示最近100条，不表示跨机器精确时序。</p></details>${f.gap||f.stream_dropped?`<div class="notice warn">${eventGap(f)}</div>`:''}${events(f)}</section>`;
}
export function faults(s) {return header('故障实验','选择节点，观察重选与恢复。')+`<div class="fault-layout"><section style="position:relative"><div id="stage-alert" class="stage-alert"></div><div id="stage-host" class="raft-stage fault-stage" aria-label="故障实验逻辑拓扑"></div></section><div id="fault-content">${faultContent(s)}</div></div><aside id="node-detail" class="node-detail" aria-label="节点详情" hidden></aside>`;}
export function experiments(s) {
  const ops=(s.frame?.operations||[]).filter(o=>o.kind==='experiment'), active=activeExperiment(s), rows=ops.flatMap(o=>o.result?.rows||[]), deps=s.bootstrap?.experiment_dependencies;
  const environment=deps?.ready?'<span class="tag teal">实验环境已就绪</span>':`<div class="notice warn" role="status"><strong>实验环境未就绪</strong><p>${esc(deps?.reason||'正在核查 Go、Python 与源码。')}</p><details data-disclosure="dependencies"><summary>配置运行依赖</summary><p>规模实验需要满足 go.mod 的 Go、Python 3.12或以上以及完整源码。可配置便携工具 PATH 和 -python 后重新核查。普通演示无需这些工具；环境错误不代表 Raft 协议失败。</p></details></div>`;
  return header('性能实验','独立目录运行，保留成功、失败与中断记录。')+live('dependencies',environment)+
    `<section class="panel pad"><div class="actions"><button class="btn" data-preset="classroom">课堂复制</button><button class="btn" data-preset="scale">四规模选举</button><button class="btn" data-act="refresh-dependencies">重新核查环境</button></div><form id="experiment-form" class="experiment-fields"><fieldset><legend>节点规模</legend><div class="check-grid">${[3,11,10,20,50,100].map(n=>`<label><input type="checkbox" name="nodes" value="${n}" ${n===11?'checked':''}>${n} 节点</label>`).join('')}</div></fieldset><fieldset><legend>实验场景</legend><div class="check-grid">${Object.entries(scenarioLabels).map(([key,label])=>`<label><input type="checkbox" name="scenarios" value="${key}" ${key==='replication'?'checked':''}>${label}</label>`).join('')}</div></fieldset><div class="actions"><label>算术命令数<input name="entries" type="number" value="2101" min="256" max="100000" required></label><label>轮数<input name="rounds" type="number" value="1" min="1" max="10" required></label></div><details><summary>高级参数</summary><div class="actions"><label>种子<input name="seed" type="number" min="-2147483648" max="2147483647" value="42" required></label><label>复制批次<input name="batch" type="number" value="128" min="1" max="4096" required></label></div></details><p class="field-error" hidden></p><button type="submit" class="btn primary">运行实际实验</button><p class="action-reason" data-form-reason="experiment"></p></form></section>`+
    live('experiment-active',active?`<section class="panel pad">${receipt(active)}${button(s,'cancel_experiment','请求取消实验')}</section>`:'')+
    live('experiment-chart',`<section class="panel pad">${experimentChart(rows)}</section>`)+live('experiment-receipts',ops.filter(o=>o.ended_at).slice(-8).reverse().map(o=>`<section class="panel pad">${receipt(o)}</section>`).join(''))+footer();
}
export function evidence(s) {
  const f=s.frame||{};
  return header('一致性证据','当前收敛与历史前缀分别验证。',button(s,'verify','校验当前')+button(s,'verify_history','校验历史'))+
    live('evidence-checks',`<div class="cards3">${[['当前收敛',f.current_verification],['历史前缀',f.history_verification]].map(([title,v])=>{const state=verificationState(s,v);return `<section class="panel pad"><h2>${title}</h2><div class="result-state">${tag(checks[state]||state,state==='passed'?'teal':'amber')}</div><p>${esc(v?.error||(state==='passed'?'本次校验通过。':state==='stale'?'观测已变化，请重新校验。':'未执行时没有通过结论。'))}</p><p class="small mono">目标 ${v?.target||'—'} · ${v?.completed_at&&!v.completed_at.startsWith('0001')?esc(new Date(v.completed_at).toLocaleString()):'尚无完成时间'}</p></section>`;}).join('')}<section class="panel pad"><h2>固定检查点</h2>${f.checkpoint?`<p class="mono">index ${f.checkpoint.index} · x ${esc(f.checkpoint.x)}</p><div class="evidence-hash mono">${esc(f.checkpoint.hash)}</div>`:empty('先保存一次已提交前缀，用于故障后的历史核查。')}${button(s,'checkpoint',f.checkpoint?'替换历史检查点':'保存当前已提交前缀')}</section></div>`)+
    live('evidence-exports',`<section class="panel pad"><h2>原始证据</h2><p>导出配置身份、JSON/CSV、摘要、任务回执、事件与历史检查点。</p><div class="actions">${button(s,'export','生成证据 ZIP')}${(f.operations||[]).filter(o=>o.kind==='export'&&o.state==='succeeded').map(o=>`<a class="btn" href="/api/exports/${esc(o.id)}">下载 ${esc(o.id.slice(0,8))}</a>`).join('')}</div></section>`)+
    live('evidence-raw',`<details class="panel pad" data-disclosure="verification-raw"><summary>完整验证回执</summary><pre class="json-view">${esc(JSON.stringify({current:f.current_verification,history:f.history_verification},null,2))}</pre></details>`)+footer();
}
export function settings(s) {
  const f=s.frame||{},session=f.session;
  return header('会话与设置','固定成员不热改；关闭浏览器后集群继续运行。')+
    `<div class="settingsgrid">${live('settings-current',`<section class="panel pad"><h2>当前会话</h2><div class="kv"><span>名称</span><strong>${esc(session?.name||'尚未选择')}</strong></div><div class="kv"><span>模式</span><span>${s.bootstrap?.read_only_transport?'当前入口仅供查看':f.control_enabled?'已明确启用控制':'默认只读'}</span></div><div class="kv"><span>固定成员</span><span class="mono">${session?.config.nodes.map(n=>n.id).join(', ')||'—'}</span></div><div class="actions">${button(s,'enable_control','启用本机会话控制')}${button(s,'resume','恢复原会话')}</div><p class="action-reason">${esc(f.control_enabled&&!s.bootstrap?.read_only_transport?'':actionReason(s,'enable_control'))}</p><details data-disclosure="identity"><summary>只读身份与参数</summary><div class="kv"><span>cluster_id</span><code>${esc(session?.config.cluster_id)}</code></div><div class="kv"><span>session_id</span><code>${esc(session?.id)}</code></div><p>旧数据认领使用 CLI -claim-legacy 和原配置；页面不绕过身份保护。</p></details></section>`)}
    <section class="panel pad"><h2>新的独立实验</h2><form id="create-form" class="form-stack"><label>会话名称<input name="name" value="课堂演示" maxlength="60" required></label><label>节点数<input name="nodes" type="number" min="3" max="100" value="11" required></label><details><summary>高级参数</summary><label>复制批次<input name="batch" type="number" min="1" max="4096" value="128" required></label></details><p class="field-error" hidden></p><button class="btn primary" type="submit">创建并启动</button><p class="action-reason" data-form-reason="create_session"></p></form></section></div>`+
    live('session-list',`<section class="panel pad"><h2>已登记会话</h2><div class="actions">${(s.bootstrap?.sessions||[]).map(x=>`<button class="btn" data-session="${esc(x.id)}" ${x.id===session?.id||actionReason(s,'select_session')?'disabled':''}>${esc(x.name)} · ${x.config.nodes.length} 节点${x.id===session?.id?' · 当前':''}</button>`).join('')||'无历史会话'}</div><p class="small muted">先停止当前自有节点再切换；原配置和数据保留。</p></section>`)+
    '<section class="panel pad"><h2>显示偏好</h2><div class="actions"><button class="btn" data-act="theme">切换明暗主题</button><button class="btn" data-act="present">投影演示模式</button></div></section>'+footer();
}
function lesson(s){
  const f=s.frame||{},nodes=stageNodes(s),members=f.session?.config.nodes.length||0;
  const generated=(f.operations||[]).findLast(o=>o.kind==='generate'),target=generated?.result?.last_index||f.target||0;
  const applied=target?nodes.filter(n=>n.reachable&&n.identity_ok&&!n.error&&n.status?.last_applied>=target).length:0;
  const current=verificationState(s,f.current_verification),history=verificationState(s,f.history_verification);
  const ops=f.operations||[],stopped=ops.findLastIndex(o=>['stop','stop_all'].includes(o.kind)&&o.state==='succeeded');
  const restoreIndex=ops.findLastIndex(o=>['restart','resume'].includes(o.kind)&&o.state==='succeeded');
  const restored=stopped>=0&&restoreIndex>stopped;
  const generateIndex=ops.findLastIndex(o=>o.kind==='generate');
  const inFault=stopped>=0&&(!restored||generateIndex<restoreIndex);
  const ready=members>0&&fresh(s)&&nodes.length===members&&nodes.every(n=>n.reachable&&n.identity_ok&&!n.error);
  const waiting=generated&&generated.committed!==true&&(generated.accepted!==false||!generated.ended_at);
  const steps=[
    ['准备集群',members?`${nodes.filter(n=>n.reachable).length}/${members} 节点可达`:'创建11节点或恢复原会话',ready,'<button class="btn lesson-next" data-page="settings">会话设置</button>'],
    ['提交算术命令',generated?.committed===true?'已确认提交':waiting?'请求已发出；提交结果请查看回执':'2101 条命令 · 种子 42',generated?.committed===true,waiting?'<button class="btn lesson-next" data-act="show-task">查看回执</button>':button(s,'generate','提交命令','primary lesson-next')],
    ['应用与完整校验',`目标 ${target||'—'} · ${applied}/${members} 已应用 · ${checks[current]||current}`,Boolean(target&&applied===members&&current==='passed'),button(s,'verify','校验当前','lesson-next')],
    ['保存历史检查点',f.checkpoint?`固定前缀 #${f.checkpoint.index}`:'为故障前的已提交历史留存证据',Boolean(f.checkpoint),button(s,'checkpoint','保存检查点','lesson-next')],
    ['故障与恢复',restored?'进程已恢复；继续核查追赶和历史':'选择节点，确认停止，再用原数据恢复',restored,'<button class="btn lesson-next" data-page="faults">故障实验</button>'],
    ['验证恢复结果',`当前：${checks[current]||current} · 历史：${checks[history]||history}`,history==='passed'&&current==='passed'&&ready&&restored,button(s,'verify','校验当前','lesson-next')+button(s,'verify_history','校验历史','lesson-next')]
  ];
  const next=inFault?(restored?5:4):!ready?0:!generated?.committed?1:!(target&&applied===members&&current==='passed')?2:!f.checkpoint?3:4;
  return {steps,next,complete:inFault&&restored&&ready&&applied===members&&current==='passed'&&history==='passed'};
}
export function workflow(s){
  const{steps,next}=lesson(s);
  return `<button class="iconbtn detail-close" data-act="close-demo" aria-label="关闭演示流程">×</button><p class="eyebrow">课堂演示</p><h2>从提交到恢复</h2><p class="muted">每一步明确执行，结果分别确认。</p><ol class="workflow-steps">${steps.map(([title,note,done,actions],i)=>`<li class="workflow-step ${done?'complete':i===next?'current':''}"><strong>${title}</strong><p>${esc(note)}</p><div class="actions">${actions}</div></li>`).join('')}</ol><p class="small muted">恢复进程不等于完成追赶。索引进度不代替完整日志校验。</p>`;
}
export function lessonDock(s){
  const{steps,next,complete}=lesson(s),[title,note,,action]=steps[next];
  const readonly=s.bootstrap?.read_only_transport||s.bootstrap?.control_allowed===false;
  return `<button class="lesson-index" data-act="demo" aria-label="展开完整课堂流程">${complete?'✓':String(next+1).padStart(2,'0')}</button><div class="lesson-copy"><strong class="lesson-step">${readonly?'当前入口仅供查看':complete?'本轮课堂流程完成':title}</strong><span>${readonly?'实时观察节点与日志，控制操作未开放':esc(note)}</span></div>${readonly||complete?'<button class="btn lesson-next" data-act="demo">查看流程</button>':action}`;
}
export function stageChrome(s){
  const nodes=stageNodes(s),leaders=nodes.filter(n=>n.reachable&&n.identity_ok&&!n.error&&n.status?.state==='Leader');
  const state=!s.connected?'连接中断':!fresh(s)?'等待新鲜观测':leaders.length===1?`Leader #${leaders[0].id} · T${leaders[0].status.term}`:leaders.length>1?'观察到多个本地 Leader':'尚未观察到 Leader';
  return `<span class="stage-brand">MyRaft</span><span class="stage-session">${esc(s.frame?.session?.name||'共识观测台')}</span><span class="stage-observation ${!fresh(s)?'warning':''}">${esc(state)}</span>`;
}
export function stageLegend(s,visible=0,total=0){
  const nodes=stageNodes(s),count=nodes.filter(n=>n.reachable&&n.identity_ok&&!n.error).length;
  return `<summary>关系 ${visible}/${total} · ${count}/${nodes.length} 可达</summary><p>连线表示节点报告的 Leader 关系，不代表实测链路或复制确认。</p><p>点击节点突出关系；滚轮缩放、拖动平移。大集群全景用于概览，放大后阅读节点。</p>${eventGap(s.frame||{})?`<div class="event-gap">${eventGap(s.frame||{})}</div>`:''}`;
}
export function taskSummary(s) {
  if(s.pending)return `${labels[s.pendingKind]||'操作'} · 正在发送`;
  if(s.actionError)return s.actionError.unknown?'请求结果未知 · 请核对回执':'操作未完成 · 查看原因';
  const op=(s.frame?.operations||[]).at(-1)||s.lastReceipt;
  if(op?.kind==='generate'&&op.committed===true) {
    const target=op.result?.last_index||s.frame?.target, nodes=stageNodes(s);
    const applied=nodes.filter(n=>n.reachable&&n.identity_ok&&!n.error&&target&&n.status?.last_applied>=target).length;
    return `命令已提交 · ${fresh(s)&&target?`${applied}/${nodes.length} 节点已应用`:'应用进度待观测'}`;
  }
  if(op&&['restart','resume'].includes(op.kind)&&op.state==='succeeded')return '进程已恢复 · 请继续追赶与历史校验';
  if(op&&['verify','verify_history'].includes(op.kind)) {
    const status=verificationState(s,op.kind==='verify'?s.frame?.current_verification:s.frame?.history_verification);
    return `${labels[op.kind]} · ${checks[status]||status}`;
  }
  return op?`${labels[op.kind]||op.kind} · ${phases[op.state]||op.state}`:'';
}
export function taskBody(s) {
  const ops=(s.frame?.operations||[]).slice(-8).reverse();
  if(s.lastReceipt?.id&&!ops.some(o=>o.id===s.lastReceipt.id))ops.unshift(s.lastReceipt);
  return `${s.actionError?`<div class="notice warn" role="alert"><strong>${s.actionError.unknown?'请求结果未知':'操作未完成'}</strong><p>${esc(s.actionError.message)}</p>${s.actionError.unknown?'<p>不会自动重发。请查看已有任务与当前状态，确认后再决定下一步。</p>':''}<button class="btn" data-act="dismiss-error">知道了</button></div>`:''}${ops.slice(0,8).map(receipt).join('')}`;
}
