import { fresh } from "./actions";
import type { ClientState, NodeSample, NodeStatus, Role } from "./types";

export interface ViewNode {
  id: number;
  role: Role | "unknown";
  availability: "online" | "offline" | "unknown" | "identity-error";
  status: NodeStatus | null;
  sample?: NodeSample;
}
export interface Relation {
  id: string;
  from: number;
  to: number;
  term: number;
}
export interface Observation {
  nodes: ViewNode[];
  relations: Relation[];
  leaders: ViewNode[];
  fresh: boolean;
  notice: string;
}
export function observe(state: ClientState, now = Date.now()): Observation {
  const current = fresh(state, now),
    samples = new Map(
      (state.frame?.snapshot.nodes || []).map((n) => [n.id, n]),
    );
  const nodes: ViewNode[] = (state.frame?.session?.config.nodes || [])
    .map((member): ViewNode => {
      const sample = samples.get(member.id);
      const status = sample?.status;
      const valid =
        current &&
        sample?.reachable &&
        sample.identity_ok &&
        !sample.error &&
        status &&
        !status.error;
      return {
        id: member.id,
        sample,
        status: valid ? status : null,
        role: valid ? status.state : ("unknown" as const),
        availability:
          !current || !sample
            ? "unknown"
            : !sample.reachable
              ? "offline"
              : !sample.identity_ok
                ? "identity-error"
                : valid
                  ? "online"
                  : "unknown",
      };
    })
    .sort((a, b) => a.id - b.id);
  const leaders = nodes.filter((n) => n.role === "Leader");
  const byID = new Map(nodes.map((n) => [n.id, n]));
  const relations = nodes.flatMap((n) => {
    const status = n.status,
      leader = status && byID.get(status.leader_id);
    return n.role === "Follower" &&
      leader?.role === "Leader" &&
      status?.term === leader.status?.term
      ? [
          {
            id: `${n.id}/${leader.id}/${status!.term}`,
            from: n.id,
            to: leader.id,
            term: status!.term,
          },
        ]
      : [];
  });
  const candidates = nodes.filter((n) => n.role === "Candidate");
  const notice = !state.bootstrap
    ? "正在连接控制器…"
    : !state.frame
      ? "等待首次节点观测…"
      : !state.connected
        ? "连接中断 · 当前状态未知"
        : !state.frame.session
          ? "创建或选择一个固定成员会话"
          : !current
            ? "样本过期 · 等待新鲜观测"
            : leaders.length > 1
              ? "观察到多个本地 Leader"
              : leaders.length === 1
                ? ""
                : candidates.length
                  ? `正在选举 · Term ${Math.max(...candidates.map((n) => n.status!.term))}`
                  : "尚未观察到 Leader";
  return { nodes, relations, leaders, fresh: current, notice };
}

export interface CenterState {
  scope: string;
  key: string;
  seq: number;
  count: number;
  confirmed: number | null;
  display: number | null;
  seeded: boolean;
}
export const initialCenter = (): CenterState => ({
  scope: "",
  key: "",
  seq: -1,
  count: 0,
  confirmed: null,
  display: null,
  seeded: false,
});
export function updateCenter(
  previous: CenterState,
  observation: Observation,
  scope: string,
  seq: number,
): CenterState {
  let result =
    previous.scope === scope ? { ...previous } : { ...initialCenter(), scope };
  const leader =
    observation.leaders.length === 1 ? observation.leaders[0] : null;
  if (!leader) return { ...result, key: "", count: 0, display: null };
  const key = `${leader.id}/${leader.status!.instance_id}/${leader.status!.term}`;
  if (key !== result.key)
    result = { ...result, key, count: 1, seq, confirmed: null };
  else if (seq > result.seq)
    result = { ...result, count: result.count + 1, seq };
  if (result.count >= 2) result.confirmed = leader.id;
  // Only the first view may seed a center. Later terms require two distinct
  // snapshots; an invalid former leader never remains in the center meanwhile.
  result.display =
    !result.seeded ||
    result.confirmed === leader.id ||
    result.display === leader.id
      ? leader.id
      : null;
  result.seeded = true;
  return result;
}
