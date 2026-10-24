export type Integer = number | string;
export type Role = "Follower" | "Candidate" | "Leader";
export interface NodeStatus {
  id: number;
  state: Role;
  term: number;
  leader_id: number;
  instance_id: string;
  cluster_id: string;
  membership_hash: string;
  revision: Integer;
  last_log_index: number;
  commit_index: number;
  last_applied: number;
  committed_commands: number;
  applied_commands: number;
  x: Integer;
  log_hash: string;
  committed_hash: string;
  dropped_events: Integer;
  target_index?: number;
  target_hash?: string;
  target_x?: Integer;
  target_available?: boolean;
  error?: string;
}
export interface NodeSample {
  id: number;
  reachable: boolean;
  identity_ok: boolean;
  owned: boolean;
  sampled_at: string;
  status: NodeStatus | null;
  error?: string;
}
export interface Session {
  id: string;
  name: string;
  managed: boolean;
  batch_size: number;
  created_at: string;
  config: { cluster_id: string; nodes: { id: number; addr: string }[] };
}
export interface Snapshot {
  session_id: string;
  generation: number;
  seq: number;
  completed_at: string;
  nodes: NodeSample[] | null;
  fingerprint: string;
  monitor_rpcs: Integer;
}
export interface Checkpoint {
  index: number;
  hash: string;
  x: Integer;
  saved_at: string;
}
export interface Verification {
  state: string;
  kind: string;
  fingerprint: string;
  target: number;
  at: string;
  completed_at: string;
  error?: string;
}
export type OperationKind =
  | "enable_control"
  | "create_session"
  | "select_session"
  | "generate"
  | "verify"
  | "checkpoint"
  | "verify_history"
  | "stop"
  | "restart"
  | "stop_all"
  | "resume"
  | "export"
  | "experiment"
  | "cancel_experiment";
export interface Operation {
  id: string;
  session_id: string;
  generation: number;
  kind: OperationKind;
  state: string;
  created_at: string;
  ended_at?: string;
  accepted: boolean | null;
  committed: boolean | null;
  result?: Record<string, unknown>;
  error?: string;
}
export interface ConsoleEvent {
  seq: number;
  received_at: string;
  source: string;
  session_id: string;
  node_id?: number;
  name: string;
  message: string;
  operation_id?: string;
}
export interface Frame {
  controller_id: string;
  mode: "REAL";
  session: Session | null;
  generation: number;
  snapshot: Snapshot;
  events: ConsoleEvent[];
  event_seq: number;
  gap: boolean;
  stream_dropped: number;
  operations: Operation[];
  current_verification: Verification;
  history_verification: Verification;
  checkpoint: Checkpoint | null;
  target: number;
  control_enabled: boolean;
  busy: boolean;
}
export interface Bootstrap {
  controller_id: string;
  mode: "REAL";
  csrf_token: string;
  session: Session | null;
  sessions: Session[];
  generation: number;
  control_allowed: boolean;
  control_enabled: boolean;
  poll_ms: number;
  read_only_transport?: boolean;
  network_partition_supported: boolean;
  experiment_dependencies?: { ready: boolean; [key: string]: unknown };
}
export interface Scope {
  controller_id: string;
  session_id: string;
  generation: number;
}
export interface OperationParams {
  node_id?: number;
  confirm?: boolean;
  name?: string;
  nodes?: number[];
  count?: number;
  seed?: number;
  batch?: number;
  rounds?: number;
  scenarios?: string[];
  select_session?: string;
  operation_id?: string;
}
export interface ClientState {
  bootstrap: Bootstrap | null;
  frame: Frame | null;
  connected: boolean;
  pending: boolean;
  pendingKind: OperationKind | null;
  error: string;
  unknownWrite: boolean;
  receipt: Operation | null;
  events: ConsoleEvent[];
  gap: boolean;
  dropped: number;
}
export type RendererKind = "svg" | "flow" | "compare";
