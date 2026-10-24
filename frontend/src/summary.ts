import { observe } from "./model";
import type { Observation, ViewNode } from "./model";
import type { ClientState, Integer } from "./types";

export interface RateWindow {
  scope: string;
  seq: number;
  completedAt: number;
  count: bigint | null;
  value: number | null;
}

function counter(value: Integer | null | undefined): bigint | null {
  if (typeof value === "number")
    return Number.isSafeInteger(value) && value >= 0 ? BigInt(value) : null;
  if (typeof value === "string" && /^\d+$/.test(value)) return BigInt(value);
  return null;
}

function scopeOf(state: ClientState): string {
  const frame = state.frame;
  return [
    frame?.controller_id || state.bootstrap?.controller_id || "",
    frame?.session?.id || "",
    frame?.generation ?? state.bootstrap?.generation ?? 1,
  ].join("/");
}

function freshnessLimit(state: ClientState): number {
  return Math.max(5000, (state.bootstrap?.poll_ms || 1000) * 3);
}

export function updateRate(
  previous: RateWindow | null,
  state: ClientState,
  now = Date.now(),
): RateWindow | null {
  const frame = state.frame;
  if (!frame?.session || !frame.snapshot) return null;
  const snapshot = frame.snapshot;
  const scope = scopeOf(state);
  const completedAt = Date.parse(snapshot.completed_at);
  const count = counter(snapshot.monitor_rpcs);
  const threshold = freshnessLimit(state);
  const valid =
    state.connected &&
    Number.isFinite(completedAt) &&
    completedAt > 0 &&
    now - completedAt < threshold &&
    snapshot.session_id === frame.session.id &&
    snapshot.generation === frame.generation;
  if (
    valid &&
    previous?.scope === scope &&
    previous.seq === snapshot.seq &&
    previous.completedAt === completedAt &&
    previous.count === count
  )
    return previous;
  const matchingPrevious =
    previous?.scope === scope &&
    previous.count !== null &&
    previous.seq < snapshot.seq &&
    previous.completedAt < completedAt &&
    completedAt - previous.completedAt <= threshold;
  let value: number | null = null;
  if (
    valid &&
    count !== null &&
    matchingPrevious &&
    previous &&
    count >= previous.count!
  ) {
    const delta = count - previous.count!;
    if (delta <= BigInt(Number.MAX_SAFE_INTEGER))
      value = Number(delta) / ((completedAt - previous.completedAt) / 1000);
  }
  return {
    scope,
    seq: snapshot.seq,
    completedAt,
    count: valid ? count : null,
    value,
  };
}

export interface Summary {
  leader: ViewNode | null;
  reachable: number | null;
  total: number;
  label: string;
  tone: "neutral" | "good" | "warning" | "danger";
  rate: number | null;
}

export function deriveSummary(
  state: ClientState,
  now: number,
  rate: RateWindow | null,
  observation = observe(state, now),
): Summary {
  const nodes = observation.nodes;
  const leaders = observation.leaders;
  const total = nodes.length;
  const matchingSnapshot =
    state.frame?.session?.id === state.frame?.snapshot.session_id &&
    state.frame?.generation === state.frame?.snapshot.generation;
  const reachable =
    observation.fresh && matchingSnapshot
      ? nodes.filter((node) => node.sample?.reachable).length
      : null;
  let label = "观察到 Leader";
  let tone: Summary["tone"] = "good";
  if (!state.bootstrap) {
    label = "正在连接控制器";
    tone = "neutral";
  } else if (!state.frame) {
    label = "等待首次观测";
    tone = "neutral";
  } else if (!state.frame.session) {
    label = "无活跃会话";
    tone = "neutral";
  } else if (!state.connected) {
    label = "连接中断";
    tone = "danger";
  } else if (!matchingSnapshot) {
    label = "等待当前会话采样";
    tone = "neutral";
  } else if (!observation.fresh) {
    label = "采样过期";
    tone = "warning";
  } else if (nodes.some((node) => node.availability === "identity-error")) {
    label = "身份异常";
    tone = "danger";
  } else if (
    nodes.some(
      (node) =>
        node.sample?.reachable &&
        (node.sample.error || node.sample.status?.error),
    )
  ) {
    label = "节点返回错误";
    tone = "danger";
  } else if (leaders.length > 1) {
    label = "观察到多个本地 Leader";
    tone = "warning";
  } else if (nodes.some((node) => node.role === "Candidate")) {
    label = "正在选举";
    tone = "warning";
  } else if (leaders.length === 0) {
    label = "尚未观察到 Leader";
    tone = "warning";
  } else if (reachable !== total) {
    label = "部分节点未响应";
    tone = "warning";
  } else {
    label = "观察到 Leader";
  }
  const currentRate =
    observation.fresh &&
    matchingSnapshot &&
    state.connected &&
    rate?.scope === scopeOf(state)
      ? rate.value
      : null;
  return {
    leader: matchingSnapshot && leaders.length === 1 ? leaders[0] : null,
    reachable,
    total,
    label,
    tone,
    rate: currentRate,
  };
}
