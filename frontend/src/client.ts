import * as api from "./api";
import { actionReason, scopeKey, scopeOf } from "./actions";
import type {
  ClientState,
  Frame,
  OperationKind,
  OperationParams,
} from "./types";

export const initialState = (): ClientState => ({
  bootstrap: null,
  frame: null,
  connected: false,
  pending: false,
  pendingKind: null,
  error: "",
  unknownWrite: false,
  receipt: null,
  events: [],
  gap: false,
  dropped: 0,
});

// A single controller subscription belongs to the application, never to a renderer.
export class ConsoleClient {
  private state = initialState();
  private listeners = new Set<() => void>();
  private stream: EventSource | null = null;
  private retry: ReturnType<typeof setTimeout> | undefined;
  private epoch = 0;
  private bootstrapRequest = 0;
  private lastDrop = 0;
  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };
  getSnapshot = () => this.state;
  private set(patch: Partial<ClientState>) {
    this.state = { ...this.state, ...patch };
    for (const notify of this.listeners) notify();
  }
  start() {
    const epoch = ++this.epoch;
    const connect = async () => {
      try {
        const bootstrap = await api.bootstrap();
        if (this.epoch !== epoch) return;
        this.set({ bootstrap, error: "" });
        const stream = new EventSource("/api/events");
        this.stream = stream;
        stream.addEventListener("frame", (event) => {
          if (this.epoch !== epoch) return;
          try {
            this.receive(api.parseJSON<Frame>((event as MessageEvent).data));
          } catch (error) {
            this.set({
              connected: false,
              error: `快照解析失败：${(error as Error).message}`,
            });
          }
        });
        stream.onerror = () => {
          if (this.epoch === epoch) this.set({ connected: false });
        };
      } catch (error) {
        if (this.epoch !== epoch) return;
        this.set({ connected: false, error: (error as Error).message });
        this.retry = setTimeout(connect, 3000);
      }
    };
    void connect();
    return () => {
      ++this.epoch;
      ++this.bootstrapRequest;
      clearTimeout(this.retry);
      this.stream?.close();
      this.stream = null;
      this.set({ connected: false });
    };
  }
  private async refreshBootstrap(controller: string) {
    const request = ++this.bootstrapRequest;
    try {
      const bootstrap = await api.bootstrap();
      if (
        request === this.bootstrapRequest &&
        bootstrap.controller_id === controller &&
        this.state.frame?.controller_id === controller
      )
        this.set({ bootstrap });
    } catch (error) {
      if (
        request === this.bootstrapRequest &&
        this.state.frame?.controller_id === controller
      )
        this.set({ error: (error as Error).message });
    }
  }
  receive(frame: Frame) {
    if (frame.mode !== "REAL") return;
    const previous = this.state.frame;
    if (previous?.controller_id === frame.controller_id) {
      if (frame.generation < previous.generation) return;
      if (
        frame.generation === previous.generation &&
        frame.snapshot.seq < previous.snapshot.seq
      )
        return;
    }
    const changed =
      !previous ||
      scopeKey(scopeOf({ ...this.state, frame })) !==
        scopeKey(scopeOf(this.state));
    if (changed) this.lastDrop = 0;
    const events = changed ? [] : [...this.state.events];
    const known = new Set(events.map((e) => e.seq));
    for (const event of frame.events || [])
      if (!known.has(event.seq)) {
        events.push(event);
        known.add(event.seq);
      }
    const dropped = frame.stream_dropped || 0;
    this.set({
      frame,
      connected: true,
      events: events.slice(-512),
      gap: (changed ? false : this.state.gap) || frame.gap,
      dropped:
        (changed ? 0 : this.state.dropped) +
        (dropped >= this.lastDrop ? dropped - this.lastDrop : dropped),
      ...(changed ? { receipt: null, error: "", unknownWrite: false } : {}),
    });
    this.lastDrop = dropped;
    if (changed || this.state.bootstrap?.controller_id !== frame.controller_id)
      void this.refreshBootstrap(frame.controller_id);
  }
  async execute(
    kind: OperationKind,
    params: OperationParams = {},
    expected = scopeOf(this.state),
  ) {
    const reason = actionReason(this.state, kind, params.node_id);
    if (reason) throw new Error(reason);
    if (scopeKey(expected) !== scopeKey(scopeOf(this.state)))
      throw new Error("会话已变化，请重新确认操作。");
    const sent = scopeKey(expected);
    this.set({
      pending: true,
      pendingKind: kind,
      error: "",
      unknownWrite: false,
    });
    try {
      const receipt = await api.operate(
        kind,
        expected,
        this.state.bootstrap!.csrf_token,
        params,
      );
      const current = scopeOf(this.state);
      if (
        "id" in receipt &&
        current.controller_id === expected.controller_id &&
        (sent === scopeKey(current) ||
          (["create_session", "select_session"].includes(kind) &&
            receipt.session_id === current.session_id &&
            receipt.generation === current.generation))
      )
        this.set({ receipt });
      return receipt;
    } catch (error) {
      if (sent === scopeKey(scopeOf(this.state)))
        this.set({
          error: (error as Error).message,
          unknownWrite:
            !(error instanceof api.HttpError) ||
            !error.status ||
            error.status >= 500,
        });
      throw error;
    } finally {
      this.set({ pending: false, pendingKind: null });
    }
  }
  dismissError = () => this.set({ error: "", unknownWrite: false });
}
