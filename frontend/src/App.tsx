import {
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { ConsoleClient } from "./client";
import { actionReason, fresh, scopeKey, scopeOf } from "./actions";
import { initialCenter, observe, updateCenter, type ViewNode } from "./model";
import { TopologyPanel } from "./components/TopologyPanel";
import { Icon } from "./components/Icon";
import { deriveSummary, updateRate, type RateWindow } from "./summary";
import { mergeReceipts, type ReceiptView } from "./receipts";
import type {
  ClientState,
  OperationKind,
  OperationParams,
  RendererKind,
  Scope,
} from "./types";

const labels: Record<OperationKind, string> = {
  generate: "提交命令",
  verify: "校验当前",
  checkpoint: "保存检查点",
  verify_history: "校验历史",
  stop: "停止节点",
  restart: "恢复原节点",
  stop_all: "停止自有节点",
  resume: "恢复会话",
  enable_control: "启用本机控制",
  create_session: "创建会话",
  select_session: "切换会话",
  export: "导出证据",
  experiment: "性能实验",
  cancel_experiment: "取消实验",
};
const phases: Record<string, string> = {
  queued: "已登记",
  running: "进行中",
  succeeded: "任务完成",
  failed: "失败",
  unknown: "结果未知",
  interrupted: "已中断",
  canceled: "已取消",
  cancel_requested: "正在取消",
};
const checks: Record<string, string> = {
  not_run: "未运行",
  running: "执行中",
  passed: "通过",
  failed: "失败",
  partial: "部分不可达",
  partial_unreachable: "部分不可达",
  stale: "已过期",
  unreachable: "部分不可达",
};
const client = new ConsoleClient();
interface Confirmation {
  kind: OperationKind;
  scope: Scope;
  nodeID?: number;
}
function modeFromURL(): RendererKind {
  const mode = new URLSearchParams(location.search).get("renderer");
  return mode === "flow" || mode === "compare" ? mode : "svg";
}

export function App() {
  const state = useSyncExternalStore(client.subscribe, client.getSnapshot);
  const [mode, setMode] = useState<RendererKind>(modeFromURL),
    [now, setNow] = useState(Date.now());
  const [selected, setSelected] = useState<number | null>(null),
    [detail, setDetail] = useState(false),
    [filter, setFilter] = useState("all");
  const [focusRequest, setFocusRequest] = useState(0),
    [search, setSearch] = useState(""),
    [error, setError] = useState("");
  const [dialog, setDialog] = useState<Confirmation | null>(null),
    [tasks, setTasks] = useState(false),
    [evidence, setEvidence] = useState(false);
  const [theme, setTheme] = useState(
      () => localStorage.getItem("myraft-prototype-theme") || "dark",
    ),
    [present, setPresent] = useState(false);
  const [menu, setMenu] = useState<"session" | "navigation" | null>(null);
  const [keyboardOwner, setKeyboardOwner] = useState<"svg" | "flow">("svg");
  const sessionTrigger = useRef<HTMLButtonElement>(null),
    navigationTrigger = useRef<HTMLButtonElement>(null);
  const sessionPanel = useRef<HTMLDivElement>(null),
    navigationPanel = useRef<HTMLElement>(null);
  const dialogOrigin = useRef<HTMLElement | null>(null);
  const rateRef = useRef<RateWindow | null>(null),
    receiptsRef = useRef<ReceiptView | null>(null);
  const searchRef = useRef<HTMLInputElement>(null),
    centerRef = useRef(initialCenter());
  const scope = scopeOf(state),
    key = scopeKey(scope);
  const observation = useMemo(() => observe(state, now), [state, now]);
  rateRef.current = updateRate(rateRef.current, state, now);
  const summary = deriveSummary(state, now, rateRef.current, observation);
  receiptsRef.current = mergeReceipts(receiptsRef.current, state);
  const operations = receiptsRef.current.operations;
  centerRef.current = updateCenter(
    centerRef.current,
    observation,
    key,
    state.frame?.snapshot.seq ?? 0,
  );
  const selectedNode = observation.nodes.find((n) => n.id === selected);
  useEffect(() => client.start(), []);
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("myraft-prototype-theme", theme);
  }, [theme]);
  useEffect(() => {
    document.documentElement.dataset.present = String(present);
  }, [present]);
  useEffect(() => {
    setSelected(null);
    setDetail(false);
    setDialog(null);
    setMenu(null);
    setEvidence(false);
    setKeyboardOwner("svg");
    setError("");
    setFilter("all");
    setSearch("");
    setTasks(false);
  }, [key]);
  useEffect(() => {
    if (
      !tasks &&
      !((detail || evidence) && window.matchMedia("(max-width:700px)").matches)
    )
      return;
    const frame = requestAnimationFrame(() =>
      document
        .querySelector<HTMLElement>(
          tasks ? ".task-panel" : ".workspace .inspector",
        )
        ?.scrollIntoView({ block: "nearest" }),
    );
    return () => cancelAnimationFrame(frame);
  }, [tasks, detail, evidence]);
  function closeMenu(restore = false) {
    const trigger =
      menu === "session" ? sessionTrigger.current : navigationTrigger.current;
    setMenu(null);
    if (restore) trigger?.focus({ preventScroll: true });
  }
  useEffect(() => {
    if (!menu) return;
    const content =
      menu === "session" ? sessionPanel.current : navigationPanel.current;
    const trigger =
      menu === "session" ? sessionTrigger.current : navigationTrigger.current;
    const dismiss = (event: Event) => {
      if (
        !content?.contains(event.target as Node) &&
        !trigger?.contains(event.target as Node)
      )
        setMenu(null);
    };
    document.addEventListener("pointerdown", dismiss, true);
    document.addEventListener("focusin", dismiss);
    content
      ?.querySelector<HTMLElement>("button:not([disabled]),a[href]")
      ?.focus({ preventScroll: true });
    return () => {
      document.removeEventListener("pointerdown", dismiss, true);
      document.removeEventListener("focusin", dismiss);
    };
  }, [menu]);
  useEffect(() => {
    const keydown = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        searchRef.current?.focus();
        searchRef.current?.select();
      }
      if (event.key === "Escape" && !dialog) {
        if (menu) {
          event.preventDefault();
          closeMenu(true);
          return;
        }
        setSelected(null);
        setDetail(false);
        setTasks(false);
        setEvidence(false);
      }
    };
    window.addEventListener("keydown", keydown);
    return () => window.removeEventListener("keydown", keydown);
  }, [dialog, menu]);
  function select(id: number | null) {
    setSelected(id);
    setDetail(id !== null);
    setEvidence(false);
    setTasks(false);
  }
  function changeMode(value: RendererKind) {
    setMode(value);
    if (value !== "compare") setKeyboardOwner(value);
    const url = new URL(location.href);
    url.searchParams.set("renderer", value);
    history.replaceState(null, "", url);
  }
  async function execute(
    kind: OperationKind,
    params: OperationParams = {},
    expected = scopeOf(client.getSnapshot()),
  ) {
    try {
      setError("");
      await client.execute(kind, params, expected);
    } catch (e) {
      if (scopeKey(expected) === scopeKey(scopeOf(client.getSnapshot())))
        setError((e as Error).message);
    }
  }
  function action(kind: OperationKind, nodeID?: number, trigger?: HTMLElement) {
    const reason = actionReason(state, kind, nodeID);
    if (reason) {
      setError(reason);
      return;
    }
    dialogOrigin.current = trigger?.closest(".session-popover")
      ? sessionTrigger.current
      : trigger || (document.activeElement as HTMLElement);
    setMenu(null);
    if (
      [
        "enable_control",
        "create_session",
        "generate",
        "stop",
        "stop_all",
      ].includes(kind) ||
      (kind === "checkpoint" && state.frame?.checkpoint)
    ) {
      setDialog({ kind, scope: scopeOf(state), nodeID });
      return;
    }
    void execute(kind, nodeID !== undefined ? { node_id: nodeID } : {});
  }
  function button(
    kind: OperationKind,
    title = labels[kind],
    className = "",
    nodeID?: number,
  ) {
    const reason = actionReason(state, kind, nodeID);
    return (
      <button
        className={className}
        data-act={kind}
        disabled={!!reason}
        title={reason || title}
        onClick={(event) => action(kind, nodeID, event.currentTarget)}
      >
        {title}
      </button>
    );
  }
  const latest = operations.at(-1);
  const age = state.frame?.snapshot.completed_at
    ? (now - Date.parse(state.frame.snapshot.completed_at)) / 1000
    : Infinity;
  const done =
    observation.fresh &&
    !!state.frame?.target &&
    observation.nodes.length > 0 &&
    observation.nodes.every(
      (n) => n.status && n.status.last_applied >= state.frame!.target,
    );
  const modeName =
    state.bootstrap?.read_only_transport || !state.bootstrap?.control_allowed
      ? "只读入口"
      : state.frame?.control_enabled
        ? "本机控制"
        : "只读 · 可启用控制";
  return (
    <div className="workbench">
      <header className="topbar">
        <button
          className="icon-button mobile-menu"
          ref={navigationTrigger}
          aria-label="打开工作区导航"
          aria-controls="navigation-popover"
          aria-expanded={menu === "navigation"}
          onClick={() =>
            setMenu((current) =>
              current === "navigation" ? null : "navigation",
            )
          }
        >
          <Icon name="menu" />
        </button>
        <a className="product" href="/" title="返回原版六页控制台">
          <span className="product-mark">
            <i />
            <i />
            <i />
          </span>
          <b>MyRaft</b>
          <span>拓扑工作台</span>
        </a>
        <button
          className="session-switch"
          ref={sessionTrigger}
          aria-label="会话操作"
          aria-controls="session-popover"
          aria-expanded={menu === "session"}
          onClick={() =>
            setMenu((current) => (current === "session" ? null : "session"))
          }
        >
          <span className={`status-dot ${state.connected ? "" : "offline"}`} />
          <span>{state.frame?.session?.name || "尚无会话"}</span>
          <Icon name="chevron" size={14} />
        </button>
        <div className="header-space" />
        <form
          className="node-search"
          onSubmit={(e) => {
            e.preventDefault();
            const id = Number(search.trim().replace(/^#/, ""));
            if (observation.nodes.some((n) => n.id === id)) {
              select(id);
              setFilter("all");
              setFocusRequest((n) => n + 1);
              setError("");
            } else setError("当前固定成员中没有这个节点 ID。");
          }}
        >
          <Icon name="search" size={16} />
          <input
            ref={searchRef}
            aria-label="搜索节点"
            placeholder="查找节点"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <kbd>⌘ K</kbd>
        </form>
        {button("generate", "提交命令", "primary")}
        {button("verify", "校验当前", "header-verify")}
        <button
          className="icon-button"
          aria-label="切换主题"
          onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
        >
          <Icon name={theme === "dark" ? "sun" : "moon"} />
        </button>
        <button
          className="icon-button presentation"
          aria-label="切换投影模式"
          aria-pressed={present}
          onClick={() => setPresent(!present)}
        >
          <Icon name="fit" />
        </button>
      </header>
      <nav className="rail" aria-label="工作区">
        <button className="active" aria-label="集群总览" title="集群总览">
          <Icon name="network" />
        </button>
        <a
          href="/#logs"
          aria-label="日志实验室（原版）"
          title="日志实验室 · 原版保留"
        >
          <Icon name="logs" />
        </a>
        <a
          href="/#faults"
          aria-label="故障实验（原版）"
          title="故障实验 · 原版保留"
        >
          <Icon name="fault" />
        </a>
        <a
          href="/#experiments"
          aria-label="性能实验（原版）"
          title="性能实验 · 原版保留"
        >
          <Icon name="chart" />
        </a>
        <button
          aria-label="一致性证据"
          aria-pressed={evidence}
          onClick={() => {
            setEvidence(!evidence);
            setDetail(false);
          }}
        >
          <Icon name="shield" />
        </button>
        <div className="rail-spacer" />
        <a
          href="/#settings"
          aria-label="会话设置（原版）"
          title="会话设置 · 原版保留"
        >
          <Icon name="settings" />
        </a>
      </nav>
      <main
        className={`workspace ${detail || evidence ? "with-inspector" : ""} ${tasks ? "with-tasks" : ""}`}
      >
        <section className="cluster-overview" aria-label="集群摘要">
          <div className="workspace-bar cluster-hero">
            <div className="hero-heading">
              <p className="eyebrow">CLUSTER OBSERVATORY</p>
              <h1 title={state.frame?.session?.name}>
                {state.frame?.session?.name || "集群工作台"}
              </h1>
              <div className="hero-status">
                <span
                  className={`observation-badge ${summary.tone}`}
                  data-observation-state
                >
                  {summary.label}
                </span>
                {summary.leader && (
                  <span>
                    #{summary.leader.id} · Term {summary.leader.status?.term}
                  </span>
                )}
                <span>
                  {summary.reachable === null
                    ? "可达性未知"
                    : `${summary.reachable} / ${summary.total} 可达`}
                </span>
                <span>
                  {Number.isFinite(age)
                    ? `${observation.fresh ? "采样" : "上次采样"} ${Math.max(0, age).toFixed(1)}s 前`
                    : "等待采样"}
                </span>
              </div>
            </div>
            <div className="hero-controls">
              <div className="renderer-switch" aria-label="原型渲染器">
                {(["svg", "flow", "compare"] as const).map((m) => (
                  <button
                    key={m}
                    aria-pressed={mode === m}
                    onClick={() => changeMode(m)}
                  >
                    {m === "svg"
                      ? "SVG"
                      : m === "flow"
                        ? "React Flow"
                        : "并排比较"}
                  </button>
                ))}
              </div>
              <select
                aria-label="节点状态筛选"
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
              >
                {[
                  ["all", "全部状态"],
                  ["Leader", "Leader"],
                  ["Follower", "Follower"],
                  ["Candidate", "Candidate"],
                  ["offline", "不可达 / 未知"],
                  ["exception", "例外"],
                ].map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <div
            className="kpi-strip"
            role="region"
            aria-label="Leader观测指标，窄屏可横向滚动"
            tabIndex={0}
          >
            {[
              [
                "leader",
                "Leader",
                summary.leader ? `#${summary.leader.id}` : "—",
                summary.leader ? "唯一有效本地角色观测" : "无唯一有效 Leader",
              ],
              [
                "term",
                "Term",
                summary.leader?.status?.term ?? "—",
                "Leader 当前任期",
              ],
              [
                "commit",
                "Commit",
                summary.leader?.status?.commit_index ?? "—",
                "Leader 已提交日志索引",
              ],
              [
                "applied",
                "Applied",
                summary.leader?.status?.last_applied ?? "—",
                "Leader 已应用日志索引",
              ],
              [
                "x",
                "State x",
                summary.leader?.status?.x ?? "—",
                "Leader 的精确整数状态",
              ],
              [
                "rpc",
                "监控 RPC/s",
                summary.rate === null ? "—" : summary.rate.toFixed(1),
                "控制台观测与校验请求尝试；不代表 Raft 通信吞吐",
              ],
            ].map(([id, label, value, description]) => (
              <div
                className={`kpi kpi-${id}`}
                key={id}
                title={String(description)}
              >
                <span className="kpi-label">{label}</span>
                <strong
                  className={String(value).length > 12 ? "long-value" : ""}
                  data-kpi={id}
                >
                  {value}
                </strong>
              </div>
            ))}
          </div>
          <p className="kpi-context">
            {summary.leader
              ? `前五项来自 Leader #${summary.leader.id} 的本地观测，非全体一致结论。`
              : "没有唯一有效 Leader，前五项显示未知。"}
            <span>监控速率：相邻完整采样的请求尝试。</span>
          </p>
        </section>
        {(state.error || error) && (
          <div className="notice-error" role="alert">
            <span>
              {state.unknownWrite
                ? "结果未知，请先核查回执，勿重复发送。 "
                : ""}
              {error || state.error}
            </span>
            <button
              aria-label="关闭错误提示"
              onClick={() => {
                setError("");
                client.dismissError();
              }}
            >
              ×
            </button>
          </div>
        )}
        <div className={`stage-area ${mode === "compare" ? "comparison" : ""}`}>
          {(mode === "compare" ? (["svg", "flow"] as const) : [mode]).map(
            (renderer) => (
              <TopologyPanel
                key={renderer}
                renderer={renderer}
                observation={observation}
                center={centerRef.current.display}
                scope={key}
                selected={selected}
                filter={filter}
                onSelect={select}
                keyboardActive={
                  mode !== "compare" || keyboardOwner === renderer
                }
                onActivate={() => setKeyboardOwner(renderer)}
                focusRequest={focusRequest}
              />
            ),
          )}
        </div>
        {detail && selectedNode && (
          <Inspector
            node={selectedNode}
            state={state}
            age={age}
            onClose={() => {
              setDetail(false);
              requestAnimationFrame(() =>
                document
                  .querySelector<HTMLElement>(`[data-node="${selected}"]`)
                  ?.focus({ preventScroll: true }),
              );
            }}
            actions={
              <>
                {button("stop", "停止节点", "danger", selectedNode.id)}
                {button("restart", "恢复原节点", "", selectedNode.id)}
              </>
            }
          />
        )}
        {evidence && (
          <aside className="inspector evidence-inspector">
            <div className="inspector-heading">
              <span className="eyebrow">一致性证据</span>
              <button
                className="icon-button"
                aria-label="关闭证据"
                onClick={() => setEvidence(false)}
              >
                <Icon name="close" />
              </button>
            </div>
            <h2>提交与验证</h2>
            <div className="evidence-step">
              <span>目标日志索引</span>
              <b>{state.frame?.target || "—"}</b>
            </div>
            <div className="evidence-step">
              <span>全体应用至目标</span>
              <b>{done ? "已观察到" : "尚未确认"}</b>
            </div>
            {(["current_verification", "history_verification"] as const).map(
              (field) => {
                const verification = state.frame?.[field];
                const status =
                  !fresh(state) && verification?.state === "passed"
                    ? "stale"
                    : verification?.state || "not_run";
                return (
                  <div className="verification" key={field}>
                    <span>
                      {field === "current_verification"
                        ? "当前完整校验"
                        : "历史前缀校验"}
                    </span>
                    <b
                      data-verification={field}
                      className={status === "passed" ? "good" : ""}
                    >
                      {checks[status] || status}
                    </b>
                    <small>
                      {verification?.error ||
                        `目标索引 ${verification?.target || "—"}`}
                    </small>
                  </div>
                );
              },
            )}
            <div className="actions">{button("verify_history")}</div>
            <div className="checkpoint">
              <span className="eyebrow">固定检查点</span>
              <p>
                index <b>{state.frame?.checkpoint?.index || "—"}</b> · x{" "}
                {state.frame?.checkpoint?.x ?? "—"}
              </p>
              <code>{state.frame?.checkpoint?.hash || "尚未保存历史前缀"}</code>
              {button("checkpoint")}
            </div>
            {button("export")}
            <p className="footnote">
              应用完成与完整一致性校验分别判断；检查点不会被更大的提交索引自动替换。
            </p>
          </aside>
        )}
        {tasks && (
          <section className="task-panel" aria-label="任务回执">
            <div className="task-panel-head">
              <b>任务与事件</b>
              <button aria-label="收起任务" onClick={() => setTasks(false)}>
                ×
              </button>
            </div>
            <div className="task-columns">
              <div>
                {[...operations]
                  .reverse()
                  .slice(0, 8)
                  .map((op) => (
                    <article
                      className="task-receipt"
                      key={op.id}
                      data-operation={op.id}
                    >
                      <div>
                        <strong>{labels[op.kind]}</strong>
                        <span>{phases[op.state] || op.state}</span>
                      </div>
                      {op.kind === "generate" && (
                        <p>
                          {op.accepted === true
                            ? "已受理"
                            : op.accepted === false
                              ? "未受理"
                              : "受理未知"}{" "}
                          · {op.committed === true ? "已提交" : "提交未确认"}
                        </p>
                      )}
                      {op.kind === "restart" && (
                        <p>进程恢复后仍需追赶与校验。</p>
                      )}
                      {op.error && <p className="error-text">{op.error}</p>}
                      <details>
                        <summary>原始回执</summary>
                        <pre>{JSON.stringify(op, null, 2)}</pre>
                      </details>
                      {op.kind === "export" &&
                        typeof op.result?.url === "string" && (
                          <a href={op.result.url}>下载证据</a>
                        )}
                    </article>
                  ))}
              </div>
              <ol className="event-list">
                {state.events
                  .slice(-30)
                  .reverse()
                  .map((event) => (
                    <li key={event.seq}>
                      <time>
                        {new Date(event.received_at).toLocaleTimeString(
                          "zh-CN",
                          { hour12: false },
                        )}
                      </time>
                      <span>
                        {event.source === "node"
                          ? "节点"
                          : event.source === "control"
                            ? "操作"
                            : "观测"}{" "}
                        {event.node_id ? `#${event.node_id}` : ""}
                      </span>
                      <code>{event.name}</code>
                    </li>
                  ))}
              </ol>
            </div>
          </section>
        )}
      </main>
      <footer className="statusbar">
        <span className={`status-dot ${observation.fresh ? "" : "offline"}`} />
        <span>{state.connected ? "REAL" : "连接中断"}</span>
        <span>{modeName}</span>
        <span className="sample-age">
          {Number.isFinite(age)
            ? `${Math.max(0, age).toFixed(1)}s 前采样`
            : "等待数据"}
        </span>
        <span className="gap-status">
          {state.gap ? "历史事件有缺口 · " : ""}丢弃 {state.dropped}
        </span>
        <div className="header-space" />
        <button
          className="task-trigger"
          aria-expanded={tasks}
          onClick={() => {
            setTasks(!tasks);
            setDetail(false);
            setEvidence(false);
          }}
        >
          {latest
            ? `${labels[latest.kind]} · ${phases[latest.state] || latest.state}`
            : "尚无任务"}
          <Icon name="chevron" size={14} />
        </button>
      </footer>
      {menu === "session" && (
        <div
          className="session-popover"
          id="session-popover"
          ref={sessionPanel}
        >
          <div>
            <b>会话控制</b>
            <button aria-label="关闭会话菜单" onClick={() => closeMenu(true)}>
              ×
            </button>
          </div>
          <p>{modeName}</p>
          {button("enable_control")}
          {button("create_session")}
          {button("resume")}
          {button("stop_all", "停止全部自有节点", "danger")}
          <a href="/#settings">完整会话管理 →</a>
        </div>
      )}
      {menu === "navigation" && (
        <nav
          className="mobile-navigation"
          id="navigation-popover"
          ref={navigationPanel}
          aria-label="手机工作区"
        >
          <button onClick={() => closeMenu(true)}>集群总览</button>
          <a href="/#logs">日志实验室 · 原版</a>
          <a href="/#faults">故障实验 · 原版</a>
          <a href="/#experiments">性能实验 · 原版</a>
          <button
            onClick={() => {
              setEvidence(true);
              setDetail(false);
              closeMenu(true);
            }}
          >
            一致性证据
          </button>
          <a href="/#settings">会话设置 · 原版</a>
        </nav>
      )}
      <Dialog.Root
        open={!!dialog}
        onOpenChange={(open) => !open && setDialog(null)}
      >
        <Dialog.Portal>
          <Dialog.Overlay className="dialog-overlay" />
          <Dialog.Content
            className="dialog-content"
            onCloseAutoFocus={(event) => {
              event.preventDefault();
              const origin = dialogOrigin.current;
              (origin?.isConnected ? origin : sessionTrigger.current)?.focus({
                preventScroll: true,
              });
            }}
          >
            <Dialog.Title>
              {dialog ? labels[dialog.kind] : ""}
              {dialog?.nodeID !== undefined ? ` #${dialog.nodeID}` : ""}
            </Dialog.Title>
            <Dialog.Description>
              {dialog?.kind === "generate"
                ? "确定性算术命令由 Leader 通过真实 Raft 提交。受理或提交未知时不会自动重发。"
                : dialog?.kind === "stop" || dialog?.kind === "stop_all"
                  ? `仅停止本控制器持有的进程，保留原配置和数据。固定成员 ${observation.nodes.length} 个，多数派门槛 ${Math.floor(observation.nodes.length / 2) + 1}。可达数量不是多数派授权证明。`
                  : dialog?.kind === "enable_control"
                    ? "允许控制本机会话。停止节点仍需单独确认。"
                    : dialog?.kind === "checkpoint"
                      ? "替换后将以新的已提交前缀进行历史校验。通常应保留故障前的原检查点。"
                      : "创建独立配置和数据目录，不更改当前固定成员。"}
            </Dialog.Description>
            <form
              onSubmit={async (e) => {
                e.preventDefault();
                if (!dialog) return;
                const form = new FormData(e.currentTarget),
                  captured = dialog;
                let params: OperationParams = {};
                if (captured.kind === "generate")
                  params = {
                    count: Number(form.get("count")),
                    seed: Number(form.get("seed")),
                  };
                if (captured.kind === "create_session")
                  params = {
                    name: String(form.get("name")),
                    nodes: [Number(form.get("nodes"))],
                    batch: 128,
                  };
                if (
                  ["stop", "stop_all", "enable_control"].includes(captured.kind)
                )
                  params = {
                    confirm: true,
                    ...(captured.nodeID !== undefined
                      ? { node_id: captured.nodeID }
                      : {}),
                  };
                await execute(captured.kind, params, captured.scope);
                setDialog((current) => (current === captured ? null : current));
              }}
            >
              {dialog?.kind === "generate" && (
                <>
                  <label>
                    算术命令数
                    <input
                      name="count"
                      type="number"
                      min="1"
                      max="100000"
                      defaultValue="2101"
                      required
                    />
                  </label>
                  <label>
                    随机种子
                    <input
                      name="seed"
                      type="number"
                      min="-2147483648"
                      max="2147483647"
                      defaultValue="42"
                      required
                    />
                  </label>
                </>
              )}
              {dialog?.kind === "create_session" && (
                <>
                  <label>
                    会话名称
                    <input
                      name="name"
                      defaultValue="拓扑对比实验"
                      maxLength={80}
                      required
                    />
                  </label>
                  <label>
                    固定成员数
                    <select name="nodes" defaultValue="11">
                      {[3, 11, 20, 50, 100].map((n) => (
                        <option key={n}>{n}</option>
                      ))}
                    </select>
                  </label>
                </>
              )}
              <div className="dialog-actions">
                <Dialog.Close asChild>
                  <button type="button">取消</button>
                </Dialog.Close>
                <button
                  data-testid="confirm"
                  className={
                    dialog?.kind === "stop" || dialog?.kind === "stop_all"
                      ? "danger"
                      : "primary"
                  }
                  disabled={state.pending}
                  type="submit"
                >
                  {state.pending
                    ? "等待回执…"
                    : dialog?.kind === "generate"
                      ? "发送一次"
                      : "确认"}
                </button>
              </div>
            </form>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </div>
  );
}

function Inspector({
  node,
  state,
  age,
  onClose,
  actions,
}: {
  node: ViewNode;
  state: ClientState;
  age: number;
  onClose: () => void;
  actions: React.ReactNode;
}) {
  const status = node.status,
    last = status?.last_log_index || 0;
  return (
    <aside className="inspector" aria-label={`节点 ${node.id} 详情`}>
      <div className="inspector-heading">
        <span className="eyebrow">节点检查器</span>
        <button
          className="icon-button"
          aria-label="关闭节点详情"
          onClick={onClose}
        >
          <Icon name="close" />
        </button>
      </div>
      <div className="inspector-title">
        <h2>#{node.id}</h2>
        <span className={`role-tag ${node.role.toLowerCase()}`}>
          {node.role === "unknown" ? "角色未知" : node.role}
        </span>
      </div>
      <p className="node-availability">
        {
          {
            online: "当前可达",
            offline: "当前不可达",
            unknown: "当前状态未知",
            "identity-error": "身份不匹配",
          }[node.availability]
        }{" "}
        ·{" "}
        {Number.isFinite(age)
          ? `${Math.max(0, age).toFixed(1)}s 前采样`
          : "尚无样本"}
      </p>
      <dl className="node-fields">
        {[
          ["Term", status?.term],
          [
            "报告 Leader",
            status?.leader_id ? `#${status.leader_id}` : "未报告",
          ],
          ["LastLogIndex", status?.last_log_index],
          ["CommitIndex", status?.commit_index],
          ["LastApplied", status?.last_applied],
        ].map(([k, v]) => (
          <div key={k}>
            <dt>{k}</dt>
            <dd>{v ?? "—"}</dd>
          </div>
        ))}
      </dl>
      <div className="index-progress">
        <label>
          已提交
          <span>
            {status?.commit_index ?? "—"} / {last || "—"}
          </span>
        </label>
        <progress max={Math.max(1, last)} value={status?.commit_index || 0} />
        <label>
          已应用
          <span>
            {status?.last_applied ?? "—"} / {last || "—"}
          </span>
        </label>
        <progress max={Math.max(1, last)} value={status?.last_applied || 0} />
      </div>
      <div className="state-value">
        <span>状态机 x</span>
        <strong>{status?.x ?? "—"}</strong>
        <small>已应用算术命令 {status?.applied_commands ?? "—"}</small>
      </div>
      {node.role === "Leader" && (
        <p className="footnote">
          这是节点报告的本地角色。Follower 报告关系不代表复制 ACK 或多数派授权。
        </p>
      )}
      {node.sample?.error && (
        <details>
          <summary>节点诊断</summary>
          <p className="error-text">{node.sample.error}</p>
        </details>
      )}
      <div className="inspector-danger">
        <span className="eyebrow">进程操作</span>
        <div className="actions">{actions}</div>
        <p className="footnote">
          {state.bootstrap?.read_only_transport
            ? "当前入口禁止操作。"
            : "仅控制本会话持有的进程；恢复使用原配置与数据。"}
        </p>
      </div>
      <a className="text-link" href="/#logs">
        在日志实验室检查实际条目 →
      </a>
    </aside>
  );
}
