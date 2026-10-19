import {topology, experimentChart} from './charts.js';

export const pages = [['overview','集群总览','grid'],['logs','日志实验室','log'],['faults','故障与时间线','bolt'],['experiments','性能实验','chart'],['evidence','一致性证据','shield'],['settings','会话与设置','sliders']];
export const esc = value => String(value ?? '—').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const icon = name => `<svg class="ico" aria-hidden="true"><use href="#i-${name}"/></svg>`;
const num = n => n == null ? '—' : Number(n).toLocaleString('zh-CN');
const tag = (label, cls='') => `<span class="tag ${cls}">${esc(label)}</span>`;
const button = (act, label, disabled=false, cls='') => `<button class="btn ${cls}" data-act="${act}" ${disabled?'disabled':''}>${label}</button>`;
export function age(state) {const at = state.frame?.snapshot?.completed_at;return at && !at.startsWith('0001') ? (Date.now()-Date.parse(at))/1000 : Infinity;}
export function fresh(state) {return state.connected && age(state)<Math.max(5,(state.bootstrap?.poll_ms||1000)/1000*3);}
const controlled = s => s.frame?.control_enabled && fresh(s) && !s.frame?.busy && !s.pending;
const header = (title, subtitle, actions='') => `<div class="intro"><div><div class="eyebrow">CONSENSUS / REAL</div><h1>${title}</h1><p>${subtitle}</p></div><div class="actions">${actions}</div></div>`;
const empty = text => `<div class="empty-state muted">${esc(text)}</div>`;
const footer = () => `<div class="footer"><span>REAL · 本机 net/rpc 观测</span><span>本地角色 ≠ 多数派授权 · 索引对齐 ≠ 日志校验</span></div>`;
function receipt(op) {
  if (!op) return empty('尚未执行操作。请求受理、提交、全体应用和校验分别记录。');
  const accepted = op.accepted == null ? '未知 / 未返回' : op.accepted ? '已受理' : '未受理';
  const committed = op.committed == null ? '未确认' : op.committed ? '已提交' : '未确认提交';
  return `<div class="job"><strong>${esc(op.kind)} · ${esc(op.state)}</strong><p class="mono small">${esc(op.id)}</p><p>${accepted} → ${committed}</p>${op.error?`<p class="error-text">${esc(op.error)}</p>`:''}<p class="small muted">operation_id 仅跟踪控制器任务，不提供 Raft exactly-once。</p></div>`;
}
function events(frame, limit=20) {
  const rows=(frame?.eventsHistory||frame?.events||[]).slice(-limit).reverse();
  return rows.length ? `<ol class="timeline">${rows.map(e=>`<li><div class="small mono muted">#${e.seq} · ${esc(e.source)} · ${esc(new Date(e.received_at).toLocaleTimeString())}</div><strong>${esc(e.name)}</strong><p>${esc(e.message)}</p></li>`).join('')}</ol>` : empty('尚无实际事件。');
}
function samples(s) {return (s.frame?.snapshot?.nodes||[]).map(n=>fresh(s)?n:{...n,reachable:false,status:null,error:'样本过期，当前状态未知'});}

export function overview(s) {
  const f=s.frame||{}, nodes=samples(s), members=f.session?.config.nodes||[], reachable=nodes.filter(n=>n.reachable&&n.identity_ok).length;
  const leaders=nodes.filter(n=>n.status?.state==='Leader'), selected=nodes.find(n=>n.id===s.selected), status=selected?.status;
  const target=f.target||0, applied=nodes.filter(n=>target>0&&n.status?.last_applied>=target).length;
  const actions=button('verify','校验当前',!fresh(s)||!f.session||f.busy)+button('generate','＋ 提交命令',!controlled(s),'primary');
  return header('集群总览','让选举、复制与恢复可见，同时保留证据边界。',actions)+
    `<div class="metrics">${[
      ['节点可达',fresh(s)?`${reachable} <span>/ ${members.length}</span>`:'—','多数派门槛 '+(Math.floor(members.length/2)+1)+'；不等于写入授权'],
      ['观察到的 Leader',leaders.length?leaders.map(n=>`#${n.id} <span>term ${n.status.term}</span>`).join('<br>'):'—','本地角色；不同任期多 Leader 不直接判为违规'],
      ['固定目标索引',num(target||null),'仅由实际已提交回执或检查点设置'],
      ['达到应用目标',target?`${applied} <span>/ ${members.length}</span>`:'—','未运行完整校验时，不显示一致性通过']
    ].map(([label,value,note])=>`<div class="metric"><div class="metriclabel">${label}</div><div class="metricvalue mono">${value}</div><div class="metricfoot">${esc(note)}</div></div>`).join('')}</div>
    <div class="mainrow"><section class="panel"><div class="panelhead"><div><h2>集群拓扑</h2><p>选择节点查看三索引与真实回执</p></div>${tag(f.session?'共享快照':'等待会话','teal')}</div><div class="graph">${nodes.length?topology(nodes,s.selected,target):empty('在会话设置创建实验，或启动控制台时用 -config 登记已有集群。')}</div><div class="panefoot">逻辑关系，非实测链路 · 无心跳动画<span class="mono">snapshot #${f.snapshot?.seq||0}</span></div></section>
    <aside class="panel pad"><h2>节点详情 ${selected?'#'+selected.id:''}</h2>${selected?`${tag(status?status.state+' · local':'未知',status?.state==='Leader'?'teal':'')}<div class="kv"><span>当前任期</span><b>${num(status?.term)}</b></div><div class="kv"><span>Last / Commit / Applied</span><span class="mono">${num(status?.last_log_index)} / ${num(status?.commit_index)} / ${num(status?.last_applied)}</span></div><div class="kv"><span>状态机 x</span><b class="mono">${esc(status?.x)}</b></div><div class="kv"><span>普通输出丢弃</span><b>${num(status?.dropped_events)}</b></div><p class="small muted">${esc(selected.error||'仅观察，不代表完整日志已验证。')}</p><div class="actions">${button('stop','停止节点',!controlled(s)||!selected.owned,'danger')}${button('restart','恢复原节点',!controlled(s)||!f.session?.managed||selected.reachable)}</div>`:empty('选择一个节点。')}</aside></div>
    <div class="mainrow"><section class="panel"><div class="panelhead"><h2>日志复制进度</h2>${button('open-logs','查看日志 →')}</div><div class="table-scroll"><table><thead><tr><th>节点</th><th>可达 / 本地角色</th><th>Term</th><th>Last</th><th>Commit</th><th>Applied</th><th>x</th></tr></thead><tbody>${nodes.filter(n=>!s.filter||String(n.id).includes(s.filter)).sort((a,b)=>Number(a.reachable)-Number(b.reachable)||a.id-b.id).map(n=>`<tr><td><button class="node-link" data-node="${n.id}">#${n.id}</button></td><td>${esc(n.status?.state||'未知 / 不可达')}</td><td>${num(n.status?.term)}</td><td>${num(n.status?.last_log_index)}</td><td>${num(n.status?.commit_index)}</td><td>${num(n.status?.last_applied)}</td><td class="mono">${esc(n.status?.x)}</td></tr>`).join('')}</tbody></table></div></section><aside class="panel pad"><h2>操作与观测</h2>${receipt(f.operations?.at(-1))}${events(f,6)}</aside></div>`+footer();
}

export function logView(s) {
  const members=s.frame?.session?.config.nodes||[], selected=s.logNodes.length?s.logNodes:members.slice(0,2).map(n=>n.id), ranges=s.logData;
  const start=Number(s.logFrom),limit=Number(s.logLimit);
  const cells=Array.from({length:limit},(_,i)=>start+i).map(index=>`<tr><th class="mono">${index}</th>${selected.map(id=>{
    const range=ranges[id]?.range, entry=range?.entries?.find(e=>e.index===index);
    let label='未知',cls='';if(range&&!entry){label=index>range.last_log_index?'缺失':'未知';}else if(entry){label=index<=range.last_applied?'已应用':index<=range.commit_index?'已提交':'未提交';cls=index<=range.commit_index?'teal':'amber';}
    return `<td>${entry?`<button class="log-cell ${cls}" data-entry="${index}" data-entry-node="${id}"><span class="mono">T${entry.term} · ${esc(entry.command.op)}</span><small>${label}${entry.command.op==='noop'?' · 内部 noop':''}</small></button>`:`<span class="muted small">${label}</span>`}</td>`;
  }).join('')}</tr>`).join('');
  return header('日志实验室','有界索引窗口。内容来自 LogRange；不会根据聚合索引编造日志。')+
    `<section class="panel pad"><form id="logs-form" class="actions"><label>起始索引 <input id="log-from" type="number" min="1" value="${start}"></label><label>窗口 <select id="log-limit">${[32,64,128,256].map(n=>`<option ${limit===n?'selected':''}>${n}</option>`).join('')}</select></label><button class="btn primary" ${!fresh(s)||s.logLoading?'disabled':''}>${s.logLoading?'读取中…':'读取实际日志'}</button></form><div class="node-picker">${members.map(n=>`<label><input type="checkbox" data-log-node="${n.id}" ${selected.includes(n.id)?'checked':''}> #${n.id}</label>`).join('')}</div><p class="small muted">最多选 8 个节点；双节点同索引比较通过点击单元格查看。各节点 revision / term 属于各自快照，不宣称原子跨节点读取。</p></section>
    ${s.logError?`<div class="notice warn" role="alert">${esc(s.logError)}</div>`:''}<section class="panel" style="margin-top:18px"><div class="table-scroll log-matrix"><table><thead><tr><th>索引</th>${selected.map(id=>`<th>#${id}<small class="muted"> revision ${esc(ranges[id]?.range?.revision)}</small></th>`).join('')}</tr></thead><tbody>${Object.keys(ranges).length?cells:`<tr><td colspan="${selected.length+1}">尚未读取。请选择范围并点击读取，不自动执行完整历史扫描。</td></tr>`}</tbody></table></div></section>`+footer();
}

export function faults(s) {
  const f=s.frame||{}, nodes=samples(s);
  return header('故障与时间线','进程故障与网络分区分别处理。事件按接收顺序排列，非跨节点精确墙钟顺序。')+
    `<div class="cards3">${nodes.filter(n=>n.owned).map(n=>`<section class="panel pad"><h3>Node ${n.id} · ${esc(n.status?.state||'未知')}</h3><p>只操作当前控制器真正持有的进程句柄。</p><button class="btn danger" data-stop="${n.id}" ${controlled(s)?'':'disabled'}>停止节点 ${n.id}</button></section>`).join('')||empty('当前没有可停止的自有节点。只读登记不会认领外部 PID。')}</div>
    <section class="panel pad" style="margin-top:18px"><div class="actions">${button('stop-all','停止本会话全部节点',!controlled(s)||!nodes.some(n=>n.owned),'danger')}${button('resume','恢复原会话',!controlled(s)||!f.session?.managed)}<button class="btn" disabled title="没有真实网络注入器">网络分区：不可用</button>${button('divergence','独立分歧实验',!controlled(s))}</div><p class="small muted">恢复保留原身份、成员和数据；网络分区不会被停止进程代替。分歧实验使用独立目录。</p></section>
    <section class="panel pad" style="margin-top:18px"><h2>实际事件</h2>${f.gap||f.stream_dropped?`<div class="notice warn">事件/快照存在缺口，stream dropped=${f.stream_dropped||0}。不会补造缺失事件。</div>`:''}${events(f,100)}</section>`+footer();
}

export function experiments(s) {
  const ops=(s.frame?.operations||[]).filter(o=>o.kind==='experiment'), active=ops.find(o=>!o.ended_at), rows=ops.flatMap(o=>o.result?.rows||[]);
  return header('性能实验','每次独立构建与数据目录。按源码、环境、规模、场景和批次分组，不使用静态样例。')+
    `<section class="panel pad"><form id="experiment-form" class="experiment-fields"><label>节点规模<select name="nodes" multiple size="4">${[3,11,10,20,50,100].map(n=>`<option value="${n}" ${n===11?'selected':''}>${n}</option>`).join('')}</select></label><label>场景<select name="scenarios" multiple size="4">${['election','failover','catchup','divergence','replication'].map(n=>`<option ${n==='replication'?'selected':''}>${n}</option>`).join('')}</select></label><label>命令数<input name="entries" type="number" value="2101" min="256" max="100000"></label><label>轮数<input name="rounds" type="number" value="1" min="1" max="10"></label><label>种子<input name="seed" type="number" value="42"></label><label>批次<input name="batch" type="number" value="128" min="1" max="4096"></label><button class="btn primary" ${controlled(s)?'':'disabled'}>运行实际实验</button></form>${active?`<p>任务 ${esc(active.id)} · ${esc(active.state)} · 完成 ${active.result?.rows?.length||0} 轮</p>${button('cancel-experiment','请求取消实验',!s.frame?.control_enabled)}`:''}<p class="small muted">取消会清理该实验自己的节点，保留已完成、失败、中断记录。少量样本不报告可靠 p99。</p></section>
    <section class="panel pad" style="margin-top:18px">${experimentChart(rows)}</section>${ops.map(o=>`<section class="panel pad" style="margin-top:18px">${receipt(o)}</section>`).join('')}`+footer();
}

export function evidence(s) {
  const f=s.frame||{}, label=v=>!fresh(s)&&v?.state==='passed'?'stale':v?.state||'not_run';
  return header('一致性证据','当前节点收敛与历史前缀不变，是两种独立的验证。',button('verify','校验当前',!fresh(s)||f.busy)+button('verify-history','校验历史',!fresh(s)||!f.checkpoint||f.busy))+
    `<div class="cards3">${[['当前收敛',f.current_verification],['历史前缀',f.history_verification]].map(([title,v])=>`<section class="panel pad"><h2>${title}</h2>${tag(label(v),label(v)==='passed'?'teal':'amber')}<p>${esc(v?.error||'未执行时没有通过结论。')}</p><p class="small muted">${v?.at&&!v.at.startsWith('0001')?esc(new Date(v.at).toLocaleString()):'尚无时间记录'}</p></section>`).join('')}<section class="panel pad"><h2>固定检查点</h2>${f.checkpoint?`<p class="mono">index ${f.checkpoint.index} · x ${f.checkpoint.x}</p><div class="evidence-hash mono">${esc(f.checkpoint.hash)}</div>`:empty('尚未保存历史检查点。')}${button('checkpoint','保存当前已提交前缀',!fresh(s)||f.busy)}</section></div>
    <section class="panel pad" style="margin-top:18px"><h2>导出可核对的原始证据</h2><p>包含原始 JSON/CSV、身份配置、源码与二进制摘要、回执、事件、固定检查点和实验结果。不会导出 CSRF 凭据或以截图代替数据。</p>${button('export','生成证据 ZIP',!f.session||f.busy)}${(f.operations||[]).filter(o=>o.kind==='export'&&o.state==='succeeded').map(o=>` <a class="btn" href="/api/exports/${esc(o.id)}">下载 ${esc(o.id.slice(0,8))}</a>`).join('')}</section>
    <section class="panel pad" style="margin-top:18px"><h2>验证回执</h2><pre class="json-view">${esc(JSON.stringify({current:f.current_verification,history:f.history_verification},null,2))}</pre></section>`+footer();
}

export function settings(s) {
  const f=s.frame||{}, session=f.session, allowed=s.bootstrap?.control_allowed;
  return header('会话与设置','成员身份由节点持久层保护。新规模创建新会话，不热改已有数据。')+
    `<div class="notice">REAL 模式。后端断线不会回退到演示数据。关闭浏览器不会停止集群；控制器只操作自己持有的进程。</div>
    <div class="settingsgrid"><section class="panel pad"><h2>当前登记</h2><div class="kv"><span>集群身份</span><code>${esc(session?.config.cluster_id)}</code></div><div class="kv"><span>会话</span><code>${esc(session?.id)}</code></div><div class="kv"><span>固定成员</span><span class="mono">${session?.config.nodes.map(n=>n.id).join(', ')||'—'}</span></div><div class="kv"><span>模式</span><span>${f.control_enabled?'已明确启用控制':'默认只读'}</span></div><p class="small muted">${allowed?'可明确启用本机控制；之后每次停机仍需确认。':'服务端未允许控制。需要以 -allow-control 启动，再在此明确启用。'}</p>${button('enable-control','启用本机会话控制',!allowed||f.control_enabled||!s.connected)}<p>旧数据认领须用 CLI 对原配置执行 -claim-legacy，保留备份；页面没有忽略身份冲突的按钮。</p></section>
    <section class="panel pad"><h2>创建新的独立实验</h2><form id="create-form" class="form-stack"><label>会话名称<input name="name" value="课堂演示" maxlength="60"></label><label>节点数<input name="nodes" type="number" min="3" max="100" value="11"></label><label>复制批次<input name="batch" type="number" min="1" max="4096" value="128"></label><button class="btn primary" ${f.control_enabled&&!f.busy?'':'disabled'}>创建并启动</button></form><p class="small muted">端口、身份和目录由服务端登记。不得输入任意路径、PID 或 shell。</p></section></div>
    <section class="panel pad" style="margin-top:18px"><h2>已登记会话</h2><div class="actions">${(s.bootstrap?.sessions||[]).map(x=>`<button class="btn" data-session="${esc(x.id)}" ${x.id===session?.id||f.busy?'disabled':''}>${esc(x.name)} · ${x.config.nodes.length} 节点</button>`).join('')||'无历史会话'}</div><p>先停止当前自有节点再切换；数据保留。控制器重启不凭旧 PID 接管仍在运行的外部进程。</p></section>
    <section class="panel pad" style="margin-top:18px"><div class="actions">${button('theme','切换明暗主题')}${button('present','投影演示模式')}</div></section>`+footer();
}
