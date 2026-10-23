import type {
  Bootstrap,
  ClientState,
  Frame,
  NodeSample,
  NodeStatus,
  Session,
} from "../src/types";

export function session(memberIDs: number[] = [1, 2, 3]): Session {
  return {
    id: "session-a",
    name: "fixture",
    managed: true,
    batch_size: 128,
    created_at: "2026-01-01T00:00:00Z",
    config: {
      cluster_id: "cluster-a",
      nodes: memberIDs.map((id) => ({ id, addr: `127.0.0.1:${7000 + id}` })),
    },
  };
}

export function sample(
  id: number,
  overrides: Partial<NodeSample> = {},
): NodeSample {
  const status: NodeStatus = {
    id,
    state: id === 1 ? "Leader" : "Follower",
    term: 7,
    leader_id: 1,
    instance_id: `instance-${id}`,
    cluster_id: "cluster-a",
    membership_hash: "members-a",
    revision: 1,
    last_log_index: 10,
    commit_index: 10,
    last_applied: 10,
    committed_commands: 10,
    applied_commands: 10,
    x: id,
    log_hash: `log-${id}`,
    committed_hash: `commit-${id}`,
    dropped_events: 0,
  };
  return {
    id,
    reachable: true,
    identity_ok: true,
    owned: true,
    sampled_at: "2026-01-01T00:00:00Z",
    status,
    ...overrides,
  };
}

export function frame(
  memberIDs: number[] = [1, 2, 3],
  overrides: Partial<Frame> = {},
): Frame {
  const sessionData = session(memberIDs);
  return {
    controller_id: "controller-a",
    mode: "REAL",
    session: sessionData,
    generation: 1,
    snapshot: {
      session_id: sessionData.id,
      generation: 1,
      seq: 1,
      completed_at: new Date(1_000_000).toISOString(),
      nodes: memberIDs.map((id) => sample(id)),
      fingerprint: "snapshot-a",
      monitor_rpcs: memberIDs.length,
    },
    events: [],
    event_seq: 0,
    gap: false,
    stream_dropped: 0,
    operations: [],
    current_verification: {
      state: "not_run",
      kind: "",
      fingerprint: "",
      target: 0,
      at: "",
      completed_at: "",
    },
    history_verification: {
      state: "not_run",
      kind: "",
      fingerprint: "",
      target: 0,
      at: "",
      completed_at: "",
    },
    checkpoint: null,
    target: 10,
    control_enabled: true,
    busy: false,
    ...overrides,
  };
}

export function bootstrap(controller_id = "controller-a"): Bootstrap {
  return {
    controller_id,
    mode: "REAL",
    csrf_token: "csrf-a",
    session: null,
    sessions: [],
    generation: 1,
    control_allowed: true,
    control_enabled: true,
    poll_ms: 1000,
    network_partition_supported: false,
  };
}

export function clientState(
  memberIDs: number[] = [1, 2, 3],
  overrides: Partial<ClientState> = {},
): ClientState {
  const currentFrame = frame(memberIDs);
  return {
    bootstrap: bootstrap(),
    frame: currentFrame,
    connected: true,
    pending: false,
    pendingKind: null,
    error: "",
    unknownWrite: false,
    receipt: null,
    events: [],
    gap: false,
    dropped: 0,
    ...overrides,
  };
}
