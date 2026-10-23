import type { ClientState, OperationKind, Scope } from "./types";

export function scopeOf(s: ClientState): Scope {
  return {
    controller_id: s.frame?.controller_id || s.bootstrap?.controller_id || "",
    session_id: s.frame?.session?.id || "",
    generation: s.frame?.generation || s.bootstrap?.generation || 1,
  };
}

export function scopeKey(scope: Scope): string {
  return [scope.controller_id, scope.session_id, scope.generation].join("/");
}

export function fresh(s: ClientState, now = Date.now()): boolean {
  const at = s.frame?.snapshot?.completed_at;
  const age =
    at && !at.startsWith("0001") ? (now - Date.parse(at)) / 1000 : Infinity;
  return (
    s.connected &&
    age < Math.max(5, ((s.bootstrap?.poll_ms || 1000) / 1000) * 3)
  );
}

export function actionReason(
  s: ClientState,
  kind: OperationKind,
  id?: number,
): string {
  const f = s.frame;
  const session = f?.session;
  if (!s.connected) return "连接中断，等待控制器重新连接";
  if (!s.bootstrap || s.bootstrap.controller_id !== f?.controller_id)
    return "正在确认控制器身份";
  if (s.bootstrap.read_only_transport)
    return "当前预览入口只允许查看，操作请使用本机控制台";
  if (s.pending) return "请求已发出，正在等待回执";
  if (kind === "enable_control")
    return !s.bootstrap.control_allowed
      ? "当前入口仅供查看，未开放会话控制"
      : f?.control_enabled
        ? "已启用控制"
        : "";
  if (kind === "cancel_experiment") {
    const op = f?.operations.find(
      (o) => o.kind === "experiment" && !o.ended_at,
    );
    return !f?.control_enabled
      ? "请先明确启用本机控制"
      : !op || op.result?.phase !== "running"
        ? "实验尚未进入可取消阶段"
        : op.state === "cancel_requested"
          ? "已请求取消"
          : "";
  }
  if (f?.busy) return "另一项任务正在进行";
  if (
    ![
      "verify",
      "verify_history",
      "checkpoint",
      "export",
      "select_session",
    ].includes(kind) &&
    !f?.control_enabled
  ) {
    return s.bootstrap.control_allowed
      ? "请先在会话设置明确启用本机控制"
      : "当前入口仅供查看，未开放会话控制";
  }
  if (["create_session", "select_session"].includes(kind)) return "";
  if (!session) return "请先创建或选择会话";
  if (
    ["generate", "verify", "verify_history", "checkpoint"].includes(kind) &&
    !fresh(s)
  )
    return "等待新鲜的节点观测";
  const node = f?.snapshot.nodes?.find((n) => n.id === id);
  if (kind === "stop" && !node?.owned) return "该节点不是本控制器持有的进程";
  if (kind === "stop_all" && !f?.snapshot.nodes?.some((n) => n.owned))
    return "没有本控制器持有的节点进程";
  if (["restart", "resume"].includes(kind) && !session.managed)
    return "外部会话请使用原启动入口恢复";
  if (kind === "restart" && node?.reachable) return "节点当前可达";
  if (kind === "verify_history" && !f?.checkpoint) return "请先保存历史检查点";
  if (kind === "experiment" && !s.bootstrap.experiment_dependencies?.ready)
    return "实验环境未就绪";
  return "";
}
